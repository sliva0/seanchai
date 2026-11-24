"""Corrections for 3GPP TS 29.561 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, header, reused_avps

CORRECTIONS = [
    Correction(
        id="bases-nasreq-eap",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC7155", "RFC4072"),
        reason="clause 12.6.1 names the bodies' other AVPs 'as defined in IETF RFC"
        " 4072 [25] and IETF RFC 7155 [23]', and table 12.4-1 lists none of them",
        versions="19.6.0",
    ),
    Insert(
        id="application-id-eap",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter EAP",
            source=ast.SourceRef(section="12.1.1", page=58),
            application_id=5,
            applies_to=("12.6.2.*", "12.6.3.*"),
        ),
        after=None,
        reason="clause 12.1.1 advertises the NASREQ and EAP applications, 'the value"
        " (1 and 5) of the application identifier', and clauses 12.6.2 and 12.6.3"
        " say DER and DEA are 'defined in IETF RFC 4072 [25]', whose section 2.1"
        " gives five. The command headers print none",
        versions="19.6.0",
    ),
    Insert(
        id="application-id-nasreq",
        into=header(),
        node=ast.ApplicationScope(
            name="NASREQ",
            source=ast.SourceRef(section="12.1.1", page=58),
            application_id=1,
            applies_to=("12.6.4.*", "12.6.5.*"),
        ),
        after=None,
        reason="clause 12.1.1 advertises the NASREQ and EAP applications, 'the value"
        " (1 and 5) of the application identifier', and clauses 12.6.4 and 12.6.5"
        " say RAR and RAA are 'defined in IETF RFC 7155 [23]', whose section 1.5"
        " gives one. The command headers print none",
        versions="19.6.0",
    ),
    Insert(
        id="reused-delegated-ipv6-prefix",
        into=reused_avps("12.4-1"),
        node=ast.ReusedAvpRow(name="Delegated-IPv6-Prefix", origin="RFC4818"),
        after=None,
        reason="a member of the DER and DEA bodies (clauses 12.6.2, 12.6.3) in no"
        " table of this document; clause 2 cites RFC 4818 [10], 'RADIUS"
        " Delegated-IPv6-Prefix Attribute', whose clause 5 gives the attribute as"
        " an AVP its code, 123, its type and flag rules",
        versions="19.6.0",
    ),
]
