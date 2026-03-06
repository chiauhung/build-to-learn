# Level 7: Multi-Agent — Model Escalation

Two agents. Two models. Same tools.
The expensive model only runs when the cheap one can't handle it.

## The pattern

```
User question
    ↓
Agent A  (gemini-2.0-flash-lite — fast, cheap)
    ↓ handles it directly   →  return result
    ↓ or flags "ESCALATE:"
Agent B  (gemini-2.0-flash — thorough, expensive)
    ↓ receives A's work as context
    →  return final result
```

Agent A never throws away its work. When it escalates, it passes its SQL,
data, and partial reasoning to Agent B. Agent B picks up from there.

## Why this model

| | Agent A | Agent B |
|---|---|---|
| Model | `gemini-2.0-flash-lite` | `gemini-2.0-flash` |
| Cost | ~$0.075 / 1M tokens | ~$0.30 / 1M tokens |
| Good at | Simple lookups, single-table queries | Multi-step reasoning, trend analysis, cross-dataset |
| Escalates when | Complex, ambiguous, or needs interpretation | Never — it's the final tier |

In production: 80% of queries are simple. Haiku/flash-lite handles them.
You only pay Sonnet/flash prices for the hard 20%.

## Run

```bash
cd pydantic-ai-learn
uv run level-7-multi-agent/main.py
```

Expected output:
- Scenario 1: Agent A answers directly (no escalation)
- Scenario 2: Agent A escalates → Agent B gives deeper analysis
- Scenario 3: Agent A escalates → Agent B handles cross-dataset reasoning

## Key insight: escalation via output format

Agent A signals escalation through its text output:

```
ESCALATE: needs cross-dataset join and trend analysis
SELECT region, SUM(amount) ... (SQL already run)
Results: APAC: $562, NA: $442 ... (data already fetched)
```

Agent B receives this as a prompt prefix — no duplicate tool calls,
no wasted tokens re-running the same SQL.

This is simpler than building a router agent or a graph. The "routing"
is just a string check: `output.startswith("ESCALATE:")`.

## Registering tools on multiple agents

```python
for _agent in (agent_a, agent_b):

    @_agent.tool
    async def list_datasets(ctx: RunContext[ChatDeps]) -> list[str]:
        ...
```

Both agents share the same tool implementations. If you update a tool,
both agents get the update automatically.

## What's next

- **FastAPI wrapper:** add `/query` endpoint that runs this escalation flow
- **Streaming:** stream Agent A's response while it runs, show "escalating..." in UI
- **Real models:** swap `gemini-2.0-flash-lite` for `claude-haiku-4-5`, `gemini-2.0-flash` for `claude-sonnet-4-6`
- **Confidence score:** instead of "ESCALATE:" prefix, have Agent A return a structured output with `{answer, confidence}` and escalate if confidence < 0.8
