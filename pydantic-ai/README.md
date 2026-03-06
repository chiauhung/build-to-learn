# Pydantic AI

Two projects exploring Pydantic AI from different angles — one builds up concepts level by level, the other demonstrates production patterns in action.

---

### [SQL Safety Assistant](./sql-safety-assistant/) — Learn by Building

A multi-tenant SQL Safety Assistant built across 8 levels (0–7). Each level adds one concept: dependency injection, human-in-the-loop approval, cost guardrails, FastAPI integration, multi-turn sessions, Redis persistence, and multi-agent model escalation.

Start here if you want to understand **how** Pydantic AI works under the hood.

---

### [HR Pipeline Demo](./hr-pipeline-demo/) — Patterns in Action

Three runnable demos using a talent acquisition domain — DI as a security boundary, loop-level control (audit trails, mutation caps, replan loops), and a Chainlit UI with real-time approval flows.

Start here if you want to see **what** Pydantic AI can do that orchestration frameworks can't.
