"""Corrections for 3GPP TS 29.217 — see docs/corrections.md."""

from seanchai.dad.corrections import (
    Correction,
    definition,
)

# The four grouped-AVP clauses print `< AVP Header: nnn >` with no vendor-id,
# while clause 5.3.1 sets "the Vendor-Id header of all AVPs defined in the
# present document" to 10415 and table 5.3.1.1 marks the V flag mandatory.
_VENDORLESS = [
    ("Aggregated-Congestion-Info", "5.3.2"),
    ("Aggregated-RUCI-Report", "5.3.3"),
    ("Congestion-Level-Definition", "5.3.4"),
    ("Congestion-Location-Id", "5.3.8"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause"
        " 5.3.1 gives every AVP the document defines vendor 10415 and table"
        " 5.3.1.1 marks the V flag mandatory",
        versions="18.0.0..19.0.0",
    )
    for name, section in _VENDORLESS
]
