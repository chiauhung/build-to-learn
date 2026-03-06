"""
Level 1: Basic Agent + Dependency Injection

What you'll learn:
- Agent with RunContext[Deps] — typed dependency injection
- DuckDB as mock BQ — real SQL, fixture-style setup
- Multi-tenant permission boundary — same agent, different deps per user
- agent.iter() — step through the ReAct loop node by node

Key insight: deps are invisible to the LLM. The permission boundary
lives in runtime, not in prompts.
"""

import asyncio
import sys
from dataclasses import dataclass, field

import duckdb
from pydantic_ai import Agent, RunContext

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import db
from shared import print_header, print_node


# ---------------------------------------------------------------------------
# Dependencies — this is the security boundary
# ---------------------------------------------------------------------------


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    allowed_datasets: list[str] = field(default_factory=list)
    user_id: str = "anonymous"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

agent = Agent(
    "google-gla:gemini-2.0-flash",
    deps_type=ChatDeps,
    system_prompt=(
        "You are a BigQuery assistant. You help users explore datasets and tables. "
        "Use the provided tools to list tables and query data. "
        "Always use the tools — never make up data."
    ),
)


# ---------------------------------------------------------------------------
# Tools — note how permission checks live in deps, not prompts
# ---------------------------------------------------------------------------


@agent.tool
async def list_datasets(ctx: RunContext[ChatDeps]) -> list[str]:
    """List the datasets you have access to."""
    return ctx.deps.allowed_datasets


@agent.tool
async def list_tables(ctx: RunContext[ChatDeps], dataset: str) -> list[str]:
    """List tables in a dataset."""
    if dataset not in ctx.deps.allowed_datasets:
        return [f"Access denied: you don't have permission to access `{dataset}`"]
    return db.list_tables(ctx.deps.conn, dataset)


@agent.tool
async def query_table(ctx: RunContext[ChatDeps], dataset: str, table: str) -> str:
    """Query all rows from a table. Returns the data as text."""
    if dataset not in ctx.deps.allowed_datasets:
        return f"Access denied: you don't have permission to access `{dataset}`"
    try:
        return db.run_query(ctx.deps.conn, f"SELECT * FROM {dataset}.{table}")
    except duckdb.Error as e:
        return f"Query error: {e}"


# ---------------------------------------------------------------------------
# Run with agent.iter() — see the ReAct loop node by node
# ---------------------------------------------------------------------------


async def run_with_iter(user_prompt: str, deps: ChatDeps):
    print_header(deps, user_prompt)

    async with agent.iter(user_prompt, deps=deps) as agent_run:
        async for node in agent_run:
            print_node(node, user_prompt)

    result = agent_run.result
    assert result is not None
    print(f"\n  Agent: {result.output}")
    print(f"  (usage: {result.usage()})")


# ---------------------------------------------------------------------------
# Demo: same agent, different permissions
# ---------------------------------------------------------------------------


async def main():
    conn = db.create_db()

    # User A: can only see sales
    deps_a = ChatDeps(conn=conn, allowed_datasets=["sales"], user_id="user-a")

    # User B: can see everything
    deps_b = ChatDeps(
        conn=conn, allowed_datasets=["sales", "marketing", "hr"], user_id="user-b"
    )

    # Same agent, same tools — different permission boundaries
    await run_with_iter("What tables are available? Show me the sales orders.", deps_a)
    await run_with_iter("Show me the HR employee data.", deps_a)  # denied
    await run_with_iter("Show me the HR employee data.", deps_b)  # works


if __name__ == "__main__":
    asyncio.run(main())
