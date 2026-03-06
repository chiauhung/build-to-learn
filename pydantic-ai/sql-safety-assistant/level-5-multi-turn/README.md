# Level 5: Multi-Turn Chat Session

Level-4 was stateless — every `/query` call was a fresh start.
Level-5 adds `session_id`. The LLM remembers the conversation.

## The one-line difference

```python
# level-4: no history
result = await agent.run(req.question, deps=deps)

# level-5: pass accumulated history
result = await agent.run(req.message, deps=deps, message_history=session["messages"])
```

`message_history` IS the session. There's no session object inside pydantic-ai —
you own the list, you own the persistence.

## Run

```bash
cd pydantic-ai-learn
uv run uvicorn level-5-multi-turn.main:app --reload --port 8001
# then open http://localhost:8001/docs
```

## Flow

```
POST /session                  → create session, get session_id
POST /session/{id}/chat        → send message (agent sees full history)
GET  /session/{id}/history     → inspect conversation so far
GET  /pending/{approval_id}    → inspect paused approval
POST /approve/{approval_id}    → approve/deny → agent resumes → history updated
```

## Try it (curl)

### Full multi-turn demo

**Step 1: Create a session**
```bash
curl -s -X POST http://localhost:8001/session \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "analyst-a",
    "allowed_datasets": ["sales", "marketing", "hr"],
    "cost_limit_usd": 0.01
  }' | python3 -m json.tool
```
Expected: `{"session_id": "abc123", ...}`

---

**Step 2: First turn — ask about sales**
```bash
curl -s -X POST http://localhost:8001/session/abc123/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me all sales orders over $100"}' | python3 -m json.tool
```
Expected: `{"status": "done", "result": "..."}`

---

**Step 3: Follow-up — agent remembers the previous result**
```bash
curl -s -X POST http://localhost:8001/session/abc123/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How many rows was that?"}' | python3 -m json.tool
```
Expected: agent answers from memory, no new SQL query.

---

**Step 4: Inspect conversation history**
```bash
curl -s http://localhost:8001/session/abc123/history | python3 -m json.tool
```

---

**Step 5: Expensive query — triggers approval gate**
```bash
curl -s -X POST http://localhost:8001/session/abc123/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Now show me all employee salaries"}' | python3 -m json.tool
```
Expected: `{"status": "pending_approval", "approval_id": "xyz789"}`

---

**Step 6: Inspect what's waiting**
```bash
curl -s http://localhost:8001/pending/xyz789 | python3 -m json.tool
```

---

**Step 7a: Approve — agent resumes, history updated**
```bash
curl -s -X POST http://localhost:8001/approve/xyz789 \
  -H "Content-Type: application/json" \
  -d '{"approved": true}' | python3 -m json.tool
```

**Step 7b: Deny**
```bash
curl -s -X POST http://localhost:8001/approve/xyz789 \
  -H "Content-Type: application/json" \
  -d '{"approved": false}' | python3 -m json.tool
```

---

**Step 8: Continue the conversation after approval**
```bash
curl -s -X POST http://localhost:8001/session/abc123/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Which department has the highest average salary?"}' | python3 -m json.tool
```
Agent sees all previous turns — sales query, approval, employee query — and answers in context.

---

## Key insight

```
session["messages"]  ←  this list grows with every turn
                         the LLM sees the full history on each call
                         YOU decide where to store it (memory → Redis → Postgres)
```

When an approval happens mid-session:
1. `/chat` → agent pauses → `approval_save(session_id, messages)` — history NOT yet in session
2. `/approve` → agent resumes → `session_update_messages(session_id, messages)` — now it's in

The session always reflects *completed* turns only.

## What's different from level-4

| | level-4 | level-5 |
|---|---|---|
| State between requests | none | `session["messages"]` |
| `/query` | new agent run every time | `/chat` appends to history |
| Approval | standalone `deps_config` | linked to `session_id` |
| After approve | result returned | history written back to session |
