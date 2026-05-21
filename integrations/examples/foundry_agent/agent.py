# SPDX-License-Identifier: Apache-2.0
"""
Colectica ↔ Purview Agent — Azure AI Foundry Agent SDK

Deploys an Azure AI Agent that uses both MCPs via the MCP tool extension.
Runs fully in the cloud (AI Foundry) or as a container (Container Apps / ACI).

Requirements:
  - Azure AI Hub + Project
  - Both MCP servers reachable over HTTPS (set env-vars below)
  - azure-ai-projects >= 1.0.0b10
"""

from __future__ import annotations

import os
import sys
import json
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    Agent,
    AgentThread,
    MessageRole,
    RunStatus,
    McpToolDefinition,
    McpToolSetDefinition,
    RequiredMcpToolCall,
    SubmitToolOutputsAction,
    ToolOutput,
)
from azure.identity import DefaultAzureCredential

# ---------------------------------------------------------------------------
# Configuration — override via environment variables
# ---------------------------------------------------------------------------
PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]   # e.g. https://<hub>.api.azureml.ms
COLECTICA_MCP_URL = os.environ["COLECTICA_MCP_URL"]          # e.g. https://colectica-mcp.example.com/mcp
PURVIEW_MCP_URL   = os.environ["PURVIEW_MCP_URL"]            # e.g. https://purview-mcp.example.com/mcp
MODEL_NAME        = os.environ.get("AZURE_AI_MODEL", "gpt-4o")

SYSTEM_PROMPT = """
You are a data governance orchestrator that bridges Colectica Repository and
Microsoft Purview using their MCP tools.

Type mapping:
  QuestionItem      → DataSet
  Variable          → Column
  VariableStatistic → Column
  Instrument        → Process
  ResourcePackage   → DataSet

Qualified name convention: colectica://<agency>/<identifier>/<version>

Rules:
1. Always dry-run Purview writes before committing.
2. Batch imports ≤50 entities per call.
3. Report: items found, transformed, imported, failed.
4. Never fabricate identifiers, URNs, or Purview GUIDs.
"""


def build_client() -> AIProjectClient:
    return AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
    )


def create_agent(client: AIProjectClient) -> Agent:
    """Create (or reuse) an AI Foundry agent with both MCP tool sets."""
    toolset = McpToolSetDefinition(
        tools=[
            McpToolDefinition(
                server_label="colectica",
                server_url=COLECTICA_MCP_URL,
                # Add auth header if your MCP server requires it:
                # headers={"Authorization": f"Bearer {os.environ['COLECTICA_TOKEN']}"},
            ),
            McpToolDefinition(
                server_label="purview",
                server_url=PURVIEW_MCP_URL,
                # headers={"Authorization": f"Bearer {os.environ['PURVIEW_TOKEN']}"},
            ),
        ]
    )

    agent = client.agents.create_agent(
        model=MODEL_NAME,
        name="colectica-purview-agent",
        instructions=SYSTEM_PROMPT,
        tools=toolset,
    )
    print(f"✓ Agent created: {agent.id}")
    return agent


def run_scenario(
    client: AIProjectClient,
    agent: Agent,
    user_message: str,
) -> str:
    """
    Execute a single scenario against the agent and return the final answer.
    Handles MCP tool-approval flow automatically.
    """
    thread: AgentThread = client.agents.threads.create()

    client.agents.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=user_message,
    )

    run = client.agents.runs.create(
        thread_id=thread.id,
        agent_id=agent.id,
    )

    # Agentic loop — process tool calls until the run completes
    while run.status in (RunStatus.QUEUED, RunStatus.IN_PROGRESS, RunStatus.REQUIRES_ACTION):
        run = client.agents.runs.get(thread_id=thread.id, run_id=run.id)

        if run.status == RunStatus.REQUIRES_ACTION:
            action: SubmitToolOutputsAction = run.required_action
            tool_outputs: list[ToolOutput] = []

            for tool_call in action.submit_tool_outputs.tool_calls:
                if isinstance(tool_call, RequiredMcpToolCall):
                    # Approve the MCP tool call (no local execution needed —
                    # the platform calls the MCP server directly).
                    tool_outputs.append(
                        ToolOutput(tool_call_id=tool_call.id, output="approved")
                    )
                    print(
                        f"  → MCP call approved: {tool_call.function.name}"
                        f"({json.dumps(json.loads(tool_call.function.arguments), separators=(',', ':'))[:80]}...)"
                    )

            run = client.agents.runs.submit_tool_outputs(
                thread_id=thread.id,
                run_id=run.id,
                tool_outputs=tool_outputs,
            )

    if run.status != RunStatus.COMPLETED:
        raise RuntimeError(f"Run ended with status: {run.status} — {run.last_error}")

    messages = client.agents.messages.list(thread_id=thread.id)
    for msg in messages:
        if msg.role == MessageRole.ASSISTANT:
            for content_block in msg.content:
                if hasattr(content_block, "text"):
                    return content_block.text.value

    return "(no response)"


# ---------------------------------------------------------------------------
# Pre-built scenario helpers
# ---------------------------------------------------------------------------

def scenario_sync_metadata(client: AIProjectClient, agent: Agent, query: str = "type:QuestionItem", dry_run: bool = True) -> str:
    flag = "DRY RUN — preview only, do not import" if dry_run else "LIVE — import to Purview"
    return run_scenario(
        client, agent,
        f"Sync Colectica items matching '{query}' to Purview. Mode: {flag}. "
        f"Show a summary table before importing. Batch size ≤50.",
    )


def scenario_lineage(client: AIProjectClient, agent: Agent, item_identifier: str, agency: str) -> str:
    return run_scenario(
        client, agent,
        f"Build and register data lineage in Purview for Colectica item "
        f"agency={agency}, identifier={item_identifier}. "
        f"Use the relationship matrix to discover all edges, then create Purview lineage.",
    )


def scenario_drift(client: AIProjectClient, agent: Agent, since_date: str | None = None) -> str:
    scope = f"since {since_date}" if since_date else "for all items"
    return run_scenario(
        client, agent,
        f"Run a metadata drift check {scope}. "
        f"Identify items missing from Purview, stale entities (attributes changed), "
        f"and orphaned Purview entities. Return a structured report.",
    )


def scenario_tag_sync(client: AIProjectClient, agent: Agent, direction: str = "colectica→purview", tag_filter: str | None = None) -> str:
    tag_part = f"Only sync tag '{tag_filter}'." if tag_filter else "Sync all tags."
    return run_scenario(
        client, agent,
        f"Synchronise tags and classifications. Direction: {direction}. {tag_part} "
        f"Report what was added, skipped, and failed.",
    )


def scenario_query(client: AIProjectClient, agent: Agent, question: str) -> str:
    return run_scenario(client, agent, question)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

SCENARIOS = {
    "sync":    ("Sync QuestionItems to Purview (dry run)", lambda c, a: scenario_sync_metadata(c, a)),
    "lineage": ("Lineage for a sample item",               lambda c, a: scenario_lineage(c, a, "SAMPLE-001", "int.example")),
    "drift":   ("Drift detection for all items",           lambda c, a: scenario_drift(c, a)),
    "tags":    ("Sync tags Colectica→Purview",             lambda c, a: scenario_tag_sync(c, a)),
    "query":   ("Coverage report: how many items in each system",
                lambda c, a: scenario_query(c, a, "Give me a coverage report: how many QuestionItems are in Colectica and how many are already in Purview?")),
}


def main() -> None:
    scenario_key = sys.argv[1] if len(sys.argv) > 1 else "query"
    custom_msg   = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else None

    if scenario_key not in SCENARIOS and not custom_msg:
        print("Usage: python agent.py <scenario> [custom message]")
        print(f"Scenarios: {', '.join(SCENARIOS)}")
        sys.exit(1)

    client = build_client()
    agent  = create_agent(client)

    try:
        if custom_msg:
            print(f"\n▶ Custom: {custom_msg}\n")
            answer = run_scenario(client, agent, custom_msg)
        else:
            label, fn = SCENARIOS[scenario_key]
            print(f"\n▶ Scenario: {label}\n")
            answer = fn(client, agent)

        print(f"\n{'─'*70}\n{answer}\n{'─'*70}")
    finally:
        client.agents.delete_agent(agent.id)
        print(f"\n✓ Agent {agent.id} deleted")


if __name__ == "__main__":
    main()
