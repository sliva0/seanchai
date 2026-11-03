"""Corrections for 3GPP TS 29.217 — see docs/corrections.md."""

from seanchai.dad.corrections import (
    Accept,
    Correction,
    definition,
    value_row,
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

# The codes clauses say are defined elsewhere, as the registry allocates them.
CORRECTIONS += [
    Accept(
        id="pending-transaction-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_PENDING_TRANSACTION"),
        expect="DIAMETER_PENDING_TRANSACTION (code 4144) is listed here, but TS29.230 "
        "table 8.1.3 allocates the code to TS29.212",
        reason="clause 5.5.4 says 'As an addition the following "
        "Experimental-Result-Code value defined in 3GPP TS 29.212 [14] is "
        "applicable:': the document lists a code it re-uses",
        versions="18.0.0..19.0.0",
    ),
]
