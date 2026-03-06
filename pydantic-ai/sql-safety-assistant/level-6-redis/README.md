# Level 6: Redis-Backed Session Store

Same app as level-5. One swap: in-memory dict → Redis.

Sessions survive process restarts. That's the only difference.

## What changes

```
level-5/store.py   → _sessions: dict[str, ...]   (gone when process dies)
level-6/store.py   → redis.setex("session:abc", ...)  (survives restarts)
```

The app code (`main.py`) is identical to level-5 line for line.
This is the payoff of designing the store interface first.

## Run

**Step 1: Start Redis**
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

**Step 2: Install redis-py**
```bash
# already in pyproject.toml under optional deps
uv sync --extra redis
```

**Step 3: Run the app**
```bash
cd pydantic-ai-learn
uv run uvicorn level-6-redis.main:app --reload --port 8002
# then open http://localhost:8002/docs
```

## Verify persistence

```bash
# Create a session and send a message
curl -s -X POST http://localhost:8002/session \
  -H "Content-Type: application/json" \
  -d '{"user_id": "analyst-a", "allowed_datasets": ["sales"], "cost_limit_usd": 0.01}' \
  | python3 -m json.tool
# → {"session_id": "abc123"}

curl -s -X POST http://localhost:8002/session/abc123/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me all sales orders"}' | python3 -m json.tool

# Restart the server (Ctrl+C, then rerun uvicorn)
# Session still exists:
curl -s http://localhost:8002/session/abc123/history | python3 -m json.tool
```

Level-5 would return 404 after restart. Level-6 returns the history.

## Serialization

pydantic-ai messages are pydantic models. They serialize cleanly:

```python
from pydantic_ai.messages import ModelMessagesTypeAdapter

# serialize
json_str = ModelMessagesTypeAdapter.dump_json(messages).decode()

# deserialize
messages = ModelMessagesTypeAdapter.validate_json(json_str)
```

This is the same pattern you'd use for Postgres (`TEXT` column) or any other store.

## TTLs

| Key | TTL |
|-----|-----|
| `session:{id}` | 24 hours |
| `approval:{id}` | 1 hour |

TTLs reset on every write. A session that's actively used stays alive.

## Key insight

```
level-5: dict lives in process memory  → restart = data lost
level-6: Redis key lives on the network → restart = data survives

session state is the foundation for durable execution.
you can't build reliable async queues (level-6 concept) without it.
```
