"""
Example: Create and run the Colectica Statistician Prompt Agent in Azure AI Foundry.

Usage:
  setx AIFOUNDRY_PROJECT_CONNECTION_STRING "<your-connection-string>"
  python integrations/examples/aifoundry_statistician_prompt_agent_example.py

Optional environment variables:
  AIFOUNDRY_MODEL                        Override model in payload
  AIFOUNDRY_PROJECT_CONNECTION_STRING    AI Foundry project connection string
    COLECTICA_MCP_TRANSPORT                stdio (default) or http
    COLECTICA_MCP_COMMAND                  Stdio command (default: colectica-mcp)
    COLECTICA_MCP_URL                      Streamable HTTP URL (required for http transport)
    COLECTICA_BASE_URL                     Required by the Colectica MCP server
    COLECTICA_BEARER_TOKEN                 Optional bearer auth
    COLECTICA_USERNAME                     Optional basic auth username
    COLECTICA_PASSWORD                     Optional basic auth password
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MessageRole

from integrations.aifoundry import ColecticaMcpHttpExecutor
from integrations.aifoundry import ColecticaMcpStdioExecutor
from integrations.aifoundry import ColecticaToolBridge
from integrations.aifoundry import build_statistician_foundry_agent_payload
from integrations.aifoundry import submit_tool_outputs


def _require_connection_string() -> str:
    conn = os.getenv("AIFOUNDRY_PROJECT_CONNECTION_STRING", "").strip()
    if not conn:
        raise RuntimeError(
            "Missing AIFOUNDRY_PROJECT_CONNECTION_STRING environment variable."
        )
    return conn


def _build_payload() -> dict[str, Any]:
    payload = build_statistician_foundry_agent_payload()

    model_override = os.getenv("AIFOUNDRY_MODEL", "").strip()
    if model_override:
        payload["model"] = model_override

    return payload


def _build_bridge() -> ColecticaToolBridge:
    transport = os.getenv("COLECTICA_MCP_TRANSPORT", "stdio").strip().lower()

    if transport == "http":
        url = os.getenv("COLECTICA_MCP_URL", "").strip()
        if not url:
            raise RuntimeError(
                "COLECTICA_MCP_URL is required when COLECTICA_MCP_TRANSPORT=http."
            )
        return ColecticaToolBridge(executor=ColecticaMcpHttpExecutor(url=url))

    command = os.getenv("COLECTICA_MCP_COMMAND", "colectica-mcp").strip() or "colectica-mcp"
    return ColecticaToolBridge(executor=ColecticaMcpStdioExecutor(command=command))


def _run_mcp_preflight_check(bridge: ColecticaToolBridge) -> None:
    result = bridge.execute_tool("health_check", {"auth_mode": "auto"})

    if isinstance(result, dict) and result.get("isError"):
        raise RuntimeError(f"Colectica MCP health_check failed: {result}")

    structured_content = result.get("structuredContent") if isinstance(result, dict) else None
    if isinstance(structured_content, dict):
        status = structured_content.get("status")
        if status != "ok":
            raise RuntimeError(f"Colectica MCP preflight returned non-ok status: {structured_content}")

    print("Colectica MCP preflight check passed.")


def main() -> None:
    connection_string = _require_connection_string()
    payload = _build_payload()
    bridge = _build_bridge()

    _run_mcp_preflight_check(bridge)

    client = AIProjectClient.from_connection_string(connection_string)

    # Create an AI Foundry agent with the statistician prompt and Colectica tool schema.
    agent = client.agents.create(**payload)

    print(f"Created agent: {agent.id} ({payload['name']})")

    thread = client.agents.create_thread()

    prompt = (
        "Find 5 Variable items related to labour force surveys, summarize metadata "
        "completeness gaps, and propose a safe transaction plan without committing changes."
    )

    client.agents.create_message(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=prompt,
    )

    run = client.agents.create_run(thread_id=thread.id, assistant_id=agent.id)

    while run.status in {"queued", "in_progress", "requires_action"}:
        if run.status == "requires_action":
            tool_outputs = bridge.build_tool_outputs_for_run(run)
            if tool_outputs:
                run = submit_tool_outputs(
                    client=client,
                    thread_id=thread.id,
                    run_id=run.id,
                    tool_outputs=tool_outputs,
                )
                continue

        time.sleep(1)
        run = client.agents.get_run(thread_id=thread.id, run_id=run.id)

    print(f"Run completed with status: {run.status}")

    messages = client.agents.list_messages(thread_id=thread.id)
    for msg in reversed(list(messages.data)):
        if getattr(msg, "role", "") == MessageRole.ASSISTANT:
            print("\nAssistant response:\n")
            for part in getattr(msg, "content", []):
                text = getattr(getattr(part, "text", None), "value", None)
                if text:
                    print(text)
            break


if __name__ == "__main__":
    main()
