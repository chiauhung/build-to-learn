"""Main pipeline entry point for the Gacha CDC streaming pipeline.

Flow:
    PubSub → Decode → Validate (DLQ on fail) → Transform
          → Bronze write
          → Segregate upsert/delete
          → Windowed GroupByKey → MergeToSilver | DeleteFromSilver

Run locally with DirectRunner:

    uv run python -m pipeline.core \\
        --runner DirectRunner \\
        --input_subscription projects/gacha-local/subscriptions/cdc-sub \\
        --dlq_topic projects/gacha-local/topics/cdc-dlq \\
        --streaming
"""

import json
import logging
from datetime import datetime, timezone

import apache_beam as beam
from apache_beam import pvalue
from apache_beam.io.gcp.pubsub import ReadFromPubSub, WriteToPubSub
from apache_beam.options.pipeline_options import StandardOptions
from apache_beam.transforms.trigger import (
    AccumulationMode,
    AfterProcessingTime,
    Repeatedly,
)
from apache_beam.transforms.window import GlobalWindows

from pipeline.bigquery import delete_from_silver, merge_to_silver, write_to_bronze
from pipeline.options import GachaOptions
from pipeline.transforms import (
    FAILURE_TAG,
    UPSERT_TAG,
    DecodeMessage,
    KeyByTable,
    SegregateByEvent,
    TransformCDC,
    ValidateCDC,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Silver merge DoFns (called after windowed GroupByKey)
# ---------------------------------------------------------------------------


class MergeToSilver(beam.DoFn):
    """Execute MERGE SQL for a batch of upsert records from one table.

    Receives ``table_name`` (the GroupByKey key) and calls ``merge_to_silver``.
    The actual rows have already been written to Bronze staging — this step
    just fires the MERGE query.
    """

    def __init__(self, project_id: str, endpoint: str) -> None:
        self._project_id = project_id
        self._endpoint = endpoint

    def process(self, table_name: str, *args, **kwargs):  # type: ignore[override]
        try:
            merge_to_silver(
                table_name=table_name,
                project_id=self._project_id,
                endpoint=self._endpoint,
            )
        except Exception as exc:
            logger.error("MergeToSilver: failed for table %s — %s", table_name, exc)
        return []


class DeleteFromSilver(beam.DoFn):
    """Execute DELETE SQL for a batch of delete records from one table."""

    def __init__(self, project_id: str, endpoint: str) -> None:
        self._project_id = project_id
        self._endpoint = endpoint

    def process(self, table_name: str, *args, **kwargs):  # type: ignore[override]
        try:
            delete_from_silver(
                table_name=table_name,
                project_id=self._project_id,
                endpoint=self._endpoint,
            )
        except Exception as exc:
            logger.error("DeleteFromSilver: failed for table %s — %s", table_name, exc)
        return []


# ---------------------------------------------------------------------------
# Bronze write DoFn
# ---------------------------------------------------------------------------


class WriteToBronzeDoFn(beam.DoFn):
    """Write a single normalized CDC record to the Bronze BigQuery table.

    Adds ``ingested_at`` before writing so the Bronze row records when it
    was received by the pipeline.
    """

    def __init__(self, project_id: str, endpoint: str) -> None:
        self._project_id = project_id
        self._endpoint = endpoint

    def process(self, element: dict, *args, **kwargs):  # type: ignore[override]
        row = {
            **element,
            "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        table_name = element["source_table"]

        try:
            write_to_bronze(
                table_name=table_name,
                rows=[row],
                project_id=self._project_id,
                endpoint=self._endpoint,
            )
        except Exception as exc:
            logger.error("WriteToBronze: failed for table %s — %s", table_name, exc)

        yield element  # pass through for downstream steps


# ---------------------------------------------------------------------------
# DLQ serialisation helper
# ---------------------------------------------------------------------------


def _serialise_for_dlq(element: dict) -> bytes:
    """Encode a DLQ failure dict as UTF-8 JSON bytes for WriteToPubSub."""
    return json.dumps(element, default=str).encode("utf-8")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run(argv: list[str] | None = None) -> None:
    """Build and run the Gacha CDC pipeline."""
    options = GachaOptions(flags=argv)
    options.view_as(StandardOptions).streaming = True

    gacha_opts = options.view_as(GachaOptions)
    project_id: str = gacha_opts.project_id
    input_subscription: str = gacha_opts.input_subscription
    dlq_topic: str = gacha_opts.dlq_topic
    merge_window_minutes: int = gacha_opts.merge_window_minutes
    bq_endpoint: str = gacha_opts.bigquery_endpoint

    merge_trigger = Repeatedly(
        AfterProcessingTime(delay=merge_window_minutes * 60)
    )

    with beam.Pipeline(options=options) as p:
        # ── 1. Read ──────────────────────────────────────────────────────────
        raw = p | "ReadFromPubSub" >> ReadFromPubSub(
            subscription=input_subscription,
            with_attributes=True,
        )

        # ── 2. Decode ────────────────────────────────────────────────────────
        decoded = raw | "Decode" >> beam.ParDo(DecodeMessage())

        # ── 3. Validate → DLQ on failure ─────────────────────────────────────
        validated = decoded | "Validate" >> beam.ParDo(ValidateCDC()).with_outputs(
            FAILURE_TAG, main="success"
        )

        # Route failures to the DLQ topic.
        (
            validated[FAILURE_TAG]
            | "SerialiseFailures" >> beam.Map(_serialise_for_dlq)
            | "WriteToDLQ" >> WriteToPubSub(topic=dlq_topic)
        )

        # ── 4. Transform ─────────────────────────────────────────────────────
        transformed = validated["success"] | "Transform" >> beam.ParDo(TransformCDC())

        # ── 5. Write to Bronze ───────────────────────────────────────────────
        bronze_out = transformed | "WriteToBronze" >> beam.ParDo(
            WriteToBronzeDoFn(project_id=project_id, endpoint=bq_endpoint)
        )

        # ── 6. Segregate upsert vs delete ────────────────────────────────────
        segregated = bronze_out | "Segregate" >> beam.ParDo(
            SegregateByEvent()
        ).with_outputs(UPSERT_TAG, main="delete")

        # ── 7. Windowed upsert → MERGE Silver ────────────────────────────────
        (
            segregated[UPSERT_TAG]
            | "KeyUpsertByTable"   >> beam.ParDo(KeyByTable())
            | "WindowUpsert"       >> beam.WindowInto(
                GlobalWindows(),
                trigger=merge_trigger,
                accumulation_mode=AccumulationMode.DISCARDING,
            )
            | "GroupUpsert"        >> beam.GroupByKey()
            | "UpsertTableKeys"    >> beam.Keys()
            | "MergeToSilver"      >> beam.ParDo(
                MergeToSilver(project_id=project_id, endpoint=bq_endpoint)
            )
        )

        # ── 8. Windowed delete → DELETE Silver ───────────────────────────────
        (
            segregated["delete"]
            | "KeyDeleteByTable"   >> beam.ParDo(KeyByTable())
            | "WindowDelete"       >> beam.WindowInto(
                GlobalWindows(),
                trigger=merge_trigger,
                accumulation_mode=AccumulationMode.DISCARDING,
            )
            | "GroupDelete"        >> beam.GroupByKey()
            | "DeleteTableKeys"    >> beam.Keys()
            | "DeleteFromSilver"   >> beam.ParDo(
                DeleteFromSilver(project_id=project_id, endpoint=bq_endpoint)
            )
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
