"""Rules over one parsed `.dad` file.

Each rule is exercised twice: against a hand-built specification that isolates
it, and — where the corpus has a real case — against the committed file that
motivated the rule in the first place.
"""

from pathlib import Path

import pytest

from seanchai import linter
from seanchai.dad import ast, parser

_ROOT = Path(__file__).parent.parent
_CORPUS = _ROOT / "dad"


def _spec(*sections, specification="3GPP TS 29.329", vendor_id=10415):
    return ast.Specification(
        specification=specification,
        version="1.0.0",
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


def test_a_clean_specification_reports_nothing():
    spec = _spec(_grouped("Example", 700), _table(_row("Example", 700)))

    assert linter.lint(spec) == []


def test_two_definitions_of_one_name():
    spec = _spec(
        _grouped("Example", 700, section="6.3.1"),
        _grouped("Example", 701, section="6.3.9"),
    )

    (finding,) = [f for f in linter.lint(spec) if f.rule == "duplicate-definition"]

    assert finding.severity is linter.Severity.ERROR
    assert "6.3.1, 6.3.9" in finding.message


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


def test_two_avps_sharing_one_identity():
    """Not the same rule as duplicate names: TS 29.272 printed `Area-Scope`
    with `Job-Type`'s code, so both names stayed unique."""
    spec = _spec(_grouped("First", 700), _grouped("Second", 700))

    (finding,) = [f for f in linter.lint(spec) if f.rule == "duplicate-identity"]

    assert "vendor 10415, code 700" in finding.message
    assert "First" in finding.message and "Second" in finding.message


def test_one_code_in_two_vendor_spaces_is_not_a_collision():
    """TS 29.229 gives 621 to Primary-Charging-Collection-Function-Name and
    also carries RFC 7683's OC-Supported-Features, which is 621 in the IETF
    space. AVP tables have no vendor column, so a check that assumed one space
    would call these a collision."""
    spec = _spec(
        _table(_row("Local-AVP", 621), _row("OC-Supported-Features", 621)),
        _reused(ast.ReusedAvpRow(name="OC-Supported-Features", origin="RFC7683")),
    )

    assert "duplicate-identity" not in _rules(linter.lint(spec))


def test_re_used_rows_are_left_to_the_cross_document_rules():
    """A re-used AVP's vendor is the origin document's `; Vendor-ID:` to state,
    and this file cannot read it. Two re-used rows sharing a code may or may
    not collide depending on where each comes from, so a single-file rule
    declines rather than guesses."""
    spec = _spec(
        _table(_row("One", 621), _row("Two", 621)),
        _reused(
            ast.ReusedAvpRow(name="One", origin="RFC7683"),
            ast.ReusedAvpRow(name="Two", origin="TS29.212"),
        ),
    )

    assert "duplicate-identity" not in _rules(linter.lint(spec))


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


def test_a_definition_and_its_own_table_row_are_one_avp():
    spec = _spec(_grouped("Example", 700), _table(_row("Example", 700)))

    assert "duplicate-identity" not in _rules(linter.lint(spec))


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_row("Example", 701), "the AVP table says code 701"),
        (
            _row("Example", 700, ast.DataType.UNSIGNED32),
            "the AVP table says type Unsigned32",
        ),
    ],
    ids=["code", "type"],
)
def test_a_table_row_disagreeing_with_its_definition(row, expected):
    spec = _spec(_grouped("Example", 700), _table(row))

    (finding,) = [f for f in linter.lint(spec) if f.rule == "table-definition-mismatch"]

    assert expected in finding.message
    assert finding.severity is linter.Severity.ERROR


def test_a_row_with_no_local_definition_is_not_compared():
    """Most rows have no clause in this file — the AVP is defined elsewhere,
    and comparing against nothing would report every one of them."""
    spec = _spec(_table(_row("Elsewhere", 700, ast.DataType.OCTET_STRING)))

    assert linter.lint(spec) == []


def test_local_and_reused_is_a_note_because_one_file_cannot_judge_it():
    """A specification may re-print another's AVP so a reader need not fetch
    the other document, or extend it with fields of its own. TS 29.272 does
    this nine times."""
    spec = _spec(
        _grouped("Borrowed", 700),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="TS29.212")),
    )

    (finding,) = [f for f in linter.lint(spec) if f.rule == "local-and-reused"]

    assert finding.severity is linter.Severity.NOTE
    assert "needs TS29.212" in finding.message


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


def _corpus(*, raw: bool):
    """Committed files of one kind. `rglob("*.dad")` matches `.raw.dad` too,
    so the two are told apart by suffix rather than by glob."""
    paths = [
        path
        for path in sorted(_CORPUS.rglob("*.dad"))
        if path.name.endswith(".raw.dad") == raw
    ]
    assert paths, "no committed .dad files found — these tests would pass vacuously"
    return paths


@pytest.mark.parametrize("path", _corpus(raw=False), ids=lambda path: path.name)
def test_the_corrected_corpus_has_no_errors(path):
    """Correcting a file is what clears its errors, so the corrected corpus is
    the one that must come out clean. An error here means either a correction
    is missing or a rule started firing on something new."""
    findings = linter.lint(parser.parse(path.read_text(encoding="utf-8")))

    assert [f for f in findings if f.severity is linter.Severity.ERROR] == []


@pytest.mark.parametrize("path", _corpus(raw=True), ids=lambda path: path.name)
def test_the_raw_corpus_reports_exactly_what_the_documents_say(path):
    """Raw files legitimately carry the documents' own mistakes, and pinning
    them is what proves the rules fire at all — the corrected corpus being
    clean would otherwise be indistinguishable from rules that never match."""
    findings = linter.lint(parser.parse(path.read_text(encoding="utf-8")))
    errors = [f for f in findings if f.severity is linter.Severity.ERROR]

    if path.name == "29272-i60.raw.dad":
        assert _rules(errors) == ["duplicate-identity", "table-definition-mismatch"]
        assert all("Area-Scope" in f.message for f in errors)
    else:
        assert errors == []


@pytest.mark.parametrize(
    "path", _corpus(raw=True) + _corpus(raw=False), ids=lambda path: path.name
)
def test_the_committed_corpus_reports_only_its_known_notes(path):
    """Pins what the corpus says today, so a rule that starts firing on
    something else shows up as a test failure rather than as noise. Notes are
    unaffected by correcting a file, so both kinds carry the same ones."""
    notes = [
        f
        for f in linter.lint(parser.parse(path.read_text(encoding="utf-8")))
        if f.severity is linter.Severity.NOTE
    ]

    if path.name.startswith("29272-i60"):
        # The nine AVPs 29.272 both defines and lists as re-used.
        assert len(notes) == 9
        assert {f.rule for f in notes} == {"local-and-reused"}
    else:
        assert notes == []
