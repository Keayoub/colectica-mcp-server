# SPDX-License-Identifier: Apache-2.0
"""Advanced search convenience wrappers.

Provides text-facet filtering, transparent pagination, and URN-prefix search
on top of the standard Colectica search API.
"""
from __future__ import annotations

from typing import Any

from ..client import ColecticaApiClient
from ..config import AuthMode
from ._internal import _colectica_op, _resolve_item_types


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_with_text_facets(
    client: ColecticaApiClient,
    item_types: list[str],
    text_facets: list[dict[str, Any]],
    max_results: int,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Search with structured text-facet filters using the advanced search endpoint.

    Parameters
    ----------
    item_types:
        List of DDI type names or GUIDs to restrict results.  Pass ``[]`` for
        all types.
    text_facets:
        List of facet dicts.  Each dict should contain:

        * ``property_name``  – Colectica metadata field to search (e.g.
          ``"dcTitle"``, ``"description"``, ``"keyword"``)
        * ``terms``          – list of strings to match
        * ``exact_match``    – bool (default ``False``)
    max_results:
        Maximum results to return from this single call.

    Returns
    -------
    dict with keys:
        ``total_results`` – ``TotalResults`` from the API
        ``returned``      – number of results in this response
        ``results``       – list of search result dicts
    """
    resolved_types = await _resolve_item_types(item_types, client) if item_types else []

    # Build the AdvancedSearchRequest body
    body: dict[str, Any] = {"MaxResults": max_results}
    if resolved_types:
        body["ItemTypes"] = resolved_types

    facet_list = []
    for f in text_facets:
        facet_list.append({
            "PropertyName": f.get("property_name", f.get("PropertyName", "")),
            "Terms":        f.get("terms", f.get("Terms", [])),
            "ExactMatch":   f.get("exact_match", f.get("ExactMatch", False)),
        })
    if facet_list:
        body["TextFacets"] = facet_list

    resp = await client.call_operation(
        _colectica_op("POST", "/api/v1/query/_advanced"),
        arguments={"body": body},
        auth_mode=auth_mode,
    )
    resp_body   = resp.get("body", {}) or {}
    results     = resp_body.get("Results", []) or []

    return {
        "total_results": resp_body.get("TotalResults", len(results)),
        "returned":      len(results),
        "results":       results,
    }


async def search_all_pages(
    client: ColecticaApiClient,
    search_body: dict[str, Any],
    max_total: int,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Execute a paginated search and collect all results up to *max_total*.

    Repeatedly calls the standard ``POST /api/v1/_query`` endpoint, bumping
    ``ResultOffset`` each iteration until ``TotalResults`` is exhausted or
    *max_total* items have been collected.

    Parameters
    ----------
    search_body:
        Any valid ``SearchRequest`` body dict.  ``ResultOffset`` and
        ``MaxResults`` will be managed automatically.
    max_total:
        Safety ceiling — stop after collecting this many results regardless of
        ``TotalResults``.  Maximum 50 000.

    Returns
    -------
    dict with keys:
        ``total_available`` – ``TotalResults`` reported by the first API call
        ``total_fetched``   – actual number of results collected
        ``pages_fetched``   – number of API calls made
        ``results``         – aggregated list of all result dicts
    """
    max_total  = min(max_total, 50_000)
    page_size  = min(search_body.get("MaxResults", 200), 1000)
    offset     = 0
    pages      = 0
    total_api  = 0
    all_hits:  list[dict[str, Any]] = []

    while len(all_hits) < max_total:
        paged_body = {**search_body, "ResultOffset": offset, "MaxResults": page_size}
        resp       = await client.call_operation(
            _colectica_op("POST", "/api/v1/_query"),
            arguments={"body": paged_body},
            auth_mode=auth_mode,
        )
        body  = resp.get("body", {}) or {}
        hits  = body.get("Results", []) or []
        pages += 1

        if pages == 1:
            total_api = body.get("TotalResults", 0)

        if not hits:
            break

        all_hits.extend(hits)
        offset += len(hits)

        if offset >= total_api:
            break

    return {
        "total_available": total_api,
        "total_fetched":   len(all_hits),
        "pages_fetched":   pages,
        "results":         all_hits,
    }


async def search_by_urn_prefix(
    client: ColecticaApiClient,
    urn_prefix: str,
    agency: str,
    max_results: int,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Search for items whose URN begins with *urn_prefix*.

    The Colectica search API does not expose a native URN prefix filter, so
    this function uses a ``SearchTerms`` query with the prefix and optionally
    further client-side filters on the agency to narrow results.

    Parameters
    ----------
    urn_prefix:
        URN prefix string (e.g. ``"urn:ddi:int.colectica:"``).
    agency:
        Agency identifier to restrict results.  Pass ``""`` to search all.
    max_results:
        Maximum results to scan (up to 1 000).

    Returns
    -------
    dict with keys:
        ``urn_prefix``      – the searched prefix
        ``agency``          – the agency filter applied
        ``total_scanned``   – results inspected
        ``matched_count``   – items whose URN matches the prefix
        ``items``           – list of ``{agency, id, version, urn, item_type}``
    """
    search_body: dict[str, Any] = {
        "SearchTerms": [urn_prefix],
        "MaxResults":  min(max_results, 1000),
    }
    if agency:
        # Most Colectica deployments support filtering by agency in the request
        search_body["SearchFacets"] = [{"Agency": agency}]

    resp = await client.call_operation(
        _colectica_op("POST", "/api/v1/_query"),
        arguments={"body": search_body},
        auth_mode=auth_mode,
    )
    body    = resp.get("body", {}) or {}
    results = body.get("Results", []) or []

    matched: list[dict[str, Any]] = []
    for r in results:
        item_agency = r.get("AgencyId", r.get("Agency", ""))
        if agency and item_agency != agency:
            continue

        item_id  = r.get("Identifier", "")
        version  = r.get("Version", 1)
        urn      = r.get("Urn") or r.get("URN") or f"urn:ddi:{item_agency}:{item_id}:{version}"

        if urn.startswith(urn_prefix):
            matched.append({
                "agency":    item_agency,
                "id":        item_id,
                "version":   version,
                "urn":       urn,
                "item_type": r.get("ItemType", r.get("TypeGuid", "")),
            })

    return {
        "urn_prefix":    urn_prefix,
        "agency":        agency,
        "total_scanned": len(results),
        "matched_count": len(matched),
        "items":         matched,
    }
