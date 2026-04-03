"""Unit tests for pipeline/transforms.py.

Most DoFns are tested by calling .process() directly — cheap and fast.
Where the Beam test harness adds clarity (tagged outputs) we use TestPipeline
+ assert_that.
"""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import apache_beam as beam
import pytest
from apache_beam.testing.test_pipeline import TestPipeline
from apache_beam.testing.util import assert_that, equal_to

from pipeline.transforms import (
    FAILURE_TAG,
    UPSERT_TAG,
    DecodeMessage,
    KeyByTable,
    SegregateByEvent,
    TransformCDC,
    ValidateCDC,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_debezium(
    op: str = "c",
    table: str = "pulls",
    schema: str = "public",
    after: dict | None = None,
    before: dict | None = None,
    ts_ms: int = 1_700_000_000_000,
) -> dict:
    """Build a minimal Debezium-style CDC message dict."""
    if after is None and op != "d":
        after = {"id": "row-1", "player_id": "player-uuid", "rarity": "SSR"}
    if before is None and op == "d":
        before = {"id": "row-1", "player_id": "player-uuid", "rarity": "SSR"}

    return {
        "payload": {
            "before": before,
            "after": after,
            "source": {"schema": schema, "table": table},
            "op": op,
            "ts_ms": ts_ms,
        }
    }


def _process(dofn: beam.DoFn, element: Any) -> list[Any]:
    """Collect all outputs from a single DoFn.process() call into a list."""
    return list(dofn.process(element))


# ---------------------------------------------------------------------------
# DecodeMessage
# ---------------------------------------------------------------------------


class TestDecodeMessage:
    def test_decode_message(self):
        msg_dict = {"payload": {"op": "c", "after": {"id": "1"}}}
        raw = json.dumps(msg_dict).encode("utf-8")

        # Wrap bytes in a mock that mimics a PubsubMessage with .data attribute
        mock_msg = MagicMock()
        mock_msg.data = raw

        results = _process(DecodeMessage(), mock_msg)

        assert len(results) == 1
        assert results[0] == msg_dict

    def test_decode_message_plain_bytes(self):
        """Should also accept plain bytes (no .data wrapper)."""
        msg_dict = {"hello": "world"}
        raw = json.dumps(msg_dict).encode("utf-8")

        results = _process(DecodeMessage(), raw)
        assert results == [msg_dict]

    def test_decode_message_invalid(self):
        """Malformed JSON should be dropped silently (returns nothing)."""
        results = _process(DecodeMessage(), b"not-json{{{")
        assert results == []

    def test_decode_message_invalid_utf8(self):
        """Invalid UTF-8 should also be dropped."""
        results = _process(DecodeMessage(), b"\xff\xfe")
        assert results == []


# ---------------------------------------------------------------------------
# ValidateCDC
# ---------------------------------------------------------------------------


class TestValidateCDC:
    def _successes(self, element: dict) -> list[dict]:
        return [r for r in ValidateCDC().process(element) if not isinstance(r, beam.pvalue.TaggedOutput)]

    def _failures(self, element: dict) -> list[beam.pvalue.TaggedOutput]:
        return [r for r in ValidateCDC().process(element) if isinstance(r, beam.pvalue.TaggedOutput)]

    def test_validate_cdc_success(self):
        element = _make_debezium(op="c")
        successes = self._successes(element)
        failures = self._failures(element)

        assert len(successes) == 1
        assert len(failures) == 0

    def test_validate_cdc_delete_uses_before(self):
        element = _make_debezium(op="d")
        successes = self._successes(element)
        assert len(successes) == 1

    def test_validate_cdc_missing_payload(self):
        element = {"not_payload": {}}
        failures = self._failures(element)
        assert len(failures) == 1
        assert failures[0].tag == FAILURE_TAG
        assert "missing payload" in failures[0].value["reason"]

    def test_validate_cdc_missing_op(self):
        element = _make_debezium(op="c")
        del element["payload"]["op"]
        failures = self._failures(element)
        assert len(failures) == 1
        assert "missing payload.op" in failures[0].value["reason"]

    def test_validate_cdc_missing_after_for_insert(self):
        element = _make_debezium(op="c")
        element["payload"]["after"] = None
        failures = self._failures(element)
        assert len(failures) == 1

    def test_validate_cdc_missing_before_for_delete(self):
        element = _make_debezium(op="d")
        element["payload"]["before"] = None
        failures = self._failures(element)
        assert len(failures) == 1


# ---------------------------------------------------------------------------
# TransformCDC
# ---------------------------------------------------------------------------


class TestTransformCDC:
    def _transform(self, element: dict) -> dict:
        results = _process(TransformCDC(), element)
        assert len(results) == 1
        return results[0]

    def test_transform_cdc_insert(self):
        element = _make_debezium(op="c", table="pulls")
        result = self._transform(element)

        assert result["event"] == "insert"
        assert result["source_table"] == "pulls"
        assert result["source_schema"] == "public"
        assert result["id"] == "row-1"
        assert json.loads(result["data"])["id"] == "row-1"

    def test_transform_cdc_snapshot_is_insert(self):
        element = _make_debezium(op="r", table="players")
        result = self._transform(element)
        assert result["event"] == "insert"

    def test_transform_cdc_update(self):
        element = _make_debezium(op="u", table="player_pity")
        result = self._transform(element)
        assert result["event"] == "update"

    def test_transform_cdc_delete(self):
        element = _make_debezium(op="d", table="player_inventory")
        result = self._transform(element)

        assert result["event"] == "delete"
        # Delete uses ``before``, which also has id="row-1"
        assert result["id"] == "row-1"

    def test_transform_cdc_event_timestamp_is_iso(self):
        element = _make_debezium(op="c", ts_ms=1_700_000_000_000)
        result = self._transform(element)
        # Should parse without error
        from datetime import datetime
        dt = datetime.fromisoformat(result["event_timestamp"])
        assert dt.year == 2023  # 1700000000 epoch = Nov 2023

    def test_transform_cdc_data_is_json_string(self):
        element = _make_debezium(op="c")
        result = self._transform(element)
        parsed = json.loads(result["data"])
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# SegregateByEvent
# ---------------------------------------------------------------------------


class TestSegregateByEvent:
    def _segregate(self, event: str):
        element = {"event": event, "id": "x", "source_table": "pulls"}
        return list(SegregateByEvent().process(element))

    def test_segregate_upsert_insert(self):
        outputs = self._segregate("insert")
        assert len(outputs) == 1
        tagged = outputs[0]
        assert isinstance(tagged, beam.pvalue.TaggedOutput)
        assert tagged.tag == UPSERT_TAG

    def test_segregate_upsert_update(self):
        outputs = self._segregate("update")
        tagged = outputs[0]
        assert tagged.tag == UPSERT_TAG

    def test_segregate_delete(self):
        outputs = self._segregate("delete")
        assert len(outputs) == 1
        # Main output is a plain dict, not a TaggedOutput
        result = outputs[0]
        assert not isinstance(result, beam.pvalue.TaggedOutput)
        assert result["event"] == "delete"


# ---------------------------------------------------------------------------
# KeyByTable
# ---------------------------------------------------------------------------


class TestKeyByTable:
    def test_key_by_table(self):
        element = {"source_table": "pulls", "id": "row-1", "event": "insert"}
        results = _process(KeyByTable(), element)

        assert len(results) == 1
        key, value = results[0]
        assert key == "pulls"
        assert value == element

    def test_key_by_table_different_tables(self):
        tables = ["pulls", "transactions", "player_pity"]
        for table in tables:
            element = {"source_table": table, "id": "x"}
            key, _ = _process(KeyByTable(), element)[0]
            assert key == table
