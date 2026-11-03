"""Corrections for 3GPP TS 29.283 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Delete,
    reused_row,
    value_row,
)

CORRECTIONS = [
    Delete(
        id="sequence-number-origin-is-another-avp",
        target=reused_row("Sequence-Number"),
        expect=ast.ReusedAvpRow(name="Sequence-Number", origin="TS29.329"),
        reason="clause 7.3.21 cites TS 29.329, but table 7.3.1-1 gives"
        " this MC service profile's Sequence-Number code 4512; TS 29.230"
        " allocates 4512 to TS 29.283 and separately allocates 716 to"
        " TS 29.329's Sh Sequence-Number, so the citation does not identify"
        " this AVP's origin and following it would change its wire identity",
        versions="18.0.0",
    ),
    Delete(
        id="feature-id-row-not-in-origin",
        target=reused_row("Feature-Id"),
        expect=ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229"),
        reason="table 7.3.1-2 cites Feature-Id from TS 29.229, which neither"
        " defines nor tabulates any such AVP in any version; the Supported-"
        "Features mechanism's real AVPs (Feature-List-ID, Feature-List) are"
        " already listed on the adjacent rows",
        versions="18.0.0",
    ),
    Correction(
        id="drmp-origin-rfc",
        target=reused_row("DRMP"),
        field="origin",
        expect="RFC7844",
        replace="RFC7944",
        reason="RFC 7844 is about DHCP anonymity and defines no DRMP AVP;"
        " RFC 7944 defines DRMP with code 301",
        versions="18.0.0",
    ),
    Correction(
        id="unknown-data-result-spelling",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_ UNKNOWN _DATA"),
        field="name",
        expect="DIAMETER_ERROR_ UNKNOWN _DATA",
        replace="DIAMETER_ERROR_UNKNOWN_DATA",
        reason="clause 7.4.3.12's heading prints two spaces inside the name; TS "
        "29.230 table 8.1.4 allocates 5670 to it, whose own misprint is patched "
        "on input",
        versions="18.0.0",
    ),
]

# The codes clauses say are defined elsewhere, as the registry allocates them.
CORRECTIONS += [
    Accept(
        id="user-unknown-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_USER_UNKNOWN"),
        expect="DIAMETER_ERROR_USER_UNKNOWN (code 5001) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 7.4.3.2 says 'This error code is defined in 3GPP TS 29.229 "
        "[6].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="user-data-not-recognized-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_DATA_NOT_RECOGNIZED"
        ),
        expect="DIAMETER_ERROR_USER_DATA_NOT_RECOGNIZED (code 5100) is listed here, "
        "but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 7.4.3.3 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="operation-not-allowed-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_OPERATION_NOT_ALLOWED"
        ),
        expect="DIAMETER_ERROR_OPERATION_NOT_ALLOWED (code 5101) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 7.4.3.4 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="user-data-cannot-be-read-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_DATA_CANNOT_BE_READ"
        ),
        expect="DIAMETER_ERROR_USER_DATA_CANNOT_BE_READ (code 5102) is listed here, "
        "but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 7.4.3.5 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="user-data-cannot-be-modified-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_DATA_CANNOT_BE_MODIFIED"
        ),
        expect="DIAMETER_ERROR_USER_DATA_CANNOT_BE_MODIFIED (code 5103) is listed "
        "here, but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 7.4.3.6 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="user-data-cannot-be-notified-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_DATA_CANNOT_BE_NOTIFIED"
        ),
        expect="DIAMETER_ERROR_USER_DATA_CANNOT_BE_NOTIFIED (code 5104) is listed "
        "here, but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 7.4.3.7 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="too-much-data-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_TOO_MUCH_DATA"),
        expect="DIAMETER_ERROR_TOO_MUCH_DATA (code 5008) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 7.4.3.8 says 'This error code is defined in 3GPP TS 29.229 "
        "[6].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="data-out-of-sync-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_DATA OUT_OF_SYNC"),
        expect="DIAMETER_ERROR_DATA OUT_OF_SYNC (code 5105) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 7.4.3.9 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="feature-unsupported-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_FEATURE_UNSUPPORTED"
        ),
        expect="DIAMETER_ERROR_FEATURE_UNSUPPORTED (code 5011) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.229",
        reason="clause 7.4.3.10 says 'This error code is defined in 3GPP TS 29.229 "
        "[6].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="no-subscription-to-data-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_NO_SUBSCRIPTION_TO_DATA"
        ),
        expect="DIAMETER_ERROR_NO_SUBSCRIPTION_TO_DATA (code 5107) is listed here, "
        "but TS29.230 table 8.1.4 allocates the code to TS29.329",
        reason="clause 7.4.3.11 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="user-data-not-available-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_USER_DATA_NOT_AVAILABLE"
        ),
        expect="DIAMETER_USER_DATA_NOT_AVAILABLE (code 4100) is listed here, but "
        "TS29.230 table 8.1.3 allocates the code to TS29.329",
        reason="clause 7.4.4.2 says 'This error code is defined in 3GPP TS 29.329 "
        "[9].': the document lists a code it re-uses",
        versions="18.0.0",
    ),
]
