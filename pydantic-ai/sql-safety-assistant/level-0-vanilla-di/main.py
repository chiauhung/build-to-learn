"""
Level 0: Vanilla Runtime Context Injection — No Framework

What you'll learn:
- Agent = logic (stateless). Deps = environment (per-request).
- RunContext is just a wrapper that carries deps into tools.
- RunContext does NOT manage resource lifecycle. You do.
- Same agent, different deps = multi-tenant. Not different agents.

This is pure Python. No pydantic-ai. No magic.
Once you understand this, Level 1's RunContext[Deps] will make total sense.

Key rules:
  1. Agent has NO user-specific state
  2. Deps are created per-request, passed at run time
  3. Whoever creates a resource (conn) is responsible for closing it
  4. RunContext = runtime view of deps, not a resource manager
"""

import sys
from dataclasses import dataclass, field
from typing import Generic, TypeVar

import duckdb

T = TypeVar("T")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import db


# ---------------------------------------------------------------------------
# 1. RunContext — just a bag that carries deps into tools
# ---------------------------------------------------------------------------


@dataclass
class RunContext(Generic[T]):
    """This is what Pydantic AI's RunContext[T] is under the hood.
    It's not a connection manager. It's not magic. It's just this."""

    deps: T


# ---------------------------------------------------------------------------
# 2. Deps — the runtime environment (per-user, per-request)
# ---------------------------------------------------------------------------


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    allowed_datasets: list[str] = field(default_factory=list)
    user_id: str = "anonymous"


# ---------------------------------------------------------------------------
# 3. Agent — stateless. No conn. No user info. Just logic + tools.
# ---------------------------------------------------------------------------


class Agent:
    """Minimal agent. The point: it holds ZERO user-specific state."""

    def __init__(self):
        self.tools: dict[str, callable] = {}

    def tool(self, fn):
        """Register a tool function."""
        self.tools[fn.__name__] = fn
        return fn

    def run(self, prompt: str, deps: ChatDeps) -> str:
        """Run the agent. Creates RunContext here — per run, not per agent."""
        ctx = RunContext(deps=deps)  # ← created at RUN time, not at INIT time

        print(f"\n{'=' * 50}")
        print(f"[run] user={deps.user_id} | datasets={deps.allowed_datasets}")
        print(f"[run] prompt: {prompt!r}")
        print(f"{'=' * 50}")

        # Simulate a simple "agent loop" — call tools based on the prompt
        if "tables" in prompt.lower() or "list" in prompt.lower():
            result = self.tools["list_datasets"](ctx)
            print(f"\n  [tool] list_datasets → {result}")

            for ds in result:
                tables = self.tools["list_tables"](ctx, ds)
                print(f"  [tool] list_tables({ds!r}) → {tables}")

            return f"Available datasets: {result}"

        elif "query" in prompt.lower() or "show" in prompt.lower():
            # Try to query HR data — permission check happens in the tool
            result = self.tools["query_table"](ctx, "hr", "employees")
            print(f"\n  [tool] query_table('hr', 'employees') →")
            print(f"  {result}")
            return result

        else:
            return "I don't understand. Try asking about tables or queries."


# ---------------------------------------------------------------------------
# 4. Create the agent (once, at app startup)
# ---------------------------------------------------------------------------

agent = Agent()


# ---------------------------------------------------------------------------
# 5. Tools — they receive RunContext, not raw deps
#    Permission boundary lives in ctx.deps, invisible to the "LLM"
# ---------------------------------------------------------------------------


@agent.tool
def list_datasets(ctx: RunContext[ChatDeps]) -> list[str]:
    """Only returns datasets this user is allowed to see."""
    return ctx.deps.allowed_datasets


@agent.tool
def list_tables(ctx: RunContext[ChatDeps], dataset: str) -> list[str]:
    """Permission check: is this dataset in allowed_datasets?"""
    if dataset not in ctx.deps.allowed_datasets:
        return [f"ACCESS DENIED: {dataset}"]
    return db.list_tables(ctx.deps.conn, dataset)


@agent.tool
def query_table(ctx: RunContext[ChatDeps], dataset: str, table: str) -> str:
    """Permission check happens HERE, not in the prompt."""
    if dataset not in ctx.deps.allowed_datasets:
        return f"ACCESS DENIED: you cannot access `{dataset}`"
    return db.run_query(ctx.deps.conn, f"SELECT * FROM {dataset}.{table}")


# ---------------------------------------------------------------------------
# 6. Runtime — this is where lifecycle management happens
#    YOU create conn. YOU close conn. RunContext doesn't touch it.
# ---------------------------------------------------------------------------


def main():
    # --- App startup: create shared resources ---
    conn = db.create_db()  # in-memory DuckDB, seeded with data

    # --- User A request: can only see sales ---
    deps_a = ChatDeps(conn=conn, allowed_datasets=["sales"], user_id="user-a")
    agent.run("List all tables", deps=deps_a)
    agent.run("Show me HR data", deps=deps_a)  # should be DENIED

    # --- User B request: can see everything ---
    deps_b = ChatDeps(
        conn=conn, allowed_datasets=["sales", "marketing", "hr"], user_id="user-b"
    )
    agent.run("List all tables", deps=deps_b)
    agent.run("Show me HR data", deps=deps_b)  # should work

    # --- Cleanup: YOU close conn, not RunContext ---
    conn.close()
    print("\n[cleanup] conn.close() — YOU manage this, not RunContext")

    # --- What you just proved: ---
    print("\n" + "=" * 50)
    print("KEY TAKEAWAYS:")
    print("=" * 50)
    print("  1. agent was created ONCE. Never changes.")
    print("  2. deps were created PER USER. Different permissions.")
    print("  3. RunContext was created PER RUN (inside agent.run).")
    print("  4. conn was closed by YOU, not by RunContext.")
    print("  5. Same agent + different deps = multi-tenant.")
    print()
    print("  If your colleague creates agent_per_user... that's wrong.")
    print("  Agent = SQL query template. Deps = DB connection.")
    print("  You don't compile a new SQL engine per user.")


if __name__ == "__main__":
    main()
