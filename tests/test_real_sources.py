"""Regression pin of the whole pipeline against the real source documents.

`seanchai regenerate` is run over the downloaded corpus into a scratch
directory, and every committed pair must come out unchanged. This is the test
that catches an extractor or correction change which is fine on the synthetic
fixture and wrong on the real documents, and it uses the same code path a
maintainer runs, so the test and the tool cannot drift apart.

A missing manifest is a failure, not a skip: a suite that silently skipped its
strongest check would look green for the wrong reason. Run
`pytest -m "not sources"` to leave these out deliberately.
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
    )
    return {outcome.reference: outcome for outcome in report.outcomes}


@pytest.mark.sources
@pytest.mark.parametrize("reference", _REFERENCES)
def test_the_real_sources_still_produce_the_committed_output(regenerated, reference):
    outcome = regenerated[reference]
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
