"""
Example: Create and run the Colectica Statistician Prompt Agent in Azure AI Foundry.

Usage:
  setx AIFOUNDRY_PROJECT_CONNECTION_STRING "<your-connection-string>"
  python integrations/examples/aifoundry_statistician_prompt_agent_example.py

Optional environment variables:
  AIFOUNDRY_MODEL                        Override model in payload
  AIFOUNDRY_PROJECT_CONNECTION_STRING    AI Foundry project connection string
"""

from __future__ import annotations

import os
import time
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MessageRole

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


def main() -> None:
    connection_string = _require_connection_string()
    payload = _build_payload()

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
    bridge = ColecticaToolBridge()

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
