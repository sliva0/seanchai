"""Corrections for 3GPP TS 29.140 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, information_elements

# Clause 4.1 maps its procedure to the commands and names the tables, which sit
# in its subclause 4.1.1, where the extractor looks for the sentence.
CORRECTIONS = [
    Correction(
        id=f"elements-command-{label.replace('.', '-')}",
        target=information_elements(label),
        field="command",
        expect=None,
        replace=command,
        reason="clause 4.1 says 'This procedure is mapped to the commands"
        " Message-Process-Request/Answer in the Diameter application specified in"
        " section 6.1. Tables 4.1.1.1 and 4.1.1.2 detail the involved information"
        f" elements'; table {label} is captioned '{caption}'",
        versions="7.0.0",
    )
    for label, caption, command in (
        ("4.1.1.1", "MM10 Interrogation Request", "Message-Process-Request"),
        ("4.1.1.2", "MM10 Interrogation Response", "Message-Process-Answer"),
    )
]
