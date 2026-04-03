# Chat

LLM query layer over gacha analytics. Natural language → SQL → results.

## Stack

- **Pydantic AI** — Agent framework, structured outputs
- **Chainlit** — Conversational UI (embedded in NiceGUI or standalone)
- **Langfuse** — Tracing, prompt management, cost tracking
- **DuckDB / BigQuery** — Query backend (local / GCP)

## What You Can Ask

```
"How much do whales spend before their first SSR?"
"What's the average pity across all players?"
"Which banner had the highest revenue?"
"Show me top-up conversion by package tier"
"Am I a whale?" (when playing via UI)
```

## Architecture

```
User question
  → Pydantic AI agent (with tool: run_sql)
  → Agent generates SQL against Gold layer
  → Executes on DuckDB/BigQuery
  → Returns formatted answer
  → Langfuse traces the full chain
```

## Key Files

- **`agent.py`** — Pydantic AI agent definition, tools, system prompt
- **`prompts/`** — Versioned prompt templates (managed via Langfuse or local)
