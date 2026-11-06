"""Corpus pins and synthetic cases for rules the committed files do not cover."""

from pathlib import Path

import pydantic
import pytest
from conftest import _CORPUS_DIR, _corpus

from seanchai import corpus, linter
from seanchai.dad import ast, corrections, parser


def _spec(*sections, specification="3GPP TS 29.329", vendor_id=10415, version="1.0.0"):
    return ast.Specification(
        specification=specification,
        version=version,
        vendor_id=vendor_id,
        sections=sections,
    )


def _grouped(name, code, vendor_id: int | None = 10415, section="6.3.1"):
    return ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section=section),
        code=code,
        vendor_id=vendor_id,
        avps=(),
    )


def _enumerated(name, code, *values, section="6.3.2"):
    return ast.EnumeratedAvp(
        name=name,
        source=ast.SourceRef(section=section),
        code=code,
        vendor_id=10415,
        values=values,
    )


def _table(*rows, section="6.3"):
    return ast.AvpTable(
        table="6.3.1",
        columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.TYPE),
        source=ast.SourceRef(section=section),
        rows=rows,
    )


def _row(name, code, data_type=ast.DataType.GROUPED):
    return ast.AvpTableRow(name=name, code=code, data_type=data_type)


def _reused(*rows, section="6.3"):
    return ast.ReusedAvps(
        table="6.3/2",
        columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
        source=ast.SourceRef(section=section),
        rows=rows,
    )


def _rules(findings):
    return [f.rule for f in findings]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((("On", 1), ("Off", 1)), "the value 1 twice"),
        ((("On", 1), ("On", 2)), "the name 'On' twice"),
    ],
    ids=["repeated-value", "repeated-name"],
)
def test_duplicate_enum_values(values, expected):
    spec = _spec(
        _enumerated("Mode", 700, *(ast.EnumValue(name=n, value=v) for n, v in values))
    )

    (finding,) = [f for f in linter.lint(spec) if f.rule == "duplicate-enum-value"]

    assert expected in finding.message


def _vendor(first, last):
    return ast.VendorSpecificValues(first=first, last=last)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            (ast.EnumValue(name="On", value=150), _vendor(100, 199)),
            ["Mode's vendor-specific 100-199 overlaps 'On' = 150"],
        ),
        (
            (ast.ReservedValues(first=11, last=120), _vendor(100, 199)),
            ["Mode's vendor-specific 100-199 overlaps reserved 11-120"],
        ),
        (
            (_vendor(100, 199), _vendor(150, 250)),
            ["Mode's vendor-specific 100-199 overlaps vendor-specific 150-250"],
        ),
        (
            (ast.VoidValues(first=150, last=150), _vendor(100, 199)),
            ["Mode's vendor-specific 100-199 overlaps void 150-150"],
        ),
        # TS 32.299's SM-Service-Type: named, reserved and left to vendors,
        # each its own values.
        (
            (
                ast.EnumValue(name="On", value=10),
                ast.ReservedValues(first=11, last=99),
                _vendor(100, 199),
            ),
            [],
        ),
    ],
    ids=["named-value", "reserved-range", "vendor-range", "void-value", "disjoint"],
)
def test_a_vendor_specific_range_overlapping_another_line_is_an_error(values, expected):
    spec = _spec(_enumerated("Mode", 700, *values))

    findings = [f for f in linter.lint(spec) if f.rule == "vendor-specific-overlap"]

    assert [f.message for f in findings] == expected
    assert all(f.severity is linter.Severity.ERROR for f in findings)
    assert all(f.section == "6.3.2" for f in findings)


def _void(first, last=None):
    return ast.VoidValues(first=first, last=first if last is None else last)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            (ast.EnumValue(name="On", value=5), _void(5)),
            ["Mode's void 5-5 overlaps 'On' = 5"],
        ),
        (
            (_void(5, 9), ast.ReservedValues(first=9, last=20)),
            ["Mode's void 5-9 overlaps reserved 9-20"],
        ),
        (
            (_void(5), _void(5)),
            ["Mode's void 5-5 overlaps void 5-5"],
        ),
        # `vendor-specific-overlap` reports this one.
        ((_void(150), _vendor(100, 199)), []),
        # TS 29.214's Specific-Action, whose named values are others.
        (
            (_void(0), ast.EnumValue(name="On", value=1), _void(5)),
            [],
        ),
    ],
    ids=["named-value", "reserved-range", "void-value", "vendor-range", "disjoint"],
)
def test_a_void_value_overlapping_another_line_is_an_error(values, expected):
    spec = _spec(_enumerated("Mode", 700, *values))

    findings = [f for f in linter.lint(spec) if f.rule == "void-overlap"]

    assert [f.message for f in findings] == expected
    assert all(f.severity is linter.Severity.ERROR for f in findings)
    assert all(f.section == "6.3.2" for f in findings)


def test_the_file_vendor_is_what_local_avps_are_compared_in():
    """`; Vendor-ID:` supplies the half of an AVP's identity the rest of the file
    does not, so two files differing only in it disagree about collisions."""
    tgpp = _spec(_grouped("First", 700), _grouped("Second", 700))
    ietf = _spec(
        _grouped("First", 700, None),
        _grouped("Second", 700, None),
        vendor_id=0,
    )

    assert "duplicate-identity" in _rules(linter.lint(tgpp))
    assert "duplicate-identity" in _rules(linter.lint(ietf))
    assert "vendor 0" in next(
        f.message for f in linter.lint(ietf) if f.rule == "duplicate-identity"
    )


def test_a_definition_claiming_another_vendors_space():
    spec = _spec(_grouped("Example", 700, vendor_id=13019))

    (finding,) = [f for f in linter.lint(spec) if f.rule == "vendor-id-mismatch"]

    assert "vendor 13019" in finding.message
    assert "states vendor 10415" in finding.message


def _vendor_row(name, code, vendor_id, column="must"):
    return ast.AvpTableRow(
        name=name,
        vendor_id=vendor_id,
        code=code,
        flag_rules=ast.AvpFlagRules(**{column: frozenset({ast.AvpFlag.VENDOR})}),
    )


def _vendor_table(label, *rows):
    return ast.AvpTable(
        table=label,
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.VENDOR,
            ast.AvpColumn.CODE,
            ast.AvpColumn.MUST,
            ast.AvpColumn.MUST_NOT,
        ),
        source=ast.SourceRef(section="A.4"),
        rows=rows,
    )


def test_a_vendor_id_cell_its_v_flag_contradicts_is_an_error():
    """oneM2M TS-0004 table A.4-1 gives its own AVPs vendor 45687 and puts
    V under Must-not; RFC 6733 section 4.1.1 sets V exactly with a vendor."""
    spec = _spec(
        _vendor_table(
            "A.4-1",
            _vendor_row("Occupancy", 1012, 45687, "must_not"),
            _vendor_row("Session-Id", 263, 0, "must_not"),
            _vendor_row("Node-Id", 2064, 10415),
            _vendor_row("Odd", 1999, 0),
        ),
        specification="oneM2M TS-0004",
        vendor_id=45687,
    )

    found = [f for f in linter.lint(spec) if f.rule == "vendor-flag-mismatch"]

    assert [(f.severity, f.message.split(";")[0]) for f in found] == [
        (
            linter.Severity.ERROR,
            "Occupancy is tabulated with vendor 45687 with V under Must-not in"
            " table A.4-1",
        ),
        (
            linter.Severity.ERROR,
            "Odd is tabulated with vendor 0 with V under Must in table A.4-1",
        ),
    ]
    # Each row is its own identity: 0/263 and 10415/2064 and 45687/1012.
    assert "duplicate-identity" not in _rules(linter.lint(spec))


def test_two_tables_giving_one_avp_two_vendors_is_an_error():
    spec = _spec(
        _vendor_table("1", _vendor_row("Example", 1000, 45687)),
        _vendor_table("2", _vendor_row("Example", 1000, 10415)),
    )

    (finding,) = [f for f in linter.lint(spec) if f.rule == "table-row-mismatch"]

    assert finding.severity is linter.Severity.ERROR
    assert finding.message == (
        "Example is tabulated with differing vendor: 45687 in table 1; 10415 in table 2"
    )


def test_a_definition_is_compared_with_its_rows_vendor_id_cell():
    """oneM2M TS-0004 prints M2M-Information's header with no vendor-id
    (clause A.5.14) and its table A.4-1 row with vendor 45687."""
    forgot = _spec(
        _grouped("M2M-Information", 1011, vendor_id=None),
        _vendor_table("A.4-1", _vendor_row("M2M-Information", 1011, 45687)),
        vendor_id=45687,
    )
    ietf = _spec(
        _grouped("Accounting-Record-Type", 480, vendor_id=None),
        _vendor_table(
            "A.4-1", _vendor_row("Accounting-Record-Type", 480, 0, "must_not")
        ),
        vendor_id=45687,
    )

    (finding,) = [f for f in linter.lint(forgot) if f.rule == "vendor-id-mismatch"]

    assert finding.message == (
        "M2M-Information is defined with no vendor-id, but the AVP table gives"
        " it vendor 45687"
    )
    assert "vendor-id-mismatch" not in _rules(linter.lint(ietf))


def test_a_row_citing_its_own_document_is_no_re_use():
    """TS 29.212's Gxx and S9 tables cite TS 29.212 for Gx's AVPs: the
    definition is the file's own, so it is checked like one and not reported
    as defined here and re-used from elsewhere."""
    spec = _spec(
        _grouped("Own", 700, vendor_id=None),
        ast.AvpTable(
            table="6.3.1",
            columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.MUST),
            source=ast.SourceRef(section="6.3"),
            rows=(
                ast.AvpTableRow(
                    name="Own",
                    code=700,
                    flag_rules=ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR})),
                ),
            ),
        ),
        _reused(ast.ReusedAvpRow(name="Own", origin="TS29.329")),
    )

    assert _rules(linter.lint(spec)) == ["vendor-id-mismatch"]


def test_a_row_citing_its_own_document_for_nothing_it_has_is_an_error():
    spec = _spec(
        _table(_row("Own", 700)),
        _reused(ast.ReusedAvpRow(name="Elsewhere", origin="TS29.329")),
    )

    (finding,) = linter.lint(spec)

    assert finding.rule == "reused-avp-not-in-origin"
    assert finding.severity is linter.Severity.ERROR
    assert "Elsewhere" in finding.message


def test_errors_sort_before_notes():
    spec = _spec(
        _grouped("First", 700),
        _grouped("Second", 700),
        _reused(ast.ReusedAvpRow(name="First", origin="TS29.212")),
    )

    severities = [f.severity for f in linter.lint(spec)]

    assert severities == sorted(
        severities, key=lambda s: s is not linter.Severity.ERROR
    )


def _application(name, application_id, *applies_to, section="5.1"):
    return ast.ApplicationScope(
        name=name,
        source=ast.SourceRef(section=section),
        application_id=application_id,
        applies_to=applies_to,
    )


def _command(section, application_id=None):
    return ast.Message(
        name="Credit-Control-Request",
        abbreviation="CCR",
        source=ast.SourceRef(section=section),
        command_code=272,
        flags=frozenset({ast.CommandFlag.REQUEST}),
        application_id=application_id,
        avps=(),
    )


def test_a_command_in_the_scope_of_two_applications_is_an_error():
    spec = _spec(
        _application("Gx", 16777238, "5.*"),
        _application("Gxx", 16777266, "5.6.*", section="5a.1"),
        _command("5.6.2"),
        _command("5a.6.2"),
    )

    (finding,) = linter.lint(spec)

    assert finding.rule == "application-scope-overlap"
    assert finding.section == "5.6.2"
    assert "Gx (16777238, clause 5.1), Gxx (16777266, clause 5a.1)" in finding.message


def test_a_header_disagreeing_with_its_application_is_an_error():
    spec = _spec(
        _application("Gx", 16777238, "5.*"),
        _command("5.6.2", 16777238),
        _command("5.6.3", 16777266),
    )

    (finding,) = linter.lint(spec)

    assert finding.rule == "application-header-mismatch"
    assert finding.section == "5.6.3"
    assert "prints application 16777266" in finding.message


def _flagged_table(label, *rows, encrypt=True):
    columns = (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.TYPE,
        ast.AvpColumn.MUST,
        ast.AvpColumn.MUST_NOT,
    )
    return ast.AvpTable(
        table=label,
        columns=(*columns, ast.AvpColumn.ENCRYPT) if encrypt else columns,
        source=ast.SourceRef(section="6.3"),
        rows=rows,
    )


def _flagged_row(
    code=700, must=frozenset(), must_not=frozenset(), encrypt: bool | None = True
):
    return ast.AvpTableRow(
        name="Example",
        code=code,
        data_type=ast.DataType.UNSIGNED32,
        flag_rules=ast.AvpFlagRules(must=must, must_not=must_not),
        may_encrypt=encrypt,
    )


def test_a_row_forbidding_v_is_compared_in_ietf_space():
    """Two rows numbered 110 in vendor 10415's table, one of them with V
    under Must-not: RFC 4590's IETF `Digest-QoP` and a 3GPP AVP are two
    identities, as the model reads them; two rows requiring V collide."""

    def row(name, column):
        return ast.AvpTableRow(
            name=name,
            code=110,
            data_type=ast.DataType.UTF8_STRING,
            flag_rules=ast.AvpFlagRules(**{column: frozenset({ast.AvpFlag.VENDOR})}),
        )

    apart = _spec(
        _flagged_table("1", row("Digest-QoP", "must_not"), row("Other", "must"))
    )
    together = _spec(
        _flagged_table("1", row("Digest-QoP", "must"), row("Other", "must"))
    )

    assert "duplicate-identity" not in _rules(linter.lint(apart))
    (finding,) = [f for f in linter.lint(together) if f.rule == "duplicate-identity"]
    assert "vendor 10415, code 110" in finding.message


def _full_table(row):
    return ast.AvpTable(
        table="6.3.1",
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
            ast.AvpColumn.MUST,
            ast.AvpColumn.MUST_NOT,
            ast.AvpColumn.ENCRYPT,
        ),
        source=ast.SourceRef(section="6.3"),
        rows=(row,),
    )


@pytest.mark.parametrize(
    "row",
    [
        ast.AvpTableRow(
            name="Load",
            section="6.3.68",
            flag_rules=ast.AvpFlagRules(must_not=frozenset({ast.AvpFlag.MANDATORY})),
        ),
        ast.AvpTableRow(name="Sealed", section="6.3.69", may_encrypt=False),
        ast.AvpTableRow(name="AVP"),
    ],
    ids=lambda row: row.name,
)
def test_a_code_less_row_stating_flags_or_no_clause_is_an_error(row):
    (finding,) = linter.lint(_spec(_full_table(row)))

    assert (finding.severity, finding.rule) == (
        linter.Severity.ERROR,
        "row-without-code",
    )


def test_a_code_less_row_stating_only_its_clause_is_a_note():
    row = ast.AvpTableRow(name="Thing", section="6.3.43")

    (finding,) = linter.lint(_spec(_full_table(row)))

    assert (finding.severity, finding.rule) == (
        linter.Severity.NOTE,
        "row-without-code",
    )
    assert finding.section == "6.3.43"


def test_two_tables_disagreeing_on_a_code_is_an_error():
    """A row with no clause behind it is only caught here: neither code
    collides with anything, so `duplicate-identity` stays silent."""
    spec = _spec(
        _flagged_table("1", _flagged_row(700)), _flagged_table("2", _flagged_row(701))
    )

    (finding,) = linter.lint(spec)

    assert (finding.severity, finding.rule) == (
        linter.Severity.ERROR,
        "table-row-mismatch",
    )
    assert "700 in table 1; 701 in table 2" in finding.message


def test_two_tables_disagreeing_on_flags_is_a_note():
    mandatory = frozenset({ast.AvpFlag.MANDATORY})
    spec = _spec(
        _flagged_table("1", _flagged_row(must=mandatory)),
        _flagged_table("2", _flagged_row(must_not=mandatory)),
        _flagged_table("3", _flagged_row(must=mandatory)),
    )

    (finding,) = linter.lint(spec)

    assert (finding.severity, finding.rule) == (
        linter.Severity.NOTE,
        "table-row-mismatch",
    )
    assert finding.message == (
        "Example is tabulated with differing flag rules:"
        " Must M, M.not - in tables 1, 3; Must -, M.not M in table 2"
    )


def test_a_table_without_the_column_makes_no_claim_to_disagree_with():
    spec = _spec(
        _flagged_table("1", _flagged_row(encrypt=True)),
        _flagged_table("2", _flagged_row(encrypt=None), encrypt=False),
    )

    assert linter.lint(spec) == []


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
    # where clauses 5.2 and 10.1 set 3GPP's; clause 6.1's commands, which TS
    # 29.210's two application statements (6.1, 6.2) both reach as clause 6's.
    "29210-670.raw.dad": ["application-scope-overlap"] * 4 + ["vendor-id-mismatch"] * 4,
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
    # Clause 6.1 lists Service-Type's Callback Login (3) and Callback Framed
    # (4), then repeats both among the values it qualifies.
    "rfc4005.raw.dad": ["duplicate-enum-value"] * 4,
    # The wildcard row of table 7.1.0.1; two Integer32 rows clauses 7.2.111AaA
    # and 7.2.111AaB define as Enumerated; and every grouped header in clause
    # 7.2 printing no vendor while table 7.2.0.1 sets V.
    "32299-j00.raw.dad": ["row-without-code"]
    + ["table-definition-mismatch"] * 2
    + ["vendor-id-mismatch"] * 96,
    # Release 11: table 7.1's wildcard row, and the grouped headers of clause
    # 7.2 printing no vendor while table 7.2 sets V.
    "32299-bk0.raw.dad": ["row-without-code"] + ["vendor-id-mismatch"] * 66,
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

    assert _rules(errors) == _RAW_ERRORS.get(path.name, [])


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

    # AVPs each document both defines and lists as re-used, plus rows its
    # tables print differently (29.061's tables 9a and 10, see
    # `_STANDING_CORPUS_NOTES`; 29.273's two).
    expected = {
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
    stem = path.name.removesuffix(".dad")

    assert len(notes) == expected.get(stem, expected.get(stem.removesuffix(".raw"), 0))
    assert {f.rule for f in notes} <= {
        "local-and-reused",
        "member-marked-unused",
        "registry-range-overlap",
        "row-without-code",
        "section-mismatch",
        "section-unknown",
        "table-row-mismatch",
        "undefined-avp",
    }


# --- cross-file rules -------------------------------------------------------


def _origin_spec(specification, version, *sections):
    return ast.Specification(
        specification=specification, version=version, vendor_id=10415, sections=sections
    )


def _books(*specs):
    return corpus.Corpus(
        corpus.Entry(path=Path(f"{i}.dad"), spec=spec) for i, spec in enumerate(specs)
    )


def _grouped_with(name, code, *members, section="6.3.1"):
    return ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section=section),
        code=code,
        vendor_id=10415,
        avps=tuple(
            ast.AvpRule(name=member, presence=ast.Presence.OPTIONAL)
            for member in members
        ),
    )


def test_a_reprint_and_an_extension_are_told_apart():
    """The answer the single-file note declines to give. Both are legitimate
    and a reader wants to know which one they are looking at."""
    origin = _origin_spec(
        "3GPP TS 29.272", "18.6.0", _grouped_with("Borrowed", 700, "A")
    )

    reprint = _spec(
        _grouped_with("Borrowed", 700, "A"),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")),
        version="18.0.0",
    )
    extension = _spec(
        _grouped_with("Borrowed", 700, "A", "B"),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")),
        version="18.0.0",
    )

    assert "reused-reprint" in _rules(linter.lint_with_corpus(reprint, _books(origin)))
    (finding,) = [
        f
        for f in linter.lint_with_corpus(extension, _books(origin))
        if f.rule == "reused-extension"
    ]
    assert "adding B" in finding.message


def test_a_body_that_neither_reprints_nor_extends_is_reported_as_it_is():
    """TS 29.388's V2X-Subscription-Data both adds and omits against 29.272's.
    That is a fact about two documents, not a defect in one, so it is a note
    and the message says exactly what differs."""
    origin = _origin_spec(
        "3GPP TS 29.272", "18.6.0", _grouped_with("Borrowed", 700, "A", "B")
    )
    spec = _spec(
        _grouped_with("Borrowed", 700, "A", "C"),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")),
        version="18.0.0",
    )

    (finding,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-body-differs"
    ]

    assert finding.severity is linter.Severity.NOTE
    assert "adds C" in finding.message and "missing B" in finding.message


def _differing_body():
    """TS 29.336's Serving-Node shape: a body differing from its origin's."""
    origin = _origin_spec(
        "3GPP TS 29.272", "18.6.0", _grouped_with("Borrowed", 700, "A", "B")
    )
    spec = _spec(
        _grouped_with("Borrowed", 700, "A", "C"),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")),
        version="18.0.0",
    )
    return spec, _books(origin)


_DIFFERS = "Borrowed's body, against TS29.272's definition: adds C, missing B"


def _acceptance(target=None, expect=_DIFFERS, rule="reused-body-differs"):
    return corrections.Accept(
        id="borrowed-body",
        rule=rule,
        target=target or corrections.definition("Borrowed"),
        expect=expect,
        reason="clause 6.3.1 prints the interface's own body",
    )


def test_an_accepted_note_is_reported_apart_citing_its_acceptance():
    spec, books = _differing_body()

    findings = linter.lint_with_corpus(spec, books, [_acceptance()])

    (finding,) = [f for f in findings if f.rule == "reused-body-differs"]
    assert finding.severity is linter.Severity.ACCEPTED
    assert finding.accepted_by == "borrowed-body"
    assert str(finding).startswith("accepted: [reused-body-differs]")
    # The fixture's members are names only; nothing else is an error.
    assert {f.rule for f in findings if f.severity is linter.Severity.ERROR} == {
        "unresolved-reference"
    }


@pytest.mark.parametrize(
    ("acceptance", "problem"),
    [
        # The document changed what it says: the message moved on.
        (
            _acceptance(expect=_DIFFERS.replace("adds C", "adds D")),
            f"no finding about it reads as expected; it now reads {_DIFFERS!r}",
        ),
        (_acceptance(rule="reused-reprint"), "no finding about it reads as expected"),
        (
            _acceptance(target=corrections.definition("Lent")),
            "its target matches 0 nodes",
        ),
        # The node exists, but the finding is about another.
        (
            _acceptance(target=corrections.definition("Own")),
            "no finding about it reads as expected",
        ),
    ],
)
def test_an_acceptance_matching_no_finding_is_a_stale_error(acceptance, problem):
    spec, books = _differing_body()
    spec = spec.model_copy(
        update={"sections": (*spec.sections, _grouped("Own", 701, section="6.3.2"))}
    )

    findings = linter.lint_with_corpus(spec, books, [acceptance])

    (stale,) = [f for f in findings if f.rule == "stale-acceptance"]
    assert stale.severity is linter.Severity.ERROR
    assert stale.message.endswith(f"but {problem}")
    (kept,) = [f for f in findings if f.rule == "reused-body-differs"]
    assert kept.severity is linter.Severity.NOTE


def test_an_acceptance_covers_only_the_node_its_target_selects():
    """Two clauses defining `Borrowed`: 6.3.1 re-prints the origin's body,
    6.3.2 differs from it. Accepting 6.3.1's body as differing must not
    take 6.3.2's finding, whose name and message it shares."""
    origin = _origin_spec(
        "3GPP TS 29.272", "18.6.0", _grouped_with("Borrowed", 700, "A", "B")
    )
    spec = _spec(
        _grouped_with("Borrowed", 700, "A", "B", section="6.3.1"),
        _grouped_with("Borrowed", 700, "A", "C", section="6.3.2"),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")),
        version="18.0.0",
    )

    findings = linter.lint_with_corpus(
        spec,
        _books(origin),
        [_acceptance(target=corrections.definition("Borrowed", section="6.3.1"))],
    )

    (differs,) = [f for f in findings if f.rule == "reused-body-differs"]
    assert differs.severity is linter.Severity.NOTE
    assert differs.section == "6.3.2"
    (stale,) = [f for f in findings if f.rule == "stale-acceptance"]
    assert stale.message.endswith("but no finding about it reads as expected")


def test_an_error_is_never_accepted():
    """An error is the file asserting two things that cannot both be true;
    no clause makes that deliberate."""
    spec = _spec(_grouped("Twice", 700), _grouped("Twice", 700, section="6.3.2"))
    (error,) = [f for f in linter.lint(spec) if f.rule == "duplicate-definition"]

    findings = linter.accept(
        spec,
        linter.lint(spec),
        [
            _acceptance(
                target=corrections.definition("Twice", section="6.3.1"),
                expect=error.message,
                rule="duplicate-definition",
            )
        ],
    )

    assert error in findings
    (stale,) = [f for f in findings if f.rule == "stale-acceptance"]
    assert stale.message.endswith("but the finding is error")


@pytest.mark.parametrize(
    ("declare", "message"),
    [
        (lambda: _acceptance(rule="Reused Body"), "names no linter rule"),
        (lambda: _acceptance(expect=""), "expects no finding"),
    ],
)
def test_acceptance_declarations_that_cannot_mean_anything_are_rejected(
    declare, message
):
    with pytest.raises(corrections.CorrectionError, match=message):
        declare()


def _origin_row(name, code, data_type, must=(), must_not=()):
    return ast.AvpTableRow(
        name=name,
        code=code,
        data_type=data_type,
        flag_rules=ast.AvpFlagRules(must=frozenset(must), must_not=frozenset(must_not)),
    )


def _flag_table(*rows, label="6.3.1", section="6.3"):
    return ast.AvpTable(
        table=label,
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.TYPE,
            ast.AvpColumn.MUST,
            ast.AvpColumn.MUST_NOT,
        ),
        source=ast.SourceRef(section=section),
        rows=rows,
    )


_M, _V, _P = ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR, ast.AvpFlag.PROTECTED


@pytest.mark.parametrize(
    ("ours", "theirs", "expected"),
    [
        # M placed in two different columns.
        (
            (ast.DataType.ENUMERATED, (_M, _V), ()),
            (ast.DataType.ENUMERATED, (_V,), (_M,)),
            ["flag rule M in Must"],
        ),
        (
            (ast.DataType.UNSIGNED32, (_V,), ()),
            (ast.DataType.ENUMERATED, (_V,), ()),
            ["type Unsigned32"],
        ),
        # The origin places M nowhere, RFC 7683's way: nothing to disagree with.
        (
            (ast.DataType.ENUMERATED, (_V,), (_M,)),
            (ast.DataType.ENUMERATED, (_V,), ()),
            [],
        ),
        # P is compared nowhere.
        (
            (ast.DataType.ENUMERATED, (_V,), (_P,)),
            (ast.DataType.ENUMERATED, (_V, _P), ()),
            [],
        ),
    ],
    ids=["flag", "type", "unplaced", "p-bit"],
)
def test_a_tabulated_re_used_avp_is_compared_with_its_origin(ours, theirs, expected):
    origin = _origin_spec(
        "3GPP TS 29.212", "18.0.0", _flag_table(_origin_row("Shared", 1032, *theirs))
    )
    spec = _origin_spec(
        "3GPP TS 29.273",
        "18.0.0",
        _flag_table(_origin_row("Shared", 1032, *ours)),
        _reused(ast.ReusedAvpRow(name="Shared", origin="TS29.212")),
    )

    found = [
        f.message.split(" is tabulated with ")[1].split(" in table")[0]
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-row-mismatch"
    ]

    assert found == expected


def test_a_re_used_rows_note_says_which_side_the_model_follows():
    """Flag rules are the citing application's (RFC 6733 sections 4.1 and
    4.5), so the model reads each flag from the citing file's first row
    placing it; a second table's row names that one. The type stays the
    origin's."""
    origin = _origin_spec(
        "3GPP TS 29.212",
        "18.0.0",
        _flag_table(_origin_row("Shared", 1032, ast.DataType.ENUMERATED, (_V,), (_M,))),
    )
    ours = _origin_row("Shared", 1032, ast.DataType.UNSIGNED32, (_M, _V))
    spec = _origin_spec(
        "3GPP TS 29.273",
        "18.0.0",
        _flag_table(ours, label="6.3.1"),
        _flag_table(ours.model_copy(), label="6.3.2"),
        _reused(ast.ReusedAvpRow(name="Shared", origin="TS29.212")),
    )

    found = sorted(
        f.message.split("; the model follows ")[1]
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-row-mismatch"
    )

    assert found == [
        "TS29.212",
        "TS29.212",
        "an earlier row for M, in table 6.3.1",
        "this row for M",
    ]


def test_a_re_used_rows_note_names_the_row_placing_the_disputed_flag():
    """The origin sets M; the citing file's first row places V alone and its
    second forbids M. The model reads M from the second row, the first
    saying nothing of it, and the note on the second says so."""
    origin = _origin_spec(
        "3GPP TS 29.212",
        "18.0.0",
        _flag_table(_origin_row("Shared", 1032, ast.DataType.UNSIGNED32, (_M, _V))),
    )
    spec = _origin_spec(
        "3GPP TS 29.273",
        "18.0.0",
        _flag_table(
            _origin_row("Shared", 1032, ast.DataType.UNSIGNED32, (_V,)), label="6.3.1"
        ),
        _flag_table(
            _origin_row("Shared", 1032, ast.DataType.UNSIGNED32, (_V,), (_M,)),
            label="6.3.2",
        ),
        _reused(ast.ReusedAvpRow(name="Shared", origin="TS29.212")),
    )

    (found,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-row-mismatch"
    ]

    assert found.message == (
        "Shared is tabulated with flag rule M in M.not in table 6.3.2, but"
        " TS29.212, which it is re-used from, reads M in Must in table 6.3.1;"
        " the model follows this row for M"
    )


def test_a_re_used_avp_tabulated_nowhere_in_its_origin_is_typed_by_its_definition():
    origin = _origin_spec("3GPP TS 29.212", "18.0.0", _grouped_with("Shared", 1032))
    spec = _origin_spec(
        "3GPP TS 29.273",
        "18.0.0",
        _flag_table(_origin_row("Shared", 1032, ast.DataType.OCTET_STRING)),
        _reused(ast.ReusedAvpRow(name="Shared", origin="TS29.212")),
    )

    (finding,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-row-mismatch"
    ]

    assert finding.severity is linter.Severity.NOTE
    assert "reads Grouped in its clause 6.3.1" in finding.message


_SHARED_V = _flag_table(
    _origin_row("Shared", 1032, ast.DataType.ENUMERATED, must=(_V,))
)


@pytest.mark.parametrize(
    ("ours", "theirs", "expected"),
    [
        # A Vendor-ID cell agreeing with the origin row's V under Must, read in
        # the origin's file vendor.
        (_vendor_table("A.4-1", _vendor_row("Shared", 1032, 10415)), _SHARED_V, []),
        (
            _vendor_table("A.4-1", _vendor_row("Shared", 1032, 45687)),
            _SHARED_V,
            [
                "Shared is tabulated in vendor 45687 in table A.4-1, but TS29.212,"
                " which it is re-used from, reads vendor 10415 in table 6.3.1"
            ],
        ),
        # The origin's header states the vendor, as TS 183 017's do 13019.
        (
            _vendor_table("A.4-1", _vendor_row("Shared", 1032, 13019)),
            _grouped("Shared", 1032, vendor_id=13019),
            [],
        ),
        # No cell: V under Must puts the row in the file's vendor, against an
        # origin header with no vendor-id, IETF space.
        (
            _SHARED_V,
            _grouped("Shared", 1032, vendor_id=None),
            [
                "Shared is tabulated in vendor 10415 in table 6.3.1, but TS29.212,"
                " which it is re-used from, reads vendor 0 in its clause 6.3.1"
            ],
        ),
        # V under Must-not is IETF space, TS 29.229's Digest-* rows' reading.
        (
            _flag_table(
                _origin_row("Shared", 1032, ast.DataType.ENUMERATED, must_not=(_V,))
            ),
            _grouped("Shared", 1032, vendor_id=None),
            [],
        ),
        # A row placing V nowhere states no vendor, and agrees with any.
        (
            _flag_table(_origin_row("Shared", 1032, ast.DataType.ENUMERATED)),
            _grouped("Shared", 1032, vendor_id=13019),
            [],
        ),
    ],
    ids=[
        "cell-agrees",
        "cell-disagrees",
        "cell-against-header",
        "no-cell-file-vendor",
        "no-cell-ietf",
        "no-cell-no-v",
    ],
)
def test_a_tabulated_re_used_avp_is_in_its_origins_vendor_space(ours, theirs, expected):
    origin = _origin_spec("3GPP TS 29.212", "18.0.0", theirs)
    spec = _origin_spec(
        "3GPP TS 29.273",
        "18.0.0",
        ours,
        _reused(ast.ReusedAvpRow(name="Shared", origin="TS29.212")),
    )

    found = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-row-vendor-mismatch"
    ]

    assert [f.message for f in found] == expected
    assert all(f.severity is linter.Severity.ERROR for f in found)


def test_two_documents_disagreeing_on_a_code_is_an_error():
    """An AVP is its (vendor-id, code), so two codes are two AVPs and one of
    the documents is wrong — the one thing here that is not a judgement call."""
    origin = _origin_spec("3GPP TS 29.272", "18.6.0", _grouped_with("Borrowed", 700))
    spec = _spec(
        _grouped_with("Borrowed", 701),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")),
        version="18.0.0",
    )

    (finding,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-code-conflict"
    ]

    assert finding.severity is linter.Severity.ERROR
    assert "701 here and 700" in finding.message


def test_a_re_used_tables_code_and_type_cells_are_compared_with_the_origin():
    """TS 29.172 table 7.4.1-2 prints the code and type of what it re-uses;
    the origin's definition states both."""
    origin = _origin_spec("3GPP TS 29.272", "18.6.0", _grouped_with("Borrowed", 700))
    spec = _spec(
        ast.ReusedAvps(
            table="7.4.1-2",
            columns=(
                ast.ReusedColumn.NAME,
                ast.ReusedColumn.CODE,
                ast.ReusedColumn.FROM,
                ast.ReusedColumn.TYPE,
            ),
            source=ast.SourceRef(section="7.4.1"),
            rows=(
                ast.ReusedAvpRow(
                    name="Borrowed",
                    origin="TS29.272",
                    code=701,
                    data_type=ast.DataType.UNSIGNED32,
                ),
            ),
        ),
        version="18.0.0",
    )

    found = {
        f.rule: f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule in ("reused-code-conflict", "reused-row-mismatch")
    }

    assert found["reused-code-conflict"].severity is linter.Severity.ERROR
    assert "code 701 in re-used table 7.4.1-2 and 700" in (
        found["reused-code-conflict"].message
    )
    assert "typed Unsigned32 in re-used table 7.4.1-2" in (
        found["reused-row-mismatch"].message
    )
    assert found["reused-row-mismatch"].message.endswith(
        "reads Grouped; the model follows TS29.272"
    )


def test_a_tabulated_code_for_a_re_used_avp_is_compared_with_the_origin():
    """TS 29.283 clause 7.3.21 says its Sequence-Number is TS 29.329's, whose is
    716, while table 7.3.1-1 gives 4512; TS 29.140 tabulates the codes of the
    AVPs it re-uses, and they agree."""
    origin = _origin_spec(
        "3GPP TS 29.329",
        "18.0.0",
        ast.AvpTable(
            table="6.3.1",
            source=ast.SourceRef(section="6.3"),
            columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE),
            rows=(
                ast.AvpTableRow(name="Sequence-Number", code=716),
                ast.AvpTableRow(name="MSISDN", code=701),
            ),
        ),
    )
    spec = _spec(
        ast.AvpTable(
            table="7.3.1-1",
            source=ast.SourceRef(section="7.3.1"),
            columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE),
            rows=(
                ast.AvpTableRow(name="Sequence-Number", code=4512),
                ast.AvpTableRow(name="MSISDN", code=701),
            ),
        ),
        ast.ReusedAvps(
            source=ast.SourceRef(section="7.3.21"),
            columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
            rows=(
                ast.ReusedAvpRow(name="Sequence-Number", origin="TS29.329"),
                ast.ReusedAvpRow(name="MSISDN", origin="TS29.329"),
            ),
        ),
        specification="3GPP TS 29.283",
        version="18.0.0",
    )

    (conflict,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-code-conflict"
    ]

    assert conflict.severity is linter.Severity.ERROR
    assert conflict.message == (
        "Sequence-Number is code 4512 in table 7.3.1-1 and 716 in TS29.329, which"
        " it is listed as re-used from"
    )
    assert conflict.paths == (("sections", 0, "rows", 0),)


def test_a_member_its_table_marks_unused_in_its_command_is_a_note():
    """TS 32.299 clause 7.1.0: "Those Diameter AVPs that are not used are
    marked '-'". A blank cell marks nothing, and another command's dash
    says nothing of this one."""
    acr = ast.MarkColumn.ACR
    table = ast.AvpTable(
        table="7.1.0.1",
        source=ast.SourceRef(section="7.1.0"),
        columns=(ast.AvpColumn.NAME, ast.AvpColumn.ACR, ast.AvpColumn.ACA),
        rows=(
            ast.AvpTableRow(name="Dashed", marks={acr: ()}),
            ast.AvpTableRow(name="Blank"),
            ast.AvpTableRow(name="Other", marks={acr: ("M",), ast.MarkColumn.ACA: ()}),
        ),
    )
    message = ast.Message(
        name="Accounting-Request",
        abbreviation="ACR",
        source=ast.SourceRef(section="6.2.2"),
        command_code=271,
        flags=frozenset({ast.CommandFlag.REQUEST}),
        application_id=3,
        avps=tuple(
            ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL)
            for name in ("Dashed", "Blank", "Other")
        ),
    )

    (finding,) = [
        f
        for f in linter.lint(_spec(message, table))
        if f.rule == "member-marked-unused"
    ]

    assert finding.severity is linter.Severity.NOTE
    assert finding.message.startswith("Dashed is a member of ACR, but table 7.1.0.1")
    assert finding.section == "6.2.2"


def test_an_avp_the_origin_never_heard_of():
    """TS 29.283 cites Feature-Id from TS 29.229, which has no such AVP."""
    origin = _origin_spec("3GPP TS 29.229", "18.1.0", _grouped_with("Something", 700))
    spec = _spec(
        _reused(ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229")),
        version="18.0.0",
    )

    (finding,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-avp-not-in-origin"
    ]

    assert finding.severity is linter.Severity.ERROR


def test_an_origin_that_borrows_the_avp_itself_is_a_note_not_an_error():
    """TS 29.172 cites Service-Selection from TS 29.272, which carries it as
    RFC 5778's. The AVP is real; the citation names a middleman."""
    origin = _origin_spec(
        "3GPP TS 29.272",
        "18.6.0",
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="RFC5778")),
    )
    spec = _spec(
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")), version="18.0.0"
    )

    (finding,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule == "reused-origin-indirect"
    ]

    assert finding.severity is linter.Severity.NOTE
    assert "RFC5778" in finding.message


def test_an_origin_resolved_across_releases_is_a_note_naming_the_rule():
    """TS 29.140 ends at V7.0.0; a Release 19 document's non-specific
    reference reads as that final version (`corpus.FINAL_VERSIONS`), the
    cross-file rules run against it, and a note says so for audit."""
    spec = _spec(
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.140")),
        specification="3GPP TS 32.299",
        version="18.0.0",
    )
    origin = _origin_spec("3GPP TS 29.140", "7.0.0", _grouped_with("Other", 700))

    findings = linter.lint_with_corpus(spec, _books(origin))

    (crossing,) = [f for f in findings if f.rule == "cross-release-origin"]
    assert crossing.severity is linter.Severity.NOTE
    assert crossing.message == (
        "TS29.140 is resolved across releases to 0.dad: 3GPP TS 32.299 V18.0.0"
        " is the citing file, and it cites the document non-specifically,"
        " which reads as its final version, V7.0.0 (corpus.FINAL_VERSIONS)"
    )
    assert "origin-not-in-corpus" not in _rules(findings)
    assert "reused-avp-not-in-origin" in _rules(findings)


def _tgpp2_origin(revision):
    return ast.Specification(
        specification="3GPP2 X.S0057",
        version="2.0",
        vendor_id=5535,
        transcribed=pydantic.HttpUrl(
            f"http://example.test/X.S0057-{revision}_v2.0_091215.pdf"
        ),
        sections=(_grouped_with("Borrowed", 700),),
    )


def test_a_revision_standing_in_for_the_cited_one_is_a_note_with_its_evidence():
    """TS 29.212 cites 3GPP2 X.S0057-B, which 3GPP2's library does not
    publish; revision 0 V2.0 answers it only by its `corpus.STAND_INS`
    entry, and a note says so with the entry's evidence."""
    spec = _spec(
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="3GPP2-X.S0057")),
        specification="3GPP TS 29.212",
        version="18.2.0",
    )

    findings = linter.lint_with_corpus(spec, _books(_tgpp2_origin("0")))

    (crossing,) = [f for f in findings if f.rule == "cross-release-origin"]
    assert crossing.severity is linter.Severity.NOTE
    assert crossing.message == (
        "3GPP2-X.S0057 is resolved across releases to 0.dad: 3GPP TS 29.212"
        " V18.2.0 is the citing file, and its references name revision B,"
        " which the corpus lacks, and revision 0 V2.0 stands in: "
        + corpus.STAND_INS["TS29.212", "3GPP2-X.S0057"].evidence
        + " (corpus.STAND_INS)"
    )
    assert "external-origin-not-in-corpus" not in _rules(findings)


def test_a_later_release_standing_in_is_a_note_with_its_evidence():
    """TS 32.299 V11.20.0 cites TS 29.329 non-specifically, meaning
    V11.7.0, which the corpus lacks; V19.1.0 answers by its
    `corpus.RELEASE_STAND_INS` entry, and the note quotes the evidence."""
    spec = _spec(
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.329")),
        specification="3GPP TS 32.299",
        version="11.20.0",
    )
    origin = _origin_spec("3GPP TS 29.329", "19.1.0", _grouped_with("Borrowed", 700))

    findings = linter.lint_with_corpus(spec, _books(origin))

    (crossing,) = [f for f in findings if f.rule == "cross-release-origin"]
    assert crossing.message == (
        "TS29.329 is resolved across releases to 0.dad: 3GPP TS 32.299"
        " V11.20.0 is the citing file, and it cites the document"
        " non-specifically, meaning V11.7.0, which the corpus lacks, and"
        " V19.1.0 stands in: "
        + corpus.RELEASE_STAND_INS["TS32.299", "11.20.0", "TS29.329"].evidence
        + " (corpus.RELEASE_STAND_INS)"
    )
    assert "origin-not-in-corpus" not in _rules(findings)


def test_a_later_release_stating_a_field_is_a_note_with_its_evidence():
    """TS 29.210 V6.7.0's TS 29.061 is V6.15.0, in its own release, so that
    resolution is no crossing; the type V19.1.0 states by its
    `corpus.RELEASE_FILLS` entry is, and the note names the fields and AVPs."""
    spec = _spec(
        _reused(ast.ReusedAvpRow(name="3GPP-SGSN-MCC-MNC", origin="TS29.061")),
        specification="3GPP TS 29.210",
        version="6.7.0",
    )
    origins = [
        _origin_spec(
            "3GPP TS 29.061",
            version,
            _table(_row("3GPP-SGSN-MCC-MNC", 18, ast.DataType.UTF8_STRING)),
        )
        for version in ("6.15.0", "19.1.0")
    ]

    findings = linter.lint_with_corpus(spec, _books(*origins))

    (crossing,) = [f for f in findings if f.rule == "cross-release-origin"]
    assert crossing.message == (
        "TS29.061 is resolved across releases to 1.dad for data_type of"
        " 3GPP-GPRS-Negotiated-QoS-Profile, 3GPP-SGSN-MCC-MNC: 3GPP TS 29.210"
        " V6.7.0 is the citing file, and it cites the document non-specifically,"
        " meaning V6.15.0, which answers for all else and leaves those unstated,"
        " and V19.1.0 states them: "
        + corpus.RELEASE_FILLS["TS29.210", "6.7.0", "TS29.061"].evidence
        + " (corpus.RELEASE_FILLS)"
    )


def test_an_unresolvable_origin_is_one_note_and_keeps_the_single_file_answer():
    """A partial corpus must stay useful: the rules that needed the missing
    document are skipped, and the single-file note it would have superseded
    is kept rather than silently dropped."""
    spec = _spec(
        _grouped_with("Borrowed", 700),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.212")),
        version="18.0.0",
    )

    rules = _rules(linter.lint_with_corpus(spec, _books()))

    assert "origin-not-in-corpus" in rules
    assert "local-and-reused" in rules


def test_an_origin_outside_3gpp_and_ietf_is_a_note_of_its_own():
    spec = _spec(
        _reused(
            ast.ReusedAvpRow(name="Borrowed", origin="TS29.212"),
            ast.ReusedAvpRow(name="Elsewhere", origin="oneM2M-TS-0004"),
        ),
        version="18.0.0",
    )

    found = {f.rule: f for f in linter.lint_with_corpus(spec, _books())}

    assert found["origin-not-in-corpus"].message.endswith(": TS29.212")
    external = found["external-origin-not-in-corpus"]
    assert external.severity is linter.Severity.NOTE
    assert external.message.startswith("1 of 2 cited origins are documents outside")
    assert external.message.endswith(": oneM2M-TS-0004")


def test_a_hand_written_external_origin_resolves():
    origin = _origin_spec("ETSI ES 283 034", "2.2.0", _grouped_with("Borrowed", 700))
    spec = _spec(
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="ETSI-TS283.034")),
        version="18.0.0",
    )

    rules = _rules(linter.lint_with_corpus(spec, _books(origin)))

    assert "external-origin-not-in-corpus" not in rules
    assert "reused-avp-not-in-origin" not in rules


def test_resolving_the_origin_replaces_the_single_file_note():
    origin = _origin_spec("3GPP TS 29.272", "18.6.0", _grouped_with("Borrowed", 700))
    spec = _spec(
        _grouped_with("Borrowed", 700),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.272")),
        version="18.0.0",
    )

    rules = _rules(linter.lint_with_corpus(spec, _books(origin)))

    assert "reused-reprint" in rules
    assert "local-and-reused" not in rules


def test_re_used_rows_join_the_identity_check_once_their_vendor_is_known():
    """The single-file rule skips them because their vendor space is the
    origin's to state. With the origin readable, TS 29.229's two 621s are
    still not a collision — but two rows in one vendor space would be."""
    ietf = ast.Specification(
        specification="RFC 7683",
        version="1.0.0",
        vendor_id=0,
        sections=(_grouped_with("OC-Supported-Features", 621),),
    )
    spec = _spec(
        _table(_row("Local-AVP", 621), _row("OC-Supported-Features", 621)),
        _reused(ast.ReusedAvpRow(name="OC-Supported-Features", origin="RFC7683")),
        version="18.0.0",
    )

    assert "duplicate-identity" not in _rules(
        linter.lint_with_corpus(spec, _books(ietf))
    )


def test_references_resolve_against_a_base_document():
    """`; Bases:` supplies the names no re-used table cites — RFC 6733's
    `Session-Id` and friends — so a message referencing them is resolved
    rather than reported. The trailing `* [ AVP ]` is the base protocol's
    any-AVP wildcard, not a reference."""
    base = ast.Specification(
        specification="RFC 6733",
        vendor_id=0,
        sections=(
            _table(
                ast.AvpTableRow(name="Session-Id", code=263),
                _row("Local-Group", 700),
            ),
        ),
    )
    spec = ast.Specification(
        specification="3GPP TS 29.329",
        version="18.0.0",
        vendor_id=10415,
        bases=("RFC6733",),
        sections=(
            ast.Message(
                name="Example-Request",
                abbreviation="EXR",
                source=ast.SourceRef(section="6.1.1"),
                command_code=306,
                flags=frozenset({ast.CommandFlag.REQUEST}),
                application_id=16777217,
                avps=(
                    ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),
                    ast.AvpRule(name="Mystery", presence=ast.Presence.OPTIONAL),
                    ast.AvpRule(name="AVP", presence=ast.Presence.OPTIONAL),
                ),
            ),
        ),
    )

    findings = linter.lint_with_corpus(spec, _books(base))
    (unresolved,) = [f for f in findings if f.rule == "unresolved-reference"]

    assert unresolved.severity is linter.Severity.ERROR
    assert "Mystery" in unresolved.message
    assert "Session-Id" not in unresolved.message


def test_a_base_missing_from_the_corpus_is_a_note_and_turns_the_rule_off():
    spec = ast.Specification(
        specification="3GPP TS 29.329",
        version="18.0.0",
        vendor_id=10415,
        bases=("RFC6733",),
        sections=(
            _grouped_with("Example", 700, "Session-Id"),
            _table(_row("Example", 700)),
        ),
    )

    findings = linter.lint_with_corpus(spec, _books())
    rules = _rules(findings)

    assert "base-not-in-corpus" in rules
    assert "unresolved-reference" not in rules


def _reprinted(
    name="Base-Grouped", code=260, *members, origin="RFC6733", section="4.2"
):
    return ast.ReprintedAvp(
        name=name,
        source=ast.SourceRef(section=section),
        origin=origin,
        code=code,
        avps=tuple(
            ast.AvpRule(name=member, presence=ast.Presence.OPTIONAL)
            for member in members
        ),
    )


def _rfc6733(*sections):
    return ast.Specification(specification="RFC 6733", vendor_id=0, sections=sections)


def test_a_reprint_printed_three_times_is_no_duplicate():
    # TS 29.109 prints RFC 6733's rule in clauses 4.2, 5.2 and 5.4.
    spec = _spec(
        _reprinted("Base-Grouped", 260, "Member", section="4.2"),
        _reprinted("Base-Grouped", 260, "Member", section="5.2"),
        _reprinted("Base-Grouped", 260, "Member", section="5.4"),
    )
    origin = _rfc6733(_grouped_with("Base-Grouped", 260, "Member"))

    assert linter.lint(spec) == []
    assert not [
        f
        for f in linter.lint_with_corpus(spec, _books(origin))
        if f.rule.startswith(("duplicate", "reprint", "reused"))
    ]


@pytest.mark.parametrize(
    ("origin", "severity", "rule", "message"),
    [
        (
            _grouped_with("Other", 261),
            linter.Severity.ERROR,
            "reprint-not-in-origin",
            "Base-Grouped is printed as RFC6733's, which does not define it",
        ),
        (
            _grouped_with("Base-Grouped", 299, "Member"),
            linter.Severity.ERROR,
            "reused-code-conflict",
            "Base-Grouped is code 260 here and 299 in RFC6733",
        ),
        (
            _grouped_with("Base-Grouped", 260, "Gone"),
            linter.Severity.NOTE,
            "reprint-differs",
            "Base-Grouped's body, against RFC6733's definition: adds Member,"
            " missing Gone",
        ),
    ],
    ids=["undefined", "another-code", "other-members"],
)
def test_a_reprint_is_held_to_the_document_it_names(origin, severity, rule, message):
    spec = _spec(_reprinted("Base-Grouped", 260, "Member"))

    (finding,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(_rfc6733(origin)))
        if f.rule == rule
    ]

    assert (finding.severity, finding.message) == (severity, message)


def test_a_reprint_of_a_document_the_corpus_lacks_says_so():
    spec = _spec(_reprinted("Base-Grouped", 260, "Member"))

    assert "origin-not-in-corpus" in _rules(linter.lint_with_corpus(spec, _books()))


def _undefined(name="Mystery", section="6.3.1"):
    return ast.UndefinedAvp(name=name, source=ast.SourceRef(section=section))


def _naming_mystery(*sections):
    """A grouped body in clause 6.3.1 naming a member nothing defines, and
    in clause 6.3.2 another naming it again."""
    return _spec(
        _grouped_with("Holder", 700, "Mystery", section="6.3.1"),
        _grouped_with("Other", 701, "Mystery", section="6.3.2"),
        _table(_row("Holder", 700), _row("Other", 701)),
        *sections,
    )


def test_an_undefined_avp_block_is_a_note_naming_where_it_is_referenced():
    (finding,) = [
        f for f in linter.lint(_naming_mystery(_undefined())) if "undefined" in f.rule
    ]

    assert finding.severity is linter.Severity.NOTE
    assert str(finding) == (
        "note: [undefined-avp] Mystery is referenced in clauses 6.3.1, 6.3.2"
        " and declared undefined (clause 6.3.1)"
    )
    assert finding.paths == (("sections", 3),)


@pytest.mark.parametrize(
    ("block", "message"),
    [
        (
            _undefined("Absent"),
            "Absent is declared undefined, but no body references it",
        ),
        (
            _undefined(section="6.3"),
            "Mystery is declared undefined citing a clause whose bodies do not"
            " reference it; it is referenced in clauses 6.3.1, 6.3.2",
        ),
    ],
    ids=["by-name", "by-clause"],
)
def test_an_undefined_avp_block_nothing_references_is_an_error(block, message):
    findings = [
        f for f in linter.lint(_naming_mystery(block)) if f.rule.startswith("undefined")
    ]

    assert [(f.severity, f.rule, f.message) for f in findings] == [
        (linter.Severity.ERROR, "undefined-avp-unused", message)
    ]


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        (
            (_grouped_with("Mystery", 702),),
            "Mystery is declared undefined, but the file defines, tabulates or"
            " re-uses it",
        ),
        (
            (_table(_row("Mystery", 702, ast.DataType.UTF8_STRING)),),
            "Mystery is declared undefined, but the file defines, tabulates or"
            " re-uses it",
        ),
        (
            (_reused(ast.ReusedAvpRow(name="Mystery", origin="TS29.272")),),
            "Mystery is declared undefined, but the file defines, tabulates or"
            " re-uses it",
        ),
        ((_undefined(),), "Mystery is declared undefined 2 times"),
    ],
    ids=["defined", "tabulated", "re-used", "twice"],
)
def test_an_undefined_avp_block_for_a_name_the_file_knows_is_an_error(
    sections, message
):
    findings = linter.lint(_naming_mystery(_undefined(), *sections))

    assert message in [
        f.message
        for f in findings
        if f.rule == "undefined-avp-defined" and f.severity is linter.Severity.ERROR
    ]


def test_an_undefined_avp_a_base_resolves_is_an_error_with_the_corpus():
    base = _origin_spec("RFC 6733", None, _table(_row("Mystery", 9, ast.DataType.TIME)))
    spec = _naming_mystery(_undefined()).model_copy(update={"bases": ("RFC6733",)})

    assert "undefined-avp-defined" not in _rules(linter.lint(spec))
    findings = linter.lint_with_corpus(spec, _books(base))

    (stale,) = [f for f in findings if f.rule == "undefined-avp-defined"]
    assert stale.severity is linter.Severity.ERROR
    assert (
        stale.message
        == "Mystery is declared undefined, but a base document resolves it"
    )


def _cited_row(name="Mapped", section: str | None = "6.3.1"):
    return ast.AvpTableRow(
        name=name, code=1, data_type=ast.DataType.OCTET_STRING, section=section
    )


def _cited_table(*rows):
    return ast.AvpTable(
        table="6.3/1",
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
        ),
        source=ast.SourceRef(section="6.3"),
        rows=rows,
    )


def _section_findings(*sections):
    return [
        (f.rule, f.message)
        for f in linter.lint(_spec(*sections))
        if f.rule.startswith("section-")
    ]


def _values_at(*rows, kind=ast.ValueKind.BITS, section="6.3.9"):
    return ast.ValueTable(
        avp="Mapped",
        kind=kind,
        source=ast.SourceRef(section=section),
        rows=rows or (ast.ValueRow(name="ONE", value=1),),
    )


_REPRINT = ast.ReprintedAvp(
    name="Mapped",
    source=ast.SourceRef(section="6.3.9"),
    origin="RFC6733",
    code=1,
    avps=(),
)


@pytest.mark.parametrize(
    ("cited", "holder"),
    [
        pytest.param("6.3.9", _grouped("Mapped", 1, section="6.3.9"), id="its clause"),
        pytest.param("6.3", _grouped("Mapped", 1, section="6.3.9"), id="a parent"),
        pytest.param("6", _enumerated("Mapped", 1, section="6.3.9"), id="the top"),
        pytest.param("6.3.9", _REPRINT, id="a re-print"),
        pytest.param("6.3.9", _values_at(), id="a bit table"),
    ],
)
def test_a_row_citing_what_holds_its_avp_reports_nothing(cited, holder):
    assert _section_findings(_cited_table(_cited_row(section=cited)), holder) == []


def test_a_row_citing_another_clause_than_its_block_is_a_note():
    table = _cited_table(_cited_row(section="6.3.1"))
    holder = _grouped("Mapped", 1, section="6.3.9")
    other = _grouped("Other", 2, section="6.3.1")

    assert _section_findings(table, holder, other) == [
        (
            "section-mismatch",
            "Mapped is cited at clause 6.3.1 in table 6.3/1, but the file holds it"
            " at clause 6.3.9",
        )
    ]


def test_a_row_citing_a_clause_the_file_lacks_says_so():
    """TS 29.214 V19.3.0's table 5.3.0.1 and its clause 5.3.81."""
    table = _cited_table(_cited_row(section="6.3.142"))

    assert _section_findings(table, _grouped("Mapped", 1, section="6.3.9")) == [
        (
            "section-mismatch",
            "Mapped is cited at clause 6.3.142 in table 6.3/1, but the file holds it"
            " at clause 6.3.9, and nothing at clause 6.3.142",
        )
    ]


def test_a_row_agreeing_with_any_block_of_its_avp_reports_nothing():
    """TS 29.273 points each interface's row at its own clause's copy."""
    table = _cited_table(_cited_row(section="6.3.9"))
    defined = _grouped("Mapped", 1, section="6.3.1")

    assert _section_findings(table, defined, _REPRINT) == []


def test_a_row_is_not_held_to_a_feature_or_result_code_table():
    """TS 29.229 tabulates `Feature-List` at clause 6.3.31 and prints its
    features in clause 7.1.1, both as they should."""
    table = _cited_table(_cited_row(section="6.3.1"))
    features = _values_at(kind=ast.ValueKind.FEATURES, section="7.1.1")
    codes = _values_at(kind=ast.ValueKind.RESULT_CODES, section="7.1.2")

    assert _section_findings(table, features, codes) == []


def test_a_row_whose_avp_no_block_holds_is_not_checked():
    """A simple-typed AVP has no block, so its clause is absent from any file."""
    assert _section_findings(_cited_table(_cited_row(section="99.1"))) == []


def test_a_row_citing_no_clause_reports_nothing():
    table = _cited_table(_cited_row(section=None))

    assert _section_findings(table, _grouped("Mapped", 1, section="6.3.9")) == []


def test_an_application_scope_naming_a_clause_the_file_lacks_is_a_note():
    scope = _application("Sh", 1, "6.*", "9.*")
    command = _command("6.1.1")

    assert _section_findings(scope, command) == [
        (
            "section-unknown",
            "Sh applies to clause 9.*, under which the file holds no block",
        )
    ]


def _values_cited(source):
    return ast.EnumeratedAvp(
        name="Mapped",
        source=ast.SourceRef(section="6.3.9"),
        code=1,
        vendor_id=10415,
        values_source=source,
        values=(),
    )


def test_values_citing_a_clause_the_file_lacks_are_a_note():
    assert _section_findings(_values_cited("clause 9.9")) == [
        (
            "section-unknown",
            "Mapped's values are cited from clause 9.9, where the file holds no block",
        )
    ]


@pytest.mark.parametrize(
    "source",
    ["clause 6.3", "TS 32.422 [23] for Trace Depth", "Table 6.3.4.2.5-6", None],
)
def test_values_citing_a_held_clause_or_another_document_report_nothing(source):
    assert _section_findings(_values_cited(source)) == []


def test_a_misprinted_clause_can_be_accepted():
    spec = _spec(
        _cited_table(_cited_row(section="6.3.142")),
        _grouped("Mapped", 1, section="6.3.9"),
    )
    acceptance = corrections.Accept(
        id="mapped-clause",
        rule="section-mismatch",
        target=corrections.table_row("Mapped", table="6.3/1"),
        expect="Mapped is cited at clause 6.3.142 in table 6.3/1, but the file holds"
        " it at clause 6.3.9, and nothing at clause 6.3.142",
        reason="a misprint: the document has no clause 6.3.142",
        origin="TS29.329.py",
    )

    findings = linter.lint_with_corpus(spec, _books(spec), [acceptance])

    (accepted,) = [f for f in findings if f.rule == "section-mismatch"]
    assert accepted.severity is linter.Severity.ACCEPTED


def test_the_motivating_misprint_is_reported_raw_and_corrected():
    release = _CORPUS_DIR / "3gpp" / "rel-19"
    message = (
        "PC-Session-Recovery-Status is cited at clause 5.3.142 in table 5.3.0.1, but"
        " the file holds it at clause 5.3.81, and nothing at clause 5.3.142"
    )
    for path in (
        release / "29214-j30.dad",
        _CORPUS_DIR / "raw" / "3gpp" / "rel-19" / "29214-j30.raw.dad",
    ):
        findings = linter.lint(parser.parse(path.read_text(encoding="utf-8")))

        assert [f.message for f in findings if f.rule == "section-mismatch"] == [
            message
        ]


def test_a_declared_name_is_no_unresolved_reference():
    base = _origin_spec("RFC 6733", None, _table(_row("Session-Id", 263)))
    undeclared = _naming_mystery().model_copy(update={"bases": ("RFC6733",)})
    declared = _naming_mystery(_undefined()).model_copy(update={"bases": ("RFC6733",)})

    (unresolved,) = [
        f
        for f in linter.lint_with_corpus(undeclared, _books(base))
        if f.rule == "unresolved-reference"
    ]
    assert unresolved.severity is linter.Severity.ERROR
    assert unresolved.message.startswith(
        "Mystery is referenced in clauses 6.3.1, 6.3.2"
    )
    rules = _rules(linter.lint_with_corpus(declared, _books(base)))
    assert "unresolved-reference" not in rules
    assert "undefined-avp" in rules


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
    # publish; revision 0 V2.0 stands in (corpus.STAND_INS).
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
    # Release 19 copies standing in (corpus.RELEASE_STAND_INS), and its TS
    # 29.212 and 29.214 are the pinned Release 11 copies, whose own Release
    # 11 citations of TS 29.061, 29.229 and 29.272 nothing stands in for:
    # TS 29.212 V11.19.0's Trace-Data, from TS 29.272, differs from Release
    # 18's.
    # TS 29.210 V6.7.0 and TS 29.234 V11.2.0, held for TS 29.230's rows, cite
    # TS 29.229 in their releases; V18.1.0 stands in for both. TS 29.234's
    # clause 10.1.4 prints SIP-Auth-Data-Item's body with three members more and
    # five fewer than TS 29.229's. TS 29.210's TS 29.061 is the pinned V6.15.0,
    # V19.1.0 typing the two AVPs it leaves untyped (corpus.RELEASE_FILLS).
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
    books = corpus.Corpus.load(_corpus(raw=False))
    actual = {}
    accepted = {}
    for entry in books:
        declared = corrections.in_release(
            corrections.load(
                Path(__file__).parent.parent / "edits" / "corrections",
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


def _recorded_books(*holes):
    spec = _origin_spec(
        "3GPP TS 29.900",
        "18.1.0",
        ast.AvpTable(
            source=ast.SourceRef(section="6.3.1"),
            columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE),
            rows=(ast.AvpTableRow(name="Thing", code=1),),
        ),
    )
    return corpus.Corpus(
        [corpus.Entry(path=Path("29900.dad"), spec=spec)],
        corpus.HoleRecord(Path("holes.toml"), holes),
    )


def test_a_hole_the_record_does_not_list_is_an_error():
    (finding,) = linter.lint_record(_recorded_books())

    assert finding.severity is linter.Severity.ERROR
    assert finding.rule == "unrecorded-hole"
    assert finding.message == (
        "TS29.900 Thing: no data_type, no flag_rules, which the record does not list"
    )


def test_a_hole_the_record_lists_otherwise_is_an_error():
    wrong = corpus.KnownHole("TS29.900", "Thing", ("data_type",), "clause 6.3.1")

    (finding,) = linter.lint_record(_recorded_books(wrong))

    assert finding.rule == "unrecorded-hole"
    assert finding.message.endswith("which the record lists missing data_type")


def test_an_entry_naming_no_hole_is_an_error():
    right = corpus.KnownHole(
        "TS29.900", "Thing", ("data_type", "flag_rules"), "clause 6.3.1"
    )
    stale = corpus.KnownHole("TS29.900", "Worked-Off", ("definition",), "clause 6.3.2")

    (finding,) = linter.lint_record(_recorded_books(right, stale))

    assert finding.severity is linter.Severity.ERROR
    assert finding.rule == "stale-hole-record"
    assert finding.message.startswith(
        "TS29.900 Worked-Off is recorded missing definition"
    )


def test_a_corpus_with_no_record_draws_no_record_rule():
    spec = _origin_spec(
        "3GPP TS 29.900",
        "18.1.0",
        ast.AvpTable(
            source=ast.SourceRef(section="6.3.1"),
            columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE),
            rows=(ast.AvpTableRow(name="Thing", code=1),),
        ),
    )
    books = corpus.Corpus([corpus.Entry(path=Path("29900.dad"), spec=spec)])

    assert linter.lint_record(books) == []


def _registry_spec(*sections):
    return _origin_spec("3GPP TS 29.230", "18.6.0", *sections)


def _registry(kind, columns, *rows, table="7.1"):
    return ast.Registry(
        registry=kind,
        table=table,
        source=ast.SourceRef(section=table.partition("/")[0]),
        columns=columns,
        rows=rows,
    )


def _registered_command(name, abbreviation, code, application_id=None, section="6.1.1"):
    return ast.Message(
        name=name,
        abbreviation=abbreviation,
        source=ast.SourceRef(section=section),
        command_code=code,
        flags=frozenset({ast.CommandFlag.REQUEST}),
        application_id=application_id,
        avps=(),
    )


def _registry_findings(spec, registry):
    return [
        (f.rule, f.message.split()[0])
        for f in linter.lint_with_corpus(spec, _books(spec, registry))
        if f.rule.startswith("registry")
    ]


def test_a_command_agrees_with_its_registry_row_by_either_name_or_abbreviation():
    registry = _registry_spec(
        _registry(
            ast.RegistryKind.COMMAND_CODES,
            (
                ast.RegistryColumn.CODE,
                ast.RegistryColumn.NAME,
                ast.RegistryColumn.ABBREVIATION,
                ast.RegistryColumn.DEFINED_IN,
            ),
            ast.RegistryRow(
                code=300,
                name="User-Authorization-Request/-Answer",
                abbreviation="UAR/UAA",
                defined_in=("TS29.229",),
            ),
            ast.RegistryRow(
                code=8388656,
                name="Trigger-Establishment-Request/Answer",
                abbreviation="TER/TEA",
                defined_in=("TS29.338",),
            ),
            table="5.1/1",
        )
    )
    spec = _origin_spec(
        "3GPP TS 29.273",
        "18.6.0",
        # Another document re-using the code under its name is no finding.
        _registered_command("User-Authorization-Answer", "XXA", 300),
        _registered_command("TE-Request", "TER", 8388656),
        _registered_command("Other-Request", "OTR", 8388656),
    )

    assert _registry_findings(spec, registry) == [
        ("registry-command-name", "Other-Request")
    ]


def test_an_application_id_is_compared_by_document_and_scope_name():
    registry = _registry_spec(
        _registry(
            ast.RegistryKind.APPLICATION_IDS,
            (
                ast.RegistryColumn.CODE,
                ast.RegistryColumn.NAME,
                ast.RegistryColumn.DEFINED_IN,
            ),
            ast.RegistryRow(code=16777238, name="3GPP Gx", defined_in=("TS29.212",)),
            ast.RegistryRow(code=16777251, name="3GPP S6a", defined_in=("TS29.272",)),
            table="4.1",
        )
    )
    scope = ast.ApplicationScope(
        name="Gx",
        source=ast.SourceRef(section="5.1"),
        application_id=16777238,
        applies_to=("5.*",),
    )
    spec = _origin_spec(
        "3GPP TS 29.212",
        "18.2.0",
        scope,
        _registered_command("X-Request", "XR", 1, 16777251),
    )

    assert _registry_findings(spec, registry) == [
        ("registry-application-document", "Application")
    ]


def test_a_reserved_code_is_reported_only_outside_its_own_documents_ranges():
    registry = _registry_spec(
        _registry(
            ast.RegistryKind.AVP_CODES,
            (ast.RegistryColumn.CODE, ast.RegistryColumn.NAME),
            ast.RegistryReservation(
                first=1,
                last=255,
                defined_in=("TS29.061",),
                purpose="backwards compatibility (See TS 29.329)",
            ),
            ast.RegistryReservation(first=300, last=399, purpose="future use"),
            ast.RegistryRow(code=700, name="User-Identity"),
        )
    )
    spec = _origin_spec(
        "3GPP TS 29.329",
        "18.0.0",
        _grouped_with("Named-In-Purpose", 5),
        _grouped_with("Future", 300),
        _grouped_with("User-Id", 700),
        _grouped_with("Unallocated", 900),
    )

    assert _registry_findings(spec, registry) == [
        ("registry-avp-name", "User-Id"),
        ("registry-reserved-code", "Future"),
    ]
    assert _registry_findings(spec, _origin_spec("3GPP TS 29.231", "18.0.0")) == []


def test_every_scope_naming_an_application_id_is_compared_with_the_registry():
    registry = _registry_spec(
        _registry(
            ast.RegistryKind.APPLICATION_IDS,
            (ast.RegistryColumn.CODE, ast.RegistryColumn.NAME),
            ast.RegistryRow(code=16777238, name="3GPP Gx"),
            table="4.1",
        )
    )
    scopes = [
        ast.ApplicationScope(
            name=name,
            source=ast.SourceRef(section=clause),
            application_id=16777238,
            applies_to=(f"{clause}.*",),
        )
        for name, clause in (("Gx", "5"), ("Wrong", "6"), ("Wrong", "7"))
    ]
    spec = _origin_spec("3GPP TS 29.212", "18.2.0", *scopes)

    assert [
        (f.rule, f.message.split()[0], f.section)
        for f in linter.lint_with_corpus(spec, _books(spec, registry))
        if f.rule.startswith("registry")
    ] == [("registry-application-name", "Wrong", "6")]


def _value_spec(*tables, sections=()):
    return ast.Specification(
        specification="3GPP TS 29.999",
        version="18.0.0",
        vendor_id=10415,
        sections=(*sections, *tables),
    )


def _bits(*rows, avp="Some-Flags", kind=ast.ValueKind.BITS):
    return ast.ValueTable(
        avp=avp,
        kind=kind,
        source=ast.SourceRef(section="6.3.1"),
        rows=tuple(ast.ValueRow(name=name, value=value) for name, value in rows),
    )


def test_a_number_twice_in_one_value_table_is_an_error():
    spec = _value_spec(_bits(("A", 0), ("B", 0), ("C", 1)), _bits(("A", 1)))

    (finding,) = [f for f in linter.lint(spec) if f.rule == "duplicate-value"]

    assert finding.severity is linter.Severity.ERROR
    assert finding.message == "Some-Flags's bits table gives 0 to 'A', 'B', 2 rows"
    assert finding.paths == (
        ("sections", 0, "rows", 0),
        ("sections", 0, "rows", 1),
    )


def test_a_bit_past_its_type_is_an_error():
    table = ast.AvpTable(
        source=ast.SourceRef(section="6.3"),
        columns=(ast.AvpColumn.NAME, ast.AvpColumn.TYPE),
        rows=(ast.AvpTableRow(name="Wide-Flags", data_type=ast.DataType.UNSIGNED64),),
    )
    spec = _value_spec(
        _bits(("A", 31), ("B", 32)),
        _bits(("A", 63), ("B", 64), avp="Wide-Flags"),
        _bits(("A", 40), avp="Feature-List", kind=ast.ValueKind.FEATURES),
        sections=(table,),
    )

    found = [f for f in linter.lint(spec) if f.rule == "value-bit-out-of-range"]

    assert [f.message for f in found] == [
        "Some-Flags's bits table numbers 'B' bit 32, past the 31 a Unsigned32 holds",
        "Wide-Flags's bits table numbers 'B' bit 64, past the 63 a Unsigned64 holds",
        "Feature-List's features table numbers 'A' bit 40, past the 31 a Unsigned32"
        " holds",
    ]
    assert all(f.severity is linter.Severity.ERROR for f in found)


def _result_registry():
    return ast.Specification(
        specification="3GPP TS 29.230",
        version="18.0.0",
        vendor_id=10415,
        sections=(
            ast.Registry(
                registry=ast.RegistryKind.RESULT_CODES,
                table="8.1.4",
                source=ast.SourceRef(section="8.1.4"),
                columns=(
                    ast.RegistryColumn.CODE,
                    ast.RegistryColumn.NAME,
                    ast.RegistryColumn.DEFINED_IN,
                ),
                rows=(
                    ast.RegistryRow(
                        code=5001,
                        name="DIAMETER_ERROR_USER_UNKNOWN",
                        defined_in=("TS29.229",),
                    ),
                    ast.RegistryRow(
                        code=5002, name="DIAMETER_MINE", defined_in=("TS29.999",)
                    ),
                ),
            ),
        ),
    )


def _result_codes(avp="Experimental-Result-Code"):
    return _bits(
        ("DIAMETER_ERROR_USER_UNKNOWN", 5001),
        ("DIAMETER_MISSPELT", 5002),
        ("DIAMETER_UNALLOCATED", 5003),
        avp=avp,
        kind=ast.ValueKind.RESULT_CODES,
    )


def test_an_experimental_result_code_is_compared_with_the_result_registry():
    spec = _value_spec(_result_codes())
    findings = linter.lint_with_corpus(spec, _books(spec, _result_registry()))

    (other,) = [f for f in findings if f.rule == "registry-result-code-document"]
    assert other.severity is linter.Severity.NOTE
    assert other.message == (
        "DIAMETER_ERROR_USER_UNKNOWN (code 5001) is listed here, but TS29.230 table"
        " 8.1.4 allocates the code to TS29.229"
    )
    assert other.paths == (("sections", 0, "rows", 0),)
    (name,) = [f for f in findings if f.rule == "registry-result-code-name"]
    assert name.message == (
        "DIAMETER_MISSPELT has code 5002, which TS29.230 table 8.1.4 allocates to"
        " DIAMETER_MINE"
    )


def test_a_plain_result_code_is_not_the_registry_s():
    spec = _value_spec(_result_codes("Result-Code"))

    assert not [
        f
        for f in linter.lint_with_corpus(spec, _books(spec, _result_registry()))
        if f.rule.startswith("registry-result-code")
    ]


def _cited_codes(*rows):
    return ast.ValueTable(
        avp="Experimental-Result-Code",
        kind=ast.ValueKind.RESULT_CODES,
        source=ast.SourceRef(section="6.2"),
        rows=tuple(
            ast.ValueRow(name=name, value=value, origin=origin)
            for name, value, origin in rows
        ),
    )


def test_a_code_cited_from_its_document_claims_no_allocation():
    spec = _value_spec(
        _cited_codes(
            ("DIAMETER_ERROR_USER_UNKNOWN", 5001, "TS29.229"),
            ("DIAMETER_MISSPELT", 5002, None),
        )
    )
    origin = _origin_spec(
        "3GPP TS 29.229",
        "18.0.0",
        _cited_codes(("DIAMETER_ERROR_USER_UNKNOWN", 5001, None)),
    )

    findings = linter.lint_with_corpus(spec, _books(spec, origin, _result_registry()))

    assert not [f for f in findings if f.rule == "registry-result-code-document"]
    assert not [f for f in findings if f.rule.startswith("result-code-")]
    assert [f.rule for f in findings if f.rule.startswith("registry-")] == [
        "registry-result-code-name"
    ]


def test_a_cited_code_is_held_to_its_origin():
    spec = _value_spec(
        _cited_codes(
            ("DIAMETER_ERROR_USER_UNKNOWN", 5001, "TS29.229"),
            ("DIAMETER_ERROR_RENAMED", 5002, "TS29.229"),
            ("DIAMETER_ERROR_ABSENT", 5003, "TS29.229"),
            ("DIAMETER_ERROR_PASSED_ON", 5004, "TS29.229"),
        )
    )
    origin = _origin_spec(
        "3GPP TS 29.229",
        "18.0.0",
        _cited_codes(
            ("DIAMETER_ERROR_USER_UNKNOWN", 5001, None),
            ("DIAMETER_ERROR_THEIRS", 5002, None),
            ("DIAMETER_ERROR_PASSED_ON", 5004, "TS29.329"),
        ),
    )

    findings = {
        f.rule: f
        for f in linter.lint_with_corpus(spec, _books(spec, origin))
        if f.rule.startswith("result-code-")
    }

    assert findings["result-code-not-in-origin"].severity is linter.Severity.ERROR
    assert findings["result-code-not-in-origin"].message == (
        "DIAMETER_ERROR_ABSENT (code 5003) is cited from TS29.229, but 3GPP TS"
        " 29.229 18.0.0 lists no Experimental-Result-Code 5003"
    )
    assert findings["result-code-origin-name"].severity is linter.Severity.NOTE
    assert findings["result-code-origin-name"].message == (
        "DIAMETER_ERROR_RENAMED (code 5002) is cited from TS29.229, which names it"
        " DIAMETER_ERROR_THEIRS"
    )
    assert findings["result-code-origin-name"].paths == (("sections", 0, "rows", 1),)
    assert findings["result-code-origin-indirect"].message == (
        "DIAMETER_ERROR_PASSED_ON (code 5004) is cited from TS29.229, which re-uses"
        " it from TS29.329 rather than defining it"
    )
    assert len(findings) == 3


def test_a_cited_code_s_origin_missing_from_the_corpus_is_named():
    spec = _value_spec(_cited_codes(("DIAMETER_ERROR_USER_UNKNOWN", 5001, "TS29.229")))

    (missing,) = [
        f
        for f in linter.lint_with_corpus(spec, _books(spec))
        if f.rule == "origin-not-in-corpus"
    ]
    assert missing.message.endswith(": TS29.229")


def test_a_clause_citing_a_code_s_document_can_accept_the_note():
    spec = _value_spec(_result_codes())
    message = (
        "DIAMETER_ERROR_USER_UNKNOWN (code 5001) is listed here, but TS29.230 table"
        " 8.1.4 allocates the code to TS29.229"
    )
    acceptance = corrections.Accept(
        id="user-unknown",
        rule="registry-result-code-document",
        target=corrections.value_row(
            "Experimental-Result-Code", "DIAMETER_ERROR_USER_UNKNOWN"
        ),
        expect=message,
        reason="clause 6.3.3.1 says it is defined in TS 29.229",
    )

    findings = linter.lint_with_corpus(
        spec, _books(spec, _result_registry()), [acceptance]
    )

    (accepted,) = [f for f in findings if f.rule == "registry-result-code-document"]
    assert accepted.severity is linter.Severity.ACCEPTED
