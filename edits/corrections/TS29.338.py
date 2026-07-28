"""Corrections for 3GPP TS 29.338 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
        target=definition("SMS-MI-Correlation-ID", section="6.3.3.13"),
        field="name",
        expect="SMS-MI-Correlation-ID",
        replace="SMSMI-Correlation-ID",
        reason="clause 6.3.3.13's AVP format writes 'SMS-MI-Correlation-ID';"
        " the clause heading, the clause prose, table 6.3.3.1-1 and every"
        " command ABNF in the document spell it 'SMSMI-Correlation-ID'",
        versions="18.2.0",
    ),
    Correction(
        target=definition("SMS-MI-Correlation-ID", section="6.3.3.13"),
        field="code",
        expect=3308,
        replace=3324,
        reason="clause 6.3.3.13's AVP format re-prints SM-RP-MTI's code 3308"
        " (clause 5.3.3.2); table 6.3.3.1-1 gives SMSMI-Correlation-ID the"
        " code 3324",
        versions="18.2.0",
    ),
]
