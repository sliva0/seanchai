"""Corrections for 3GPP TS 29.173 — see docs/corrections.md."""

from seanchai.dad.corrections import Accept, value_row

CORRECTIONS = [
    Accept(
        id="user-unknown-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_USER_UNKNOWN"),
        expect="DIAMETER_ERROR_USER_UNKNOWN (code 5001) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.3.3.1 says 'This error code is defined in 3GPP TS 29.229 "
        "[8]': the document lists a code it re-uses",
        versions="18.0.0",
    ),
]
