# Syntax Comparison: Your Code vs Pydantic AI vs LangGraph

All three do the same thing. Here's the same concepts side by side.

---

## Defining Tools

```python
# YOUR CODE (Level 4-7)
TOOLS = {
    "calculator": {
        "description": "Evaluate a math expression",
        "function": lambda args: str(eval(args["expression"])),
    },
}

# PYDANTIC AI
@agent.tool
async def calculator(ctx: RunContext, expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))

# LANGGRAPH
@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))
```

---

## The Loop

```python
# YOUR CODE (Level 4-7)
while not done:
    action = ask_llm(session)
    if action["action"] == "USE_TOOL":
        result = execute_tool(action["tool"], action["args"])
    elif action["action"] == "FINAL_ANSWER":
        break
    session["history"].append(result)

# PYDANTIC AI
async for node in agent_run:
    if Agent.is_model_request_node(node):   # reason
        ...
    elif Agent.is_call_tools_node(node):     # act
        ...

# LANGGRAPH
graph.add_conditional_edges("reason", should_continue, {
    "act": "act",
    "end": END,
})
graph.add_edge("act", "reason")   # loop back
# then: app.invoke(...)           # runs the loop
```

---

## State / Session

```python
# YOUR CODE (Level 2-7)
session = {"history": [], "data": {}}
save_session(session)

# PYDANTIC AI
cl.user_session.set("message_history", [...])

# LANGGRAPH
class AgentState(TypedDict):
    messages: list   # that's it
```

---

## Running It

```python
# YOUR CODE (Level 4-7)
run_agent(session)            # you control the loop

# PYDANTIC AI
async with agent.iter(...):   # framework controls the loop, you observe
    async for node in agent_run:
        ...

# LANGGRAPH
app.invoke({"messages": [...]})   # one call, framework runs entire loop
```

---

## When to use what

| | Best for |
|---|---|
| **Manual (Level 1-7)** | Learning. Understanding. Full control. |
| **Pydantic AI** | Production apps. Clean, Pythonic. Good defaults. |
| **LangGraph** | Complex flows with branching, parallel paths, human-in-the-loop. |

Your boss chose Pydantic AI because it's the simplest for a
straightforward tool-calling agent. LangGraph would be overkill
for what his app does.
