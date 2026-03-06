"""
Level 4: FastAPI — Production Web App Pattern

What you learn:
- Agent run splits across TWO HTTP requests (pause → resume)
- In-memory store bridges the gap (swap for Redis in level-5)
- Same agent + tools as level-3, different runner

Flow:
  POST /query          → agent runs → hits deferred → save to store → return {approval_id}
  GET  /pending/{id}   → show what SQL + cost is waiting for approval
  POST /approve/{id}   → {"approved": true} → resume agent → return final result

Try it:
  uv run uvicorn level-4-fastapi.main:app --reload
  open http://localhost:8000/docs   ← Swagger UI, all endpoints clickable
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

app = FastAPI(title="SQL Safety Assistant", version="1.0")


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
# Agent + tools (identical to level-3)
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


class QueryRequest(BaseModel):
    question: str
    user_id: str = "anonymous"
    allowed_datasets: list[str] = ["sales", "marketing"]
    cost_limit_usd: float = 0.01


class QueryResponse(BaseModel):
    status: str                     # "done" | "pending_approval"
    result: str | None = None       # final answer if done
    approval_id: str | None = None  # approval key if paused


class ApprovalRequest(BaseModel):
    approved: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """Submit a question. May return immediately or pause for approval."""
    conn = db.create_db()  # fresh in-memory DB per request
    deps = ChatDeps(
        conn=conn,
        allowed_datasets=req.allowed_datasets,
        user_id=req.user_id,
        cost_limit_usd=req.cost_limit_usd,
    )

    result = await agent.run(req.question, deps=deps)

    if isinstance(result.output, DeferredToolRequests):
        # Agent paused — store state, return approval_id to client
        approvals = [
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "args": call.args,
                "meta": result.output.metadata.get(call.tool_call_id, {}),
            }
            for call in result.output.approvals
        ]
        approval_id = store.save(
            messages=result.all_messages(),
            approvals=approvals,
            deps_config={
                "user_id": req.user_id,
                "allowed_datasets": req.allowed_datasets,
                "cost_limit_usd": req.cost_limit_usd,
            },
        )
        return QueryResponse(status="pending_approval", approval_id=approval_id)

    return QueryResponse(status="done", result=str(result.output))


@app.get("/pending/{approval_id}")
async def get_pending(approval_id: str):
    """Get details of a pending approval request."""
    entry = store.get(approval_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    return {
        "approval_id": approval_id,
        "approvals": entry["approvals"],
        "deps_config": entry["deps_config"],
    }


@app.post("/approve/{approval_id}", response_model=QueryResponse)
async def approve(approval_id: str, req: ApprovalRequest):
    """Approve or deny a pending SQL execution. Resumes the agent."""
    entry = store.get(approval_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")

    # Re-build deps (conn is not serializable, so we recreate it)
    cfg = entry["deps_config"]
    conn = db.create_db()
    deps = ChatDeps(
        conn=conn,
        allowed_datasets=cfg["allowed_datasets"],
        user_id=cfg["user_id"],
        cost_limit_usd=cfg["cost_limit_usd"],
    )

    # Build deferred results from human decision
    deferred_results = DeferredToolResults()
    for call in entry["approvals"]:
        if req.approved:
            deferred_results.approvals[call["tool_call_id"]] = True
        else:
            deferred_results.approvals[call["tool_call_id"]] = ToolDenied(
                "User denied via API"
            )

    # Resume agent from saved message history
    result = await agent.run(
        message_history=entry["messages"],
        deferred_tool_results=deferred_results,
        deps=deps,
    )

    store.delete(approval_id)
    return QueryResponse(status="done", result=str(result.output))
