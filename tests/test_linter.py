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
    "29388-i10.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "table-definition-mismatch",
    ],
    "29212-i20.raw.dad": ["vendor-id-mismatch"] * 8,
    "29214-i40.raw.dad": ["duplicate-enum-value"] + ["vendor-id-mismatch"] * 10,
    "29336-i20.raw.dad": [
        "duplicate-definition",
        "duplicate-identity",
        "duplicate-identity",
    ],
    "29338-i20.raw.dad": ["duplicate-identity"],
    # Both tabulate RFC 8583's Load among their own AVPs, with no code —
    # their Load clauses define it only by reference to RFC 8583.
    "29229-i10.raw.dad": ["row-without-code"],
    "29329-i00.raw.dad": ["row-without-code"],
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
    "rfc4004.raw.dad": ["table-definition-mismatch"],
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
    usually survive correction unchanged, so most specs carry one count for
    both kinds; 29.336 and 29.338 differ because their corrections delete a
    duplicated definition (removing its note) and align a misprinted name
    with its re-used row (adding one)."""
    notes = [
        f
        for f in linter.lint(parser.parse(path.read_text(encoding="utf-8")))
        if f.severity is linter.Severity.NOTE
    ]

    # AVPs each document both defines and lists as re-used.
    expected = {
        "29128-i00": 3,
        "29212-i20": 9,
        "29272-i60": 9,
        "29283-i00": 1,
        "29336-i20.raw": 7,
        "29336-i20": 6,
        "29337-i00": 2,
        "29338-i20.raw": 3,
        "29338-i20": 4,
        "29388-i10": 1,
    }
    stem = path.name.removesuffix(".dad")

    assert len(notes) == expected.get(stem, expected.get(stem.removesuffix(".raw"), 0))
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


# Standing findings from docs/linter.md, plus the additional reprints,
# body differences and indirect origins present in the committed corpus.
_STANDING_CORPUS_NOTES = {
    "29061-i10.dad": {
        "origin-not-in-corpus": ["TS29.468"],
    },
    "29128-i00.dad": {
        "origin-not-in-corpus": ["TS32.299"],
        "reused-body-differs": [
            "Monitoring-Event-Configuration",
            "Monitoring-Event-Report",
            "Terminal-Information",
        ],
    },
    "29172-i10.dad": {
        "origin-not-in-corpus": ["TS32.299"],
        "reused-origin-indirect": ["Service-Selection"],
    },
    "29173-i00.dad": {
        "origin-not-in-corpus": ["TS29.273"],
    },
    "29212-i20.dad": {
        "origin-not-in-corpus": ["TS283.034, TS29.273, TS32.299, X.S0057"],
        "reused-reprint": [
            "ADC-Rule-Definition",
            "ADC-Rule-Install",
            "ADC-Rule-Remove",
            "ADC-Rule-Report",
            "Application-Detection-Information",
            "Default-EPS-Bearer-QoS",
            "Packet-Filter-Information",
            "Redirect-Information",
            "Usage-Monitoring-Information",
        ],
    },
    "29214-i40.dad": {
        "origin-not-in-corpus": ["TS183.017, TS29.154, TS29.273, TS32.299"],
    },
    "29272-i60.dad": {
        "origin-not-in-corpus": ["TS29.217, TS29.273, TS32.299"],
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
            "Communication-Pattern-Set",
            "MIP6-Agent-Info",
        ],
    },
    "29283-i00.dad": {
        "reused-body-differs": ["User-Identifier"],
    },
    "29336-i20.dad": {
        "origin-not-in-corpus": ["TS29.154, TS29.217, TS29.368, TS32.299"],
        "reused-body-differs": [
            "Additional-Serving-Node",
            "MME-Location-Information",
            "SGSN-Location-Information",
            "Serving-Node",
        ],
        "reused-origin-indirect": ["User-CSG-Information"],
        "reused-reprint": ["EPS-Location-Information", "User-Identifier"],
    },
    "29337-i00.dad": {
        "origin-not-in-corpus": ["TS29.368"],
        "reused-body-differs": ["Additional-Serving-Node", "Serving-Node"],
    },
    "29338-i20.dad": {
        "origin-not-in-corpus": ["TS23.329"],
        "reused-body-differs": ["Additional-Serving-Node", "Serving-Node"],
        "reused-reprint": ["SM-Delivery-Failure-Cause", "SMSMI-Correlation-ID"],
    },
    "29345-i00.dad": {
        "origin-not-in-corpus": ["TS29.273, TS32.299"],
        "unresolved-reference": ["ProSe-Query-Code", "ProSe-Response-Code"],
    },
    "29388-i10.dad": {
        "reused-body-differs": ["V2X-Subscription-Data"],
    },
    "29389-i00.dad": {
        "origin-not-in-corpus": ["TS32.299"],
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
