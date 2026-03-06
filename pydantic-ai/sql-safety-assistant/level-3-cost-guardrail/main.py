"""
Level 3: Cost Guardrail + Multi-Tenant — The Full SQL Safety Assistant

What you'll learn:
- Cost guardrail: LLM proposes, runtime enforces
- Conditional approval: only ask human when cost exceeds threshold
- Multi-tenant: same agent, different permission + cost limits per user
- agent.iter(): watch the full pipeline step by step

Pipeline:
  1. LLM generates SQL            → generate_sql (regular tool)
  2. Dry-run checks cost           → dry_run_sql (regular tool)
  3. If cost > threshold → human   → execute_sql (conditional ApprovalRequired)
  4. Execute SQL                   → execute_sql (runs if approved / under limit)
"""

import asyncio
import sys
from dataclasses import dataclass, field

import duckdb
from pydantic_ai import (
    Agent,
    ApprovalRequired,
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolDenied,
)

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import db
from shared import print_header, print_node, print_deferred


# ---------------------------------------------------------------------------
# Dependencies — permission boundary + cost guardrail
# ---------------------------------------------------------------------------


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    allowed_datasets: list[str] = field(default_factory=list)
    user_id: str = "anonymous"
    # Cost guardrail — the LLM never sees this value
    cost_limit_usd: float = 0.01


# ---------------------------------------------------------------------------
# Agent
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


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


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
    """Generate SQL for a question. Returns SQL string, does NOT execute."""
    allowed = ctx.deps.allowed_datasets
    q = question.lower()

    if ("salary" in q or "employee" in q):
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
        f"  Est. cost: ${cost:.4f}\n"
        f"  Cost limit: ${limit:.4f}\n"
        f"  Status: {status}"
    )


@agent.tool
async def execute_sql(ctx: RunContext[ChatDeps], sql: str) -> str:
    """Execute SQL. If cost exceeds the limit, requires human approval."""
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
# Run with iter() + deferred tool handling
# ---------------------------------------------------------------------------


async def run_agent(user_prompt: str, deps: ChatDeps):
    print_header(deps, user_prompt)

    async with agent.iter(user_prompt, deps=deps) as agent_run:
        async for node in agent_run:
            print_node(node, user_prompt)

    result = agent_run.result
    assert result is not None

    # Handle deferred tools (human approval needed)
    if isinstance(result.output, DeferredToolRequests):
        print_deferred(result.output)

        answer = input("\n  Approve? [y/N]: ").strip().lower()
        approved = answer == "y"
        print(f"  → {'APPROVED' if approved else 'DENIED'}")

        deferred_results = DeferredToolResults()
        for call in result.output.approvals:
            if approved:
                deferred_results.approvals[call.tool_call_id] = True
            else:
                deferred_results.approvals[call.tool_call_id] = ToolDenied(
                    "User denied: cost too high"
                )

        result = await agent.run(
            message_history=result.all_messages(),
            deferred_tool_results=deferred_results,
            deps=deps,
        )

    print(f"\n  Agent: {result.output}")
    print(f"  (usage: {result.usage()})")


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------


async def main():
    conn = db.create_db()

    # Scenario 1: Cheap query — auto-execute (under cost limit)
    print("\n" + "~" * 60)
    print("SCENARIO 1: Cheap query — should auto-execute")
    print("~" * 60)
    await run_agent(
        "Show me sales orders over $100",
        ChatDeps(conn=conn, allowed_datasets=["sales", "marketing"], user_id="analyst-a", cost_limit_usd=0.01),
    )

    # Scenario 2: Expensive query — will prompt for approval (HR = 50GB)
    # Try typing 'y' to approve, or anything else to deny
    print("\n" + "~" * 60)
    print("SCENARIO 2: Expensive query — you decide [y/N]")
    print("~" * 60)
    await run_agent(
        "Show me all employee salaries",
        ChatDeps(conn=conn, allowed_datasets=["sales", "marketing", "hr"], user_id="analyst-b", cost_limit_usd=0.01),
    )

    # Scenario 3: Permission boundary — no HR access at all
    print("\n" + "~" * 60)
    print("SCENARIO 3: No HR access — permission boundary in deps")
    print("~" * 60)
    await run_agent(
        "Show me all employee salaries",
        ChatDeps(conn=conn, allowed_datasets=["sales"], user_id="analyst-c", cost_limit_usd=0.01),
    )


if __name__ == "__main__":
    asyncio.run(main())
