from __future__ import annotations

import argparse
import os
import re
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import ColecticaApiClient
from .client import ColecticaApiError
from .config import AuthMode, ColecticaConfig

load_dotenv()

mcp = FastMCP(
    name="colectica-mcp",
    instructions=(
        "Use this server to access Colectica Repository REST API via OpenAPI discovery. "
        "Call list_operations first, then call_operation by operationId."
    ),
)


def _resolve_config() -> ColecticaConfig:
    return ColecticaConfig.from_env()


def _resolve_auth_mode(auth_mode: str) -> AuthMode:
    mode = auth_mode.strip().lower()
    if mode not in {"auto", "basic", "bearer", "none"}:
        raise ValueError("auth_mode must be one of: auto, basic, bearer, none.")
    return mode  # type: ignore[return-value]


def _contains_any_term(text: str, terms: list[str]) -> bool:
    normalized = text.lower()
    return any(term in normalized for term in terms)


def _colectica_op(method: str, path: str) -> str:
    normalized_method = re.sub(r"[^A-Za-z0-9]", "_", method.upper())
    normalized_path = re.sub(r"[^A-Za-z0-9]", "_", path)
    normalized_path = re.sub(r"_+", "_", normalized_path).strip("_")
    return f"{normalized_method}_{normalized_path}"


def _derive_operation_category(path: str) -> str:
    normalized = path.strip("/")
    if not normalized:
        return "Root"

    segments = normalized.split("/")
    if len(segments) >= 2 and segments[0].lower() == "api" and segments[1].lower() == "v1":
        segments = segments[2:]

    if not segments:
        return "Root"

    primary = segments[0].strip("{}")
    if primary == "_query":
        return "Query"

    if not primary:
        return "Root"

    return primary[:1].upper() + primary[1:]


async def _call_first_available_operation(
    client: ColecticaApiClient,
    operation_ids: list[str],
    *,
    arguments: dict[str, Any] | None = None,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for operation_id in operation_ids:
        try:
            if arguments is None:
                return await client.call_operation(operation_id, auth_mode=auth_mode)
            return await client.call_operation(operation_id, arguments=arguments, auth_mode=auth_mode)
        except ColecticaApiError as exc:
            # Older specs can expose different operationId naming conventions.
            if "was not found in the OpenAPI document" in str(exc):
                last_error = exc
                continue
            raise

    if last_error is not None:
        raise last_error
    raise ColecticaApiError("No operation identifiers were provided.")


@mcp.tool()
async def health_check(auth_mode: str = "auto") -> dict[str, Any]:
    """Validate connectivity and OpenAPI discovery against the Colectica API."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    resolved_auth_mode = _resolve_auth_mode(auth_mode)
    discovered_path, _ = await client.discover_openapi(auth_mode=resolved_auth_mode)
    return {
        "base_url": cfg.base_url,
        "openapi_document": discovered_path,
        "auth_mode_used": resolved_auth_mode,
    }


@mcp.tool()
async def list_operations(auth_mode: str = "auto") -> list[dict[str, str]]:
    """List available Colectica operations from Swagger/OpenAPI by operationId."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.list_operations(auth_mode=_resolve_auth_mode(auth_mode))


@mcp.tool()
async def find_operations(
    query: str,
    auth_mode: str = "auto",
    limit: int = 50,
) -> dict[str, Any]:
    """
    Find Colectica operations by keyword in operationId/method/path.

    Useful for narrowing to candidate operations before calling `operation_details`
    and `call_operation`.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    terms = [part.strip().lower() for part in query.split() if part.strip()]
    if not terms:
        raise ValueError("query must contain at least one non-whitespace term")

    operations = await list_operations(auth_mode=auth_mode)
    matches: list[dict[str, str]] = []
    for op in operations:
        haystack = " ".join(
            [
                str(op.get("operation_id", "")),
                str(op.get("method", "")),
                str(op.get("path", "")),
            ]
        )
        if _contains_any_term(haystack, terms):
            matches.append(op)

    return {
        "query": query,
        "terms": terms,
        "total_matches": len(matches),
        "returned": min(len(matches), limit),
        "matches": matches[:limit],
    }


@mcp.tool()
async def find_ddi_operations(auth_mode: str = "auto", limit: int = 50) -> dict[str, Any]:
    """
    Find likely DDI-related Colectica operations.

    This applies a DDI-focused keyword set over discovered operationId/method/path
    values and returns likely candidates for import/export and metadata workflows.
    """
    ddi_terms = [
        "ddi",
        "study",
        "variable",
        "questionnaire",
        "instrument",
        "code",
        "category",
        "import",
        "export",
    ]

    operations = await list_operations(auth_mode=auth_mode)
    matches: list[dict[str, str]] = []
    for op in operations:
        haystack = " ".join(
            [
                str(op.get("operation_id", "")),
                str(op.get("method", "")),
                str(op.get("path", "")),
            ]
        )
        if _contains_any_term(haystack, ddi_terms):
            matches.append(op)

    return {
        "keywords": ddi_terms,
        "total_matches": len(matches),
        "returned": min(len(matches), limit),
        "matches": matches[:limit],
        "next_steps": [
            "Run operation_details(operation_id) for each candidate.",
            "Invoke read/search operations first to validate payload shapes.",
            "Execute write/import operations with minimal test payloads.",
        ],
    }


@mcp.tool()
async def call_operation(
    operation_id: str,
    arguments: dict[str, Any] | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """
    Invoke any Colectica operation by OpenAPI operationId.

    Pass operation parameters in `arguments` using parameter names from Swagger.
    For request bodies, pass `arguments.body` as a JSON object.
    """
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        operation_id=operation_id,
        arguments=arguments,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def call_endpoint(
    method: str,
    path: str,
    arguments: dict[str, Any] | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """
    Invoke any Colectica endpoint by HTTP method + OpenAPI path.

    Example: method="POST", path="/api/v1/transaction/commit".
    Path parameters, query parameters, headers, and request body are supplied in `arguments`.
    """
    cleaned_method = method.strip().upper()
    if cleaned_method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        raise ValueError("method must be one of: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS")

    cleaned_path = path.strip()
    if not cleaned_path:
        raise ValueError("path must be a non-empty OpenAPI path")

    if not cleaned_path.startswith("/"):
        cleaned_path = f"/{cleaned_path}"

    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        operation_id=_colectica_op(cleaned_method, cleaned_path),
        arguments=arguments,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def list_operation_categories(auth_mode: str = "auto") -> dict[str, Any]:
    """List discovered Colectica API categories and operation counts (Agency, Item, Query, Transaction, etc.)."""
    operations = await list_operations(auth_mode=auth_mode)
    category_counts: dict[str, int] = {}
    for op in operations:
        category = _derive_operation_category(str(op.get("path", "")))
        category_counts[category] = category_counts.get(category, 0) + 1

    sorted_categories = sorted(
        [{"category": name, "operation_count": count} for name, count in category_counts.items()],
        key=lambda item: item["category"],
    )

    return {
        "total_categories": len(sorted_categories),
        "total_operations": len(operations),
        "categories": sorted_categories,
    }


@mcp.tool()
async def list_operations_by_category(
    category: str,
    auth_mode: str = "auto",
    limit: int = 200,
) -> dict[str, Any]:
    """List operations for one Colectica category (for example: Agency, Comment, Query, Transaction)."""
    normalized_category = category.strip().lower()
    if not normalized_category:
        raise ValueError("category must be a non-empty string")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    operations = await list_operations(auth_mode=auth_mode)
    matches: list[dict[str, str]] = []
    for op in operations:
        op_category = _derive_operation_category(str(op.get("path", "")))
        if op_category.lower() == normalized_category:
            matches.append(op)

    return {
        "category": category,
        "total_matches": len(matches),
        "returned": min(len(matches), limit),
        "matches": matches[:limit],
    }


@mcp.tool()
async def operation_details(operation_id: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get OpenAPI-derived capability details for an operationId (params, body, responses)."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.operation_details(operation_id=operation_id, auth_mode=_resolve_auth_mode(auth_mode))


@mcp.tool()
async def call_operation_paginated(
    operation_id: str,
    arguments: dict[str, Any] | None = None,
    auth_mode: str = "auto",
    max_pages: int = 20,
    items_path: str | None = None,
) -> dict[str, Any]:
    """
    Invoke an operation repeatedly using continuation tokens and aggregate item lists.

    `items_path` can be used to extract arrays from nested body fields, e.g. "data.items".
    """
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation_paginated(
        operation_id=operation_id,
        arguments=arguments,
        auth_mode=_resolve_auth_mode(auth_mode),
        max_pages=max_pages,
        items_path=items_path,
    )


@mcp.tool()
async def get_repository_info(auth_mode: str = "auto") -> dict[str, Any]:
    """Convenience wrapper for operationId `GetRepositoryInfo`."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["GetRepositoryInfo", _colectica_op("GET", "/api/v1/repository/info")],
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item(arguments: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Convenience wrapper for operationId `GetItem`."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        [
            "GetItem",
            _colectica_op("GET", "/api/v1/item/{agency}/{id}/{version}"),
            _colectica_op("GET", "/api/v1/item/{agency}/{id}"),
        ],
        arguments=arguments,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def search(arguments: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Convenience wrapper for operationId `Search`."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["Search", _colectica_op("POST", "/api/v1/_query")],
        arguments=arguments,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def register_item(arguments: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Convenience wrapper for operationId `RegisterItem`."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["RegisterItem", _colectica_op("POST", "/api/v1/item")],
        arguments=arguments,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_by_urn(urn: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Fetch a repository item by URN using operationId `GetItem`."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        [
            "GetItem",
            _colectica_op("GET", "/api/v1/item/{agency}/{id}/{version}"),
            _colectica_op("GET", "/api/v1/item/{agency}/{id}"),
        ],
        arguments={"urn": urn},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def register_item_body(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Register a repository item using operationId `RegisterItem` with a typed body argument."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["RegisterItem", _colectica_op("POST", "/api/v1/item")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_ddi_fragment(
    agency: str,
    identifier: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Get DDI XML fragment for one item using /api/v1/ddi paths."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    path = "/api/v1/ddi/{agency}/{identifier}/{version}" if version is not None else "/api/v1/ddi/{agency}/{identifier}"
    args: dict[str, Any] = {"agency": agency, "identifier": identifier}
    if version is not None:
        args["version"] = version
    return await client.call_operation(
        _colectica_op("GET", path),
        arguments=args,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_ddi_set_fragment(
    agency: str,
    identifier: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Get DDI XML fragment instance including children using /api/v1/ddiset paths."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    path = "/api/v1/ddiset/{agency}/{identifier}/{version}" if version is not None else "/api/v1/ddiset/{agency}/{identifier}"
    args: dict[str, Any] = {"agency": agency, "identifier": identifier}
    if version is not None:
        args["version"] = version
    return await client.call_operation(
        _colectica_op("GET", path),
        arguments=args,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_json(
    agency: str,
    identifier: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Get one item serialized in JSON using /api/v1/json paths."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    path = "/api/v1/json/{agency}/{identifier}/{version}" if version is not None else "/api/v1/json/{agency}/{identifier}"
    args: dict[str, Any] = {"agency": agency, "identifier": identifier}
    if version is not None:
        args["version"] = version
    return await client.call_operation(
        _colectica_op("GET", path),
        arguments=args,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_json_set(
    agency: str,
    identifier: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Get one item plus children serialized in nested JSON using /api/v1/jsonset paths."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    path = "/api/v1/jsonset/{agency}/{identifier}/{version}" if version is not None else "/api/v1/jsonset/{agency}/{identifier}"
    args: dict[str, Any] = {"agency": agency, "identifier": identifier}
    if version is not None:
        args["version"] = version
    return await client.call_operation(
        _colectica_op("GET", path),
        arguments=args,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_json_set_filtered(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get nested JSON set while filtering excluded/accepted item types via /api/v1/jsonset/filtered."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/jsonset/filtered"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Colectica MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.getenv("COLECTICA_MCP_TRANSPORT", "stdio"),
        help="MCP transport to run.",
    )
    parser.add_argument(
        "--mount-path",
        default=os.getenv("COLECTICA_MCP_MOUNT_PATH"),
        help="Mount path for streamable-http transport (optional).",
    )
    args = parser.parse_args()

    mcp.run(transport=args.transport, mount_path=args.mount_path)


if __name__ == "__main__":
    main()

