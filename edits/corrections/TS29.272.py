"""Corrections for 3GPP TS 29.272 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    avp_rule,
    definition,
    reused_avps,
    reused_row,
    table_row,
)

# The VCSG command headers print "< Diameter Header: 8388638, REQ, PXY, >" with
# the application id left empty. Clause 7.2.2 assigns these command codes to
# table 7.2.2/3 and states that "the Application-ID field shall be set to
# 16777308 (application identifier of the S7a/S7d interface application)", so
# the value is not in doubt — only the header is.
_S7A_S7D = 16777308

CORRECTIONS = [
    Correction(
        id=f"vcsg-application-id-{name.lower()}",
        target=definition(name),
        field="application_id",
        expect=None,
        replace=_S7A_S7D,
        reason="clause 7.2.2 assigns the VCSG commands to S7a/S7d (16777308);"
        " the command header omits the id",
        versions="18.6.0..18.7.0",
    )
    for name in (
        "Update-VCSG-Location-Request",
        "Update-VCSG-Location-Answer",
        "Cancel-VCSG-Location-Request",
        "Cancel-VCSG-Location-Answer",
    )
]

CORRECTIONS += [
    Correction(
        id="area-scope-code",
        target=definition("Area-Scope"),
        field="code",
        expect=1623,
        replace=1624,
        reason="clause 7.3.138's AVP header prints Job-Type's code; table"
        " 7.3.1/1 and the TS 29.230 registry both assign Area-Scope 1624",
        versions="18.6.0..18.7.0",
    ),
    Correction(
        id="wlan-offloadability-vendor-id",
        target=definition("WLAN-offloadability"),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason="clause 7.3.181's AVP header omits the vendor-id; table 7.3.1/1"
        " marks the V flag mandatory for it, as for every other AVP the"
        " specification defines",
        versions="18.6.0..18.7.0",
    ),
    # Two AVPs the ABNF appears to reference without the document introducing
    # them turned out to be spelling mismatches against table 7.3.1/1 — the
    # references resolve once one side is spelled the way the defining clause
    # heading spells it.
    Correction(
        id="additional-context-identifier-name",
        target=table_row("Additional-Context-ID"),
        field="name",
        expect="Additional-Context-ID",
        replace="Additional-Context-Identifier",
        reason="clause 7.3.206's heading and body, and the ABNF reference in"
        " clause 7.3.34, all spell it Additional-Context-Identifier; only the"
        " table row abbreviates it",
        versions="18.6.0..18.7.0",
    ),
    Correction(
        id="re-synchronization-info-case",
        target=avp_rule(
            "Requested-EUTRAN-Authentication-Info", "Re-synchronization-Info"
        ),
        field="name",
        expect="Re-synchronization-Info",
        replace="Re-Synchronization-Info",
        reason="clause 7.3.15's heading and table 7.3.1/1 both spell it"
        " Re-Synchronization-Info; clause 7.3.11's ABNF lower-cases the S",
        versions="18.6.0..18.7.0",
    ),
    # Three re-printed grouped bodies use member AVPs that table 7.3.1/2
    # omits while listing the grouped AVPs themselves and, for
    # Communication-Pattern-Set, three of its eight members
    # (Reference-ID-Validity-Time, Traffic-Profile, Battery-Indicator).
    *(
        Insert(
            id=f"missing-row-{name.lower()}",
            into=reused_avps("7.3.1/2"),
            node=ast.ReusedAvpRow(name=name, origin=origin),
            after=after,
            reason=f"the {parent} body (clause {clause}) uses {name} but"
            f" table 7.3.1/2 omits the row; {origin} defines the AVP",
            versions="18.6.0..18.7.0",
        )
        for name, origin, after, parent, clause in (
            (
                "MIP6-Home-Link-Prefix",
                "RFC5447",
                "MIP6-Agent-Info",
                "MIP6-Agent-Info",
                "7.3.45",
            ),
            (
                "ProSe-Permission",
                "TS29.344",
                "ProSe-Subscription-Data",
                "ProSe-Subscription-Data",
                "7.3.180",
            ),
            (
                "Periodic-Communication-Indicator",
                "TS29.336",
                "Communication-Pattern-Set",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Communication-Duration-Time",
                "TS29.336",
                "Periodic-Communication-Indicator",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Periodic-Time",
                "TS29.336",
                "Communication-Duration-Time",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Scheduled-Communication-Time",
                "TS29.336",
                "Periodic-Time",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
            (
                "Stationary-Indication",
                "TS29.336",
                "Scheduled-Communication-Time",
                "Communication-Pattern-Set",
                "7.3.194",
            ),
        )
    ),
]

# TS 29.217, which defines both AVPs, spells them eNodeB-Id and
# Extended-eNodeB-Id in its table 5.3.1.1, the defining clauses and its
# Congestion-Location-Id body; this document's re-used table and the
# MME-Location-Information body (clause 7.3.115) capitalise the D.
CORRECTIONS += [
    correction
    for printed, name, clause in (
        ("eNodeB-ID", "eNodeB-Id", "5.3.10"),
        ("Extended-eNodeB-ID", "Extended-eNodeB-Id", "5.3.15"),
    )
    for correction in (
        Correction(
            id=f"{name.lower()}-row-spelling",
            target=reused_row(printed),
            field="name",
            expect=printed,
            replace=name,
            reason=f"the re-used row cites TS 29.217, which defines {name}"
            f" (clause {clause})",
            versions="18.7.0",
        ),
        Correction(
            id=f"{name.lower()}-in-mme-location-information",
            target=avp_rule("MME-Location-Information", printed),
            field="name",
            expect=printed,
            replace=name,
            reason="the MME-Location-Information body (clause 7.3.115) uses the"
            f" re-used row's spelling; TS 29.217 defines {name}",
            versions="18.7.0",
        ),
    )
]
