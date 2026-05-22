# SPDX-License-Identifier: Apache-2.0
"""DDI item creation and bulk import helpers.

Builds minimal DDI 3.3 XML for Variables and QuestionItems, then registers
them via the Colectica transaction API.

DDI 3.3 item format GUID used for registration::

    DC337820-AF3A-4C0B-82F9-CF02535CDE83

Transaction commit type used::

    CommitAsLatestWithLatestChildrenAndPropagateVersions
"""
from __future__ import annotations

import csv
import io
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from ..client import ColecticaApiClient
from ..config import AuthMode
from ._internal import _colectica_op, _get_item_type_guid_map

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DDI33_FORMAT_GUID  = "DC337820-AF3A-4C0B-82F9-CF02535CDE83"
_COMMIT_TYPE        = "CommitAsLatestWithLatestChildrenAndPropagateVersions"

# DDI 3.3 XML namespaces
_NS_I  = "ddi:instance:3_3"
_NS_R  = "ddi:reusable:3_3"
_NS_V  = "ddi:variable:3_3"
_NS_DC = "ddi:datacollection:3_3"

# Register all namespaces for clean serialisation (no ns0: prefixes)
ET.register_namespace("",  _NS_I)
ET.register_namespace("r", _NS_R)
ET.register_namespace("v", _NS_V)
ET.register_namespace("d", _NS_DC)


# ---------------------------------------------------------------------------
# DDI XML builders
# ---------------------------------------------------------------------------

def _r(name: str) -> str:
    """Return Clark-notation tag in the ddi:reusable:3_3 namespace."""
    return f"{{{_NS_R}}}{name}"


def _make_identity_elements(
    parent: ET.Element,
    agency: str,
    item_id: str,
    version: int,
) -> None:
    """Append r:URN, r:Agency, r:ID, r:Version to *parent*."""
    ET.SubElement(parent, _r("URN")).text    = f"urn:ddi:{agency}:{item_id}:{version}"
    ET.SubElement(parent, _r("Agency")).text  = agency
    ET.SubElement(parent, _r("ID")).text     = item_id
    ET.SubElement(parent, _r("Version")).text = str(version)


def _make_label(
    parent: ET.Element,
    label: str,
    language: str = "en-US",
) -> None:
    """Append an r:Label element containing an r:Content child."""
    label_el   = ET.SubElement(parent, _r("Label"))
    content_el = ET.SubElement(label_el, _r("Content"))
    content_el.set("{http://www.w3.org/XML/1998/namespace}lang", language)
    content_el.text = label


def _make_description(
    parent: ET.Element,
    description: str,
    language: str = "en-US",
) -> None:
    """Append an r:Description element containing an r:Content child."""
    desc_el    = ET.SubElement(parent, _r("Description"))
    content_el = ET.SubElement(desc_el, _r("Content"))
    content_el.set("{http://www.w3.org/XML/1998/namespace}lang", language)
    content_el.text = description


def build_variable_xml(
    agency: str,
    item_id: str,
    name: str,
    label: str,
    description: str = "",
    language: str    = "en-US",
    version: int     = 1,
    concept_guid: str | None = None,
) -> str:
    """Build a minimal DDI 3.3 Variable Fragment XML string.

    Parameters
    ----------
    agency:
        Colectica agency identifier.
    item_id:
        GUID for the new variable.
    name:
        Short machine-readable variable name (e.g. ``"AGE"``).
    label:
        Human-readable label.
    description:
        Optional free-text description.
    language:
        BCP-47 language code for label/description/name.
    version:
        DDI version integer (default 1).
    concept_guid:
        Optional GUID of a Concept to reference.

    Returns
    -------
    UTF-8 XML string.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fragment root
    fragment = ET.Element(f"{{{_NS_I}}}Fragment")

    # Variable element
    variable = ET.SubElement(fragment, f"{{{_NS_V}}}Variable")
    variable.set("isUniversallyUnique", "true")
    variable.set("versionDate", now)

    _make_identity_elements(variable, agency, item_id, version)

    # VariableName
    var_name_el = ET.SubElement(variable, f"{{{_NS_V}}}VariableName")
    str_el      = ET.SubElement(var_name_el, _r("String"))
    str_el.set("{http://www.w3.org/XML/1998/namespace}lang", language)
    str_el.text = name

    _make_label(variable, label, language)
    if description:
        _make_description(variable, description, language)

    # Optional Concept reference
    if concept_guid:
        ref_el    = ET.SubElement(variable, f"{{{_NS_V}}}ConceptReference")
        ET.SubElement(ref_el, _r("Agency")).text  = agency
        ET.SubElement(ref_el, _r("ID")).text      = concept_guid
        ET.SubElement(ref_el, _r("Version")).text = "1"
        ET.SubElement(ref_el, _r("TypeOfObject")).text = "Concept"

    return ET.tostring(fragment, encoding="unicode", xml_declaration=False)


def build_question_item_xml(
    agency: str,
    item_id: str,
    question_text: str,
    label: str       = "",
    description: str = "",
    language: str    = "en-US",
    version: int     = 1,
    response_type: str = "text",
) -> str:
    """Build a minimal DDI 3.3 QuestionItem Fragment XML string.

    Parameters
    ----------
    response_type:
        One of ``"text"`` (default), ``"numeric"``.  Use
        ``get_codebook_for_variable`` + ``create_variable_from_dict`` for
        code-domain questions.

    Returns
    -------
    UTF-8 XML string.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    fragment = ET.Element(f"{{{_NS_I}}}Fragment")
    qi       = ET.SubElement(fragment, f"{{{_NS_DC}}}QuestionItem")
    qi.set("isUniversallyUnique", "true")
    qi.set("versionDate", now)

    _make_identity_elements(qi, agency, item_id, version)

    if label:
        _make_label(qi, label, language)
    if description:
        _make_description(qi, description, language)

    # QuestionItemName
    qi_name = ET.SubElement(qi, f"{{{_NS_DC}}}QuestionItemName")
    str_el  = ET.SubElement(qi_name, _r("String"))
    str_el.set("{http://www.w3.org/XML/1998/namespace}lang", language)
    str_el.text = label or question_text[:80]

    # QuestionText
    qt_el   = ET.SubElement(qi, f"{{{_NS_DC}}}QuestionText")
    lit_el  = ET.SubElement(qt_el, f"{{{_NS_DC}}}LiteralText")
    txt_el  = ET.SubElement(lit_el, f"{{{_NS_DC}}}Text")
    txt_el.set("{http://www.w3.org/XML/1998/namespace}lang", language)
    txt_el.text = question_text

    # Response domain
    if response_type == "numeric":
        ET.SubElement(qi, f"{{{_NS_DC}}}NumericDomain")
    else:
        ET.SubElement(qi, f"{{{_NS_DC}}}TextDomain")

    return ET.tostring(fragment, encoding="unicode", xml_declaration=False)


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------

async def _create_and_commit_transaction(
    client: ColecticaApiClient,
    agency: str,
    items_xml: list[tuple[str, str, str, int]],  # (item_type_guid, item_id, xml, version)
    auth_mode: AuthMode,
    version_rationale: str = "Created via Colectica MCP",
) -> dict[str, Any]:
    """Create a transaction, add DDI items, and commit it.

    Returns the transaction commit response body, or an error dict on failure.
    """
    # 1. Open transaction
    tx_result = await client.call_operation(
        _colectica_op("POST", "/api/v1/transaction"),
        arguments={"body": {}},
        auth_mode=auth_mode,
    )
    tx_id = tx_result.get("body")
    if isinstance(tx_id, dict):
        tx_id = tx_id.get("TransactionId") or tx_id.get("transactionId")
    if not tx_id:
        raise RuntimeError(f"Failed to create transaction: {tx_result}")

    # 2. Add items
    item_payloads = [
        {
            "ItemType":   type_guid,
            "AgencyId":   agency,
            "Identifier": item_id,
            "Version":    version,
            "Item":       xml_str,
            "ItemFormat": _DDI33_FORMAT_GUID,
            "IsPublished": False,
        }
        for type_guid, item_id, xml_str, version in items_xml
    ]
    await client.call_operation(
        _colectica_op("POST", "/api/v1/transaction/_addItemsToTransaction"),
        arguments={"body": {"TransactionId": tx_id, "Items": item_payloads}},
        auth_mode=auth_mode,
    )

    # 3. Commit
    commit_result = await client.call_operation(
        _colectica_op("POST", "/api/v1/transaction/_commitTransaction"),
        arguments={"body": {
            "TransactionId":  tx_id,
            "TransactionType": _COMMIT_TYPE,
            "VersionRationale": {auth_mode: version_rationale},
        }},
        auth_mode=auth_mode,
    )
    return commit_result.get("body") or {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def create_variable_from_dict(
    client: ColecticaApiClient,
    variable_data: dict[str, Any],
    agency: str,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Create a new DDI 3.3 Variable in the repository.

    Parameters
    ----------
    variable_data:
        dict with keys:

        * ``name``         – short variable name (required)
        * ``label``        – human-readable label (required)
        * ``description``  – free-text description (optional)
        * ``concept_guid`` – GUID of associated Concept (optional)
        * ``language``     – BCP-47 language tag (default ``"en-US"``)
        * ``version``      – DDI version integer (default 1)
    agency:
        Target Colectica agency.

    Returns
    -------
    dict with keys:
        ``agency`` / ``id`` / ``version`` / ``urn`` / ``item_type``
    """
    name         = variable_data.get("name", "")
    label        = variable_data.get("label", name)
    description  = variable_data.get("description", "")
    concept_guid = variable_data.get("concept_guid")
    language     = variable_data.get("language", "en-US")
    version      = int(variable_data.get("version", 1))

    if not name:
        raise ValueError("variable_data must contain a 'name' key")

    # Resolve Variable type GUID
    guid_map   = await _get_item_type_guid_map(client)
    type_guid  = guid_map.get("variable", "")

    item_id = str(uuid.uuid4())
    xml_str = build_variable_xml(
        agency=agency, item_id=item_id, name=name, label=label,
        description=description, language=language, version=version,
        concept_guid=concept_guid,
    )

    await _create_and_commit_transaction(
        client, agency, [(type_guid, item_id, xml_str, version)], auth_mode
    )

    return {
        "agency":    agency,
        "id":        item_id,
        "version":   version,
        "urn":       f"urn:ddi:{agency}:{item_id}:{version}",
        "item_type": "Variable",
    }


async def create_question_item(
    client: ColecticaApiClient,
    question_data: dict[str, Any],
    agency: str,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Create a new DDI 3.3 QuestionItem in the repository.

    Parameters
    ----------
    question_data:
        dict with keys:

        * ``question_text``   – the question text (required)
        * ``label``           – human-readable label (optional, defaults to first 80 chars)
        * ``description``     – free-text description (optional)
        * ``response_type``   – ``"text"`` (default) or ``"numeric"``
        * ``language``        – BCP-47 language tag (default ``"en-US"``)
        * ``version``         – DDI version integer (default 1)
    agency:
        Target Colectica agency.

    Returns
    -------
    dict with keys:
        ``agency`` / ``id`` / ``version`` / ``urn`` / ``item_type``
    """
    question_text = question_data.get("question_text", "")
    label         = question_data.get("label", question_text[:80])
    description   = question_data.get("description", "")
    response_type = question_data.get("response_type", "text")
    language      = question_data.get("language", "en-US")
    version       = int(question_data.get("version", 1))

    if not question_text:
        raise ValueError("question_data must contain a 'question_text' key")

    guid_map  = await _get_item_type_guid_map(client)
    type_guid = guid_map.get("questionitem", "")

    item_id = str(uuid.uuid4())
    xml_str = build_question_item_xml(
        agency=agency, item_id=item_id, question_text=question_text,
        label=label, description=description, language=language,
        version=version, response_type=response_type,
    )

    await _create_and_commit_transaction(
        client, agency, [(type_guid, item_id, xml_str, version)], auth_mode
    )

    return {
        "agency":    agency,
        "id":        item_id,
        "version":   version,
        "urn":       f"urn:ddi:{agency}:{item_id}:{version}",
        "item_type": "QuestionItem",
    }


async def import_variables_from_csv_text(
    client: ColecticaApiClient,
    csv_text: str,
    agency: str,
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Bulk-import Variables from a CSV string in a single transaction.

    Expected CSV columns (header row required):

    ``name``, ``label``, ``description`` (optional), ``concept_guid`` (optional),
    ``language`` (optional, defaults to ``"en-US"``)

    All rows are submitted atomically — if the transaction fails, nothing is
    committed.

    Returns
    -------
    dict with keys:
        ``attempted``   – number of rows parsed
        ``created``     – number of variables in the committed transaction
        ``items``       – list of ``{agency, id, version, urn, name}``
        ``parse_errors``– list of ``{row, error}`` for rows that failed to parse
    """
    guid_map  = await _get_item_type_guid_map(client)
    type_guid = guid_map.get("variable", "")

    reader       = csv.DictReader(io.StringIO(csv_text))
    items_xml:   list[tuple[str, str, str, int]] = []
    created_meta: list[dict[str, Any]]           = []
    parse_errors: list[dict[str, Any]]           = []

    for i, row in enumerate(reader, start=1):
        name    = (row.get("name") or "").strip()
        label   = (row.get("label") or name).strip()
        if not name:
            parse_errors.append({"row": i, "error": "Missing 'name' column value"})
            continue
        description  = (row.get("description") or "").strip()
        concept_guid = (row.get("concept_guid") or "").strip() or None
        language     = (row.get("language") or "en-US").strip()

        item_id = str(uuid.uuid4())
        xml_str = build_variable_xml(
            agency=agency, item_id=item_id, name=name, label=label,
            description=description, language=language, concept_guid=concept_guid,
        )
        items_xml.append((type_guid, item_id, xml_str, 1))
        created_meta.append({"agency": agency, "id": item_id, "version": 1,
                              "urn": f"urn:ddi:{agency}:{item_id}:1", "name": name})

    if items_xml:
        await _create_and_commit_transaction(client, agency, items_xml, auth_mode)

    return {
        "attempted":    len(items_xml) + len(parse_errors),
        "created":      len(items_xml),
        "items":        created_meta,
        "parse_errors": parse_errors,
    }
