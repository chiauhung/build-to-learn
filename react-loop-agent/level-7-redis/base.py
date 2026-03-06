"""
Carried forward from Level 4-6 — tools, plan display, LLM plan generation, history compaction.
Open this file only if you want to see the unchanged parts.
The new stuff is in main.py.
"""

import json
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from google import genai


# ──────────────────────────────────────────────
# Tools (same as Level 4)
# ──────────────────────────────────────────────

def tool_query_department(args: dict, session: dict) -> str:
    dept = args.get("department", "").lower()
    print(f"    Querying {dept} department...")
    time.sleep(1)
    dept_data = {
        "engineering": {"headcount": 84, "active_today": 72, "new_hires": 5, "avg_tenure_months": 18},
        "sales":       {"headcount": 45, "active_today": 38, "new_hires": 8, "avg_tenure_months": 12},
        "marketing":   {"headcount": 32, "active_today": 28, "new_hires": 3, "avg_tenure_months": 24},
    }
    data = dept_data.get(dept, {"error": f"Unknown department: {dept}"})
    if "departments" not in session["data"]:
        session["data"]["departments"] = {}
    session["data"]["departments"][dept] = data
    return json.dumps(data)


def tool_calculate(args: dict, session: dict) -> str:
    expr = args.get("expression", "")
    print(f"    Calculating: {expr}")
    try:
        return str(eval(expr))
    except Exception as e:
        return f"Error: {e}"


def tool_list_departments(args: dict, session: dict) -> str:
    print("    Listing departments...")
    departments = ["engineering", "sales", "marketing"]
    session["data"]["available_departments"] = departments
    return json.dumps(departments)


def tool_create_bar_chart(args: dict, session: dict) -> str:
    title = args.get("title", "Chart")
    labels = args.get("labels", [])
    values = args.get("values", [])
    if not labels or not values:
        return "Error: need both 'labels' and 'values' arrays"
    print(f"    Creating bar chart: {title}")
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=["#4C78A8", "#F58518", "#E45756", "#72B7B2"])
    ax.set_title(title)
    ax.set_ylabel("Value")
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                str(val), ha="center", va="bottom", fontsize=11)
    sessions_dir = os.path.join(os.path.dirname(__file__), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    filename = f"{session['session_id']}_chart_{int(time.time())}.png"
    path = os.path.join(sessions_dir, filename)
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return f"Chart saved to {path}"


TOOLS = {
    "query_department": {
        "description": "Fetch metrics for a department. Args: {\"department\": \"engineering\"}",
        "function": tool_query_department,
    },
    "calculate": {
        "description": "Evaluate a math expression. Args: {\"expression\": \"72/84 * 100\"}",
        "function": tool_calculate,
    },
    "list_departments": {
        "description": "List all available departments. Args: {}",
        "function": tool_list_departments,
    },
    "create_bar_chart": {
        "description": "Create a bar chart PNG. Args: {\"title\": \"Headcount\", \"labels\": [\"eng\", \"sales\"], \"values\": [84, 45]}",
        "function": tool_create_bar_chart,
    },
}


# ──────────────────────────────────────────────
# Plan display (same as Level 5)
# ──────────────────────────────────────────────

def display_plan(plan: list[dict], current_index: int):
    print()
    print("  [Plan]")
    for i, step in enumerate(plan):
        letter = chr(ord('a') + i)
        if step.get("tool"):
            args_str = json.dumps(step.get("args", {}))
            label = f"{step['tool']}({args_str})"
        elif step.get("action") == "ASK_USER":
            label = f"ask user: \"{step.get('question', '?')}\""
        elif step.get("action") == "FINAL_ANSWER":
            label = "FINAL_ANSWER"
        else:
            label = step.get("action", "?")

        if len(label) > 55:
            label = label[:52] + "..."

        if i < current_index:
            indicator = "\u2705"
            status = "done"
        elif i == current_index:
            indicator = "\U0001f504"
            status = "doing"
        else:
            indicator = "\u23f3"
            status = "pending"

        print(f"    {letter}. {label:<58} {indicator} {status}")
    print()


# ──────────────────────────────────────────────
# LLM — plan generation (same as Level 5)
# ──────────────────────────────────────────────

def build_system_prompt() -> str:
    tools_desc = "\n".join(
        f"  - {name}: {info['description']}"
        for name, info in TOOLS.items()
    )

    return f"""You are a helpful data analyst agent. The user will give you a goal.

Available tools:
{tools_desc}

You must respond with a PLAN — a JSON array of steps to accomplish the goal.

Each step is one of:
{{"action": "USE_TOOL", "tool": "tool_name", "args": {{"arg1": "value1"}}, "reason": "why"}}
{{"action": "ASK_USER", "question": "your question"}}
{{"action": "FINAL_ANSWER", "answer": "placeholder"}}

Rules:
- Return a JSON array of steps
- The last step should always be FINAL_ANSWER
- Don't re-do steps that are already done (check history)
- History may contain a COMPACTED_SUMMARY — this is a summary of older steps.
  Trust it and don't repeat those actions.
- If the user corrected their request, adapt accordingly
- Respond with valid JSON array only
"""


def ask_llm_for_plan(session: dict) -> list[dict]:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    messages = f"User goal: {session['user_goal']}\n\n"

    if session["history"]:
        messages += "History (already completed):\n"
        for h in session["history"]:
            messages += f"- {json.dumps(h)}\n"
        messages += "\n"

    if session["data"]:
        messages += f"Data collected so far: {json.dumps(session['data'])}\n\n"

    messages += "Generate a plan (JSON array of steps) to accomplish the remaining work."

    print("  [Asking LLM for plan...]")

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=messages,
        config=genai.types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            temperature=0,
        ),
    )

    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
        text = text.strip()

    try:
        plan = json.loads(text)
        if isinstance(plan, dict):
            plan = [plan]
        return plan
    except json.JSONDecodeError:
        return [{"action": "FINAL_ANSWER", "answer": text}]


def ask_llm_for_final_answer(session: dict) -> str:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    messages = f"User goal: {session['user_goal']}\n\n"
    messages += f"Data collected: {json.dumps(session['data'])}\n\n"

    if session["history"]:
        messages += "History:\n"
        for h in session["history"]:
            messages += f"- {json.dumps(h)}\n"
        messages += "\n"

    messages += "Based on all data, provide your final answer. Plain text, not JSON."

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=messages,
        config=genai.types.GenerateContentConfig(
            system_instruction="You are a helpful data analyst. Give a clear, concise answer.",
            temperature=0,
        ),
    )
    return response.text.strip()


# ──────────────────────────────────────────────
# History Compaction (same as Level 6)
# ──────────────────────────────────────────────

COMPACT_THRESHOLD = 5
KEEP_RECENT = 3


def compact_history(session: dict):
    """
    Compact old history entries into a summary.
    Currently FAKE — just concatenates. In production, use an LLM.
    """
    history = session["history"]

    if len(history) <= COMPACT_THRESHOLD:
        return

    print()
    print("  " + "=" * 50)
    print("  [COMPACTING HISTORY...]")
    print(f"  Before: {len(history)} entries")

    old_entries = history[:-KEEP_RECENT]
    recent_entries = history[-KEEP_RECENT:]

    summary_parts = []
    for entry in old_entries:
        action = entry.get("action", "?")
        if action == "USE_TOOL":
            tool = entry.get("tool", "?")
            summary_parts.append(f"Used {tool}")
        elif action == "ASK_USER":
            summary_parts.append(f"Asked user, got: {entry.get('result', '?')}")
        elif action == "USER_CORRECTION":
            summary_parts.append(f"User corrected: {entry.get('result', '?')}")
        elif action == "FINAL_ANSWER":
            summary_parts.append("Gave answer")
        elif action == "COMPACTED_SUMMARY":
            summary_parts.append(entry.get("summary", ""))
        else:
            summary_parts.append(f"{action}: {entry.get('result', '?')}")

    summary_text = "Previously: " + ". ".join(summary_parts) + "."

    compacted_entry = {
        "action": "COMPACTED_SUMMARY",
        "summary": summary_text,
        "compacted_count": len(old_entries),
    }

    session["history"] = [compacted_entry] + recent_entries

    print(f"  After:  {len(session['history'])} entries "
          f"(1 summary + {len(recent_entries)} recent)")
    print(f"  Summary: \"{summary_text[:80]}...\"")
    print("  " + "=" * 50)
    print()
