"""Corrections for 3GPP TS 29.061 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, table_row

CORRECTIONS = [
    Correction(
        target=table_row("MBMS-Flag"),
        field="name",
        expect="MBMS-Flag",
        replace="MBMS-Flags",
        reason="only the table cell drops the s; clause 20.5a.9's heading,"
        " prose and value table all write MBMS-Flags, and Wireshark's"
        " dictionary reads it the same way",
        versions="18.1.0",
    ),
]
