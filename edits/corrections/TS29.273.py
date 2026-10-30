"""Corrections for TS 29.273; the raw file retains every printed definition."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Accept,
    Correction,
    Delete,
    Insert,
    avp_rule,
    definition,
    flag_rules,
    header,
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
    ),
    Correction(
        id="access-network-info-code",
        target=table_row("Access-Network-Info", table="8.2.3.0/1"),
        field="code",
        expect=1524,
        replace=1526,
        reason=(
            "Table 8.2.3.0/1 contradicts the defining header in clause"
            " 5.2.3.24 and tables 5.2.3.1/1 and 7.2.3.1/1: Access-Network-Info"
            " is 1526; 1524 is SSID."
        ),
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
    ),
    Insert(
        id="mip-home-agent-host-reused",
        into=reused_avps("9.2.3.3/1"),
        node=ast.ReusedAvpRow(name="MIP-Home-Agent-Host", origin="RFC4004"),
        after=None,
        reason="RFC 4004 clause 7.11 defines this member of MIP6-Agent-Info.",
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
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
        versions="18.6.0",
    ),
]
