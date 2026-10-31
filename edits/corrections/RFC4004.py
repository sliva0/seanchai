"""Corrections for RFC 4004 — see docs/corrections.md."""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, Insert, avp_rule, header, table_row

CORRECTIONS = [
    Correction(
        id="amr-session-id-case",
        target=avp_rule("AA-Mobile-Node-Request", "Session-ID"),
        field="name",
        expect="Session-ID",
        replace="Session-Id",
        reason="the AMR ABNF (clause 5.1) capitalizes the D; the AVP is the"
        " base protocol's Session-Id (code 263), spelled Session-Id in this"
        " document's every other ABNF",
    ),
    *(
        Correction(
            id=f"mip-nonce-case-{parent.lower()}",
            target=avp_rule(parent, "MIP-nonce"),
            field="name",
            expect="MIP-nonce",
            replace="MIP-Nonce",
            reason=f"the {parent} ABNF (clause {clause}) lowercases the"
            " name; clause 9.12 defines MIP-Nonce (code 335) and the AVP"
            " table spells it the same way",
        )
        for parent, clause in (
            ("MIP-MN-to-FA-MSA", "9.5"),
            ("MIP-MN-to-HA-MSA", "9.6"),
        )
    ),
    Correction(
        id="mn-to-ha-msa-spi-name",
        target=avp_rule("MIP-MN-to-HA-MSA", "MIP-MN-HA-SPI"),
        field="name",
        expect="MIP-MN-HA-SPI",
        replace="MIP-MN-to-HA-SPI",
        reason="the MIP-MN-to-HA-MSA ABNF (clause 9.6) writes MIP-MN-HA-SPI,"
        " where its prose says 'The HA allocates the MIP-MN-to-HA-SPI' and"
        " the command AVP table of clause 11.1 lists MIP-MN-to-HA-SPI;"
        " verified erratum 1462 corrects the name. No clause defines either"
        " spelling, and the printed one is RFC 5778's later MIPv6 AVP (code"
        " 491)",
    ),
    Correction(
        id="mn-to-fa-msa-spi-name",
        target=avp_rule("MIP-MN-to-FA-MSA", "MIP-MN-FA-SPI"),
        field="name",
        expect="MIP-MN-FA-SPI",
        replace="MIP-MN-to-FA-SPI",
        reason="the MIP-MN-to-FA-MSA ABNF (clause 9.5) writes MIP-MN-FA-SPI,"
        " where its prose says 'The FA allocates the MIP-MN-to-FA-SPI' and"
        " the command AVP table of clause 11.1 lists MIP-MN-to-FA-SPI, as"
        " erratum 1462 corrects clause 9.6's MIP-MN-HA-SPI to the"
        " MIP-MN-to-HA-SPI its prose and table use. No clause defines either"
        " spelling",
    ),
    Correction(
        id="mip-home-agent-host-type",
        target=table_row("MIP-Home-Agent-Host"),
        field="data_type",
        expect=ast.DataType.DIAMETER_IDENTITY,
        replace=ast.DataType.GROUPED,
        reason="table 7 says DiameterIdentity, but clause 7.11 explicitly"
        " defines MIP-Home-Agent-Host as Grouped and prints its grouped ABNF",
    ),
]

# Application ids the command headers omit and the prose states.
CORRECTIONS += [
    Insert(
        id="application-id",
        into=header(),
        node=ast.ApplicationScope(
            name="Diameter Mobile IPv4",
            source=ast.SourceRef(section="4", page=20),
            application_id=2,
            applies_to=("5.*",),
        ),
        after=None,
        reason=(
            "clause 4: 'The value of two (2) MUST be used as the Application-Id "
            "in all AMR/AMA and HAR/HAA commands'; the command headers print "
            "none"
        ),
    ),
]

# The three SPIs clauses 9.4-9.6 make required members of their MSAs, which
# nothing defines (docs/linter.md#standing-findings). Searched: the RFC's
# clause 9 AVP table and clause 11.1 table, its verified errata (1462
# renames 9.6's member, 3234 retypes MIP-Home-Agent-Host), IANA's AVP Codes
# registry and Wireshark's dictionary.
_SEARCHED = (
    "; the clause 9 AVP table lists only MIP-FA-to-HA-SPI (318),"
    " MIP-FA-to-MN-SPI (319) and MIP-HA-to-FA-SPI (323), each defined in a"
    " clause of its own (9.10, 9.11, 9.14), and clause 11.1's table lists"
    " the name 0-1 in HAA with no code; neither verified erratum (1462,"
    " 3234) defines it; IANA's AVP Codes registry leaves 324, 327 and 330"
    " among the MSA codes unassigned, and nothing says any was meant for it;"
    " Wireshark's dictionary has no such AVP. By analogy with 318, 319 and"
    " 323 it would be Unsigned32, M in Must, P in May, V in Must not and"
    " encryptable, which is analogy, not a definition"
)

CORRECTIONS += [
    Insert(
        id=f"undefined-{name.lower()}",
        into=header(),
        node=ast.UndefinedAvp(
            name=name,
            source=ast.SourceRef(section=section, page=page),
            note=f'"{note}"',
        ),
        after=None,
        reason=f"a required member of {parent} (clause {section}) that no"
        f" clause defines{_SEARCHED}",
    )
    for name, parent, section, page, note in (
        (
            "MIP-HA-to-MN-SPI",
            "MIP-HA-to-MN-MSA",
            "9.4",
            40,
            "The MN allocates the MIP-HA-to-MN-SPI.",
        ),
        (
            "MIP-MN-to-FA-SPI",
            "MIP-MN-to-FA-MSA",
            "9.5",
            40,
            "The FA allocates the MIP-MN-to-FA-SPI.",
        ),
        (
            "MIP-MN-to-HA-SPI",
            "MIP-MN-to-HA-MSA",
            "9.6",
            41,
            "The HA allocates the MIP-MN-to-HA-SPI.",
        ),
    )
]
