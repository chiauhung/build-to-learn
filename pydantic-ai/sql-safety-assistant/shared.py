"""
Shared printing helpers for all levels.

Usage:
    from shared import print_header, print_node, print_deferred
"""

from pydantic_ai import DeferredToolRequests
from pydantic_ai.agent import UserPromptNode, ModelRequestNode, CallToolsNode
from pydantic_ai.messages import ToolCallPart, TextPart
from pydantic_graph import End


def print_node(node, user_prompt: str = ""):
    """Pretty-print a single agent graph node."""
    if isinstance(node, UserPromptNode):
        print(f"\n  [UserPrompt] {user_prompt!r}")

    elif isinstance(node, ModelRequestNode):
        print("\n  [ModelRequest] sending to LLM...")

    elif isinstance(node, CallToolsNode):
        for part in node.model_response.parts:
            if isinstance(part, ToolCallPart):
                print(f"\n  [ToolCall] {part.tool_name}({part.args})")
            elif isinstance(part, TextPart):
                preview = (
                    part.content[:120] + "..."
                    if len(part.content) > 120
                    else part.content
                )
                print(f"\n  [Text] {preview!r}")

    elif isinstance(node, End):
        print("\n  [End]")


def print_header(deps, user_prompt: str):
    """Print run header with deps info."""
    print(f"\n{'=' * 60}")
    print(f"User [{deps.user_id}]: {user_prompt}")
    info_parts = [f"datasets={deps.allowed_datasets}"]
    if hasattr(deps, "cost_limit_usd"):
        info_parts.append(f"cost_limit=${deps.cost_limit_usd:.4f}")
    print(f"  {' | '.join(info_parts)}")
    print(f"{'=' * 60}")


def print_deferred(output: DeferredToolRequests):
    """Print deferred tool approval requests."""
    print("\n  >>> PAUSED — human approval required <<<")
    for call in output.approvals:
        meta = output.metadata.get(call.tool_call_id, {})
        print(f"\n  Tool: {call.tool_name} | Args: {call.args}")
        if meta:
            for k, v in meta.items():
                print(f"    {k}: {v}")
