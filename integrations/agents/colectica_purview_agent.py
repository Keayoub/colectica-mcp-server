# SPDX-License-Identifier: Apache-2.0
"""
Colectica → Purview Sync Agent

Orchestrates bidirectional integration between Colectica MCP and Purview MCP using Claude.
"""

from __future__ import annotations

import json
import asyncio
import os
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()


@dataclass
class SyncCheckpoint:
    """Track sync progress across runs."""

    last_synced_timestamp: str | None = None
    last_synced_id: str | None = None
    total_items_synced: int = 0
    failed_items: list[str] = field(default_factory=list)
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_synced_timestamp": self.last_synced_timestamp,
            "last_synced_id": self.last_synced_id,
            "total_items_synced": self.total_items_synced,
            "failed_items": self.failed_items,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_file(cls, path: str) -> SyncCheckpoint:
        """Load checkpoint from JSON file."""
        if Path(path).exists():
            with open(path) as f:
                data = json.load(f)
                return cls(**data)
        return cls()

    def save(self, path: str):
        """Save checkpoint to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


class Colectica_PurviewAgent:
    """
    Claude SDK implementation of Colectica → Purview sync agent.

    ⚠️  This is ONE example using Claude SDK. The same orchestration pattern
    works with ANY agent framework (AI Foundry, LangChain, Local LLMs, etc).
    See integrations/docs/FRAMEWORK_AGNOSTIC.md for other implementations.

    Handles:
    - Data transformation (Colectica → Purview types)
    - Sync workflows (search, transform, validate, import)
    - Checkpoint management (resumable syncs)
    - Tool orchestration via Claude API
    """

    def __init__(self, checkpoint_file: str = ".sync_checkpoint.json"):
        """
        Initialize agent.

        Args:
            checkpoint_file: Path to checkpoint JSON for resumable syncs
        """
        self.client = Anthropic()
        self.checkpoint_file = checkpoint_file
        self.checkpoint = SyncCheckpoint.from_file(checkpoint_file)
        self.correlation_id = f"sync_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    def sync_survey_items(
        self,
        query: str = "all",
        dry_run: bool = True,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Sync Colectica items to Purview.

        Args:
            query: Colectica search query (e.g., "type:QuestionItem")
            dry_run: If True, preview only (no Purview mutations)
            limit: Max items to sync per batch

        Returns:
            Summary of sync operation
        """
        user_message = f"""
Sync Colectica items to Purview.

Parameters:
- Search query: {query}
- Dry run: {dry_run}
- Limit: {limit}
- Correlation ID: {self.correlation_id}
- Resume from: {self.checkpoint.last_synced_id or 'beginning'}

Steps:
1. Use search() to find matching items in Colectica
2. For each item, fetch full JSON with get_item_json_set()
3. Transform each to Purview DataSet/Column/Process entity
4. If dry_run=true, just show preview; if false, call bulk_import() to sync
5. Update checkpoint with results
6. Report summary (created, updated, failed counts)
"""
        return self._run_agent_loop(user_message)

    def validate_consistency(self) -> dict[str, Any]:
        """
        Verify that Purview entities match Colectica source.

        Returns:
            Validation report with mismatches and recommendations
        """
        user_message = f"""
Validate consistency between Colectica and Purview.

Steps:
1. Search Purview for entities with sourceSystemId = "{self.correlation_id}"
2. For each entity, look up the source item in Colectica
3. Compare key attributes (name, description, owner, etc.)
4. Report mismatches and suggest remediation
5. For any conflicts, suggest manual review or auto-update
"""
        return self._run_agent_loop(user_message)

    def _run_agent_loop(self, user_message: str) -> dict[str, Any]:
        """
        Run the agentic loop with Claude.

        Uses tool_use to call MCP server functions.
        """
        messages = [{"role": "user", "content": user_message}]
        system = self._build_system_prompt()

        print(f"\n{'='*70}")
        print(f"User: {user_message[:100]}...")
        print(f"{'='*70}\n")

        max_iterations = 10
        iteration = 0
        result = {"status": "incomplete"}

        while iteration < max_iterations:
            iteration += 1

            # Call Claude with available tools
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                system=system,
                tools=self._get_mcp_tools_schema(),
                messages=messages,
            )

            print(f"[Iteration {iteration}] Stop reason: {response.stop_reason}")

            # Check if agent is done
            if response.stop_reason == "end_turn":
                # Extract final message from response
                for block in response.content:
                    if hasattr(block, "text"):
                        print(f"\n✓ Agent completed:\n{block.text}")
                        result = {
                            "status": "complete",
                            "message": block.text,
                        }
                break

            # Process tool calls
            if response.stop_reason == "tool_use":
                # Add assistant response to messages
                messages.append({"role": "assistant", "content": response.content})

                # Process each tool call
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input

                        print(f"\n→ Calling: {tool_name}")
                        print(f"  Input: {json.dumps(tool_input, indent=2)[:200]}...")

                        # Execute tool
                        result = self._execute_tool(tool_name, tool_input)

                        print(
                            f"  Result: {json.dumps(result, indent=2)[:300]}..."
                        )

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            }
                        )

                # Add tool results to messages
                messages.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason
                print(f"Unexpected stop reason: {response.stop_reason}")
                result = {"status": "error", "stop_reason": response.stop_reason}
                break

        # Update checkpoint
        self.checkpoint.last_synced_timestamp = datetime.utcnow().isoformat()
        self.checkpoint.correlation_id = self.correlation_id
        self.checkpoint.save(self.checkpoint_file)
        print(f"\n✓ Checkpoint saved to {self.checkpoint_file}")

        return result

    def _build_system_prompt(self) -> str:
        """Construct system prompt with context about both MCPs."""
        return """
You are a data sync orchestrator that bridges Colectica Repository and Microsoft Purview.

Your role:
1. Query Colectica MCP for survey items, variables, and metadata
2. Transform Colectica items to Purview entities
3. Manage the sync workflow between systems
4. Handle conflicts and validation
5. Track sync state for resumable operations

Available MCPs:
- Colectica MCP: Access Colectica Repository REST API (list_operations, search, get_item, get_item_json_set, etc.)
- Purview MCP: Manage Microsoft Purview (bulk_import, search, manage_entities, etc.)

Type Mapping:
- QuestionItem → DataSet
- Variable → Column
- Instrument → Process
- ResourcePackage → DataSet

Sync Workflow:
1. Query Colectica for items matching criteria
2. Transform each item to Purview entity format
3. Batch items into manageable chunks (max 50 per API call)
4. Use bulk_import to create/update in Purview
5. Validate consistency after sync
6. Report results and update checkpoint

Guidelines:
- Always preview before actual sync (dry-run first)
- Handle errors gracefully with retry logic
- Track failed items for manual review
- Use correlation_id for audit trails
- Respect rate limits on both APIs
"""

    def _get_mcp_tools_schema(self) -> list[dict]:
        """Return available tools from both MCPs."""
        return [
            # Colectica MCP tools
            {
                "name": "colectica_search",
                "description": "Search Colectica Repository for items",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g., 'type:QuestionItem')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results",
                            "default": 50,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "colectica_get_item_json_set",
                "description": "Get a Colectica item and its children in JSON format",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agency": {"type": "string", "description": "Agency ID"},
                        "identifier": {"type": "string", "description": "Item ID"},
                        "version": {
                            "type": "integer",
                            "description": "Item version (optional)",
                        },
                    },
                    "required": ["agency", "identifier"],
                },
            },
            # Purview MCP tools
            {
                "name": "purview_bulk_import",
                "description": "Bulk import entities into Purview",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "entities": {
                            "type": "array",
                            "description": "List of Purview entities",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "Preview only",
                            "default": True,
                        },
                    },
                    "required": ["entities"],
                },
            },
            {
                "name": "purview_search",
                "description": "Search for entities in Purview",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
        ]

    def _execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """
        Execute a tool call (mock implementation).

        In production, this would call the actual MCP servers.
        """
        # Mock implementations for demonstration
        if tool_name == "colectica_search":
            return {
                "total": 3,
                "items": [
                    {"id": "Q001", "name": "Annual Survey 2025", "type": "QuestionItem"},
                    {"id": "V001", "name": "Age Variable", "type": "Variable"},
                    {"id": "I001", "name": "Main Survey Instrument", "type": "Instrument"},
                ],
            }
        elif tool_name == "colectica_get_item_json_set":
            return {
                "id": tool_input["identifier"],
                "name": "Sample Item",
                "type": "QuestionItem",
                "description": "A sample DDI item",
                "children": [],
            }
        elif tool_name == "purview_bulk_import":
            return {
                "status": "preview" if tool_input.get("dry_run") else "imported",
                "total": len(tool_input["entities"]),
                "created": len(tool_input["entities"]),
                "updated": 0,
                "failed": 0,
            }
        elif tool_name == "purview_search":
            return {
                "total": 1,
                "entities": [
                    {"id": "dataset-Q001", "name": "Annual Survey 2025", "typeName": "DataSet"}
                ],
            }
        return {"error": "Tool not found"}
