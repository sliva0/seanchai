"""Loading several `.dad` files, and choosing which one an origin means."""

from pathlib import Path

import pytest

from seanchai import corpus
from seanchai.dad import ast, formatter


def _spec(specification, version, *sections):
    return ast.Specification(
        specification=specification,
        version=version,
        vendor_id=10415,
        sections=sections
        or (
            ast.GroupedAvp(
                name="Example",
                source=ast.SourceRef(section="6.1"),
                code=700,
                vendor_id=10415,
                avps=(),
            ),
        ),
    )


def _entry(specification, version):
    return corpus.Entry(
        path=Path(f"{specification}-{version}.dad"), spec=_spec(specification, version)
    )


def test_the_newest_matching_version_wins():
    books = corpus.Corpus(
        [
            _entry("3GPP TS 29.272", v)
            for v in ("17.9.0", "18.1.0", "18.10.0", "18.2.0", "19.0.0")
        ]
    )

    resolved = books.resolve("TS29.272", like=_spec("3GPP TS 29.388", "18.0.0"))

    # Newest by version *number*: 18.10.0 is above 18.2.0, which string
    # ordering would get backwards.
    assert resolved is not None
    assert resolved.spec.version == "18.10.0"


def test_nothing_resolves_across_a_major_version():
    """A release boundary is where 3GPP may change what an AVP means, so
    checking a Rel-18 document against a Rel-19 definition would report
    differences that are not errors."""
    books = corpus.Corpus([_entry("3GPP TS 29.272", "19.0.0")])

    assert books.resolve("TS29.272", like=_spec("3GPP TS 29.388", "18.1.0")) is None


def test_an_external_origin_resolves_to_any_copy():
    """ETSI's versions are not 3GPP's releases: a hand-written V3.2.1 of
    ETSI TS 183 017 is what a Release 18 citation means."""
    books = corpus.Corpus([_entry("ETSI TS 183 017", "3.2.1")])

    resolved = books.resolve("ETSI-TS183.017", like=_spec("3GPP TS 29.214", "18.4.0"))

    assert resolved is not None
    assert resolved.reference == "ETSI-TS183.017"


def test_onem2m_ts_0004_resolves_for_ts_32_299_from_the_committed_corpus():
    """TS 32.299 table 7.5.1 cites `oneM2M-TS-0004` ([301], Release 2 by no
    version); the corpus holds V2.35.0, oneM2M's own numbering, which a
    Release 18 citation reads as any external document's."""
    books = corpus.Corpus.load([Path(__file__).parent.parent / "dad"])
    citing = _spec("3GPP TS 32.299", "18.0.0")

    resolved = books.resolve("oneM2M-TS-0004", like=citing)

    assert resolved is not None
    assert resolved.path.as_posix().endswith("dad/onem2m/ts-0004-v2_35_0.dad")
    assert (resolved.spec.version, resolved.spec.vendor_id) == ("2.35.0", 45687)
    assert books.versions("oneM2M-TS-0004") == ["2.35.0"]


def test_a_misnamed_citation_resolves_to_the_publishers_document():
    """3GPP cites the e4 document as "ETSI TS 283 034"; ETSI publishes it
    as ES 283 034, which is the title its transcription carries."""
    books = corpus.Corpus([_entry("ETSI ES 283 034", "2.2.0")])

    resolved = books.resolve("ETSI-TS283.034", like=_spec("3GPP TS 29.212", "18.2.0"))

    assert resolved is not None
    assert resolved.reference == "ETSI-ES283.034"
    assert books.versions("ETSI-TS283.034") == ["2.2.0"]


def test_another_publishers_document_resolves_no_3gpp_citation():
    """ETSI TS 183 017 V3.2.1 cites TS 29.214 Release 7 (its clause 2); its
    own version names no 3GPP release, so a Release 18 copy is no answer."""
    books = corpus.Corpus(
        [_entry("3GPP TS 29.214", "18.4.0"), _entry("RFC 4005", None)]
    )
    citing = _spec("ETSI TS 183 017", "3.2.1")

    assert books.resolve("TS29.214", like=citing) is None
    assert books.resolve("RFC4005", like=citing) is not None


def test_an_absent_origin_resolves_to_nothing_rather_than_raising():
    """A partial corpus is the normal state, and callers report the gap as a
    note rather than failing the run."""
    books = corpus.Corpus([])

    assert books.resolve("TS29.272", like=_spec("3GPP TS 29.388", "18.1.0")) is None
    assert books.versions("TS29.272") == []


def test_load_reads_a_directory_tree_and_skips_raw_files(tmp_path):
    """A corpus holding both copies of one specification would hold two
    documents that disagree on purpose and share a version number, leaving
    resolution to pick between them arbitrarily."""
    nested = tmp_path / "3gpp" / "rel-18"
    nested.mkdir(parents=True)
    text = formatter.format_spec(_spec("3GPP TS 29.272", "18.6.0"))
    (nested / "29272-i60.dad").write_text(text, encoding="utf-8")
    (nested / "29272-i60.raw.dad").write_text(text, encoding="utf-8")

    corrected = corpus.Corpus.load([tmp_path])
    raw = corpus.Corpus.load([tmp_path], raw=True)

    assert [entry.path.name for entry in corrected] == ["29272-i60.dad"]
    assert [entry.path.name for entry in raw] == ["29272-i60.raw.dad"]


def test_load_names_the_file_it_could_not_parse(tmp_path):
    broken = tmp_path / "broken.dad"
    broken.write_text("; Specification: nonsense\n", encoding="utf-8")

    with pytest.raises(corpus.CorpusError, match=r"broken\.dad"):
        corpus.Corpus.load([tmp_path])
