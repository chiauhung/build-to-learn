"""
In-memory store for level-5: sessions + pending approvals.

Two separate namespaces:

  Sessions  — keyed by session_id, hold message history across turns
  Approvals — keyed by approval_id, hold a paused agent run waiting for human decision

A session can be mid-approval: both records exist simultaneously.
When the approval resolves, the updated message history is written back to the session.

In production: replace both dicts with Redis hashes.
The interface stays identical — only this file changes.
"""

import uuid
from typing import Any

# session_id → {"deps_config": dict, "messages": list[ModelMessage]}
_sessions: dict[str, dict[str, Any]] = {}

# approval_id → {"session_id": str, "approvals": list[dict], "messages": list}
_approvals: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def session_create(deps_config: dict) -> str:
    """Create a new empty session. Returns session_id."""
    session_id = str(uuid.uuid4())[:8]
    _sessions[session_id] = {"deps_config": deps_config, "messages": []}
    return session_id


def session_get(session_id: str) -> dict[str, Any] | None:
    return _sessions.get(session_id)


def session_update_messages(session_id: str, messages: list) -> None:
    """Overwrite the message history for a session."""
    if session_id in _sessions:
        _sessions[session_id]["messages"] = messages


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


def approval_save(session_id: str, messages: list, approvals: list[dict]) -> str:
    """Pause a session mid-run. Returns approval_id."""
    approval_id = str(uuid.uuid4())[:8]
    _approvals[approval_id] = {
        "session_id": session_id,
        "messages": messages,
        "approvals": approvals,
    }
    return approval_id


def approval_get(approval_id: str) -> dict[str, Any] | None:
    return _approvals.get(approval_id)


def approval_delete(approval_id: str) -> None:
    _approvals.pop(approval_id, None)
