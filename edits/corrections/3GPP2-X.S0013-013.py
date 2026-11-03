"""Corrections for 3GPP2 X.S0013-013 — see docs/corrections.md.

The input is the transcription (`raw/3gpp2/xs0013-013-0_v1.0.raw.dad`), which
records what the PDF prints. Clause 5.5 sets the Vendor-Id header of table
5.1-1's AVPs to 10415 (3GPP) and of table 5.1-2's to 5535 (3GPP2), the file's
own, so table 5.1-1 states the former in a column of its own. That table's clause
cells run ahead of the clauses from Flow-Number on: it counts one clause more
before 5.5.9, and another before 5.5.14, than the document numbers."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    avp_rule,
    avp_table,
    definition,
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
)

_THREE_GPP_ROWS = (
    "Abort-Cause",
    "Access-Network-Charging-Address",
    "Access-Network-Charging-Identifier",
    "Access-Network-Charging-Identifier-Value",
    "AF-Application-Identifier",
    "AF-Charging-Identifier",
    "Codec-Data",
    "Flow-Description",
    "Flow-Number",
    "Flows",
    "Flow-Status",
    "Flow-Usage",
    "Specific-Action",
    "Max-Requested-Bandwidth-DL",
    "Max-Requested-Bandwidth-UL",
    "Media-Component-Description",
    "Media-Component-Number",
    "Media-Sub-Component",
    "Media-Type",
    "RR-Bandwidth",
    "RS-Bandwidth",
    "SIP-Forking-Indication",
)

# (row, what the cell prints, the clause heading the AVP).
_CLAUSES = [
    ("Flow-Number", "5.5.10", "5.5.9"),
    ("Flows", "5.5.11", "5.5.10"),
    ("Flow-Status", "5.5.12", "5.5.11"),
    ("Flow-Usage", "5.5.13", "5.5.12"),
    ("Specific-Action", "5.5.14", "5.5.13"),
    ("Max-Requested-Bandwidth-DL", "5.5.16", "5.5.14"),
    ("Max-Requested-Bandwidth-UL", "5.5.17", "5.5.15"),
    ("Media-Component-Description", "5.5.18", "5.5.16"),
    ("Media-Component-Number", "5.5.19", "5.5.17"),
    ("Media-Sub-Component", "5.5.20", "5.5.18"),
    ("Media-Type", "5.5.21", "5.5.19"),
    ("RR-Bandwidth", "5.5.22", "5.5.20"),
    ("RS-Bandwidth", "5.5.23", "5.5.21"),
    ("SIP-Forking-Indication", "5.5.24", "5.5.22"),
]

_THREE_GPP_GROUPS = [
    ("Access-Network-Charging-Identifier", "5.5.3"),
    ("Flows", "5.5.10"),
    ("Media-Component-Description", "5.5.16"),
    ("Media-Sub-Component", "5.5.18"),
]

CORRECTIONS = [
    Correction(
        id="vendor-id-column",
        target=avp_table("5.1-1"),
        field="columns",
        expect=_COLUMNS,
        replace=(_COLUMNS[0], ast.AvpColumn.VENDOR, *_COLUMNS[1:]),
        reason="clause 5.5: 'The Vendor-Id header of all 3GPP Diameter AVPs defined"
        " in the present document shall be set to 10415 (3GPP)', which no cell of"
        " table 5.1-1 can state in a file of 3GPP2's vendor",
        versions="1.0",
    ),
    Correction(
        id="experimental-result-vendor-id-case",
        target=avp_rule("Experimental-Result", "Vendor-ID"),
        field="name",
        expect="Vendor-ID",
        replace="Vendor-Id",
        reason="clause 5.4.1's format upper-cases the 'D'; its next sentence writes"
        " Vendor-Id AVP, as RFC 3588, which it cites for the AVP, defines it",
        versions="1.0",
    ),
    Correction(
        id="sip-forking-indication-name",
        target=definition("SIP_Forking"),
        field="name",
        expect="SIP_Forking",
        replace="SIP-Forking-Indication",
        reason="clause 5.5.22's sentence names the AVP SIP_Forking; its heading,"
        " table 5.1-1 (code 523) and the AAR format name SIP-Forking-Indication",
        versions="1.0",
    ),
    Correction(
        id="access-network-physical-access-id-vendor",
        target=definition("Access-Network-Physical-Access-ID"),
        field="vendor_id",
        expect=None,
        replace=5535,
        reason="clause 5.5.23's AVP format omits the vendor-id; its sentence says"
        " 'The 3GPP2 vendor ID 5535 shall be used for this AVP'",
        versions="1.0",
    ),
]

CORRECTIONS += (
    [
        Correction(
            id=f"{command.lower()}-subscription-id-case",
            target=avp_rule(command, "Subscription-ID"),
            field="name",
            expect="Subscription-ID",
            replace="Subscription-Id",
            reason=f"the format of clause {clause} upper-cases the 'd'; table 5.6.1 and"
            " RFC 4006, which it cites, spell Subscription-Id",
            versions="1.0",
        )
        for command, clause in [("AA-Request", "5.3.1"), ("RA-Request", "5.3.3")]
    ]
    + [
        Correction(
            id=f"{name.lower()}-row-vendor",
            target=table_row(name, table="5.1-1"),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason="clause 5.5: table 5.1-1's AVPs are 3GPP's, whose Vendor-Id header"
            " 'shall be set to 10415 (3GPP)'",
            versions="1.0",
        )
        for name in _THREE_GPP_ROWS
    ]
    + [
        Correction(
            id=f"{name.lower()}-row-clause",
            target=table_row(name, table="5.1-1"),
            field="section",
            expect=printed,
            replace=heading,
            reason=f"table 5.1-1 prints clause {printed}, which heads another AVP or"
            f" none; clause {heading} heads and defines {name}",
            versions="1.0",
        )
        for name, printed, heading in _CLAUSES
    ]
    + [
        Correction(
            id=f"{name.lower()}-vendor",
            target=definition(name, section=section),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason=f"clause {section}'s AVP format omits the vendor-id; clause 5.5 sets"
            " that of 'all 3GPP Diameter AVPs defined in the present document' to 10415"
            " (3GPP), and table 5.1-1 lists the AVP",
            versions="1.0",
        )
        for name, section in _THREE_GPP_GROUPS
    ]
)
