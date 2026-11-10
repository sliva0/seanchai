"""The corpus's record of its corrections: in sync with the modules, and all
an export needs of them (docs/corrections.md#the-corrections-record)."""

import json
from pathlib import Path

import pytest
from conftest import _CORPUS_DIR, _ROOT

from seanchai import _correction_record, linter
from seanchai.corpus import Corpus, CorpusError
from seanchai.dad import ast, corrections
from seanchai.dad.corrections import Accept, Correction, definition

_CORRECTIONS = _ROOT / "edits" / "corrections"
_COMMITTED = _CORPUS_DIR / _correction_record.RECORD_NAME


@pytest.fixture(scope="module")
def books():
    return Corpus.installed()


def test_the_committed_record_is_what_the_modules_say(books):
    built = _correction_record.build(books, _CORRECTIONS)
    committed = _COMMITTED.read_text("utf-8")
    assert built.render() == committed, (
        f"{_COMMITTED} is stale: run `seanchai corpus regenerate` and commit it"
    )
    assert _correction_record.load(_COMMITTED) == built


def test_the_record_replays_every_acceptance_as_its_module_does(books):
    record = _correction_record.load(_COMMITTED)
    accepted = 0
    for entry in books:
        declared = corrections.in_release(
            corrections.load(_CORRECTIONS, entry.spec.specification),
            entry.spec.version,
        )
        accepts = corrections.acceptances(declared)
        if not accepts:
            continue
        replayed = record.documents[entry.path.stem].acceptances()
        found = linter.lint_with_corpus(entry.spec, books, replayed)
        assert found == linter.lint_with_corpus(entry.spec, books, accepts)
        accepted += sum(f.severity is linter.Severity.ACCEPTED for f in found)
    assert accepted


def test_a_stale_recorded_acceptance_reads_as_a_stale_acceptance(books):
    entry = next(e for e in books if e.path.stem == "29229-j10")
    stale = _correction_record.RecordedDocument(
        reference="TS29.229",
        version=entry.spec.version,
        edits={
            "TS29.229.py#gone": _correction_record.RecordedAcceptance(
                kind="accept",
                reason="r",
                rule="reused-body-differs",
                expect="what the document no longer says",
                targets=(("sections", 99999),),
            )
        },
        renames=(),
    )
    findings = linter.lint_with_corpus(entry.spec, books, stale.acceptances())
    assert any(
        f.rule == "stale-acceptance" and "TS29.229.py#gone" in f.message
        for f in findings
    )


def test_a_record_holds_kinds_reasons_and_renames_in_declared_order():
    spec = ast.Specification(specification="RFC 9999", vendor_id=0, sections=())
    first = Correction(
        id="one",
        target=definition("A"),
        field="name",
        expect="A",
        replace="B",
        reason="first",
        origin="RFC9999.py",
    )
    second = Correction(
        id="two",
        target=definition("B"),
        field="code",
        expect=1,
        replace=2,
        reason="not a rename",
        origin="RFC9999.py",
    )
    third = Correction(
        id="a-three",
        target=definition("C"),
        field="name",
        expect="C",
        replace="D",
        reason="third",
        origin="RFC9999.py",
    )
    note = Accept(
        id="noted",
        rule="some-rule",
        target=definition("Nothing"),
        expect="the message",
        reason="deliberate",
        origin="RFC9999.py",
    )

    record = _correction_record.RecordedDocument.of(spec, [first, second, third, note])

    assert [(r.expect, r.replace) for r in record.renames] == [("A", "B"), ("C", "D")]
    assert {cited: edit.kind for cited, edit in record.edits.items()} == {
        "RFC9999.py#one": "correction",
        "RFC9999.py#two": "correction",
        "RFC9999.py#a-three": "correction",
        "RFC9999.py#noted": "accept",
    }
    (accept,) = record.acceptances()
    assert accept.cited == "RFC9999.py#noted"
    assert accept.expect == "the message"


def test_a_rendered_record_is_sorted_with_one_field_per_line():
    text = _COMMITTED.read_text("utf-8")
    data = json.loads(text)
    assert list(data) == ["documents", "note"]
    assert list(data["documents"]) == sorted(data["documents"])
    assert text.endswith("}\n")
    assert '"reason": "' in text
    assert not any('", "' in line for line in text.splitlines() if "reason" not in line)


def test_a_malformed_record_is_refused(tmp_path: Path):
    path = tmp_path / _correction_record.RECORD_NAME
    path.write_text('{"documents": {"x": {"reference": 1}}}', "utf-8")
    with pytest.raises(CorpusError, match=r"corrections\.json"):
        _correction_record.load(path)
    path.write_text("not json", "utf-8")
    with pytest.raises(CorpusError, match=r"corrections\.json"):
        _correction_record.load(path)
