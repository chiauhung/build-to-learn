"""
In-memory store for pending approval requests.

In production you'd replace this with Redis or a DB.
The interface stays the same — only this file changes.

Structure of a pending entry:
{
    "messages":   list[ModelMessage],   # full agent message history to resume from
    "approvals":  [{"tool_call_id": str, "tool_name": str, "args": dict, "meta": dict}],
    "deps_config": dict,                # serializable deps (user_id, allowed_datasets, cost_limit)
}
"""

import uuid
from typing import Any

# approval_id → pending entry
_store: dict[str, dict[str, Any]] = {}


def save(messages: list, approvals: list[dict], deps_config: dict) -> str:
    """Store a paused agent run. Returns the approval_id."""
    approval_id = str(uuid.uuid4())[:8]
    _store[approval_id] = {
        "messages": messages,
        "approvals": approvals,
        "deps_config": deps_config,
    }
    return approval_id


def get(approval_id: str) -> dict[str, Any] | None:
    return _store.get(approval_id)


def delete(approval_id: str) -> None:
    _store.pop(approval_id, None)
