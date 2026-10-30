"""Hand transcriptions: the input patches stand between them and the raw
files, as they stand between a 3GPP document and its extraction."""

import pytest
from conftest import _ROOT

from seanchai.dad import formatter, parser
from seanchai.extractor import transcription
from seanchai.extractor.sources import PatchError

_TRANSCRIPTIONS = sorted((_ROOT / "edits" / "transcriptions").glob("*.dad"))
_RAW = {
    "3GPP2-X.S0057": _ROOT / "dad" / "raw" / "3gpp2" / "xs0057-0_v2.0.raw.dad",
    "ETSI-ES283.034": _ROOT / "dad" / "raw" / "etsi" / "es283034-020200.raw.dad",
    "ETSI-TS183.017": _ROOT / "dad" / "raw" / "etsi" / "ts183017-030201.raw.dad",
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
