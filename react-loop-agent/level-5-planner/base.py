"""
Carried forward from Level 4 — tools + session management.
Open this file only if you want to see the unchanged parts.
The new stuff is in main.py.
"""

import json
import os
import time
import uuid

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


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
# Session management (same as Level 4)
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
        "current_plan": [],
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
