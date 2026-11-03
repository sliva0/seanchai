"""Corrections for 3GPP TS 29.330 — see docs/corrections.md."""

from seanchai.dad.corrections import Accept, value_row

CORRECTIONS = [
    Accept(
        id="user-unknown-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_USER_UNKNOWN"),
        expect="DIAMETER_ERROR_USER_UNKNOWN (code 5001) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.4.3.1 says 'This error code is defined in 3GPP TS 29.229 [6] "
        "clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
    Accept(
        id="operation-not-allowed-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_OPERATION_NOT_ALLOWED"
        ),
        expect="DIAMETER_ERROR_OPERATION_NOT_ALLOWED (code 5101) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 6.4.3.2 says 'This error code is defined in 3GPP TS 29.329 "
        "[12] clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
    Accept(
        id="user-data-cannot-be-read-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_DATA_CANNOT_BE_READ"
        ),
        expect="DIAMETER_ERROR_USER_DATA_CANNOT_BE_READ (code 5102) is listed here, "
        "but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 6.4.3.3 says 'This error code is defined in 3GPP TS 29.329 "
        "[12] clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
    Accept(
        id="user-data-cannot-be-modified-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_DATA_CANNOT_BE_MODIFIED"
        ),
        expect="DIAMETER_ERROR_USER_DATA_CANNOT_BE_MODIFIED (code 5103) is listed "
        "here, but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 6.4.3.4 says 'This error code is defined in 3GPP TS 29.329 "
        "[12] clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
    Accept(
        id="too-much-data-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_TOO_MUCH_DATA"),
        expect="DIAMETER_ERROR_TOO_MUCH_DATA (code 5008) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.4.3.5 says 'This error code is defined in 3GPP TS 29.229 [6] "
        "clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
    Accept(
        id="transparent-data-out-of-sync-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_TRANSPARENT_DATA OUT_OF_SYNC"
        ),
        expect="DIAMETER_ERROR_TRANSPARENT_DATA OUT_OF_SYNC (code 5105) is listed "
        "here, but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 6.4.3.6 says 'This error code is defined in 3GPP TS 29.329 "
        "[12] clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
    Accept(
        id="feature-unsupported-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_FEATURE_UNSUPPORTED"
        ),
        expect="DIAMETER_ERROR_FEATURE_UNSUPPORTED (code 5011) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.4.3.7 says 'The error code is defined in 3GPP TS 29.229 [6] "
        "clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
    Accept(
        id="user-data-not-available-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_USER_DATA_NOT_AVAILABLE"
        ),
        expect="DIAMETER_USER_DATA_NOT_AVAILABLE (code 4100) is listed here, but "
        "TS29.230 table 8.1.3 allocates the code to TS29.329",
        reason="clause 6.4.4.1 says 'This error code is defined in 3GPP TS 29.329 "
        "[12] clause 6.': the document lists a code it re-uses",
        versions="18.1.0..19.0.0",
    ),
]
