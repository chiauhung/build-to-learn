"""
LEVEL 7: Production — Redis + Plan-First + Compaction + Chat
==============================================================

What changed from Level 6:
  - State is stored in Redis (with JSON file fallback if Redis isn't running)
  - Multiple sessions can run independently
  - Sessions expire after 1 hour (TTL)
  - Everything else is the same: plan-first, live status, compaction, chat, tools

Unchanged code (tools, plan display, LLM, compaction) is in base.py.

This is the "full package":
  - Level 1: while loop
  - Level 2: save/load state
  - Level 3: LLM replaces if/else
  - Level 4: tool registry + interrupt
  - Level 5: plan-first + live status
  - Level 6: history compaction + chat mode
  - Level 7: Redis persistence (production-ready)    ← you are here

Setup:
  pip install google-genai matplotlib redis
  docker compose up -d              # start Redis in Docker
  export GEMINI_API_KEY=your_key

Run:
  python main.py                    # start new session (single-shot)
  python main.py --chat             # chat mode (keep going with follow-ups)
  python main.py <session_id>       # resume (with optional correction)
  python main.py --list             # list all sessions
"""

import json
import os
import sys
import uuid

from base import (
    TOOLS, COMPACT_THRESHOLD,
    display_plan, ask_llm_for_plan, ask_llm_for_final_answer,
    compact_history,
)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


# ──────────────────────────────────────────────
# NEW: Storage backend — Redis or JSON fallback
# ──────────────────────────────────────────────
# Level 6 uses save_session()/load_session() with JSON files.
# Here we swap in a RedisStore — same interface, different backend.
# If Redis isn't available, falls back to JSON files automatically.

class RedisStore:
    def __init__(self):
        self.client = redis.Redis(host="localhost", port=6379, db=0)
        self.client.ping()
        print("[Storage: Redis]")

    def save(self, session: dict):
        key = f"agent:session:{session['session_id']}"
        self.client.setex(key, 3600, json.dumps(session))

    def load(self, session_id: str) -> dict:
        key = f"agent:session:{session_id}"
        data = self.client.get(key)
        if data is None:
            raise KeyError(f"Session not found: {session_id}")
        return json.loads(data)

    def list_all(self) -> list[dict]:
        keys = self.client.keys("agent:session:*")
        sessions = []
        for key in keys:
            data = self.client.get(key)
            if data:
                sessions.append(json.loads(data))
        return sessions


class JsonStore:
    def __init__(self):
        self.dir = os.path.join(os.path.dirname(__file__), "sessions")
        os.makedirs(self.dir, exist_ok=True)
        print("[Storage: JSON files (Redis not available)]")

    def save(self, session: dict):
        path = os.path.join(self.dir, f"{session['session_id']}.json")
        with open(path, "w") as f:
            json.dump(session, f, indent=2)

    def load(self, session_id: str) -> dict:
        path = os.path.join(self.dir, f"{session_id}.json")
        if not os.path.exists(path):
            raise KeyError(f"Session not found: {session_id}")
        with open(path) as f:
            return json.load(f)

    def list_all(self) -> list[dict]:
        sessions = []
        for f in os.listdir(self.dir):
            if f.endswith(".json"):
                with open(os.path.join(self.dir, f)) as fh:
                    sessions.append(json.load(fh))
        return sessions


def get_store():
    if REDIS_AVAILABLE:
        try:
            return RedisStore()
        except (redis.ConnectionError, redis.exceptions.ConnectionError):
            print("[Redis not running, falling back to JSON files]")
    return JsonStore()


# ──────────────────────────────────────────────
# The execution loop — same as Level 6 but with store
# ──────────────────────────────────────────────
# Only difference: save_session(session) → store.save(session)

def run_one_goal(session: dict, store):
    """Execute a single goal: plan → execute steps → final answer."""
    plan = ask_llm_for_plan(session)
    session["current_plan"] = plan
    store.save(session)

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
            store.save(session)

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
            store.save(session)

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
            store.save(session)
            display_plan(plan, current_index=len(plan))
            return

        compact_history(session)
        if len(session["history"]) <= COMPACT_THRESHOLD:
            pass
        else:
            session["compaction_count"] = session.get("compaction_count", 0) + 1
        store.save(session)

        step_index += 1

        if step_index < len(plan):
            print("  ─────────────────────────────────────────")
            correction = input("  Continue? (enter=yes, or type correction): ").strip()

            if correction and correction.lower() not in ("yes", "y", "ok", "continue"):
                session["history"].append({
                    "step": len(session["history"]) + 1,
                    "action": "USER_CORRECTION",
                    "result": correction,
                })

                compact_history(session)
                store.save(session)

                print(f"\n  [Re-planning with correction: \"{correction}\"]")
                new_plan = ask_llm_for_plan(session)
                completed = plan[:step_index]
                plan = completed + new_plan
                session["current_plan"] = plan
                store.save(session)
                print("  [New plan generated!]")


def run_agent(session: dict, store, chat_mode: bool = False):
    print("=" * 60)
    print(f"LEVEL 7: Production Agent (session: {session['session_id']})"
          + (" (chat mode)" if chat_mode else ""))
    print(f"Goal: {session['user_goal']}")
    print(f"History entries: {len(session['history'])} "
          f"(compacted {session.get('compaction_count', 0)} times)")
    print("=" * 60)

    if session["status"] == "DONE":
        print("\nThis session is already complete.")
        return

    # Execute the first goal
    run_one_goal(session, store)

    if not chat_mode:
        session["status"] = "DONE"
        store.save(session)
        return

    # ── Chat loop — keep going with follow-up questions ──
    while True:
        print()
        print("─" * 60)
        follow_up = input("What else? (enter to quit): ").strip()
        if not follow_up:
            break

        session["user_goal"] = follow_up
        session["status"] = "RUNNING"
        store.save(session)

        print()
        print(f"  [Follow-up: \"{follow_up}\"]")
        print(f"  [History: {len(session['history'])} entries, "
              f"compacted {session.get('compaction_count', 0)} times]")

        run_one_goal(session, store)

    session["status"] = "DONE"
    store.save(session)
    print("\nSession complete. Goodbye!")


# ──────────────────────────────────────────────
# NEW: CLI entry point with --list
# ──────────────────────────────────────────────

def main():
    store = get_store()
    chat_mode = "--chat" in sys.argv

    if "--list" in sys.argv:
        sessions = store.list_all()
        if not sessions:
            print("No sessions found.")
            return
        print(f"\n{'ID':<10} {'Status':<20} {'Steps':<8} {'Goal'}")
        print("-" * 70)
        for s in sessions:
            print(f"{s['session_id']:<10} {s['status']:<20} {len(s['history']):<8} {s['user_goal'][:40]}")
        return

    session_id = None
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            session_id = arg
            break

    if session_id:
        session = store.load(session_id)
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
            session["history"].append({
                "step": len(session["history"]) + 1,
                "action": "USER_CORRECTION",
                "result": correction,
            })
            store.save(session)
            print("  [Added correction to history]")

    else:
        print("What do you want help with?")
        goal = input("> ")
        session_id = str(uuid.uuid4())[:8]
        session = {
            "session_id": session_id,
            "status": "RUNNING",
            "user_goal": goal,
            "data": {},
            "history": [],
            "current_plan": [],
            "compaction_count": 0,
        }
        store.save(session)

    run_agent(session, store, chat_mode=chat_mode)


if __name__ == "__main__":
    main()
