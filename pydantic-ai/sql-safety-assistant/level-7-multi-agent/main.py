"""
Level 7: Multi-Agent — Model Escalation

What you learn:
- Two agents, two models, same tools
- Agent A (Haiku / flash-lite) handles the query cheaply
- If it flags the query as complex, Agent B (Sonnet / flash) takes over
- Agent B receives Agent A's attempt as context — no duplicate work

Why different agents instead of one?
- Cost: Haiku is ~20x cheaper than Sonnet
- In production, 80% of queries are simple — Haiku handles them
- You only pay for the expensive model when genuinely needed
- The escalation decision lives in Agent A's output, not in routing logic you write

Flow:
  User question
      ↓
  Agent A (cheap model)
      ↓ if output starts with "ESCALATE:"
  Agent B (expensive model) — receives A's analysis as context
      ↓
  Final result

Run:
  python -m level-7-multi-agent.main
  or: uv run level-7-multi-agent/main.py
"""

import asyncio
import sys

import duckdb
from dataclasses import dataclass, field
from pydantic_ai import Agent, RunContext

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import db


# ---------------------------------------------------------------------------
# Shared deps
# ---------------------------------------------------------------------------


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    allowed_datasets: list[str] = field(default_factory=list)
    user_id: str = "anonymous"


# ---------------------------------------------------------------------------
# Agent A — cheap, fast (gemini-2.0-flash-lite or haiku)
#
# Handles simple queries directly.
# For complex/ambiguous queries, outputs "ESCALATE: <reason>\n<analysis>"
# so Agent B gets A's work as context rather than starting from scratch.
# ---------------------------------------------------------------------------

agent_a = Agent(
    "google-gla:gemini-2.0-flash-lite",
    deps_type=ChatDeps,
    output_type=str,
    system_prompt=(
        "You are a SQL analyst (fast tier). Answer data questions about BigQuery.\n\n"
        "ALWAYS call tools in this order — never skip steps, never ask the user:\n"
        "1. list_datasets\n"
        "2. list_tables for relevant datasets\n"
        "3. generate_sql\n"
        "4. dry_run_sql\n"
        "5. execute_sql\n\n"
        "After executing, decide:\n"
        "- If the result is clear and complete → answer directly.\n"
        "- If the question requires multi-step reasoning, cross-dataset joins, "
        "trend analysis, or statistical interpretation → respond with:\n"
        "  ESCALATE: <one-line reason>\n"
        "  <your SQL, data, and partial analysis so far>\n\n"
        "Be conservative: escalate when in doubt. Never fabricate data."
    ),
)


# ---------------------------------------------------------------------------
# Agent B — expensive, thorough (gemini-2.0-flash or sonnet)
#
# Only called when Agent A escalates.
# Receives A's full analysis as additional context.
# ---------------------------------------------------------------------------

agent_b = Agent(
    "google-gla:gemini-2.0-flash",
    deps_type=ChatDeps,
    output_type=str,
    system_prompt=(
        "You are a senior SQL analyst (thorough tier). "
        "You receive queries that the fast tier could not fully resolve.\n\n"
        "You will be given:\n"
        "- The original user question\n"
        "- The fast tier's analysis (SQL run, data retrieved, partial reasoning)\n\n"
        "Use the fast tier's work as a starting point. "
        "Call tools only if you need fresher data or additional queries.\n"
        "Provide a complete, well-reasoned answer.\n\n"
        "Tool order if needed: list_datasets → list_tables → generate_sql → dry_run_sql → execute_sql\n"
        "Never ask the user clarifying questions. Never fabricate data."
    ),
)


# ---------------------------------------------------------------------------
# Shared tools — registered on both agents
# ---------------------------------------------------------------------------

for _agent in (agent_a, agent_b):

    @_agent.tool
    async def list_datasets(ctx: RunContext[ChatDeps]) -> list[str]:
        """List datasets you have access to."""
        return ctx.deps.allowed_datasets

    @_agent.tool
    async def list_tables(ctx: RunContext[ChatDeps], dataset: str) -> str:
        """List tables in a dataset."""
        if dataset not in ctx.deps.allowed_datasets:
            return f"Access denied: no permission for `{dataset}`"
        tables = db.list_tables(ctx.deps.conn, dataset)
        return f"Tables in {dataset}: {', '.join(tables)}"

    @_agent.tool
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
        elif "trend" in q or "over time" in q:
            return "SELECT region, SUM(amount) as total FROM sales.orders GROUP BY region ORDER BY total DESC"
        else:
            return "SELECT * FROM sales.orders WHERE amount > 100"

    @_agent.tool
    async def dry_run_sql(ctx: RunContext[ChatDeps], sql: str) -> str:
        """Dry-run SQL to estimate cost. Does NOT execute."""
        result = db.dry_run(ctx.deps.conn, sql)
        cost = result["estimated_cost_usd"]
        return (
            f"Dry run: {result['estimated_bytes']:,} bytes | "
            f"Est. cost: ${cost:.4f}"
        )

    @_agent.tool
    async def execute_sql(ctx: RunContext[ChatDeps], sql: str) -> str:
        """Execute SQL and return results."""
        return db.run_query(ctx.deps.conn, sql)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def answer(question: str, deps: ChatDeps) -> dict:
    """
    Run Agent A. If it escalates, run Agent B with A's context.
    Returns {"model_used": str, "escalated": bool, "result": str}
    """
    print(f"\n  [Agent A — flash-lite] answering: {question!r}")
    result_a = await agent_a.run(question, deps=deps)
    output_a = result_a.output

    print(f"  [Agent A] usage: {result_a.usage()}")

    if output_a.startswith("ESCALATE:"):
        # Extract the reason line and Agent A's analysis
        lines = output_a.split("\n", 1)
        reason = lines[0].replace("ESCALATE:", "").strip()
        context_from_a = lines[1].strip() if len(lines) > 1 else ""

        print(f"  [Agent A] escalating — reason: {reason}")
        print(f"  [Agent B — flash] taking over...")

        escalation_prompt = (
            f"Original question: {question}\n\n"
            f"Fast tier escalated because: {reason}\n\n"
            f"Fast tier's work so far:\n{context_from_a}"
        )

        result_b = await agent_b.run(escalation_prompt, deps=deps)
        print(f"  [Agent B] usage: {result_b.usage()}")

        return {
            "model_used": "gemini-2.0-flash (Agent B — thorough tier)",
            "escalated": True,
            "escalation_reason": reason,
            "result": result_b.output,
        }

    return {
        "model_used": "gemini-2.0-flash-lite (Agent A — fast tier)",
        "escalated": False,
        "result": output_a,
    }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

SEPARATOR = "~" * 60


async def demo(label: str, question: str, deps: ChatDeps):
    print(f"\n{SEPARATOR}")
    print(f"  {label}")
    print(f"  Question: {question}")
    print(SEPARATOR)
    result = await answer(question, deps)
    print(f"\n  Model used : {result['model_used']}")
    if result["escalated"]:
        print(f"  Escalated  : yes — {result['escalation_reason']}")
    else:
        print(f"  Escalated  : no")
    print(f"\n  Answer:\n{result['result']}")


async def main():
    conn = db.create_db()
    deps_sales = ChatDeps(conn=conn, allowed_datasets=["sales", "marketing"], user_id="analyst")
    deps_all = ChatDeps(conn=conn, allowed_datasets=["sales", "marketing", "hr"], user_id="analyst")

    # Simple query — Agent A handles it directly
    await demo(
        "SCENARIO 1: Simple query — expect Agent A to answer directly",
        "Show me all sales orders over $100",
        deps_sales,
    )

    # Complex analytical question — expect Agent A to escalate
    await demo(
        "SCENARIO 2: Complex analysis — expect escalation to Agent B",
        "Analyze our sales performance by region and explain which region is underperforming and why",
        deps_sales,
    )

    # Cross-dataset question — likely escalation
    await demo(
        "SCENARIO 3: Cross-dataset — compare marketing spend to sales",
        "Which marketing campaigns drove the most revenue relative to spend?",
        deps_all,
    )


if __name__ == "__main__":
    asyncio.run(main())
