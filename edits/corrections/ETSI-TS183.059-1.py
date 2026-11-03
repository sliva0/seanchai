"""Corrections for ETSI TS 183 059-1 — see docs/corrections.md.

The input is the transcription (`raw/etsi/ts18305901-020101.raw.dad`), which
records what the PDF prints."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    avp_rule,
    reused_avps,
    reused_row,
)

_CLAUSE = {
    "Push-Notification-Request": "7.1.1",
    "User-Data-Request": "7.1.3",
    "User-Data-Answer": "7.1.4",
}

_ID_CASE = [
    (
        "Logical-Access-Id",
        "Logical-Access-ID",
        "clause 7.3.1 heads the AVP Logical-Access-ID, as ES 283 034 clause 7.3.3 does",
        ("Push-Notification-Request", "User-Data-Request", "User-Data-Answer"),
    ),
    (
        "Physical-Access-Id",
        "Physical-Access-ID",
        "clause 7.3.2 heads the AVP Physical-Access-ID, as ES 283 034 clause 7.3.14"
        " does",
        ("Push-Notification-Request", "User-Data-Answer"),
    ),
]

CORRECTIONS = [
    Insert(
        id="globally-unique-address-reused",
        into=reused_avps("7.3"),
        node=ast.ReusedAvpRow(
            name="Globally-Unique-Address",
            origin="ETSI-ES283.034",
            code=300,
            data_type=ast.DataType.GROUPED,
        ),
        after=None,
        reason="clauses 7.1.1, 7.1.3 and 7.1.4 list the AVP and table 7.3 omits"
        " it, and the document defines it nowhere; clause 7.1 re-uses the commands"
        " of ES 283 034 [9], whose table 10 gives it code 300 and type Grouped and"
        " whose clause 7.3.1 defines it, and clause 5.2.1.2 describes its members",
        versions="2.1.1",
    ),
] + [
    Correction(
        id=f"{printed.lower()}-row-case",
        target=reused_row(printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"table 7.3 lower-cases the 'D'; {why}",
        versions="2.1.1",
    )
    for printed, spelled, why, _ in _ID_CASE
]

CORRECTIONS += [
    Correction(
        id=f"{command.lower()}-{printed.lower()}-case",
        target=avp_rule(command, printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"the format of clause {_CLAUSE[command]} lower-cases the 'D'; {why}",
        versions="2.1.1",
    )
    for printed, spelled, why, commands in _ID_CASE
    for command in commands
]
