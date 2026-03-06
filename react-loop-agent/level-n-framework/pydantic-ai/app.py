"""
Framework Version (Pydantic AI + Chainlit)
============================================

This is your boss's code. It does the SAME thing as Level 4,
but uses frameworks that hide the plumbing.

DO NOT start here. Come back after you've run Level 1-7
and understand the loop.

Read MAPPING.md in this folder to see how every line maps
back to what you built by hand.

Setup:
  pip install pydantic-ai chainlit

Run:
  chainlit run app.py -w
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import chainlit as cl
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ToolCallPartDelta,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
)

# ---------------------------------------------------------------------------
# Dependencies — inject per-session state into tools
# ---------------------------------------------------------------------------

@dataclass
class SessionDeps:
    """Carried into every tool via RunContext[SessionDeps]."""
    session_id: str = ""
    # Add any GCP clients, BigQuery handles, etc. here


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

agent = Agent(
    # Swap model string as needed: "anthropic:claude-sonnet-4-20250514", "openai:gpt-4o", etc.
    "anthropic:claude-sonnet-4-20250514",
    deps_type=SessionDeps,
    instructions=(
        "You are a helpful data platform assistant. "
        "You can look up table schemas and run example queries. "
        "Keep answers concise and technical."
    ),
)


# ---------------------------------------------------------------------------
# Example tools — replace with real GCP / BigQuery calls
# ---------------------------------------------------------------------------

@agent.tool
async def lookup_table_schema(
    ctx: RunContext[SessionDeps], dataset: str, table: str
) -> str:
    """Look up the schema of a BigQuery table."""
    # Placeholder — replace with actual BigQuery client call
    return (
        f"Schema for `{dataset}.{table}`:\n"
        "  - id: INTEGER\n"
        "  - name: STRING\n"
        "  - created_at: TIMESTAMP\n"
        "  - status: STRING"
    )


@agent.tool
async def run_dry_run_query(
    ctx: RunContext[SessionDeps], sql: str
) -> str:
    """Dry-run a SQL query and return estimated bytes processed."""
    # Placeholder — replace with BigQuery dry-run
    return f"Dry-run OK. Estimated bytes processed: 1.2 GB\nSQL: {sql}"


# ---------------------------------------------------------------------------
# Chainlit lifecycle
# ---------------------------------------------------------------------------

@cl.on_chat_start
async def on_chat_start():
    """Initialise per-session state."""
    cl.user_session.set("message_history", [])
    cl.user_session.set("deps", SessionDeps(session_id="demo"))
    cl.user_session.set("cancel_event", asyncio.Event())
    await cl.Message(content="Hey! I'm your data platform assistant. Ask me anything.").send()


@cl.on_stop
async def on_stop():
    """Called when user clicks the Stop button — signal cancellation."""
    cancel: asyncio.Event = cl.user_session.get("cancel_event")
    cancel.set()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle each user message: stream the agent response with tool-call steps."""

    # Retrieve session state
    history: list[ModelMessage] = cl.user_session.get("message_history")
    deps: SessionDeps = cl.user_session.get("deps")
    cancel: asyncio.Event = cl.user_session.get("cancel_event")
    cancel.clear()  # reset for this turn

    # Prepare the Chainlit response message (will be streamed into)
    response_msg = cl.Message(content="")
    await response_msg.send()

    # Active Chainlit Steps for tool calls (keyed by tool-call index)
    active_steps: dict[int, cl.Step] = {}

    try:
        async with agent.iter(
            message.content,
            message_history=history,
            deps=deps,
        ) as agent_run:

            async for node in agent_run:
                if cancel.is_set():
                    break

                # -- Model is making a request (contains streaming events) --
                if Agent.is_model_request_node(node):
                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            if cancel.is_set():
                                break

                            # Text token deltas -> stream to the UI
                            if isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, TextPartDelta
                            ):
                                await response_msg.stream_token(event.delta.content_delta)

                # -- Agent is calling tools --
                elif Agent.is_call_tools_node(node):
                    # Show each tool call as a Chainlit Step
                    for part in node.model_response.parts:
                        if hasattr(part, "tool_name"):
                            tool_step = cl.Step(
                                name=part.tool_name,
                                type="tool",
                            )
                            tool_step.input = getattr(part, "args_as_json_str", lambda: "{}")()
                            tool_step.start = True
                            await tool_step.send()

                            tool_step.output = "Done"
                            await tool_step.update()

        # Persist updated history for next turn
        if not cancel.is_set():
            updated_history = agent_run.result.all_messages()
            cl.user_session.set("message_history", updated_history)

    except Exception as e:
        await response_msg.stream_token(f"\n\nError: {e}")

    # Finalise the streamed message
    await response_msg.update()
