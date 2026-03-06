# HR Pipeline Demo — Pydantic AI Patterns in Action

Three runnable demos showing what Pydantic AI's `agent.iter()` loop control and dependency injection enable — things that orchestration frameworks like Mastra handle at a different layer.

**Domain:** Multi-tenant talent acquisition platform (DuckDB mock data, two companies, three user personas).

## Setup

```bash
cd hr-pipeline-demo
uv sync
export GOOGLE_API_KEY=your-key
```

## Demo 1 — DI as Permission Boundary

```bash
uv run demo-1-di-boundary/main.py
```

Same agent, same tools, same prompt — three users get completely different results:

- **Alice** (HR Manager, Growthly) — sees Growthly's applicants, can move status
- **Bob** (Talent Lead, BrightHire) — sees only BrightHire's applicants
- **Charlie** (Recruiter, Growthly) — sees applicants but **denied** when trying to move status

The LLM never sees `company_id` or `can_move_status`. They live in `deps` — a typed dataclass injected at the call site. Every tool inherits the boundary automatically.

## Demo 2 — Loop Control (3 Scenarios)

```bash
uv run demo-2-loop-control/main.py
```

Three scenarios exercising different `agent.iter()` loop-control capabilities:

| Scenario | What it shows |
|----------|---------------|
| **A: Normal run** | Every node rendered, full audit log — compliance trail that fires *before* each tool call |
| **B: Mutation cap** | Agent stopped after N actual database mutations (not LLM call count) |
| **C: Replan loop** | Outer loop detects operator denials, captures message history, injects new strategy, restarts the agent with full context |

**Five loop-control primitives demonstrated:**

1. Custom stopping condition (business signal, not step count)
2. Runtime middleware (per-tool-call audit log)
3. Tool execution interception (pause before terminal transitions)
4. Reasoning state injection (mutable deps read live by the outer loop)
5. Meta-loop replan (capture history → inject instruction → restart)

## Demo 3 — Chainlit UI

```bash
uv run chainlit run chainlit_app.py
```

Interactive web app combining all patterns — login-based DI, threshold prompts via action buttons, real-time tool call rendering, and mid-stream approve/deny for terminal transitions.

Login: `alice`/`alice`, `bob`/`bob`, or `charlie`/`charlie`.

## Key Takeaway

Pydantic AI controls what happens **inside** the agent loop — between every tool call. Orchestration frameworks control what happens **between** agents or workflow steps. They solve different problems at different layers.
