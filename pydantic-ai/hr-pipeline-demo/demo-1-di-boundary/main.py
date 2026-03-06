"""
Demo 1: Dependency Injection as Permission Boundary

The point:
  DI is not clean code. It is a security boundary.
  The agent calls pre-built tools — it never writes SQL.
  The runtime decides WHICH company's data is returned and WHAT can be mutated.

Domain: Talent acquisition platform (Pulsifi-style)
  Two client companies:
    - Growthly Tech    (company_id=1001)
    - BrightHire Bank  (company_id=1002)

Tools (no free-form SQL — hardcoded queries, safe by design):
  get_applicants(status=None)              → returns applicants for deps.company_id
  move_applicant_status(app_id, new_status)→ moves status, guarded by deps.company_id
                                              AND deps.can_move_status

Two DI boundaries — both invisible to the LLM:
  deps.company_id       — which tenant's rows are touched
  deps.can_move_status  — whether this user is allowed to mutate status

Personas:
  Alice  — HR Manager,        Growthly (1001), can_move_status=True
  Bob    — Talent Acq. Lead,  BrightHire (1002), can_move_status=True
  Charlie— Recruiter (read-only), Growthly (1001), can_move_status=False

Run:
  cd pydantic-ai-demo
  uv run demo-1-di-boundary/main.py
"""

import asyncio
import sys
from dataclasses import dataclass

import duckdb

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import db
from pydantic_ai import Agent, RunContext

# ─────────────────────────────────────────────
# Deps — the permission boundary
# ─────────────────────────────────────────────

VALID_STATUSES = {
    "applied",
    "sourced",
    "shortlisted",
    "interviewed",
    "offered",
    "hired",
    "rejected",
    "withdrawn",
}


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    user_id: str
    role: str
    company_id: int  # ← tenant boundary — LLM never sees this
    can_move_status: bool  # ← mutation permission — LLM never sees this


# ─────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────

agent = Agent(
    "google-gla:gemini-3-pro-preview",
    deps_type=ChatDeps,
    output_type=str,
    system_prompt=(
        "You are a talent acquisition assistant. "
        "Use the available tools to answer questions about job applicants. "
        "To move an applicant's status, use move_applicant_status with their application ID and the new status. "
        "Valid statuses: applied, sourced, shortlisted, interviewed, offered, hired, rejected, withdrawn."
    ),
)


@agent.tool
async def get_applicants(ctx: RunContext[ChatDeps], status: str | None = None) -> str:
    """
    Get job applicants for the current company.
    Optionally filter by status: applied, sourced, shortlisted, interviewed,
    offered, hired, rejected, withdrawn.
    """
    # company_id comes from deps — the LLM never passes it, never knows it exists
    sql = """
        SELECT id, first_name, last_name, status, role_fit_score, culture_fit_score,
               has_passed_screening, submitted_at
        FROM talent_acquisition.job_application
        WHERE company_id = ?
    """
    params: list[int | str] = [ctx.deps.company_id]

    if status:
        if status not in VALID_STATUSES:
            return f"[ERROR] '{status}' is not a valid status. Choose from: {', '.join(sorted(VALID_STATUSES))}"
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY role_fit_score DESC NULLS LAST"

    result = ctx.deps.conn.execute(sql, params)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()

    if not rows:
        return "No applicants found."

    header = " | ".join(columns)
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    lines.append(f"({len(rows)} rows)")
    return "\n".join(lines)


@agent.tool
async def move_applicant_status(
    ctx: RunContext[ChatDeps], application_id: str, new_status: str
) -> str:
    """
    Move a job applicant to a new status.
    Valid statuses: applied, sourced, shortlisted, interviewed, offered, hired, rejected, withdrawn.
    """
    # ── Permission check 1: role allows mutation ──────────────
    if not ctx.deps.can_move_status:
        return (
            f"[DENIED] User '{ctx.deps.user_id}' (role: {ctx.deps.role}) "
            f"does not have permission to change applicant status."
        )

    # ── Validate status value ─────────────────────────────────
    if new_status not in VALID_STATUSES:
        return f"[ERROR] '{new_status}' is not a valid status. Choose from: {', '.join(sorted(VALID_STATUSES))}"

    # ── Permission check 2: application belongs to this company ──
    # The LLM passes application_id — but we verify it belongs to deps.company_id.
    # Even if the LLM passes an app_id from another company, this blocks it.
    row = ctx.deps.conn.execute(
        "SELECT id, first_name, last_name, status FROM talent_acquisition.job_application "
        "WHERE id = ? AND company_id = ?",
        [application_id, ctx.deps.company_id],
    ).fetchone()

    if not row:
        return (
            f"[DENIED] Application '{application_id}' not found or does not belong to "
            f"company {ctx.deps.company_id}."
        )

    old_status = row[3]

    # ── Execute update ────────────────────────────────────────
    ctx.deps.conn.execute(
        "UPDATE talent_acquisition.job_application SET status = ? WHERE id = ? AND company_id = ?",
        [new_status, application_id, ctx.deps.company_id],
    )

    return (
        f"[OK] {row[1]} {row[2]} (id: {application_id}) "
        f"moved from '{old_status}' → '{new_status}'."
    )


# ─────────────────────────────────────────────
# Demo runner
# ─────────────────────────────────────────────

SEP = "=" * 64


def banner(user_id: str, role: str, company_id: int, can_move: bool, question: str):
    print(f"\n{SEP}")
    print(f"  User       : {user_id}  ({role})")
    print(f"  Company ID : {company_id}  (from deps — LLM never sees this)")
    print(f"  Can move   : {can_move}  (from deps — LLM never sees this)")
    print(f"  Question   : {question}")
    print(SEP)


async def ask(question: str, deps: ChatDeps) -> str:
    result = await agent.run(question, deps=deps)
    return result.output


async def main():
    conn = db.create_db()

    # ── Persona A: Alice — HR Manager, Growthly ──────────────
    # Can view AND move applicants. Scoped to company_id=1001.
    deps_a = ChatDeps(
        conn=conn,
        user_id="alice@growthly.com",
        role="HR Manager",
        company_id=1001,
        can_move_status=True,
    )
    banner(
        deps_a.user_id,
        deps_a.role,
        deps_a.company_id,
        deps_a.can_move_status,
        "Show me all shortlisted candidates",
    )
    print(await ask("Show me all shortlisted candidates", deps_a))

    banner(
        deps_a.user_id,
        deps_a.role,
        deps_a.company_id,
        deps_a.can_move_status,
        "Move Aisha Rahman to interviewed",
    )
    print(await ask("Move Aisha Rahman to interviewed", deps_a))

    # ── Persona B: Bob — Talent Acq. Lead, BrightHire ────────
    # Can view AND move. Scoped to company_id=1002.
    # Asks about "all applicants" — only gets BrightHire's, never Growthly's.
    deps_b = ChatDeps(
        conn=conn,
        user_id="bob@brighthirebank.com",
        role="Talent Acquisition Lead",
        company_id=1002,
        can_move_status=True,
    )
    banner(
        deps_b.user_id,
        deps_b.role,
        deps_b.company_id,
        deps_b.can_move_status,
        "Show me all applicants and move the shortlisted ones to interviewed",
    )
    print(
        await ask(
            "Show me all applicants and move the shortlisted ones to interviewed",
            deps_b,
        )
    )

    # ── Persona C: Charlie — Recruiter (read-only), Growthly ─
    # Same company as Alice, but can_move_status=False.
    # Tries to promote someone — blocked by the DI boundary.
    deps_c = ChatDeps(
        conn=conn,
        user_id="charlie@growthly.com",
        role="Recruiter",
        company_id=1001,
        can_move_status=False,
    )
    banner(
        deps_c.user_id,
        deps_c.role,
        deps_c.company_id,
        deps_c.can_move_status,
        "Show me applied candidates, then move Marcus Tan to shortlisted",
    )
    print(
        await ask(
            "Show me applied candidates, then move Marcus Tan to shortlisted", deps_c
        )
    )

    # ── What just happened? ───────────────────────────────────
    print(f"\n{'~' * 64}")
    print("  KEY INSIGHT")
    print(f"{'~' * 64}")
    print("""
  Same agent. Same tools. Same prompt structure.

  Alice   → viewed Growthly's shortlisted, moved Aisha to interviewed. ✅
  Bob     → viewed BrightHire's applicants only, moved Ahmad to interviewed. ✅
  Charlie → viewed Growthly's applied (read-only), move was denied. ❌

  Two DI boundaries — both invisible to the LLM:

    deps.company_id       → get_applicants uses it in WHERE clause (no LLM SQL)
                            move_applicant_status verifies app belongs to this company
                            The LLM cannot pass a different company_id — it has no access.

    deps.can_move_status  → move_applicant_status checks this before any mutation
                            Charlie's role can call the tool, but the runtime stops it.

  No free-form SQL:
    The LLM calls named tools with typed arguments.
    The tool itself holds the query logic — hardcoded, auditable, safe.
    The LLM cannot construct a query that bypasses the company boundary.

  Mastra equivalent:
    Pass tenantId in step context. Manually check in every tool.
    Forget it in one tool → data leak. No type safety. Discipline-enforced.
    DI makes it language-enforced across ALL tools simultaneously.
""")


if __name__ == "__main__":
    asyncio.run(main())
