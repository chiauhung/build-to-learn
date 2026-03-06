"""
LEVEL 6: History Compaction + Chat Mode
==========================================

What changed from Level 5:
  - When history exceeds a threshold (5 entries), old entries get COMPACTED
  - Compaction = summarize old history into a short summary + keep recent entries
  - This prevents the LLM context window from blowing up in long sessions
  - Currently uses a FAKE compactor (just concatenates). In production, you'd
    use an LLM to summarize.
  - NEW: --chat mode keeps the agent alive for follow-up questions

Unchanged code (tools, session mgmt, plan display, LLM) is in base.py.

Why this matters:
  - LLMs have a context window limit (e.g. 128k tokens)
  - Each step adds to history: tool calls, results, user messages
  - After 50+ steps, history can be huge
  - Compaction keeps it small while preserving important info

How Claude Code does it:
  - It periodically summarizes older conversation turns
  - Recent turns stay detailed, old turns become a summary
  - This is why long Claude Code sessions don't slow down

Setup:
  pip install google-genai matplotlib
  export GEMINI_API_KEY=your_key_here

Run:
  python main.py             # single-shot mode (one goal, then done)
  python main.py --chat      # chat mode (keep going with follow-ups)

Try this (--chat mode):
  1. Ask: "What departments are available?"
  2. Then: "Compare engineering and sales"
  3. Then: "Now add marketing and make a chart"
  4. Watch history grow → compaction kicks in → old steps summarized
  5. Check the session JSON — see COMPACTED_SUMMARY entries
"""

import json
import sys

from base import (
    TOOLS, create_session, load_session, save_session,
    display_plan, ask_llm_for_plan, ask_llm_for_final_answer,
)


# ──────────────────────────────────────────────
# NEW: History Compaction
# ──────────────────────────────────────────────
#
# When history gets too long, we:
#   1. Take old entries (all except the most recent KEEP_RECENT ones)
#   2. Summarize them into a single "COMPACTED_SUMMARY" entry
#   3. Replace the old entries with the summary
#
# Before compaction:
#   [step1, step2, step3, step4, step5, step6, step7]
#
# After compaction (KEEP_RECENT=3):
#   [summary_of_1_2_3_4, step5, step6, step7]

COMPACT_THRESHOLD = 5   # compact when history has more than this many entries
KEEP_RECENT = 3          # keep this many recent entries un-compacted


def compact_history(session: dict):
    """
    Compact old history entries into a summary.

    Currently FAKE — just concatenates old entries into a text summary.
    In production, you'd call an LLM to summarize intelligently.
    """
    history = session["history"]

    if len(history) <= COMPACT_THRESHOLD:
        return  # nothing to compact

    print()
    print("  " + "=" * 50)
    print("  [COMPACTING HISTORY...]")
    print(f"  Before: {len(history)} entries")

    # Split: old entries to compact, recent to keep
    old_entries = history[:-KEEP_RECENT]
    recent_entries = history[-KEEP_RECENT:]

    # ── FAKE COMPACTION ──
    # In production, replace this with:
    #   summary = ask_llm(f"Summarize these steps: {old_entries}")
    #
    # For now, we just concatenate the key info:
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
            # Already compacted before — carry forward
            summary_parts.append(entry.get("summary", ""))
        else:
            summary_parts.append(f"{action}: {entry.get('result', '?')}")

    summary_text = "Previously: " + ". ".join(summary_parts) + "."

    # Create the compacted entry
    compacted_entry = {
        "action": "COMPACTED_SUMMARY",
        "summary": summary_text,
        "compacted_count": len(old_entries),
    }

    # Replace history
    session["history"] = [compacted_entry] + recent_entries

    print(f"  After:  {len(session['history'])} entries "
          f"(1 summary + {len(recent_entries)} recent)")
    print(f"  Summary: \"{summary_text[:80]}...\"")
    print("  " + "=" * 50)
    print()


# ──────────────────────────────────────────────
# The execution loop — plan + execute + COMPACT
# ──────────────────────────────────────────────
# Same as Level 5, but with compact_history()
# called after each step.

def run_one_goal(session: dict):
    """Execute a single goal: plan → execute steps → final answer."""
    plan = ask_llm_for_plan(session)
    session["current_plan"] = plan
    save_session(session)

    display_plan(plan, current_index=0)

    step_index = 0

    while step_index < len(plan):
        step = plan[step_index]
        action = step.get("action", "")

        display_plan(plan, current_index=step_index)

        # Handle tool calls — LLM sometimes returns "USE_TOOL" or the tool
        # name itself (e.g. "CREATE_BAR_CHART"). If the step has a "tool" field,
        # treat it as a tool call regardless of the action name.
        if action == "USE_TOOL" or (step.get("tool") and action != "FINAL_ANSWER"):
            tool_name = step.get("tool", "")
            tool_args = step.get("args", {})
            if tool_name not in TOOLS:
                result = f"Error: unknown tool '{tool_name}'"
            else:
                result = TOOLS[tool_name]["function"](tool_args, session)

            session["history"].append({
                "step": len(session["history"]) + 1,
                "action": "USE_TOOL",
                "tool": tool_name,
                "args": tool_args,
                "result": result,
            })
            save_session(session)

        elif action == "ASK_USER":
            question = step.get("question", "Can you clarify?")
            print(f"    Agent asks: {question}")
            user_input = input("    Your answer: ")
            session["history"].append({
                "step": len(session["history"]) + 1,
                "action": "ASK_USER",
                "question": question,
                "result": f"User said: {user_input}",
            })
            save_session(session)

        elif action == "FINAL_ANSWER":
            print("    Generating final answer...")
            answer = ask_llm_for_final_answer(session)
            print(f"\n{'='*60}")
            print("AGENT'S FINAL ANSWER:")
            print("=" * 60)
            print(answer)
            session["history"].append({
                "step": len(session["history"]) + 1,
                "action": "FINAL_ANSWER",
                "result": answer,
            })
            save_session(session)
            display_plan(plan, current_index=len(plan))
            return

        # ── COMPACT HISTORY if needed ──
        compact_history(session)
        if len(session["history"]) <= COMPACT_THRESHOLD:
            pass
        else:
            session["compaction_count"] = session.get("compaction_count", 0) + 1
        save_session(session)

        step_index += 1

        # Inline interrupt (same as Level 5)
        if step_index < len(plan):
            print("  ─────────────────────────────────────────")
            correction = input("  Continue? (enter=yes, or type correction): ").strip()

            if correction and correction.lower() not in ("yes", "y", "ok", "continue"):
                session["history"].append({
                    "step": len(session["history"]) + 1,
                    "action": "USER_CORRECTION",
                    "result": correction,
                })

                # Compact again if the correction pushed us over
                compact_history(session)
                save_session(session)

                print(f"\n  [Re-planning with correction: \"{correction}\"]")
                new_plan = ask_llm_for_plan(session)
                completed = plan[:step_index]
                plan = completed + new_plan
                session["current_plan"] = plan
                save_session(session)
                print("  [New plan generated!]")


def run_agent(session: dict, chat_mode: bool = False):
    print("=" * 60)
    print("LEVEL 6: Plan-First Agent + History Compaction"
          + (" (chat mode)" if chat_mode else ""))
    print(f"Goal: {session['user_goal']}")
    print(f"History entries: {len(session['history'])} "
          f"(compacted {session.get('compaction_count', 0)} times)")
    print("=" * 60)

    if session["status"] == "DONE":
        print("\nThis session is already complete.")
        return

    # Execute the first goal
    run_one_goal(session)

    if not chat_mode:
        session["status"] = "DONE"
        save_session(session)
        return

    # ── NEW: Chat loop — keep going with follow-up questions ──
    # After the agent finishes, ask "What else?" and loop.
    # Each follow-up becomes a new goal on the SAME session,
    # so history + data accumulate → compaction kicks in naturally.
    while True:
        print()
        print("─" * 60)
        follow_up = input("What else? (enter to quit): ").strip()
        if not follow_up:
            break

        # Update the goal and re-open the session
        session["user_goal"] = follow_up
        session["status"] = "RUNNING"
        save_session(session)

        print()
        print(f"  [Follow-up: \"{follow_up}\"]")
        print(f"  [History: {len(session['history'])} entries, "
              f"compacted {session.get('compaction_count', 0)} times]")

        run_one_goal(session)

    session["status"] = "DONE"
    save_session(session)
    print("\nSession complete. Goodbye!")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main():
    chat_mode = "--chat" in sys.argv

    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        session = load_session(sys.argv[1])
    else:
        print("What do you want help with?")
        goal = input("> ")
        session = create_session(goal)

    run_agent(session, chat_mode=chat_mode)


if __name__ == "__main__":
    main()
