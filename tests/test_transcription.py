"""Hand transcriptions: the input patches stand between them and the raw
files, as they stand between a 3GPP document and its extraction.

The transcriptions are committed, so unlike the downloaded documents they
are rebuilt here without the `sources` marker."""

import json

import pytest
from conftest import _CORPUS_DIR, _ROOT

from seanchai import _regenerate
from seanchai.dad import parser
from seanchai.downloader import load_catalog
from seanchai.extractor import transcription
from seanchai.extractor.sources import PatchError

_EDITS = _ROOT / "edits"
_TRANSCRIPTIONS = sorted((_EDITS / "transcriptions").glob("*.dad"))


def test_every_transcription_rebuilds_the_committed_pair(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"artifacts": []}))

    report = _regenerate.regenerate(
        manifest,
        _CORPUS_DIR,
        tmp_path / "dad",
        sources_dir=_EDITS / "sources",
        corrections_dir=_EDITS / "corrections",
        transcriptions_dir=_EDITS / "transcriptions",
        only=[path.stem for path in _TRANSCRIPTIONS],
    )

    assert _TRANSCRIPTIONS
    assert {
        outcome.reference: (outcome.status, outcome.error)
        for outcome in report.outcomes
    } == {path.stem: ("unchanged", None) for path in _TRANSCRIPTIONS}


def test_the_catalog_fetches_what_each_transcription_was_copied_from():
    """`seanchai corpus download` reads the catalog's URL and the export looks the
    file up by the name in the transcription's header, so the two are one."""
    catalog = {document.reference: document for document in load_catalog().transcribed}

    assert sorted(catalog) == [path.stem for path in _TRANSCRIPTIONS]
    for path in _TRANSCRIPTIONS:
        spec = parser.parse(transcription.patched(path, _EDITS / "sources"))
        assert str(spec.transcribed) == catalog[path.stem].url


def test_a_patch_that_stops_matching_fails_the_reading(tmp_path):
    text = (_EDITS / "transcriptions" / "ETSI-TS183.017.dad").read_text(
        encoding="utf-8"
    )
    path = tmp_path / "ETSI-TS183.017.dad"
    path.write_text(text.replace("< AVP header: x >", "< AVP header: 510 >"))

    with pytest.raises(PatchError, match="applied 0 times"):
        transcription.read(path, _EDITS / "sources")
