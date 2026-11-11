"""The corpus's record of its corrections: in sync with the modules, and all
an export needs of them (docs/corrections.md#the-corrections-record)."""

from pathlib import Path

import pytest
from conftest import _CORPUS_DIR, _ROOT

from seanchai import _correction_record, linter
from seanchai.corpus import Corpus, CorpusError
from seanchai.dad import corrections

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


def test_a_malformed_record_is_refused(tmp_path: Path):
    path = tmp_path / _correction_record.RECORD_NAME
    path.write_text('{"documents": {"x": {"reference": 1}}}', "utf-8")
    with pytest.raises(CorpusError, match=r"corrections\.json"):
        _correction_record.load(path)
    path.write_text("not json", "utf-8")
    with pytest.raises(CorpusError, match=r"corrections\.json"):
        _correction_record.load(path)
    path.write_bytes(b"\xff")
    with pytest.raises(CorpusError, match=r"corrections\.json"):
        _correction_record.load(path)
    path.unlink()
    path.mkdir()
    with pytest.raises(CorpusError, match=r"corrections\.json"):
        _correction_record.load(path)
