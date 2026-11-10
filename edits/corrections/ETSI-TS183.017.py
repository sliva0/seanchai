"""Corrections for ETSI TS 183 017 — see docs/corrections.md.

The input is the transcription (`raw/etsi/ts183017-030201.raw.dad`),
which records what the PDF prints. The document's clause headings
sentence-case AVP names ("Port-number AVP", "Flow-description AVP"), so a
clause's defining sentence and the ABNFs are what name an AVP here."""

from seanchai.dad.corrections import (
    Accept,
    Correction,
    avp_rule,
    definition,
    enum_value,
    reused_row,
    table_row,
)

# Table 7.3.1 sentence-cases names the defining sentences and ABNFs spell
# otherwise: (printed, spelled, clause, where else the spelling stands).
_TABLE_CASE = [
    ("Binding-information", "Binding-Information", "7.3.1", "the AAR and AAA ABNFs"),
    ("Binding-input-list", "Binding-Input-List", "7.3.2", "its own AVP format"),
    ("Binding-output-list", "Binding-Output-List", "7.3.3", "its own AVP format"),
    (
        "V6-transport-address",
        "V6-Transport-Address",
        "7.3.4",
        "the Binding-Input-List and Binding-Output-List formats",
    ),
    (
        "V4-transport-address",
        "V4-Transport-Address",
        "7.3.5",
        "the Binding-Input-List and Binding-Output-List formats",
    ),
    ("Port-number", "Port-Number", "7.3.6", "the transport address formats"),
    (
        "Latching-indication",
        "Latching-Indication",
        "7.3.8",
        "the AAR ABNF",
    ),
    (
        "Reservation-priority",
        "Reservation-Priority",
        "7.3.9",
        "the AAR, AAA and Media-Component-Description formats",
    ),
]

# Groups printing no vendor-id where table 7.3.3's paragraph says "The
# Vendor-Id header of these AVPs shall be set to 3GPP (10415)".
_GQ_GROUPS = [
    ("Flow-Grouping", "7.3.18"),
    ("Flows", "7.3.20"),
    ("Media-Component-Description", "7.3.26"),
    ("Media-Sub-Component", "7.3.28"),
]

CORRECTIONS = (
    [
        Correction(
            id=f"{printed.lower()}-row-case",
            target=table_row(printed, table="7.3.1"),
            field="name",
            expect=printed,
            replace=spelled,
            reason=f"table 7.3.1 sentence-cases the name; clause {clause}'s"
            f" defining sentence and {elsewhere} spell {spelled}",
            versions="3.2.1",
        )
        for printed, spelled, clause, elsewhere in _TABLE_CASE
    ]
    + [
        Correction(
            id="reservation-class-row-case",
            target=table_row("Reservation-class", table="7.3.1"),
            field="name",
            expect="Reservation-class",
            replace="Reservation-Class",
            reason="table 7.3.1 and clause 7.3.7's sentence print"
            " Reservation-class; the clause's heading, which unlike its"
            " neighbours' capitalises the name, and the Media-Component-"
            "Description format (7.3.26) spell Reservation-Class",
            versions="3.2.1",
        ),
        Correction(
            id="binding-information-rule-case",
            target=definition("Binding-information"),
            field="name",
            expect="Binding-information",
            replace="Binding-Information",
            reason="clause 7.3.1's AVP format names the rule Binding-information;"
            " its defining sentence and the AAR and AAA ABNFs spell"
            " Binding-Information",
            versions="3.2.1",
        ),
    ]
    + [
        Correction(
            id=f"{spelled.lower()}-rule-name",
            target=definition("Transport-Address", section=clause),
            field="name",
            expect="Transport-Address",
            replace=spelled,
            reason=f"clause {clause}'s AVP format names the rule Transport-Address,"
            f" as clause {other}'s does; its heading, its defining sentence (AVP"
            f" code {code}) and table 7.3.1 name {spelled}",
            versions="3.2.1",
        )
        for spelled, clause, other, code in [
            ("V6-Transport-Address", "7.3.4", "7.3.5", 453),
            ("V4-Transport-Address", "7.3.5", "7.3.4", 454),
        ]
    ]
    + [
        Correction(
            id="abort-cause-name",
            target=definition("Session-Abort-Cause"),
            field="name",
            expect="Session-Abort-Cause",
            replace="Abort-Cause",
            reason="clause 7.3.14's sentence names the AVP Session-Abort-Cause;"
            " its heading, table 7.3.3 (code 500) and the RAR and ASR ABNFs name"
            " Abort-Cause",
            versions="3.2.1",
        ),
        Correction(
            id="sip-forking-indication-name",
            target=definition("SIP_Forking"),
            field="name",
            expect="SIP_Forking",
            replace="SIP-Forking-Indication",
            reason="clause 7.3.32's sentence names the AVP SIP_Forking; its"
            " heading, table 7.3.3 (code 523) and the AAR ABNF name"
            " SIP-Forking-Indication",
            versions="3.2.1",
        ),
    ]
    + [
        Correction(
            id=f"vendor-id-{name.lower()}",
            target=definition(name, section=section),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason=f"clause {section}'s AVP format omits the vendor-id; the"
            " paragraph before table 7.3.3, which lists the AVP, says 'The"
            " Vendor-Id header of these AVPs shall be set to 3GPP (10415)'",
            versions="3.2.1",
        )
        for name, section in _GQ_GROUPS
    ]
    + [
        Correction(
            id=f"overbooking-indicator-value-{value}-name",
            target=enum_value(
                "Overbooking-indicator", "Overbooking-indicator", value=value
            ),
            field="name",
            expect="Overbooking-indicator",
            replace=label,
            reason="clause 7.3.35 labels both values with the AVP's own name and"
            f" says what each means; value {value} takes its meaning as its"
            " label, as a value printed with no name takes its description",
            versions="3.2.1",
        )
        for value, label in [
            (0, "no overbooking mode is required"),
            (1, "overbooking is mode required"),
        ]
    ]
)

CORRECTIONS += [
    Correction(
        id="logical-access-id-reused-row-case",
        target=reused_row("Logical-Access-Id"),
        field="name",
        expect="Logical-Access-Id",
        replace="Logical-Access-ID",
        reason="table 7.3.2 lower-cases the 'D'; clause 7.3.39, which it"
        " cites, and ES 283 034 clause 7.3.3 name Logical-Access-ID",
        versions="3.2.1",
    ),
    Correction(
        id="rar-logical-access-id-case",
        target=avp_rule("RA-Request", "Logical-Access-Id"),
        field="name",
        expect="Logical-Access-Id",
        replace="Logical-Access-ID",
        reason="the RAR ABNF (clause 7.1.3) lower-cases the 'D'; clause"
        " 7.3.39 names Logical-Access-ID",
        versions="3.2.1",
    ),
] + [
    Correction(
        id=f"asa-{printed.lower()}",
        target=avp_rule("AS-Answer", printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"the ASA ABNF (clause 7.1.8) prints {printed}, which nothing"
        f" defines; the STA ABNF (7.1.6) lists the same three members as"
        f" RFC 3588's {spelled}",
        versions="3.2.1",
    )
    for printed, spelled in [
        ("Redirected-Host", "Redirect-Host"),
        ("Redirected-Host-Usage", "Redirect-Host-Usage"),
        ("Redirected-Max-Cache-Time", "Redirect-Max-Cache-Time"),
    ]
]

# Resolved to TS 29.209 V6.8.0, the version clause 2's [4] names
# ("3GPP TS 29.209 Release 6"; corpus.toml, cited_version), the re-printed Gq
# AVPs are compared with it.
CORRECTIONS += [
    Accept(
        id="media-component-description-extension",
        rule="reused-extension",
        target=definition("Media-Component-Description"),
        expect="Media-Component-Description's body, against TS29.209's"
        " definition: extended, adding Codec-Data, Media-Authorization-Context-Id,"
        " Reservation-Class, Reservation-Priority, Transport-Class",
        reason="table 7.3.3 NOTE 3: 'The AVP was initially defined in the Gq"
        " specification TS 129 209 [4]. The present document provides updated"
        " syntax to some of those AVP in the form of optional AVPs that have"
        " been added to the Grouped AVP syntax.'",
        versions="3.2.1",
    )
]
