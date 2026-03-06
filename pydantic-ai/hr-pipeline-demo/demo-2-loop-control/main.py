"""
Demo 2: agent.iter() — You Control the Execution Loop

Domain: Talent acquisition platform (Pulsifi-style)

Three scenarios, each exercising a different loop-control capability:

  A: Normal run — watch every node, see the full audit log
  B: Mutation cap — safety guard stops the loop after N status changes
  C: Replan loop — outer loop detects a dead end and injects a new strategy

The 4 loop-control primitives shown across A + B:
  1. Custom stopping condition  — halt when mutations_this_run >= mutation_cap
  2. Runtime middleware         — compliance audit log per tool call
  3. Tool execution interception— pause before → hired / → rejected for human approval
  4. Reasoning state injection  — mutations_this_run updated inside tool, read live in loop

Scenario C adds a 5th: the meta-loop (replan)
  5. Replan loop — outer loop observes denials, captures message history,
     injects a new strategy prompt, restarts agent.iter() with full context

Run:
  cd pydantic-ai-demo
  uv run demo-2-loop-control/main.py
"""

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import duckdb
from pydantic_ai import Agent, RunContext
from pydantic_ai._agent_graph import (
    CallToolsNode,
    End,
    ModelRequestNode,
    UserPromptNode,
)
from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import db

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
TERMINAL_STATUSES = {"hired", "rejected"}


# ─────────────────────────────────────────────
# Deps
# ─────────────────────────────────────────────


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    user_id: str
    company_id: int
    mutation_cap: int = 5

    # Scenario C: auto-deny the first N "→ offered" transitions
    # to simulate an operator repeatedly saying no (without requiring input())
    auto_deny_n_offers: int = 0

    # Runtime state — tracked externally, invisible to the LLM
    mutations_this_run: int = field(default=0, init=False)
    operator_denials: int = field(default=0, init=False)
    audit_log: list[dict] = field(default_factory=list, init=False)


# ─────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────

agent = Agent(
    "google-gla:gemini-3-pro-preview",
    deps_type=ChatDeps,
    output_type=str,
    system_prompt=(
        "You are a talent acquisition assistant. "
        "Use get_applicants and move_applicant_status to process the pipeline. "
        "Valid statuses: applied, sourced, shortlisted, interviewed, offered, hired, rejected, withdrawn. "
        "When asked to process the pipeline: get candidates first, then move them based on their role_fit_score."
    ),
)


@agent.tool
async def get_applicants(ctx: RunContext[ChatDeps], status: str | None = None) -> str:
    """
    Get job applicants for the current company.
    Optionally filter by status: applied, sourced, shortlisted, interviewed,
    offered, hired, rejected, withdrawn.
    """
    sql = """
        SELECT id, first_name, last_name, status, role_fit_score, has_passed_screening
        FROM talent_acquisition.job_application
        WHERE company_id = ?
    """
    params: list[int | str] = [ctx.deps.company_id]

    if status:
        if status not in VALID_STATUSES:
            return f"[ERROR] '{status}' is not valid. Choose from: {', '.join(sorted(VALID_STATUSES))}"
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
    if new_status not in VALID_STATUSES:
        return f"[ERROR] '{new_status}' is not a valid status."

    row = ctx.deps.conn.execute(
        "SELECT id, first_name, last_name, status FROM talent_acquisition.job_application "
        "WHERE id = ? AND company_id = ?",
        [application_id, ctx.deps.company_id],
    ).fetchone()

    if not row:
        return f"[DENIED] Application '{application_id}' not found or belongs to another company."

    old_status = row[3]

    # Scenario C: simulate operator denial for "→ offered" transitions
    if new_status == "offered" and ctx.deps.auto_deny_n_offers > 0:
        ctx.deps.auto_deny_n_offers -= 1
        ctx.deps.operator_denials += 1
        return (
            f"[DENIED by operator] {row[1]} {row[2]} → '{new_status}' was rejected. "
            f"(operator unavailable for this candidate)"
        )

    ctx.deps.conn.execute(
        "UPDATE talent_acquisition.job_application SET status = ? WHERE id = ? AND company_id = ?",
        [new_status, application_id, ctx.deps.company_id],
    )

    # [4] REASONING STATE INJECTION
    ctx.deps.mutations_this_run += 1

    return (
        f"[OK] {row[1]} {row[2]} moved '{old_status}' → '{new_status}'. "
        f"(mutation #{ctx.deps.mutations_this_run})"
    )


# ─────────────────────────────────────────────
# Loop runners
# ─────────────────────────────────────────────

DIVIDER = "  " + "-" * 52


async def _run_one(
    prompt: str,
    deps: ChatDeps,
    message_history: list | None = None,
) -> tuple[str | None, bool]:
    """
    Run one agent.iter() pass. Returns (final_output, replan_needed).
    Encapsulates the loop-control logic shared across scenarios.
    """
    stop_reason: str | None = None
    replan_needed = False

    async with agent.iter(
        prompt, deps=deps, message_history=message_history or []
    ) as agent_run:
        async for node in agent_run:
            if isinstance(node, UserPromptNode):
                print("  [UserPrompt] loaded")

            elif isinstance(node, ModelRequestNode):
                print("  [ModelRequest] → LLM thinking...")

            elif isinstance(node, CallToolsNode):
                for part in node.model_response.parts:
                    if not isinstance(part, ToolCallPart):
                        continue

                    tool_name = part.tool_name
                    tool_args = part.args_as_dict()

                    # [2] MIDDLEWARE — audit log
                    entry = {
                        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                        "tool": tool_name,
                        "args": tool_args,
                    }
                    deps.audit_log.append(entry)
                    print(f"\n{DIVIDER}")
                    print(f"  [Audit] {tool_name}({tool_args})")

                    if tool_name == "move_applicant_status":
                        # [1] CUSTOM STOP — mutation cap
                        if deps.mutations_this_run >= deps.mutation_cap:
                            print(
                                f"  [STOP] Mutation cap "
                                f"{deps.mutations_this_run}/{deps.mutation_cap}. Halting."
                            )
                            stop_reason = (
                                f"Agent halted: mutation cap of {deps.mutation_cap} reached. "
                                f"{deps.mutations_this_run} changes made."
                            )
                            break

                        # [3] INTERCEPTION — terminal transitions (A/B scenarios)
                        new_status = tool_args.get("new_status", "")
                        if new_status in TERMINAL_STATUSES:
                            app_id = tool_args.get("application_id", "")
                            print(
                                f"  [INTERCEPT] Terminal → '{new_status}' | app: {app_id}"
                            )
                            answer = input("  Approve? [y/N]: ").strip().lower()
                            if answer != "y":
                                print("  [DENIED by operator]")
                                stop_reason = (
                                    f"Operator denied '{new_status}' transition."
                                )
                                break

                # [5] REPLAN SIGNAL — check after tools ran
                if deps.operator_denials >= 2:
                    print(
                        f"\n  [REPLAN SIGNAL] {deps.operator_denials} operator denials detected "
                        "— this plan is stuck."
                    )
                    replan_needed = True
                    # Capture history BEFORE breaking
                    captured_history = list(agent_run.all_messages())
                    break

            elif isinstance(node, End):
                print(f"\n{DIVIDER}")
                print("  [End] Run complete")

        if replan_needed:
            return captured_history, True  # type: ignore[return-value]

        if stop_reason:
            return stop_reason, False

        result = agent_run.result
        return (str(result.output) if result else "(no result)"), False


async def run_with_loop_control(question: str, deps: ChatDeps) -> str:
    """Scenarios A and B — single pass with loop control."""
    print(f"\n  Question : {question!r}")
    print(f"  User     : {deps.user_id} | cap: {deps.mutation_cap}\n")
    output, _ = await _run_one(question, deps)
    return str(output)


# Replan prompt injected as a new user turn after denials
REPLAN_INJECT = (
    "The previous candidates you selected for 'offered' were all rejected by the operator — "
    "they are no longer available for this role. "
    "Please reconsider: look at interviewed-stage candidates or anyone with role_fit_score above 60. "
    "There are still offer slots to fill."
)


async def run_with_replan(question: str, deps: ChatDeps, max_replans: int = 3) -> str:
    """
    Scenario C — meta-loop around agent.iter().

    Outer loop:
      1. Runs the agent
      2. Observes operator_denials accumulating in deps
      3. When denials >= 2: captures full message history, injects a replan prompt
      4. Restarts agent.iter() with that history — agent sees everything that happened
         plus the new instruction, and replans accordingly

    The agent never knows a replan happened.
    From its perspective it just received more context.
    """
    prompt = question
    message_history: list = []

    for attempt in range(1, max_replans + 1):
        print(f"\n{DIVIDER}")
        print(f"  [Attempt {attempt}/{max_replans}]")
        if message_history:
            print(f"  [Carrying {len(message_history)} messages from previous run]")

        deps.operator_denials = 0  # reset signal for this attempt

        result, replan_needed = await _run_one(prompt, deps, message_history)

        if not replan_needed:
            return str(result)

        # result is the captured history when replan_needed=True
        message_history = result  # type: ignore[assignment]

        # Inject replan instruction as a new user turn into the history
        message_history.append(
            ModelRequest(parts=[UserPromptPart(content=REPLAN_INJECT)])
        )

        print("\n  [REPLAN] Injecting new strategy into history...")
        print(f"  [REPLAN] Instruction: '{REPLAN_INJECT[:80]}...'")
        print(f"  [REPLAN] Starting attempt {attempt + 1} with full context")

        # The next pass receives the same original question — the injected
        # message in history is what drives the new strategy
        prompt = question

    return f"Max replans ({max_replans}) reached without completing the task."


# ─────────────────────────────────────────────
# Demo scenarios
# ─────────────────────────────────────────────

SEP = "=" * 64

PIPELINE_PROMPT = (
    "Process our applied pipeline: "
    "move candidates with role_fit_score above 70 to shortlisted, "
    "move candidates with role_fit_score below 50 to rejected, "
    "and skip candidates with no role_fit_score (leave them as applied)."
)

OFFER_PROMPT = (
    "We need to fill 2 offer slots. "
    "Find our strongest applied candidates (role_fit_score above 80) and move them to offered."
)


async def main():
    # ── Scenario A: Normal run ────────────────────────────────
    print(f"\n{SEP}")
    print("  SCENARIO A: Normal run — process applied → shortlisted/rejected by threshold")
    print("  mutation_cap=10 (won't trigger)")
    print(SEP)

    conn_a = db.create_db()
    deps_a = ChatDeps(
        conn=conn_a, user_id="alice@growthly.com", company_id=1001, mutation_cap=10
    )
    answer_a = await run_with_loop_control(PIPELINE_PROMPT, deps_a)
    print(f"\n  Result:\n{answer_a}")
    print(f"\n  Audit log ({len(deps_a.audit_log)} entries):")
    for i, e in enumerate(deps_a.audit_log, 1):
        print(f"    {i}. [{e['ts']}] {e['tool']}({e['args']})")

    # ── Scenario B: Mutation cap ──────────────────────────────
    print(f"\n{SEP}")
    print("  SCENARIO B: Mutation cap — stops after 2 status changes")
    print("  maxSteps=2 would stop after 2 LLM calls. This stops after 2 mutations.")
    print(SEP)

    conn_b = db.create_db()
    deps_b = ChatDeps(
        conn=conn_b, user_id="alice@growthly.com", company_id=1001, mutation_cap=2
    )
    answer_b = await run_with_loop_control(PIPELINE_PROMPT, deps_b)
    print(f"\n  Result:\n{answer_b}")
    print(f"  Mutations before halt: {deps_b.mutations_this_run}")

    # ── Scenario C: Replan loop ───────────────────────────────
    print(f"\n{SEP}")
    print(
        "  SCENARIO C: Replan loop — outer loop detects dead end, injects new strategy"
    )
    print(
        "  First 2 'offered' transitions are auto-denied (simulating operator rejection)"
    )
    print(
        "  After 2 denials: message history captured, replan injected, agent restarts"
    )
    print(SEP)

    conn_c = db.create_db()
    deps_c = ChatDeps(
        conn=conn_c,
        user_id="alice@growthly.com",
        company_id=1001,
        mutation_cap=10,
        auto_deny_n_offers=2,  # first 2 offered transitions will be auto-denied
    )
    answer_c = await run_with_replan(OFFER_PROMPT, deps_c, max_replans=3)
    print(f"\n  Result:\n{answer_c}")
    print(f"  Total mutations: {deps_c.mutations_this_run}")
    print(f"  Audit log ({len(deps_c.audit_log)} entries):")
    for i, e in enumerate(deps_c.audit_log, 1):
        print(f"    {i}. [{e['ts']}] {e['tool']}({e['args']})")

    # ── Key insights ──────────────────────────────────────────
    print(f"\n{'~' * 64}")
    print("  KEY INSIGHT — 5 loop-control capabilities")
    print(f"{'~' * 64}")
    print("""
  ✅ [1] Custom stopping condition
     → mutations_this_run >= mutation_cap. A business signal, not a step count.

  ✅ [2] Runtime middleware
     → Audit log fires before every tool call. Compliance-grade trail.

  ✅ [3] Tool execution interception
     → Pauses BEFORE → hired / → rejected. Human approves mid-loop.
       Mastra suspends a STEP. This suspends between two calls in the same step.

  ✅ [4] Reasoning state injection
     → deps.mutations_this_run updated inside the tool, read by the outer loop.
       No message passing. No shared queue. Just a mutable reference.

  ✅ [5] Replan loop (meta-loop)
     → Outer loop observes operator_denials accumulating in deps.
       Breaks the run, captures agent_run.all_messages() as history.
       Injects a new strategy prompt into that history.
       Restarts agent.iter() — agent sees full context + new instruction.
       The agent never knows a replan happened.
       Mastra equivalent: two separate workflow steps with an explicit branch.
       Here: one outer loop reacting to what it watched happen inside.
""")


if __name__ == "__main__":
    asyncio.run(main())
