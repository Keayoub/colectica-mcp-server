# SPDX-License-Identifier: Apache-2.0
"""Batch and bulk operation helpers.

Fan-out multiple API calls in parallel, bulk-tag items from a search, and
export search results as CSV.
"""
from __future__ import annotations

import asyncio
import csv
import io
from typing import Any

from ..client import ColecticaApiClient
from ..config import AuthMode
from ._internal import _colectica_op


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def batch_get_items(
    client: ColecticaApiClient,
    items: list[dict[str, Any]],
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Fetch multiple DDI items in parallel and return aggregated results.

    Each entry in *items* must have ``agency``, ``id``, and ``version`` keys.
    Failures for individual items are captured and reported without aborting
    the entire batch.

    Returns
    -------
    dict with keys:
        ``requested``  – total items requested
        ``succeeded``  – items fetched without error
        ``failed``     – items that raised an error
        ``results``    – list of ``{agency, id, version, item: <body dict>}``
        ``errors``     – list of ``{agency, id, version, error: <message>}``
    """
    async def _fetch_one(spec: dict[str, Any]) -> dict[str, Any]:
        agency  = spec.get("agency", spec.get("AgencyId", ""))
        item_id = spec.get("id", spec.get("Identifier", spec.get("identifier", "")))
        version = spec.get("version", spec.get("Version", 1))
        try:
            result = await client.call_operation(
                _colectica_op("GET", "/api/v1/item/{agency}/{id}/{version}"),
                arguments={"agency": agency, "id": item_id, "version": version},
                auth_mode=auth_mode,
            )
            return {
                "agency":  agency,
                "id":      item_id,
                "version": version,
                "item":    result.get("body"),
                "_error":  None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "agency":  agency,
                "id":      item_id,
                "version": version,
                "item":    None,
                "_error":  str(exc),
            }

    raw_results = await asyncio.gather(*[_fetch_one(it) for it in items])

    results: list[dict[str, Any]] = []
    errors:  list[dict[str, Any]] = []

    for r in raw_results:
        if r["_error"] is None:
            results.append({"agency": r["agency"], "id": r["id"], "version": r["version"], "item": r["item"]})
        else:
            errors.append({"agency": r["agency"], "id": r["id"], "version": r["version"], "error": r["_error"]})

    return {
        "requested": len(items),
        "succeeded": len(results),
        "failed":    len(errors),
        "results":   results,
        "errors":    errors,
    }


async def bulk_tag_by_search(
    client: ColecticaApiClient,
    search_body: dict[str, Any],
    tag: str,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Search for items and apply a tag to every match.

    Runs the supplied search, collects **all** results (auto-paginates up to
    10 000 items), then fires concurrent ``PUT`` tag requests.

    Returns
    -------
    dict with keys:
        ``tag``           – the applied tag string
        ``total_matched`` – how many search results were found
        ``tagged``        – how many tag requests succeeded
        ``errors``        – list of ``{agency, id, version, error}``
    """
    # Collect all pages
    all_results: list[dict[str, Any]] = []
    offset       = 0
    page_size    = search_body.get("MaxResults", 100)
    max_total    = 10_000

    while offset < max_total:
        paged_body = {**search_body, "ResultOffset": offset, "MaxResults": page_size}
        try:
            resp = await client.call_operation(
                _colectica_op("POST", "/api/v1/_query"),
                arguments={"body": paged_body},
                auth_mode=auth_mode,
            )
        except Exception:  # noqa: BLE001
            break
        body  = resp.get("body", {}) or {}
        hits  = body.get("Results", []) or []
        if not hits:
            break
        all_results.extend(hits)
        total = body.get("TotalResults", 0)
        offset += len(hits)
        if offset >= total:
            break

    # Tag all concurrently
    async def _tag_one(r: dict[str, Any]) -> dict[str, Any] | None:
        agency  = r.get("AgencyId", r.get("Agency", ""))
        item_id = r.get("Identifier", "")
        version = r.get("Version", 1)
        try:
            await client.call_operation(
                _colectica_op("PUT", "/api/v1/item/{agency}/{id}/{version}/tag/{tag}"),
                arguments={"agency": agency, "id": item_id, "version": version, "tag": tag},
                auth_mode=auth_mode,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            return {"agency": agency, "id": item_id, "version": version, "error": str(exc)}

    tag_outcomes = await asyncio.gather(*[_tag_one(r) for r in all_results])
    errors = [e for e in tag_outcomes if e is not None]

    return {
        "tag":           tag,
        "total_matched": len(all_results),
        "tagged":        len(all_results) - len(errors),
        "errors":        errors,
    }


async def export_search_to_csv(
    client: ColecticaApiClient,
    search_body: dict[str, Any],
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Run a search and export all results as a CSV string.

    Auto-paginates to collect up to 10 000 results.  Each row contains:
    ``urn``, ``item_type``, ``agency``, ``identifier``, ``version``,
    ``label_en``.

    Returns
    -------
    dict with keys:
        ``csv``        – the CSV string (UTF-8)
        ``total_rows`` – number of data rows (excluding header)
    """
    all_results: list[dict[str, Any]] = []
    offset    = 0
    page_size = search_body.get("MaxResults", 200)
    max_total = 10_000

    while offset < max_total:
        paged_body = {**search_body, "ResultOffset": offset, "MaxResults": page_size}
        try:
            resp = await client.call_operation(
                _colectica_op("POST", "/api/v1/_query"),
                arguments={"body": paged_body},
                auth_mode=auth_mode,
            )
        except Exception:  # noqa: BLE001
            break
        body  = resp.get("body", {}) or {}
        hits  = body.get("Results", []) or []
        if not hits:
            break
        all_results.extend(hits)
        total  = body.get("TotalResults", 0)
        offset += len(hits)
        if offset >= total:
            break

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["urn", "item_type", "agency", "identifier", "version", "label_en"])

    for r in all_results:
        agency  = r.get("AgencyId", r.get("Agency", ""))
        item_id = r.get("Identifier", "")
        version = r.get("Version", 1)
        type_   = r.get("ItemType", r.get("TypeGuid", ""))

        # Build URN if not already present
        urn = r.get("Urn") or r.get("URN") or f"urn:ddi:{agency}:{item_id}:{version}"

        # Label: try Label dict first, then Name
        label_val = r.get("Label") or r.get("label") or {}
        if isinstance(label_val, dict):
            label_en = label_val.get("en-US") or label_val.get("en") or next(iter(label_val.values()), "")
        else:
            label_en = str(label_val)

        writer.writerow([urn, type_, agency, item_id, version, label_en])

    csv_text = output.getvalue()
    return {"csv": csv_text, "total_rows": len(all_results)}
