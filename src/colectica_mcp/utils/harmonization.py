# SPDX-License-Identifier: Apache-2.0
"""Cross-study harmonization helpers.

These functions help analysts compare DDI items across versions and discover
reuse patterns based on shared concepts or category schemes.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..client import ColecticaApiClient
from ..config import AuthMode
from ._internal import _colectica_op
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


def _diff_lang_map(old: dict[str, str], new: dict[str, str]) -> dict[str, Any]:
    """Produce a diff between two ``{lang: text}`` dicts."""
    changes: dict[str, Any] = {}
    all_langs = set(old) | set(new)
    for lang in sorted(all_langs):
        o = old.get(lang)
        n = new.get(lang)
        if o != n:
            changes[lang] = {"old": o, "new": n}
    return changes


def _diff_references(
    old_refs: list[dict[str, Any]],
    new_refs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (added, removed) reference lists when comparing two versions."""
    def _key(r: dict[str, Any]) -> tuple[str, str, str]:
        return (r.get("type", ""), r.get("agency", ""), r.get("id", ""))

    old_keys = {_key(r): r for r in old_refs}
    new_keys = {_key(r): r for r in new_refs}

    added   = [r for k, r in new_keys.items() if k not in old_keys]
    removed = [r for k, r in old_keys.items() if k not in new_keys]
    return added, removed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compare_item_versions(
    client: ColecticaApiClient,
    agency: str,
    id: str,
    version1: int,
    version2: int,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Compare two versions of the same DDI item and report what changed.

    Fetches DDI fragments for *version1* and *version2* in parallel, then
    diffs labels, descriptions, names, and references.

    Returns
    -------
    dict with keys:
        ``agency`` / ``id`` / ``version1`` / ``version2``
        ``item_type``           – DDI element type (e.g. ``"Variable"``)
        ``label_changes``       – ``{lang: {old, new}}`` for changed labels
        ``description_changes`` – ``{lang: {old, new}}``
        ``name_changes``        – ``{lang: {old, new}}``
        ``added_references``    – references present in v2 but not v1
        ``removed_references``  – references present in v1 but not v2
        ``unchanged``           – True if no differences were found
    """
    xml1, xml2 = await asyncio.gather(
        _fetch_ddi(client, agency, id, version1, auth_mode),
        _fetch_ddi(client, agency, id, version2, auth_mode),
    )

    parsed1 = parse_ddi_item(xml1)
    parsed2 = parse_ddi_item(xml2)

    label_changes = _diff_lang_map(
        parsed1.get("labels", {}), parsed2.get("labels", {})
    )
    desc_changes = _diff_lang_map(
        parsed1.get("descriptions", {}), parsed2.get("descriptions", {})
    )
    name_changes = _diff_lang_map(
        parsed1.get("names", {}), parsed2.get("names", {})
    )
    added_refs, removed_refs = _diff_references(
        parsed1.get("references", []), parsed2.get("references", [])
    )

    unchanged = not (label_changes or desc_changes or name_changes or added_refs or removed_refs)

    return {
        "agency":               agency,
        "id":                   id,
        "version1":             version1,
        "version2":             version2,
        "item_type":            parsed1.get("type"),
        "label_changes":        label_changes,
        "description_changes":  desc_changes,
        "name_changes":         name_changes,
        "added_references":     added_refs,
        "removed_references":   removed_refs,
        "unchanged":            unchanged,
    }


async def find_harmonizable_variables(
    client: ColecticaApiClient,
    agency: str,
    id: str,
    version: int | None,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Find Variables that share the same Concept or CategoryScheme as the given variable.

    Useful for identifying cross-study harmonization candidates.  The function:

    1. Fetches the target variable's DDI and extracts Concept / CategoryScheme refs.
    2. For each found reference, calls ``search_relationships_by_object`` to
       locate other Variables pointing to the same item.
    3. De-duplicates and returns grouped results.

    Returns
    -------
    dict with keys:
        ``source_variable``      – ``{agency, id, version, type}``
        ``by_concept``           – list of ``{concept, variables: []}``
        ``by_category_scheme``   – list of ``{category_scheme, variables: []}``
        ``total_candidates``     – total unique harmonizable variable identifiers
    """
    xml_text = await _fetch_ddi(client, agency, id, version or 1, auth_mode)
    parsed   = parse_ddi_item(xml_text)

    concept_refs:    list[dict[str, Any]] = []
    cat_scheme_refs: list[dict[str, Any]] = []

    for ref in parsed.get("references", []):
        rtype = ref.get("type", "").lower()
        if "concept" in rtype:
            concept_refs.append(ref)
        elif "categoryscheme" in rtype or "codelist" in rtype:
            cat_scheme_refs.append(ref)

    async def _vars_for_ref(ref: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            rel = await client.call_operation(
                _colectica_op("POST", "/api/v1/query/relationship/byobject"),
                arguments={"body": {
                    "Agency":     ref["agency"],
                    "Identifier": ref["id"],
                    "Version":    ref.get("version", 1),
                }},
                auth_mode=auth_mode,
            )
            all_refs: list[dict[str, Any]] = rel.get("body", []) or []
            return [
                r for r in all_refs
                if "variable" in str(r.get("ItemType", r.get("TypeOfObject", ""))).lower()
                and r.get("Identifier") != id  # exclude self
            ]
        except Exception:  # noqa: BLE001
            return []

    # Fan-out relationship queries in parallel
    concept_var_lists, cat_var_lists = await asyncio.gather(
        asyncio.gather(*[_vars_for_ref(r) for r in concept_refs]),
        asyncio.gather(*[_vars_for_ref(r) for r in cat_scheme_refs]),
    )

    by_concept = [
        {"concept": ref, "variables": vars_}
        for ref, vars_ in zip(concept_refs, concept_var_lists)
        if vars_
    ]
    by_cat = [
        {"category_scheme": ref, "variables": vars_}
        for ref, vars_ in zip(cat_scheme_refs, cat_var_lists)
        if vars_
    ]

    # Unique IDs across all groups
    all_ids: set[str] = set()
    for group in by_concept + by_cat:
        for v in group["variables"]:
            all_ids.add(v.get("Identifier", ""))

    return {
        "source_variable":    {"agency": agency, "id": id, "version": version or 1, "type": parsed.get("type")},
        "by_concept":         by_concept,
        "by_category_scheme": by_cat,
        "total_candidates":   len(all_ids),
    }


async def get_concept_usage(
    client: ColecticaApiClient,
    concept_agency: str,
    concept_id: str,
    concept_version: int,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Report all DDI items that reference a given Concept, grouped by type.

    Useful for impact analysis before modifying a shared concept.

    Returns
    -------
    dict with keys:
        ``concept``          – ``{agency, id, version}``
        ``total_references`` – total count of referencing items
        ``by_type``          – ``{type_name: count}``
        ``references``       – list of ``{agency, id, version, item_type}``
    """
    rel_result = await client.call_operation(
        _colectica_op("POST", "/api/v1/query/relationship/byobject"),
        arguments={"body": {
            "Agency":     concept_agency,
            "Identifier": concept_id,
            "Version":    concept_version,
        }},
        auth_mode=auth_mode,
    )
    all_refs: list[dict[str, Any]] = rel_result.get("body", []) or []

    by_type: dict[str, int] = {}
    references: list[dict[str, Any]] = []

    for r in all_refs:
        raw_type  = r.get("ItemType", r.get("TypeOfObject", "Unknown"))
        type_name = str(raw_type)
        by_type[type_name] = by_type.get(type_name, 0) + 1
        references.append({
            "agency":    r.get("Agency", ""),
            "id":        r.get("Identifier", ""),
            "version":   r.get("Version", 1),
            "item_type": type_name,
        })

    return {
        "concept":          {"agency": concept_agency, "id": concept_id, "version": concept_version},
        "total_references": len(all_refs),
        "by_type":          by_type,
        "references":       references,
    }
