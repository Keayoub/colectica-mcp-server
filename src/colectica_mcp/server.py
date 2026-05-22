# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import asyncio
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .client import ColecticaApiClient
from .client import ColecticaApiError
from .config import AuthMode, ColecticaConfig
from .__version__ import __version__ as _SERVER_VERSION

# ---------------------------------------------------------------------------
# Utils sub-package imports
# ---------------------------------------------------------------------------
from .utils._internal import (
    _build_item_type_guid_map,
    _colectica_op,
    _get_item_type_guid_map,
    _resolve_item_types,
    _UUID_RE,
)
from .utils import (
    batch as _batch,
    composite as _composite,
    ddi_parser as _ddi_parser,
    harmonization as _harmonization,
    importer as _importer,
    quality as _quality,
    search_helpers as _search_helpers,
)

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
    """Convenience wrapper for operationId `Search`.

    Accepts friendly DDI type names (e.g. ``"Variable"``, ``"QuestionItem"``)
    in ``arguments["body"]["ItemTypes"]`` and resolves them to the UUIDs
    required by the Colectica API automatically.

    Note: ``arguments["body"]["SearchTerms"]`` must be a list of strings,
    e.g. ``["age"]``, not a plain string. A bare string is coerced automatically.
    """
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    resolved_auth_mode = _resolve_auth_mode(auth_mode)
    body = arguments.get("body", {})
    if isinstance(body, dict):
        # Coerce SearchTerms string → list as required by the Colectica API
        if isinstance(body.get("SearchTerms"), str):
            body["SearchTerms"] = [body["SearchTerms"]]
        if body.get("ItemTypes"):
            body["ItemTypes"] = await _resolve_item_types(body["ItemTypes"], client)
        arguments = {**arguments, "body": body}
    return await _call_first_available_operation(
        client,
        ["Search", _colectica_op("POST", "/api/v1/_query")],
        arguments=arguments,
        auth_mode=resolved_auth_mode,
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
    """Search repository with advanced search options.

    Accepts friendly DDI type names (e.g. ``"Variable"``, ``"QuestionItem"``)
    in ``body["ItemTypes"]`` and resolves them to the UUIDs required by the
    Colectica API automatically.
    """
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    resolved_auth_mode = _resolve_auth_mode(auth_mode)
    if body.get("ItemTypes"):
        body = {**body, "ItemTypes": await _resolve_item_types(body["ItemTypes"], client)}
    return await _call_first_available_operation(
        client,
        ["SearchAdvanced", _colectica_op("POST", "/api/v1/_query/advanced")],
        arguments={"body": body},
        auth_mode=resolved_auth_mode,
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


@mcp.tool()
async def get_item_types(auth_mode: str = "auto") -> dict[str, Any]:
    """Return all DDI item types available in this Colectica repository.

    Queries the live API to discover item types and maps each friendly DDI
    type name (e.g. ``"Variable"``, ``"QuestionItem"``) to its UUID.  The
    result is cached for the lifetime of the server process.

    Use the returned names directly in the ``item_types`` / ``ItemTypes``
    parameter of ``search``, ``search_advanced``, and ``search_by_text``
    — the search tools resolve them to UUIDs automatically.
    """
    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    _ = _resolve_auth_mode(auth_mode)
    guid_map = await _get_item_type_guid_map(client)
    # Also attach counts from statistics for convenience
    stats = await client.call_operation(
        _colectica_op("GET", "/api/v1/repository/statistics"), arguments={}
    )
    counts: dict[str, int] = stats.get("body", {}).get("ItemCounts", {})
    # Invert guid_map to guid→name for the count lookup
    guid_to_name = {v: k for k, v in guid_map.items()}
    return {
        "item_types": [
            {
                "name": guid_to_name.get(guid, "(unknown)"),
                "guid": guid,
                "count": count,
            }
            for guid, count in sorted(counts.items(), key=lambda x: -x[1])
        ],
        "total_types": len(counts),
        "note": (
            "Pass 'name' values directly to item_types / ItemTypes in search tools; "
            "they are resolved to GUIDs automatically."
        ),
    }


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
        "SearchTerms": [query.strip()],
        "MaxResults": max_results,
    }
    if agency_ids:
        body["AgencyIds"] = agency_ids

    cfg = _resolve_config()
    client = ColecticaApiClient(cfg)
    resolved_auth_mode = _resolve_auth_mode(auth_mode)
    if item_types:
        body["ItemTypes"] = await _resolve_item_types(item_types, client)
    return await _call_first_available_operation(
        client,
        ["Search", _colectica_op("POST", "/api/v1/_query")],
        arguments={"body": body},
        auth_mode=resolved_auth_mode,
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


# ===========================================================================
# Advanced utility tools (Batch 6 — implemented in utils/ sub-package)
# ===========================================================================

# ---------------------------------------------------------------------------
# DDI Parser tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def parse_ddi_item(xml_text: str) -> dict[str, Any]:
    """Parse a raw DDI 3.x Fragment XML string into a structured JSON dict.

    Extracts type name, URN, agency, id, version, multilingual labels,
    descriptions, names, and all *Reference child elements.  No network call
    is made — all parsing is client-side.

    Parameters
    ----------
    xml_text:
        Raw DDI Fragment XML as returned by ``get_ddi_fragment``.
    """
    return _ddi_parser.parse_ddi_item(xml_text)


@mcp.tool()
async def extract_variable_stats(xml_text: str) -> dict[str, Any]:
    """Parse a VariableStatistics DDI fragment into a structured statistics dict.

    Extracts the variable reference, total responses, summary statistics
    (min, max, mean, etc.) and per-category frequency counts.

    Parameters
    ----------
    xml_text:
        Raw DDI Fragment XML for a VariableStatistics item.
    """
    return _ddi_parser.extract_variable_stats(xml_text)


@mcp.tool()
async def get_multilingual_labels(xml_text: str) -> dict[str, Any]:
    """Extract all multilingual label, description, and name variants from a DDI XML string.

    Useful for translation gap analysis — returns every ``xml:lang`` variant
    found in the fragment along with a sorted list of all encountered language
    codes.

    Parameters
    ----------
    xml_text:
        Raw DDI Fragment XML string.
    """
    return _ddi_parser.get_multilingual_labels(xml_text)


@mcp.tool()
async def validate_ddi_fragment(xml_text: str) -> dict[str, Any]:
    """Validate a DDI Fragment XML string for structural correctness.

    Checks that the XML is well-formed, has a ``Fragment`` root element,
    contains exactly one typed child element, and that child has the required
    ``r:URN``, ``r:Agency``, ``r:ID``, and ``r:Version`` elements.

    Parameters
    ----------
    xml_text:
        DDI Fragment XML string to validate.
    """
    return _ddi_parser.validate_ddi_fragment(xml_text)


# ---------------------------------------------------------------------------
# Composite navigation tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_study_outline(
    agency: str,
    id: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Return a hierarchical type-grouped outline of all items in a study set.

    Fetches the full typed item set for the given identifier, groups children
    by DDI type (Variable, QuestionItem, DataCollection, etc.), and resolves
    human-readable labels for each item.

    Parameters
    ----------
    agency:
        Agency identifier of the root item (e.g. StudyUnit).
    id:
        GUID of the root item.
    version:
        Version number.  Defaults to 1 if omitted.
    auth_mode:
        Authentication mode: ``"auto"``, ``"basic"``, ``"bearer"``, ``"none"``.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _composite.get_study_outline(client, agency, id, version, _resolve_auth_mode(auth_mode))


@mcp.tool()
async def get_codebook_for_variable(
    agency: str,
    id: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Retrieve a Variable together with its full codebook (codes and categories).

    Fetches the variable DDI, locates its CategoryScheme or CodeList reference,
    then fetches that scheme and returns the complete list of codes with labels.

    Parameters
    ----------
    agency:
        Agency identifier of the Variable.
    id:
        GUID of the Variable item.
    version:
        Version number.  Defaults to 1 if omitted.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _composite.get_codebook_for_variable(client, agency, id, version, _resolve_auth_mode(auth_mode))


@mcp.tool()
async def get_question_with_responses(
    agency: str,
    id: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Retrieve a QuestionItem with its question text and full response domain.

    Parses the DDI fragment to extract all language variants of the question
    text and identifies the response domain type (CodeDomain, TextDomain,
    NumericDomain).  For CodeDomain questions the associated codes are fetched.

    Parameters
    ----------
    agency:
        Agency identifier of the QuestionItem.
    id:
        GUID of the QuestionItem.
    version:
        Version number.  Defaults to 1 if omitted.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _composite.get_question_with_responses(client, agency, id, version, _resolve_auth_mode(auth_mode))


@mcp.tool()
async def find_variables_by_concept(
    concept_agency: str,
    concept_id: str,
    concept_version: int = 1,
    max_results: int = 50,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Find all Variable items that reference a given Concept.

    Uses the relationship-by-object endpoint to locate every item pointing to
    the specified concept, then filters the results to Variable type only.

    Parameters
    ----------
    concept_agency:
        Agency of the Concept item.
    concept_id:
        GUID of the Concept.
    concept_version:
        Version of the Concept (default 1).
    max_results:
        Maximum number of Variables to return.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _composite.find_variables_by_concept(
        client, concept_agency, concept_id, concept_version, max_results,
        _resolve_auth_mode(auth_mode),
    )


# ---------------------------------------------------------------------------
# Harmonization tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def compare_item_versions(
    agency: str,
    id: str,
    version1: int,
    version2: int,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Compare two versions of the same DDI item and report what changed.

    Fetches DDI fragments for both versions in parallel, then diffs labels,
    descriptions, names, and references.

    Parameters
    ----------
    agency:
        Agency of the item.
    id:
        GUID of the item.
    version1:
        First (older) version number.
    version2:
        Second (newer) version number.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _harmonization.compare_item_versions(
        client, agency, id, version1, version2, _resolve_auth_mode(auth_mode)
    )


@mcp.tool()
async def find_harmonizable_variables(
    agency: str,
    id: str,
    version: int | None = None,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Find Variables that share the same Concept or CategoryScheme as the given variable.

    Useful for discovering cross-study harmonization candidates.  Fetches the
    target variable, extracts its concept and category-scheme references, then
    queries for other Variables pointing to the same items.

    Parameters
    ----------
    agency:
        Agency of the source Variable.
    id:
        GUID of the source Variable.
    version:
        Version number.  Defaults to 1 if omitted.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _harmonization.find_harmonizable_variables(
        client, agency, id, version, _resolve_auth_mode(auth_mode)
    )


@mcp.tool()
async def get_concept_usage(
    concept_agency: str,
    concept_id: str,
    concept_version: int = 1,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Report all DDI items that reference a given Concept, grouped by type.

    Useful for impact analysis before modifying a shared concept.  Returns a
    breakdown by item type (Variable, QuestionItem, etc.) and the full list of
    referencing identifiers.

    Parameters
    ----------
    concept_agency:
        Agency of the Concept.
    concept_id:
        GUID of the Concept.
    concept_version:
        Version of the Concept (default 1).
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _harmonization.get_concept_usage(
        client, concept_agency, concept_id, concept_version, _resolve_auth_mode(auth_mode)
    )


# ---------------------------------------------------------------------------
# Batch tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def batch_get_items(
    items: list[dict[str, Any]],
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Fetch multiple DDI items in parallel and return aggregated results.

    Fires concurrent GET requests for all supplied items and reports successes
    and failures separately.

    Parameters
    ----------
    items:
        List of ``{"agency": "...", "id": "...", "version": 1}`` dicts.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _batch.batch_get_items(client, items, _resolve_auth_mode(auth_mode))


@mcp.tool()
async def bulk_tag_by_search(
    search_body: dict[str, Any],
    tag: str,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Run a search and apply a tag to every matching item.

    Auto-paginates through all search results (up to 10 000) and fires
    concurrent tag PUT requests.

    Parameters
    ----------
    search_body:
        Standard ``SearchRequest`` body dict (same as ``search``).
    tag:
        Tag string to apply to every matched item.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _batch.bulk_tag_by_search(client, search_body, tag, _resolve_auth_mode(auth_mode))


@mcp.tool()
async def export_search_to_csv(
    search_body: dict[str, Any],
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Run a search and export all results as a CSV string.

    Auto-paginates to collect up to 10 000 results.  Each CSV row contains:
    ``urn``, ``item_type``, ``agency``, ``identifier``, ``version``,
    ``label_en``.

    Parameters
    ----------
    search_body:
        Standard ``SearchRequest`` body dict (same as ``search``).
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _batch.export_search_to_csv(client, search_body, _resolve_auth_mode(auth_mode))


# ---------------------------------------------------------------------------
# Quality / audit tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def audit_item_completeness(
    items: list[dict[str, Any]],
    language: str = "en-US",
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Audit a list of DDI items for metadata completeness.

    For each item fetches its DDI fragment and checks: label present in the
    requested language, description present, and (for Variables) Concept and
    CategoryScheme references exist.

    Parameters
    ----------
    items:
        List of ``{"agency": "...", "id": "...", "version": 1}`` dicts.
    language:
        BCP-47 language tag to check (e.g. ``"en-US"``).  Pass ``""`` to
        accept any language.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _quality.audit_item_completeness(
        client, items, language, _resolve_auth_mode(auth_mode)
    )


@mcp.tool()
async def find_items_without_label(
    item_type: str,
    agency: str = "",
    language: str = "en-US",
    max_results: int = 200,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Search for items of a given type that are missing a label in a specific language.

    Runs a type-filtered search and inspects each result's inline label dict
    to identify items lacking the requested language.

    Parameters
    ----------
    item_type:
        DDI type name (e.g. ``"Variable"``) or GUID.
    agency:
        Agency to restrict results.  Pass ``""`` for all agencies.
    language:
        BCP-47 language code to check (e.g. ``"en-US"``).
    max_results:
        Maximum items to scan (up to 1 000 per call).
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _quality.find_items_without_label(
        client, item_type, agency, language, max_results, _resolve_auth_mode(auth_mode)
    )


# ---------------------------------------------------------------------------
# Importer tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def create_variable_from_dict(
    variable_data: dict[str, Any],
    agency: str,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Create a new DDI 3.3 Variable item in the repository.

    Builds a minimal DDI 3.3 XML fragment and registers it via the transaction
    API (create → add → commit).

    Parameters
    ----------
    variable_data:
        Dict containing:
        ``name`` (required), ``label``, ``description``, ``concept_guid``,
        ``language`` (default ``"en-US"``), ``version`` (default 1).
    agency:
        Target Colectica agency identifier.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _importer.create_variable_from_dict(
        client, variable_data, agency, _resolve_auth_mode(auth_mode)
    )


@mcp.tool()
async def create_question_item(
    question_data: dict[str, Any],
    agency: str,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Create a new DDI 3.3 QuestionItem in the repository.

    Builds a minimal DDI 3.3 XML fragment and registers it via the transaction
    API.

    Parameters
    ----------
    question_data:
        Dict containing:
        ``question_text`` (required), ``label``, ``description``,
        ``response_type`` (``"text"`` or ``"numeric"``, default ``"text"``),
        ``language`` (default ``"en-US"``), ``version`` (default 1).
    agency:
        Target Colectica agency identifier.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _importer.create_question_item(
        client, question_data, agency, _resolve_auth_mode(auth_mode)
    )


@mcp.tool()
async def import_variables_from_csv_text(
    csv_text: str,
    agency: str,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Bulk-import Variables from a CSV string in a single atomic transaction.

    Expected CSV columns (header row required):
    ``name``, ``label``, ``description`` (optional), ``concept_guid``
    (optional), ``language`` (optional, defaults to ``"en-US"``).

    All rows are submitted in one transaction — if it fails nothing is
    committed.

    Parameters
    ----------
    csv_text:
        Full CSV content as a string, including a header row.
    agency:
        Target Colectica agency identifier.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _importer.import_variables_from_csv_text(
        client, csv_text, agency, _resolve_auth_mode(auth_mode)
    )


# ---------------------------------------------------------------------------
# Search-helpers tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search_with_text_facets(
    item_types: list[str],
    text_facets: list[dict[str, Any]],
    max_results: int = 100,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Search with structured text-facet filters using the advanced search endpoint.

    Parameters
    ----------
    item_types:
        DDI type names or GUIDs to restrict results.  Pass ``[]`` for all types.
    text_facets:
        List of facet dicts.  Each should have:
        ``property_name`` (e.g. ``"dcTitle"``), ``terms`` (list of strings),
        ``exact_match`` (bool, default ``false``).
    max_results:
        Maximum results per call.
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _search_helpers.search_with_text_facets(
        client, item_types, text_facets, max_results, _resolve_auth_mode(auth_mode)
    )


@mcp.tool()
async def search_all_pages(
    search_body: dict[str, Any],
    max_total: int = 1000,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Execute a paginated search and collect all results up to *max_total*.

    Transparently pages through ``POST /api/v1/_query`` results by bumping
    ``ResultOffset`` each iteration.

    Parameters
    ----------
    search_body:
        Any valid ``SearchRequest`` body dict.  ``ResultOffset`` and
        ``MaxResults`` are managed automatically.
    max_total:
        Safety ceiling on total items collected (max 50 000).
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _search_helpers.search_all_pages(
        client, search_body, max_total, _resolve_auth_mode(auth_mode)
    )


@mcp.tool()
async def search_by_urn_prefix(
    urn_prefix: str,
    agency: str = "",
    max_results: int = 100,
    auth_mode: str = "auto",
) -> dict[str, Any]:
    """Search for items whose URN begins with a given prefix.

    Uses a ``SearchTerms`` query with the prefix value, then filters results
    client-side to items whose full URN starts with *urn_prefix*.

    Parameters
    ----------
    urn_prefix:
        URN prefix string, e.g. ``"urn:ddi:int.colectica:"``.
    agency:
        Agency to filter results.  Pass ``""`` for all agencies.
    max_results:
        Maximum results to scan (up to 1 000).
    auth_mode:
        Authentication mode.
    """
    cfg    = _resolve_config()
    client = ColecticaApiClient(cfg)
    return await _search_helpers.search_by_urn_prefix(
        client, urn_prefix, agency, max_results, _resolve_auth_mode(auth_mode)
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

