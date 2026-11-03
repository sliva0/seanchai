"""Corrections for 3GPP TS 29.389 — see docs/corrections.md."""

from seanchai.dad.corrections import Accept, value_row

CORRECTIONS = [
    Accept(
        id="user-unknown-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_USER_UNKNOWN"),
        expect="DIAMETER_ERROR_USER_UNKNOWN (code 5001) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.4.3.2 says 'This error code is defined in 3GPP TS 29.229 "
        "[6].': the document lists a code it re-uses",
        versions="18.0.0..19.0.0",
    ),
    Accept(
        id="unknown-v2x-subscription-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_UNKNOWN_V2X_SUBSCRIPTION"
        ),
        expect="DIAMETER_ERROR_UNKNOWN_V2X_SUBSCRIPTION (code 5690) is listed here, "
        "but TS29.230 table 8.1.4 allocates the code to TS29.388",
        reason="clause 6.4.3.3 says 'This error code is defined in 3GPP TS 29.388 "
        "[16].': the document lists a code it re-uses",
        versions="18.0.0..19.0.0",
    ),
    Accept(
        id="v2x-not-allowed-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_V2X_NOT_ALLOWED"),
        expect="DIAMETER_ERROR_V2X_NOT_ALLOWED (code 5691) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.388",
        reason="clause 6.4.3.4 says 'This error code is defined in 3GPP TS 29.388 "
        "[16].': the document lists a code it re-uses",
        versions="18.0.0..19.0.0",
    ),
]
