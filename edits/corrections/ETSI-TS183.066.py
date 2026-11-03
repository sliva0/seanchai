"""Corrections for ETSI TS 183 066 — see docs/corrections.md.

The input is the transcription (`raw/etsi/ts183066-020101.raw.dad`), which
records what the PDF prints."""

from seanchai.dad.corrections import Correction, avp_rule, reused_row

_CLAUSE = {
    "User-Data-Request": "7.1.1",
    "User-Data-Answer": "7.1.2",
    "Push-Notification-Request": "7.1.3",
}

CORRECTIONS = [
    Correction(
        id="logical-access-id-row-case",
        target=reused_row("Logical-Access-Id"),
        field="name",
        expect="Logical-Access-Id",
        replace="Logical-Access-ID",
        reason="table 7.3 lower-cases the 'D'; ES 283 034 clause 7.3.3, which it"
        " cites, heads and defines the AVP as Logical-Access-ID, and clauses 5.2.1.2"
        " and 5.2.2.2 write Logical-Access-ID AVP",
        versions="2.1.1",
    ),
] + [
    Correction(
        id=f"{command.lower()}-{printed.lower()}-case",
        target=avp_rule(command, printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"the format of clause {_CLAUSE[command]} lower-cases the 'D'; {why}",
        versions="2.1.1",
    )
    for printed, spelled, why, commands in [
        (
            "Logical-Access-Id",
            "Logical-Access-ID",
            "ES 283 034 clause 7.3.3 heads and defines the AVP as Logical-Access-ID",
            ("User-Data-Request", "User-Data-Answer", "Push-Notification-Request"),
        ),
        (
            "Physical-Access-Id",
            "Physical-Access-ID",
            "table 7.3 and ES 283 034 clause 7.3.14 spell Physical-Access-ID",
            ("User-Data-Answer", "Push-Notification-Request"),
        ),
    ]
    for command in commands
]
