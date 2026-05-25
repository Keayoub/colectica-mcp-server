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

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp import StdioServerParameters
from mcp import stdio_client

try:
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # pragma: no cover - compatibility for older mcp versions
    from mcp.client.streamable_http import streamablehttp_client as streamable_http_client


class ToolBridgeError(RuntimeError):
    """Raised when tool-call extraction or submission cannot proceed."""


class ColecticaMcpStdioExecutor:
    """
    Execute Colectica MCP tools through stdio transport.

    This is a concrete MCP execution path suitable for local development and
    production runners that can spawn processes.
    """

    def __init__(
        self,
        command: str = "colectica-mcp",
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = args or ["--transport", "stdio"]
        self.env = env

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return asyncio.run(self._call_tool(tool_name=tool_name, arguments=arguments))

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        server = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )
        async with stdio_client(server) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                result = await session.call_tool(name=tool_name, arguments=arguments)
                return _normalize_call_tool_result(result)


class ColecticaMcpHttpExecutor:
    """Execute Colectica MCP tools through streamable HTTP transport."""

    def __init__(self, url: str) -> None:
        self.url = url

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return asyncio.run(self._call_tool(tool_name=tool_name, arguments=arguments))

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        async with streamable_http_client(self.url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name=tool_name, arguments=arguments)
                return _normalize_call_tool_result(result)


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

    def execute_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Execute a single tool call through the configured backend executor."""
        return self._executor(tool_name, arguments or {})

    def build_tool_outputs_for_run(self, run: Any) -> list[dict[str, str]]:
        """Build `tool_outputs` payload for a run in `requires_action` state."""
        outputs: list[dict[str, str]] = []
        for call in extract_tool_calls(run):
            try:
                result = self.execute_tool(call.name, call.arguments)
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
        raise ToolBridgeError(
            "No executor configured. Provide ColecticaToolBridge(executor=ColecticaMcpStdioExecutor(...)) "
            "or ColecticaMcpHttpExecutor(...)."
        )


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


def _normalize_call_tool_result(result: Any) -> dict[str, Any]:
    """Normalize MCP CallToolResult into JSON-safe output."""
    payload: dict[str, Any] = {
        "isError": bool(getattr(result, "isError", False)),
    }

    structured_content = getattr(result, "structuredContent", None)
    content = getattr(result, "content", None)

    if structured_content is not None:
        payload["structuredContent"] = _to_json_safe(structured_content)

    if content is not None:
        payload["content"] = _to_json_safe(content)

    return payload


def _to_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]

    if hasattr(value, "model_dump"):
        try:
            return _to_json_safe(value.model_dump())
        except Exception:
            return str(value)

    if hasattr(value, "dict"):
        try:
            return _to_json_safe(value.dict())
        except Exception:
            return str(value)

    return str(value)
