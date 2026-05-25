# SPDX-License-Identifier: Apache-2.0
"""Azure AI Foundry prompt-agent assets for Colectica workflows."""

from .statistician_prompt_agent import (
    StatisticianPromptAgent,
    build_statistician_foundry_agent_payload,
)
from .colectica_tool_bridge import (
    ColecticaToolBridge,
    extract_tool_calls,
    submit_tool_outputs,
)

__all__ = [
    "StatisticianPromptAgent",
    "build_statistician_foundry_agent_payload",
    "ColecticaToolBridge",
    "extract_tool_calls",
    "submit_tool_outputs",
]
