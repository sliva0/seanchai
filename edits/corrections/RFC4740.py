"""Corrections for RFC 4740 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_rule, header

CORRECTIONS = [
    Correction(
        id="bases-rfc4590",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4590"),
        reason=(
            "clause 9.5.6 lists the Digest-* AVPs, and clause 9.8 SIP-AOR, as "
            "RADIUS attributes imported from RFC 4590, in no table of this "
            "document"
        ),
    ),
    *(
        Correction(
            id=f"digest-qop-case-{parent.lower()}",
            target=avp_rule(parent, "Digest-QoP"),
            field="name",
            expect="Digest-QoP",
            replace="Digest-Qop",
            reason=f"the {parent} ABNF (clause {clause}) capitalizes the P; RFC"
            " 4590 clause 3.8 defines Digest-Qop, and verified erratum 6028"
            " corrects the spelling throughout this document",
        )
        for parent, clause in (
            ("SIP-Authenticate", "9.5.3"),
            ("SIP-Authorization", "9.5.4"),
            ("SIP-Authentication-Info", "9.5.5"),
        )
    ),
]

# The application id prose states; the command headers omit it.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter Session Initiation Protocol (SIP) Application",
            source=ast.SourceRef(section="13.1", page=64),
            application_id=6,
            applies_to=("8.*",),
        ),
        after=None,
        reason=(
            "clause 13.1 records ID value 6 for the 'Diameter Session "
            "Initiation Protocol (SIP) Application', the value clause 7 says "
            "Auth-Application-Id advertises; clause 8's twelve commands print "
            "no id in their headers"
        ),
    ),
]
