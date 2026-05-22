# SPDX-License-Identifier: Apache-2.0
"""Pure DDI XML parsing helpers — no network calls, no async.

All functions accept a raw DDI 3.x XML string (as returned by
``get_ddi_fragment``) and return plain Python dicts.

DDI 3.3 XML conventions used here
----------------------------------
* The outer element is always ``<Fragment xmlns="ddi:instance:3_3" …>``
* The first child is the strongly-typed DDI element (``Variable``,
  ``QuestionItem``, ``StudyUnit``, etc.) in its own namespace.
* Reusable elements use the ``ddi:reusable:3_3`` namespace (``r:`` prefix).
* Multilingual text lives in ``r:Content`` or ``r:String`` elements with an
  ``xml:lang`` attribute.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------

_NS_R = "ddi:reusable:3_3"            # r: prefix
_NS_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# Clark-notation shortcuts for frequently accessed elements
_TAG_URN         = f"{{{_NS_R}}}URN"
_TAG_AGENCY      = f"{{{_NS_R}}}Agency"
_TAG_ID          = f"{{{_NS_R}}}ID"
_TAG_VERSION     = f"{{{_NS_R}}}Version"
_TAG_LABEL       = f"{{{_NS_R}}}Label"
_TAG_DESCRIPTION = f"{{{_NS_R}}}Description"
_TAG_CONTENT     = f"{{{_NS_R}}}Content"
_TAG_STRING      = f"{{{_NS_R}}}String"
_TAG_TYPE_OBJ    = f"{{{_NS_R}}}TypeOfObject"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    """Strip the ``{namespace}`` prefix and return the local name."""
    return tag.split("}")[1] if "}" in tag else tag


def _get_typed_child(root: ET.Element) -> ET.Element | None:
    """Return the first child of a Fragment element (the DDI typed item)."""
    return next(iter(root), None)


def _collect_multilingual(element: ET.Element, child_tag: str) -> dict[str, str]:
    """Walk *element* for *child_tag* children and collect lang → text pairs.

    Works for both ``r:Content`` and ``r:String`` child patterns.
    """
    result: dict[str, str] = {}
    for child in element.iter(child_tag):
        lang = child.get(_NS_XML_LANG, "")
        text = (child.text or "").strip()
        if text:
            result[lang or "_"] = text
    return result


def _collect_label_desc(
    item_el: ET.Element,
) -> tuple[dict[str, str], dict[str, str]]:
    """Extract label and description multilingual dicts from a DDI item element."""
    labels: dict[str, str] = {}
    descriptions: dict[str, str] = {}

    for label_el in item_el.findall(_TAG_LABEL):
        labels.update(_collect_multilingual(label_el, _TAG_CONTENT))

    for desc_el in item_el.findall(_TAG_DESCRIPTION):
        descriptions.update(_collect_multilingual(desc_el, _TAG_CONTENT))

    return labels, descriptions


def _collect_references(item_el: ET.Element) -> list[dict[str, Any]]:
    """Collect all *Reference child elements and return a list of identity dicts."""
    refs: list[dict[str, Any]] = []
    for child in item_el:
        local = _local(child.tag)
        if not local.endswith("Reference"):
            continue
        agency_el  = child.find(_TAG_AGENCY)
        id_el      = child.find(_TAG_ID)
        version_el = child.find(_TAG_VERSION)
        type_el    = child.find(_TAG_TYPE_OBJ)
        if id_el is None:
            continue
        refs.append({
            "type":    (type_el.text or "").strip() if type_el is not None else _local(child.tag).replace("Reference", ""),
            "agency":  (agency_el.text  or "").strip() if agency_el  is not None else "",
            "id":      (id_el.text      or "").strip(),
            "version": int(version_el.text or 1) if version_el is not None else 1,
        })
    return refs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_ddi_item(xml_text: str) -> dict[str, Any]:
    """Parse a DDI 3.x Fragment XML string into a structured dict.

    Returns
    -------
    dict with keys:
        ``type``          – local element name of the DDI item (e.g. ``"Variable"``)
        ``urn``           – full DDI URN string
        ``agency``        – agency identifier
        ``id``            – item GUID
        ``version``       – integer version
        ``labels``        – ``{lang: text}`` from ``r:Label``
        ``descriptions``  – ``{lang: text}`` from ``r:Description``
        ``names``         – ``{lang: text}`` from ``*Name/r:String`` children
        ``references``    – list of ``{type, agency, id, version}`` dicts from
                           ``*Reference`` children
        ``raw_type_tag``  – full Clark-notation tag of the typed child
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {"error": f"XML parse error: {exc}"}

    item_el = _get_typed_child(root)
    if item_el is None:
        return {"error": "Fragment has no child element"}

    type_name   = _local(item_el.tag)

    urn_el      = item_el.find(_TAG_URN)
    agency_el   = item_el.find(_TAG_AGENCY)
    id_el       = item_el.find(_TAG_ID)
    version_el  = item_el.find(_TAG_VERSION)

    labels, descriptions = _collect_label_desc(item_el)
    references           = _collect_references(item_el)

    # Names: search for elements whose local tag ends with "Name"
    # (e.g. VariableName, QuestionItemName) containing r:String children.
    names: dict[str, str] = {}
    for child in item_el:
        if _local(child.tag).endswith("Name"):
            names.update(_collect_multilingual(child, _TAG_STRING))

    return {
        "type":         type_name,
        "urn":          (urn_el.text     or "").strip() if urn_el     is not None else "",
        "agency":       (agency_el.text  or "").strip() if agency_el  is not None else "",
        "id":           (id_el.text      or "").strip() if id_el      is not None else "",
        "version":      int(version_el.text or 1)       if version_el is not None else 1,
        "labels":       labels,
        "descriptions": descriptions,
        "names":        names,
        "references":   references,
        "raw_type_tag": item_el.tag,
    }


def extract_variable_stats(xml_text: str) -> dict[str, Any]:
    """Parse a VariableStatistics DDI fragment into a structured stats dict.

    Returns
    -------
    dict with keys:
        ``variable_reference``   – ``{type, agency, id, version}``
        ``total_responses``      – int
        ``summary_statistics``   – list of ``{type: str, value: float}``
        ``category_statistics``  – list of ``{value, frequency, is_missing}``
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {"error": f"XML parse error: {exc}"}

    item_el = _get_typed_child(root)
    if item_el is None:
        return {"error": "Fragment has no child element"}

    # Resolve the active namespace for VariableStatistics sub-elements.
    # They use the same namespace as the typed item.
    ns = item_el.tag.split("}")[0].lstrip("{") if "}" in item_el.tag else ""
    _q = lambda name: f"{{{ns}}}{name}" if ns else name  # noqa: E731

    # VariableReference
    var_ref: dict[str, Any] = {}
    var_ref_el = item_el.find(_q("VariableReference"))
    if var_ref_el is not None:
        agency_el  = var_ref_el.find(_TAG_AGENCY)
        id_el      = var_ref_el.find(_TAG_ID)
        version_el = var_ref_el.find(_TAG_VERSION)
        type_el    = var_ref_el.find(_TAG_TYPE_OBJ)
        var_ref = {
            "type":    (type_el.text    or "Variable").strip() if type_el    is not None else "Variable",
            "agency":  (agency_el.text  or "").strip()         if agency_el  is not None else "",
            "id":      (id_el.text      or "").strip()         if id_el      is not None else "",
            "version": int(version_el.text or 1)               if version_el is not None else 1,
        }

    # TotalResponses
    total_el = item_el.find(_q("TotalResponses"))
    total    = int((total_el.text or 0)) if total_el is not None else None

    # SummaryStatistic list
    summary_stats: list[dict[str, Any]] = []
    for ss_el in item_el.iter(_q("SummaryStatistic")):
        type_el  = ss_el.find(_q("TypeOfSummaryStatistic"))
        stat_el  = ss_el.find(_q("Statistic"))
        if stat_el is None:
            continue
        try:
            value = float(stat_el.text or 0)
        except ValueError:
            value = 0.0
        summary_stats.append({
            "type":  (type_el.text or "").strip() if type_el is not None else "",
            "value": value,
        })

    # CategoryStatistics
    cat_stats: list[dict[str, Any]] = []
    for cs_el in item_el.iter(_q("CategoryStatistic")):
        value_el = cs_el.find(_q("Value"))
        freq_el  = cs_el.find(_q("Frequency"))
        miss_el  = cs_el.find(_q("Missing"))
        cat_stats.append({
            "value":      (value_el.text or "").strip() if value_el is not None else "",
            "frequency":  int(freq_el.text or 0)        if freq_el  is not None else 0,
            "is_missing": (miss_el.text or "false").strip().lower() == "true" if miss_el is not None else False,
        })

    return {
        "variable_reference":  var_ref,
        "total_responses":     total,
        "summary_statistics":  summary_stats,
        "category_statistics": cat_stats,
    }


def get_multilingual_labels(xml_text: str) -> dict[str, Any]:
    """Extract all multilingual label, description, and name variants from DDI XML.

    Useful for finding gaps in translations across languages.

    Returns
    -------
    dict with keys:
        ``item_type``    – DDI element type name
        ``labels``       – ``{lang: text}``
        ``descriptions`` – ``{lang: text}``
        ``names``        – ``{lang: text}``
        ``all_languages``– sorted list of all language codes encountered
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {"error": f"XML parse error: {exc}"}

    item_el = _get_typed_child(root)
    if item_el is None:
        return {"error": "Fragment has no child element"}

    labels, descriptions = _collect_label_desc(item_el)
    names: dict[str, str] = {}
    for child in item_el:
        if _local(child.tag).endswith("Name"):
            names.update(_collect_multilingual(child, _TAG_STRING))

    all_langs = sorted(set(list(labels) + list(descriptions) + list(names)))

    return {
        "item_type":    _local(item_el.tag),
        "labels":       labels,
        "descriptions": descriptions,
        "names":        names,
        "all_languages": all_langs,
    }


def validate_ddi_fragment(xml_text: str) -> dict[str, Any]:
    """Validate a DDI Fragment XML string for structural correctness.

    Checks
    ------
    * Well-formed XML
    * Root element is ``Fragment`` (namespace-aware)
    * Fragment has exactly one typed child element
    * Typed child has ``r:URN``, ``r:Agency``, ``r:ID``, ``r:Version``

    Returns
    -------
    dict with keys:
        ``valid``      – bool
        ``item_type``  – type name if parseable, else ``None``
        ``urn``        – URN value if found
        ``issues``     – list of human-readable issue strings
    """
    issues: list[str] = []
    item_type: str | None = None
    urn_value: str | None = None

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return {"valid": False, "item_type": None, "urn": None, "issues": [f"XML parse error: {exc}"]}

    if _local(root.tag) != "Fragment":
        issues.append(f"Root element should be 'Fragment', got '{_local(root.tag)}'")

    children = list(root)
    if not children:
        issues.append("Fragment has no child elements")
        return {"valid": False, "item_type": None, "urn": None, "issues": issues}

    if len(children) > 1:
        issues.append(f"Fragment should have exactly 1 child, found {len(children)}")

    item_el = children[0]
    item_type = _local(item_el.tag)

    for required_tag, label in [
        (_TAG_URN,     "r:URN"),
        (_TAG_AGENCY,  "r:Agency"),
        (_TAG_ID,      "r:ID"),
        (_TAG_VERSION, "r:Version"),
    ]:
        el = item_el.find(required_tag)
        if el is None or not (el.text or "").strip():
            issues.append(f"Missing or empty '{label}'")
        elif required_tag == _TAG_URN:
            urn_value = el.text.strip()

    return {
        "valid":     len(issues) == 0,
        "item_type": item_type,
        "urn":       urn_value,
        "issues":    issues,
    }
