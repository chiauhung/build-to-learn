"""
LEVEL 4: Agent With Tools + Interrupt & Re-plan
=================================================

What changed from Level 3:
  - Actions are now TOOLS — modular, reusable Python functions
  - The LLM picks from a tool registry (same as how Claude Code works)
  - You can INTERRUPT mid-run and give a correction when resuming
  - Every run exports a visual "graph" showing the path the agent took

Same use case as Level 2-3 (department analysis), but now with proper tools.

The big new thing: INTERRUPT AND RE-PLAN
  1. Ask: "Compare sales vs marketing"
  2. Agent fetches sales data...
  3. Ctrl+C (kill it)
  4. Resume: python main.py <session_id>
  5. It asks: "Add a message before continuing?"
  6. You type: "Actually, compare sales vs engineering"
  7. LLM sees: [sales already fetched, user changed mind]
  8. LLM decides: skip re-fetching sales, just fetch engineering → answer

This is the "adaptive" part of ReAct — the agent re-plans based on new info.

Setup:
  pip install google-genai
  export GEMINI_API_KEY=your_key_here

Run:
  python main.py                     # start new session
  python main.py <session_id>        # resume (with optional correction)
  python main.py --list              # list all sessions

After each run, check sessions/<id>_graph.txt for the execution path.
"""

import json
import os
import sys
import time
import uuid

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, no GUI needed
import matplotlib.pyplot as plt

from google import genai


# ──────────────────────────────────────────────
# TOOLS — modular Python functions
# ──────────────────────────────────────────────
# In Level 3, actions were baked into the code.
# Now they're a registry — add/remove tools without touching the loop.

def tool_query_department(args: dict, session: dict) -> str:
    """Fetch metrics for a specific department."""
    dept = args.get("department", "").lower()
    print(f"  Querying {dept} department...")
    time.sleep(1)

    dept_data = {
        "engineering": {"headcount": 84, "active_today": 72, "new_hires": 5, "avg_tenure_months": 18},
        "sales":       {"headcount": 45, "active_today": 38, "new_hires": 8, "avg_tenure_months": 12},
        "marketing":   {"headcount": 32, "active_today": 28, "new_hires": 3, "avg_tenure_months": 24},
    }
    data = dept_data.get(dept, {"error": f"Unknown department: {dept}. Valid: engineering, sales, marketing"})

    # Store in session so LLM can see accumulated data
    if "departments" not in session["data"]:
        session["data"]["departments"] = {}
    session["data"]["departments"][dept] = data

    return json.dumps(data)


def tool_calculate(args: dict, session: dict) -> str:
    """Evaluate a math expression."""
    expr = args.get("expression", "")
    print(f"  Calculating: {expr}")
    try:
        result = eval(expr)  # don't do eval in production!
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def tool_list_departments(args: dict, session: dict) -> str:
    """List all available departments."""
    print("  Listing departments...")
    departments = ["engineering", "sales", "marketing"]
    session["data"]["available_departments"] = departments
    return json.dumps(departments)


def tool_create_bar_chart(args: dict, session: dict) -> str:
    """Create a bar chart PNG from labels and values."""
    title = args.get("title", "Chart")
    labels = args.get("labels", [])
    values = args.get("values", [])

    if not labels or not values:
        return "Error: need both 'labels' and 'values' arrays"

    print(f"  Creating bar chart: {title}")

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=["#4C78A8", "#F58518", "#E45756", "#72B7B2"])
    ax.set_title(title)
    ax.set_ylabel("Value")

    # Add value labels on top of each bar
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                str(val), ha="center", va="bottom", fontsize=11)

    # Save to sessions folder
    sessions_dir = os.path.join(os.path.dirname(__file__), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    filename = f"{session['session_id']}_chart_{int(time.time())}.png"
    path = os.path.join(sessions_dir, filename)
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)

    print(f"  Chart saved to {path}")
    return f"Chart saved to {path}"


# Tool registry — the LLM sees this list
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
# Session management (same as before)
# ──────────────────────────────────────────────

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def create_session(user_goal: str) -> dict:
    session_id = str(uuid.uuid4())[:8]
    session = {
        "session_id": session_id,
        "status": "RUNNING",
        "user_goal": user_goal,
        "data": {},
        "history": [],
    }
    save_session(session)
    return session


def save_session(session: dict):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session['session_id']}.json")
    with open(path, "w") as f:
        json.dump(session, f, indent=2)


def load_session(session_id: str) -> dict:
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No session found: {session_id}")
    with open(path) as f:
        return json.load(f)


def list_sessions() -> list[dict]:
    if not os.path.exists(SESSIONS_DIR):
        return []
    sessions = []
    for f in os.listdir(SESSIONS_DIR):
        if f.endswith(".json") and not f.endswith("_graph.txt"):
            with open(os.path.join(SESSIONS_DIR, f)) as fh:
                sessions.append(json.load(fh))
    return sessions


# ──────────────────────────────────────────────
# Graph export — visual trace of what happened
# ──────────────────────────────────────────────

def export_graph(session: dict):
    """Export a visual graph of the agent's execution path."""
    lines = []
    lines.append(f"Session: {session['session_id']}")
    lines.append(f"Goal: {session['user_goal']}")
    lines.append(f"Status: {session['status']}")
    lines.append("")

    for i, h in enumerate(session["history"]):
        step = h.get("step", i + 1)
        action = h["action"]

        if action == "USE_TOOL":
            tool = h.get("tool", "?")
            args = h.get("args", {})
            label = f"USE_TOOL: {tool}({json.dumps(args)})"
        elif action == "ASK_USER":
            label = f"ASK_USER: \"{h.get('reason', '?')}\""
        elif action == "USER_CORRECTION":
            label = f"USER_CORRECTION: \"{h.get('result', '?')}\""
        elif action == "FINAL_ANSWER":
            label = f"FINAL_ANSWER"
        else:
            label = action

        lines.append(f"  Step {step}: {label}")

        # Draw arrow to next step (unless last)
        if i < len(session["history"]) - 1:
            lines.append(f"    ↓")

    lines.append("")
    lines.append(f"Total steps: {len(session['history'])}")

    graph_text = "\n".join(lines)

    # Save to file
    path = os.path.join(SESSIONS_DIR, f"{session['session_id']}_graph.txt")
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(graph_text)

    print(f"\n  [Graph saved to {path}]")
    print()
    print(graph_text)


# ──────────────────────────────────────────────
# LLM brain — now with tool awareness
# ──────────────────────────────────────────────

def build_system_prompt() -> str:
    tools_desc = "\n".join(
        f"  - {name}: {info['description']}"
        for name, info in TOOLS.items()
    )

    return f"""You are a helpful data analyst agent. The user will give you a goal.
You must accomplish it step by step.

Available tools:
{tools_desc}

At each step, respond with EXACTLY ONE action in JSON format:

To use a tool:
{{"action": "USE_TOOL", "tool": "tool_name", "args": {{"arg1": "value1"}}, "reason": "why"}}

To ask the user a question:
{{"action": "ASK_USER", "question": "your question"}}

To give your final answer:
{{"action": "FINAL_ANSWER", "answer": "your complete answer"}}

Rules:
- Use tools to gather data before answering
- Look at history carefully — don't re-fetch data you already have
- If the user corrected their request mid-way, adapt your plan accordingly
- The user might change their mind. Always follow the LATEST instruction.
- Respond with valid JSON only, no extra text
"""


def ask_llm(session: dict) -> dict:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    messages = f"User goal: {session['user_goal']}\n\n"

    if session["history"]:
        messages += "History of what happened so far:\n"
        for h in session["history"]:
            messages += f"- {json.dumps(h)}\n"
        messages += "\n"

    if session["data"]:
        messages += f"Data collected so far: {json.dumps(session['data'])}\n\n"

    messages += "What is your next action? JSON only."

    print(f"\n  [Asking LLM...]")

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
        action = json.loads(text)
    except json.JSONDecodeError:
        print(f"  [LLM returned invalid JSON: {text[:100]}]")
        action = {"action": "FINAL_ANSWER", "answer": text}

    print(f"  [LLM decided: {action['action']}", end="")
    if action["action"] == "USE_TOOL":
        print(f" → {action.get('tool')}({action.get('args', {})})", end="")
    print("]")

    return action


# ──────────────────────────────────────────────
# The ReAct loop — now with tools + interrupt
# ──────────────────────────────────────────────

def run_agent(session: dict):
    print("=" * 50)
    print("LEVEL 4: Agent With Tools")
    print(f"Goal: {session['user_goal']}")
    print(f"Tools: {', '.join(TOOLS.keys())}")
    if session["history"]:
        print(f"Resuming from step {len(session['history'])}")
    print("=" * 50)

    if session["status"] == "DONE":
        print("\nThis session is already complete.")
        export_graph(session)
        return

    max_steps = 10
    start_step = len(session["history"])

    for step_num in range(start_step, start_step + max_steps):
        print(f"\n{'='*30} Step {step_num + 1} {'='*30}")

        # 1. REASON
        action = ask_llm(session)

        # 2. ACT
        if action["action"] == "USE_TOOL":
            tool_name = action.get("tool", "")
            tool_args = action.get("args", {})

            if tool_name not in TOOLS:
                result = f"Error: unknown tool '{tool_name}'"
            else:
                result = TOOLS[tool_name]["function"](tool_args, session)

            print(f"  Tool result: {result}")

        elif action["action"] == "ASK_USER":
            question = action.get("question", "Can you clarify?")
            print(f"\n  Agent asks: {question}")
            user_input = input("  Your answer: ")
            result = f"User said: {user_input}"

        elif action["action"] == "FINAL_ANSWER":
            print(f"\n{'='*50}")
            print("AGENT'S FINAL ANSWER:")
            print("=" * 50)
            print(action["answer"])

            session["history"].append({
                "step": step_num + 1,
                "action": "FINAL_ANSWER",
                "result": action["answer"],
            })
            session["status"] = "DONE"
            save_session(session)
            export_graph(session)
            return

        else:
            result = f"Unknown action: {action['action']}"

        # 3. OBSERVE
        session["history"].append({
            "step": step_num + 1,
            "action": action["action"],
            "tool": action.get("tool"),
            "args": action.get("args"),
            "reason": action.get("reason", action.get("question", "")),
            "result": result,
        })
        save_session(session)

    print("\n[Hit max steps.]")
    session["status"] = "DONE"
    save_session(session)
    export_graph(session)


# ──────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────

def main():
    # List all sessions
    if "--list" in sys.argv:
        sessions = list_sessions()
        if not sessions:
            print("No sessions found.")
            return
        print(f"\n{'ID':<10} {'Status':<20} {'Steps':<8} {'Goal'}")
        print("-" * 70)
        for s in sessions:
            print(f"{s['session_id']:<10} {s['status']:<20} {len(s['history']):<8} {s['user_goal'][:40]}")
        return

    # Resume or start new
    session_id = None
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            session_id = arg
            break

    if session_id:
        # ── RESUME with optional correction ──
        session = load_session(session_id)
        print(f"Resumed session: {session_id}")
        print(f"Goal: {session['user_goal']}")
        print(f"Steps completed: {len(session['history'])}")

        if session["history"]:
            last = session["history"][-1]
            print(f"Last action: {last['action']}", end="")
            if last.get("tool"):
                print(f" → {last['tool']}", end="")
            print()

        print()
        correction = input("Add a message before continuing? (enter to skip): ").strip()

        if correction:
            # Inject the correction into history — LLM will see it
            session["history"].append({
                "step": len(session["history"]) + 1,
                "action": "USER_CORRECTION",
                "result": correction,
            })
            save_session(session)
            print(f"  [Added correction to history]")

    else:
        # ── NEW session ──
        print("What do you want help with?")
        goal = input("> ")
        session = create_session(goal)

    run_agent(session)


if __name__ == "__main__":
    main()
