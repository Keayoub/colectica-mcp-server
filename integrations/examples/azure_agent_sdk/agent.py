# SPDX-License-Identifier: Apache-2.0
"""
Colectica ↔ Purview Sync Agent — Azure AI Projects SDK

Hosts the governance agent using the Azure AI Foundry Agent Service.
Supports all five integration scenarios:
  1. Metadata sync (Colectica → Purview)
  2. Lineage propagation
  3. Drift detection
  4. Tag governance round-trip
  5. Natural language cross-system queries

Deploy to:
  - AI Foundry Agent Service (managed)
  - Azure Container Apps (containerised, see Dockerfile)
  - Local (python agent.py)

Environment variables required:
  PROJECT_CONNECTION_STRING   Azure AI Foundry project connection string
  AZURE_OPENAI_DEPLOYMENT     Model deployment name (default: gpt-4o)
  COLECTICA_BASE_URL          Colectica portal base URL
  COLECTICA_BEARER_TOKEN      Colectica bearer token (or use basic auth below)
  COLECTICA_USERNAME          Colectica username (basic auth)
  COLECTICA_PASSWORD          Colectica password (basic auth)
  PURVIEW_ACCOUNT_NAME        Azure Purview account name
  AZURE_TENANT_ID             Azure tenant ID
  AZURE_CLIENT_ID             Service principal client ID
  AZURE_CLIENT_SECRET         Service principal secret
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEventHandler,
    MessageDeltaChunk,
    RunStep,
    ThreadMessage,
    ThreadRun,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP subprocess wrapper — bridges Azure agent tool calls to MCP stdio
# ---------------------------------------------------------------------------

class MCPBridge:
    """Wraps a running MCP server process and exposes call_tool()."""

    def __init__(self, name: str, command: list[str], env: dict[str, str]) -> None:
        self.name = name
        merged_env = {**os.environ, **env}
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=merged_env,
        )
        self._req_id = 0
        log.info("MCP bridge started: %s", name)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        line = json.dumps(request) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()
        response_line = self._proc.stdout.readline()
        response = json.loads(response_line)
        if "error" in response:
            raise RuntimeError(f"MCP {self.name}/{tool_name} error: {response['error']}")
        # MCP returns content as list of text blocks
        content = response.get("result", {}).get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return response.get("result", {})

    def close(self) -> None:
        self._proc.terminate()
        log.info("MCP bridge stopped: %s", self.name)


def _start_mcp_bridges() -> tuple[MCPBridge, MCPBridge]:
    colectica = MCPBridge(
        name="colectica",
        command=["colectica-mcp", "--transport", "stdio"],
        env={
            "COLECTICA_BASE_URL": os.environ["COLECTICA_BASE_URL"],
            "COLECTICA_BEARER_TOKEN": os.getenv("COLECTICA_BEARER_TOKEN", ""),
            "COLECTICA_USERNAME": os.getenv("COLECTICA_USERNAME", ""),
            "COLECTICA_PASSWORD": os.getenv("COLECTICA_PASSWORD", ""),
        },
    )
    purview = MCPBridge(
        name="purview",
        command=["purview-mcp", "--transport", "stdio"],
        env={
            "PURVIEW_ACCOUNT_NAME": os.environ["PURVIEW_ACCOUNT_NAME"],
            "AZURE_TENANT_ID": os.environ["AZURE_TENANT_ID"],
            "AZURE_CLIENT_ID": os.environ["AZURE_CLIENT_ID"],
            "AZURE_CLIENT_SECRET": os.environ["AZURE_CLIENT_SECRET"],
        },
    )
    return colectica, purview


# ---------------------------------------------------------------------------
# Tool definitions — exposed to the Azure AI Agent
# ---------------------------------------------------------------------------

TOOLS = [
    # --- Colectica tools ---
    {
        "type": "function",
        "function": {
            "name": "colectica__search",
            "description": "Search Colectica Repository items by text query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "searchText": {"type": "string", "description": "Free-text search query"},
                    "maxResults": {"type": "integer", "default": 50},
                    "itemTypes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by item types e.g. QuestionItem, Variable",
                    },
                },
                "required": ["searchText"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "colectica__get_item_json_set",
            "description": "Get a Colectica item and all its children as JSON.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agency": {"type": "string"},
                    "identifier": {"type": "string"},
                    "version": {"type": "integer"},
                },
                "required": ["agency", "identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "colectica__get_relationship_matrix",
            "description": "Get all items in a set and the relationships among them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "Agency": {"type": "string"},
                                "Identifier": {"type": "string"},
                            },
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "colectica__get_tags",
            "description": "Get tags applied to a Colectica item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agency": {"type": "string"},
                    "id": {"type": "string"},
                    "version": {"type": "integer"},
                },
                "required": ["agency", "id", "version"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "colectica__add_tag",
            "description": "Add a tag to a Colectica item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agency": {"type": "string"},
                    "id": {"type": "string"},
                    "version": {"type": "integer"},
                    "tag": {"type": "string"},
                },
                "required": ["agency", "id", "version", "tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "colectica__get_item_latest_version",
            "description": "Get the latest version number of a Colectica item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agency": {"type": "string"},
                    "id": {"type": "string"},
                },
                "required": ["agency", "id"],
            },
        },
    },
    # --- Purview tools ---
    {
        "type": "function",
        "function": {
            "name": "purview__bulk_import",
            "description": (
                "Import or update entities in Purview. "
                "Always call with dry_run=true first to preview changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entities": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of Purview Atlas entities (max 50 per call)",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "default": True,
                        "description": "Preview only when true. Set false only after user confirms.",
                    },
                },
                "required": ["entities"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "purview__search",
            "description": "Search entities in the Purview data catalog.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "purview__add_classification",
            "description": "Add a classification to a Purview entity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "classification_name": {"type": "string"},
                },
                "required": ["entity_id", "classification_name"],
            },
        },
    },
]

SYSTEM_PROMPT = """\
You are a data governance agent that bridges Colectica Repository (survey/DDI metadata)
and Microsoft Purview (data catalog).

Type mapping (always apply):
- QuestionItem  → DataSet
- Variable      → Column
- Instrument    → Process
- ResourcePackage → DataSet

Available skills:
1. sync_metadata    — search Colectica, transform, import to Purview (always dry_run first)
2. propagate_lineage — map Colectica relationships to Purview lineage graph
3. detect_drift     — find items missing or stale in Purview vs Colectica
4. sync_tags        — push Colectica tags to Purview or pull Purview classifications back
5. cross_system_query — answer questions that require data from both systems

Rules:
- ALWAYS preview (dry_run=true) before any write; ask user to confirm before committing.
- NEVER delete items without explicit double confirmation.
- Batch bulk_import to ≤50 entities per call.
- Set qualifiedName = colectica://{agency}/{identifier} for all imported entities.
- After each major step output a one-line status (✓ Found N items, ✓ Imported N entities).
"""


# ---------------------------------------------------------------------------
# Tool execution router
# ---------------------------------------------------------------------------

TYPE_MAP = {
    "QuestionItem": "DataSet",
    "Variable": "Column",
    "VariableStatistic": "Column",
    "Instrument": "Process",
    "ResourcePackage": "DataSet",
    "ConceptualComponent": "Process",
}


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    colectica: MCPBridge,
    purview: MCPBridge,
) -> str:
    try:
        if tool_name == "colectica__search":
            result = colectica.call_tool("search", {"body": arguments})
        elif tool_name == "colectica__get_item_json_set":
            result = colectica.call_tool(
                "get_item_json_set",
                {
                    "agency": arguments["agency"],
                    "identifier": arguments["identifier"],
                    "version": arguments.get("version"),
                },
            )
        elif tool_name == "colectica__get_relationship_matrix":
            result = colectica.call_tool(
                "get_relationship_matrix", {"body": {"Items": arguments["items"]}}
            )
        elif tool_name == "colectica__get_tags":
            result = colectica.call_tool("get_tags", arguments)
        elif tool_name == "colectica__add_tag":
            result = colectica.call_tool("add_tag", arguments)
        elif tool_name == "colectica__get_item_latest_version":
            result = colectica.call_tool("get_item_latest_version", arguments)
        elif tool_name == "purview__bulk_import":
            result = purview.call_tool("bulk_import", arguments)
        elif tool_name == "purview__search":
            result = purview.call_tool("search", arguments)
        elif tool_name == "purview__add_classification":
            result = purview.call_tool("add_classification", arguments)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        return json.dumps(result)
    except Exception as exc:  # noqa: BLE001
        log.error("Tool %s failed: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Event handler — streams agent output to stdout
# ---------------------------------------------------------------------------

class StreamingHandler(AgentEventHandler):
    def on_message_delta(self, delta: MessageDeltaChunk) -> None:
        for block in delta.delta.content or []:
            if hasattr(block, "text") and block.text:
                print(block.text.value or "", end="", flush=True)

    def on_thread_run(self, run: ThreadRun) -> None:
        log.debug("Run status: %s", run.status)

    def on_run_step(self, step: RunStep) -> None:
        log.debug("Run step: %s", step.type)

    def on_thread_message(self, message: ThreadMessage) -> None:
        pass


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

def run_agent(user_message: str) -> None:
    connection_string = os.environ["PROJECT_CONNECTION_STRING"]
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    colectica_bridge, purview_bridge = _start_mcp_bridges()

    try:
        client = AIProjectClient.from_connection_string(
            credential=DefaultAzureCredential(),
            conn_str=connection_string,
        )

        # Create or reuse agent
        agent = client.agents.create_agent(
            model=deployment,
            name="ColecticaPurviewAgent",
            instructions=SYSTEM_PROMPT,
            tools=TOOLS,
        )
        log.info("Agent created: %s", agent.id)

        thread = client.agents.create_thread()
        client.agents.create_message(
            thread_id=thread.id,
            role="user",
            content=user_message,
        )

        with client.agents.create_stream(
            thread_id=thread.id,
            assistant_id=agent.id,
            event_handler=StreamingHandler(),
        ) as stream:
            stream.until_done()

            # Process tool calls in the run
            run = stream.get_final_run()
            while run.status == "requires_action":
                tool_calls = run.required_action.submit_tool_outputs.tool_calls
                tool_outputs = []
                for tc in tool_calls:
                    args = json.loads(tc.function.arguments)
                    log.info("Calling tool: %s", tc.function.name)
                    output = execute_tool(
                        tc.function.name, args, colectica_bridge, purview_bridge
                    )
                    tool_outputs.append({"tool_call_id": tc.id, "output": output})

                with client.agents.submit_tool_outputs_stream(
                    thread_id=thread.id,
                    run_id=run.id,
                    tool_outputs=tool_outputs,
                    event_handler=StreamingHandler(),
                ) as tool_stream:
                    tool_stream.until_done()
                    run = tool_stream.get_final_run()

        print()  # newline after streamed output
        log.info("Run completed: %s", run.status)

        # Cleanup agent (optional — remove for persistent agents)
        client.agents.delete_agent(agent.id)

    finally:
        colectica_bridge.close()
        purview_bridge.close()


if __name__ == "__main__":
    import sys

    message = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "How many Colectica QuestionItems are missing from my Purview catalog? "
        "Show me the list and offer to sync them."
    )
    run_agent(message)
