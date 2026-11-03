"""Corrections for 3GPP TS 29.388 — see docs/corrections.md."""

from seanchai.dad.corrections import (
    Accept,
    Correction,
    definition,
    value_row,
)

CORRECTIONS = [
    Correction(
        id="plmn-allowed-pc5-rats-rule-name",
        target=definition("V2X-PC5-Allowed-PLMN", section="6.3.10"),
        field="name",
        expect="V2X-PC5-Allowed-PLMN",
        replace="PLMN-Allowed-PC5-RATs",
        reason="clause 6.3.10's AVP format re-prints clause 6.3.3's rule name;"
        " the heading, the clause prose and table 6.3.1-1 all call the AVP at"
        " code 4603 'PLMN-Allowed-PC5-RATs', and 6.3.3's own AVP is 4600",
        versions="18.1.0..19.1.0",
    ),
]

# Findings the linter reports that the document makes on purpose; they
# change no data (docs/corrections.md).
CORRECTIONS += [
    Accept(
        id="v2x-subscription-data-v4-body",
        rule="reused-body-differs",
        target=definition("V2X-Subscription-Data"),
        expect="V2X-Subscription-Data's body, against TS29.272's definition: adds "
        "V2X-PC5-Allowed-PLMN, missing UE-PC5-AMBR, V2X-Permission",
        reason="clause 6.3.2: 'The V2X-Subscription-Data is originally defined in TS "
        "29.272 [10]. AVP format when used over V4 interface'",
        versions="18.1.0..19.1.0",
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
        reason="clause 6.4.3.2 says 'This error code is defined in TS 29.229 [6].': "
        "the document lists a code it re-uses",
        versions="18.1.0..19.1.0",
    ),
]
