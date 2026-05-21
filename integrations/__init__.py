# SPDX-License-Identifier: Apache-2.0
"""
Colectica Integration Module

Provides orchestration layer for integrating Colectica MCP with other systems (Purview, etc).
Contains agent definitions, examples, and documentation for multi-MCP workflows.

Submodules:
- agents: Agent class definitions for orchestrating MCPs
- examples: Working examples and reference implementations
- docs: Detailed documentation and diagrams

Usage:
    from integrations.agents import Colectica_PurviewAgent
    agent = Colectica_PurviewAgent()
    agent.sync_survey_items(query="type:QuestionItem", dry_run=True)
"""

__version__ = "0.1.0"
__all__ = [
    "Colectica_PurviewAgent",
]
