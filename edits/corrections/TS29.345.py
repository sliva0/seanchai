"""Corrections for 3GPP TS 29.345 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import (
    Correction,
    Insert,
    avp_rule,
    definition,
    header,
    table_row,
)

CORRECTIONS = [
    Correction(
        id="wlan-link-layer-id-type",
        target=table_row("WLAN-Link-Layer-Id"),
        field="data_type",
        expect=ast.DataType.OCTET_STRING,
        replace=ast.DataType.GROUPED,
        reason="clause 6.3.32 explicitly defines this AVP as Grouped and gives"
        " its grouped rule; table 6.3.1/1 incorrectly says OctetString",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="prose-restricted-code-suffix-range-type",
        target=table_row("ProSe-Restricted-Code-Suffix-Range"),
        field="data_type",
        expect=ast.DataType.OCTET_STRING,
        replace=ast.DataType.GROUPED,
        reason="clause 6.3.68 explicitly defines this AVP as Grouped and gives"
        " its grouped rule; table 6.3.1/1 incorrectly says OctetString",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="code-receiving-security-material-code",
        target=definition("Code-Receiving-Security-Material"),
        field="code",
        expect=3847,
        replace=3860,
        reason="table 6.3.1/1 assigns this AVP code 3860; clause 6.3.75's rule"
        " repeats code 3847 from ProSe-Restricted-Code-Suffix-Range",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="code-sending-security-material-code",
        target=definition("Code-Sending-Security-Material"),
        field="code",
        expect=3847,
        replace=3861,
        reason="table 6.3.1/1 assigns this AVP code 3861; clause 6.3.76's rule"
        " repeats code 3847 from ProSe-Restricted-Code-Suffix-Range",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="prose-app-code-suffix-range-code",
        target=definition("ProSe-App-Code-Suffix-Range"),
        field="code",
        expect=3847,
        replace=3867,
        reason="table 6.3.1/1 assigns this AVP code 3867; clause 6.3.82's rule"
        " repeats code 3847 from ProSe-Restricted-Code-Suffix-Range",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="prose-app-code-suffix-range-type",
        target=table_row("ProSe-App-Code-Suffix-Range"),
        field="data_type",
        expect=ast.DataType.OCTET_STRING,
        replace=ast.DataType.GROUPED,
        reason="clause 6.3.82 explicitly defines this AVP as Grouped and gives"
        " its grouped rule; table 6.3.1/1 incorrectly says OctetString",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="wifi-p2p-assistance-info-spelling",
        target=avp_rule("WLAN-Assistance-Info", "WiFi-P2P-Assistance-Iinfo"),
        field="name",
        expect="WiFi-P2P-Assistance-Iinfo",
        replace="WiFi-P2P-Assistance-Info",
        reason="the WLAN-Assistance-Info body (clause 6.3.31) doubles the i;"
        " clause 6.3.30 defines WiFi-P2P-Assistance-Info and table 6.3.1-1"
        " spells it the same way",
        versions="18.0.0..19.0.0",
    ),
    # The Discovery-Auth-Request/Match-Report-Info bodies (clauses 6.3.53,
    # 6.3.56) capitalize the D of ProSe-App-Id, which clause 6.3.17 defines
    # and table 6.3.1-1 lists; the same two bodies and the PAR command
    # (clause 6.2.3) write User-Identity for User-Identifier, the TS 29.336
    # AVP their information-element tables name and which table 6.3.1-2
    # lists as re-used — no AVP named User-Identity exists in this document
    # or its citations, and the listed User-Identifier row is otherwise
    # referenced by nothing. The Match-Request body (clause 6.3.55) does the
    # same, as an input patch prints it, and capitalizes the d of
    # Visited-PLMN-Id, which table 6.3.1-2 lists.
    *(
        Correction(
            id=f"{parent.lower()}-{wrong.lower()}",
            target=avp_rule(parent, wrong),
            field="name",
            expect=wrong,
            replace=right,
            reason=f"the {parent} body writes {wrong}; the AVP is {right} —"
            " see the block comment above",
            versions="18.0.0..19.0.0",
        )
        for parent, wrong, right in (
            ("Discovery-Auth-Request", "ProSe-App-ID", "ProSe-App-Id"),
            ("Match-Report-Info", "ProSe-App-ID", "ProSe-App-Id"),
            ("ProSe-Authorization-Request", "User-Identity", "User-Identifier"),
            ("Discovery-Auth-Request", "User-Identity", "User-Identifier"),
            ("Match-Report-Info", "User-Identity", "User-Identifier"),
            ("Match-Request", "User-Identity", "User-Identifier"),
            ("Match-Request", "Visited-PLMN-ID", "Visited-PLMN-Id"),
        )
    ),
]

# Two members of clauses 6.3.53 and 6.3.54 that nothing defines
# (docs/linter.md#standing-findings). Searched: V18.0.0 and V19.0.0, the TS
# 29.230 registry, TS 29.343 and 29.344, and Wireshark's dictionary.
_SEARCHED = (
    " that no clause defines and table 6.3.1-1 does not list, in V18.0.0 as"
    " in V19.0.0; TS 29.230 table 7.1 allocates TS 29.345 3800-3868, none"
    " to it, and reserves 3869..3899; TS 29.343 (PC2) and 29.344 (PC4a) do"
    " not name it, and Wireshark's dictionary has no such AVP. The DUSK,"
    " DUIK and Encrypted-Bitmask clauses treat it as a discovery code like"
    " ProSe-Restricted-Code (3846, OctetString, 6.3.67), which is analogy,"
    " not a definition. Restricted discovery came with CR 0029r5"
    " (CP-150772, V13.0.0), and every version since carries the gap"
)

CORRECTIONS += [
    Insert(
        id=f"undefined-{name.lower()}",
        into=header(),
        node=ast.UndefinedAvp(
            name=name,
            source=ast.SourceRef(section="6.3.53", page=53),
            note=f'"the Discovery-Auth-Request shall contain a UE identity, an'
            f' Application Identifier, Requesting RPAUID, a {words}"',
        ),
        after=None,
        reason=f"an optional member of Discovery-Auth-Request (6.3.53) and"
        f" Discovery-Auth-Response (6.3.54){_SEARCHED}; clause 6.3.53's prose"
        f" asks for it for Discovery-Type {case}",
        versions="18.0.0..19.0.0",
    )
    for name, words, case in (
        (
            "ProSe-Query-Code",
            "ProSe Query Code",
            "DISCOVERER_ANNOUNCING_REQUEST_FOR_RESTRICTED_PROSE_DIRECT_DISCOVERY",
        ),
        (
            "ProSe-Response-Code",
            "ProSe Response Code",
            "DISCOVEREE_REQUEST_FOR_RESTRICTED_PROSE_DIRECT_DISCOVERY",
        ),
    )
]
