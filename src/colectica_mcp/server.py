# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import ColecticaApiClient
from .client import ColecticaApiError
from .config import AuthMode, ColecticaConfig
from .__version__ import __version__ as _SERVER_VERSION

load_dotenv()


def _load_instructions() -> str:
    """Load MCP server instructions from prompt_instructions.md."""
    path = Path(__file__).parent / "prompt_instructions.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (
            "You are an agent connected to a Colectica Repository. "
            "Call list_operations first, then call_operation by operationId."
        )


mcp = FastMCP(
    name="colectica-mcp",
    instructions=_load_instructions(),
    host=os.getenv("COLECTICA_MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("COLECTICA_MCP_PORT", "8000")),
)


def _resolve_config() -> ColecticaConfig:
    load_dotenv(override=True)
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
    try:
        discovered_path, _ = await client.discover_openapi(auth_mode=resolved_auth_mode)
    except ColecticaApiError as exc:
        error_message = str(exc)
        if "Cloudflare challenge page" not in error_message:
            raise
        return {
            "base_url": cfg.base_url,
            "status": "warning",
            "warning": error_message,
            "openapi_document": None,
            "auth_mode_used": resolved_auth_mode,
        }

    return {
        "base_url": cfg.base_url,
        "status": "ok",
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


@mcp.tool()
async def create_transaction(auth_mode: str = "auto") -> dict[str, Any]:
    """Create a new repository transaction."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["CreateTransaction", _colectica_op("POST", "/api/v1/transaction")],
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_transactions(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get transaction metadata by ids."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["GetTransactions", _colectica_op("POST", "/api/v1/transaction/_getTransactions")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def list_transactions(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """List transaction metadata with list options."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["ListTransactions", _colectica_op("POST", "/api/v1/transaction/_listTransactions")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def commit_transaction(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Commit and register items in a transaction."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["CommitTransaction", _colectica_op("POST", "/api/v1/transaction/_commitTransaction")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def cancel_transaction(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Cancel a repository transaction."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["CancelTransaction", _colectica_op("POST", "/api/v1/transaction/_cancelTransaction")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def add_items_to_transaction(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Add items to a repository transaction."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["AddItemsToTransaction", _colectica_op("POST", "/api/v1/transaction/_addItemsToTransaction")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_items_in_transaction(transaction_id: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get all items currently associated with a transaction."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["GetItemsInTransaction", _colectica_op("POST", "/api/v1/transaction/_getItemsInTransaction")],
        arguments={"transactionId": transaction_id},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_tags(agency: str, id: str, version: int, auth_mode: str = "auto") -> dict[str, Any]:
    """Get tags applied to an item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["GetTags", _colectica_op("GET", "/api/v1/item/{agency}/{id}/{version}/tag")],
        arguments={"agency": agency, "id": id, "version": version},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def add_tag(agency: str, id: str, version: int, tag: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Apply a tag to an item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["AddTag", _colectica_op("PUT", "/api/v1/item/{agency}/{id}/{version}/tag/{tag}")],
        arguments={"agency": agency, "id": id, "version": version, "tag": tag},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def remove_tag(
    agency: str,
    id: str,
    version: int,
    tag: str,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Remove a tag from an item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["RemoveTag", _colectica_op("DELETE", "/api/v1/item/{agency}/{id}/{version}/tag/{tag}")],
        arguments={"agency": agency, "id": id, "version": version, "tag": tag},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_ratings(agency: str, id: str, version: int, auth_mode: str = "auto") -> dict[str, Any]:
    """Get ratings for an item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["GetRatings", _colectica_op("GET", "/api/v1/item/{agency}/{id}/{version}/rating")],
        arguments={"agency": agency, "id": id, "version": version},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def add_rating(
    agency: str,
    id: str,
    version: int,
    rating: Any,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Add a rating to an item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["AddRating", _colectica_op("POST", "/api/v1/item/{agency}/{id}/{version}/rating")],
        arguments={"agency": agency, "id": id, "version": version, "body": rating},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def search_advanced(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Search repository with advanced search options."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["SearchAdvanced", _colectica_op("POST", "/api/v1/_query/advanced")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def search_set(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Search within a typed set."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["SearchSet", _colectica_op("POST", "/api/v1/_query/set")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_repository_statistics(auth_mode: str = "auto") -> dict[str, Any]:
    """Get repository statistics."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["GetRepositoryStatistics", _colectica_op("GET", "/api/v1/repository/statistics")],
        auth_mode=_resolve_auth_mode(auth_mode),
    )


# ---------------------------------------------------------------------------
# Batch 1 — Item lifecycle, versions, history, and comments
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_item_versions(agency: str, id: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get a list of all versions of the specified item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/item/{agency}/{id}/versions"),
        arguments={"agency": agency, "id": id},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_latest_version(agency: str, id: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get the latest version number of a repository item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/item/{agency}/{id}/versions/_latest"),
        arguments={"agency": agency, "id": id},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_latest_version_by_tag(agency: str, id: str, tag: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get the latest version number of an item that has the specified tag."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/item/{agency}/{id}/{tag}/versions/_latest"),
        arguments={"agency": agency, "id": id, "tag": tag},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_description(agency: str, id: str, version: int, auth_mode: str = "auto") -> dict[str, Any]:
    """Get identification, naming, and summary information for a single item version."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/item/{agency}/{id}/{version}/description"),
        arguments={"agency": agency, "id": id, "version": version},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_history(agency: str, id: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get the version history of an item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/item/{agency}/{id}/history"),
        arguments={"agency": agency, "id": id},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_comments(agency: str, id: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get the comments for the specified item."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/item/{agency}/{id}/comment"),
        arguments={"agency": agency, "id": id},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def add_item_comment(
    agency: str, id: str, version: int, body: dict[str, Any], auth_mode: str = "auto"
) -> dict[str, Any]:
    """Add a comment to the specified item version."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/{agency}/{id}/{version}/comment"),
        arguments={"agency": agency, "id": id, "version": version, "body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def delete_items(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Delete items from the repository (requires ColecticaAdministrator)."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_delete"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_descriptions(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get descriptions of multiple repository items (identification and summary, not full content)."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_getDescriptions"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_latest_version_numbers(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get the latest version numbers of multiple items."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_getLatestVersionNumbers"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_items_list(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get multiple items from the repository."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_getList"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_items_list_latest(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get a list of the latest versions of items from the repository."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_getListLatest"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def update_item_state(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Update the deprecated state of a set of items (requires ColecticaAdministrator)."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_updateState"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_comment_list(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get multiple comments from the repository."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_getCommentList"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


# ---------------------------------------------------------------------------
# Batch 2 — Relationship queries
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_relationships_by_subject(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get items referenced by the specified item according to the provided search options."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/_query/relationship/bysubject"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def search_relationships_by_subject_descriptions(
    body: dict[str, Any], auth_mode: str = "auto"
) -> dict[str, Any]:
    """Get item descriptions for items referenced by the target item in the search facet."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/_query/relationship/bysubject/descriptions"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def search_relationships_by_object(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get items that reference the specified item according to the provided search options."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/_query/relationship/byobject"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def search_relationships_by_object_descriptions(
    body: dict[str, Any], auth_mode: str = "auto"
) -> dict[str, Any]:
    """Get item descriptions for items that reference the target item in the search facet."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/_query/relationship/byobject/descriptions"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_relationship_matrix(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get a matrix of all items in a set and the relationships among those items."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/_query/relationship/matrix"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_relationship_matrix_typed(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get a typed matrix of all items in a set and the relationships among those items."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/_query/relationship/matrix/typed"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


# ---------------------------------------------------------------------------
# Batch 3 — Settings, agency, events, permissions, item sets, and tokens
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_settings(auth_mode: str = "auto") -> dict[str, Any]:
    """Get all repository settings."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/setting"),
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_setting(setting: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Get the repository setting with the specified name."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/setting/{setting}"),
        arguments={"setting": setting},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def set_setting(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Add or update a repository setting."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/setting"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def delete_setting(setting: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Remove the repository setting with the specified name."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("DELETE", "/api/v1/setting/{setting}"),
        arguments={"setting": setting},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def create_agency(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Mark the repository as authoritative for the specified agency."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/agency"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def delete_agency(agency: str, auth_mode: str = "auto") -> dict[str, Any]:
    """Mark the repository as no longer authoritative for the specified agency."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("DELETE", "/api/v1/agency/{agency}"),
        arguments={"agency": agency},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def publish_event(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Store information about an event in the repository."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/event"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def add_permissions(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Add the specified permissions to the repository."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/permission"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def delete_permissions(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Remove the specified permissions from the repository."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/permission/_delete"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_permissions(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get all permissions that apply to the specified items and item types."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/permission/_get"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_set(
    agency: str, id: str, version: int | None = None, auth_mode: str = "auto"
) -> dict[str, Any]:
    """Get the set of items under the specified root with the latest version of each item.

    Optionally pass ``version`` as a query parameter to pin the root item version.
    """
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    args: dict[str, Any] = {"agency": agency, "id": id}
    if version is not None:
        args["version"] = version
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/set/{agency}/{id}"),
        arguments=args,
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_set_versioned(agency: str, id: str, version: int, auth_mode: str = "auto") -> dict[str, Any]:
    """Get the set of all items under the specified root at the given version."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/set/{agency}/{id}/{version}"),
        arguments={"agency": agency, "id": id, "version": version},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_set_typed(agency: str, id: str, version: int, auth_mode: str = "auto") -> dict[str, Any]:
    """Get the typed set of all items under the specified root (identifiers include item type)."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/set/{agency}/{id}/{version}/typed"),
        arguments={"agency": agency, "id": id, "version": version},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def create_token(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Create a Colectica authentication token."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/token/CreateToken"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def create_windows_token(auth_mode: str = "auto") -> dict[str, Any]:
    """Create a Colectica authentication token using Windows credentials."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/token/CreateWindowsToken"),
        auth_mode=_resolve_auth_mode(auth_mode),
    )


# ---------------------------------------------------------------------------
# Batch 4 — Replication
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_replication_targets(auth_mode: str = "auto") -> dict[str, Any]:
    """Get the list of replication targets configured for this repository."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("GET", "/api/v1/replication/targets"),
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def create_replication(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Initiate a replication operation."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/replication"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_replication_allowed_initial_states(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get the allowed initial states for a replication operation."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/replication/allowed-initial-states"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_replication_allowed_transitions(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Get the allowed state transitions for a replication operation."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/replication/allowed-state-transitions"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def request_replication_state_change(body: dict[str, Any], auth_mode: str = "auto") -> dict[str, Any]:
    """Request a state change for a replication operation."""
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await client.call_operation(
        _colectica_op("POST", "/api/v1/replication/request-state-change"),
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


# ---------------------------------------------------------------------------
# Batch 5 — Convenience / composite tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def server_info(auth_mode: str = "auto") -> dict[str, Any]:
    """Return MCP server version, configuration summary, and live connectivity status.

    Useful as a first call to orient an LLM: confirms the server is reachable and
    shows which base URL, transport, and auth mode are active.
    """
    cfg = _resolve_config()
    resolved_auth_mode = _resolve_auth_mode(auth_mode)

    client = ColecticaApiClient(cfg)
    connectivity: dict[str, Any] = {"status": "unknown"}
    try:
        discovered_path, _ = await client.discover_openapi(auth_mode=resolved_auth_mode)
        connectivity = {"status": "ok", "openapi_document": discovered_path}
    except ColecticaApiError as exc:
        connectivity = {"status": "error", "detail": str(exc)}

    return {
        "server_version": _SERVER_VERSION,
        "base_url": cfg.base_url,
        "transport": cfg.transport,
        "auth_mode_resolved": resolved_auth_mode,
        "connectivity": connectivity,
    }


@mcp.tool()
async def search_by_text(
    query: str,
    item_types: list[str] | None = None,
    max_results: int = 20,
    agency_ids: list[str] | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Search Colectica repository items by plain-text query.

    A convenience wrapper that builds the search request body automatically.
    Use ``item_types`` to filter by DDI item-type URNs (e.g.
    ``["urn:ddi:controlled_vocabulary:variable:1"]``).
    Use ``agency_ids`` to restrict results to specific agencies.
    Returns raw search results from the repository.
    """
    if not query.strip():
        raise ValueError("query must be a non-empty string")
    if max_results < 1 or max_results > 1000:
        raise ValueError("max_results must be between 1 and 1000")

    body: dict[str, Any] = {
        "SearchTerms": query.strip(),
        "MaxResults": max_results,
    }
    if item_types:
        body["ItemTypes"] = item_types
    if agency_ids:
        body["AgencyIds"] = agency_ids

    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _call_first_available_operation(
        client,
        ["Search", _colectica_op("POST", "/api/v1/_query")],
        arguments={"body": body},
        auth_mode=_resolve_auth_mode(auth_mode),
    )


@mcp.tool()
async def get_item_summary(
    agency: str,
    id: str,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Fetch history and latest version number for an item in a single call.

    Combines ``get_item_history`` and ``get_item_latest_version`` using
    concurrent requests, reducing round trips for the LLM.
    Returns a merged dict with ``latest_version`` and ``history`` keys.
    """
    cfg = _resolve_config()
    resolved_auth_mode = _resolve_auth_mode(auth_mode)

    async def _history() -> dict[str, Any]:
        c = ColecticaApiClient(cfg)
        return await c.call_operation(
            _colectica_op("GET", "/api/v1/item/{agency}/{id}/history"),
            arguments={"agency": agency, "id": id},
            auth_mode=resolved_auth_mode,
        )

    async def _latest() -> dict[str, Any]:
        c = ColecticaApiClient(cfg)
        return await c.call_operation(
            _colectica_op("GET", "/api/v1/item/{agency}/{id}/versions/_latest"),
            arguments={"agency": agency, "id": id},
            auth_mode=resolved_auth_mode,
        )

    history_result, latest_result = await asyncio.gather(_history(), _latest())

    return {
        "agency": agency,
        "id": id,
        "latest_version": latest_result.get("body"),
        "history": history_result.get("body"),
    }


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

