"""
LEVEL 5: Plan-First Execution + Live Status + Inline Interrupt
================================================================

What changed from Level 4:
  - LLM generates a FULL PLAN upfront (not one step at a time)
  - Plan is displayed with live status: done / doing / pending
  - After each step, you can type a correction WITHOUT killing the process
  - If you correct, LLM re-plans from current state → new steps appear

Unchanged code (tools, session mgmt) is in base.py.

This is how Claude Code works:
  1. You ask something
  2. It shows you what it's going to do (the plan)
  3. It executes step by step, showing progress
  4. If you interrupt, it re-plans

Setup:
  pip install google-genai matplotlib
  export GEMINI_API_KEY=your_key_here

Run:
  python main.py

Try this:
  1. Ask: "Compare sales vs marketing with a chart"
  2. Watch the plan appear, then steps execute with live status
  3. After step 1 finishes, type: "actually compare sales vs engineering"
  4. Watch the plan update — LLM keeps what's done, replans the rest
"""

import json
import os
import sys

from google import genai

from base import TOOLS, create_session, load_session, save_session


# ──────────────────────────────────────────────
# NEW: Plan display — live status
# ──────────────────────────────────────────────

def display_plan(plan: list[dict], current_index: int):
    """
    Print the plan with status indicators.

    Example output:
      [Plan]
        a. query_department("sales")          ✅ done
        b. query_department("marketing")      🔄 doing
        c. create_bar_chart(...)              ⏳ pending
        d. FINAL_ANSWER                       ⏳ pending
    """
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
            status = "done"
            indicator = "\u2705"
        elif i == current_index:
            status = "doing"
            indicator = "\U0001f504"
        else:
            status = "pending"
            indicator = "\u23f3"

        print(f"    {letter}. {label:<58} {indicator} {status}")

    print()


# ──────────────────────────────────────────────
# NEW: LLM generates a FULL PLAN (not one step)
# ──────────────────────────────────────────────
# Level 4 asked the LLM "what's the next step?" one at a time.
# Now we ask "give me the FULL plan" upfront.

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
{{"action": "FINAL_ANSWER", "answer": "placeholder — will be filled after data is collected"}}

Rules:
- Return a JSON array of steps, e.g. [{{"action": "USE_TOOL", ...}}, {{"action": "FINAL_ANSWER", ...}}]
- The last step should always be FINAL_ANSWER
- Look at history — don't re-do steps that are already done
- If the user corrected their request, adapt the plan accordingly
- For FINAL_ANSWER, put "placeholder" as the answer — you'll fill it in when you get there
- Respond with valid JSON array only, no extra text
"""


def ask_llm_for_plan(session: dict) -> list[dict]:
    """Ask LLM to generate a full plan (list of steps)."""
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
        print("  [LLM returned invalid JSON, falling back to single answer]")
        return [{"action": "FINAL_ANSWER", "answer": text}]


def ask_llm_for_final_answer(session: dict) -> str:
    """Ask LLM to generate the final answer based on all collected data."""
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    messages = f"User goal: {session['user_goal']}\n\n"
    messages += f"Data collected: {json.dumps(session['data'])}\n\n"

    if session["history"]:
        messages += "History:\n"
        for h in session["history"]:
            messages += f"- {json.dumps(h)}\n"
        messages += "\n"

    messages += "Based on all the data collected, provide your final answer to the user's goal. Respond with plain text, not JSON."

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=messages,
        config=genai.types.GenerateContentConfig(
            system_instruction="You are a helpful data analyst. Give a clear, concise answer based on the data provided.",
            temperature=0,
        ),
    )

    return response.text.strip()


# ──────────────────────────────────────────────
# NEW: The execution loop — plan then execute
# ──────────────────────────────────────────────
# Level 4 asked the LLM one step at a time.
# Now we get the FULL plan upfront, display it,
# and execute with live status + inline interrupt.

def run_agent(session: dict):
    print("=" * 60)
    print("LEVEL 5: Plan-First Agent")
    print(f"Goal: {session['user_goal']}")
    print("=" * 60)

    if session["status"] == "DONE":
        print("\nThis session is already complete.")
        return

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
            session["status"] = "DONE"
            save_session(session)

            display_plan(plan, current_index=len(plan))
            return

        step_index += 1

        # ── INLINE INTERRUPT: ask user before continuing ──
        if step_index < len(plan):
            print("  ─────────────────────────────────────────")
            correction = input("  Continue? (enter=yes, or type correction): ").strip()

            if correction and correction.lower() not in ("yes", "y", "ok", "continue"):
                session["history"].append({
                    "step": len(session["history"]) + 1,
                    "action": "USER_CORRECTION",
                    "result": correction,
                })
                save_session(session)

                print(f"\n  [Re-planning with correction: \"{correction}\"]")

                new_plan = ask_llm_for_plan(session)

                completed = plan[:step_index]
                plan = completed + new_plan
                session["current_plan"] = plan
                save_session(session)

                print("  [New plan generated!]")

    session["status"] = "DONE"
    save_session(session)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def main():
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        session = load_session(sys.argv[1])
    else:
        print("What do you want help with?")
        goal = input("> ")
        session = create_session(goal)

    run_agent(session)


if __name__ == "__main__":
    main()
