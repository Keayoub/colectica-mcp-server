# SPDX-License-Identifier: Apache-2.0
"""Internal shared helpers — moved from server.py to avoid duplication.

Both ``server.py`` (tool registrations) and the ``utils/`` sub-modules import
from here.  Do not import from ``server.py`` in this file to avoid cycles.
"""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import ColecticaApiClient

# ---------------------------------------------------------------------------
# Operation-ID builder
# ---------------------------------------------------------------------------

def _colectica_op(method: str, path: str) -> str:
    """Build the canonical operationId string used by :class:`ColecticaApiClient`.

    Examples::

        _colectica_op("GET", "/api/v1/item/{agency}/{id}/{version}")
        # → "GET_api_v1_item_agency_id_version"
    """
    normalized_method = re.sub(r"[^A-Za-z0-9]", "_", method.upper())
    normalized_path = re.sub(r"[^A-Za-z0-9]", "_", path)
    normalized_path = re.sub(r"_+", "_", normalized_path).strip("_")
    return f"{normalized_method}_{normalized_path}"


# ---------------------------------------------------------------------------
# Item-type name → GUID resolution
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Module-level cache shared across all callers: {lowercase_type_name: guid}
_item_type_guids_cache: dict[str, str] | None = None
_item_type_guids_lock = asyncio.Lock()


async def _build_item_type_guid_map(client: "ColecticaApiClient") -> dict[str, str]:
    """Discover item-type name → GUID mapping from the live Colectica API.

    Queries the statistics endpoint to enumerate all type GUIDs present in the
    repository, then fetches one DDI fragment per type and reads the first
    child element tag (e.g. ``QuestionItem``, ``Variable``) as the type name.
    Returns ``{lowercase_name: guid}``.
    """
    stats = await client.call_operation(
        _colectica_op("GET", "/api/v1/repository/statistics"), arguments={}
    )
    type_guids: dict[str, int] = stats.get("body", {}).get("ItemCounts", {})

    mapping: dict[str, str] = {}
    for guid in type_guids:
        try:
            search = await client.call_operation(
                _colectica_op("POST", "/api/v1/_query"),
                arguments={"body": {"ItemTypes": [guid], "MaxResults": 1}},
            )
            results = search.get("body", {}).get("Results", [])
            if not results:
                continue
            r = results[0]
            ddi = await client.call_operation(
                _colectica_op("GET", "/api/v1/ddi/{agency}/{identifier}/{version}"),
                arguments={
                    "agency": r["AgencyId"],
                    "identifier": r["Identifier"],
                    "version": r["Version"],
                },
            )
            xml_text = ddi.get("body", "")
            root = ET.fromstring(xml_text)
            first_child = next(iter(root), None)
            if first_child is None:
                continue
            tag = first_child.tag
            if "}" in tag:
                tag = tag.split("}")[1]
            mapping[tag.lower()] = guid
        except Exception:  # noqa: BLE001
            continue

    return mapping


async def _get_item_type_guid_map(client: "ColecticaApiClient") -> dict[str, str]:
    """Return the cached item-type name → GUID map, building it on first call."""
    global _item_type_guids_cache
    if _item_type_guids_cache is not None:
        return _item_type_guids_cache
    async with _item_type_guids_lock:
        if _item_type_guids_cache is None:
            _item_type_guids_cache = await _build_item_type_guid_map(client)
    return _item_type_guids_cache


async def _resolve_item_types(
    types: list[str], client: "ColecticaApiClient"
) -> list[str]:
    """Resolve DDI type names to GUIDs expected by the Colectica search API.

    Values that are already valid UUIDs are passed through unchanged.
    Friendly names (e.g. ``"Variable"``, ``"QuestionItem"``) are looked up in
    the live type map.  Unknown names are returned as-is so the API can emit a
    meaningful error instead of silently dropping them.
    """
    if not types:
        return types
    guid_map = await _get_item_type_guid_map(client)
    resolved: list[str] = []
    for t in types:
        if _UUID_RE.match(t):
            resolved.append(t)
        else:
            resolved.append(guid_map.get(t.lower(), t))
    return resolved
