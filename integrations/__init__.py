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
    "StatisticianPromptAgent",
    "build_statistician_foundry_agent_payload",
    "ColecticaMcpStdioExecutor",
    "ColecticaMcpHttpExecutor",
    "ColecticaToolBridge",
    "extract_tool_calls",
    "submit_tool_outputs",
]

from .agents import Colectica_PurviewAgent
from .aifoundry import (
    ColecticaMcpHttpExecutor,
    ColecticaMcpStdioExecutor,
    ColecticaToolBridge,
    StatisticianPromptAgent,
    build_statistician_foundry_agent_payload,
    extract_tool_calls,
    submit_tool_outputs,
)
