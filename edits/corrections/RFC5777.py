"""Corrections for RFC 5777 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_rule, definition, table_row

CORRECTIONS = [
    Correction(
        id="ip-mask-bit-mask-width-name",
        target=avp_rule("IP-Address-Mask", "IP-Bit-Mask-Width"),
        field="name",
        expect="IP-Bit-Mask-Width",
        replace="IP-Mask-Bit-Mask-Width",
        reason="the IP-Address-Mask ABNF (clause 4.1.7.6) writes"
        " IP-Bit-Mask-Width, as clause 4.1.7.7's body and the section 7.6"
        " example do, where the clause's heading and the allocation table"
        " (section 10.1) say IP-Mask-Bit-Mask-Width; verified erratum 2335"
        " corrects every IP-Bit-Mask-Width to IP-Mask-Bit-Mask-Width, the"
        " name IANA registered for 523",
    ),
    Correction(
        id="treatment-action-type",
        target=table_row("Treatment-Action"),
        field="data_type",
        expect=ast.DataType.GROUPED,
        replace=ast.DataType.ENUMERATED,
        reason="the allocation table (section 10.1) says Grouped, but clause"
        " 5.1 defines Treatment-Action as 'of type Enumerated' and lists its"
        " values 0 drop / 1 shape / 2 mark / 3 permit; verified erratum 2334"
        " corrects the table's type to Enumerated",
    ),
]

# Verified erratum 2333 (section 4.2.1): "3 AVPs are omitted in the ABNF for
# the Time-Of-Day-Condition AVP", each defined in its own clause and
# tabulated in section 10.1.
CORRECTIONS += [
    Insert(
        id=f"time-of-day-condition-{name.lower()}",
        into=definition("Time-Of-Day-Condition"),
        node=ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL),
        after=after,
        reason=f"clause {clause} defines {name}, which the Time-Of-Day-Condition"
        " ABNF (clause 4.2.1) omits; verified erratum 2333 adds it after"
        f" {after}",
    )
    for name, after, clause in (
        ("Absolute-Start-Fractional-Seconds", "Absolute-Start-Time", "4.2.8"),
        ("Absolute-End-Fractional-Seconds", "Absolute-End-Time", "4.2.10"),
        ("Timezone-Offset", "Timezone-Flag", "4.2.12"),
    )
]
