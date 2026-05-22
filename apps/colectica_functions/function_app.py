# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import logging
import os

import azure.functions as func
from dotenv import load_dotenv

from colectica_mcp.client import ColecticaApiClient, ColecticaApiError
from colectica_mcp.config import ColecticaConfig

logger = logging.getLogger("colectica-mcp-functions")

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_JSON = "application/json"
_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _make_client() -> ColecticaApiClient:
    """Create a fresh client, honouring env / Key Vault overrides at call time."""
    load_dotenv(override=True)
    return ColecticaApiClient(ColecticaConfig.from_env())


def _json_response(data: object, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status,
        headers={**_CORS, "Content-Type": _JSON},
    )


def _error(message: str, status: int = 500) -> func.HttpResponse:
    return _json_response({"error": message}, status)


# ── /api/health ────────────────────────────────────────────────────────────────

@app.route(route="health", methods=["GET"])
async def health_check(req: func.HttpRequest) -> func.HttpResponse:
    try:
        client = _make_client()
        await client.discover_openapi()
        return _json_response({"status": "healthy", "service": "colectica-mcp"})
    except ColecticaApiError as exc:
        return _error(str(exc), 503)
    except Exception as exc:
        logger.exception("Health check failed")
        return _error(str(exc), 503)


# ── /api/operations ────────────────────────────────────────────────────────────

@app.route(route="operations", methods=["GET"])
async def list_operations(req: func.HttpRequest) -> func.HttpResponse:
    """Return all Colectica API operations, optionally filtered by ?category=<name>."""
    try:
        client = _make_client()
        ops = await client.list_operations()
        category = req.params.get("category", "").strip().lower()
        if category:
            ops = [o for o in ops if category in o.get("path", "").lower()]
        return _json_response({"count": len(ops), "operations": ops})
    except ColecticaApiError as exc:
        return _error(str(exc), 502)
    except Exception as exc:
        logger.exception("list_operations failed")
        return _error(str(exc))


# ── /api/operations/{operation_id} ────────────────────────────────────────────

@app.route(route="operations/{operation_id}", methods=["GET"])
async def get_operation(req: func.HttpRequest) -> func.HttpResponse:
    operation_id = req.route_params.get("operation_id", "")
    try:
        client = _make_client()
        detail = await client.operation_details(operation_id)
        return _json_response(detail)
    except ColecticaApiError as exc:
        status = 404 if "not found" in str(exc).lower() else 502
        return _error(str(exc), status)
    except Exception as exc:
        logger.exception("get_operation failed")
        return _error(str(exc))


# ── /api/call ─────────────────────────────────────────────────────────────────

@app.route(route="call", methods=["POST", "OPTIONS"])
async def call_operation(req: func.HttpRequest) -> func.HttpResponse:
    """Invoke a Colectica API operation.

    Request body (JSON):
        {
            "operationId": "<string>",
            "arguments":   { ... }   // optional
        }
    """
    if req.method == "OPTIONS":
        return func.HttpResponse(b"", status_code=200, headers=_CORS)

    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON.", 400)

    operation_id = (body.get("operationId") or body.get("operation_id") or "").strip()
    if not operation_id:
        return _error("'operationId' is required.", 400)

    arguments: dict = body.get("arguments") or {}

    try:
        client = _make_client()
        result = await client.call_operation(operation_id, arguments)
        return _json_response(result)
    except ColecticaApiError as exc:
        msg = str(exc)
        status = 404 if "not found" in msg.lower() else 502
        return _error(msg, status)
    except Exception as exc:
        logger.exception("call_operation failed for %s", operation_id)
        return _error(str(exc))


# ── /api/mcp  (MCP JSON-RPC over HTTP) ────────────────────────────────────────

@app.route(route="mcp", methods=["GET", "POST", "OPTIONS"])
async def mcp_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Minimal MCP JSON-RPC handler (tools/list, tools/call, initialize).

    Compatible with MCP clients that connect via Streamable HTTP.
    """
    if req.method == "OPTIONS":
        return func.HttpResponse(b"", status_code=200, headers=_CORS)

    if req.method == "GET":
        return _json_response({
            "service": "colectica-mcp",
            "protocol": "MCP JSON-RPC 2.0",
            "endpoints": {
                "mcp": "POST /api/mcp",
                "operations": "GET /api/operations",
                "call": "POST /api/call",
                "health": "GET /api/health",
            },
        })

    # POST — JSON-RPC 2.0
    try:
        rpc = req.get_json()
    except ValueError:
        return _json_rpc_error(None, -32700, "Parse error")

    rpc_id = rpc.get("id")
    method = rpc.get("method", "")
    params = rpc.get("params") or {}

    try:
        client = _make_client()

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "colectica-mcp", "version": "0.1.8"},
            }

        elif method == "tools/list":
            ops = await client.list_operations()
            result = {
                "tools": [
                    {
                        "name": o["operation_id"],
                        "description": f"{o['method']} {o['path']}",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                    for o in ops
                ]
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}
            if not tool_name:
                return _json_rpc_error(rpc_id, -32602, "Missing tool name")
            data = await client.call_operation(tool_name, arguments)
            result = {
                "content": [{"type": "text", "text": json.dumps(data, default=str)}]
            }

        else:
            return _json_rpc_error(rpc_id, -32601, f"Method not found: {method}")

    except ColecticaApiError as exc:
        return _json_rpc_error(rpc_id, -32000, str(exc))
    except Exception as exc:
        logger.exception("MCP method %s failed", method)
        return _json_rpc_error(rpc_id, -32603, str(exc))

    return func.HttpResponse(
        json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result}, default=str),
        status_code=200,
        headers={**_CORS, "Content-Type": _JSON},
    )


def _json_rpc_error(rpc_id: object, code: int, message: str) -> func.HttpResponse:
    body = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }
    http_status = 400 if code in (-32700, -32600, -32602) else 200
    return func.HttpResponse(
        json.dumps(body),
        status_code=http_status,
        headers={**_CORS, "Content-Type": _JSON},
    )
