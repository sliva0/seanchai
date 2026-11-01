"""Corrections for 3GPP TS 29.061 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    Supply,
    avp_table,
    definition,
    table_row,
)

CORRECTIONS = [
    Correction(
        id="mbms-flags-name",
        target=table_row("MBMS-Flag"),
        field="name",
        expect="MBMS-Flag",
        replace="MBMS-Flags",
        reason="only the table cell drops the s; clause 20.5a.9's heading,"
        " prose and value table all write MBMS-Flags, and Wireshark's"
        " dictionary reads it the same way",
        versions="18.1.0",
    ),
    Insert(
        id="session-stop-indicator-row",
        into=avp_table("9a"),
        node=ast.AvpTableRow(
            name="3GPP-Session-Stop-Indicator",
            code=11,
            section="16.4.7",
            flag_rules=ast.AvpFlagRules(),
        ),
        after="3GPP-NSAPI",
        reason="clause 16.4.7.2 codes sub-attribute 11, 3GPP-Session-Stop-Indicator,"
        " among the others table 9a lists, but the table skips it; TS 32.299"
        " table 7.2.0.1 re-uses it from here. Only the name, code and clause"
        " are stated: the clause gives no Diameter type or flags",
        versions="18.1.0",
    ),
]

# TS 29.210 V6.7.0 table 5.3 re-uses these two from here, meaning Release 6's
# last version (its clause 2 [11] is non-specific). V6.15.0 tabulates neither:
# table 10, its only AVP table, is Gmb's, and clause 16.4.7 lists them as RADIUS
# sub-attributes, by number and with no Diameter type or flag rule.
CORRECTIONS += [
    Insert(
        id=f"{name.lower()}-row",
        into=avp_table("10"),
        node=ast.AvpTableRow(
            name=name,
            code=code,
            section="16.4.7",
            flag_rules=ast.AvpFlagRules(),
        ),
        after="MBMS-Counting-Information",
        reason=f"clause 16.4.7 codes sub-attribute {code}, {name}, and TS 29.210"
        " V6.7.0 table 5.3 re-uses it from here, but table 10 skips it. Only the"
        " name, code and clause are stated: the clause gives no Diameter type or"
        " flags",
        versions="6.15.0",
    )
    for name, code in (
        ("3GPP-GPRS-Negotiated-QoS-Profile", 5),
        ("3GPP-SGSN-MCC-MNC", 18),
    )
]

# Values the document takes from another.
CORRECTIONS += [
    Supply(
        id="mbms-hc-indicator-values",
        target=definition("MBMS-HC-Indicator"),
        expect="3GPP TS 25.413 [92]",
        values=(
            ast.EnumValue(name="uncompressed-header", value=0),
            ast.EnumValue(name="compressed-header", value=1),
        ),
        reason="TS 25.413 V18.0.0 (2024-03), the only Release 18 version,"
        " clause 9.2.1.84 types MBMS HC Indicator 'ENUMERATED (uncompressed"
        " header, compressed header, ...)', and its ASN.1 MBMSHCIndicator"
        " lists uncompressed-header, then compressed-header, then the"
        " extension marker. The ASN.1 numbers nothing: 0 and 1 are"
        " the declaration order, X.680's ordinal numbering, a judgement"
        " Wireshark's dictionary shares; the names are the ASN.1 identifiers",
        versions="18.1.0",
    ),
]
