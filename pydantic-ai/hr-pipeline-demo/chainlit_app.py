"""
Chainlit app — Talent Acquisition Assistant (Pydantic AI demo)

Shows:
  - Login-based DI boundary (company_id, can_move_status injected from user registry)
  - Agent loop internals rendered as Chainlit steps (LLM decisions, tool calls)
  - Terminal transition interception via approve/deny action buttons (mid-stream)
  - Mutation cap safety guard with real-time counter
  - Role-fit threshold prompt before pipeline processing (AskActionMessage)

Run:
  export GOOGLE_API_KEY=your-key
  cd pydantic-ai-demo
  uv run chainlit run chainlit_app.py
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import chainlit as cl
import duckdb

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import db
from pydantic_ai import Agent, RunContext
from pydantic_ai._agent_graph import (
    CallToolsNode,
    End,
    ModelRequestNode,
    UserPromptNode,
)
from pydantic_ai.messages import ToolCallPart

# ─── User registry ────────────────────────────────────────────────────────────
# username = password for each user
# deps boundaries are hardcoded here — never exposed to the LLM

USER_REGISTRY: dict[str, dict] = {
    "alice": {
        "display_name": "Alice",
        "role": "HR Manager",
        "company_id": 1001,
        "company_name": "Growthly Tech",
        "can_move_status": True,
        "mutation_cap": 5,
    },
    "bob": {
        "display_name": "Bob",
        "role": "Talent Acquisition Lead",
        "company_id": 1002,
        "company_name": "BrightHire Bank",
        "can_move_status": True,
        "mutation_cap": 5,
    },
    "charlie": {
        "display_name": "Charlie",
        "role": "Recruiter (read-only)",
        "company_id": 1001,
        "company_name": "Growthly Tech",
        "can_move_status": False,
        "mutation_cap": 5,
    },
}

# ─── Deps ─────────────────────────────────────────────────────────────────────

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


@dataclass
class ChatDeps:
    conn: duckdb.DuckDBPyConnection
    user_id: str
    role: str
    company_id: int
    company_name: str
    can_move_status: bool
    mutation_cap: int = 5

    # Runtime state — live, invisible to the LLM
    mutations_this_run: int = field(default=0, init=False)
    audit_log: list[dict] = field(default_factory=list, init=False)
    tool_results: dict[str, str] = field(default_factory=dict, init=False)
    # Pre-approvals set in CallToolsNode (before tools run) keyed by tool_call_id
    pre_approvals: dict[str, bool] = field(default_factory=dict, init=False)


# ─── Agent ────────────────────────────────────────────────────────────────────

agent = Agent(
    "google-gla:gemini-2.0-flash",
    deps_type=ChatDeps,
    output_type=str,
    system_prompt=(
        "You are a talent acquisition assistant. "
        "Use get_applicants, get_application_id, and move_applicant_status to answer questions and process pipelines. "
        "Valid statuses: applied, sourced, shortlisted, interviewed, offered, hired, rejected, withdrawn. "
        "IMPORTANT: move_applicant_status requires an application ID. If you only have a candidate's name, "
        "always call get_application_id first to resolve their ID before calling move_applicant_status. "
        "When processing the pipeline: fetch all applied candidates first, then move each one to 'shortlisted' "
        "if their role_fit_score meets or exceeds the threshold provided by the user, otherwise move them to 'rejected'. "
        "Skip candidates with no role_fit_score (null) — leave them as 'applied'. "
        "Always explain what you did and why."
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

    def _ret(msg: str) -> str:
        if ctx.tool_call_id:
            ctx.deps.tool_results[ctx.tool_call_id] = msg
        return msg

    if not rows:
        return _ret("No applicants found.")

    lines = [" | ".join(columns), "-" * 60]
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    lines.append(f"({len(rows)} rows)")
    return _ret("\n".join(lines))


@agent.tool
async def get_application_id(ctx: RunContext[ChatDeps], candidate_name: str) -> str:
    """
    Look up an application ID by candidate name.
    Use this whenever you only have a candidate's name and need their application ID
    before calling move_applicant_status.
    candidate_name: full name or partial name (e.g. "Aisha Rahman" or "Aisha").
    """
    term = f"%{candidate_name.strip().lower()}%"
    rows = ctx.deps.conn.execute(
        "SELECT id, first_name, last_name, status FROM talent_acquisition.job_application "
        "WHERE company_id = ? AND LOWER(first_name || ' ' || last_name) LIKE ?",
        [ctx.deps.company_id, term],
    ).fetchall()

    if not rows:
        return f"[NOT FOUND] No applicant matching '{candidate_name}' in your company."
    if len(rows) == 1:
        row = rows[0]
        return f"application_id={row[0]} | {row[1]} {row[2]} | status={row[3]}"
    # Multiple matches — return all so the LLM can pick the right one
    results = [f"application_id={r[0]} | {r[1]} {r[2]} | status={r[3]}" for r in rows]
    return "Multiple matches found:\n" + "\n".join(results)


@agent.tool
async def move_applicant_status(
    ctx: RunContext[ChatDeps], application_id: str, new_status: str
) -> str:
    """
    Move a job applicant to a new status.
    application_id: must be a valid application ID (e.g. app-g01). Use get_application_id first if you only have a name.
    Valid statuses: applied, sourced, shortlisted, interviewed, offered, hired, rejected, withdrawn.
    """
    # ── DI boundary 1: role permission ───────────────────────
    if not ctx.deps.can_move_status:
        msg = (
            f"[DENIED] {ctx.deps.user_id} ({ctx.deps.role}) "
            "does not have permission to change applicant status."
        )
        if ctx.tool_call_id:
            ctx.deps.tool_results[ctx.tool_call_id] = msg
        return msg

    def _ret(msg: str) -> str:
        if ctx.tool_call_id:
            ctx.deps.tool_results[ctx.tool_call_id] = msg
        return msg

    if ctx.deps.mutations_this_run >= ctx.deps.mutation_cap:
        return _ret(
            f"[STOPPED] Mutation cap of {ctx.deps.mutation_cap} reached. No further changes allowed this run."
        )

    if new_status not in VALID_STATUSES:
        return _ret(f"[ERROR] '{new_status}' is not a valid status.")

    # ── DI boundary 2: tenant scope ───────────────────────────
    row = ctx.deps.conn.execute(
        "SELECT id, first_name, last_name, status FROM talent_acquisition.job_application "
        "WHERE id = ? AND company_id = ?",
        [application_id, ctx.deps.company_id],
    ).fetchone()

    if not row:
        return _ret(f"[DENIED] Application '{application_id}' not found or belongs to another company.")

    old_status = row[3]

    # ── Interception: terminal transitions need human approval ─
    # Approval was collected in CallToolsNode (before tools ran) via AskActionMessage.
    # Tool just reads the pre-stored decision; no async interaction needed here.
    if new_status in TERMINAL_STATUSES and ctx.tool_call_id:
        if not ctx.deps.pre_approvals.pop(ctx.tool_call_id, True):
            candidate_name = f"{row[1]} {row[2]}"
            return _ret(f"[DENIED by operator] '{new_status}' transition for {candidate_name} was rejected.")

    # ── Execute ───────────────────────────────────────────────
    ctx.deps.conn.execute(
        "UPDATE talent_acquisition.job_application SET status = ? WHERE id = ? AND company_id = ?",
        [new_status, application_id, ctx.deps.company_id],
    )

    # ── Reasoning state injection ─────────────────────────────
    ctx.deps.mutations_this_run += 1

    return _ret(
        f"[OK] {row[1]} {row[2]} moved '{old_status}' → '{new_status}' "
        f"(mutation #{ctx.deps.mutations_this_run} this run)"
    )


# ─── Table helper ─────────────────────────────────────────────────────────────


def _build_applicants_table(conn: duckdb.DuckDBPyConnection, company_id: int) -> str:
    rows = conn.execute(
        """
        SELECT first_name || ' ' || last_name AS name,
               status, role_fit_score, has_passed_screening
        FROM talent_acquisition.job_application
        WHERE company_id = ?
        ORDER BY role_fit_score DESC NULLS LAST
        """,
        [company_id],
    ).fetchall()

    if not rows:
        return "_No applicants._"

    lines = [
        "| Name | Status | Role Fit | Screening |",
        "|------|--------|:--------:|:---------:|",
    ]
    for name, status, score, passed in rows:
        score_str = f"{score:.0f}" if score is not None else "—"
        passed_str = "✅" if passed is True else ("❌" if passed is False else "—")
        lines.append(f"| {name} | `{status}` | {score_str} | {passed_str} |")
    return "\n".join(lines)


async def _show_applicants(deps: ChatDeps):
    table = _build_applicants_table(deps.conn, deps.company_id)
    await cl.Message(
        content=f"### 📋 {deps.company_name} — Applicants\n\n{table}",
    ).send()


# ─── Auth ─────────────────────────────────────────────────────────────────────


@cl.password_auth_callback
def auth_callback(username: str, password: str) -> cl.User | None:
    if username == password and username in USER_REGISTRY:
        return cl.User(identifier=username, metadata=USER_REGISTRY[username])
    return None


# ─── Lifecycle ────────────────────────────────────────────────────────────────


@cl.on_chat_start
async def on_chat_start():
    user = cl.user_session.get("user")
    meta = user.metadata

    conn = db.create_db()
    deps = ChatDeps(
        conn=conn,
        user_id=f"{user.identifier}@company.com",
        role=meta["role"],
        company_id=meta["company_id"],
        company_name=meta["company_name"],
        can_move_status=meta["can_move_status"],
        mutation_cap=meta["mutation_cap"],
    )
    cl.user_session.set("deps", deps)
    cl.user_session.set("message_history", [])

    perm_icon = "✏️" if meta["can_move_status"] else "👁️ read-only"
    await cl.Message(
        content=(
            f"👋 Welcome, **{meta['display_name']}** ({meta['role']})\n\n"
            f"🏢 **{meta['company_name']}** (company `{meta['company_id']}`)\n"
            f"{perm_icon} &nbsp; mutation cap: **{meta['mutation_cap']}** per run\n\n"
            "**Try:**\n"
            '- *"Show me our applicants"*\n'
            '- *"Process the pipeline"*\n'
            '- *"Move Aisha Rahman to interviewed"*'
        )
    ).send()

    await _show_applicants(deps)


# ─── Threshold prompt ─────────────────────────────────────────────────────────

PIPELINE_KEYWORDS = {"process", "pipeline", "shortlist", "shortlisted", "screening"}


async def _ask_threshold() -> int | None:
    """
    Ask the user for a role_fit_score threshold via action buttons.
    Returns the chosen threshold, or None if timed out.
    """
    res = await cl.AskActionMessage(
        content=(
            "📊 **What role_fit_score threshold should I use for shortlisting?**\n\n"
            "Candidates at or above this score will be moved to `shortlisted`."
        ),
        actions=[
            cl.Action(name="t60", payload={"threshold": 60}, label="60 — wider pool"),
            cl.Action(name="t70", payload={"threshold": 70}, label="70 — balanced"),
            cl.Action(name="t80", payload={"threshold": 80}, label="80 — selective"),
            cl.Action(name="t90", payload={"threshold": 90}, label="90 — top only"),
        ],
        timeout=60,
    ).send()

    if res is None:
        return None
    return res.get("payload", {}).get("threshold")


# ─── Message handler ──────────────────────────────────────────────────────────


@cl.on_message
async def on_message(message: cl.Message):
    deps: ChatDeps = cl.user_session.get("deps")
    message_history: list = cl.user_session.get("message_history")
    deps.mutations_this_run = 0
    deps.tool_results.clear()
    deps.pre_approvals.clear()

    # ── Threshold prompt for pipeline processing ───────────────
    prompt = message.content
    if any(kw in prompt.lower() for kw in PIPELINE_KEYWORDS):
        threshold = await _ask_threshold()
        if threshold is not None:
            prompt = f"{prompt} Use a role_fit_score threshold of {threshold}."
        else:
            await cl.Message(content="⏱️ No threshold selected — proceeding without shortlisting filter.").send()

    stop_reason: str | None = None
    # Buffer tool calls from CallToolsNode — rendered after tools run (next node)
    pending_calls: list[ToolCallPart] = []

    async def _flush_pending() -> bool:
        """Render buffered tool calls with their results. Returns True if mutation cap hit."""
        if not pending_calls:
            return False
        for call in pending_calls:
            args = call.args_as_dict()
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            result = deps.tool_results.get(call.tool_call_id or "", "—")
            deps.audit_log.append({"ts": ts, "tool": call.tool_name, "args": args, "result": result})
            async with cl.Step(name=f"🔧 {call.tool_name}", type="tool") as step:
                step.input = json.dumps(args, indent=2)
                step.output = result
        pending_calls.clear()
        return deps.mutations_this_run >= deps.mutation_cap

    async with agent.iter(prompt, deps=deps, message_history=message_history) as agent_run:
        async for node in agent_run:
            # ── UserPrompt ────────────────────────────────────
            if isinstance(node, UserPromptNode):
                pass

            # ── ModelRequest: LLM is deciding ─────────────────
            # Tools from the previous CallToolsNode have now run — flush them first
            elif isinstance(node, ModelRequestNode):
                capped = await _flush_pending()
                if capped:
                    stop_reason = (
                        f"⛔ **Mutation cap reached** "
                        f"({deps.mutations_this_run}/{deps.mutation_cap} changes this run).\n\n"
                        "The agent has been stopped as a safety guard. "
                        "Start a new message to continue."
                    )
                    break
                async with cl.Step(name="🧠 LLM", type="llm") as step:
                    step.output = "Deciding next action..."

            # ── CallTools: intercept + buffer (tools haven't run yet) ──
            elif isinstance(node, CallToolsNode):
                for part in node.model_response.parts:
                    if not isinstance(part, ToolCallPart):
                        continue
                    # Ask for approval BEFORE terminal transitions run
                    if (
                        part.tool_name == "move_applicant_status"
                        and part.args_as_dict().get("new_status") in TERMINAL_STATUSES
                        and part.tool_call_id
                    ):
                        args = part.args_as_dict()
                        res = await cl.AskActionMessage(
                            content=(
                                f"⚠️ **Terminal transition requested**\n\n"
                                f"Candidate: `{args.get('application_id')}`\n"
                                f"New status: **`{args.get('new_status')}`**\n\n"
                                "Approve to proceed."
                            ),
                            actions=[
                                cl.Action(name="approve_terminal", payload={"approved": True},  label="✅ Approve"),
                                cl.Action(name="deny_terminal",    payload={"approved": False}, label="❌ Deny"),
                            ],
                            timeout=60,
                        ).send()
                        approved = res is not None and res.get("payload", {}).get("approved") is True
                        deps.pre_approvals[part.tool_call_id] = approved
                    pending_calls.append(part)

            # ── End: flush any final tool calls ───────────────
            elif isinstance(node, End):
                await _flush_pending()

    if stop_reason:
        await cl.Message(content=stop_reason, author="Loop Monitor").send()
        await _show_applicants(deps)
        return

    # Only persist history on a clean run — broken runs may have incomplete tool exchanges
    cl.user_session.set("message_history", agent_run.all_messages())

    result = agent_run.result
    if result:
        await cl.Message(content=result.output).send()

    if deps.mutations_this_run > 0:
        await _show_applicants(deps)
