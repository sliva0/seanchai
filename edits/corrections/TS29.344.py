"""Corrections for 3GPP TS 29.344 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Insert,
    avp_table,
    definition,
    value_row,
)

# Clauses 6.2.11 and 6.2.12 head "ProSe-Initial-Location-Information-Request"
# and "-Answer" and carry command code 8388713 with the abbreviations PSR/PSA,
# but their ABNF re-prints the rule names of clauses 6.2.3/6.2.4, which are
# command 8388664 (PIR/PIA). IANA assigns 8388713 to
# ProSe-Initial-Location-Information-Request/Answer, so the headings and the
# codes agree with each other and only the rule names are wrong.
_PSR_PSA = (
    "clauses 6.2.11/6.2.12 re-print the rule names of 6.2.3/6.2.4; the headings,"
    " the PSR/PSA abbreviations and command code 8388713 all name"
    " ProSe-Initial-Location-Information instead"
)

CORRECTIONS = [
    Correction(
        id=f"psr-psa-rule-name-{kind.lower()}",
        target=definition(f"ProSe-Subscriber-Information-{kind}", section=section),
        field="name",
        expect=f"ProSe-Subscriber-Information-{kind}",
        replace=f"ProSe-Initial-Location-Information-{kind}",
        reason=_PSR_PSA,
        versions="18.1.0..19.1.0",
    )
    for kind, section in (("Request", "6.2.11"), ("Answer", "6.2.12"))
]

CORRECTIONS += [
    Insert(
        id="authorized-discovery-range-row-missing",
        into=avp_table("6.3.1-1"),
        node=ast.AvpTableRow(
            name="Authorized-Discovery-Range",
            code=3708,
            section="6.3.13",
            data_type=ast.DataType.UNSIGNED32,
            flag_rules=ast.AvpFlagRules(
                must=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR})
            ),
            may_encrypt=False,
        ),
        after="ProSe-Initial-Location-Information",
        reason="clause 6.3.13 defines this Unsigned32 AVP and TS 29.230 assigns"
        " it code 3708, but table 6.3.1-1 accidentally omits the row; its flag"
        " rules follow every locally defined PC4a AVP in the table",
        versions="18.1.0..19.1.0",
    )
]

CORRECTIONS += [
    Correction(
        id="prose-not-allowed-result-spelling",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_ PROSE_NOT_ALLOWED"
        ),
        field="name",
        expect="DIAMETER_ERROR_ PROSE_NOT_ALLOWED",
        replace="DIAMETER_ERROR_PROSE_NOT_ALLOWED",
        reason="clause 6.4.3.4's heading prints a space inside the name; TS 29.230 "
        "table 8.1.4 allocates 5611 under the name without it",
        versions="18.1.0..19.1.0",
    ),
    Correction(
        id="ue-location-unknown-result-spelling",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_ UE_LOCATION_UNKNOWN"
        ),
        field="name",
        expect="DIAMETER_ERROR_ UE_LOCATION_UNKNOWN",
        replace="DIAMETER_ERROR_UE_LOCATION_UNKNOWN",
        reason="clause 6.4.3.5's heading prints a space inside the name; TS 29.230 "
        "table 8.1.4 allocates 5612 under the name without it",
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
