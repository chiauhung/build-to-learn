"""Apache Beam DoFns for the Gacha CDC streaming pipeline.

Each transform is a separate class to mirror production patterns and keep
each step independently testable.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import apache_beam as beam
from apache_beam import pvalue

logger = logging.getLogger(__name__)

# TaggedOutput labels
FAILURE_TAG = "failure"
UPSERT_TAG = "upsert"

# Debezium op codes → our event names
_OP_MAP: dict[str, str] = {
    "c": "insert",   # create
    "r": "insert",   # read (snapshot)
    "u": "update",   # update
    "d": "delete",   # delete
}

# Required top-level fields in a Debezium payload
_REQUIRED_PAYLOAD_FIELDS = ("op", "source", "ts_ms")


class DecodeMessage(beam.DoFn):
    """Decode raw PubSub message bytes into a Python dict.

    Expects UTF-8 encoded JSON. Emits the decoded dict on success.
    Logs and drops messages that cannot be decoded — they are unrecoverable
    (we cannot even route them to DLQ without a valid structure).
    """

    def process(self, element: Any, *args, **kwargs):  # type: ignore[override]
        # element is a PubsubMessage when with_attributes=True
        raw_data: bytes = element.data if hasattr(element, "data") else element

        try:
            decoded = json.loads(raw_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error("DecodeMessage: cannot decode message — %s", exc)
            return  # drop; nothing useful we can do

        yield decoded


class ValidateCDC(beam.DoFn):
    """Validate a decoded Debezium message.

    Routes valid messages to the main output and invalid ones to the
    ``failure`` TaggedOutput so they can be forwarded to the DLQ.

    A message is valid when:
    - It has a ``payload`` key.
    - ``payload`` contains ``op``, ``source``, and ``ts_ms``.
    - ``payload.source`` contains ``table`` and ``schema``.
    - For non-delete ops (c/r/u): ``payload.after`` is present and non-null.
    - For delete ops (d): ``payload.before`` is present and non-null.
    """

    def process(self, element: dict, *args, **kwargs):  # type: ignore[override]
        failure_reason = self._validate(element)

        if failure_reason:
            logger.warning("ValidateCDC: invalid message — %s | %s", failure_reason, element)
            yield pvalue.TaggedOutput(
                FAILURE_TAG,
                {
                    "reason": failure_reason,
                    "raw": json.dumps(element),
                },
            )
        else:
            yield element

    @staticmethod
    def _validate(element: dict) -> str | None:
        """Return a failure reason string, or None if the message is valid."""
        payload = element.get("payload")
        if not payload:
            return "missing payload"

        for field in _REQUIRED_PAYLOAD_FIELDS:
            if field not in payload:
                return f"missing payload.{field}"

        source = payload.get("source")
        if not isinstance(source, dict):
            return "payload.source is not an object"
        if "table" not in source:
            return "missing payload.source.table"
        if "schema" not in source:
            return "missing payload.source.schema"

        op = payload.get("op")
        if op == "d":
            if not payload.get("before"):
                return "delete event missing payload.before"
        else:
            if not payload.get("after"):
                return f"op={op!r} missing payload.after"

        return None


class TransformCDC(beam.DoFn):
    """Normalize a Debezium CDC message into our pipeline schema.

    Input (Debezium):
        {
            "payload": {
                "before": {...} | null,
                "after":  {...} | null,
                "source": {"schema": "public", "table": "pulls", ...},
                "op": "c" | "u" | "d" | "r",
                "ts_ms": 1234567890
            }
        }

    Output (normalized):
        {
            "id":               "<primary key value>",
            "data":             "<JSON string of the after/before payload>",
            "event":            "insert" | "update" | "delete",
            "event_timestamp":  "2024-01-01T00:00:00+00:00",
            "source_table":     "pulls",
            "source_schema":    "public",
        }
    """

    def process(self, element: dict, *args, **kwargs):  # type: ignore[override]
        payload = element["payload"]
        op: str = payload["op"]
        source: dict = payload["source"]

        event = _OP_MAP.get(op, "insert")

        # For deletes, reconstruct from ``before``; otherwise use ``after``.
        row_data: dict = payload["after"] if op != "d" else payload["before"]

        # Best-effort primary key extraction: try ``id`` first (all our tables
        # have it), then fall back to a stringified composite of all values.
        row_id: str = str(row_data.get("id", json.dumps(row_data, sort_keys=True)))

        ts_ms: int = payload["ts_ms"]
        event_timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()

        yield {
            "id": row_id,
            "data": json.dumps(row_data),
            "event": event,
            "event_timestamp": event_timestamp,
            "source_table": source["table"],
            "source_schema": source["schema"],
        }


class SegregateByEvent(beam.DoFn):
    """Route CDC records to upsert or delete outputs.

    - ``upsert`` TaggedOutput: insert + update events
    - main output:             delete events
    """

    def process(self, element: dict, *args, **kwargs):  # type: ignore[override]
        if element["event"] in ("insert", "update"):
            yield pvalue.TaggedOutput(UPSERT_TAG, element)
        else:
            yield element  # delete → main output


class KeyByTable(beam.DoFn):
    """Emit ``(source_table, element)`` pairs for GroupByKey windowing.

    Keying by table lets us batch merges per table after the window fires,
    so the MERGE SQL only touches one table at a time.
    """

    def process(self, element: dict, *args, **kwargs):  # type: ignore[override]
        yield (element["source_table"], element)
