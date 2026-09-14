"""Corrections for RFC 5777 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, table_row

CORRECTIONS = [
    Correction(
        id="ip-bit-mask-width-name",
        target=table_row("IP-Mask-Bit-Mask-Width"),
        field="name",
        expect="IP-Mask-Bit-Mask-Width",
        replace="IP-Bit-Mask-Width",
        reason="only clause 4.1.7.7's heading and the allocation table"
        " (section 10.1) say IP-Mask-Bit-Mask-Width; the clause's own body"
        " ('The IP-Bit-Mask-Width AVP (AVP Code 523)'), the IP-Address-Mask"
        " ABNF that carries it, and the section 8.3 example all say"
        " IP-Bit-Mask-Width, and Wireshark's dictionary reads it the same way",
    ),
    Correction(
        id="treatment-action-type",
        target=table_row("Treatment-Action"),
        field="data_type",
        expect=ast.DataType.GROUPED,
        replace=ast.DataType.ENUMERATED,
        reason="the allocation table (section 10.1) says Grouped, but clause"
        " 5.1 defines Treatment-Action as 'of type Enumerated' and lists its"
        " values 0 drop / 1 shape / 2 mark / 3 permit; Wireshark's dictionary"
        " also carries it as Enumerated with those values",
    ),
]
