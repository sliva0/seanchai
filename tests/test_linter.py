"""Rules over one parsed `.dad` file.

Each rule is exercised twice: against a hand-built specification that isolates
it, and — where the corpus has a real case — against the committed file that
motivated the rule in the first place.
"""

from pathlib import Path

import pytest

from seanchai import corpus, linter
from seanchai.dad import ast, parser

_ROOT = Path(__file__).parent.parent
_CORPUS = _ROOT / "dad"


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


def _message(name, command_code, section, application_id=42):
    return ast.Message(
        name=name,
        abbreviation="EXR",
        source=ast.SourceRef(section=section),
        command_code=command_code,
        flags=frozenset({ast.CommandFlag.REQUEST}),
        application_id=application_id,
        avps=(),
    )


def test_one_command_name_may_not_name_two_command_codes():
    """TS 29.344 clauses 6.2.11/6.2.12 print 6.2.3/6.2.4's rule names above
    command 8388713, so one name appeared to be two commands."""
    spec = _spec(
        _message("Example-Request", 8388664, "6.2.3"),
        _message("Example-Request", 8388713, "6.2.11"),
    )

    (finding,) = [f for f in linter.lint(spec) if f.rule == "one-name-two-commands"]

    assert finding.severity is linter.Severity.ERROR
    assert "8388664 (clause 6.2.3)" in finding.message
    assert "8388713 (clause 6.2.11)" in finding.message


def test_one_command_defined_for_two_applications_is_not_a_duplicate():
    """TS 29.272 defines IDR/DSR/RSR once for S6a and once for S7a: one name,
    one code, two application ids. That is the shape the rule must not flag."""
    spec = _spec(
        _message("Example-Request", 8388638, "5.2.1", application_id=16777251),
        _message("Example-Request", 8388638, "5.2.1", application_id=16777308),
    )

    assert "one-name-two-commands" not in _rules(linter.lint(spec))


def _flagged_table(name, code, must=frozenset({ast.AvpFlag.VENDOR})):
    """An AVP table that has a Must column, which is what makes a missing
    vendor-id contradictable."""
    return ast.AvpTable(
        table="6.3.1",
        columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.MUST),
        source=ast.SourceRef(section="6.3"),
        rows=(
            ast.AvpTableRow(
                name=name, code=code, flag_rules=ast.AvpFlagRules(must=must)
            ),
        ),
    )


def test_a_vendor_less_definition_whose_table_row_requires_v():
    """TS 29.272 clause 7.3.181 defines WLAN-offloadability with a bare
    `< AVP header: 1667 >` while table 7.3.1/1 marks its V flag mandatory."""
    spec = _spec(
        _grouped("Example", 700, vendor_id=None), _flagged_table("Example", 700)
    )

    (finding,) = [f for f in linter.lint(spec) if f.rule == "vendor-id-mismatch"]

    assert finding.severity is linter.Severity.ERROR
    assert finding.section == "6.3.1"
    assert "vendor 10415" in finding.message


def test_a_vendor_less_definition_is_only_suspect_when_the_table_says_so():
    """Nothing else in the file contradicts it, so nothing here can call it
    wrong: a genuinely IETF-space AVP looks exactly like this."""
    spec = _spec(
        _grouped("Example", 700, vendor_id=None),
        _flagged_table("Example", 700, must=frozenset()),
    )

    assert _rules(linter.lint(spec)) == []

    # And an AVP with no table row at all is not compared either.
    assert linter.lint(_spec(_grouped("Example", 700, vendor_id=None))) == []


def test_a_re_used_avp_may_be_vendor_less():
    """MIP6-Agent-Info is RFC 5447's, correctly vendor-less in TS 29.272, and
    listed as re-used — which is what tells it apart from the case above."""
    spec = _spec(
        _grouped("Borrowed", 700, vendor_id=None),
        _flagged_table("Borrowed", 700),
        _reused(ast.ReusedAvpRow(name="Borrowed", origin="RFC5447")),
    )

    assert "vendor-id-mismatch" not in _rules(linter.lint(spec))


def test_a_definition_claiming_another_vendors_space():
    spec = _spec(_grouped("Example", 700, vendor_id=13019))

    (finding,) = [f for f in linter.lint(spec) if f.rule == "vendor-id-mismatch"]

    assert "vendor 13019" in finding.message
    assert "states vendor 10415" in finding.message


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


# What each raw file's own document gets wrong, and therefore what its
# corrections exist to fix. Every entry was confirmed against the source clause
# before it was written down; a file absent from here must lint clean raw.
_RAW_ERRORS = {
    "29172-i10.raw.dad": ["duplicate-identity"],
    "29128-i00.raw.dad": ["duplicate-identity", "duplicate-identity"],
    "29272-i60.raw.dad": [
        "duplicate-identity",
        "table-definition-mismatch",
        "vendor-id-mismatch",
    ],
    "29344-i10.raw.dad": ["one-name-two-commands", "one-name-two-commands"],
    "29388-i00.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "table-definition-mismatch",
    ],
    "29345-i00.raw.dad": [
        "duplicate-identity",
        "duplicate-identity",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
        "table-definition-mismatch",
    ],
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
    something else shows up as a test failure rather than as noise. Notes are
    unaffected by correcting a file, so both kinds carry the same ones."""
    notes = [
        f
        for f in linter.lint(parser.parse(path.read_text(encoding="utf-8")))
        if f.severity is linter.Severity.NOTE
    ]

    # AVPs each document both defines and lists as re-used.
    expected = {
        "29128-i00": 3,
        "29272-i60": 9,
        "29283-i00": 1,
        "29337-i00": 2,
        "29388-i00": 1,
    }
    stem = path.name.removesuffix(".dad").removesuffix(".raw")

    assert len(notes) == expected.get(stem, 0)
    assert {f.rule for f in notes} <= {"local-and-reused"}


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
