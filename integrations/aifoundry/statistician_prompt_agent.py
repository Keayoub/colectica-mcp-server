# SPDX-License-Identifier: Apache-2.0
"""
Statistician Prompt Agent for Azure AI Foundry.

Builds a prompt-agent payload specialized for survey metadata workflows
on top of the Colectica MCP server.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_prompt() -> str:
    prompt_path = Path(__file__).with_name("statistician_prompt.md")
    return prompt_path.read_text(encoding="utf-8")


@dataclass(slots=True)
class StatisticianPromptAgent:
    """Definition for a statistician-focused prompt agent in Azure AI Foundry."""

    name: str = "Colectica-Statistician"
    model: str = "gpt-4o"

    def instructions(self) -> str:
        return _load_prompt()

    def tools(self) -> list[dict[str, Any]]:
        """
        Return tool definitions expected by AI Foundry function tools.

        The function names mirror Colectica MCP tool names so a runtime bridge can
        route calls directly to the server.
        """
        return [
            _tool("health_check", "Check Colectica API health and connectivity."),
            _tool("list_operation_categories", "List Colectica operation categories."),
            _tool(
                "list_operations_by_category",
                "List operations in a single category.",
                {
                    "category": {"type": "string", "description": "Operation category"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum operations to return",
                        "default": 200,
                    },
                },
                ["category"],
            ),
            _tool(
                "search",
                "Search Colectica items by terms and item types.",
                {
                    "arguments": {
                        "type": "object",
                        "description": "Search payload for Colectica search()",
                    }
                },
                ["arguments"],
            ),
            _tool(
                "search_advanced",
                "Run advanced Colectica search with filters.",
                {
                    "body": {
                        "type": "object",
                        "description": "Advanced search body",
                    }
                },
                ["body"],
            ),
            _tool(
                "get_item_json_set",
                "Get an item and related children as JSON.",
                {
                    "agency": {"type": "string"},
                    "identifier": {"type": "string"},
                    "version": {"type": "integer"},
                },
                ["agency", "identifier"],
            ),
            _tool(
                "get_ddi_fragment",
                "Get DDI XML fragment for an item.",
                {
                    "agency": {"type": "string"},
                    "identifier": {"type": "string"},
                    "version": {"type": "integer"},
                },
                ["agency", "identifier"],
            ),
            _tool(
                "audit_item_completeness",
                "Audit metadata completeness for selected items.",
                {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "language": {"type": "string", "default": "en-US"},
                },
                ["items"],
            ),
            _tool(
                "find_harmonizable_variables",
                "Find variables that can be harmonized across studies.",
                {
                    "body": {
                        "type": "object",
                        "description": "Harmonization query payload",
                    }
                },
                ["body"],
            ),
            _tool(
                "get_codebook_for_variable",
                "Retrieve a variable with full codebook details.",
                {
                    "agency": {"type": "string"},
                    "id": {"type": "string"},
                    "version": {"type": "integer"},
                },
                ["agency", "id"],
            ),
            _tool("create_transaction", "Start a Colectica transaction."),
            _tool(
                "add_items_to_transaction",
                "Add DDI items to an active transaction.",
                {
                    "body": {
                        "type": "object",
                        "description": "Transaction payload with TransactionId and Items",
                    }
                },
                ["body"],
            ),
            _tool(
                "commit_transaction",
                "Commit a Colectica transaction.",
                {"body": {"type": "object"}},
                ["body"],
            ),
            _tool(
                "cancel_transaction",
                "Cancel a Colectica transaction.",
                {"body": {"type": "object"}},
                ["body"],
            ),
        ]

    def to_foundry_payload(self) -> dict[str, Any]:
        """Return a ready-to-use `client.agents.create(...)` payload."""
        return {
            "name": self.name,
            "model": self.model,
            "instructions": self.instructions(),
            "tools": self.tools(),
        }


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


def build_statistician_foundry_agent_payload() -> dict[str, Any]:
    """Convenience factory for scripts and notebooks."""
    return StatisticianPromptAgent().to_foundry_payload()
