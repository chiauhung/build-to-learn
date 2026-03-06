# Framework → Level 1-7 Mapping

Come back here AFTER you've run Level 1-7. This maps every part of the
framework code (app.py) back to what you built by hand.

---

## The ReAct Loop

**What you built (Level 4):**
```python
while not done:
    action = ask_llm(session)       # REASON
    result = execute_tool(...)      # ACT
    session["history"].append(...)  # OBSERVE
```

**Framework version (app.py):**
```python
async for node in agent_run:                    # ← same while loop
    if Agent.is_model_request_node(node):        # ← REASON (LLM thinking)
        ...stream text...
    elif Agent.is_call_tools_node(node):          # ← ACT (run tools)
        ...run tools...
```

Same loop. Pydantic AI just wraps it in an async iterator.

---

## Tool Registration

**What you built (Level 4):**
```python
TOOLS = {
    "calculator": {
        "description": "Evaluate a math expression...",
        "function": lambda args: str(eval(args["expression"])),
    },
}
```

**Framework version:**
```python
@agent.tool
async def lookup_table_schema(ctx, dataset: str, table: str) -> str:
    """Look up the schema of a BigQuery table."""   # ← description comes from docstring
    return f"Schema for {dataset}.{table}: ..."      # ← function body is the tool
```

Same thing. `@agent.tool` = adding to a TOOLS dict. The docstring = description.
Pydantic AI auto-generates the JSON schema from the function signature.

---

## Session / State

**What you built (Level 2-7):**
```python
session = {
    "session_id": "abc123",
    "history": [...],
    "data": {...},
}
save_session(session)   # → JSON file or Redis
load_session("abc123")  # → load from disk
```

**Framework version:**
```python
cl.user_session.set("message_history", [...])   # Chainlit stores it in memory
cl.user_session.set("deps", SessionDeps(...))   # deps = your session["data"]
```

Chainlit manages sessions in-memory per browser tab. No file/Redis needed
for a demo, but in production you'd add persistence (same as our Level 7).

---

## LLM Call

**What you built (Level 3):**
```python
client = genai.Client(api_key=...)
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=messages,
    config=genai.types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
    ),
)
text = response.text
action = json.loads(text)   # ← you parse the JSON yourself
```

**Framework version:**
```python
agent = Agent("anthropic:claude-sonnet-4-20250514", ...)
# That's it. Pydantic AI handles:
#   - building the prompt
#   - sending to the API
#   - parsing tool calls (no JSON parsing needed!)
#   - routing to the right @agent.tool function
```

Pydantic AI uses the model's native tool-calling API (not JSON-in-text),
so it never needs the ````json` stripping hack we did in Level 3.

---

## User Interaction

**What you built:**
```python
user_input = input("Your answer: ")   # terminal
```

**Framework version:**
```python
@cl.on_message                        # web UI
async def on_message(message):
    ...
```

Chainlit gives you a chat UI in the browser instead of terminal input().

---

## Summary Table

| Concept            | Your code (Level 1-7)              | Framework                              |
|--------------------|-------------------------------------|----------------------------------------|
| The loop           | `while not done:`                   | `async for node in agent_run:`         |
| LLM decides        | `ask_llm(session)` → parse JSON     | Pydantic AI calls model + parses tools |
| Tools              | `TOOLS` dict + `execute_tool()`     | `@agent.tool` decorated functions      |
| State              | `session` dict → JSON/Redis         | `cl.user_session` (in-memory)          |
| Save/Load          | `save_session()` / `load_session()` | Chainlit manages per-tab               |
| User input         | `input()`                           | `@cl.on_message` (web chat)            |
| System prompt      | `SYSTEM_PROMPT` string              | `instructions=` parameter              |
| Tool descriptions  | Manual string in TOOLS dict         | Function docstring                     |
| Tool arg parsing   | You parse JSON from LLM text        | Auto from function type hints          |
| Streaming          | (not implemented)                   | `PartDeltaEvent` → `stream_token()`   |

---

## What frameworks DON'T give you

Some things you built in Level 5-7 aren't covered by frameworks:

| Concept | Your code | Framework equivalent |
|---|---|---|
| **Plan-first execution** (Level 5) | LLM generates full plan, then executes | You'd build this yourself on top |
| **History compaction** (Level 6) | Summarize old history to stay within context | Not built-in — you'd add it yourself |
| **Chat mode** (Level 6) | Keep agent alive for follow-ups | Chainlit gives you this via `@cl.on_message` |
| **Redis persistence** (Level 7) | Production state storage with TTL | You'd add this yourself |

Frameworks handle the basics (loop, tools, LLM calls) but the interesting
production concerns — compaction, planning, persistence — you still build.

---

## The point

Frameworks don't add new concepts. They package the same concepts
so you write less boilerplate. But if you don't understand the concepts,
the framework code looks like magic.

Now you understand the concepts. It's not magic anymore.
