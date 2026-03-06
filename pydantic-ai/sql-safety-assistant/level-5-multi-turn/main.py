"""
Level 5: Multi-Turn Chat Session

What you learn:
- message_history is the session — you own persistence, not the framework
- Same agent handles turn 1 and turn 10; it just sees more history each time
- Approval can happen mid-session; history is written back after resume

New vs level-4:
  level-4: stateless per request (no memory between /query calls)
  level-5: session_id ties turns together — LLM remembers the conversation

Endpoints:
  POST /session                  → create session, get session_id
  POST /session/{id}/chat        → send a message (may return approval_id)
  GET  /session/{id}/history     → see the full conversation so far
  GET  /pending/{approval_id}    → inspect what's waiting for approval
  POST /approve/{approval_id}    → approve or deny, resumes agent, history updated

Try it:
  uv run uvicorn level-5-multi-turn.main:app --reload --port 8001
  open http://localhost:8001/docs
"""

import sys
from dataclasses import dataclass, field

import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pydantic_ai import (
    Agent,
    ApprovalRequired,
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolDenied,
)

_here = __import__("pathlib").Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))  # for db.py
sys.path.insert(0, str(_here))         # for store.py
import db
import store

app = FastAPI(title="SQL Safety Assistant — Multi-Turn", version="2.0")


# ---------------------------------------------------------------------------
# Deps
# ---------------------------------------------------------------------------


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    allowed_datasets: list[str] = field(default_factory=list)
    user_id: str = "anonymous"
    cost_limit_usd: float = 0.01


# ---------------------------------------------------------------------------
# Agent + tools (identical to level-3/4)
# ---------------------------------------------------------------------------

agent = Agent(
    "google-gla:gemini-2.0-flash",
    deps_type=ChatDeps,
    output_type=str | DeferredToolRequests,
    system_prompt=(
        "You are the SQL Safety Assistant. Help users query BigQuery safely.\n\n"
        "IMPORTANT: Never ask the user for information you can get from tools. "
        "Always call tools first.\n\n"
        "Workflow (always follow this order, no exceptions):\n"
        "1. Call list_datasets immediately — do not ask the user what datasets exist\n"
        "2. Call list_tables for relevant datasets\n"
        "3. Call generate_sql with the user's question\n"
        "4. Call dry_run_sql to check cost\n"
        "5. Call execute_sql\n\n"
        "You have memory of the full conversation. Use previous results to answer "
        "follow-up questions without re-running queries unless the user asks you to refresh.\n\n"
        "Never skip any step. Never ask the user clarifying questions. "
        "Never make up data. If access is denied, report it."
    ),
)


@agent.tool
async def list_datasets(ctx: RunContext[ChatDeps]) -> list[str]:
    """List datasets you have access to."""
    return ctx.deps.allowed_datasets


@agent.tool
async def list_tables(ctx: RunContext[ChatDeps], dataset: str) -> str:
    """List tables in a dataset."""
    if dataset not in ctx.deps.allowed_datasets:
        return f"Access denied: no permission for `{dataset}`"
    tables = db.list_tables(ctx.deps.conn, dataset)
    return f"Tables in {dataset}: {', '.join(tables)}"


@agent.tool
async def generate_sql(ctx: RunContext[ChatDeps], question: str) -> str:
    """Generate SQL for a question. Does NOT execute."""
    allowed = ctx.deps.allowed_datasets
    q = question.lower()

    if "salary" in q or "employee" in q:
        if "hr" not in allowed:
            return "Access denied: you do not have permission to query the hr dataset."
        return "SELECT emp_id, name, dept, salary FROM hr.employees"
    elif "campaign" in q:
        if "marketing" not in allowed:
            return "Access denied: you do not have permission to query the marketing dataset."
        return "SELECT * FROM marketing.campaigns"
    else:
        return "SELECT * FROM sales.orders WHERE amount > 100"


@agent.tool
async def dry_run_sql(ctx: RunContext[ChatDeps], sql: str) -> str:
    """Dry-run SQL to estimate cost. Does NOT execute."""
    result = db.dry_run(ctx.deps.conn, sql)
    cost = result["estimated_cost_usd"]
    limit = ctx.deps.cost_limit_usd
    status = "UNDER LIMIT" if cost <= limit else "OVER LIMIT — will need approval"
    return (
        f"Dry run:\n"
        f"  SQL: {result['sql']}\n"
        f"  Bytes: {result['estimated_bytes']:,}\n"
        f"  Est. cost: ${cost:.4f} | Limit: ${limit:.4f}\n"
        f"  Status: {status}"
    )


@agent.tool
async def execute_sql(ctx: RunContext[ChatDeps], sql: str) -> str:
    """Execute SQL. Requires human approval if cost exceeds limit."""
    dry_run_result = db.dry_run(ctx.deps.conn, sql)
    cost = dry_run_result["estimated_cost_usd"]

    if cost > ctx.deps.cost_limit_usd and not ctx.tool_call_approved:
        raise ApprovalRequired(
            metadata={
                "sql": sql,
                "estimated_cost_usd": cost,
                "cost_limit_usd": ctx.deps.cost_limit_usd,
                "reason": f"Cost ${cost:.4f} exceeds limit ${ctx.deps.cost_limit_usd:.4f}",
            }
        )
    return db.run_query(ctx.deps.conn, sql)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    user_id: str = "anonymous"
    allowed_datasets: list[str] = ["sales", "marketing"]
    cost_limit_usd: float = 0.01


class SessionCreateResponse(BaseModel):
    session_id: str
    user_id: str
    allowed_datasets: list[str]


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    status: str                     # "done" | "pending_approval"
    result: str | None = None
    approval_id: str | None = None


class ApprovalRequest(BaseModel):
    approved: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/session", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest):
    """Start a new chat session. Returns session_id to use in subsequent /chat calls."""
    deps_config = {
        "user_id": req.user_id,
        "allowed_datasets": req.allowed_datasets,
        "cost_limit_usd": req.cost_limit_usd,
    }
    session_id = store.session_create(deps_config)
    return SessionCreateResponse(
        session_id=session_id,
        user_id=req.user_id,
        allowed_datasets=req.allowed_datasets,
    )


@app.post("/session/{session_id}/chat", response_model=ChatResponse)
async def chat(session_id: str, req: ChatRequest):
    """
    Send a message in a session. The agent sees the full conversation history.
    May return immediately (done) or pause for approval (pending_approval).
    """
    session = store.session_get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    cfg = session["deps_config"]
    conn = db.create_db()
    deps = ChatDeps(
        conn=conn,
        allowed_datasets=cfg["allowed_datasets"],
        user_id=cfg["user_id"],
        cost_limit_usd=cfg["cost_limit_usd"],
    )

    # Pass accumulated history — this is what makes it multi-turn
    result = await agent.run(
        req.message,
        deps=deps,
        message_history=session["messages"],
    )

    if isinstance(result.output, DeferredToolRequests):
        # Save approval, but do NOT update session history yet —
        # we'll write it back after the human decides
        approvals = [
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "args": call.args,
                "meta": result.output.metadata.get(call.tool_call_id, {}),
            }
            for call in result.output.approvals
        ]
        approval_id = store.approval_save(
            session_id=session_id,
            messages=result.all_messages(),
            approvals=approvals,
        )
        return ChatResponse(status="pending_approval", approval_id=approval_id)

    # Update session history with the completed turn
    store.session_update_messages(session_id, result.all_messages())
    return ChatResponse(status="done", result=str(result.output))


@app.get("/session/{session_id}/history")
async def get_history(session_id: str):
    """See the full conversation history for a session."""
    session = store.session_get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Return a readable summary of the message history
    messages = session["messages"]
    summary = []
    for msg in messages:
        kind = type(msg).__name__
        # Extract text content where possible
        parts = []
        if hasattr(msg, "parts"):
            for part in msg.parts:
                if hasattr(part, "content") and isinstance(part.content, str):
                    parts.append(part.content[:200])
                elif hasattr(part, "tool_name"):
                    parts.append(f"[tool: {part.tool_name}]")
        summary.append({"type": kind, "parts": parts})

    return {"session_id": session_id, "turn_count": len(messages), "messages": summary}


@app.get("/pending/{approval_id}")
async def get_pending(approval_id: str):
    """Inspect what's waiting for approval."""
    entry = store.approval_get(approval_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    session = store.session_get(entry["session_id"])
    deps_config = session["deps_config"] if session else {}

    return {
        "approval_id": approval_id,
        "session_id": entry["session_id"],
        "approvals": entry["approvals"],
        "deps_config": deps_config,
    }


@app.post("/approve/{approval_id}", response_model=ChatResponse)
async def approve(approval_id: str, req: ApprovalRequest):
    """
    Approve or deny a pending SQL execution.
    Resumes the agent and writes the completed turn back to the session.
    """
    entry = store.approval_get(approval_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    session_id = entry["session_id"]
    session = store.session_get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    cfg = session["deps_config"]
    conn = db.create_db()
    deps = ChatDeps(
        conn=conn,
        allowed_datasets=cfg["allowed_datasets"],
        user_id=cfg["user_id"],
        cost_limit_usd=cfg["cost_limit_usd"],
    )

    deferred_results = DeferredToolResults()
    for call in entry["approvals"]:
        if req.approved:
            deferred_results.approvals[call["tool_call_id"]] = True
        else:
            deferred_results.approvals[call["tool_call_id"]] = ToolDenied(
                "User denied via API"
            )

    result = await agent.run(
        message_history=entry["messages"],
        deferred_tool_results=deferred_results,
        deps=deps,
    )

    # Write completed turn back to session history
    store.session_update_messages(session_id, result.all_messages())
    store.approval_delete(approval_id)

    return ChatResponse(status="done", result=str(result.output))
