"""
LEVEL 3: LLM Decides What To Do Next
======================================

What changed from Level 2:
  - No more hardcoded steps!
  - The LLM (Gemini) decides what the next action should be
  - The LLM outputs a structured action: FETCH_OVERVIEW, FETCH_DEPARTMENT, ASK_USER, or FINAL_ANSWER
  - We parse the LLM's response and execute it

This is the "ReAct loop":
  1. REASON: LLM looks at state + history and decides next action
  2. ACT:    We execute that action
  3. OBSERVE: We store the result back into state
  ... repeat until LLM says FINAL_ANSWER

Compare with Level 2:
  Level 2 hardcodes: FETCH_OVERVIEW → ASK_DEPARTMENT → FETCH_DEPARTMENT → ASK_REPORT_TYPE → GENERATE_REPORT
  Level 3: LLM decides the flow. It might ask questions first, or fetch data first, or skip steps entirely.

Setup:
  pip install google-genai

  export GEMINI_API_KEY=your_key_here
  # Get one free at: https://aistudio.google.com/apikey

Run:
  python main.py              # start new session
  python main.py <session_id> # resume existing session

Try these goals:
  - "Give me a detailed report on the engineering department"
    (watch: LLM fetches overview → fetches engineering → generates report, no questions needed)
  - "Analyze a department for me"
    (watch: LLM asks WHICH department first, then fetches data)
  - "Compare engineering and sales"
    (watch: LLM fetches both departments before answering)
"""

import json
import os
import sys
import time
import uuid

from google import genai

# ──────────────────────────────────────────────
# Session management (same as Level 2)
# ──────────────────────────────────────────────

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def create_session(user_goal: str) -> dict:
    session_id = str(uuid.uuid4())[:8]
    session = {
        "session_id": session_id,
        "status": "RUNNING",
        "user_goal": user_goal,
        "data": {},
        "history": [],  # list of {"step": ..., "action": ..., "result": ...}
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
    with open(path) as f:
        return json.load(f)


# ──────────────────────────────────────────────
# The LLM "brain" — this replaces hardcoded if/else
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are a helpful data analyst agent. The user will give you a goal.
You must accomplish it step by step.

At each step, you MUST respond with EXACTLY ONE action in this JSON format:

{"action": "FETCH_OVERVIEW", "reason": "why you need the company overview"}
or
{"action": "FETCH_DEPARTMENT", "department": "engineering", "reason": "why you need this department's data"}
or
{"action": "ASK_USER", "question": "what you want to ask the user"}
or
{"action": "FINAL_ANSWER", "answer": "your final response to the user"}

Available data:
- FETCH_OVERVIEW: returns company-wide metrics (total users, list of departments)
- FETCH_DEPARTMENT: returns metrics for a specific department (headcount, active today, new hires, avg tenure)
  Valid departments: engineering, sales, marketing

Rules:
- Use FETCH_OVERVIEW first if you need to know what departments exist
- Use FETCH_DEPARTMENT to get data for a specific department
- Use ASK_USER if you need clarification from the user (e.g. which department, what report format)
- Use FINAL_ANSWER when you have enough info to fully answer the user's goal
- Always respond with valid JSON only. No extra text.
- Look at the history to see what already happened. Don't repeat actions.
"""


def ask_llm(session: dict) -> dict:
    """
    Send the current state to Gemini and get back the next action.

    This is the REASON step of ReAct.
    """
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    # Build the conversation for the LLM
    messages = f"User goal: {session['user_goal']}\n\n"

    if session["history"]:
        messages += "History of what happened so far:\n"
        for h in session["history"]:
            messages += f"- {json.dumps(h)}\n"
        messages += "\n"

    if session["data"]:
        messages += f"Data collected so far: {json.dumps(session['data'])}\n\n"

    messages += "What is your next action? Respond with JSON only."

    print(f"\n  [Asking LLM: what should I do next?]")

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=messages,
        config=genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
        ),
    )

    # Parse the LLM's response as JSON
    text = response.text.strip()
    # Sometimes LLM wraps in ```json ... ```, strip that
    if text.startswith("```"):
        text = text.split("\n", 1)[1]  # remove first line
        text = text.rsplit("```", 1)[0]  # remove last ```
        text = text.strip()

    try:
        action = json.loads(text)
    except json.JSONDecodeError:
        print(f"  [LLM returned invalid JSON: {text}]")
        action = {"action": "FINAL_ANSWER", "answer": text}

    print(f"  [LLM decided: {action['action']}]")
    return action


# ──────────────────────────────────────────────
# Action executors — the ACT step
# ──────────────────────────────────────────────
# These are the same "steps" from Level 2, but now the LLM
# chooses which one to run and in what order.

def execute_fetch_overview(session: dict, action: dict) -> str:
    """Fetch company overview data."""
    print("  Fetching company overview...")
    time.sleep(1)
    data = {
        "total_users": 1523,
        "departments": ["engineering", "sales", "marketing"],
    }
    session["data"]["overview"] = data
    return f"Fetched overview: {json.dumps(data)}"


def execute_fetch_department(session: dict, action: dict) -> str:
    """Fetch data for a specific department."""
    dept = action.get("department", "engineering").lower()
    print(f"  Fetching {dept} department data...")
    time.sleep(1)

    dept_data = {
        "engineering": {"headcount": 84, "active_today": 72, "new_hires": 5, "avg_tenure_months": 18},
        "sales":       {"headcount": 45, "active_today": 38, "new_hires": 8, "avg_tenure_months": 12},
        "marketing":   {"headcount": 32, "active_today": 28, "new_hires": 3, "avg_tenure_months": 24},
    }
    data = dept_data.get(dept, {"error": f"Unknown department: {dept}"})

    # Store under department name so multiple departments can be fetched
    if "departments" not in session["data"]:
        session["data"]["departments"] = {}
    session["data"]["departments"][dept] = data

    return f"Fetched {dept} data: {json.dumps(data)}"


def execute_ask_user(session: dict, action: dict) -> str:
    """Ask the user a question and return their response."""
    question = action.get("question", "Can you clarify?")
    print(f"\n  Agent asks: {question}")
    user_input = input("  Your answer: ")
    return f"User said: {user_input}"


# ──────────────────────────────────────────────
# The main loop — this is ReAct
# ──────────────────────────────────────────────

def run_agent(session: dict):
    print("=" * 50)
    print("LEVEL 3: LLM-Powered Agent (Gemini)")
    print(f"Goal: {session['user_goal']}")
    print("=" * 50)

    max_steps = 10  # safety limit so we don't loop forever

    # Start from where we left off (for resumed sessions)
    start_step = len(session["history"])

    for step_num in range(start_step, start_step + max_steps):
        print(f"\n{'='*30} Step {step_num + 1} {'='*30}")

        # 1. REASON: ask LLM what to do
        action = ask_llm(session)

        # 2. ACT: execute the action
        if action["action"] == "FETCH_OVERVIEW":
            result = execute_fetch_overview(session, action)

        elif action["action"] == "FETCH_DEPARTMENT":
            result = execute_fetch_department(session, action)

        elif action["action"] == "ASK_USER":
            result = execute_ask_user(session, action)

        elif action["action"] == "FINAL_ANSWER":
            # We're done!
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
            return

        else:
            result = f"Unknown action: {action['action']}"

        # 3. OBSERVE: store result in history
        session["history"].append({
            "step": step_num + 1,
            "action": action["action"],
            "reason": action.get("reason", action.get("question", "")),
            "result": result,
        })
        save_session(session)

        print(f"  Result: {result}")

    print("\n[Agent hit max steps limit. Stopping.]")
    session["status"] = "DONE"
    save_session(session)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        # Resume existing session
        session = load_session(sys.argv[1])
    else:
        # Start new session
        print("What do you want the agent to help with?")
        goal = input("> ")
        session = create_session(goal)

    run_agent(session)
