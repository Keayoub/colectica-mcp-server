"""
Smoke check for Colectica MCP transport before Azure AI Foundry execution.

Usage:
  python integrations/examples/colectica_mcp_smoke_check.py

Environment variables:
  COLECTICA_MCP_TRANSPORT   stdio (default) or http
  COLECTICA_MCP_COMMAND     Stdio command (default: colectica-mcp)
  COLECTICA_MCP_URL         Streamable HTTP URL when transport=http
    COLECTICA_BASE_URL        Required by the Colectica MCP server
    COLECTICA_BEARER_TOKEN    Optional bearer auth
    COLECTICA_USERNAME        Optional basic auth username
    COLECTICA_PASSWORD        Optional basic auth password

Exit behavior:
  - exits non-zero if the MCP tool call fails
  - exits non-zero if `health_check` returns a non-`ok` status
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.aifoundry import ColecticaMcpHttpExecutor
from integrations.aifoundry import ColecticaMcpStdioExecutor
from integrations.aifoundry import ColecticaToolBridge


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


def main() -> None:
    bridge = _build_bridge()
    result = bridge.execute_tool("health_check", {"auth_mode": "auto"})

    if isinstance(result, dict) and result.get("isError"):
        raise RuntimeError(f"Colectica MCP health_check failed: {result}")

    structured_content = result.get("structuredContent") if isinstance(result, dict) else None
    if isinstance(structured_content, dict):
        status = structured_content.get("status")
        if status != "ok":
            raise RuntimeError(f"Colectica MCP preflight returned non-ok status: {structured_content}")

    print("Colectica MCP smoke check passed.")
    print(result)


if __name__ == "__main__":
    main()