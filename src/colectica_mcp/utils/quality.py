# SPDX-License-Identifier: Apache-2.0
"""Metadata quality and audit helpers.

Assess DDI item completeness and find items missing required metadata
in a specific language.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..client import ColecticaApiClient
from ..config import AuthMode
from ._internal import _colectica_op, _resolve_item_types
from .ddi_parser import parse_ddi_item


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_ddi(
    client: ColecticaApiClient,
    agency: str,
    id: str,
    version: int,
    auth_mode: AuthMode,
) -> str:
    result = await client.call_operation(
        _colectica_op("GET", "/api/v1/ddi/{agency}/{identifier}/{version}"),
        arguments={"agency": agency, "identifier": id, "version": version},
        auth_mode=auth_mode,
    )
    return result.get("body", "")


def _check_item_completeness(
    parsed: dict[str, Any],
    language: str,
) -> list[str]:
    """Return a list of completeness issues for a single parsed DDI item."""
    issues: list[str] = []

    labels = parsed.get("labels", {})
    if not labels:
        issues.append("No labels found")
    elif language and language not in labels:
        available = list(labels.keys())
        issues.append(f"Missing label in '{language}' (available: {available})")

    descriptions = parsed.get("descriptions", {})
    if not descriptions:
        issues.append("No description found")
    elif language and language not in descriptions:
        available = list(descriptions.keys())
        issues.append(f"Missing description in '{language}' (available: {available})")

    item_type = parsed.get("type", "")
    if item_type.lower() == "variable":
        refs       = parsed.get("references", [])
        ref_types  = [r.get("type", "").lower() for r in refs]
        has_concept = any("concept" in t for t in ref_types)
        has_cat     = any("categoryscheme" in t or "codelist" in t for t in ref_types)
        if not has_concept:
            issues.append("Variable has no Concept reference")
        if not has_cat:
            issues.append("Variable has no CategoryScheme/CodeList reference")

    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def audit_item_completeness(
    client: ColecticaApiClient,
    items: list[dict[str, Any]],
    language: str,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Audit a list of DDI items for metadata completeness.

    For each item, fetches its DDI fragment and checks:
    * Label present (in the requested language)
    * Description present (in the requested language)
    * Variables: Concept and CategoryScheme references present

    Parameters
    ----------
    items:
        List of ``{agency, id, version}`` dicts to audit.
    language:
        BCP-47 language tag to check for (e.g. ``"en-US"``).  Pass ``""``
        to check for *any* label/description regardless of language.

    Returns
    -------
    dict with keys:
        ``total_audited``  – items inspected
        ``issues_found``   – items with at least one issue
        ``score_percent``  – percentage of items with no issues
        ``language``       – the language checked
        ``report``         – list of ``{agency, id, version, item_type, label, issues}``
    """
    async def _audit_one(spec: dict[str, Any]) -> dict[str, Any]:
        agency  = spec.get("agency",  spec.get("Agency",     ""))
        item_id = spec.get("id",      spec.get("Identifier", spec.get("identifier", "")))
        version = spec.get("version", spec.get("Version",    1))
        try:
            xml    = await _fetch_ddi(client, agency, item_id, version, auth_mode)
            parsed = parse_ddi_item(xml)
            issues = _check_item_completeness(parsed, language)
            labels = parsed.get("labels", {})
            label  = labels.get(language) or next(iter(labels.values()), "") if labels else ""
        except Exception as exc:  # noqa: BLE001
            parsed = {}
            issues = [f"Fetch error: {exc}"]
            label  = ""

        return {
            "agency":    agency,
            "id":        item_id,
            "version":   version,
            "item_type": parsed.get("type", ""),
            "label":     label,
            "issues":    issues,
        }

    report = await asyncio.gather(*[_audit_one(it) for it in items])

    issues_found = sum(1 for r in report if r["issues"])
    total        = len(report)
    score        = round(100 * (total - issues_found) / total, 1) if total else 0.0

    return {
        "total_audited": total,
        "issues_found":  issues_found,
        "score_percent": score,
        "language":      language,
        "report":        list(report),
    }


async def find_items_without_label(
    client: ColecticaApiClient,
    item_type: str,
    agency: str,
    language: str,
    max_results: int,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Search for items of a given type that are missing a label in a specific language.

    Performs a type-filtered search, then inspects each result's label dict
    (returned inline by the search API) to identify items lacking the
    requested language.

    Parameters
    ----------
    item_type:
        DDI type name (e.g. ``"Variable"``) or GUID.
    agency:
        Agency to restrict the search to (pass ``""`` for all agencies).
    language:
        BCP-47 language code (e.g. ``"en-US"``).
    max_results:
        Maximum number of items to scan.

    Returns
    -------
    dict with keys:
        ``item_type``      – the queried type
        ``language``       – the checked language
        ``total_scanned``  – items inspected
        ``missing_count``  – items without the label language
        ``items``          – list of ``{agency, id, version, available_languages}``
    """
    resolved_types = await _resolve_item_types([item_type], client)

    search_body: dict[str, Any] = {
        "ItemTypes":  resolved_types,
        "MaxResults": max_results,
    }
    if agency:
        search_body["SearchTerms"] = []

    resp = await client.call_operation(
        _colectica_op("POST", "/api/v1/_query"),
        arguments={"body": search_body},
        auth_mode=auth_mode,
    )
    results: list[dict[str, Any]] = resp.get("body", {}).get("Results", []) or []

    missing: list[dict[str, Any]] = []
    for r in results:
        item_agency = r.get("AgencyId", r.get("Agency", ""))
        if agency and item_agency != agency:
            continue

        label_val = r.get("Label") or r.get("label") or {}
        if isinstance(label_val, dict):
            available_langs = list(label_val.keys())
            has_lang        = language in label_val and bool(label_val[language])
        else:
            available_langs = []
            has_lang        = bool(label_val)

        if not has_lang:
            missing.append({
                "agency":              item_agency,
                "id":                  r.get("Identifier", ""),
                "version":             r.get("Version", 1),
                "available_languages": available_langs,
            })

    return {
        "item_type":     item_type,
        "language":      language,
        "total_scanned": len(results),
        "missing_count": len(missing),
        "items":         missing,
    }
