"""
LEVEL 1: Hardcoded Pause/Resume Workflow
=========================================

Goal: Prove you can build a workflow that:
  - runs step by step
  - PAUSES when it needs user input
  - RESUMES from where it left off

No LLM. No magic. Just a while loop + state.

Run:
  python main.py
"""

import json
import time


def run_agent():
    """
    This is the simplest possible "agent".

    It has 3 hardcoded steps:
      1. Fetch some data (simulated)
      2. Ask the user a question (PAUSE here)
      3. Generate a report using the user's answer

    The key insight: the while loop doesn't know the steps in advance.
    It asks "what's next?" each iteration — just like a real agent would.
    """

    # This is our "state". Everything the agent knows lives here.
    state = {
        "status": "RUNNING",
        "current_step": "FETCH_DATA",
        "data": {},
        "history": [],  # track what happened
    }

    print("=" * 50)
    print("LEVEL 1: Hardcoded Agent")
    print("=" * 50)

    # === THE LOOP ===
    # This is the core pattern. Every agent, no matter how fancy, is this loop.
    while state["status"] != "DONE":

        step = state["current_step"]
        print(f"\n--- Step: {step} ---")

        # ──────────────────────────────────────────────
        # Step 1: Fetch data (simulate)
        # ──────────────────────────────────────────────
        if step == "FETCH_DATA":
            print("Fetching data from database...")
            time.sleep(1)  # pretend we're doing work

            # Store result in state
            state["data"]["query_result"] = {
                "total_users": 1523,
                "active_today": 342,
                "new_signups": 28,
            }
            state["history"].append("Fetched user data")

            # Decide next step
            state["current_step"] = "ASK_USER"

        # ──────────────────────────────────────────────
        # Step 2: Ask user — THIS IS THE PAUSE
        # ──────────────────────────────────────────────
        elif step == "ASK_USER":
            print(f"Data so far: {json.dumps(state['data']['query_result'], indent=2)}")
            print()

            # PAUSE: wait for user input
            user_input = input("What kind of report do you want? (summary / detailed): ")

            # Store user's answer in state
            state["data"]["report_type"] = user_input.strip().lower()
            state["history"].append(f"User chose: {user_input}")

            # Decide next step
            state["current_step"] = "GENERATE_REPORT"

        # ──────────────────────────────────────────────
        # Step 3: Generate report
        # ──────────────────────────────────────────────
        elif step == "GENERATE_REPORT":
            report_type = state["data"]["report_type"]
            data = state["data"]["query_result"]

            if report_type == "detailed":
                report = (
                    f"DETAILED REPORT\n"
                    f"===============\n"
                    f"Total users:    {data['total_users']}\n"
                    f"Active today:   {data['active_today']} "
                    f"({data['active_today']/data['total_users']*100:.1f}%)\n"
                    f"New signups:    {data['new_signups']}\n"
                    f"Churn risk:     {data['total_users'] - data['active_today']} inactive"
                )
            else:
                report = (
                    f"SUMMARY: {data['active_today']} of {data['total_users']} "
                    f"users active today, {data['new_signups']} new signups."
                )

            state["data"]["report"] = report
            state["history"].append("Generated report")

            # We're done
            state["status"] = "DONE"

        else:
            print(f"Unknown step: {step}")
            state["status"] = "DONE"

    # === DONE ===
    print("\n" + "=" * 50)
    print("RESULT:")
    print("=" * 50)
    print(state["data"]["report"])
    print()
    print("History of what happened:")
    for i, h in enumerate(state["history"], 1):
        print(f"  {i}. {h}")


if __name__ == "__main__":
    run_agent()
