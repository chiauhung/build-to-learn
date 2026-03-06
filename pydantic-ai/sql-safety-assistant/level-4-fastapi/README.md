# Level 4: FastAPI — Web App Approval Pattern

Same agent as level-3. Different runner — the approval now happens across two HTTP requests.

## Run

```bash
cd pydantic-ai-learn
uv run uvicorn level-4-fastapi.main:app --reload
```

Then open **http://localhost:8000/docs** — Swagger UI lets you try all endpoints.

## Flow

```
POST /query          → agent runs → if cost over limit → returns {approval_id}
GET  /pending/{id}   → see what SQL + cost is waiting
POST /approve/{id}   → {"approved": true/false} → agent resumes → final result
```

## Try it (curl)

**Cheap query — completes immediately:**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me sales orders", "allowed_datasets": ["sales"], "cost_limit_usd": 0.01}'
```

**Expensive query — pauses for approval:**
```bash
# Step 1: submit
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me employee salaries", "allowed_datasets": ["sales","hr"], "cost_limit_usd": 0.01}'
# → {"status": "pending_approval", "approval_id": "abc123"}

# Step 2: inspect
curl http://localhost:8000/pending/abc123

# Step 3: approve
curl -X POST http://localhost:8000/approve/abc123 \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'

# Step 3: deny
curl -X POST http://localhost:8000/approve/abc123 \
  -H "Content-Type: application/json" \
  -d '{"approved": false}'
```

## Demo scenarios

### 1. Cheap query — completes immediately, no approval needed

```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me all sales orders",
    "allowed_datasets": ["sales"],
    "cost_limit_usd": 0.01
  }' | python3 -m json.tool
```

Expected: `{"status": "done", "result": "..."}`

---

### 2. Expensive query — triggers approval gate (full flow)

**Step 1: Submit the query**
```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me all employee salaries",
    "allowed_datasets": ["sales", "marketing", "hr"],
    "cost_limit_usd": 0.01
  }' | python3 -m json.tool
```
Expected: `{"status": "pending_approval", "approval_id": "abc123"}`

**Step 2: Inspect what's waiting** (replace `abc123` with real id)
```bash
curl -s http://localhost:8000/pending/abc123 | python3 -m json.tool
```

**Step 3a: Approve**
```bash
curl -s -X POST http://localhost:8000/approve/abc123 \
  -H "Content-Type: application/json" \
  -d '{"approved": true}' | python3 -m json.tool
```

**Step 3b: Deny** (use same id before approving)
```bash
curl -s -X POST http://localhost:8000/approve/abc123 \
  -H "Content-Type: application/json" \
  -d '{"approved": false}' | python3 -m json.tool
```

---

### 3. Permission denied — HR not in allowed_datasets

```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me employee salaries",
    "allowed_datasets": ["sales"],
    "cost_limit_usd": 0.01
  }' | python3 -m json.tool
```

Expected: `{"status": "done", "result": "... access denied ..."}` — agent completes immediately but tool returns denied.

---

### 4. High cost limit — expensive query auto-executes, no approval

```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me all employee salaries",
    "allowed_datasets": ["sales", "hr"],
    "cost_limit_usd": 1.00
  }' | python3 -m json.tool
```

Expected: `{"status": "done", "result": "..."}` — HR query costs ~$0.25, under the $1.00 limit, executes directly.

---

## Key insight

The agent's message history is serialized into the store between requests.
When you hit `/approve`, the agent resumes from exactly where it paused.

`conn` is NOT stored — it's recreated on resume. This is why DI matters:
deps that can't be serialized (DB connections, API clients) are re-injected
at resume time, not saved to state.
