"""Corrections for 3GPP TS 29.329 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Delete,
    Insert,
    avp_rule,
    definition,
    header,
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
        versions="18.0.0..19.1.0",
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
        versions="18.0.0..19.1.0",
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
        versions="18.0.0..19.1.0",
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
        versions="18.0.0..19.1.0",
    ),
]

# Sh-ee, clause 8, which Release 19 adds.
CORRECTIONS += [
    Correction(
        id="ims-event-report-row-name",
        target=table_row("Event-Report", table="8.3.1"),
        field="name",
        expect="Event-Report",
        replace="Ims-Event-Report",
        reason="table 8.3.1 prints code 735 as Event-Report, and TS 29.230 V19.3.0"
        " table 7.1 allocates it so; the table's own clause 8.3.13 defines"
        " Ims-Event-Report under that header code, and the ESA and ENR rules name"
        " it; no other clause prints the shorter name",
        versions="19.1.0",
    ),
    Correction(
        id="notification-correlation-identity-spelling",
        target=avp_rule(
            "Event-Notification-Request", "Notification-Correction-Identity"
        ),
        field="name",
        expect="Notification-Correction-Identity",
        replace="Notification-Correlation-Identity",
        reason="clause 8.1.3 misspells the AVP table 8.3.1 and clause 8.3.4 define"
        " (726), which the ESR rule names and whose value the ENR returns",
        versions="19.1.0",
    ),
    Correction(
        id="enr-request-flag",
        target=definition("Event-Notification-Request"),
        field="flags",
        expect=frozenset({ast.CommandFlag.PROXIABLE}),
        replace=frozenset({ast.CommandFlag.REQUEST, ast.CommandFlag.PROXIABLE}),
        reason="clause 8.1.3 says the command is 'indicated by the Command-Code"
        " field set to 311 and the 'R' bit set in the Command Flags field', and"
        " its rule prints '311, PXY', the answer's header, for the request",
        versions="19.1.0",
    ),
    Insert(
        id="undefined-request-current-status",
        into=header(),
        node=ast.UndefinedAvp(
            name="Request-Current-Status",
            source=ast.SourceRef(section="8.3.10"),
            note='8.3.10 "This AVP shall contain Ims-Event AVP, Event Information'
            ' AVP, Request Current Status AVP and Ims Event Filter AVP"',
        ),
        after=None,
        reason="a member of Event-List (8.3.10) no clause defines and table 8.3.1"
        " does not list, in V19.1.0, the document that adds it; the TS 29.230"
        " V19.3.0 registry allocates no such name, none of the corpus's documents"
        " defines it, and Wireshark's dictionary has no such AVP",
        versions="19.1.0",
    ),
]
