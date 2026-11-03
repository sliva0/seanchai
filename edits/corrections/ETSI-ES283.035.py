"""Corrections for ETSI ES 283 035 — see docs/corrections.md.

The input is the transcription (`raw/etsi/es283035-020501.raw.dad`), which
records what the PDF prints. Table 6 and the commands name several AVPs of ES 283
034 otherwise than that document's V2.2.0, the only one the corpus holds and the
one clause 7.1 means by "commands defined in ES 283 034 [5]"."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    avp_rule,
    enum_value,
    reused_row,
)

# (printed, spelled, why); table 6 prints the first, third and fourth.
_LOGICAL = (
    "Logical-Access-Id",
    "Logical-Access-ID",
    "ES 283 034 clause 7.3.3 heads and defines the AVP as Logical-Access-ID, the"
    " spelling every citing document uses",
)
_PHYSICAL = (
    "Physical-Access-Id",
    "Physical-Access-ID",
    "table 6 and ES 283 034 clause 7.3.14 spell Physical-Access-ID",
)
_GATE = (
    "Initial-Gate-Setting",
    "Initial-Gate-Setting-Description",
    "ES 283 034 V2.2.0 table 10 gives code 303, which table 6 cites, as"
    " Initial-Gate-Setting-Description, and clause 7.3.4 defines it so",
)
_QOS = (
    "QoS-Profile",
    "QoS-Profile-Description",
    "ES 283 034 V2.2.0 table 10 gives code 304, which table 6 cites, as"
    " QoS-Profile-Description, and clause 7.3.5 defines it so",
)

CORRECTIONS = [
    Correction(
        id=f"{printed.lower()}-row-name",
        target=reused_row(printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"table 6 prints {printed}; {why}",
        versions="2.5.1",
    )
    for printed, spelled, why in (_LOGICAL, _GATE, _QOS)
]

CORRECTIONS += [
    Correction(
        id=f"{command.lower()}-{printed.lower()}-name",
        target=avp_rule(command, printed),
        field="name",
        expect=printed,
        replace=spelled,
        reason=f"the format of clause {clause} prints {printed}; {why}",
        versions="2.5.1",
    )
    for command, clause, (printed, spelled, why) in [
        ("User-Data-Answer", "7.1.2", _LOGICAL),
        ("User-Data-Answer", "7.1.2", _PHYSICAL),
        ("Push-Notification-Request", "7.1.5", _LOGICAL),
        ("Push-Notification-Request", "7.1.5", _PHYSICAL),
        ("Push-Notification-Request", "7.1.5", _GATE),
        ("Push-Notification-Request", "7.1.5", _QOS),
    ]
]

CORRECTIONS += [
    Delete(
        id="pnr-access-network-type-repeated",
        target=avp_rule(
            "Push-Notification-Request", "Access-Network-Type", occurrence=2
        ),
        expect=ast.AvpRule(
            name="Access-Network-Type", presence=ast.Presence.OPTIONAL, bold=True
        ),
        reason="clause 7.1.5's format prints '[Access-Network-Type]' twice, each at"
        " most one occurrence; table 2e lists the AVP once for its event, and ES"
        " 283 034's PNR (7.1.3) once",
        versions="2.5.1",
    ),
    Correction(
        id="access-network-type-changed-spelling",
        target=enum_value("Event-Type", "ACCESS-NETWORK-TYPE -CHANGED", value=3),
        field="name",
        expect="ACCESS-NETWORK-TYPE -CHANGED",
        replace="ACCESS-NETWORK-TYPE-CHANGED",
        reason="clause 7.3.6 and table 2e print a space inside the value's name;"
        " none of the ten other values holds one, and they are named"
        " TERMINAL-TYPE-CHANGED and so on",
        versions="2.5.1",
    ),
]
