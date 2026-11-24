"""Corrections for TS 29.273; the raw file retains every printed definition."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Delete,
    Insert,
    avp_rule,
    command_result_codes,
    definition,
    element_row,
    flag_rules,
    header,
    information_elements,
    reused_avps,
    reused_row,
    table_row,
)

CORRECTIONS = [
    Correction(
        id="accounting-interim-interval-rule-4-2-2-1-2-diameter-eap-answer",
        target=avp_rule(
            definition("Diameter-EAP-Answer", section="4.2.2.1.2"),
            "Accounting-Interim-Interval",
        ),
        field="name",
        expect="Accounting-Interim-Interval",
        replace="Acct-Interim-Interval",
        reason=(
            "RFC 6733 clause 9.8.2 defines Acct-Interim-Interval; the printed"
            " name does not exist."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="accounting-interim-interval-rule-5-2-2-1-2-diameter-eap-answer",
        target=avp_rule(
            definition("Diameter-EAP-Answer", section="5.2.2.1.2"),
            "Accounting-Interim-Interval",
        ),
        field="name",
        expect="Accounting-Interim-Interval",
        replace="Acct-Interim-Interval",
        reason=(
            "RFC 6733 clause 9.8.2 defines Acct-Interim-Interval; the printed"
            " name does not exist."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-rule-5-2-2-1-2-diameter-eap-answer",
        target=avp_rule(
            definition("Diameter-EAP-Answer", section="5.2.2.1.2"), "Subscription-ID"
        ),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason="RFC 4006 clause 8.46 spells its AVP Subscription-Id.",
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="accounting-interim-interval-rule-5-2-2-3-4-aa-answer",
        target=avp_rule(
            definition("AA-Answer", section="5.2.2.3.4"), "Accounting-Interim-Interval"
        ),
        field="name",
        expect="Accounting-Interim-Interval",
        replace="Acct-Interim-Interval",
        reason=(
            "RFC 6733 clause 9.8.2 defines Acct-Interim-Interval; the printed"
            " name does not exist."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-rule-5-2-2-3-4-aa-answer",
        target=avp_rule(
            definition("AA-Answer", section="5.2.2.3.4"), "Subscription-ID"
        ),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason="RFC 4006 clause 8.46 spells its AVP Subscription-Id.",
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="accounting-interim-interval-rule-6-2-2-1-1-2-diameter-eap-answer",
        target=avp_rule(
            definition("Diameter-EAP-Answer", section="6.2.2.1.1.2"),
            "Accounting-Interim-Interval",
        ),
        field="name",
        expect="Accounting-Interim-Interval",
        replace="Acct-Interim-Interval",
        reason=(
            "RFC 6733 clause 9.8.2 defines Acct-Interim-Interval; the printed"
            " name does not exist."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-rule-6-2-2-1-1-2-diameter-eap-answer",
        target=avp_rule(
            definition("Diameter-EAP-Answer", section="6.2.2.1.1.2"), "Subscription-ID"
        ),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason="RFC 4006 clause 8.46 spells its AVP Subscription-Id.",
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-rule-7-2-2-1-2-diameter-eap-answer",
        target=avp_rule(
            definition("Diameter-EAP-Answer", section="7.2.2.1.2"), "Subscription-ID"
        ),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason="RFC 4006 clause 8.46 spells its AVP Subscription-Id.",
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-rule-7-2-2-1-4-aa-answer",
        target=avp_rule(
            definition("AA-Answer", section="7.2.2.1.4"), "Subscription-ID"
        ),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason="RFC 4006 clause 8.46 spells its AVP Subscription-Id.",
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="accounting-interim-interval-row-5-2-3-1",
        target=reused_row("Accounting-Interim-Interval", section="5.2.3.1"),
        field="name",
        expect="Accounting-Interim-Interval",
        replace="Acct-Interim-Interval",
        reason=(
            "Table 5.2.3.1/2 misspells the AVP; its cited origin defines Acct-"
            " Interim-Interval."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-row-5-2-3-1",
        target=reused_row("Subscription-ID", section="5.2.3.1"),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason=(
            "Table 5.2.3.1/2 misspells the AVP; its cited origin defines"
            " Subscription-Id."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="accounting-interim-interval-row-6-2-3-1",
        target=reused_row("Accounting-Interim-Interval", section="6.2.3.1"),
        field="name",
        expect="Accounting-Interim-Interval",
        replace="Acct-Interim-Interval",
        reason=(
            "Table 6.2.3.1/2 misspells the AVP; its cited origin defines Acct-"
            " Interim-Interval."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-row-6-2-3-1",
        target=reused_row("Subscription-ID", section="6.2.3.1"),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason=(
            "Table 6.2.3.1/2 misspells the AVP; its cited origin defines"
            " Subscription-Id."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-row-7-2-3-1",
        target=reused_row("Subscription-ID", section="7.2.3.1"),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason=(
            "Table 7.2.3.1/2 misspells the AVP; its cited origin defines"
            " Subscription-Id."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-row-8-2-3-0",
        target=reused_row("Subscription-ID", section="8.2.3.0"),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason=(
            "Table 8.2.3.0/2 misspells the AVP; its cited origin defines"
            " Subscription-Id."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="subscription-id-rule-8-2-3-1-non-3gpp-user-data",
        target=avp_rule(
            definition("Non-3GPP-User-Data", section="8.2.3.1"), "Subscription-ID"
        ),
        field="name",
        expect="Subscription-ID",
        replace="Subscription-Id",
        reason="RFC 4006 clause 8.46 spells its AVP Subscription-Id.",
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="swm-aa-answer-request-flag",
        target=definition("AA-Answer", section="7.2.2.1.4"),
        field="flags",
        expect=frozenset({ast.CommandFlag.REQUEST, ast.CommandFlag.PROXIABLE}),
        replace=frozenset({ast.CommandFlag.PROXIABLE}),
        reason=(
            "Clause 7.2.2.1.4 states the AAA has the 'R' bit cleared, as RFC"
            " 6733 section 3 has every answer; its header prints REQ."
        ),
        versions="18.6.0..19.2.0",
    ),
    Correction(
        id="emergency-services-clause",
        target=table_row("Emergency-Services", table="9.2.3.2.1/1"),
        field="section",
        expect="7.2.3.5",
        replace="7.2.3.4",
        reason=(
            "Emergency-Services is defined in clause 7.2.3.4; clause 7.2.3.5"
            " defines AAR-Flags."
        ),
        versions="18.6.0..19.2.0",
    ),
    Delete(
        id="mip6-agent-info-duplicate",
        target=definition("MIP6-Agent-Info", section="9.2.3.6.2"),
        expect=ast.GroupedAvp(
            name="MIP6-Agent-Info",
            source=ast.SourceRef(section="9.2.3.6.2", page=192),
            code=486,
            vendor_id=None,
            avps=(
                ast.AvpRule(
                    name="MIP-Home-Agent-Address",
                    presence=ast.Presence.OPTIONAL,
                    min_occurs=0,
                    max_occurs=2,
                    bold=False,
                ),
                ast.AvpRule(
                    name="MIP-Home-Agent-Host",
                    presence=ast.Presence.OPTIONAL,
                    min_occurs=1,
                    max_occurs=1,
                    bold=False,
                ),
                ast.AvpRule(
                    name="MIP6-Home-Link-Prefix",
                    presence=ast.Presence.OPTIONAL,
                    min_occurs=1,
                    max_occurs=1,
                    bold=False,
                ),
                ast.AvpRule(
                    name="AVP",
                    presence=ast.Presence.OPTIONAL,
                    min_occurs=0,
                    max_occurs=None,
                    bold=False,
                ),
            ),
        ),
        reason=(
            "Clauses 9.2.3.2.2 and 9.2.3.6.2 both explicitly cite RFC 5447 and"
            " print identical bodies for the same identity; keep the first copy"
            " in the corrected dictionary."
        ),
        versions="18.6.0..19.2.0",
    ),
    Insert(
        id="mip-home-agent-address-reused",
        into=reused_avps("9.2.3.3/1"),
        node=ast.ReusedAvpRow(name="MIP-Home-Agent-Address", origin="RFC4004"),
        after=None,
        reason=(
            "Clauses 9.2.3.2.2 and 9.2.3.6.2 reprint MIP6-Agent-Info but omit"
            " its members from the re-used table; RFC 4004 clause 7.4 defines"
            " this member."
        ),
        versions="18.6.0..19.2.0",
    ),
    Insert(
        id="mip-home-agent-host-reused",
        into=reused_avps("9.2.3.3/1"),
        node=ast.ReusedAvpRow(name="MIP-Home-Agent-Host", origin="RFC4004"),
        after=None,
        reason="RFC 4004 clause 7.11 defines this member of MIP6-Agent-Info.",
        versions="18.6.0..19.2.0",
    ),
    Insert(
        id="mip6-home-link-prefix-reused",
        into=reused_avps("9.2.3.3/1"),
        node=ast.ReusedAvpRow(name="MIP6-Home-Link-Prefix", origin="RFC5447"),
        after=None,
        reason=(
            "Clause 9.2.3.2.2 explicitly retains this RFC 5447 member to"
            " reflect the complete definition."
        ),
        versions="18.6.0..19.2.0",
    ),
    Insert(
        id="subscription-id-type-reused",
        into=reused_avps("8.2.3.0/2"),
        node=ast.ReusedAvpRow(name="Subscription-Id-Type", origin="RFC4006"),
        after=None,
        reason=(
            "Clause 8.2.3.2 reprints Subscription-Id from RFC 4006 but the re-"
            " used table omits its members."
        ),
        versions="18.6.0..19.2.0",
    ),
    Insert(
        id="subscription-id-data-reused",
        into=reused_avps("8.2.3.0/2"),
        node=ast.ReusedAvpRow(name="Subscription-Id-Data", origin="RFC4006"),
        after=None,
        reason=(
            "RFC 4006 clause 8.48 supplies this member of Subscription-Id in"
            " clause 8.2.3.2."
        ),
        versions="18.6.0..19.2.0",
    ),
]

# RAT-Type is re-used from TS 29.212 (tables 5.2.3.1/2, 6.2.3.1/2, 8.2.3.0/2,
# no M-bit override) and clauses 5.2.3.6 and 8.2.3.5 defer to it ("It follows
# the specification described in TS 29.212"), yet three AVP tables set M in
# Must, where TS 29.212 table 5.3.0.1 has it in Must not.
CORRECTIONS += [
    Correction(
        id=(
            f"rat-type-m-flag-{field.replace('_', '-')}-"
            + table.replace(".", "-").replace("/", "-")
        ),
        target=flag_rules(table_row("RAT-Type", table=table)),
        field=field,
        expect=expect,
        replace=replace,
        reason=(
            f"table {table} sets M in Must for RAT-Type, which clause 5.2.3.6"
            " says follows TS 29.212 and the re-used tables list from it with"
            " no M-bit override; TS 29.212 table 5.3.0.1 puts M in Must not"
        ),
        versions="18.6.0..19.2.0",
    )
    for table in ("5.2.3.1/1", "6.2.3.1/1", "7.2.3.1/1")
    for field, expect, replace in (
        (
            "must",
            frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}),
            frozenset({ast.AvpFlag.VENDOR}),
        ),
        (
            "must_not",
            frozenset({ast.AvpFlag.PROTECTED}),
            frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.PROTECTED}),
        ),
    )
]

# Clause 4.2.1: "The SWa reference point shall use the same Diameter
# application as the STa reference point", which clause 5.2.1 numbers
# 16777250. SWa's DER/DEA headers (4.2.2.1.1, 4.2.2.1.2) print no id; its
# RAR/RAA headers print 16777250.
CORRECTIONS += [
    Insert(
        id="application-id-swa",
        into=header(),
        node=ast.ApplicationScope(
            name="STa",
            source=ast.SourceRef(section="4.2.1", page=24),
            application_id=16777250,
            applies_to=("4.*",),
        ),
        after=None,
        reason=(
            "clause 4.2.1: 'The SWa reference point shall use the same"
            " Diameter application as the STa reference point'; clause 5.2.1"
            " defines '\"STa\" with value 16777250'. The DER/DEA headers of"
            " 4.2.2.1.1 and 4.2.2.1.2 print no id"
        ),
        versions="18.6.0..19.2.0",
    ),
]

# Table 9.2.3.1.1/1 still lists Trust-Relationship-Update at 1515 for
# clause 9.2.3.1.4, which reads "Void"; table 9.2.3.1.5/1's RAR-Flags bit 0,
# Trust-Relationship-Update-indication, carries what it did. No ABNF
# references it.
CORRECTIONS += [
    Delete(
        id="trust-relationship-update-void",
        target=table_row("Trust-Relationship-Update", table="9.2.3.1.1/1"),
        expect=ast.AvpTableRow(
            name="Trust-Relationship-Update",
            code=1515,
            section="9.2.3.1.4",
            data_type=ast.DataType.ENUMERATED,
            flag_rules=ast.AvpFlagRules(
                must=frozenset({ast.AvpFlag.VENDOR}),
                must_not=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.PROTECTED}),
            ),
        ),
        reason=(
            "the row's clause 9.2.3.1.4 is 'Void', and TS 29.230 table 7.1"
            " allocates 1515 to 'Reserved' (TS 29.273); table 9.2.3.1.5/1"
            " carries the indication as RAR-Flags bit 0"
        ),
        versions="18.6.0..19.2.0",
    ),
]

# Clause 5.2.2.1.2's DEA still lists NSWO-Authorization, an Enumerated AVP
# (1514, clause 5.2.3.17) until V11.3.0; CR 0309r2 (V11.4.0) made it DEA-Flags
# bit 0, printed right below it, and dropped the clause.
CORRECTIONS += [
    Delete(
        id="nswo-authorization-flag",
        target=avp_rule(
            definition("Diameter-EAP-Answer", section="5.2.2.1.2"),
            "NSWO-Authorization",
        ),
        expect=ast.AvpRule(name="NSWO-Authorization", presence=ast.Presence.OPTIONAL),
        reason=(
            "no clause defines NSWO-Authorization; table 5.2.3.21/1 carries it"
            " as DEA-Flags bit 0 'NSWO-Authorization', the [ DEA-Flags ] member"
            " beside it, and TS 29.230 table 7.1 allocates its former code"
            " 1514 to 'Reserved' (TS 29.273)"
        ),
        versions="18.6.0..19.2.0",
    ),
]

# Findings the linter reports that the document makes on purpose; they
# change no data (docs/corrections.md).
CORRECTIONS += [
    Accept(
        id="sip-auth-data-item-swx-body",
        rule="reused-body-differs",
        target=definition("SIP-Auth-Data-Item"),
        expect="SIP-Auth-Data-Item's body, against TS29.229's definition: missing "
        "Framed-IP-Address, Framed-IPv6-Prefix, Framed-Interface-Id, Line-Identifier, "
        "SIP-Authentication-Context, SIP-Digest-Authenticate",
        reason="clause 8.2.3.9: 'The SIP-Auth-Data-Item AVP is defined in 3GPP TS "
        "29.229 [24]. The optional AVPs that are needed in SWx reference point are "
        "included in the ABNF representation below.'",
        versions="18.6.0..19.2.0",
    ),
]

# Clause 9.2.3.6.2 prints the AVP the table says it does; the block is gone
# because one definition stays.
CORRECTIONS += [
    Accept(
        id="mip6-agent-info-row-clause",
        rule="section-mismatch",
        target=table_row("MIP6-Agent-Info", table="9.2.3.6.1/1"),
        expect="MIP6-Agent-Info is cited at clause 9.2.3.6.2 in table 9.2.3.6.1/1, but"
        " the file holds it at clause 9.2.3.2.2, and nothing at clause 9.2.3.6.2",
        reason="the row is right: clause 9.2.3.6.2 prints MIP6-Agent-Info again for its"
        " interface, and TS29.273.py#mip6-agent-info-duplicate deletes that copy, so"
        " the file holds only clause 9.2.3.2.2's",
        versions="18.6.0..19.2.0",
    ),
    Accept(
        id="trace-info-clause",
        rule="section-mismatch",
        target=table_row("Trace-Info", table="7.2.3.1/1"),
        expect="Trace-Info is cited at clause 8.2.3.1.3 in table 7.2.3.1/1, but the"
        " file holds it at clause 8.2.3.13, and nothing at clause 8.2.3.1.3",
        reason="a misprint in table 7.2.3.1/1: the document has no clause 8.2.3.1.3,"
        " clause 8.2.3.13 is headed 'Trace-Info' and defines it, and tables"
        " 8.2.3.0/1, 9.2.3.1.1/1 and 9.2.3.2.1/1 cite 8.2.3.13 for the same row",
        versions="18.6.0..19.2.0",
    ),
]

CORRECTIONS += [
    Correction(
        id="logical-access-id-etsi-standard",
        target=reused_row("Logical-Access-ID"),
        field="origin",
        expect="ETSI-TS283.034",
        replace="ETSI-ES283.034",
        reason="table 5.2.3.1/2 cites 'ETSI TS 283 034 [48]', as clause 2's [48] does;"
        " the document's own prose cites 'ETSI ES 283 034 [48]', which is how ETSI"
        " publishes that title, and it has no TS 283 034",
        versions="18.6.0..19.2.0",
    ),
    *(
        Correction(
            id=f"elements-application-{label.replace('/', '-').replace('.', '-')}",
            target=information_elements(label),
            field="application_id",
            expect=None,
            replace=16777264,
            reason="clause 7.1.2.2.1 is an SWm procedure, and clause 7.2.1 says"
            " 'The Diameter application for the SWm reference point shall use"
            " the Diameter Application Id with value 16777264'; the document"
            " prints AA-Request/Answer for STa, SWm and S6b",
            versions="18.6.0..19.2.0",
        )
        for label in ("7.1.2.2.1/1", "7.1.2.2.1/2")
    ),
]

# The procedure clauses' information-element tables, which name no command in a
# sentence the extractor reads: each procedure's clause, what it says maps the
# procedure to its commands, and per table its caption, the command it
# describes and the clause printing that command. A command clause is named on
# every table, since the document prints Diameter-EAP-Request for SWa, STa and
# SWd under STa's one application, and S6b's AA-Request and
# Session-Termination-Request twice each, every print with a body of its own.
# SWx's content tables tabulate SIP-Auth-Data-Item, the element tables 8.1.2.1.1/1
# and /4 map "Authentication Data" to.
_DER = "Diameter-EAP-Request"
_DEA = "Diameter-EAP-Answer"
_PROCEDURES = (
    (
        "4.1.2.1.1",
        "says the procedure 'follows the STa Authentication and Authorization"
        " procedure', which clause 5.1.2.1.1 maps 'to the Diameter-EAP-Request and"
        " Diameter-EAP-Answer command codes specified in IETF RFC 4072 [5]', and"
        " clause 4.2.1 says 'The first authentication command exchange (DER/DEA)"
        " is common between the SWa and STa reference points'; clause 4.2.2.1,"
        " 'Commands for SWa authentication and authorization procedures',",
        (
            (
                "4.1.2.1/1",
                "SWa Authentication and Authorization Request",
                _DER,
                "4.2.2.1.1",
            ),
            (
                "4.1.2.1/2",
                "SWa Authentication and Authorization Answer",
                _DEA,
                "4.2.2.1.2",
            ),
        ),
    ),
    (
        "4.1.2.4.1",
        "says 'This procedure is mapped to the Diameter command codes"
        " Re-Auth-Request and Re-Auth-Answer specified in IETF RFC 6733 [58]."
        " Information element contents for these messages shall be as shown in"
        " tables 4.1.2.4.1/1 and 4.1.2.4.1/2', then the SWa authentication and"
        " authorization procedure 'using DER/DEA commands ... Information element"
        " contents for these messages shall be as shown in tables 4.1.2.4.1/3 and"
        " 4.1.2.4.1/4'; clause 4.2.2.4, 'Commands for SWa Re-Authentication and"
        " Re-Authorization Procedures', whose DER and DEA clauses 'Refer to clause"
        " 4.2.2.1.1', 'Refer to clause 4.2.2.1.2',",
        (
            ("4.1.2.4.1/1", "SWa Re-auth request", "Re-Auth-Request", "4.2.2.4.1"),
            ("4.1.2.4.1/2", "SWa Re-auth response", "Re-Auth-Answer", "4.2.2.4.2"),
            (
                "4.1.2.4.1/3",
                "SWa Authentication and Authorization Request",
                _DER,
                "4.2.2.1.1",
            ),
            (
                "4.1.2.4.1/4",
                "SWa Authentication and Authorization Answer",
                _DEA,
                "4.2.2.1.2",
            ),
        ),
    ),
    (
        "5.1.2.1.1",
        "says 'When EAP is used, the trusted non-3GPP access authentication and"
        " authorization procedure shall be mapped to the Diameter-EAP-Request and"
        " Diameter-EAP-Answer command codes specified in IETF RFC 4072 [5]';"
        " clause 5.2.2.1, 'Commands for STa PMIPv6 or GTPv2 or ERP"
        " (re-)authentication and authorization procedures',",
        (
            (
                "5.1.2.1/1",
                "STa Access Authentication and Authorization Request",
                _DER,
                "5.2.2.1.1",
            ),
            (
                "5.1.2.1/2",
                "Trusted non-3GPP Access Authentication and Authorization Answer",
                _DEA,
                "5.2.2.1.2",
            ),
        ),
    ),
    (
        "5.1.2.2.1",
        "says 'This procedure is mapped to the Diameter command codes"
        " Diameter-Abort-Session-Request (ASR), Diameter-Abort-Session-Answer"
        " (ASA), Diameter-Session-Termination-Request (STR) and"
        " Diameter-Session-Termination-Answer (STA) specified in IETF RFC 6733"
        " [58]'; clause 5.2.2.2, 'Commands for STa HSS/AAA Initiated Detach for"
        " Trusted non-3GPP Access',",
        (
            (
                "5.1.2.2.1/1",
                "Information Elements passed in ASR message",
                "Abort-Session-Request",
                "5.2.2.2.1",
            ),
            (
                "5.1.2.2.1/2",
                "Information Elements passed in ASA message",
                "Abort-Session-Answer",
                "5.2.2.2.2",
            ),
            (
                "5.1.2.2.1/3",
                "Information Elements passed in STR message",
                "Session-Termination-Request",
                "5.2.2.2.3",
            ),
            (
                "5.1.2.2.1/4",
                "Information Elements passed in STA message",
                "Session-Termination-Answer",
                "5.2.2.2.4",
            ),
        ),
    ),
    (
        "5.1.2.3.1",
        "says 'This procedure is mapped to the Diameter command Re-Auth-Request and"
        " Re-Auth-Answer specified in IETF RFC 6733 [58]. Information element"
        " contents for these messages are shown in tables 5.1.2.3.1/1 and"
        " 5.1.2.3.1/2', then 'based on the reuse of the Diameter command codes"
        " AA-Request and AA-Answer commands specified in IETF RFC 4005 [4]."
        " Information element contents for these messages are shown in tables"
        " 5.1.2.3.1/3 and 5.1.2.3.1/4', and 'based on the reuse of the Diameter"
        " commands Diameter-EAP-Request and Diameter-EAP-Answer specified in IETF"
        " RFC 4072 [5]. Information element contents for these messages are shown"
        " in tables 5.1.2.3.1/5 and 5.1.2.3.1/6'; clause 5.2.2.3, 'Commands for"
        " Re-Authentication and Re-Authorization Procedure', whose DER and DEA"
        " clauses 'Refer to clause 5.2.2.1.1', 'Refer to clause 5.2.2.1.2',",
        (
            ("5.1.2.3.1/1", "STa Re-Auth request", "Re-Auth-Request", "5.2.2.3.1"),
            ("5.1.2.3.1/2", "STa Re-Auth response", "Re-Auth-Answer", "5.2.2.3.2"),
            ("5.1.2.3.1/3", "STa Authorization Request", "AA-Request", "5.2.2.3.3"),
            ("5.1.2.3.1/4", "STa Authorization response", "AA-Answer", "5.2.2.3.4"),
            (
                "5.1.2.3.1/5",
                "STa Access Authentication and Authorization Request",
                _DER,
                "5.2.2.1.1",
            ),
            (
                "5.1.2.3.1/6",
                "Trusted non-3GPP Access Authentication and Authorization Answer",
                _DEA,
                "5.2.2.1.2",
            ),
        ),
    ),
    (
        "5.1.2.4.1",
        "says 'These procedures are based on the reuse of Diameter STR and STA"
        " commands as specified in IETF RFC 6733 [58]'; clause 5.2.2.4, 'Commands"
        " for Trusted non-3GPP Access network Initiated Session Termination',",
        (
            (
                "5.1.2.4.1/1",
                "STa Session Termination Request",
                "Session-Termination-Request",
                "5.2.2.4.1",
            ),
            (
                "5.1.2.4.1/2",
                "STa Session Termination Answer",
                "Session-Termination-Answer",
                "5.2.2.4.2",
            ),
        ),
    ),
    (
        "5.1.2.5.1",
        "says 'When ERP is used, the ERP re-authentication procedure shall be"
        " mapped to the Diameter-EAP-Request and Diameter-EAP-Answer command codes"
        " specified in IETF RFC 4072 [5]'; clause 5.2.2.1, 'Commands for STa"
        " PMIPv6 or GTPv2 or ERP (re-)authentication and authorization"
        " procedures',",
        (
            ("5.1.2.5.1/1", "STa ERP Re-authentication Request", _DER, "5.2.2.1.1"),
            ("5.1.2.5.1/2", "STa ERP Re-authentication Answer", _DEA, "5.2.2.1.2"),
        ),
    ),
    (
        "6.1.2.1.1",
        "says 'the SWd interface shall support the trusted non-3GPP access"
        " authentication and authorization procedure defined in clause 5.1.2.1',"
        " which clause 5.1.2.1.1 maps 'to the Diameter-EAP-Request and"
        " Diameter-EAP-Answer command codes', the 3GPP AAA Proxy forwarding 'the"
        " Diameter commands', and 'Table 6.1.2.1.1/1 describes the trusted"
        " non-3GPP access authentication and authorization request forwarded on"
        " the SWd interface'; clause 6.2.2.1.1, 'Commands for STa PMIPv6 or GTPv2"
        " authentication and authorization procedures',",
        (
            (
                "6.1.2.1.1-1",
                "Trusted non-3GPP Access Authentication and Authorization Request"
                " on SWd",
                _DER,
                "6.2.2.1.1.1",
            ),
        ),
    ),
    (
        "6.1.2.1.3",
        "says 'the SWd interface shall support the trusted non-3GPP access and"
        " service authorization information update procedure defined in clause"
        " 5.1.2.3', whose authorization request clause 5.1.2.3.1 maps to"
        " 'AA-Request and AA-Answer', and 'Table 6.1.2.1.3/1 describes the trusted"
        " non-3GPP access authorization request forwarded on the SWd interface';"
        " clause 6.2.2.1.3 says 'The ABNFs defined for the STa interface in clause"
        " 5.2.2.3 and in its clauses apply', and clause 5.2.2.3",
        (
            (
                "6.1.2.1.3/1",
                "Trusted Non-3GPP Access Authorization Request on SWd interface",
                "AA-Request",
                "5.2.2.3.3",
            ),
        ),
    ),
    (
        "7.1.2.1.1",
        "says 'The SWm reference point shall perform authentication and"
        " authorization based on the reuse of the DER/DEA command set defined in"
        " Diameter EAP application, IETF RFC 4072 [5]'; clause 7.2.2.1, 'Commands"
        " for SWm Authentication and Authorization Procedures',",
        (
            (
                "7.1.2.1.1/1",
                "Authentication and Authorization Request",
                _DER,
                "7.2.2.1.1",
            ),
            (
                "7.1.2.1.1/2",
                "Authentication and Authorization Answer",
                _DEA,
                "7.2.2.1.2",
            ),
        ),
    ),
    (
        "7.1.2.3.1",
        "says 'These procedures are based on the reuse of Diameter STR and STA"
        " commands as specified in IETF RFC 6733 [58]'; clause 7.2.2.2, 'Commands"
        " for ePDG Initiated Session Termination',",
        (
            (
                "7.1.2.3.1/1",
                "SWm Session Termination Request",
                "Session-Termination-Request",
                "7.2.2.2.1",
            ),
            (
                "7.1.2.3.1/2",
                "SWm Session Termination Answer",
                "Session-Termination-Answer",
                "7.2.2.2.2",
            ),
        ),
    ),
    (
        "7.1.2.4.1",
        "says 'This procedure is based on the reuse of NASREQ IETF RFC 4005 [4]"
        " ASR, ASA, STR and STA commands'; clause 7.2.2.3, 'Commands for 3GPP AAA"
        " Server Initiated Session Termination',",
        (
            (
                "7.1.2.4.1/1",
                "SWm Abort Session Request",
                "Abort-Session-Request",
                "7.2.2.3.1",
            ),
            (
                "7.1.2.4.1/2",
                "SWm Abort Session Answer",
                "Abort-Session-Answer",
                "7.2.2.3.2",
            ),
            (
                "7.1.2.4.1/3",
                "SWm Session Termination Request",
                "Session-Termination-Request",
                "7.2.2.3.3",
            ),
            (
                "7.1.2.4.1/4",
                "SWm Session Termination Answer",
                "Session-Termination-Answer",
                "7.2.2.3.4",
            ),
        ),
    ),
    (
        "7.1.2.5.1",
        "says 'This procedure is based on the Diameter commands Re-Auth-Request and"
        " Re-Auth-Answer specified in IETF RFC 6733 [58]. Information element"
        " contents for these messages shall be as shown in tables 7.1.2.5.1/1 and"
        " 7.1.2.5.1/2'; clause 7.2.2.4, 'Commands for Authorization Information"
        " Update',",
        (
            (
                "7.1.2.5.1/1",
                "SWm Authorization Information Update Request",
                "Re-Auth-Request",
                "7.2.2.4.1",
            ),
            (
                "7.1.2.5.1/2",
                "SWm Authorization Information Update Answer",
                "Re-Auth-Answer",
                "7.2.2.4.2",
            ),
        ),
    ),
    (
        "8.1.2.1.1",
        "is the Authentication Procedure, and clause 8.2.2.1 says the"
        " Multimedia-Authentication-Request (MAR) command 'is sent by the 3GPP AAA"
        " Server to the HSS in order to request security information. This"
        " corresponds to clause 8.1.2.1', the Multimedia-Authentication-Answer"
        " (MAA) 'is sent by a server in response'; the document",
        (
            (
                "8.1.2.1.1/1",
                "Authentication request",
                "Multimedia-Auth-Request",
                "8.2.2.1",
            ),
            (
                "8.1.2.1.1/2",
                "Authentication Data content - request",
                "Multimedia-Auth-Request",
                "8.2.2.1",
                "SIP-Auth-Data-Item",
            ),
            (
                "8.1.2.1.1/3",
                "Authentication Data content - request, synchronization failure",
                "Multimedia-Auth-Request",
                "8.2.2.1",
                "SIP-Auth-Data-Item",
            ),
            (
                "8.1.2.1.1/4",
                "Authentication answer",
                "Multimedia-Auth-Answer",
                "8.2.2.1",
            ),
            (
                "8.1.2.1.1/5",
                "Authentication Data content - response",
                "Multimedia-Auth-Answer",
                "8.2.2.1",
                "SIP-Auth-Data-Item",
            ),
        ),
    ),
    (
        "8.1.2.2.2.1",
        "is the UE/PDN Registration/DeRegistration Notification, and clause"
        " 8.2.2.3 says the Server-Assignment-Request (SAR) command 'is sent by the"
        " 3GPP AAA Server to the HSS; this corresponds to clause 8.1.2.2.2', the"
        " Server-Assignment-Answer (SAA) 'to confirm the registration,"
        " de-registration, user profile download or restoration procedure';"
        " the document",
        (
            (
                "8.1.2.2.2.1/1",
                "Non-3GPP IP Access Registration request",
                "Server-Assignment-Request",
                "8.2.2.3",
            ),
            (
                "8.1.2.2.2.1/2",
                "Non-3GPP IP Access Registration response",
                "Server-Assignment-Answer",
                "8.2.2.3",
            ),
        ),
    ),
    (
        "8.1.2.2.3.1",
        "is the Network Initiated De-Registration by HSS, and clause 8.2.2.4 says"
        " the Registration-Termination-Request (RTR) command 'is sent by a Diameter"
        " Multimedia server to a Diameter Multimedia client in order to request"
        " the de-registration of a user. This corresponds to clause 8.1.2.2.3',"
        " the Registration-Termination-Answer (RTA) 'is sent by a client in"
        " response'; the document",
        (
            (
                "8.3.2.3",
                "Network Initiated Deregistration by HSS request",
                "Registration-Termination-Request",
                "8.2.2.4",
            ),
            (
                "8.3.2.4",
                "Network Initiated Deregistration by HSS response",
                "Registration-Termination-Answer",
                "8.2.2.4",
            ),
        ),
    ),
    (
        "9.1.2.1.1",
        "says 'The S6b reference point performs authentication based on reuse of"
        " the DER/DEA command set defined in Diameter EAP'; clause 9.2.2.1,"
        " 'Commands for S6b DSMIPv6 Authorization Procedures',",
        (
            (
                "9.1.2.1/1",
                "Authentication and Authorization Request",
                _DER,
                "9.2.2.1.1",
            ),
            ("9.1.2.1/2", "Authentication and Authorization Answer", _DEA, "9.2.2.1.2"),
        ),
    ),
    (
        "9.1.2.2.1",
        "says 'The procedures are based on the reuse of NASREQ IETF RFC 4005 [4]"
        " AAR and AAA commands and the Diameter extensions defined for PMIP in"
        " IETF RFC 5779 [2]'; clause 9.2.2.2, 'Commands for S6b PMIPv6, GTPv2 or"
        " DSMIPv6 Authorization Procedures',",
        (
            ("9.1.2.2.1/1", "Authorization request", "AA-Request", "9.2.2.2.1"),
            ("9.1.2.2.1/2", "Authorization answer", "AA-Answer", "9.2.2.2.2"),
        ),
    ),
    (
        "9.1.2.3.1",
        "says 'These procedures are based on the reuse of Diameter STR and STA"
        " commands as specified in IETF RFC 6733 [58]'; clause 9.2.2.3, 'Commands"
        " for PDN GW Initiated Session Termination',",
        (
            (
                "9.1.2.3.1/1",
                "S6b Session Termination Request",
                "Session-Termination-Request",
                "9.2.2.3.1",
            ),
            (
                "9.1.2.3.1/2",
                "S6b Session Termination Answer",
                "Session-Termination-Answer",
                "9.2.2.3.2",
            ),
        ),
    ),
    (
        "9.1.2.4.1",
        "says 'This procedure is based on the reuse of NASREQ IETF RFC 4005 [4]"
        " ASR, ASA, STR and STA commands'; clause 9.2.2.4, 'Commands for 3GPP AAA"
        " Server Initiated Session Termination',",
        (
            (
                "9.1.2.4.1/1",
                "S6b Abort Session Request",
                "Abort-Session-Request",
                "9.2.2.4.1",
            ),
            (
                "9.1.2.4.1/2",
                "S6b Abort Session Answer",
                "Abort-Session-Answer",
                "9.2.2.4.2",
            ),
            (
                "9.1.2.4.1/3",
                "S6b Session Termination Request",
                "Session-Termination-Request",
                "9.2.2.4.3",
            ),
            (
                "9.1.2.4.1/4",
                "S6b Session Termination Answer",
                "Session-Termination-Answer",
                "9.2.2.4.4",
            ),
        ),
    ),
    (
        "9.1.2.5.1",
        "says 'This procedure is based on the reuse of Diameter RAR and RAA"
        " commands as specified in IETF RFC 6733 [58]. The information element"
        " content for these messages is shown in tables 9.1.2.5.1/1 and"
        " 9.1.2.5.1/2', and of the authorization procedure that follows, 'The"
        " authorization procedure for PMIPv6 or GTPv2 is described in the clause"
        " 9.1.2.2. Tables 9.1.2.5.1/3 and 9.1.2.5.1/4 describe the message"
        " contents in case of DSMIPv6', clause 9.1.2.2.1 being 'based on the"
        " reuse of NASREQ IETF RFC 4005 [4] AAR and AAA commands'; clauses"
        " 9.2.2.6, 'Commands for S6b Service Authorization Information Update"
        " Procedures', and 9.2.2.2, 'Commands for S6b PMIPv6, GTPv2 or DSMIPv6"
        " Authorization Procedures',",
        (
            (
                "9.1.2.5.1/1",
                "S6b Re-authorization request",
                "Re-Auth-Request",
                "9.2.2.6.1",
            ),
            (
                "9.1.2.5.1/2",
                "S6b Re-authorization response",
                "Re-Auth-Answer",
                "9.2.2.6.2",
            ),
            (
                "9.1.2.5.1/3",
                "Authorization Request when using DSMIPv6",
                "AA-Request",
                "9.2.2.2.1",
            ),
            (
                "9.1.2.5.1/4",
                "Authorization Answer when using DSMIPv6",
                "AA-Answer",
                "9.2.2.2.2",
            ),
        ),
    ),
    (
        "9.1.2.6.1",
        "is under 'Authorization Procedures when using MIPv4 FACoA' and says 'The"
        " procedures are based on the reuse of NASREQ IETF RFC 4005 [4] AAR and AAA"
        " commands'; clause 9.2.2.5, 'Commands for S6b MIPv4 FACoA Authorization"
        " Procedures',",
        (
            ("9.1.2.6.1/1", "Authorization request", "AA-Request", "9.2.2.5.1"),
            ("9.1.2.6.1/2", "Authorization answer", "AA-Answer", "9.2.2.5.2"),
        ),
    ),
)


CORRECTIONS += [
    Correction(
        id=f"elements-{field.replace('_', '-')}-"
        + label.replace("/", "-").replace(".", "-"),
        target=information_elements(label),
        field=field,
        expect=None,
        replace=value,
        reason=f"clause {clause} {says} prints {command} at clause {section}; table"
        f" {label} is captioned '{caption}'"
        + (
            ""
            if within is None
            else f", the element tables 8.1.2.1.1/1 and /4 map to {within}"
        ),
        versions="18.6.0..19.2.0",
    )
    for clause, says, tables in _PROCEDURES
    for label, caption, command, section, *rest in tables
    for within in (rest[0] if rest else None,)
    for field, value in (
        ("command", command),
        ("command_section", section),
        *((("avp", within),) if within else ()),
    )
]


# Mapping cells of the tables above printing another spelling of the AVP than
# its defining clause's, which the command's ABNF spells right.
_ROWS = (
    (
        "EAP-payload",
        "EAP-Payload",
        "RFC 4072 clause 4.1.1 defines EAP-Payload, as the commands' ABNF prints it",
        (
            ("4.1.2.1/1", "EAP payload"),
            ("4.1.2.4.1/3", "EAP payload"),
            ("5.1.2.1/1", "EAP payload"),
            ("5.1.2.3.1/5", "EAP payload"),
            ("5.1.2.5.1/1", "EAP-Initiate"),
            ("6.1.2.1.1-1", "EAP payload"),
        ),
    ),
    (
        "Calling-Station-ID",
        "Calling-Station-Id",
        "RFC 4005 clause 4.6 spells its AVP Calling-Station-Id, as the"
        " Diameter-EAP-Requests' ABNF prints it",
        (
            ("4.1.2.1/1", "UE Layer-2 address"),
            ("5.1.2.1/1", "UE Layer-2 address"),
            ("6.1.2.1.1-1", "UE Layer-2 address"),
        ),
    ),
    (
        "Subscription-ID",
        "Subscription-Id",
        "RFC 4006 clause 8.46 spells its AVP Subscription-Id.",
        (
            ("5.1.2.1/2", "MSISDN"),
            ("5.1.2.3.1/4", "MSISDN"),
            ("5.1.2.3.1/6", "MSISDN"),
            ("7.1.2.1.1/2", "MSISDN"),
            ("7.1.2.2.1/2", "MSISDN"),
        ),
    ),
    (
        "Auth-Req-Type",
        "Auth-Request-Type",
        "RFC 6733 clause 8.7 defines Auth-Request-Type, which table 5.1.2.3.1/3"
        " maps the same 'Request-Type' element to",
        (("6.1.2.1.3/1", "Request-Type"),),
    ),
    (
        "SIP-AuthenticationScheme",
        "SIP-Authentication-Scheme",
        "the cell drops a hyphen: TS 29.229 clause 6.3.9 defines"
        " SIP-Authentication-Scheme, which SIP-Auth-Data-Item's body (clause"
        " 8.2.3.9) and table 8.1.2.1.1/2 print",
        (("8.1.2.1.1/5", "Authentication Method"),),
    ),
)

CORRECTIONS += [
    Correction(
        id=f"elements-{printed.lower()}-{label.replace('/', '-').replace('.', '-')}",
        target=element_row(information_elements(label), element),
        field="avps",
        expect=(printed,),
        replace=(name,),
        reason=reason,
        versions="18.6.0..19.2.0",
    )
    for printed, name, reason, rows in _ROWS
    for label, element in rows
]


# Table 7.1.2.5.3/1 lists the result codes of the answer of the procedure
# whose information elements tables 7.1.2.5.1/1 and /2 tabulate, whose
# commands are corrections above.
CORRECTIONS += [
    Correction(
        id=f"result-codes-{field.replace('_', '-')}-7-1-2-5-3",
        target=command_result_codes("7.1.2.5.3/1"),
        field=field,
        expect=None,
        replace=value,
        reason="table 7.1.2.5.3/1, 'Re-authorization Answer valid result codes', is"
        " in the detailed behaviour of the SWm authorization information update"
        " procedure, whose clause 7.1.2.5.1 says 'This procedure is based on the"
        " Diameter commands Re-Auth-Request and Re-Auth-Answer'; clause 7.2.2.4"
        " prints Re-Auth-Answer at clause 7.2.2.4.2, as table 7.1.2.5.1/2 is"
        " corrected",
        versions="18.6.0..19.2.0",
    )
    for field, value in (
        ("command", "Re-Auth-Answer"),
        ("command_section", "7.2.2.4.2"),
    )
]
