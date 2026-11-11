"""The linter's findings over the committed corpus, pinned, and one case for
each rule no committed file triggers."""

import dataclasses
import textwrap
from pathlib import Path

import pytest
from conftest import _CORPUS_DIR, _ROOT, _RULES, _corpus

from seanchai import corpus, linter
from seanchai.dad import ast, corrections, parser

_ERROR, _NOTE = linter.Severity.ERROR, linter.Severity.NOTE


def _dad(
    specification: str,
    *blocks: str,
    version: str | None = "19.0.0",
    vendor_id: int = 10415,
    bases: str | None = None,
) -> ast.Specification:
    """A `.dad` file of `blocks`, each written as the document prints it."""
    header = [f"; Specification: {specification}"]
    if version is not None:
        header.append(f"; Version: {version}")
    header.append(f"; Vendor-ID: {vendor_id}")
    if bases is not None:
        header.append(f"; Bases: {bases}")
    sections = [textwrap.dedent(block).strip("\n") for block in blocks]
    return parser.parse("\n\n\n".join(["\n".join(header), *sections]) + "\n")


def _books(*specs: ast.Specification) -> corpus.Corpus:
    """A fixture corpus, resolving by the committed corpus's rules."""
    return corpus.Corpus(
        (
            corpus.Entry(path=Path(f"{i}.dad"), spec=spec)
            for i, spec in enumerate(specs)
        ),
        rules=_RULES,
    )


def _only(findings: list[linter.Finding], rule: str) -> linter.Finding:
    (finding,) = [f for f in findings if f.rule == rule]
    return finding


# --- the committed corpus ------------------------------------------------------


@pytest.mark.parametrize("path", _corpus(raw=False), ids=lambda path: path.name)
def test_the_corrected_corpus_has_no_errors(path):
    """Correcting a file is what clears its errors, so the corrected corpus is
    the one that must come out clean. An error here means either a correction
    is missing or a rule started firing on something new."""
    findings = linter.lint(parser.parse(path.read_text(encoding="utf-8")))

    assert [f for f in findings if f.severity is linter.Severity.ERROR] == []


# What each raw file's own document gets wrong, and therefore what its
# corrections exist to fix. Every entry was confirmed against the source clause
# before it was written down; a file absent from here must lint clean raw.
_RAW_ERRORS = {
    "29273-j20.raw.dad": ["duplicate-definition", "duplicate-identity"],
    "29172-j00.raw.dad": ["duplicate-identity"],
    "29272-j60.raw.dad": [
        "duplicate-identity",
        "table-definition-mismatch",
        "vendor-id-mismatch",
    ],
    "29344-j10.raw.dad": ["one-name-two-commands", "one-name-two-commands"],
    "29388-j10.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "table-definition-mismatch",
    ],
    "29212-j10.raw.dad": ["vendor-id-mismatch"] * 39,
    "29214-j30.raw.dad": ["vendor-id-mismatch"] * 11,
    # Release 7 and TS 29.209, its Release 6 predecessor: grouped headers
    # printing no vendor where clause 5.3 (6.5) sets 3GPP's for every AVP.
    "29214-7c0.raw.dad": ["vendor-id-mismatch"] * 5,
    "29209-680.raw.dad": ["vendor-id-mismatch"] * 5,
    # TS 29.210's four and TS 29.234's four grouped headers printing no vendor
    # where clauses 5.2 and 10.1 set 3GPP's.
    "29210-670.raw.dad": ["vendor-id-mismatch"] * 4,
    "29234-b20.raw.dad": ["vendor-id-mismatch"] * 4,
    # Release 11, the copies TS 32.299 V11.20.0 cites: thirty-one and six
    # vendorless grouped headers, as their Release 19 successors print.
    "29212-bj0.raw.dad": ["vendor-id-mismatch"] * 31,
    "29214-bg0.raw.dad": ["vendor-id-mismatch"] * 6,
    "29336-j10.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "duplicate-identity",
    ],
    "29338-j30.raw.dad": ["duplicate-identity"],
    # Grouped headers printing no vendor while the AVP tables set V (all
    # eight; 29.154's sixth, Time-window, misspells its own rule name, so no
    # row matches it); 29.468's clauses 6.4.28 and 6.4.31 print FEC-Request's
    # code, and table 6.4.1-1 types clause 6.4.35's Enumerated AVP
    # Unsigned32.
    "29153-j00.raw.dad": ["vendor-id-mismatch"],
    "29154-j00.raw.dad": ["vendor-id-mismatch"] * 5,
    "29215-j00.raw.dad": ["vendor-id-mismatch"] * 2,
    "29217-j00.raw.dad": ["vendor-id-mismatch"] * 4,
    "29219-j00.raw.dad": ["vendor-id-mismatch"] * 2,
    "29343-j00.raw.dad": ["vendor-id-mismatch"] * 3,
    "29368-j00.raw.dad": ["vendor-id-mismatch"] * 3,
    "29468-j00.raw.dad": ["duplicate-identity"]
    + ["table-definition-mismatch"] * 3
    + ["vendor-id-mismatch"] * 12,
    # Both tabulate RFC 8583's Load among their own AVPs, with no code —
    # their Load clauses define it only by reference to RFC 8583.
    "29229-j10.raw.dad": ["row-without-code"],
    "29329-j10.raw.dad": ["row-without-code"],
    "29345-j00.raw.dad": [
        "duplicate-identity",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
    ],
    # Two clauses naming their rule Transport-Address (7.3.4, 7.3.5), two
    # values both labelled Overbooking-indicator (7.3.35), table 7.3.1's
    # sentence-cased names against the clauses' own six, and two Gq AVPs
    # whose sentences name them otherwise than table 7.3.3 does, so their
    # 3GPP vendor-id reads as the document's own.
    # Clauses 6.3.13 and ZA.2 each print SIP-Auth-Data-Item as TS 29.229
    # modified, in 3GPP's vendor space.
    "ts183033-010200.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "vendor-id-mismatch",
        "vendor-id-mismatch",
    ],
    # Table 5.1-1's AVPs are 3GPP's in a file of 3GPP2's vendor, which clause
    # 5.5 says in prose, and grouped formats print no vendor-id at all.
    "xs0013-013-0_v1.0.raw.dad": ["vendor-id-mismatch"] * 11,
    # The same, in clause 5.2.2.
    "xs0013-014-0_v1.0.raw.dad": ["vendor-id-mismatch"] * 16,
    "ts183017-030201.raw.dad": [
        "duplicate-definition",
        "duplicate-enum-value",
    ]
    + ["duplicate-identity"] * 6
    + ["vendor-id-mismatch"] * 2,
    "rfc4004.raw.dad": ["table-definition-mismatch"],
    # Two Integer32 rows clauses 7.2.111AaA and 7.2.111AaB define as
    # Enumerated, and every grouped header in clause 7.2 printing no vendor
    # while table 7.2.0.1 sets V.
    "32299-j00.raw.dad": ["table-definition-mismatch"] * 2
    + ["vendor-id-mismatch"] * 96,
    # Release 11: the grouped headers of clause 7.2 printing no vendor while
    # table 7.2 sets V.
    "32299-bk0.raw.dad": ["vendor-id-mismatch"] * 66,
    # Table A.4-1 puts V under Must not for its 45687 rows and 3GPP's
    # Service-Information, and clause A.5.14 prints M2M-Information's
    # header with no vendor-id.
    "ts-0004-v2_35_0.raw.dad": ["vendor-flag-mismatch"] * 24 + ["vendor-id-mismatch"],
    # Clauses 8.5.5 and 8.5.6 print only the code; table 11 gives vendor 10415.
    "dds-charging_data-v1_0-20110201-a.raw.dad": ["vendor-id-mismatch"] * 2,
}


@pytest.mark.parametrize("path", _corpus(raw=True), ids=lambda path: path.name)
def test_the_raw_corpus_reports_exactly_what_the_documents_say(path):
    """Raw files legitimately carry the documents' own mistakes, and pinning
    them is what proves the rules fire at all — the corrected corpus being
    clean would otherwise be indistinguishable from rules that never match."""
    findings = linter.lint(parser.parse(path.read_text(encoding="utf-8")))
    errors = [f for f in findings if f.severity is linter.Severity.ERROR]

    assert [f.rule for f in errors] == _RAW_ERRORS.get(path.name, [])


# Notes per file stem. A raw stem without an entry takes its corrected file's
# count, and any other stem none.
# AVPs each document both defines and lists as re-used, plus rows its
# tables print differently (29.061's tables 9a and 10, see
# `_STANDING_CORPUS_NOTES`; 29.273's two).
_NOTE_COUNTS = {
    # The Undefined AVP block of Delegated-IPv6-Prefix is a correction's.
    "29061-j10.raw": 7,
    "29061-j10": 8,
    "29128-j20": 3,
    # OC-OLR, which clause 6.3.61 prints as well as re-uses, and, corrected,
    # the row clause 6.3.43's Wildcarded-IMPU is corrected into.
    "29229-j10.raw": 1,
    "29229-j10": 2,
    "29272-j60": 9,
    # Rows citing another clause than the block's: table 7.2.3.1/1's
    # Trace-Info, a misprint accepted, and raw, table 9.2.3.2.1/1's
    # Emergency-Services, a misprint corrected; corrected, MIP6-Agent-Info,
    # whose second block a correction deletes.
    "29273-j20": 7,
    "29283-j00": 1,
    "29336-j10": 5,
    "29337-j00": 2,
    "29338-j30": 2,
    "29388-j10": 1,
    # Table 5.3.0.1 cites 5.3.142 for clause 5.3.81's AVP.
    "29214-j30": 1,
    # Clause 6.20 defines MIP6-Auth-Mode, clause 9.5 prints its values.
    "rfc5778": 1,
    # Clauses 5.2 and 6 are prose, under the scope a correction inserts.
    "rfc6942.raw": 0,
    "rfc6942": 2,
    # Table 5.1-1's clauses run ahead of the document's, until corrected.
    "xs0013-013-0_v1.0.raw": 7,
    # Clause A.5.25 cites clause 6.6.3, outside the Diameter annex, and,
    # raw, table A.4-1 cites clause 5.4.2 for Accounting-Record-Type.
    "ts-0004-v2_35_0.raw": 2,
    "ts-0004-v2_35_0": 1,
    # The Undefined AVP block of Delegated-IPv6-Prefix is a correction's.
    "29561-j60.raw": 0,
    "29561-j60": 1,
    # TS 29.230's registry: 318 allocated twice, four reservations
    # covering allocated codes, and 4703-4799 inside 4605-4799.
    "29230-j30": 6,
    # Table 7.1.0.1 marks ACA's Error-Message and Failed-AVP unused; the
    # corrections cite RFC origins for it, whose clauses 7.1.9, 7.1.14,
    # 7.1.17 and B.2.4 print bodies of their own.
    # Plus, corrected, the Undefined AVP blocks the corrections insert:
    # Submission-Timestamp and Network-Element.
    "32299-j00.raw": 2,
    "32299-j00": 8,
    # Only the Undefined AVP blocks, one note each: RFC 4004's three
    # SPIs, TS 29.345's ProSe-Query-Code and ProSe-Response-Code, TS
    # 29.154's External-Group-Identifier.
    "rfc4004.raw": 0,
    "rfc4004": 3,
    "rfc5866.raw": 0,
    "rfc5866": 1,
    # Clause 5.1 extends RFC 5447's MIP6-Agent-Info.
    "rfc5779": 1,
    "29345-j00.raw": 0,
    "29345-j00": 2,
    "29154-j00.raw": 0,
    "29154-j00": 1,
    # TS 29.234 prints no re-used table; the corrections give it one, in
    # which clause 10.1.4's SIP-Auth-Data-Item is defined here too, and
    # declare Error-Cause.
    "29234-b20.raw": 0,
    "29234-b20": 2,
    # The transcriptions re-print what they import: ES 283 034 clause
    # 7.3.11 TS 183 017's Reservation-Priority, TS 183 017 clauses
    # 7.3.10-7.3.32 the Gq AVPs and ES 283 034's Globally-Unique-Address;
    # two of TS 183 017's carry another name until corrected.
    "es283034-020200": 1,
    # Clauses 6.2.4, 6.2.43 and 6.2.74 print values for what table 11 lists
    # as re-used, and a correction drops the first's re-used row. Table 11
    # marks 11 members of clause 8.2's ABNF unused, and its raw Reference
    # cells cite the wrong clause for what clauses 8.5.1 to 8.5.10 head.
    "dds-charging_data-v1_0-20110201-a.raw": 19,
    "dds-charging_data-v1_0-20110201-a": 13,
    # ES 283 026 re-prints Gq's and e4's and Gq' AVPs it imports; TS 183
    # 033's corrections give SIP-Auth-Data-Item the re-used row it lacks.
    "es283026-010600": 11,
    "ts183033-010200.raw": 0,
    "ts183033-010200": 1,
    "ts183017-030201.raw": 9,
    "ts183017-030201": 11,
}


_SINGLE_FILE_NOTE_RULES = {
    "local-and-reused",
    "member-marked-unused",
    "registry-range-overlap",
    "row-without-code",
    "section-mismatch",
    "section-unknown",
    "table-row-mismatch",
    "undefined-avp",
}


@pytest.mark.parametrize(
    "path", _corpus(raw=True) + _corpus(raw=False), ids=lambda path: path.name
)
def test_the_committed_corpus_reports_only_its_known_notes(path):
    """Pins what the corpus says today, so a rule that starts firing on
    something else shows up as a test failure rather than as noise. Notes
    survive correction unchanged, so each spec carries one count for both
    kinds."""
    notes = [
        f
        for f in linter.lint(parser.parse(path.read_text(encoding="utf-8")))
        if f.severity is linter.Severity.NOTE
    ]

    stem = path.name.removesuffix(".dad")

    assert len(notes) == _NOTE_COUNTS.get(
        stem, _NOTE_COUNTS.get(stem.removesuffix(".raw"), 0)
    )
    assert {f.rule for f in notes} <= _SINGLE_FILE_NOTE_RULES


# Standing findings from docs/linter.md, plus the additional reprints,
# body differences and indirect origins present in the committed corpus.
_STANDING_CORPUS_NOTES = {
    "29061-j10.dad": {
        "table-row-mismatch": [
            "3GPP-IMSI",
            "3GPP-SGSN-Address",
            "3GPP-SGSN-IPv6-Address",
            "3GPP-IMEISV",
            "3GPP-RAT-Type",
            "3GPP-User-Location-Info",
            "3GPP-MS-TimeZone",
        ],
        "undefined-avp": ["Delegated-IPv6-Prefix"],
    },
    "29128-j20.dad": {
        "registry-result-code-document": [
            "DIAMETER_ERROR_SCEF_REFERENCE_ID_UNKNOWN",
        ],
        "reused-body-differs": ["Terminal-Information"],
    },
    "29172-j00.dad": {
        "reused-origin-indirect": ["Service-Selection"],
    },
    "29154-j00.dad": {
        "undefined-avp": ["External-Group-Identifier"],
    },
    # Clause 2 [24] cites 3GPP2 X.S0057-B, which 3GPP2's library does not
    # publish; revision 0 V2.0 stands in (corpus.toml, stand_in).
    "29212-j10.dad": {"cross-release-origin": ["3GPP2-X.S0057"]},
    # Table 6.3.0.1 sets M in Must for the four Digest AVPs it re-uses; RFC
    # 4590's stand-in flags, Wireshark's, put it in May; the model follows the table.
    "29229-j10.dad": {
        "reused-row-mismatch": [
            "Digest-Algorithm",
            "Digest-HA1",
            "Digest-Qop",
            "Digest-Realm",
        ],
        "reused-extension": ["OC-OLR"],
        "row-without-code": ["Wildcarded-IMPU"],
    },
    "29230-j30.dad": {
        "registry-range-overlap": [
            "318",
            "1..255",
            "4605..4799",
            "4605..4799",
            "4182..4200",
            "5455..5469",
        ],
    },
    "29272-j60.dad": {
        "registry-result-code-document": [
            "DIAMETER_ERROR_USER_UNKNOWN",
            "DIAMETER_ERROR_ROAMING_NOT_ALLOWED",
        ],
        "registry-application-name": ["S7a/S7d"],
        "reused-body-differs": [
            "ProSe-Subscription-Data",
            "Supported-Services",
        ],
        "reused-origin-indirect": ["Charged-Party"],
        "reused-reprint": [
            "AESE-Communication-Pattern",
            "Allocation-Retention-Priority",
            "Communication-Pattern-Set",
            "MIP6-Agent-Info",
        ],
    },
    "29273-j20.dad": {
        "registry-result-code-document": [
            "DIAMETER_ERROR_ILLEGAL_EQUIPMENT",
        ],
        "registry-avp-document": ["3GPP-AAA-Server-Name"],
        "reused-reprint": ["MIP6-Agent-Info", "Subscription-Id"],
        "table-row-mismatch": ["AN-Trusted", "Mobile-Node-Identifier"],
    },
    "29283-j00.dad": {
        "registry-result-code-name": [
            "DIAMETER_ERROR_DATA",
        ],
        "result-code-origin-name": ["DIAMETER_ERROR_DATA"],
        "registry-avp-name": ["Data", "MCVideo-ID"],
        "reused-body-differs": ["User-Identifier"],
    },
    "29140-700.dad": {
        "cross-release-origin": ["TS29.061", "TS29.329"],
        "reused-row-mismatch": ["3GPP-IMSI"],
    },
    "29330-j00.dad": {"reused-origin-indirect": ["Load"]},
    "29336-j10.dad": {
        "registry-result-code-document": [
            "DIAMETER_ERROR_USER_NO_APN_SUBSCRIPTION",
        ],
        "registry-avp-name": ["Group-User-Identifier", "NIA-Flags"],
        "reused-body-differs": [
            "MME-Location-Information",
            "SGSN-Location-Information",
        ],
        "reused-origin-indirect": ["User-CSG-Information"],
        "reused-reprint": ["EPS-Location-Information"],
    },
    "29338-j30.dad": {
        "registry-result-code-document": [
            "DIAMETER_ERROR_USER_UNKNOWN",
        ],
        "registry-avp-name": ["SGSN-Absent-User-Diagnostic-SM"],
        "reused-body-differs": ["Serving-Node"],
    },
    "29345-j00.dad": {
        "registry-result-code-document": [
            "DIAMETER_ERROR_USER_UNKNOWN",
            "DIAMETER_ERROR_UNAUTHORIZED_SERVICE",
        ],
        "undefined-avp": ["ProSe-Query-Code", "ProSe-Response-Code"],
    },
    "29561-j60.dad": {
        # Table 12.4-1 cites TS 29.061 for code 28, sub-attribute 28 of its
        # RADIUS VSA; TS 29.061's table 9b re-uses the AVP from TS 29.336, 3111.
        "reused-origin-indirect": ["External-Identifier"],
        "undefined-avp": ["Delegated-IPv6-Prefix"],
    },
    "32299-j00.dad": {
        # Table 7.1.0.1 marks them "-" under ACA, clause 6.2.3's ABNF lists them.
        "member-marked-unused": ["Error-Message", "Failed-AVP"],
        # Clause 2 [213] cites TS 29.140 non-specifically for VAS-ID and
        # VASP-ID; V7.0.0 is its final version.
        "cross-release-origin": ["TS29.140"],
        "reused-origin-indirect": [
            "3GPP2-BSID",
            "Priority-Indication",
            "Reference-Number",
        ],
        "registry-avp-name": ["Service-ID"],
        "reused-reprint": ["User-Equipment-Info"],
        # Table 7.2.0.1 sets M for the charging application on AVPs it
        # refers to TS 29.229 for, which leaves M out of Must.
        "reused-row-mismatch": [
            "Feature-List",
            "Feature-List-ID",
        ],
        "undefined-avp": [
            "Submission-Timestamp",
            "Network-Element",
        ],
    },
    # The transcriptions cite TS 29.209, which ends at V6.8.0, ES 283 034
    # non-specifically and TS 183 017 as "Release 6", and TS 183 017 cites
    # TS 29.214 "Release 7", V7.12.0.
    "es283034-020200.dad": {
        "cross-release-origin": ["TS29.209"],
        # Clause 7.3.11 prints values PRIORITY 0-7 and table 13 types the AVP
        # Unsigned32, re-used from TS 183 017, whose clause 7.3.9 enumerates
        # DEFAULT and PRIORITY-ONE to PRIORITY-FIFTEEN.
        "reused-body-differs": ["Reservation-Priority"],
        "reused-row-mismatch": ["Reservation-Priority"],
    },
    # ES 283 026 cites TS 29.209 non-specifically and re-prints what it
    # imports from it, ES 283 034 and TS 183 017. Clause 6.4.23 stops
    # Reservation-Priority at PRIORITY-SEVEN where TS 183 017 goes on to
    # FIFTEEN; clause 6.4.16 adds three members to Media-Component-Description
    # without saying so; and Media-Type adds OTHER, as TS 183 017 does.
    "es283026-010600.dad": {
        "cross-release-origin": ["TS29.209"],
        "reused-body-differs": ["Reservation-Priority"],
        "reused-extension": ["Media-Component-Description", "Media-Type"],
        "reused-reprint": [
            "Abort-Cause",
            "Flow-Grouping",
            "Flow-Status",
            "Flow-Usage",
            "Flows",
            "Globally-Unique-Address",
            "Media-Sub-Component",
        ],
    },
    # ES 283 035 cites TS 29.209, which ends at V6.8.0, and TS 29.329, whose
    # latest edition its clause 2.1 says it means.
    "es283035-020501.dad": {"cross-release-origin": ["TS29.209", "TS29.329"]},
    # TS 183 033 names TS 29.229 V6.6.0, which V18.1.0 stands in for.
    "ts183033-010200.dad": {"cross-release-origin": ["TS29.229"]},
    # oneM2M cites TS 32.299 [31], "Release 11", for Node-Id and
    # Service-Information: V11.20.0.
    "ts-0004-v2_35_0.dad": {"cross-release-origin": ["TS32.299"]},
    "dds-charging_data-v1_0-20110201-a.dad": {
        # Clause 2's [TS29.140], non-specific; V7.0.0 is its final version.
        "cross-release-origin": ["TS29.140"],
        # Clauses 6.2.43 and 6.2.74 print values table 11 cites TS 32.299 for.
        "local-and-reused": ["AoC-Request-Type", "PoC-Server-Role"],
        # Table 11 marks them "-" under CCR and CCA, clauses 8.2.1 and 8.2.2
        # print them, the first five of CCR under its MSCC columns.
        "member-marked-unused": [
            "Service-Identifier",
            "Requested-Service-Unit",
            "AoC-Request-Type",
            "Used-Service-Unit",
            "AoC-Request-Type",
            "User-Name",
            "Origin-State-Id",
            "Event-Timestamp",
            "Granted-Service-Unit",
            "Final-Unit-Indication",
            "Validity-Time",
        ],
        # Clause 2's [TS32.299] and [TS29.214] name no version and clause 2
        # says nothing of what such a reference means.
        "origin-not-in-corpus": [
            "TS29.214 (corpus has 19.3.0, 11.16.0, 7.12.0), TS32.299"
            " (corpus has 19.0.0, 11.20.0)"
        ],
        # Table 11 May Encrypt Y where TS 29.140 table 6.3.1 reads No.
        "reused-row-mismatch": ["Billing-Information", "Service-Key"],
    },
    "ts183017-030201.dad": {
        "cross-release-origin": ["TS29.209", "TS29.214"],
        # Clauses 7.3.14-7.3.32 re-print the Gq AVPs table 7.3.3 imports
        # from TS 29.209 V6.8.0: seven as printed there, Media-Type adding
        # OTHER (7.3.29), and Specific-Action (7.3.23) with values of its
        # own. Media-Component-Description's extension is NOTE 3's,
        # accepted.
        "reused-body-differs": ["Specific-Action"],
        "reused-extension": ["Media-Type"],
        "reused-reprint": [
            "Abort-Cause",
            "Flow-Grouping",
            "Flow-Status",
            "Flow-Usage",
            "Flows",
            "Globally-Unique-Address",
            "Media-Sub-Component",
            "SIP-Forking-Indication",
        ],
    },
    # The older releases the corpus holds for citations cite in turn
    # documents it holds at Release 19 only: TS 29.214 V7.12.0 re-uses Gx's
    # and Gi's AVPs, and TS 29.140 non-specifically, which reads as V7.0.0
    # here too. TS 32.299 V11.20.0's six other Release 11 citations read
    # Release 19 copies standing in (corpus.toml, release_stand_in), and its TS
    # 29.212 and 29.214 are the pinned Release 11 copies, whose own Release
    # 11 citations of TS 29.061, 29.229 and 29.272 nothing stands in for:
    # TS 29.212 V11.19.0's Trace-Data, from TS 29.272, differs from Release
    # 18's.
    # TS 29.210 V6.7.0 and TS 29.234 V11.2.0, held for TS 29.230's rows, cite
    # TS 29.229 in their releases; V18.1.0 stands in for both. TS 29.234's
    # clause 10.1.4 prints SIP-Auth-Data-Item's body with three members more and
    # five fewer than TS 29.229's. TS 29.210's TS 29.061 is the pinned V6.15.0,
    # V19.1.0 typing the two AVPs it leaves untyped (corpus.toml, release_fill).
    "29210-670.dad": {"cross-release-origin": ["TS29.061", "TS29.229"]},
    "29234-b20.dad": {
        "cross-release-origin": ["TS29.229"],
        "reused-body-differs": ["SIP-Auth-Data-Item"],
        "undefined-avp": ["Error-Cause"],
    },
    "29214-7c0.dad": {
        "origin-not-in-corpus": [
            "TS29.061 (corpus has 19.1.0, 6.15.0),"
            " TS29.212 (corpus has 19.1.0, 11.19.0)"
        ]
    },
    "29212-bj0.dad": {
        "cross-release-origin": ["3GPP2-X.S0057"],
        "origin-not-in-corpus": [
            "TS29.061 (corpus has 19.1.0, 6.15.0), TS29.229 (corpus has 19.1.0),"
            " TS29.272 (corpus has 19.6.0)"
        ],
    },
    "29214-bg0.dad": {
        "origin-not-in-corpus": [
            "TS29.061 (corpus has 19.1.0, 6.15.0), TS29.229 (corpus has 19.1.0)"
        ]
    },
    "32299-bk0.dad": {
        "cross-release-origin": [
            "TS29.061",
            "TS29.140",
            "TS29.173",
            "TS29.229",
            "TS29.272",
            "TS29.273",
            "TS29.329",
        ],
        "reused-origin-indirect": ["3GPP2-BSID"],
    },
    "rfc4004.dad": {
        "undefined-avp": [
            "MIP-HA-to-MN-SPI",
            "MIP-MN-to-FA-SPI",
            "MIP-MN-to-HA-SPI",
        ],
    },
    "rfc5779.dad": {"reused-extension": ["MIP6-Agent-Info"]},
    "rfc5866.dad": {"undefined-avp": ["Authorization-Session-Volume"]},
    "rfc6736.dad": {"origin-not-in-corpus": ["RFC4675"]},
    "rfc6738.dad": {"reused-row-mismatch": ["Key-Lifetime"]},
    "29109-j00.dad": {
        "registry-result-code-name": [
            "DIAMETER_ERROR_IDENTITY_UNKNOWN",
        ],
    },
    "29337-j00.dad": {
        "registry-result-code-document": [
            "DIAMETER_ERROR_USER_UNKNOWN",
        ],
    },
}


# Notes the specifications' corrections modules accept as overrides their
# documents state, by acceptance (docs/linter.md#standing-findings).
_ACCEPTED_CORPUS_NOTES = {
    "29214-j30.dad": {
        "section-mismatch": ["TS29.214.py#pc-session-recovery-status-clause"]
    },
    "rfc5778.dad": {"section-mismatch": ["RFC5778.py#mip6-auth-mode-clause"]},
    "rfc6942.dad": {
        "section-unknown": [
            "RFC6942.py#application-scope-clause-5-2",
            "RFC6942.py#application-scope-clause-6",
        ]
    },
    "ts-0004-v2_35_0.dad": {
        "section-unknown": ["oneM2M-TS-0004.py#response-status-code-values-clause"]
    },
    "es283026-010600.dad": {
        "reused-body-differs": ["ETSI-ES283.026.py#specific-action-rq-events"]
    },
    "ts183033-010200.dad": {
        "reused-body-differs": ["ETSI-TS183.033.py#sip-auth-data-item-endorsed-change"]
    },
    "ts183017-030201.dad": {
        "reused-extension": ["ETSI-TS183.017.py#media-component-description-extension"],
    },
    "29128-j20.dad": {
        "reused-body-differs": [
            "TS29.128.py#monitoring-event-configuration-t6a-body",
            "TS29.128.py#monitoring-event-report-t6a-body",
        ],
    },
    "29272-j60.dad": {
        "reused-body-differs": [
            "TS29.272.py#monitoring-event-configuration-s6a-body",
            "TS29.272.py#monitoring-event-report-s6a-body",
            "TS29.272.py#ue-reachability-configuration-s6a-body",
        ],
    },
    "29273-j20.dad": {
        "section-mismatch": [
            "TS29.273.py#trace-info-clause",
            "TS29.273.py#mip6-agent-info-row-clause",
        ],
        "reused-body-differs": ["TS29.273.py#sip-auth-data-item-swx-body"],
    },
    "29336-j10.dad": {
        "reused-body-differs": [
            "TS29.336.py#additional-serving-node-t4-body",
            "TS29.336.py#serving-node-t4-body",
        ],
    },
    "29337-j00.dad": {
        "reused-body-differs": [
            "TS29.337.py#additional-serving-node-t4-body",
            "TS29.337.py#serving-node-t4-body",
        ],
    },
    "29338-j30.dad": {
        "reused-body-differs": ["TS29.338.py#additional-serving-node-body"],
    },
    "29388-j10.dad": {
        "reused-body-differs": ["TS29.388.py#v2x-subscription-data-v4-body"],
    },
    "32299-j00.dad": {
        "reused-body-differs": [
            "TS32.299.py#multiple-services-credit-control-charging-body",
            "TS32.299.py#used-service-unit-charging-body",
        ],
        "reused-extension": ["TS32.299.py#oc-olr-extension"],
        "reused-row-mismatch": ["TS32.299.py#supported-features-charging-m"],
    },
}


def test_the_corrected_corpus_has_only_its_standing_cross_file_notes():
    # The directory, not its files, for the rules beside them.
    books = corpus.Corpus.load([_CORPUS_DIR])
    actual = {}
    accepted = {}
    for entry in books:
        declared = corrections.in_release(
            corrections.load(
                _ROOT / "edits" / "corrections",
                entry.spec.specification,
            ),
            entry.spec.version,
        )
        notes = {}
        for finding in linter.lint_with_corpus(
            entry.spec, books, corrections.acceptances(declared)
        ):
            assert finding.severity is not linter.Severity.ERROR, (entry.path, finding)
            if finding.severity is linter.Severity.ACCEPTED:
                by_rule = accepted.setdefault(entry.path.name, {})
                by_rule.setdefault(finding.rule, []).append(finding.accepted_by)
                continue
            # Missing origins are grouped in one finding per file; all other
            # standing notes start with the affected AVP's name.
            subject = (
                finding.message.rpartition(": ")[2]
                if finding.rule
                in {"origin-not-in-corpus", "external-origin-not-in-corpus"}
                else finding.message.split()[0].removesuffix("'s")
            )
            notes.setdefault(finding.rule, []).append(subject)
        if notes:
            actual[entry.path.name] = notes
    assert actual == _STANDING_CORPUS_NOTES
    assert accepted == _ACCEPTED_CORPUS_NOTES


def test_the_committed_record_matches_the_corpus():
    books = corpus.Corpus.load([_CORPUS_DIR])

    assert books.record is not None
    assert linter.lint_record(books) == []


# --- rules no committed file triggers ----------------------------------------

_ULR_FLAGS = """\
    ; Type: Value Table
    ; AVP: ULR-Flags
    ; Kind: bits
    ; Section: 7.3.7
    ; Table: 7.3.7/1
    Single-Registration-Indication = 0
    S6a-S6d-Indicator = 1
    """

_GX = """\
    ; Type: Application Scope
    ; Name: Gx
    ; Section: 5.1
    ; Application-ID: 16777238
    ; Applies-To: 5.*
    """


def _ccr(section: str, header: str = "272, REQ, PXY") -> str:
    return f"""\
        ; Type: Message
        ; Name: Credit-Control-Request, CCR
        ; Section: {section}
        <Credit-Control-Request> ::= < Diameter Header: {header} >
        < Session-Id >
        """


# A body naming ProSe-Query-Code, as TS 29.345 clause 6.3.53's does.
_PROSE_QUERY = """\
    ; Type: Grouped AVP
    ; Name: ProSe-Discovery-Filter
    ; Section: 6.3.53
    ProSe-Discovery-Filter ::= < AVP header: 3600 10415 >
    { ProSe-Query-Code }
    """


def _undefined(name: str) -> str:
    return f"""\
        ; Type: Undefined AVP
        ; Name: {name}
        ; Section: 6.3.53
        """


@pytest.mark.parametrize(
    ("blocks", "rule", "fact"),
    [
        pytest.param(
            [_ULR_FLAGS + "Skip-Subscriber-Data = 1\n"],
            "duplicate-value",
            "gives 1 to 'S6a-S6d-Indicator', 'Skip-Subscriber-Data'",
            id="duplicate-value",
        ),
        # Unsigned32 unless a table types the AVP otherwise.
        pytest.param(
            [_ULR_FLAGS + "Initial-Attach-Indicator = 32\n"],
            "value-bit-out-of-range",
            "bit 32, past the 31 a Unsigned32 holds",
            id="value-bit-out-of-range",
        ),
        # TS 32.299 clause 7.2.213 leaves 100-199 of SM-Service-Type to vendors.
        pytest.param(
            [
                """\
                ; Type: Enumerated AVP
                ; Name: SM-Service-Type
                ; Section: 7.2.213
                SM-Service-Type ::= < Enumerated AVP header: 2029 10415 >
                VAS4SMS-Short-Message-content-processing = 0
                ; RESERVED = 11-99
                ; VENDOR-SPECIFIC = 100-199
                Operator-Defined = 150
                """
            ],
            "vendor-specific-overlap",
            "vendor-specific 100-199 overlaps 'Operator-Defined' = 150",
            id="vendor-specific-overlap",
        ),
        # TS 29.214 clause 5.3.13 prints Specific-Action's withdrawn values as
        # `Void (0)`.
        pytest.param(
            [
                """\
                ; Type: Enumerated AVP
                ; Name: Specific-Action
                ; Section: 5.3.13
                Specific-Action ::= < Enumerated AVP header: 513 10415 >
                ; VOID = 0
                CHARGING_CORRELATION_EXCHANGE = 0
                """
            ],
            "void-overlap",
            "void 0-0 overlaps 'CHARGING_CORRELATION_EXCHANGE' = 0",
            id="void-overlap",
        ),
        # TS 29.061 tabulates its Gi AVPs in tables 9a and 10.
        pytest.param(
            [
                f"""\
                ; Type: AVP Table
                ; Section: 16.4.7
                ; Table: {label}
                ; Columns: Name Code Type
                3GPP-IMSI {code} UTF8String
                """
                for label, code in (("9a", 1), ("10", 2))
            ],
            "table-row-mismatch",
            "differing code: 1 in table 9a; 2 in table 10",
            id="table-row-mismatch-code",
        ),
        pytest.param(
            [
                _GX,
                """\
                ; Type: Application Scope
                ; Name: Gxx
                ; Section: 5a.1
                ; Application-ID: 16777266
                ; Applies-To: 5.6.*
                """,
                _ccr("5.6.2"),
            ],
            "application-scope-overlap",
            "Gx (16777238, clause 5.1), Gxx (16777266, clause 5a.1)",
            id="application-scope-overlap",
        ),
        pytest.param(
            [_GX, _ccr("5.6.2", "272, REQ, PXY, 16777266")],
            "application-header-mismatch",
            "prints application 16777266",
            id="application-header-mismatch",
        ),
        pytest.param(
            [_PROSE_QUERY, _undefined("ProSe-Response-Code")],
            "undefined-avp-unused",
            "ProSe-Response-Code is declared undefined, but no body references it",
            id="undefined-avp-unused",
        ),
        pytest.param(
            [
                _PROSE_QUERY,
                _undefined("ProSe-Query-Code"),
                """\
                ; Type: AVP Table
                ; Section: 6.3.1
                ; Table: 6.3.1-1
                ; Columns: Name Code Type
                ProSe-Query-Code 3601 OctetString
                """,
            ],
            "undefined-avp-defined",
            "ProSe-Query-Code is declared undefined, but the file defines,"
            " tabulates or re-uses it",
            id="undefined-avp-defined",
        ),
    ],
)
def test_a_single_file_rule_no_committed_file_triggers(blocks, rule, fact):
    (finding,) = [
        f for f in linter.lint(_dad("3GPP TS 29.999", *blocks)) if f.rule == rule
    ]

    assert finding.severity is _ERROR
    assert fact in finding.message


def _reused(*rows: str, columns: str = "Name From") -> str:
    lines = "\n".join(rows)
    return (
        "; Type: Reused AVPs\n; Section: 6.4.1\n; Table: 6.4.1/2\n"
        f"; Columns: {columns}\n{lines}"
    )


def _grouped(
    name: str, code: int, *members: str, section: str = "6.4.12", vendor: str = " 10415"
) -> str:
    body = "\n".join(f"[ {member} ]" for member in members)
    return (
        f"; Type: Grouped AVP\n; Name: {name}\n; Section: {section}\n"
        f"{name} ::= < AVP header: {code}{vendor} >\n{body}"
    )


# TS 29.109 clause 4.2 prints RFC 6733's Vendor-Specific-Application-Id.
_REPRINT = """\
    ; Type: Reprinted AVP
    ; Name: Vendor-Specific-Application-Id
    ; Section: 4.2
    ; From: RFC6733
    Vendor-Specific-Application-Id ::= < AVP header: 260 >
    [ Vendor-Id ]
    """


def _ietf(name: str, code: int, *members: str) -> str:
    return _grouped(name, code, *members, section="4.1", vendor="")


def _rfc6733(*blocks: str) -> ast.Specification:
    return _dad("RFC 6733", *blocks, version=None, vendor_id=0)


def _result_codes(*rows: str) -> str:
    lines = "\n".join(rows)
    return (
        "; Type: Value Table\n; AVP: Experimental-Result-Code\n"
        f"; Kind: result-codes\n; Section: 6.3.3\n{lines}"
    )


def _registry(kind: str, table: str, columns: str, *rows: str) -> ast.Specification:
    lines = "\n".join(rows)
    return _dad(
        "3GPP TS 29.230",
        f"; Type: Registry\n; Registry: {kind}\n; Section: {table.split('/')[0]}\n"
        f"; Table: {table}\n; Columns: {columns}\n{lines}",
        version="19.3.0",
    )


_TS29173 = _dad("3GPP TS 29.173", _grouped("Serving-Node", 2401, "SGSN-Number"))


@pytest.mark.parametrize(
    ("citing", "origins", "rule", "severity", "fact"),
    [
        # TS 29.338 clause 6.4.12 prints Serving-Node, which it re-uses from
        # TS 29.173; the code TS 29.173 gives it is 2401.
        pytest.param(
            _dad(
                "3GPP TS 29.338",
                _grouped("Serving-Node", 2402, "SGSN-Number"),
                _reused("Serving-Node TS29.173"),
            ),
            [_TS29173],
            "reused-code-conflict",
            _ERROR,
            "Serving-Node is code 2402 here and 2401 in TS29.173",
            id="reused-code-conflict-definition",
        ),
        pytest.param(
            _dad("3GPP TS 29.109", _REPRINT),
            [_rfc6733(_ietf("Vendor-Specific-Application-Id", 299, "Vendor-Id"))],
            "reused-code-conflict",
            _ERROR,
            "Vendor-Specific-Application-Id is code 260 here and 299 in RFC6733",
            id="reused-code-conflict-reprint",
        ),
        # TS 29.283 clause 7.3.21 says its Sequence-Number is TS 29.329's, 716,
        # while table 7.3.1-1 gives 4512.
        pytest.param(
            _dad(
                "3GPP TS 29.283",
                "; Type: AVP Table\n; Section: 7.3.1\n; Table: 7.3.1-1\n"
                "; Columns: Name Code\nSequence-Number 4512",
                _reused("Sequence-Number TS29.329"),
            ),
            [_dad("3GPP TS 29.329", _grouped("Sequence-Number", 716, section="6.3.1"))],
            "reused-code-conflict",
            _ERROR,
            "Sequence-Number is code 4512 in table 7.3.1-1 and 716 in TS29.329",
            id="reused-code-conflict-table",
        ),
        # TS 29.172 table 7.4.1-2 prints the code of what it re-uses.
        pytest.param(
            _dad(
                "3GPP TS 29.172",
                _reused("Serving-Node 2400 TS29.173", columns="Name Code From"),
            ),
            [_TS29173],
            "reused-code-conflict",
            _ERROR,
            "Serving-Node is code 2400 in re-used table 6.4.1/2 and 2401",
            id="reused-code-conflict-reused-table",
        ),
        pytest.param(
            _dad("3GPP TS 29.109", _REPRINT),
            [_rfc6733(_ietf("Auth-Application-Id", 258))],
            "reprint-not-in-origin",
            _ERROR,
            "printed as RFC6733's, which does not define it",
            id="reprint-not-in-origin",
        ),
        pytest.param(
            _dad("3GPP TS 29.109", _REPRINT),
            [_rfc6733(_ietf("Vendor-Specific-Application-Id", 260, "Acct-Id"))],
            "reprint-differs",
            _NOTE,
            "adds Vendor-Id, missing Acct-Id",
            id="reprint-differs",
        ),
        # oneM2M TS-0004 table A.4-1 prints a Vendor-ID per row; TS 32.299
        # puts Node-Id in 3GPP's space.
        pytest.param(
            _dad(
                "oneM2M TS-0004",
                "; Type: AVP Table\n; Section: A.4\n; Table: A.4-1\n"
                "; Columns: Name Vendor-ID Code Must M.not\nNode-Id 45687 2064 M,V -",
                _reused("Node-Id TS32.299"),
                version="2.35.0",
                vendor_id=45687,
            ),
            [
                _dad(
                    "3GPP TS 32.299",
                    "; Type: AVP Table\n; Section: 7.2\n; Table: 7.2.0.1\n"
                    "; Columns: Name Code Must M.not\nNode-Id 2064 M,V -",
                    version="11.20.0",
                )
            ],
            "reused-row-vendor-mismatch",
            _ERROR,
            "Node-Id is tabulated in vendor 45687 in table A.4-1, but TS32.299",
            id="reused-row-vendor-mismatch",
        ),
        # TS 29.283 cites Feature-Id from TS 29.229, which has no such AVP.
        pytest.param(
            _dad("3GPP TS 29.283", _reused("Feature-Id TS29.229")),
            [
                _dad(
                    "3GPP TS 29.229", _grouped("Feature-List-ID", 629, section="6.3.30")
                )
            ],
            "reused-avp-not-in-origin",
            _ERROR,
            "Feature-Id",
            id="reused-avp-not-in-origin",
        ),
        pytest.param(
            _dad(
                "3GPP TS 29.336",
                _result_codes("DIAMETER_ERROR_USER_UNKNOWN = 5001 ; from TS29.229"),
            ),
            [_dad("3GPP TS 29.229", _result_codes("DIAMETER_ERROR_OTHER = 5002"))],
            "result-code-not-in-origin",
            _ERROR,
            "lists no Experimental-Result-Code 5001",
            id="result-code-not-in-origin",
        ),
        pytest.param(
            _dad(
                "3GPP TS 29.336",
                _result_codes("DIAMETER_ERROR_USER_UNKNOWN = 5001 ; from TS29.229"),
            ),
            [
                _dad(
                    "3GPP TS 29.229",
                    _result_codes("DIAMETER_ERROR_USER_UNKNOWN = 5001 ; from TS29.329"),
                )
            ],
            "result-code-origin-indirect",
            _NOTE,
            "which re-uses it from TS29.329 rather than defining it",
            id="result-code-origin-indirect",
        ),
        # TS 183 017 cites ES 283 034 and TS 29.214; this corpus has neither.
        pytest.param(
            _dad(
                "ETSI TS 183 017",
                _reused("Globally-Unique-Address ETSI-ES283.034", "Flows TS29.214"),
                version="3.2.1",
                vendor_id=13019,
            ),
            [],
            "external-origin-not-in-corpus",
            _NOTE,
            "rules needing them were skipped: ETSI-ES283.034",
            id="external-origin-not-in-corpus",
        ),
        pytest.param(
            _dad("3GPP TS 29.345", _PROSE_QUERY, bases="RFC6733"),
            [_rfc6733()],
            "unresolved-reference",
            _ERROR,
            "ProSe-Query-Code is referenced in clause 6.3.53",
            id="unresolved-reference",
        ),
        pytest.param(
            _dad("3GPP TS 29.345", _PROSE_QUERY, bases="RFC6733"),
            [],
            "base-not-in-corpus",
            _NOTE,
            "RFC6733",
            id="base-not-in-corpus",
        ),
        pytest.param(
            _dad(
                "3GPP TS 29.345",
                _PROSE_QUERY,
                _undefined("ProSe-Query-Code"),
                bases="RFC6733",
            ),
            [_rfc6733(_ietf("ProSe-Query-Code", 3601))],
            "undefined-avp-defined",
            _ERROR,
            "ProSe-Query-Code is declared undefined, but a base document resolves it",
            id="undefined-avp-defined-by-a-base",
        ),
        # TS 29.230 table 7.1 reserves codes it allocates to no document.
        pytest.param(
            _dad("3GPP TS 29.329", _grouped("User-Identity", 300, section="6.3.1")),
            [
                _registry(
                    "AVP Codes", "7.1", "Code Name", '; RESERVED 300..399 "future"'
                )
            ],
            "registry-reserved-code",
            _NOTE,
            "User-Identity",
            id="registry-reserved-code",
        ),
        pytest.param(
            _dad(
                "3GPP TS 29.329",
                "; Type: Message\n; Name: Profile-Request, PRQ\n; Section: 6.1.1\n"
                "<Profile-Request> ::= < Diameter Header: 306, REQ, PXY, 16777217 >",
            ),
            [
                _registry(
                    "Command Codes",
                    "5.1/1",
                    "Code Name Abbreviation Defined-In",
                    "306 User-Data-Request/Answer UDR/UDA TS29.329",
                )
            ],
            "registry-command-name",
            _NOTE,
            "Profile-Request",
            id="registry-command-name",
        ),
        pytest.param(
            _dad("3GPP TS 29.329", _ccr("6.1.1", "306, REQ, PXY, 16777251")),
            [
                _registry(
                    "Application IDs",
                    "4.1",
                    "Code Name Defined-In",
                    '16777251 "3GPP S6a" TS29.272',
                )
            ],
            "registry-application-document",
            _NOTE,
            "16777251",
            id="registry-application-document",
        ),
    ],
)
def test_a_cross_file_rule_no_committed_file_triggers(
    citing, origins, rule, severity, fact
):
    finding = _only(linter.lint_with_corpus(citing, _books(citing, *origins)), rule)

    assert finding.severity is severity
    assert fact in finding.message


def test_the_record_of_known_holes_is_held_to_the_corpus():
    spec = _dad(
        "3GPP TS 29.900",
        "; Type: AVP Table\n; Section: 6.3.1\n; Columns: Name Code\nThing 1",
        version="18.1.0",
    )
    thing = corpus.KnownHole("TS29.900", "Thing", (corpus.Missing.DATA_TYPE,), "r")
    stale = corpus.KnownHole("TS29.900", "Gone", (corpus.Missing.DEFINITION,), "r")
    books = corpus.Corpus(
        [corpus.Entry(path=Path("29900.dad"), spec=spec)],
        corpus.HoleRecord(Path("holes.toml"), (thing, stale)),
    )

    findings = {f.rule: f for f in linter.lint_record(books)}

    assert {f.severity for f in findings.values()} == {_ERROR}
    assert findings["unrecorded-hole"].message == (
        "TS29.900 Thing: no data_type, no flag_rules, which the record lists"
        " missing data_type"
    )
    assert findings["stale-hole-record"].message.startswith(
        "TS29.900 Gone is recorded missing definition"
    )


# --- acceptances -------------------------------------------------------------


@pytest.fixture(scope="module")
def books():
    return corpus.Corpus.load([_CORPUS_DIR])


def _ts29336(books):
    (entry,) = [e for e in books if e.path.name == "29336-j10.dad"]
    (accept,) = [
        each
        for each in corrections.load(_ROOT / "edits" / "corrections", "3GPP TS 29.336")
        if each.id == "serving-node-t4-body"
    ]
    assert isinstance(accept, corrections.Accept)
    return entry.spec, accept


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            {"expect": "Serving-Node's body is as it was"},
            "no finding about it reads as expected; it now reads",
        ),
        (
            {"target": corrections.definition("Serving-Node", section="9.9")},
            "its target matches 0 nodes",
        ),
    ],
    ids=["the-document-changed", "the-node-is-gone"],
)
def test_an_acceptance_matching_no_finding_is_a_stale_error(books, change, problem):
    """TS 29.336 clause 6.4.12's accepted Serving-Node body, once the document
    or the acceptance moves on: the note re-opens."""
    spec, accept = _ts29336(books)
    stale = dataclasses.replace(accept, **change)

    findings = linter.lint_with_corpus(spec, books, [stale])

    error = _only(findings, "stale-acceptance")
    assert error.severity is _ERROR
    assert problem in error.message
    assert accept.expect in [
        f.message for f in findings if f.rule == accept.rule and f.severity is _NOTE
    ]


def test_an_error_is_never_accepted():
    spec = _dad(
        "3GPP TS 29.999",
        _grouped("Twice", 700, section="6.3.1"),
        _grouped("Twice", 700, section="6.3.2"),
    )
    error = _only(linter.lint(spec), "duplicate-definition")
    accept = corrections.Accept(
        id="twice",
        rule="duplicate-definition",
        target=corrections.definition("Twice", section="6.3.1"),
        expect=error.message,
        reason="r",
    )

    findings = linter.accept(spec, linter.lint(spec), [accept])

    assert error in findings
    assert _only(findings, "stale-acceptance").message.endswith("the finding is error")


@pytest.mark.parametrize(
    ("change", "message"),
    [({"rule": "Reused Body"}, "names no linter rule"), ({"expect": ""}, "expects no")],
)
def test_an_acceptance_that_cannot_match_anything_is_refused(change, message):
    fields = {
        "id": "body",
        "rule": "reused-body-differs",
        "target": corrections.definition("Serving-Node"),
        "expect": "a message",
        "reason": "r",
    }

    with pytest.raises(corrections.CorrectionError, match=message):
        corrections.Accept(**(fields | change))
