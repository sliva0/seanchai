"""Corrections for ETSI TS 183 020 — see docs/corrections.md.

The input is the transcription (`raw/etsi/ts183020-010101.raw.dad`), which
records what the PDF prints. Clause 2: "For a non-specific reference, the latest
version applies", and table 1's [9] ES 283 034 is one, so its names answer to
V2.2.0; TS 183 020 (March 2006) prints the names of the V1.1.1 being drafted."""

from seanchai.dad.corrections import Correction, reused_row

CORRECTIONS = [
    Correction(
        id="user-name-origin",
        target=reused_row("User-Name"),
        field="origin",
        expect="RFC3588",
        replace="RFC6733",
        reason="table 1 cites RFC 3588 [15] for User-Name; the corpus reads the"
        " base protocol as RFC 6733, which obsoletes it and defines the AVP",
        versions="1.1.1",
    ),
    Correction(
        id="initiate-gate-setting-name",
        target=reused_row("Initiate-Gate-Setting"),
        field="name",
        expect="Initiate-Gate-Setting",
        replace="Initial-Gate-Setting-Description",
        reason="table 1 prints 'Initiate-' for its InitialGateSetting element, a"
        " name ES 283 034 has never given; V1.1.1 names code 303"
        " Initial-Gate-Setting and V2.2.0, the latest version clause 2 reads a"
        " non-specific [9] as, Initial-Gate-Setting-Description, as TS 183 066"
        " table 7.3 does",
        versions="1.1.1",
    ),
    Correction(
        id="qos-profile-name",
        target=reused_row("QoS-Profile"),
        field="name",
        expect="QoS-Profile",
        replace="QoS-Profile-Description",
        reason="ES 283 034 V1.1.1 names code 304 QoS-Profile and V2.2.0, the"
        " latest version clause 2 reads a non-specific [9] as,"
        " QoS-Profile-Description, as TS 183 066 table 7.3 does",
        versions="1.1.1",
    ),
]
