"""
LangGraph: Same Agent, Graph Style
=====================================

Same thing as Level 4 and your boss's Pydantic AI code.
Just different syntax — here you explicitly draw the graph.

Read MAPPING.md in the pydantic-ai folder first.
Then come here to compare syntax.

This is NOT runnable without setup (needs langchain + API keys).
It's here so you can READ and COMPARE, not run.

Setup (if you want to try):
  pip install langgraph langchain-google-genai
  export GEMINI_API_KEY=your_key
"""

from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage


# ──────────────────────────────────────────────
# State — same as our session dict
# ──────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # ← same as session["history"]


# ──────────────────────────────────────────────
# Tools — same as our TOOLS dict / @agent.tool
# ──────────────────────────────────────────────

@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))


@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"{city}: 22°C, partly cloudy"


@tool
def search_users(name: str) -> str:
    """Search users by name."""
    return f"Found: {name} Smith (34), {name} Doe (28)"


tools = [calculator, get_weather, search_users]


# ──────────────────────────────────────────────
# LLM — same as our ask_llm()
# ──────────────────────────────────────────────

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")
llm_with_tools = llm.bind_tools(tools)  # ← tells LLM what tools exist


# ──────────────────────────────────────────────
# Graph nodes — these are the steps in the loop
# ──────────────────────────────────────────────

def reason_node(state: AgentState):
    """REASON: LLM looks at history and decides next action."""
    # Same as: action = ask_llm(session)
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def act_node(state: AgentState):
    """ACT: Execute whatever tools the LLM requested."""
    # Same as: result = execute_tool(tool_name, args)
    last_message = state["messages"][-1]
    results = []
    for tool_call in last_message.tool_calls:
        # Find and run the matching tool
        tool_fn = {t.name: t for t in tools}[tool_call["name"]]
        result = tool_fn.invoke(tool_call["args"])
        results.append(result)
    return {"messages": results}


def should_continue(state: AgentState):
    """Decide: did LLM call tools, or give final answer?"""
    # Same as: if action["action"] == "FINAL_ANSWER": break
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "act"       # LLM wants to use tools → go to act_node
    else:
        return "end"       # LLM gave text answer → we're done


# ──────────────────────────────────────────────
# Build the graph — THIS is what makes LangGraph different
# ──────────────────────────────────────────────

graph = StateGraph(AgentState)

# Add nodes (= steps)
graph.add_node("reason", reason_node)
graph.add_node("act", act_node)

# Add edges (= flow)
graph.set_entry_point("reason")                     # start here

graph.add_conditional_edges("reason", should_continue, {
    "act": "act",    # if LLM called tools → execute them
    "end": END,      # if LLM gave final answer → stop
})

graph.add_edge("act", "reason")  # after tools run → back to reason
#                                  (this is the OBSERVE → REASON loop)

# Compile
app = graph.compile()


# ──────────────────────────────────────────────
# Run it
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("What do you want help with?")
    goal = input("> ")

    # This single call runs the entire reason→act→observe loop
    # until should_continue returns "end"
    result = app.invoke({
        "messages": [HumanMessage(content=goal)]
    })

    # Print final answer
    print("\n" + "=" * 50)
    print("FINAL ANSWER:")
    print("=" * 50)
    print(result["messages"][-1].content)
