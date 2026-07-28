"""Corrections for 3GPP TS 29.229 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, reused_row

CORRECTIONS = [
    Correction(
        target=reused_row("Digest-QoP"),
        field="name",
        expect="Digest-QoP",
        replace="Digest-Qop",
        reason="table 6.3.0.1 cites RFC 4590, whose registered attribute name"
        " is Digest-Qop; the table uniquely capitalizes its final letter",
        versions="18.1.0",
    ),
]
