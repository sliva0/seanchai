"""Corrections for ETSI ES 283 026 — see docs/corrections.md.

The input is the transcription (`raw/etsi/es283026-010600.raw.dad`), which
records what the PDF prints."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Insert,
    avp_rule,
    definition,
    reused_avps,
)

# Groups printing no vendor-id where clause 6.4.2's paragraph says "The Vendor-Id
# header for these AVPs shall be set to 3GPP (10415)".
_GQ_GROUPS = [
    ("Flow-Grouping", "6.4.8"),
    ("Flows", "6.4.10"),
    ("Media-Component-Description", "6.4.16"),
    ("Media-Sub-Component", "6.4.18"),
]

CORRECTIONS = [
    Accept(
        id="specific-action-rq-events",
        rule="reused-body-differs",
        target=definition("Specific-Action"),
        expect="Specific-Action's body, against TS29.209's definition: adds"
        " INDICATION_OF_RESERVATION_EXPIRATION,"
        " INDICATION_OF_SUBSCRIBER_DETACHMENT, missing"
        " CHARGING_CORRELATION_EXCHANGE, INDICATION_OF_ESTABLISHMENT_OF_BEARER,"
        " INDICATION_OF_LOSS_OF_BEARER, INDICATION_OF_RECOVERY_OF_BEARER,"
        " SERVICE_INFORMATION_REQUEST",
        reason="clause 6.4.13 supports one event 'from TS 129 209 [7]', says 'the"
        " present document defines two new events', and of the rest that they 'are"
        " not relevant at the Rq interface and are not supported'",
        versions="1.6.0",
    ),
]

CORRECTIONS += (
    [
        Correction(
            id=f"{command.lower()}-auth-application-id-case",
            target=avp_rule(command, "Auth-Application-ID"),
            field="name",
            expect="Auth-Application-ID",
            replace="Auth-Application-Id",
            reason=f"the format of clause {clause} upper-cases the 'D'; RFC 3588 [11]"
            " defines Auth-Application-Id, and clause 6.1.1 and the RAR format (6.2.3)"
            " spell it so",
            versions="1.6.0",
        )
        for command, clause in [
            ("AA-Request", "6.2.1"),
            ("AA-Answer", "6.2.2"),
            ("ST-Request", "6.2.5"),
            ("AS-Request", "6.2.7"),
        ]
    ]
    + [
        Correction(
            id=f"asa-{printed.lower()}",
            target=avp_rule("AS-Answer", printed),
            field="name",
            expect=printed,
            replace=spelled,
            reason=f"the ASA format (clause 6.2.8) prints {printed}, which nothing"
            f" defines; the STA format (6.2.6) lists the same three members as RFC"
            f" 3588's {spelled}",
            versions="1.6.0",
        )
        for printed, spelled in [
            ("Redirected-Host", "Redirect-Host"),
            ("Redirected-Host-Usage", "Redirect-Host-Usage"),
            ("Redirected-Max-Cache-Time", "Redirect-Max-Cache-Time"),
        ]
    ]
    + [
        Correction(
            id=f"globally-unique-address-{printed.lower()}",
            target=avp_rule("Globally-Unique-Address", printed),
            field="name",
            expect=printed,
            replace=spelled,
            reason=f"clause 6.4.21's AVP format prints {printed}, as ES 283 034 clause"
            f" 7.3.1 does, which nothing defines; that document's table 12 imports"
            f" {spelled} from RFC 4005 and corrects its own format the same way",
            versions="1.6.0",
        )
        for printed, spelled in [
            ("Frame-IP-Address", "Framed-IP-Address"),
            ("Frame-IPv6-Prefix", "Framed-IPv6-Prefix"),
        ]
    ]
    + [
        Insert(
            id=f"{name.lower()}-reused",
            into=reused_avps("8"),
            node=ast.ReusedAvpRow(name=name, origin="RFC4005", code=code),
            after=None,
            reason="clause 6.4.21's format uses the AVP, as ES 283 034's does, and no"
            " table of the document lists it; ES 283 034 table 12, which clause 6.4.4"
            " follows for Globally-Unique-Address, imports it from RFC 4005, which is"
            " clause 2.1's [12]",
            versions="1.6.0",
        )
        for name, code in [("Framed-IP-Address", 8), ("Framed-IPv6-Prefix", 97)]
    ]
    + [
        Insert(
            id=f"{name.lower()}-reused",
            into=reused_avps("6"),
            node=ast.ReusedAvpRow(name=name, origin="TS29.209", code=code),
            after="Media-Type",
            reason="clause 6.4.16's Media-Component-Description format lists it and"
            " table 6 omits it, and the document defines it nowhere; TS 29.209, the"
            " source of the AVPs clause 6.4.2 imports, defines it",
            versions="1.6.0",
        )
        for name, code in [("RR-Bandwidth", 521), ("RS-Bandwidth", 522)]
    ]
    + [
        Correction(
            id=f"vendor-id-{name.lower()}",
            target=definition(name, section=section),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason=f"clause {section}'s AVP format omits the vendor-id; the paragraph"
            " before table 6, which lists the AVP, says 'The Vendor-Id header for these"
            " AVPs shall be set to 3GPP (10415)'",
            versions="1.6.0",
        )
        for name, section in _GQ_GROUPS
    ]
)
