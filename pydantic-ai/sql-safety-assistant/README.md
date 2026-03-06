# Pydantic AI — SQL Safety Assistant

Learn Pydantic AI by building a multi-tenant SQL Safety Assistant, one level at a time.

## Setup

```bash
cd pydantic-ai-learn
uv sync
export GOOGLE_API_KEY=your-key-here  # from aistudio.google.com
```

## Levels

### Level 0: Vanilla DI — No Framework (`level-0-vanilla-di/`)

**What you learn:** What runtime context injection actually IS, in pure Python. No pydantic-ai.

- `Agent` = stateless class, created once at startup
- `ChatDeps` = per-user environment (conn, permissions)
- `RunContext` = just a wrapper that carries deps into tools (not a resource manager!)
- YOU manage conn lifecycle, not RunContext

```bash
uv run level-0-vanilla-di/main.py
```

**Key insight:** `RunContext` is not magic. It's just `ctx.deps = deps`. Whoever creates the conn closes the conn. Agent holds zero user state. This is the mental model for everything that follows.

---

### Level 1: Basic Agent + DI (`level-1-basic-di/`)

**What you learn:** `RunContext[Deps]` is a security boundary, not just clean code.

- DuckDB as mock BQ — real SQL, fixture-style setup (`db.py`)
- `ChatDeps` with `allowed_datasets` — LLM never sees this
- `agent.iter()` — step through the ReAct loop node by node
- Multi-tenant demo: same agent, different permissions per user

```bash
uv run level-1-basic-di/main.py
```

**Key insight:** User A gets `allowed_datasets=["sales"]`, User B gets `["sales", "marketing", "hr"]`. Same agent, same tools — the permission boundary lives in `deps`, invisible to the LLM.

---

### Level 2: Deferred Tools (`level-2-deferred-tools/`)

**What you learn:** Tools can return intent, not result. Agent pauses for human approval.

- `execute_sql` has `requires_approval=True` — always pauses
- Agent generates SQL → dry-runs → hits the approval gate → human decides
- `DeferredToolRequests` / `DeferredToolResults` for pause/resume

```bash
uv run level-2-deferred-tools/main.py
```

**Key insight:** The agent proposes, the human disposes. `execute_sql` never runs without explicit approval.

---

### Level 3: Cost Guardrail + Multi-Tenant (`level-3-cost-guardrail/`)

**What you learn:** Guardrails the LLM must NOT control. Conditional approval based on cost.

- `cost_limit_usd` in deps — cheap queries auto-execute, expensive ones need approval
- `ApprovalRequired` raised conditionally (not `requires_approval=True`)
- 4 demo scenarios: cheap/auto, expensive/approved, expensive/denied, no-permission

```bash
uv run level-3-cost-guardrail/main.py
```

**Key insight:** Cost guardrail lives in `deps`, enforced at runtime. The LLM proposes SQL, but it's the runtime that decides whether to pause for approval. This is infra-level design.

---

### Level 4: FastAPI Web App (`level-4-fastapi/`)

**What you learn:** Agent approval across two HTTP requests. State bridged by an in-memory store.

- `POST /query` → agent runs → pauses → returns `{approval_id}`
- `GET /pending/{id}` → see the SQL + cost waiting for approval
- `POST /approve/{id}` → `{"approved": true}` → agent resumes → final result
- `conn` is NOT stored — re-injected on resume (this is why DI matters for durable patterns)

```bash
uv run uvicorn level-4-fastapi.main:app --reload
# then open http://localhost:8000/docs
```

**Key insight:** The agent's message history is serializable. The DB connection is not. DI lets you re-inject the connection cleanly on resume without touching agent or tool code.

---

### Level 5: Multi-Turn Chat Session (`level-5-multi-turn/`)

**What you learn:** `message_history` is the session — you own persistence, not the framework.

- `POST /session` — create a session (gets `session_id`)
- `POST /session/{id}/chat` — send a message; agent sees full history each turn
- `GET  /session/{id}/history` — inspect the conversation so far
- Approval mid-session: history writes back only after resolution

```bash
uv run uvicorn level-5-multi-turn.main:app --reload --port 8001
# then open http://localhost:8001/docs
```

**Key insight:** The one-line difference from level-4: `message_history=session["messages"]`. That list grows every turn. The LLM sees all of it. You decide where to store it — dict today, Redis in level-6.

---

### Level 6: Redis Session Store (`level-6-redis/`)

**What you learn:** Session state that survives process restarts. One file swap — everything else is identical to level-5.

- `store.py` swapped: in-memory dict → Redis (`redis.setex`)
- Messages serialized with `ModelMessagesTypeAdapter` (pydantic-ai's own serializer)
- 24h session TTL, 1h approval TTL
- `main.py` is byte-for-byte the same as level-5

```bash
docker run -d -p 6379:6379 redis:7-alpine
uv sync --extra redis
uv run uvicorn level-6-redis.main:app --reload --port 8002
# then open http://localhost:8002/docs
```

**Key insight:** Restart the server — sessions survive. That's the only difference from level-5. This is the foundation for durable async queues and crash recovery.

---

### Level 7: Multi-Agent Model Escalation (`level-7-multi-agent/`)

**What you learn:** Two agents, two models, same tools. Pay for the expensive model only when needed.

- Agent A (`gemini-2.0-flash-lite`) handles simple queries directly
- If Agent A outputs `ESCALATE:`, Agent B (`gemini-2.0-flash`) takes over
- Agent B receives Agent A's SQL + data as context — no duplicate work
- Tools registered on both agents via a `for agent in (a, b)` loop

```bash
uv run level-7-multi-agent/main.py
```

**Key insight:** The "routing" is just a string check: `output.startswith("ESCALATE:")`. No graph, no router agent. Agent A passes its work to Agent B — 80% of queries handled cheaply, 20% escalated.

---

## Concept Map

| Level | Concept | Key idea |
|-------|---------|----------|
| 0 | Vanilla DI | The mental model behind everything |
| 1 | `RunContext[Deps]` + `agent.iter()` | Security boundary + step-by-step visibility |
| 2 | Deferred tools | Human-in-the-loop (always pauses) |
| 3 | Cost guardrail | Human-in-the-loop (conditional) |
| 4 | FastAPI | Approval across two HTTP requests |
| 5 | Multi-turn session | `message_history` = session state |
| 6 | Redis store | Session survives restarts (durable) |
| 7 | Multi-agent | Model escalation — cheap first, expensive when needed |

## Production path

```
Real BigQuery  → replace db.py with google.cloud.bigquery.Client
Real auth      → move user_id + allowed_datasets into JWT claims
Streaming      → AG-UI protocol for real-time frontend updates
```
