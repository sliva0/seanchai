"""Corrections for 3GPP2 X.S0013-014 — see docs/corrections.md.

The input is the transcription (`raw/3gpp2/xs0013-014-0_v1.0.raw.dad`), which
records what the PDF prints. Clause 5.2.2: "The Vendor-Id header of all AVPs
defined in the present document shall be set to 10415 (3GPP) unless specified
otherwise. In other cases, as specified, the Vendor-Id shall be set to 5535
(3GPP2)."; the file's own vendor is the second, which table 5.1-2's clauses
each state, so table 5.1-1 states the first in a column of its own."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    avp_rule,
    avp_table,
    definition,
    enum_value,
    reused_row,
    table_row,
)

_COLUMNS = (
    ast.AvpColumn.NAME,
    ast.AvpColumn.CODE,
    ast.AvpColumn.SECTION,
    ast.AvpColumn.TYPE,
    ast.AvpColumn.MUST,
    ast.AvpColumn.MAY,
    ast.AvpColumn.SHOULD_NOT,
    ast.AvpColumn.MUST_NOT,
    ast.AvpColumn.ENCRYPT,
    ast.AvpColumn.ACCESS_TYPES,
)

_THREE_GPP_ROWS = (
    "Charging-Rule-Remove",
    "Charging-Rule-Base-Name",
    "Charging-Rule-Name",
    "Metering-Method",
    "Offline",
    "Online",
    "Precedence",
    "Reporting-Level",
    "QoS-Class-Identifier",
    "Access-Network-Charging-Identifier-Ty",
    "PCC-Rule-Status",
    "Guaranteed-Bitrate-UL",
    "Guaranteed-Bitrate-DL",
)

_THREE_GPP_GROUPS = [
    ("Charging-Rule-Remove", "5.2.2.3"),
    ("Access-Network-Charging-Identifier-Ty", "5.2.2.29"),
]

_THREE_GPP2_GROUPS = [
    ("Charging-Rule-Install", "5.2.2.2"),
    ("Charging-Rule-Definition", "5.2.2.4"),
    ("QoS-Information", "5.2.2.16"),
    ("Charging-Rule-Report", "5.2.2.18"),
    ("Flow-Info", "5.2.2.22"),
    ("Granted-QoS", "5.2.2.25"),
    ("Requested-QoS", "5.2.2.26"),
    ("Flow-Description-Info", "5.2.2.30"),
]

CORRECTIONS = [
    Correction(
        id="vendor-id-column",
        target=avp_table("5.1-1"),
        field="columns",
        expect=_COLUMNS,
        replace=(_COLUMNS[0], ast.AvpColumn.VENDOR, *_COLUMNS[1:]),
        reason="clause 5.2.2: table 5.1-1 'describes the 3GPP Diameter AVPs' and"
        " their Vendor-Id header 'shall be set to 10415 (3GPP)', which no cell of"
        " the table can state in a file of 3GPP2's vendor",
        versions="1.0",
    ),
    Correction(
        id="experimental-result-vendor-id-case",
        target=avp_rule("Experimental-Result", "Vendor-ID"),
        field="name",
        expect="Vendor-ID",
        replace="Vendor-Id",
        reason="clause 5.2.1.5.1's format upper-cases the 'D'; its next sentence"
        " writes Vendor-Id AVP, as RFC 3588, which it cites for the AVP, defines it",
        versions="1.0",
    ),
    Correction(
        id="called-station-id-row-case",
        target=reused_row("Called-Station-ID"),
        field="name",
        expect="Called-Station-ID",
        replace="Called-Station-Id",
        reason="table 5.3 upper-cases the 'D'; RFC 4005, which it cites, defines"
        " Called-Station-Id",
        versions="1.0",
    ),
    Correction(
        id="ccr-called-station-id-case",
        target=avp_rule("CC-Request", "Called-Station-ID"),
        field="name",
        expect="Called-Station-ID",
        replace="Called-Station-Id",
        reason="the CCR format (clause 5.2.1.1) upper-cases the 'D'; RFC 4005,"
        " which table 5.3 cites for it, defines Called-Station-Id",
        versions="1.0",
    ),
    Correction(
        id="service-identifier-level-spelling",
        target=enum_value("Reporting-Level", "SERVICE_IDENTIFIER _LEVEL", value=0),
        field="name",
        expect="SERVICE_IDENTIFIER _LEVEL",
        replace="SERVICE_IDENTIFIER_LEVEL",
        reason="clause 5.2.2.12 prints a space inside the value's name; its other"
        " value is RATING_GROUP_LEVEL, and the value names of the document hold"
        " none but RAT-Type's and PCC-Rule-Status's two words",
        versions="1.0",
    ),
]

CORRECTIONS += (
    [
        Correction(
            id=f"{name.lower()}-row-vendor",
            target=table_row(name, table="5.1-1"),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason="clause 5.2.2: table 5.1-1's AVPs are 3GPP's, whose Vendor-Id header"
            " 'shall be set to 10415 (3GPP)'",
            versions="1.0",
        )
        for name in _THREE_GPP_ROWS
    ]
    + [
        Correction(
            id=f"{name.lower()}-vendor",
            target=definition(name, section=section),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason=f"clause {section}'s AVP format omits the vendor-id; clause 5.2.2"
            " sets it to '10415 (3GPP) unless specified otherwise', and the clause"
            " specifies nothing else",
            versions="1.0",
        )
        for name, section in _THREE_GPP_GROUPS
    ]
    + [
        Correction(
            id=f"{name.lower()}-vendor",
            target=definition(name, section=section),
            field="vendor_id",
            expect=None,
            replace=5535,
            reason=f"clause {section}'s AVP format omits the vendor-id; its sentence"
            " says 'The 3GPP2 vendor ID shall be used for this AVP'",
            versions="1.0",
        )
        for name, section in _THREE_GPP2_GROUPS
    ]
)
