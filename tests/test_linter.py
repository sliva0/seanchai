"""Corpus pins and synthetic cases for rules the committed files do not cover."""

from pathlib import Path

import pytest
from conftest import _corpus

from seanchai import corpus, linter
from seanchai.dad import ast, parser


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
    "29273-i60.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "duplicate-identity",
        "table-definition-mismatch",
    ],
    "29172-i10.raw.dad": ["duplicate-identity"],
    "29272-i70.raw.dad": [
        "duplicate-identity",
        "table-definition-mismatch",
        "vendor-id-mismatch",
    ],
    "29344-i10.raw.dad": ["one-name-two-commands", "one-name-two-commands"],
    "29388-i10.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "table-definition-mismatch",
    ],
    "29212-i20.raw.dad": ["vendor-id-mismatch"] * 39,
    "29214-i40.raw.dad": ["duplicate-enum-value"] + ["vendor-id-mismatch"] * 11,
    "29336-i20.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "duplicate-identity",
    ],
    "29338-i20.raw.dad": ["duplicate-identity"],
    # Grouped headers printing no vendor while the AVP tables set V (all
    # seven; 29.154's sixth, Time-window, misspells its own rule name, so no
    # row matches it); 29.468's clauses 6.4.28 and 6.4.31 print FEC-Request's
    # code, and table 6.4.1-1 types clause 6.4.35's Enumerated AVP
    # Unsigned32.
    "29154-i00.raw.dad": ["vendor-id-mismatch"] * 5,
    "29215-i00.raw.dad": ["vendor-id-mismatch"] * 2,
    "29217-i00.raw.dad": ["vendor-id-mismatch"] * 4,
    "29219-i00.raw.dad": ["vendor-id-mismatch"] * 2,
    "29343-i00.raw.dad": ["vendor-id-mismatch"] * 3,
    "29368-i00.raw.dad": ["vendor-id-mismatch"] * 3,
    "29468-i00.raw.dad": ["duplicate-identity"]
    + ["table-definition-mismatch"] * 3
    + ["vendor-id-mismatch"] * 12,
    # Both tabulate RFC 8583's Load among their own AVPs, with no code —
    # their Load clauses define it only by reference to RFC 8583.
    "29229-i10.raw.dad": ["row-without-code"],
    "29329-i00.raw.dad": ["row-without-code"],
    "29345-i00.raw.dad": [
        "duplicate-identity",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
    ],
    "rfc4004.raw.dad": ["table-definition-mismatch"],
    # Clause 6.1 lists Service-Type's Callback Login (3) and Callback Framed
    # (4), then repeats both among the values it qualifies.
    "rfc4005.raw.dad": ["duplicate-enum-value"] * 4,
    # The wildcard row of table 7.1.0.1; two Integer32 rows clauses 7.2.111AaA
    # and 7.2.111AaB define as Enumerated; and every grouped header in clause
    # 7.2 printing no vendor while table 7.2.0.1 sets V.
    "32299-i00.raw.dad": ["row-without-code"]
    + ["table-definition-mismatch"] * 2
    + ["vendor-id-mismatch"] * 96,
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
        "29061-i10": 7,
        "29128-i00": 3,
        "29272-i70": 9,
        "29273-i60": 5,
        "29283-i00": 1,
        "29336-i20": 5,
        "29337-i00": 2,
        "29338-i20": 2,
        "29388-i10": 1,
        # TS 29.230's registry: 318 allocated twice, four reservations
        # covering allocated codes, and 4703-4799 inside 4605-4799.
        "29230-i60": 6,
        # Table 7.1.0.1 marks ACA's Error-Message and Failed-AVP unused; the
        # corrections cite RFC origins for it, whose clauses 7.1.9, 7.1.14,
        # 7.1.17 and B.2.4 print bodies of their own.
        "32299-i00.raw": 2,
        "32299-i00": 6,
    }
    stem = path.name.removesuffix(".dad")

    assert len(notes) == expected.get(stem, expected.get(stem.removesuffix(".raw"), 0))
    assert {f.rule for f in notes} <= {
        "local-and-reused",
        "member-marked-unused",
        "registry-range-overlap",
        "table-row-mismatch",
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
    assert found["reused-row-mismatch"].message.endswith("reads Grouped")


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

    assert unresolved.severity is linter.Severity.NOTE
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


# Standing findings from docs/linter.md, plus the additional reprints,
# body differences and indirect origins present in the committed corpus.
_STANDING_CORPUS_NOTES = {
    "29061-i10.dad": {
        "registry-avp-name": ["MBMS-Session-Repetition-Number"],
        "table-row-mismatch": [
            "3GPP-IMSI",
            "3GPP-SGSN-Address",
            "3GPP-SGSN-IPv6-Address",
            "3GPP-IMEISV",
            "3GPP-RAT-Type",
            "3GPP-User-Location-Info",
            "3GPP-MS-TimeZone",
        ],
    },
    "29109-i10.dad": {"registry-avp-name": ["NAF-Id"]},
    "29128-i00.dad": {
        "reused-body-differs": [
            "Monitoring-Event-Configuration",
            "Monitoring-Event-Report",
            "Terminal-Information",
        ],
    },
    "29172-i10.dad": {
        "reused-origin-indirect": ["Service-Selection"],
    },
    "29212-i20.dad": {
        "origin-not-in-corpus": ["TS283.034, X.S0057"],
    },
    "29154-i00.dad": {
        "unresolved-reference": ["External-Group-Identifier"],
    },
    "29214-i40.dad": {
        "origin-not-in-corpus": ["TS183.017"],
        "registry-avp-name": ["Media-Sub-Component"],
    },
    "29219-i00.dad": {
        "origin-not-in-corpus": ["TS283.034"],
    },
    "29229-i10.dad": {
        "unresolved-reference": ["Line-Identifier"],
    },
    "29230-i60.dad": {
        "registry-range-overlap": [
            "318",
            "1..255",
            "4605..4799",
            "4605..4799",
            "4182..4200",
            "5455..5469",
        ],
    },
    "29272-i70.dad": {
        "registry-application-name": ["S7a/S7d"],
        "registry-avp-name": [
            "Event-Threshold-RSRP",
            "Event-Threshold-RSRQ",
            "Third-Context-Identifier",
            "Visited-PLMN-Id",
        ],
        "reused-body-differs": [
            "Monitoring-Event-Configuration",
            "Monitoring-Event-Report",
            "ProSe-Subscription-Data",
            "Supported-Services",
            "UE-Reachability-Configuration",
        ],
        "reused-origin-indirect": ["Charged-Party"],
        "reused-reprint": [
            "AESE-Communication-Pattern",
            "Allocation-Retention-Priority",
            "Communication-Pattern-Set",
            "MIP6-Agent-Info",
        ],
    },
    "29273-i60.dad": {
        "origin-not-in-corpus": ["TS283.034"],
        "registry-avp-document": ["3GPP-AAA-Server-Name"],
        "reused-body-differs": ["SIP-Auth-Data-Item"],
        "reused-reprint": ["MIP6-Agent-Info", "Subscription-Id"],
        "table-row-mismatch": ["AN-Trusted", "Mobile-Node-Identifier"],
        "unresolved-reference": ["NSWO-Authorization"],
    },
    "29283-i00.dad": {
        "registry-avp-name": ["Data", "MCVideo-ID"],
        "reused-body-differs": ["User-Identifier"],
    },
    # Clauses 6.3.9-6.3.21 refer to TS 29.229 for nine AVPs table 6.3.1
    # lists among 29.329's own.
    "29329-i00.dad": {
        "registry-avp-document": [
            "Feature-List",
            "Feature-List-ID",
            "Public-Identity",
            "Server-Name",
            "Session-Priority",
            "Supported-Applications",
            "Supported-Features",
            "Wildcarded-IMPU",
            "Wildcarded-Public-Identity",
        ],
    },
    "29330-i10.dad": {"reused-origin-indirect": ["Load"]},
    "29336-i20.dad": {
        "registry-avp-name": [
            "Group-User-Identifier",
            "NIA-Flags",
            "Supported-Monitoring-Events",
            "Supported-Services",
        ],
        "reused-body-differs": [
            "Additional-Serving-Node",
            "MME-Location-Information",
            "SGSN-Location-Information",
            "Serving-Node",
        ],
        "reused-origin-indirect": ["User-CSG-Information"],
        "reused-reprint": ["EPS-Location-Information"],
    },
    "29337-i00.dad": {
        "reused-body-differs": ["Additional-Serving-Node", "Serving-Node"],
    },
    "29338-i20.dad": {
        "registry-avp-name": [
            "MME-Absent-User-Diagnostic-SM",
            "MSC-Absent-User-Diagnostic-SM",
            "SGSN-Absent-User-Diagnostic-SM",
        ],
        "reused-body-differs": ["Additional-Serving-Node", "Serving-Node"],
    },
    "29345-i00.dad": {
        "unresolved-reference": ["ProSe-Query-Code", "ProSe-Response-Code"],
    },
    "29388-i10.dad": {
        "reused-body-differs": ["V2X-Subscription-Data"],
    },
    "32299-i00.dad": {
        # Table 7.1.0.1 marks them "-" under ACA, clause 6.2.3's ABNF lists them.
        "member-marked-unused": ["Error-Message", "Failed-AVP"],
        "origin-not-in-corpus": ["TS283.034, TS29.140"],
        "reused-body-differs": [
            "Multiple-Services-Credit-Control",
            "Used-Service-Unit",
        ],
        "reused-extension": ["OC-OLR"],
        "reused-origin-indirect": [
            "3GPP2-BSID",
            "Priority-Indication",
            "Reference-Number",
        ],
        "registry-avp-name": [
            "Authorised-QoS",
            "Charging-Characteristics-Selection-Mode",
            "Deferred-Location-Event-Type",
            "IP-Realm-Default-Indication",
            "ISUP-Cause",
            "Local-GW-Inserted-Indication",
            "MBMS-GW-Address",
            "Originator-SCCP-Address",
            "PC3-Control-Protocol-Cause",
            "PC3-EPC-Control-Protocol-Cause",
            "PoC-Change-Condition",
            "ProSe-Group-IP-Multicast-Address",
            "RAN-End-Timestamp",
            "RAN-Start-Timestamp",
            "Service-ID",
            "Transcoder-Inserted-Indication",
        ],
        # Table 7.1 reserves 1324-1399 for "TS 32.229", likely TS 32.299.
        "registry-reserved-code": ["Nr-Cgi", "PSCell-Info"],
        "reused-reprint": ["User-Equipment-Info"],
        # Table 7.2.0.1 sets M for the charging application on AVPs it
        # refers to TS 29.229 for, which leaves M out of Must.
        "reused-row-mismatch": [
            "Feature-List",
            "Feature-List-ID",
            "Supported-Features",
        ],
        "unresolved-reference": [
            "M2M-Information",
            "Monitored-HPLMN-Identifier",
            "Monitoring-Event-Report",
            "Network-Element",
            "Submission-Timestamp",
            "TCP-Source-Port",
        ],
    },
    "rfc4004.dad": {
        "unresolved-reference": ["MIP-HA-to-MN-SPI", "MIP-MN-FA-SPI", "MIP-MN-HA-SPI"],
    },
}


def test_the_corrected_corpus_has_only_its_standing_cross_file_notes():
    books = corpus.Corpus.load(_corpus(raw=False))
    actual = {}
    for entry in books:
        notes = {}
        for finding in linter.lint_with_corpus(entry.spec, books):
            assert finding.severity is linter.Severity.NOTE, (entry.path, finding)
            # Missing origins are grouped in one finding per file; all other
            # standing notes start with the affected AVP's name.
            subject = (
                finding.message.rpartition(": ")[2]
                if finding.rule == "origin-not-in-corpus"
                else finding.message.split()[0].removesuffix("'s")
            )
            notes.setdefault(finding.rule, []).append(subject)
        if notes:
            actual[entry.path.name] = notes
    assert actual == _STANDING_CORPUS_NOTES


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
