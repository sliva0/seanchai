"""Corrections for 3GPP TS 29.336 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    Insert,
    avp_rule,
    definition,
    reused_avps,
    reused_row,
    table_row,
)

CORRECTIONS = [
    Delete(
        id="user-identifier-duplicate-body",
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
        id="scheduled-communication-time-case",
        target=definition("Scheduled-communication-time", section="8.4.30"),
        field="name",
        expect="Scheduled-communication-time",
        replace="Scheduled-Communication-Time",
        reason="clause 8.4.30's heading and rule lowercase the name; table"
        " 8.4.1-1 and the Monitoring-Event-Configuration ABNF (clause 8.4.24)"
        " both spell the AVP at code 3118 'Scheduled-Communication-Time'",
        versions="18.2.0",
    ),
    Correction(
        id="periodic-time-case",
        target=table_row("Periodic-time"),
        field="name",
        expect="Periodic-time",
        replace="Periodic-Time",
        reason="table 8.4.1-1 and clause 8.4.29's heading lowercase the name;"
        " both ABNFs that carry the AVP (Location-Information-Configuration,"
        " clause 8.4.15, and Communication-Pattern-Set, clause 8.4.26) and"
        " clause 8.4.29's own prose spell the AVP at code 3117 'Periodic-Time',"
        " as does Wireshark's dictionary. The same clause-body lowercasing"
        " appears on Scheduled-Communication-Time and"
        " Periodic-communication-indicator, so it is this document's typo"
        " pattern, not a name",
        versions="18.2.0",
    ),
    # The S6m Serving-Node and Additional-Serving-Node bodies (clauses
    # 6.4.12, 6.4.13) use six member AVPs that table 6.4.1/2 does not list,
    # though it lists the two grouped AVPs themselves and their origin's
    # other members (LMSI). TS 29.173 defines five of the six and itself
    # re-uses SGSN-Number from TS 29.272.
    *(
        Insert(
            id=f"missing-row-{name.lower()}",
            into=reused_avps("6.4.1/2"),
            node=ast.ReusedAvpRow(name=name, origin=origin),
            after=after,
            reason="the Serving-Node and Additional-Serving-Node bodies"
            f" (clauses 6.4.12, 6.4.13) use {name} but table 6.4.1/2 omits"
            f" the row; {origin} defines the AVP",
            versions="18.2.0",
        )
        for (name, origin), after in zip(
            (
                ("MME-Name", "TS29.173"),
                ("MME-Realm", "TS29.173"),
                ("MSC-Number", "TS29.173"),
                ("SGSN-Name", "TS29.173"),
                ("SGSN-Realm", "TS29.173"),
                ("SGSN-Number", "TS29.272"),
            ),
            (
                "Additional-Serving-Node",
                "MME-Name",
                "MME-Realm",
                "MSC-Number",
                "SGSN-Name",
                "SGSN-Realm",
            ),
            strict=True,
        )
    ),
]

# TS 29.217, which defines both AVPs, spells them eNodeB-Id and
# Extended-eNodeB-Id in its table 5.3.1.1, the defining clauses and its
# Congestion-Location-Id body; this document's re-used table and the
# MME-Location-Information body (clause 8.4.34) capitalise the D.
CORRECTIONS += [
    correction
    for printed, name, clause in (
        ("eNodeB-ID", "eNodeB-Id", "5.3.10"),
        ("Extended-eNodeB-ID", "Extended-eNodeB-Id", "5.3.15"),
    )
    for correction in (
        Correction(
            id=f"{name.lower()}-row-spelling",
            target=reused_row(printed),
            field="name",
            expect=printed,
            replace=name,
            reason=f"the re-used row cites TS 29.217, which defines {name}"
            f" (clause {clause})",
            versions="18.2.0",
        ),
        Correction(
            id=f"{name.lower()}-in-mme-location-information",
            target=avp_rule("MME-Location-Information", printed),
            field="name",
            expect=printed,
            replace=name,
            reason="the MME-Location-Information body (clause 8.4.34) uses the"
            f" re-used row's spelling; TS 29.217 defines {name}",
            versions="18.2.0",
        ),
    )
]

# TS 29.154, which defines the AVP (clause 5.3.10, code 4209), capitalises
# "Of" in its table 5.3.1.1, clause and BTA body.
CORRECTIONS += [
    Correction(
        id="number-of-ues-row-spelling",
        target=reused_row("Number-of-UEs"),
        field="name",
        expect="Number-of-UEs",
        replace="Number-Of-UEs",
        reason="the re-used row cites TS 29.154, which defines Number-Of-UEs"
        " (clause 5.3.10)",
        versions="18.2.0",
    ),
    Correction(
        id="cia-number-of-ues-spelling",
        target=avp_rule("Configuration-Information-Answer", "Number-of-UEs"),
        field="name",
        expect="Number-of-UEs",
        replace="Number-Of-UEs",
        reason="the CIA ABNF (clause 8.2.4) uses the re-used row's spelling;"
        " TS 29.154 clause 5.3.10 defines Number-Of-UEs",
        versions="18.2.0",
    ),
]
