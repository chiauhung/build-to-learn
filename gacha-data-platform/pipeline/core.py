"""Main pipeline entry point for the Gacha CDC streaming pipeline.

Flow:
    PubSub → Decode → Validate (DLQ on fail) → Transform → Bronze write

Silver/Gold transforms are handled by dbt (not in the pipeline).

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
from apache_beam.io.gcp.pubsub import ReadFromPubSub, WriteToPubSub
from apache_beam.options.pipeline_options import StandardOptions

from pipeline.options import GachaOptions
from pipeline.transforms import (
    FAILURE_TAG,
    DecodeMessage,
    TransformCDC,
    ValidateCDC,
)
from pipeline.warehouse import init_bronze_tables, write_bronze

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bronze write DoFn
# ---------------------------------------------------------------------------


class WriteToBronzeDoFn(beam.DoFn):
    """Write a normalized CDC record to the Bronze warehouse layer.

    Routes to DuckDB (local) or BigQuery (GCP) via the warehouse module.
    """

    def __init__(self) -> None:
        self._count = 0

    def process(self, element: dict, *args, **kwargs):  # type: ignore[override]
        row = {
            **element,
            "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        table_name = element["source_table"]

        try:
            write_bronze(table_name=table_name, rows=[row])
            self._count += 1
            if self._count % 100 == 0:
                logger.info("Bronze: %d records written (latest: %s)", self._count, table_name)
        except Exception as exc:
            logger.error("Bronze write failed for %s — %s", table_name, exc)

        yield element


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
    input_subscription: str = gacha_opts.input_subscription
    dlq_topic: str = gacha_opts.dlq_topic

    # Ensure Bronze tables exist in DuckDB
    init_bronze_tables()

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
        # Silver/Gold transforms are handled by dbt, not the pipeline.
        _ = transformed | "WriteToBronze" >> beam.ParDo(WriteToBronzeDoFn())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("apache_beam").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger.info("Starting Gacha CDC pipeline (streaming, Ctrl+C to stop)")
    run()
