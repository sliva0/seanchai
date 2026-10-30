"""Regression pin of the whole pipeline against the real source documents.

`seanchai regenerate` is run over the downloaded corpus into a scratch
directory, and every committed pair must come out unchanged. This is the test
that catches an extractor or correction change which is fine on the synthetic
fixture and wrong on the real documents, and it uses the same code path a
maintainer runs, so the test and the tool cannot drift apart.

A missing manifest is a failure, not a skip: a suite that silently skipped its
strongest check would look green for the wrong reason. Run
`pytest -m "not sources"` to leave these out deliberately. For the same
reason a committed pair whose legacy `.doc` the manifest holds unconverted
(`seanchai download --no-convert`) fails, rather than pass as skipped.
"""

from pathlib import Path

import pytest
from conftest import _corpus

from seanchai import regenerate
from seanchai.dad import ast, parser

_ROOT = Path(__file__).parent.parent
_MANIFEST = _ROOT / "specifications" / "manifest.json"
_REFERENCES = sorted(
    ast.spec_ref(parser.parse(path.read_text(encoding="utf-8")).specification)
    for path in _corpus(raw=False)
)


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    assert _MANIFEST.is_file(), (
        f"{_MANIFEST} not present — run `seanchai download`"
        ' or deselect with `pytest -m "not sources"`'
    )
    report = regenerate.regenerate(
        _MANIFEST,
        _ROOT / "dad",
        tmp_path_factory.mktemp("dad"),
        sources_dir=_ROOT / "edits" / "sources",
        corrections_dir=_ROOT / "edits" / "corrections",
        transcriptions_dir=_ROOT / "edits" / "transcriptions",
    )
    return {outcome.reference: outcome for outcome in report.outcomes}


_RECONVERT = (
    "the manifest holds the legacy .doc unconverted: run `seanchai download`"
    " with LibreOffice installed, without --no-convert"
)


@pytest.mark.sources
def test_every_committed_legacy_document_was_converted(regenerated):
    unconverted = sorted(
        reference
        for reference, outcome in regenerated.items()
        if outcome.status == "not-converted"
    )
    assert not unconverted, f"{', '.join(unconverted)}: {_RECONVERT}"


@pytest.mark.sources
@pytest.mark.parametrize("reference", _REFERENCES)
def test_the_real_sources_still_produce_the_committed_output(regenerated, reference):
    outcome = regenerated[reference]
    if outcome.status == "not-converted":
        pytest.fail(f"{reference}: {_RECONVERT}")
    assert outcome.error is None, outcome.error
    if outcome.status == "new":
        pytest.fail(
            f"the manifest holds {outcome.version}, the corpus"
            f" {outcome.replaced_version}: run `seanchai regenerate` and commit"
        )
    if outcome.status == "changed":
        diff = " and ".join(
            f"{path.name} differs from {committed}"
            for path in outcome.written
            for committed in _corpus(raw=path.name.endswith(".raw.dad"))
            if committed.name == path.name
            and committed.read_text(encoding="utf-8")
            != path.read_text(encoding="utf-8")
        )
        pytest.fail(f"{diff}: run `seanchai regenerate` and review the diff")
    assert outcome.status == "unchanged"
