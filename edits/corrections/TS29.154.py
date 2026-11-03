"""Corrections for 3GPP TS 29.154 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, definition, header

# Every grouped-AVP clause prints `< AVP Header: nnn >` with no vendor-id,
# while clauses 5.3.1 and A.6.3.1 set "the Vendor-Id header of all AVPs
# defined in the present document" to 10415 and tables 5.3.1.1 and
# A.6.3.1-1 mark the V flag mandatory.
_VENDORLESS = [
    ("Time-window", "5.3.5"),
    ("Transfer-Policy", "5.3.8"),
    ("Access-Network-Reports", "A.6.3.2"),
    ("Event-Configuration", "A.6.3.3"),
    ("Event-Configuration-Status", "A.6.3.5"),
    ("Event-Reports", "A.6.3.7"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; the"
        " document gives every AVP it defines vendor 10415 and its AVP"
        " table marks the V flag mandatory",
        versions="18.0.0..19.0.0",
    )
    for name, section in _VENDORLESS
] + [
    Correction(
        id="time-window-rule-case",
        target=definition("Time-window", section="5.3.5"),
        field="name",
        expect="Time-window",
        replace="Time-Window",
        reason="the clause 5.3.5 rule lower-cases the 'w'; its heading, table"
        " 5.3.1.1 and the Transfer-Policy and BTR bodies spell Time-Window",
        versions="18.0.0..19.0.0",
    ),
]

# A required member of the ECR (clause A.6.6.2) that nothing defines
# (docs/linter.md#standing-findings).
CORRECTIONS += [
    Insert(
        id="undefined-external-group-identifier",
        into=header(),
        node=ast.UndefinedAvp(
            name="External-Group-Identifier",
            source=ast.SourceRef(section="A.6.6.2"),
            note='A.4.1 "the SCEF shall send an Event-Configuration-Request'
            " (ECR) command to the PCRF including the Event-Configuration AVP"
            ' and the External-Group-Identifier AVP"',
        ),
        after=None,
        reason="a required member of the ECR (A.6.6.2) that no clause"
        " defines and table A.6.4.1-1 does not list, in V18.0.0 as in"
        " V19.0.0; CR 0022r1 (V15.1.0) added group event configuration and"
        " CR 0023 (CP-182026, V15.2.0), 'Missing re-used AVP for Nta', did"
        " not add it; the TS 29.230 registry allocates no such name and"
        " Wireshark's dictionary has no such AVP. Most likely meant: TS"
        " 29.336's External-Identifier (3111, UTF8String), which 'shall"
        " contain an external identifier for an individual UE or a group of"
        " UEs' on S6t, and which table A.6.4.1-1 re-uses as 'External"
        " Identifier of the UE'; but this document names a separate AVP in"
        " its ABNF and prose and uses External-Identifier per UE in the ERR,"
        " so reading one as the other is a guess at another document's"
        " intent",
        versions="18.0.0..19.0.0",
    ),
]
