"""Corrections for OMA-DDS-Charging_Data — see docs/corrections.md.

The input is the transcription
(`raw/oma/dds-charging_data-v1_0-20110201-a.raw.dad`), which records what the
PDF prints."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Delete,
    definition,
    header,
    reused_row,
    table_row,
)

# Table 11's Reference column cites clause 8.5.11, Service-Information, for AVPs
# with a clause of their own, and 8.5.7 for IM-Information, whose clause is
# 8.5.6: the clauses were renumbered and the column kept the old numbers.
_CLAUSES = {
    "Accounting-Record-Type": ("8.5.11", "8.5.2"),
    "Acct-Application-Id": ("8.5.11", "8.5.1"),
    "Auth-Application-Id": ("8.5.11", "8.5.3"),
    "CC-Request-Type": ("8.5.11", "8.5.4"),
    "DCD-Information": ("8.5.11", "8.5.5"),
    "IM-Information": ("8.5.7", "8.5.6"),
    "Requested-Action": ("8.5.11", "8.5.8"),
    "Service-Context-Id": ("8.5.11", "8.5.9"),
    "Service-Generic-Information": ("8.5.11", "8.5.10"),
}

# Table 11 cites [TS32.299] for these, and TS 32.299 table 7.2.0.1 types each
# "refer [223]", this document: each points at the other. TS 32.299 prints no
# clause for them, and clause 7.2.0 says of its table that "for AVPs that are
# just borrowed from other applications only the reference ... is provided", so
# the row here is what defines them. Its type and flags are table 11's.
_BORROWED_BACK = (
    "Application-Server-ID",
    "Application-Service-Type",
    "Application-Session-ID",
    "Content-ID",
    "Content-provider-ID",
    "Delivery-Status",
    "Number-Of-Messages-Successfully-Exploded",
    "Number-Of-Messages-Successfully-Sent",
    "Total-Number-Of-Messages-Exploded",
    "Total-Number-Of-Messages-Sent",
)

# Table 11's Value Type against the document its Reference cites: TS 32.299
# V11.20.0 and V19.0.0, the releases the corpus holds, agree with each other.
_TYPES = {
    "Low-Balance-Indication": (ast.DataType.GROUPED, ast.DataType.ENUMERATED),
    "Originator": (ast.DataType.UTF8_STRING, ast.DataType.ENUMERATED),
    "Time-Quota-Threshold": (ast.DataType.UNSIGNED64, ast.DataType.UNSIGNED32),
    "Volume-Quota-Threshold": (ast.DataType.UNSIGNED64, ast.DataType.UNSIGNED32),
}

# Rows citing [RFC3588], which the corpus reads as RFC 6733.
_BASE = (
    "Accounting-Record-Number",
    "Acct-Interim-Interval",
    "Destination-Host",
    "Destination-Realm",
    "Event-Timestamp",
    "Failed-AVP",
    "Origin-Host",
    "Origin-Realm",
    "Origin-State-Id",
    "Proxy-Host",
    "Proxy-Info",
    "Proxy-State",
    "Redirect-Host",
    "Redirect-Host-Usage",
    "Redirect-Max-Cache-Time",
    "Result-Code",
    "Route-Record",
    "Session-Id",
    "Termination-Cause",
    "User-Name",
)

CORRECTIONS = [
    Correction(
        id="bases-dcca",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "RFC4006"),
        reason="clauses 8.2.1 and 8.2.2 print CCR and CCA with RFC 4006's"
        " CC-Sub-Session-Id, CC-Correlation-Id and Service-Parameter-Info, which"
        " table 11 omits; clause 8.5.3 says 'the protocol used on CH-2 is Diameter"
        " Credit Control', [RFC4006]",
        versions="1.0",
    ),
    Correction(
        id="service-generic-information-name",
        target=definition("Services-Generic-Information"),
        field="name",
        expect="Services-Generic-Information",
        replace="Service-Generic-Information",
        reason="clause 8.5.10's rule prints 'Services-'; its heading and sentence,"
        " table 11 and TS 32.299 table 7.2.0.1 name the AVP"
        " Service-Generic-Information",
        versions="1.0",
    ),
    *(
        Correction(
            id=f"{name.lower()}-vendor",
            target=definition(printed),
            field="vendor_id",
            expect=None,
            replace=10415,
            reason=f"clause {clause}'s header prints only the code; table 11"
            " gives the AVP vendor 10415",
            versions="1.0",
        )
        for name, printed, clause in (
            ("dcd-information", "DCD-Information", "8.5.5"),
            ("im-information", "IM-Information", "8.5.6"),
            (
                "service-generic-information",
                "Services-Generic-Information",
                "8.5.10",
            ),
        )
    ),
    *(
        Correction(
            id=f"{name.lower()}-clause",
            target=table_row(name, table="11"),
            field="section",
            expect=printed,
            replace=clause,
            reason=f"table 11 cites [{printed}] for {name}, which clause {clause}"
            " heads",
            versions="1.0",
        )
        for name, (printed, clause) in _CLAUSES.items()
    ),
    *(
        Correction(
            id=f"{name.lower()}-origin",
            target=reused_row(name),
            field="origin",
            expect="RFC3588",
            replace="RFC6733",
            reason=f"table 11 cites [RFC3588] for {name}; the corpus reads the"
            " base protocol as RFC 6733, which obsoletes it and defines the AVP",
            versions="1.0",
        )
        for name in _BASE
    ),
    *(
        Delete(
            id=f"{name.lower()}-borrowed-back",
            target=reused_row(name),
            expect=ast.ReusedAvpRow(name=name, origin="TS32.299"),
            reason=f"table 11 cites [TS32.299] for {name}, and TS 32.299 table"
            " 7.2.0.1 prints only 'refer [223]', this document, with no clause of"
            " its own; table 11's row is the definition either citation reaches",
            versions="1.0",
        )
        for name in _BORROWED_BACK
    ),
    *(
        Correction(
            id=f"{name.lower()}-type",
            target=table_row(name, table="11"),
            field="data_type",
            expect=printed,
            replace=meant,
            reason=f"table 11 types {name} {printed} and cites [TS32.299], whose"
            f" table 7.2 (V11.20.0) and table 7.2.0.1 (V19.0.0) both type it {meant}",
            versions="1.0",
        )
        for name, (printed, meant) in _TYPES.items()
    ),
    Correction(
        id="accumulated-cost-used-in",
        target=table_row("Accumulated-Cost", table="11"),
        field="marks",
        expect={
            ast.MarkColumn.ACR: (),
            ast.MarkColumn.ACA: (),
            ast.MarkColumn.CCR: ("O",),
            ast.MarkColumn.CCR_MSCC: (),
            ast.MarkColumn.CCA: (),
            ast.MarkColumn.CCA_MSCC: (),
        },
        replace={
            ast.MarkColumn.ACR: (),
            ast.MarkColumn.ACA: (),
            ast.MarkColumn.SI: ("O",),
            ast.MarkColumn.CCR: (),
            ast.MarkColumn.CCR_MSCC: (),
            ast.MarkColumn.CCA: (),
            ast.MarkColumn.CCA_MSCC: (),
        },
        reason="table 11 leaves SI blank and marks CCR O for Accumulated-Cost; clause"
        " 6.1.4's table 4 holds it under AoC Information, and every other AoC row"
        " of table 11 (Incremental-Cost, AoC-Cost-Information) is O under SI and"
        " '-' under CCR",
        versions="1.0",
    ),
]
