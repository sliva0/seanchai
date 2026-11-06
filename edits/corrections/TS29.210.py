"""Corrections for 3GPP TS 29.210 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    avp_table,
    definition,
)

# Four grouped-AVP clauses print `< AVP Header: nnn >` with no vendor-id
# where clause 5.2 says "The Vendor-Id header of all AVPs defined in the
# present document shall be set to 3GPP (10415)" and table 5.2 marks V
# mandatory.
_VENDORLESS = [
    ("Charging-Rule-Install", "5.2.2"),
    ("Charging-Rule-Remove", "5.2.3"),
    ("Charging-Rule-Definition", "5.2.4"),
    ("TFT-Packet-Filter-Information", "5.2.19"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause 5.2"
        " sets the Vendor-Id header of every AVP the document defines to 3GPP"
        " (10415), and table 5.2 marks the V flag mandatory",
        versions="6.7.0",
    )
    for name, section in _VENDORLESS
]

# Table 5.3 prints no flag cells; the paragraph above it states them for every
# re-used 3GPP Radius VSA. TS 29.061 V6.15.0's table 10 states the same for the
# other three table 5.3 lists, and nothing of these two, so they get rows here,
# the document's only AVP table, for the citing table's flags to hold. Their type
# stays blank: no document of Release 6 states one (corpus.RELEASE_FILLS).
CORRECTIONS += [
    Insert(
        id=f"{name.lower()}-flags",
        into=avp_table("5.2"),
        node=ast.AvpTableRow(
            name=name,
            code=code,
            section="5.3",
            flag_rules=ast.AvpFlagRules(
                must=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}),
                may=frozenset({ast.AvpFlag.PROTECTED}),
            ),
        ),
        after=after,
        reason="clause 5.3 has a re-used 3GPP Radius VSA translated as RFC 4005 [12]"
        " describes, except that the M flag 'shall be set' and the P flag 'may be"
        " set'; RFC 4005 clause 9.6.2 gives V=1, and table 5.3 lists"
        f" {name}, which TS 29.061 V6.15.0 clause 16.4.7 numbers {code} among the"
        " VSAs and tabulates nowhere. The row states those flags and clause"
        " 16.4.7's code",
        versions="6.7.0",
        drawn_from="clause 5.3, its code from TS 29.061 V6.15.0 clause 16.4.7",
    )
    for name, code, after in (
        ("3GPP-GPRS-Negotiated-QoS-Profile", 5, "ToS-Traffic-Class"),
        ("3GPP-SGSN-MCC-MNC", 18, "3GPP-GPRS-Negotiated-QoS-Profile"),
    )
]
