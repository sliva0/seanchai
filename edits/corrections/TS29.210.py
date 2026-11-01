"""Corrections for 3GPP TS 29.210 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, application_scope, definition

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

# Clause 6 holds two applications, each stating its id in its own subclause,
# so the interface clause the extractor reads for a statement is too wide:
# the commands of 6.1.1-6.1.4 are Gx's alone, clause 6.2 printing none.
CORRECTIONS += [
    Correction(
        id="applies-to-gx",
        target=application_scope("Gx"),
        field="applies_to",
        expect=("6.*",),
        replace=("6.1.*",),
        reason="clause 6.1 states 16777224 for 'the Gx Application' and says it"
        " 'shall be included in the Auth-Application-Id AVP for the CCR, CCA"
        " and RAR commands' it prints in 6.1.1-6.1.4; clause 6.2 states another"
        " id for the Gx over Gy Application",
        versions="6.7.0",
    ),
    Correction(
        id="applies-to-gx-over-gy",
        target=application_scope("Gx over Gy"),
        field="applies_to",
        expect=("6.*",),
        replace=("6.2.*",),
        reason="clause 6.2 states 16777225 for 'the Gx over Gy Application',"
        " which clause 6.1's commands do not belong to",
        versions="6.7.0",
    ),
]
