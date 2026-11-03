"""Corrections for 3GPP TS 29.329 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Delete,
    table_row,
    value_row,
)

CORRECTIONS = [
    Delete(
        id="load-row-not-local",
        target=table_row("Load"),
        expect=ast.AvpTableRow(
            name="Load",
            code=None,
            section="6.3.35",
            data_type=ast.DataType.GROUPED,
            flag_rules=ast.AvpFlagRules(
                must_not=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR})
            ),
            may_encrypt=False,
        ),
        reason="table 6.3.1 prints Load with no AVP code because it is not"
        " this document's AVP: clause 6.3.35 says it is defined in RFC 8583,"
        " and table 6.3/2 already lists it as re-used from there — the"
        " code-less table row is the same fact printed in the wrong table",
        versions="18.0.0",
    ),
]

# The codes clauses say are defined elsewhere, as the registry allocates them.
CORRECTIONS += [
    Accept(
        id="too-much-data-result-code-reused",
        rule="registry-result-code-document",
        target=value_row("Experimental-Result-Code", "DIAMETER_ERROR_TOO_MUCH_DATA"),
        expect="DIAMETER_ERROR_TOO_MUCH_DATA (code 5008) is listed here, but TS29.230 "
        "table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.2.2.6 says 'This error code is defined in 3GPP TS 29.229 "
        "[6].': the document lists a code it re-uses",
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
        reason="clause 6.2.2.8 says 'See 3GPP TS 29.229 [6] clause 6.': the document "
        "lists a code it re-uses",
        versions="18.0.0",
    ),
    Accept(
        id="identities-dont-match-result-code-reused",
        rule="registry-result-code-document",
        target=value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_IDENTITIES_DONT_MATCH"
        ),
        expect="DIAMETER_ERROR_IDENTITIES_DONT_MATCH (code 5002) is listed here, but "
        "TS29.230 table 8.1.4 allocates the code to TS29.229",
        reason="clause 6.2.2.12 says 'See 3GPP TS 29.229 [6]': the document lists a "
        "code it re-uses",
        versions="18.0.0",
    ),
]
