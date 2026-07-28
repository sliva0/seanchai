"""Corrections for 3GPP TS 29.214 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    definition,
    enum_value,
    reused_row,
)

# Ten grouped-AVP clauses print `<AVP header: nnn>` with no vendor-id while
# table 5.3.0.1 marks the V flag mandatory for every one of them, exactly the
# TS 29.272 WLAN-offloadability case.
_VENDORLESS = [
    ("Access-Network-Charging-Identifier", "5.3.3"),
    ("Flows", "5.3.10"),
    ("Media-Component-Description", "5.3.16"),
    ("Media-Sub-Component", "5.3.18"),
    ("Acceptable-Service-Info", "5.3.24"),
    ("Sponsored-Connectivity-Data", "5.3.27"),
    ("Callee-Information", "5.3.62"),
    ("MA-Information", "5.3.66"),
    ("NGAP-Cause", "5.3.72"),
    ("Wireline-User-Location-Info", "5.3.75"),
]

CORRECTIONS = [
    Correction(
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; table"
        " 5.3.0.1 marks the V flag mandatory for it, as for every other AVP"
        " the specification defines",
        versions="18.4.0",
    )
    for name, section in _VENDORLESS
] + [
    Delete(
        target=enum_value("Specific-Action", "Void", value=value),
        expect=ast.EnumValue(name="Void", value=value),
        reason="clause 5.3.13 prints 'Void' as the label of values 0 and 5 —"
        " a 3GPP editorial placeholder for removed values, not an enumerated"
        " value a dictionary can carry, and one name cannot label two values",
        versions="18.4.0",
    )
    for value in (0, 5)
]

CORRECTIONS += [
    Correction(
        target=reused_row("Framed-Ipv6-Prefix", section="5.4.0"),
        field="name",
        expect="Framed-Ipv6-Prefix",
        replace="Framed-IPv6-Prefix",
        reason="table 5.4.0.1 lower-cases the 'v'; RFC 4005, which defines"
        " the AVP, spells 'IPv6'",
        versions="18.4.0",
    )
]
