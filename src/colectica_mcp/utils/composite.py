# SPDX-License-Identifier: Apache-2.0
"""Composite navigation workflows — combine multiple API calls into richer views.

Each function accepts an already-constructed :class:`ColecticaApiClient` and
returns a structured dict ready to be returned by a ``@mcp.tool()``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..client import ColecticaApiClient
from ..config import AuthMode
from ._internal import _colectica_op, _get_item_type_guid_map
from .ddi_parser import parse_ddi_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identifier(agency: str, id: str, version: int | None) -> dict[str, Any]:
    d: dict[str, Any] = {"Agency": agency, "Identifier": id}
    if version is not None:
        d["Version"] = version
    return d


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


async def _fetch_description(
    client: ColecticaApiClient,
    identifiers: list[dict[str, Any]],
    auth_mode: AuthMode,
) -> list[dict[str, Any]]:
    """Bulk-fetch item descriptions for a list of identifier dicts."""
    if not identifiers:
        return []
    result = await client.call_operation(
        _colectica_op("POST", "/api/v1/item/_getDescriptions"),
        arguments={"body": {"Identifiers": identifiers}},
        auth_mode=auth_mode,
    )
    return result.get("body", {}).get("Descriptions", result.get("body", []) or [])


def _first_label(description: dict[str, Any]) -> str:
    """Extract a best-effort single label string from a description dict."""
    label = description.get("Label") or description.get("label") or {}
    if isinstance(label, dict):
        for lang in ("en-US", "en", "_"):
            if lang in label and label[lang]:
                return label[lang]
        for v in label.values():
            if v:
                return v
    if isinstance(label, str):
        return label
    return description.get("Name") or description.get("name") or ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_study_outline(
    client: ColecticaApiClient,
    agency: str,
    id: str,
    version: int | None,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Return a hierarchical outline of a StudyUnit (or any set-bearing item).

    Fetches the full typed item set for the given identifier, groups children
    by their DDI type, and resolves their labels via a bulk description call.

    Returns
    -------
    dict with keys:
        ``root``           – ``{agency, id, version, label}`` of the root item
        ``total_items``    – total number of items in the set (including root)
        ``by_type``        – ``{type_name: [{agency, id, version, label}]}``
    """
    # 1. Fetch the typed item set
    set_result = await client.call_operation(
        _colectica_op("GET", "/api/v1/set/{agency}/{id}/{version}/typed"),
        arguments={"agency": agency, "id": id, "version": version or 1},
        auth_mode=auth_mode,
    )
    set_body = set_result.get("body", {})
    items: list[dict[str, Any]] = set_body.get("Items", set_body if isinstance(set_body, list) else [])

    # 2. Reverse-map type GUIDs to human-readable names
    guid_to_name: dict[str, str] = {}
    try:
        guid_map = await _get_item_type_guid_map(client)
        guid_to_name = {v: k for k, v in guid_map.items()}
    except Exception:  # noqa: BLE001
        pass

    # 3. Bulk-fetch descriptions for all items (labels)
    identifiers = [
        {"Agency": it.get("AgencyId", it.get("Agency", "")),
         "Identifier": it.get("Identifier", it.get("ID", "")),
         "Version": it.get("Version", 1)}
        for it in items
    ]
    descriptions: list[dict[str, Any]] = []
    try:
        descriptions = await _fetch_description(client, identifiers, auth_mode)
    except Exception:  # noqa: BLE001
        pass

    # Build lookup: (agency, identifier) → label
    desc_lookup: dict[tuple[str, str], str] = {}
    for d in descriptions:
        key = (d.get("AgencyId", ""), d.get("Identifier", ""))
        desc_lookup[key] = _first_label(d)

    # 4. Group by type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        raw_type = it.get("ItemType", it.get("TypeGuid", ""))
        type_name = guid_to_name.get(raw_type.lower() if raw_type else "", raw_type or "Unknown")
        type_name = type_name[:1].upper() + type_name[1:] if type_name else "Unknown"

        item_agency = it.get("AgencyId", it.get("Agency", agency))
        item_id     = it.get("Identifier", it.get("ID", ""))
        item_ver    = it.get("Version", 1)
        label       = desc_lookup.get((item_agency, item_id), "")

        by_type.setdefault(type_name, []).append({
            "agency":  item_agency,
            "id":      item_id,
            "version": item_ver,
            "label":   label,
        })

    return {
        "root":        {"agency": agency, "id": id, "version": version or 1},
        "total_items": len(items),
        "by_type":     by_type,
    }


async def get_codebook_for_variable(
    client: ColecticaApiClient,
    agency: str,
    id: str,
    version: int | None,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Retrieve a variable together with its associated codebook (codes/categories).

    Fetches the variable DDI, locates its ``CategorySchemeReference`` or
    ``CodeDomain → CodeListReference``, then fetches that scheme to build
    the full list of codes with labels.

    Returns
    -------
    dict with keys:
        ``variable``        – parsed variable info (from :func:`parse_ddi_item`)
        ``category_scheme`` – ``{agency, id, version, label}`` or ``None``
        ``codes``           – list of ``{value, label}`` dicts
        ``note``            – diagnostic message if category scheme not found
    """
    # 1. Fetch variable DDI
    xml_text = await _fetch_ddi(client, agency, id, version or 1, auth_mode)
    variable = parse_ddi_item(xml_text)

    # 2. Find CategoryScheme / CodeList reference in the parsed references
    cat_ref: dict[str, Any] | None = None
    for ref in variable.get("references", []):
        rtype = ref.get("type", "").lower()
        if "categoryscheme" in rtype or "codelist" in rtype:
            cat_ref = ref
            break

    if cat_ref is None:
        return {
            "variable":        variable,
            "category_scheme": None,
            "codes":           [],
            "note":            "No CategoryScheme or CodeList reference found on this variable.",
        }

    # 3. Fetch the category scheme DDI
    cat_agency  = cat_ref.get("agency",  agency)
    cat_id      = cat_ref.get("id",      "")
    cat_version = cat_ref.get("version", 1)

    cat_xml = await _fetch_ddi(client, cat_agency, cat_id, cat_version, auth_mode)
    import xml.etree.ElementTree as ET  # local import keeps top-level clean

    codes: list[dict[str, Any]] = []
    try:
        cat_root = ET.fromstring(cat_xml)
        cat_el   = next(iter(cat_root), None)
        if cat_el is not None:
            ns = cat_el.tag.split("}")[0].lstrip("{") if "}" in cat_el.tag else ""
            _q = lambda name: f"{{{ns}}}{name}" if ns else name  # noqa: E731
            from ._internal import _NS_R  # type: ignore[attr-defined]
            _NS_R_LOCAL = "ddi:reusable:3_3"
            for cat in cat_el.iter(_q("Category")):
                # Value from Code (sibling element typically) — try Code/Value first
                value = ""
                code_el = cat.find(f"{{{_NS_R_LOCAL}}}Value")
                if code_el is not None:
                    value = (code_el.text or "").strip()

                # Label
                label_dict: dict[str, str] = {}
                for label_el in cat.findall(f"{{{_NS_R_LOCAL}}}Label"):
                    for content_el in label_el.iter(f"{{{_NS_R_LOCAL}}}Content"):
                        lang_attr = content_el.get("{http://www.w3.org/XML/1998/namespace}lang", "_")
                        if content_el.text:
                            label_dict[lang_attr] = content_el.text.strip()

                codes.append({"value": value, "label": label_dict})
    except ET.ParseError:
        pass

    cat_parsed = parse_ddi_item(cat_xml)

    return {
        "variable":        variable,
        "category_scheme": {
            "agency":  cat_agency,
            "id":      cat_id,
            "version": cat_version,
            "label":   cat_parsed.get("labels", {}),
        },
        "codes": codes,
    }


async def get_question_with_responses(
    client: ColecticaApiClient,
    agency: str,
    id: str,
    version: int | None,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Retrieve a QuestionItem with its full response domain.

    Parses the DDI fragment to extract question text (all languages) and the
    response domain type.  If a CodeDomain is found, fetches the associated
    category scheme and includes its codes.

    Returns
    -------
    dict with keys:
        ``question``         – parsed item info
        ``question_text``    – ``{lang: text}``
        ``response_domain``  – ``{type, category_scheme, codes}`` or ``{type, description}``
    """
    import xml.etree.ElementTree as ET  # noqa: PLC0415

    xml_text = await _fetch_ddi(client, agency, id, version or 1, auth_mode)
    question  = parse_ddi_item(xml_text)

    # Parse question text
    question_text: dict[str, str] = {}
    try:
        root    = ET.fromstring(xml_text)
        item_el = next(iter(root), None)
        if item_el is not None:
            ns = item_el.tag.split("}")[0].lstrip("{") if "}" in item_el.tag else ""
            _q = lambda n: f"{{{ns}}}{n}" if ns else n  # noqa: E731
            _r = lambda n: f"{{ddi:reusable:3_3}}{n}"   # noqa: E731
            _xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"

            for qt_el in item_el.iter(_q("QuestionText")):
                for lit_el in qt_el.iter(_q("LiteralText")):
                    for txt_el in lit_el.iter(_q("Text")):
                        lang = txt_el.get(_xml_lang, "_")
                        if txt_el.text:
                            question_text[lang] = txt_el.text.strip()
                # Also try r:String-style
                for str_el in qt_el.iter(_r("String")):
                    lang = str_el.get(_xml_lang, "_")
                    if str_el.text:
                        question_text[lang] = str_el.text.strip()
    except ET.ParseError:
        pass

    # Identify response domain type
    response_domain: dict[str, Any] = {"type": "Unknown"}
    for ref in question.get("references", []):
        rtype = ref.get("type", "").lower()
        if "categoryscheme" in rtype or "codelist" in rtype:
            # CodeDomain — fetch codes
            try:
                codebook = await get_codebook_for_variable(
                    client, agency, id, version, auth_mode
                )
                response_domain = {
                    "type":            "CodeDomain",
                    "category_scheme": codebook.get("category_scheme"),
                    "codes":           codebook.get("codes", []),
                }
            except Exception:  # noqa: BLE001
                response_domain = {"type": "CodeDomain", "reference": ref}
            break
        if "numeric" in rtype:
            response_domain = {"type": "NumericDomain"}
            break
        if "text" in rtype:
            response_domain = {"type": "TextDomain"}
            break

    return {
        "question":        question,
        "question_text":   question_text,
        "response_domain": response_domain,
    }


async def find_variables_by_concept(
    client: ColecticaApiClient,
    concept_agency: str,
    concept_id: str,
    concept_version: int,
    max_results: int,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Find all Variable items that reference a given Concept.

    Uses the ``search_relationships_by_object`` endpoint to locate items
    pointing to the specified concept, then filters to Variable type only.

    Returns
    -------
    dict with keys:
        ``concept_id``       – the supplied concept GUID
        ``total_referenced`` – total items referencing this concept (all types)
        ``total_variables``  – number of Variable items found
        ``variables``        – list of ``{agency, id, version, label}``
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

    # Filter to Variable type — check ItemType label or type name
    variable_refs = [
        r for r in all_refs
        if "variable" in str(r.get("ItemType", "")).lower()
        or "variable" in str(r.get("TypeOfObject", "")).lower()
    ][:max_results]

    # Bulk description lookup for labels
    identifiers = [
        {"Agency": r.get("Agency", ""), "Identifier": r.get("Identifier", ""), "Version": r.get("Version", 1)}
        for r in variable_refs
    ]
    descriptions: list[dict[str, Any]] = []
    try:
        descriptions = await _fetch_description(client, identifiers, auth_mode)
    except Exception:  # noqa: BLE001
        pass

    desc_lookup: dict[tuple[str, str], str] = {
        (d.get("AgencyId", ""), d.get("Identifier", "")): _first_label(d)
        for d in descriptions
    }

    variables = [
        {
            "agency":  r.get("Agency", ""),
            "id":      r.get("Identifier", ""),
            "version": r.get("Version", 1),
            "label":   desc_lookup.get((r.get("Agency", ""), r.get("Identifier", "")), ""),
        }
        for r in variable_refs
    ]

    return {
        "concept_id":       concept_id,
        "total_referenced": len(all_refs),
        "total_variables":  len(variables),
        "variables":        variables,
    }
