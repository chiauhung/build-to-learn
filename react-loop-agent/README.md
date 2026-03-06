# ReAct Loop Agent — Learn By Building

A step-by-step learning project to understand how AI agents work.

**Core insight:** An agent is just a resumable state machine where the LLM is the decision node.

```
while not done:
    reason(state + history)    # LLM decides what to do
    act(chosen_action)         # call tool / ask user / return answer
    observe(result)            # store result back into state
```

## Structure

Each level is a **complete, runnable script**. Code is intentionally duplicated across levels so you can diff them and see exactly what changed.

```
react-loop-agent/
├── level-1-hardcoded/    # No LLM. Hardcoded steps. Just pause/resume.
├── level-2-state/        # Add session save/load. Kill & resume.
├── level-3-llm/          # Replace if/else with Gemini. This is ReAct.
├── level-4-tools/        # Tool registry + interrupt & re-plan + graph export.
├── level-5-planner/      # Plan-first execution + live status + inline interrupt.
├── level-6-compaction/   # History compaction + chat mode.
├── level-7-redis/        # Production: Redis + plan-first + compaction + chat.
└── level-n-framework/    # Framework versions (Pydantic AI, LangGraph).
```

**Reading tip:** Levels 5-7 split into `main.py` + `base.py`. Open `main.py` first — it only contains the **new** code for that level. `base.py` has the unchanged carried-forward code (tools, session management, etc.).

## How To Learn

### Level 1: The Foundation (`uv run level-1-hardcoded/main.py`)

Simplest possible agent — no save, no resume, just a loop:

```
FETCH_DATA → ASK_USER → GENERATE_REPORT → DONE
   (work)     (pause)       (work)
```

- No setup needed, just run it
- Watch how the `while` loop drives everything
- **Key question:** Where is the state? How does the loop know what to do next?

### Level 2: Save & Resume (`uv run level-2-state/main.py`)

The flow is hardcoded — but now every step saves to disk:

```
FETCH_OVERVIEW → ASK_DEPARTMENT → FETCH_DEPARTMENT → ASK_REPORT_TYPE → GENERATE_REPORT → DONE
    (work)          (pause)           (work)             (pause)            (work)
      ↑               ↑                 ↑                  ↑                  ↑
   kill here?      kill here?        kill here?         kill here?         kill here?
```

- Run it, answer the first question, then **Ctrl+C** at the second question
- Look at the JSON file in `level-2-state/sessions/` — see `current_step` and all saved data
- Resume with `uv run level-2-state/main.py <session_id>` — it picks up exactly where you left off
- **Key question:** What would happen if the server crashed? Can we recover?

### Level 3: LLM Takes Over (`uv run level-3-llm/main.py`)

Same data, same actions — but the LLM decides the order:

```
Level 2 (hardcoded):  FETCH_OVERVIEW → ASK_DEPARTMENT → FETCH_DEPARTMENT → ASK_REPORT → DONE
                      always this exact path, every time

Level 3 (LLM):       ? → ? → ? → ? → FINAL_ANSWER
                      LLM decides each step based on the goal + history
```

- Setup: `uv sync && export GEMINI_API_KEY=your_key`
- Try: `"Give me a report on engineering"` — LLM skips asking, fetches directly
- Try: `"Analyze a department"` — LLM asks which one first
- Try: `"Compare engineering and sales"` — LLM fetches both before answering
- **Key question:** What's the difference from Level 2? (Answer: only `decide_next()` changed)

### Level 4: Tools + Interrupt & Re-plan (`uv run level-4-tools/main.py`)

Actions become modular tools. Plus: interrupt mid-run and change your mind.

```
Run 1:  "Compare sales vs marketing"

  Step 1: USE_TOOL → query_department("sales")
    ↓
  Step 2: USE_TOOL → query_department("marketing")    ← Ctrl+C here!

Resume:  uv run main.py <session_id>
  > Add a message: "Actually, compare sales vs engineering"

  Step 3: USER_CORRECTION: "Actually, compare sales vs engineering"
    ↓
  Step 4: USE_TOOL → query_department("engineering")   ← skips sales, already have it!
    ↓
  Step 5: FINAL_ANSWER
```

- Tools: `query_department`, `calculate`, `list_departments`, `create_bar_chart`
- Try: `"Compare engineering and sales headcount with a chart"` — LLM fetches both, then generates a PNG
- Every run exports an execution trace to `sessions/<id>_graph.txt`
- Charts saved to `sessions/<id>_chart.png`
- **Key question:** How does the LLM know what tools exist? (Answer: we list them in the system prompt)

### Level 5: Plan-First + Live Status (`uv run level-5-planner/main.py`)

LLM generates a **full plan** upfront, then executes with live status. No more Ctrl+C — type corrections inline.

```
> "Compare sales vs marketing with a chart"

  [Plan]
    a. query_department("sales")                    🔄 doing
    b. query_department("marketing")                ⏳ pending
    c. create_bar_chart(...)                         ⏳ pending
    d. FINAL_ANSWER                                  ⏳ pending

  Continue? (enter=yes, or type correction): actually compare sales vs engineering

  [Re-planning...]

  [Plan]
    a. query_department("sales")                    ✅ done
    b. query_department("engineering")              🔄 doing     ← new!
    c. create_bar_chart(...)                         ⏳ pending   ← updated!
    d. FINAL_ANSWER                                  ⏳ pending
```

- **Key question:** What's the difference between Level 4 and 5? (Answer: Level 4 decides one step at a time. Level 5 plans ahead, then executes.)

### Level 6: History Compaction + Chat Mode (`uv run level-6-compaction/main.py`)

When history grows too long (>5 entries), old entries get compacted into a summary:

```
Before compaction:
  [step1, step2, step3, step4, step5, step6, step7]

  [COMPACTING HISTORY...]

After compaction:
  ["Previously: Used query_department. Used calculate...", step5, step6, step7]
```

NEW: `--chat` mode keeps the agent alive for follow-up questions:

```
> uv run main.py --chat
What do you want help with?
> What departments are available?

  [Plan] → [Execute] → FINAL_ANSWER

────────────────────────────────────────────────────────────
What else? (enter to quit): Compare engineering and sales
  [Follow-up, same session, history accumulates...]
  [COMPACTING HISTORY...]  ← compaction kicks in naturally!

What else? (enter to quit):   ← enter to quit
```

- Currently uses a FAKE compactor (just concatenates text)
- In production, an LLM would summarize intelligently
- This is how Claude Code handles long sessions without hitting context limits
- Chat mode naturally demonstrates compaction (longer conversations = more history)
- **Key question:** Why not just keep all history? (Answer: LLM context window has a limit)

### Level 7: Production — Redis (`uv run level-7-redis/main.py`)

The full package: plan-first + compaction + chat + Redis. Same pattern, production backend.

```
docker compose up -d          # start Redis
uv run main.py               # new session → saved to Redis
uv run main.py --chat        # chat mode with Redis persistence
uv run main.py --list        # list all sessions from Redis
uv run main.py <id>          # resume from Redis (with optional correction)
```

- `cd level-7-redis && docker compose up -d`
- Works without Redis too (falls back to JSON files)
- **Key question:** How would you turn this into a web API? (Answer: replace `input()` with FastAPI endpoints)

## What To Diff

The real learning is in seeing what changed between levels:

```bash
diff level-1-hardcoded/main.py level-2-state/main.py    # added: save/load
diff level-2-state/main.py level-3-llm/main.py           # added: LLM replaces if/else
diff level-3-llm/main.py level-4-tools/main.py           # added: tool registry + executor
diff level-4-tools/main.py level-5-planner/main.py       # added: plan-first + live status
diff level-5-planner/main.py level-6-compaction/main.py  # added: history compaction
diff level-6-compaction/main.py level-7-redis/main.py    # added: Redis storage backend
```

## What You've Learned (and What's Next)

After running all 7 levels, you understand the core mechanics:

| Concept | Where you built it |
|---|---|
| ReAct loop (Reason → Act → Observe) | Level 3-7 |
| State persistence & resumability | Level 2-7 |
| Tool registry + dynamic dispatch | Level 4-7 |
| Plan-first vs step-by-step execution | Level 4 vs 5 |
| History compaction / context management | Level 6 |
| Multi-turn chat with accumulated state | Level 6-7 |
| Production persistence (Redis + fallback) | Level 7 |
| Framework vs manual tradeoffs | Level N |

### Beyond the basics — what production agents also need

**1. Structured output / native function calling**
Our agent uses "LLM outputs JSON text → we parse it". Production agents use the model's **native tool-calling API** (OpenAI function calling, Anthropic tool use, Gemini function declarations). Native tool calling is more reliable than JSON-in-text parsing — no more ````json` stripping hacks.

**2. Streaming**
Our agent waits for the full LLM response before showing anything. Real agents stream tokens to the user while generating. This uses SSE (Server-Sent Events) or WebSockets.

**3. Error handling & retries**
What happens when the LLM returns garbage JSON? When a tool times out? When the API rate-limits you? Production agents need retry strategies, exponential backoff, and graceful degradation. (We saw this firsthand — the LLM sometimes returns `"action": "CREATE_BAR_CHART"` instead of `"action": "USE_TOOL"`.)

**4. Guardrails & safety**
How do you prevent the agent from doing dangerous things? Input validation, output filtering, tool permission scoping, human-in-the-loop approval for sensitive actions.

**5. Evaluation & testing**
How do you know your agent is good? LLM evals are hard. Key approaches: benchmark datasets, human evaluation, automated scoring (LLM-as-judge), regression testing for agent behavior.

**6. RAG (Retrieval-Augmented Generation)**
Our tools return hardcoded data. In production, tools often search vector databases or document stores. This involves embeddings, chunking strategies, and retrieval pipelines.

**7. Multi-agent orchestration**
Our agent is a single loop. What about multiple agents collaborating? Supervisor patterns, handoffs, shared state. This is where LangGraph actually shines over simpler frameworks.

**8. Observability & tracing**
How do you debug a 20-step agent run in production? Tools like LangSmith, Phoenix, or Arize let you trace each LLM call with inputs/outputs/latency/cost. Our Level 4 graph export is a primitive version of this.

**9. Cost management**
Each LLM call costs money. Our compaction helps, but also consider: model routing (cheap model for easy tasks, expensive for hard ones), response caching, and prompt optimization.

**10. When NOT to use an agent**
The most important question: "When do you need an agent vs just a good prompt?" Answer: agents are for tasks that require **multiple steps with external data**, **dynamic decision-making**, or **tool use**. If one prompt can do it, don't build an agent.

## Setup

```bash
cd react-loop-agent
uv sync
export GEMINI_API_KEY=your_key  # needed from Level 3 onward
```

- Level 1-2: no API key needed
- Level 7: also needs Docker for Redis (`cd level-7-redis && docker compose up -d`)
