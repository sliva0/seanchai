"""Corrections for 3GPP TS 29.061 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_table, table_row

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
