"""Corrections for ETSI ES 283 034 — see docs/corrections.md.

The input is the transcription (`raw/etsi/es283034-020200.raw.dad`),
which records what the PDF prints."""

from seanchai.dad.corrections import Correction, avp_rule, definition, table_row

# The UDA and PNR ABNFs (clauses 7.1.2, 7.1.3) spell two AVPs with a
# lower-case "d"; table 10 prints Physical-Access-ID as clause 7.3.14 does,
# and clause 7.3.3 heads and defines Logical-Access-ID, the spelling every
# citing document (TS 29.212, 29.219, 29.273, 32.299) uses.
_ID_CASE = [
    ("Logical-Access-Id", "Logical-Access-ID", "7.3.3"),
    ("Physical-Access-Id", "Physical-Access-ID", "7.3.14"),
]

CORRECTIONS = [
    Correction(
        id="logical-access-id-row-case",
        target=table_row("Logical-Access-Id", table="10"),
        field="name",
        expect="Logical-Access-Id",
        replace="Logical-Access-ID",
        reason="table 10 lower-cases the 'D'; clause 7.3.3 heads and defines"
        " the AVP as Logical-Access-ID",
        versions="2.2.0",
    ),
] + [
    Correction(
        id=f"{command.lower()}-{printed.lower()}-case",
        target=avp_rule(definition(command), printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"the {abbreviation} ABNF (clause {section}) lower-cases the"
        f" 'D'; clause {clause} heads and defines the AVP as {spelled}",
        versions="2.2.0",
    )
    for command, abbreviation, section in [
        ("User-Data-Answer", "UDA", "7.1.2"),
        ("Push-Notification-Request", "PNR", "7.1.3"),
    ]
    for printed, spelled, clause in _ID_CASE
]

CORRECTIONS += [
    Correction(
        id="uda-qos-profile-description-case",
        target=avp_rule("User-Data-Answer", "Qos-Profile-Description"),
        field="name",
        expect="Qos-Profile-Description",
        replace="QoS-Profile-Description",
        reason="the UDA ABNF (clause 7.1.2) prints 'Qos'; clause 7.3.5, table"
        " 10 and the PNR ABNF spell QoS-Profile-Description",
        versions="2.2.0",
    ),
] + [
    Correction(
        id=f"globally-unique-address-{printed.lower()}",
        target=avp_rule("Globally-Unique-Address", printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"clause 7.3.1's AVP format prints {printed}, which nothing"
        f" defines; table 12 imports {spelled} from RFC 4005 and clause"
        f" {clause} names it, and TS 183 017 clause 7.3.10 re-prints the"
        f" body with {spelled}",
        versions="2.2.0",
    )
    for printed, spelled, clause in [
        ("Frame-IP-Address", "Framed-IP-Address", "7.3.17"),
        ("Frame-IPv6-Prefix", "Framed-IPv6-Prefix", "7.3.18"),
    ]
]
