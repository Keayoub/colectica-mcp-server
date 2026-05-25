# SPDX-License-Identifier: Apache-2.0
"""
Tool bridge skeleton for Azure AI Foundry -> Colectica MCP.

This module provides a minimal runtime adapter to:
1) read required tool calls from a Foundry run,
2) dispatch each call to a Colectica executor, and
3) return tool output payloads consumable by Foundry.

You can swap the executor with a real MCP transport adapter (stdio or HTTP).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ToolBridgeError(RuntimeError):
    """Raised when tool-call extraction or submission cannot proceed."""


@dataclass(slots=True)
class FoundryToolCall:
    """Normalized view of a single Foundry tool call."""

    tool_call_id: str
    name: str
    arguments: dict[str, Any]


class ColecticaToolBridge:
    """
    Dispatch Foundry function calls to a backend executor.

    The executor signature is:
        executor(tool_name: str, arguments: dict[str, Any]) -> Any

    Returned values are JSON-encoded and sent back as tool outputs.
    """

    def __init__(
        self,
        executor: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._executor = executor or self._default_executor

    def build_tool_outputs_for_run(self, run: Any) -> list[dict[str, str]]:
        """Build `tool_outputs` payload for a run in `requires_action` state."""
        outputs: list[dict[str, str]] = []
        for call in extract_tool_calls(run):
            try:
                result = self._executor(call.name, call.arguments)
                payload = {
                    "ok": True,
                    "tool": call.name,
                    "result": result,
                }
            except Exception as exc:  # noqa: BLE001 - surface tool error to model
                payload = {
                    "ok": False,
                    "tool": call.name,
                    "error": str(exc),
                }

            outputs.append(
                {
                    "tool_call_id": call.tool_call_id,
                    "output": json.dumps(payload, ensure_ascii=True),
                }
            )

        return outputs

    @staticmethod
    def _default_executor(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Safe fallback executor.

        Replace this with a real MCP adapter in production.
        """
        return {
            "message": "No MCP executor configured.",
            "tool_name": tool_name,
            "arguments": arguments,
            "hint": "Provide ColecticaToolBridge(executor=your_mcp_executor).",
        }


def extract_tool_calls(run: Any) -> list[FoundryToolCall]:
    """Extract normalized tool calls from a Foundry run object."""
    required_action = getattr(run, "required_action", None)
    if not required_action:
        return []

    submit_payload = getattr(required_action, "submit_tool_outputs", None)
    if not submit_payload:
        return []

    raw_calls = getattr(submit_payload, "tool_calls", None)
    if not raw_calls:
        return []

    calls: list[FoundryToolCall] = []
    for raw in raw_calls:
        raw_id = getattr(raw, "id", None)
        function = getattr(raw, "function", None)
        raw_name = getattr(function, "name", None) if function else None
        raw_arguments = getattr(function, "arguments", "{}") if function else "{}"

        if not raw_id or not raw_name:
            continue

        calls.append(
            FoundryToolCall(
                tool_call_id=str(raw_id),
                name=str(raw_name),
                arguments=_parse_arguments(raw_arguments),
            )
        )

    return calls


def submit_tool_outputs(client: Any, thread_id: str, run_id: str, tool_outputs: list[dict[str, str]]) -> Any:
    """
    Submit tool outputs using whichever method is available on the SDK version.

    Supports either:
      - client.agents.submit_tool_outputs_to_run(...)
      - client.agents.submit_tool_outputs(...)
    """
    agents = client.agents

    if hasattr(agents, "submit_tool_outputs_to_run"):
        return agents.submit_tool_outputs_to_run(
            thread_id=thread_id,
            run_id=run_id,
            tool_outputs=tool_outputs,
        )

    if hasattr(agents, "submit_tool_outputs"):
        return agents.submit_tool_outputs(
            thread_id=thread_id,
            run_id=run_id,
            tool_outputs=tool_outputs,
        )

    raise ToolBridgeError(
        "AI Foundry SDK does not expose a recognized tool output submission method."
    )


def _parse_arguments(raw_arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments

    if not isinstance(raw_arguments, str):
        return {}

    stripped = raw_arguments.strip()
    if not stripped:
        return {}

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {"_raw": raw_arguments}

    if isinstance(parsed, dict):
        return parsed

    return {"_value": parsed}
