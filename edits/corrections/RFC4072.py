"""Corrections for RFC 4072 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_rule, header

CORRECTIONS = [
    *(
        Correction(
            id=f"dea-framed-appletalk-{suffix.lower()}-case",
            target=avp_rule("Diameter-EAP-Answer", f"Framed-Appletalk-{suffix}"),
            field="name",
            expect=f"Framed-Appletalk-{suffix}",
            replace=f"Framed-AppleTalk-{suffix}",
            reason="the DEA ABNF and the section 4.1 occupancy table lowercase"
            " the T of NASREQ's AVP; RFC 4005 clauses 6.13.1-6.13.3 define the"
            " three as Framed-AppleTalk-*, corrected the same way there",
        )
        for suffix in ("Link", "Network", "Zone")
    ),
    Correction(
        id="bases-nasreq",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4005"),
        reason=(
            "the DER/DEA ABNFs reference thirty-odd NASREQ AVPs (Callback-Id, the "
            "Framed- and NAS- families, Service-Type, Tunneling) without a re-used "
            "table; RFC 4072 is the EAP application of NASREQ and its normative "
            "references cite RFC 4005 for them"
        ),
    ),
]

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter EAP",
            source=ast.SourceRef(section="2.1", page=3),
            application_id=5,
            applies_to=("3.*",),
        ),
        after=None,
        reason=(
            "clause 2.1 advertises 'the Diameter EAP Application ID value of "
            "5', and the IANA considerations (clause 7) allocate it; the "
            "DER/DEA headers print none"
        ),
    ),
]
