"""
LEVEL 2: Session State Management
===================================

What changed from Level 1:
  - State is saved to a JSON file after every step
  - If you kill the program mid-run, you can RESUME from where you left off
  - Session has an ID (so multiple agents could run independently)
  - Multiple pause points so you can kill & resume at different stages

This is the "checkpoint" concept from the learning doc.
Think of it like Airflow saving task status — if a DAG fails,
it resumes from the failed task, not from the beginning.

Run:
  python main.py              # start new session
  python main.py <session_id> # resume existing session

Try this:
  1. Run `python main.py`
  2. Answer the first question (pick a department)
  3. When it asks the SECOND question, press Ctrl+C to kill it
  4. Look at the JSON file in ./sessions/ — see where it stopped
  5. Run `python main.py <session_id>` to resume from that exact point!
"""

import json
import os
import time
import uuid
import sys


# ──────────────────────────────────────────────
# Session Manager — this is the new part
# ──────────────────────────────────────────────

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def create_session() -> dict:
    """Create a new session with a unique ID."""
    session_id = str(uuid.uuid4())[:8]
    session = {
        "session_id": session_id,
        "status": "RUNNING",
        "current_step": "FETCH_OVERVIEW",
        "data": {},
        "history": [],
    }
    save_session(session)
    print(f"Created new session: {session_id}")
    return session


def save_session(session: dict):
    """Save session state to a JSON file. This is our checkpoint."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session['session_id']}.json")
    with open(path, "w") as f:
        json.dump(session, f, indent=2)
    print(f"  [saved state → step: {session['current_step']}]")


def load_session(session_id: str) -> dict:
    """Load session state from disk. This is our resume."""
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No session found: {session_id}")
    with open(path) as f:
        session = json.load(f)
    print(f"Resumed session: {session_id} (step: {session['current_step']})")
    return session


# ──────────────────────────────────────────────
# Agent logic — 5 steps, 2 pause points
# ──────────────────────────────────────────────
#
# Flow:
#   FETCH_OVERVIEW → ASK_DEPARTMENT → FETCH_DEPARTMENT → ASK_REPORT_TYPE → GENERATE_REPORT
#        (work)        (pause #1)         (work)            (pause #2)         (work)
#
# Kill at pause #1 → resumes at ASK_DEPARTMENT (overview data still there)
# Kill at pause #2 → resumes at ASK_REPORT_TYPE (department data still there)

def run_agent(session: dict):
    print("=" * 50)
    print("LEVEL 2: Stateful Agent (with save/resume)")
    print("=" * 50)

    while session["status"] != "DONE":

        step = session["current_step"]
        print(f"\n--- Step: {step} ---")

        # ──────────────────────────────────────────
        # Step 1: Fetch company overview (work)
        # ──────────────────────────────────────────
        if step == "FETCH_OVERVIEW":
            print("Fetching company overview...")
            time.sleep(1)

            session["data"]["overview"] = {
                "total_users": 1523,
                "departments": ["engineering", "sales", "marketing"],
            }
            session["history"].append("Fetched company overview")
            session["current_step"] = "ASK_DEPARTMENT"
            save_session(session)

        # ──────────────────────────────────────────
        # Step 2: Ask which department (PAUSE #1)
        # ──────────────────────────────────────────
        elif step == "ASK_DEPARTMENT":
            depts = session["data"]["overview"]["departments"]
            print(f"Available departments: {', '.join(depts)}")
            print()

            if "department" not in session["data"]:
                user_input = input("Which department do you want to analyze? ")
                session["data"]["department"] = user_input.strip().lower()
                session["history"].append(f"User chose department: {session['data']['department']}")

            session["current_step"] = "FETCH_DEPARTMENT"
            save_session(session)

        # ──────────────────────────────────────────
        # Step 3: Fetch department data (work)
        # ──────────────────────────────────────────
        elif step == "FETCH_DEPARTMENT":
            dept = session["data"]["department"]
            print(f"Fetching data for {dept}...")
            time.sleep(1)

            # Simulate different data per department
            dept_data = {
                "engineering": {"headcount": 84, "active_today": 72, "new_hires": 5, "avg_tenure_months": 18},
                "sales":       {"headcount": 45, "active_today": 38, "new_hires": 8, "avg_tenure_months": 12},
                "marketing":   {"headcount": 32, "active_today": 28, "new_hires": 3, "avg_tenure_months": 24},
            }
            session["data"]["department_data"] = dept_data.get(dept, {
                "headcount": 20, "active_today": 15, "new_hires": 2, "avg_tenure_months": 14,
            })
            session["history"].append(f"Fetched {dept} department data")
            session["current_step"] = "ASK_REPORT_TYPE"
            save_session(session)

        # ──────────────────────────────────────────
        # Step 4: Ask report type (PAUSE #2)
        # ──────────────────────────────────────────
        elif step == "ASK_REPORT_TYPE":
            dept = session["data"]["department"]
            data = session["data"]["department_data"]
            print(f"Department: {dept}")
            print(f"Data: {json.dumps(data, indent=2)}")
            print()

            if "report_type" not in session["data"]:
                user_input = input("What kind of report? (summary / detailed): ")
                session["data"]["report_type"] = user_input.strip().lower()
                session["history"].append(f"User chose report type: {session['data']['report_type']}")

            session["current_step"] = "GENERATE_REPORT"
            save_session(session)

        # ──────────────────────────────────────────
        # Step 5: Generate report (work)
        # ──────────────────────────────────────────
        elif step == "GENERATE_REPORT":
            report_type = session["data"]["report_type"]
            dept = session["data"]["department"]
            data = session["data"]["department_data"]

            if report_type == "detailed":
                report = (
                    f"DETAILED REPORT — {dept.upper()}\n"
                    f"{'=' * 35}\n"
                    f"Headcount:       {data['headcount']}\n"
                    f"Active today:    {data['active_today']} "
                    f"({data['active_today']/data['headcount']*100:.1f}%)\n"
                    f"New hires:       {data['new_hires']}\n"
                    f"Avg tenure:      {data['avg_tenure_months']} months\n"
                    f"Inactive today:  {data['headcount'] - data['active_today']}"
                )
            else:
                report = (
                    f"SUMMARY — {dept.upper()}: "
                    f"{data['active_today']}/{data['headcount']} active today, "
                    f"{data['new_hires']} new hires, "
                    f"avg tenure {data['avg_tenure_months']}mo."
                )

            session["data"]["report"] = report
            session["history"].append("Generated report")
            session["status"] = "DONE"
            save_session(session)

    # ──────────────────────────────────────────
    # Done — print results
    # ──────────────────────────────────────────
    print("\n" + "=" * 50)
    print("RESULT:")
    print("=" * 50)
    print(session["data"]["report"])
    print()
    print("History (everything that happened):")
    for i, h in enumerate(session["history"], 1):
        print(f"  {i}. {h}")


# ──────────────────────────────────────────────
# Entry point: start new or resume existing
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Resume existing session
        session = load_session(sys.argv[1])
    else:
        # Start fresh
        session = create_session()

    run_agent(session)
