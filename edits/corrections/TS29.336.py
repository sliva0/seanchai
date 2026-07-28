"""Corrections for 3GPP TS 29.336 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Delete, definition

CORRECTIONS = [
    Delete(
        target=definition("User-Identifier", section="8.4.36"),
        expect=ast.GroupedAvp(
            name="User-Identifier",
            source=ast.SourceRef(section="8.4.36", page=65),
            code=3102,
            vendor_id=10415,
            avps=(
                ast.AvpRule(name="User-Name", presence=ast.Presence.OPTIONAL),
                ast.AvpRule(name="MSISDN", presence=ast.Presence.OPTIONAL),
                ast.AvpRule(name="External-Identifier", presence=ast.Presence.OPTIONAL),
                ast.AvpRule(
                    name="Type-Of-External-Identifier",
                    presence=ast.Presence.OPTIONAL,
                ),
                ast.AvpRule(
                    name="AVP",
                    presence=ast.Presence.OPTIONAL,
                    min_occurs=0,
                    max_occurs=None,
                ),
            ),
        ),
        reason="clause 8.4.36 opens with 'This AVP is defined in clause"
        " 6.4.2' and then prints a second, S6t-specific format for the same"
        " (vendor 10415, code 3102) identity — swapping 6.4.2's LMSI member"
        " for Type-Of-External-Identifier. One identity cannot carry two"
        " bodies in a dictionary, and the document's own words make 6.4.2"
        " the definition, which table 8.4.1-2's re-used row also cites; the"
        " S6t variant stays readable in the source behind that row's clause"
        " pointer",
        versions="18.2.0",
    ),
    Correction(
        target=definition("Scheduled-communication-time", section="8.4.30"),
        field="name",
        expect="Scheduled-communication-time",
        replace="Scheduled-Communication-Time",
        reason="clause 8.4.30's heading and rule lowercase the name; table"
        " 8.4.1-1 and the Monitoring-Event-Configuration ABNF (clause 8.4.24)"
        " both spell the AVP at code 3118 'Scheduled-Communication-Time'",
        versions="18.2.0",
    ),
]
