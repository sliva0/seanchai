"""Hand transcriptions: the input patches stand between them and the raw
files, as they stand between a 3GPP document and its extraction."""

import pytest
from conftest import _CORPUS_DIR, _ROOT

from seanchai.dad import formatter, parser
from seanchai.downloader import load_catalog
from seanchai.extractor import transcription
from seanchai.extractor.sources import PatchError

_TRANSCRIPTIONS = sorted((_ROOT / "edits" / "transcriptions").glob("*.dad"))
_RAW = {
    "3GPP2-X.S0013-006": _CORPUS_DIR / "raw" / "3gpp2" / "xs0013-006-b_v1.0.raw.dad",
    "3GPP2-X.S0013-013": _CORPUS_DIR / "raw" / "3gpp2" / "xs0013-013-0_v1.0.raw.dad",
    "3GPP2-X.S0013-014": _CORPUS_DIR / "raw" / "3gpp2" / "xs0013-014-0_v1.0.raw.dad",
    "3GPP2-X.S0057": _CORPUS_DIR / "raw" / "3gpp2" / "xs0057-0_v2.0.raw.dad",
    "ETSI-ES283.026": _CORPUS_DIR / "raw" / "etsi" / "es283026-010600.raw.dad",
    "ETSI-ES283.034": _CORPUS_DIR / "raw" / "etsi" / "es283034-020200.raw.dad",
    "ETSI-ES283.035": _CORPUS_DIR / "raw" / "etsi" / "es283035-020501.raw.dad",
    "ETSI-TS183.017": _CORPUS_DIR / "raw" / "etsi" / "ts183017-030201.raw.dad",
    "ETSI-TS183.020": _CORPUS_DIR / "raw" / "etsi" / "ts183020-010101.raw.dad",
    "ETSI-TS183.033": _CORPUS_DIR / "raw" / "etsi" / "ts183033-010200.raw.dad",
    "ETSI-TS183.059-1": _CORPUS_DIR / "raw" / "etsi" / "ts18305901-020101.raw.dad",
    "ETSI-TS183.066": _CORPUS_DIR / "raw" / "etsi" / "ts183066-020101.raw.dad",
    "OMA-DDS-Charging_Data": _CORPUS_DIR
    / "raw"
    / "oma"
    / "dds-charging_data-v1_0-20110201-a.raw.dad",
}


def test_every_transcription_has_its_committed_raw_file():
    assert [path.stem for path in _TRANSCRIPTIONS] == sorted(_RAW)


@pytest.mark.parametrize("path", _TRANSCRIPTIONS, ids=lambda path: path.stem)
def test_the_committed_raw_file_is_the_patched_transcription(path):
    spec, comments = transcription.read(path, _ROOT / "edits" / "sources")

    assert formatter.format_spec(spec, comments) == _RAW[path.stem].read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("path", _TRANSCRIPTIONS, ids=lambda path: path.stem)
def test_a_transcription_holds_what_the_document_prints(path):
    """Each carries a misprint the grammar cannot hold, so without its
    patches it does not parse; with them, it does."""
    with pytest.raises(ValueError):
        parser.parse(transcription.patched(path))

    parser.parse(transcription.patched(path, _ROOT / "edits" / "sources"))


def test_the_catalog_fetches_what_each_transcription_was_copied_from():
    """`seanchai corpus download` reads the catalog's URL and the export looks the
    file up by the name in the transcription's header, so the two are one."""
    catalog = {document.reference: document for document in load_catalog().transcribed}

    assert sorted(catalog) == [path.stem for path in _TRANSCRIPTIONS]
    for path in _TRANSCRIPTIONS:
        spec = parser.parse(transcription.patched(path, _ROOT / "edits" / "sources"))
        assert str(spec.transcribed) == catalog[path.stem].url


def test_a_patch_that_stops_matching_fails_the_reading(tmp_path):
    text = (_ROOT / "edits" / "transcriptions" / "ETSI-TS183.017.dad").read_text(
        encoding="utf-8"
    )
    path = tmp_path / "ETSI-TS183.017.dad"
    path.write_text(text.replace("< AVP header: x >", "< AVP header: 510 >"))

    with pytest.raises(PatchError, match="applied 0 times, expected 1"):
        transcription.read(path, _ROOT / "edits" / "sources")


def test_a_section_directive_with_trailing_comment_still_scopes_patches(tmp_path):
    text = (_ROOT / "edits" / "transcriptions" / "ETSI-TS183.017.dad").read_text(
        encoding="utf-8"
    )
    assert "; Section: 7.3.20\n" in text
    path = tmp_path / "ETSI-TS183.017.dad"
    path.write_text(text.replace("; Section: 7.3.20\n", "; Section: 7.3.20 ;; Flows\n"))

    parser.parse(transcription.patched(path, _ROOT / "edits" / "sources"))
