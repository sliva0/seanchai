"""Corrections for 3GPP TS 29.228 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, information_elements

# Clause 6.3 maps its procedure to "the commands Multimedia-Auth-Request/Answer
# in the Diameter application specified in TS 29.229 [5]" and prints five
# tables for them, which the extractor gives no command: the request's and the
# answer's, and three tabulating the members of a grouped AVP each carries, as
# their captions say.
_TABLES = (
    ("6.3.1", "Request", None, "'Authentication Request'"),
    (
        "6.3.2",
        "Request",
        "SIP-Auth-Data-Item",
        "'Authentication Data content in Authentication Request', the element"
        " table 6.3.1 maps to SIP-Auth-Data-Item",
    ),
    ("6.3.4", "Answer", None, "'Authentication Request Response'"),
    (
        "6.3.5",
        "Answer",
        "SIP-Auth-Data-Item",
        "'Authentication Data information element content in Authentication"
        " Request Response', the element table 6.3.4 maps to SIP-Auth-Data-Item",
    ),
    (
        "6.3.7",
        "Answer",
        "SIP-Digest-Authenticate",
        "'Digest Authenticate information element content - Response for SIP"
        " Digest', the element table 6.3.5 maps to SIP-Digest-Authenticate",
    ),
)

# Each table's corrections: its command, the document printing it, and the
# grouped AVP whose members it tabulates.
_FIELDS = [
    (label, field, value, caption)
    for label, half, within, caption in _TABLES
    for field, value in (
        ("command", f"Multimedia-Auth-{half}"),
        ("origin", "TS29.229"),
        *((("avp", within),) if within else ()),
    )
]

CORRECTIONS = [
    Correction(
        id=f"elements-{field}-{label.replace('.', '-')}",
        target=information_elements(label),
        field=field,
        expect=None,
        replace=value,
        reason=f"clause 6.3 maps its procedure to Multimedia-Auth-Request/Answer"
        f" 'in the Diameter application specified in TS 29.229 [5]', and table"
        f" {label} is captioned {caption}",
        versions="19.2.0",
    )
    for label, field, value, caption in _FIELDS
]
