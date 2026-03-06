"""
Redis-backed store for level-6.

Drop-in replacement for level-5's in-memory store.
The interface is identical — only this file changes.

Keys:
  session:{session_id}   → JSON: {deps_config, messages}
  approval:{approval_id} → JSON: {session_id, approvals, messages}

TTL: 24h for sessions, 1h for approvals.

Start Redis:
  docker run -d -p 6379:6379 redis:7-alpine
"""

import json
import uuid
from typing import Any

import redis
from pydantic_ai.messages import ModelMessagesTypeAdapter

_redis = redis.Redis(host="localhost", port=6379, decode_responses=True)

SESSION_TTL = 60 * 60 * 24   # 24 hours
APPROVAL_TTL = 60 * 60       # 1 hour


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
# pydantic-ai messages are pydantic models — they serialize to JSON via
# ModelMessagesTypeAdapter, and deserialize back cleanly.


def _serialize_messages(messages: list) -> str:
    return ModelMessagesTypeAdapter.dump_json(messages).decode()


def _deserialize_messages(raw: str) -> list:
    return ModelMessagesTypeAdapter.validate_json(raw)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def session_create(deps_config: dict) -> str:
    session_id = str(uuid.uuid4())[:8]
    payload = {"deps_config": deps_config, "messages_json": "[]"}
    _redis.setex(f"session:{session_id}", SESSION_TTL, json.dumps(payload))
    return session_id


def session_get(session_id: str) -> dict[str, Any] | None:
    raw = _redis.get(f"session:{session_id}")
    if not raw:
        return None
    payload = json.loads(raw)
    return {
        "deps_config": payload["deps_config"],
        "messages": _deserialize_messages(payload["messages_json"]),
    }


def session_update_messages(session_id: str, messages: list) -> None:
    raw = _redis.get(f"session:{session_id}")
    if not raw:
        return
    payload = json.loads(raw)
    payload["messages_json"] = _serialize_messages(messages)
    _redis.setex(f"session:{session_id}", SESSION_TTL, json.dumps(payload))


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


def approval_save(session_id: str, messages: list, approvals: list[dict]) -> str:
    approval_id = str(uuid.uuid4())[:8]
    payload = {
        "session_id": session_id,
        "approvals": approvals,
        "messages_json": _serialize_messages(messages),
    }
    _redis.setex(f"approval:{approval_id}", APPROVAL_TTL, json.dumps(payload))
    return approval_id


def approval_get(approval_id: str) -> dict[str, Any] | None:
    raw = _redis.get(f"approval:{approval_id}")
    if not raw:
        return None
    payload = json.loads(raw)
    return {
        "session_id": payload["session_id"],
        "approvals": payload["approvals"],
        "messages": _deserialize_messages(payload["messages_json"]),
    }


def approval_delete(approval_id: str) -> None:
    _redis.delete(f"approval:{approval_id}")
