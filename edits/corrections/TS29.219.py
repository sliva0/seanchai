"""Corrections for 3GPP TS 29.219 — see docs/corrections.md."""

from seanchai.dad.corrections import (
    Correction,
    definition,
    information_elements,
    reused_row,
)

# The two grouped-AVP clauses print `< AVP Header: nnn >` with no vendor-id,
# while clause 5.3.0 sets "the Vendor-Id header of all AVPs defined in the
# present document" to 10415 and table 5.3.0.1 marks the V flag mandatory.
_VENDORLESS = [
    ("Policy-Counter-Status-Report", "5.3.3"),
    ("Pending-Policy-Counter-Information", "5.3.5"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; clause"
        " 5.3.0 gives every AVP the document defines vendor 10415 and table"
        " 5.3.0.1 marks the V flag mandatory",
        versions="18.0.0..19.0.0",
    )
    for name, section in _VENDORLESS
]

# Clause 2 [17] prints "ETSI TS 283 034 v2.2.0"; ETSI publishes it as ES 283 034.
CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-etsi-standard",
        target=reused_row(name),
        field="origin",
        expect="ETSI-TS283.034",
        replace="ETSI-ES283.034",
        reason="table 5.4 cites [17], 'ETSI TS 283 034 v2.2.0'; ETSI publishes that"
        " title and version as ES 283 034, and has no TS 283 034",
        versions="19.0.0",
    )
    for name in ("Logical-Access-ID", "Physical-Access-ID")
]

# Clauses 4.5.1.1 and 4.5.2.1 map their procedures to the commands by their
# headings' names; clauses 5.6.2-5.6.5 print the rules, which the corpus names
# the commands by, abbreviated.
_RULES = (
    ("4.5.1.1/1", "Spending-Limit-Request", "SL-Request", "5.6.2", "SLR"),
    ("4.5.1.1/2", "Spending-Limit-Answer", "SL-Answer", "5.6.3", "SLA"),
    ("4.5.2.1/1", "Spending-Status-Notification-Request", "SN-Request", "5.6.4", "SNR"),
    ("4.5.2.1/2", "Spending-Status-Notification-Answer", "SN-Answer", "5.6.5", "SNA"),
)

CORRECTIONS += [
    Correction(
        id=f"elements-command-{rule.lower()}",
        target=information_elements(label),
        field="command",
        expect=printed,
        replace=rule,
        reason=f"clause {clause} heads the command '{printed} ({abbreviation})"
        f" command' and prints its rule <{rule}>, the name the corpus gives it;"
        " the procedure's sentence names the heading's",
        versions="19.0.0",
    )
    for label, printed, rule, clause, abbreviation in _RULES
]
