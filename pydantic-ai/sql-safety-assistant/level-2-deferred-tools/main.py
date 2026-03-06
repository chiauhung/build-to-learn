"""
Level 2: Deferred Tools — Human Approval Gate

What you'll learn:
- Deferred tools: tool returns intent, not result
- ApprovalRequired: agent pauses, waits for human decision
- DeferredToolResults: resume with approval/denial
- The SQL pipeline pattern: generate → approve → dry-run → execute

Builds on Level 1: same deps pattern, but now dangerous operations
(executing SQL) require human sign-off before they run.
"""

import asyncio
import sys
from dataclasses import dataclass, field

import duckdb
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolDenied,
)

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import db
from shared import print_header, print_node, print_deferred


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    allowed_datasets: list[str] = field(default_factory=list)
    user_id: str = "anonymous"


# ---------------------------------------------------------------------------
# Agent — note output_type includes DeferredToolRequests
# ---------------------------------------------------------------------------

agent = Agent(
    "google-gla:gemini-2.0-flash",
    deps_type=ChatDeps,
    output_type=str | DeferredToolRequests,
    system_prompt=(
        "You are a SQL Safety Assistant. You help users query BigQuery safely.\n\n"
        "Workflow:\n"
        "1. User asks a question → you generate SQL using generate_sql\n"
        "2. Dry-run the SQL to check cost using dry_run_sql\n"
        "3. Execute the SQL using execute_sql (this requires human approval)\n\n"
        "Always follow this order. Never skip the dry run."
    ),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@agent.tool
async def list_datasets(ctx: RunContext[ChatDeps]) -> list[str]:
    """List datasets you have access to."""
    return ctx.deps.allowed_datasets


@agent.tool
async def generate_sql(ctx: RunContext[ChatDeps], question: str) -> str:
    """Generate a SQL query for a natural language question.
    Returns the SQL string (does NOT execute it)."""
    return f"SELECT * FROM sales.orders WHERE amount > 100 -- generated for: {question}"


@agent.tool
async def dry_run_sql(ctx: RunContext[ChatDeps], sql: str) -> str:
    """Dry-run a SQL query to estimate cost. Does NOT execute."""
    result = db.dry_run(ctx.deps.conn, sql)
    return (
        f"Dry run result:\n"
        f"  SQL: {result['sql']}\n"
        f"  Estimated bytes: {result['estimated_bytes']:,}\n"
        f"  Estimated cost: ${result['estimated_cost_usd']:.4f}"
    )


@agent.tool_plain(requires_approval=True)
def execute_sql(sql: str) -> str:
    """Execute a SQL query. This ALWAYS requires human approval."""
    conn = db.create_db()
    return db.run_query(conn, sql)


# ---------------------------------------------------------------------------
# Run with deferred tool handling
# ---------------------------------------------------------------------------


async def run_with_approval(user_prompt: str, deps: ChatDeps):
    print_header(deps, user_prompt)

    async with agent.iter(user_prompt, deps=deps) as agent_run:
        async for node in agent_run:
            print_node(node, user_prompt)

    result = agent_run.result
    assert result is not None

    # Handle deferred tools (human approval needed)
    if isinstance(result.output, DeferredToolRequests):
        print_deferred(result.output)

        # Real human decision — this is what input() looks like in practice
        answer = input("\n  Approve? [y/N]: ").strip().lower()
        approved = answer == "y"
        print(f"  → {'APPROVED' if approved else 'DENIED'}")

        deferred_results = DeferredToolResults()
        for call in result.output.approvals:
            if approved:
                deferred_results.approvals[call.tool_call_id] = True
            else:
                deferred_results.approvals[call.tool_call_id] = ToolDenied(
                    "User denied: too risky"
                )

        result = await agent.run(
            message_history=result.all_messages(),
            deferred_tool_results=deferred_results,
            deps=deps,
        )

    print(f"\n  Agent: {result.output}")
    print(f"  (usage: {result.usage()})")


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


async def main():
    conn = db.create_db()
    deps = ChatDeps(
        conn=conn,
        allowed_datasets=["sales", "marketing"],
        user_id="user-a",
    )

    await run_with_approval(
        "Find all sales orders over $100 and execute the query.",
        deps,
    )


if __name__ == "__main__":
    asyncio.run(main())
