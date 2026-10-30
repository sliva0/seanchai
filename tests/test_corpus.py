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


def test_3gpp2_x_s0057_resolves_for_ts_29_212_from_the_committed_corpus():
    """TS 29.212 cites "3GPP2 X.S0057-B" ([24]); a spec-ref keeps no
    revision letter, and the corpus holds revision 0 V2.0, the last 3GPP2's
    library publishes, which a Release 18 citation reads as any external
    document's."""
    books = corpus.Corpus.load([Path(__file__).parent.parent / "dad"])
    citing = _spec("3GPP TS 29.212", "18.2.0")

    resolved = books.resolve("3GPP2-X.S0057", like=citing)

    assert resolved is not None
    assert resolved.path.as_posix().endswith("dad/3gpp2/xs0057-0_v2.0.dad")
    assert (resolved.spec.version, resolved.spec.vendor_id) == ("2.0", 5535)
    assert books.versions("3GPP2-X.S0057") == ["2.0"]


def _tgpp2_entry(revision, version="2.0"):
    spec = _spec("3GPP2 X.S0057", version).model_copy(
        update={
            "transcribed": f"http://example.test/X.S0057-{revision}_v{version}"
            "_091215.pdf"
        }
    )
    return corpus.Entry(path=Path(f"xs0057-{revision}.dad"), spec=spec)


def test_a_cited_3gpp2_revision_resolves_to_that_revision_and_no_other():
    """TS 29.212 [24] names revision B of 3GPP2 X.S0057 (`CITED_REVISIONS`):
    a copy of revision B answers it, unreported, ahead of a newer one."""
    books = corpus.Corpus([_tgpp2_entry("0"), _tgpp2_entry("B", "1.0")])

    entry, across = books.resolution(
        "3GPP2-X.S0057", like=_spec("3GPP TS 29.212", "18.2.0")
    )

    assert entry is not None and corpus.revision(entry.spec) == "B"
    assert across is None


def test_another_revision_stands_in_only_by_its_table_entry(monkeypatch):
    """Revision 0 V2.0 answers the citation of revision B because
    `STAND_INS` says so, and says so in turn; without the entry, the
    citation of an absent revision resolves to nothing, whatever the
    corpus holds of other revisions."""
    books = corpus.Corpus([_tgpp2_entry("0")])
    citing = _spec("3GPP TS 29.212", "18.2.0")

    entry, across = books.resolution("3GPP2-X.S0057", like=citing)

    assert entry is not None and corpus.revision(entry.spec) == "0"
    assert across == corpus.CrossRelease(
        "TS29.212",
        "3GPP2-X.S0057",
        "2.0",
        corpus.STAND_IN,
        cited_revision="B",
        revision="0",
    )
    assert str(across) == (
        "TS29.212 cites 3GPP2-X.S0057 revision B, which the corpus lacks:"
        " revision 0 V2.0 stands in (corpus.STAND_INS)"
    )
    # Only the version the entry names stands in.
    assert corpus.Corpus([_tgpp2_entry("0", "1.0")]).resolution(
        "3GPP2-X.S0057", like=citing
    ) == (None, None)

    monkeypatch.delitem(corpus.STAND_INS, ("TS29.212", "3GPP2-X.S0057"))
    assert books.resolution("3GPP2-X.S0057", like=citing) == (None, None)
    # A citation naming no revision takes whatever copy the corpus holds.
    other = _spec("3GPP TS 29.999", "18.0.0")
    assert books.resolve("3GPP2-X.S0057", like=other) is not None


def test_a_misnamed_citation_resolves_to_the_publishers_document():
    """3GPP cites the e4 document as "ETSI TS 283 034"; ETSI publishes it
    as ES 283 034, which is the title its transcription carries."""
    books = corpus.Corpus([_entry("ETSI ES 283 034", "2.2.0")])

    resolved = books.resolve("ETSI-TS283.034", like=_spec("3GPP TS 29.212", "18.2.0"))

    assert resolved is not None
    assert resolved.reference == "ETSI-ES283.034"
    assert books.versions("ETSI-TS283.034") == ["2.2.0"]


def test_another_publishers_document_resolves_no_3gpp_citation_by_its_version():
    """ETSI TS 183 017 V3.2.1 cites TS 29.214 Release 7 (its clause 2); its
    own version names no 3GPP release, so a Release 18 copy is no answer."""
    books = corpus.Corpus(
        [_entry("3GPP TS 29.214", "18.4.0"), _entry("RFC 4005", None)]
    )
    citing = _spec("ETSI TS 183 017", "3.2.1")

    assert books.resolve("TS29.214", like=citing) is None
    assert books.resolve("RFC4005", like=citing) is not None


def test_a_specific_reference_resolves_to_the_version_it_names_and_no_other():
    """TS 183 017 V3.2.1 clause 2 [19] names "3GPP TS 29.214 Release 7",
    whose last version is V7.12.0 (`corpus.CITED_VERSIONS`): the Release 18
    copy is no answer, nor is another Release 7 version."""
    citing = _spec("ETSI TS 183 017", "3.2.1")
    books = corpus.Corpus(
        [_entry("3GPP TS 29.214", v) for v in ("7.11.0", "7.12.0", "18.4.0")]
    )

    entry, across = books.resolution("TS29.214", like=citing)

    assert entry is not None and entry.spec.version == "7.12.0"
    assert across == corpus.CrossRelease(
        "ETSI-TS183.017", "TS29.214", "7.12.0", corpus.SPECIFIC
    )
    lacking = corpus.Corpus([_entry("3GPP TS 29.214", "7.11.0")])
    assert lacking.resolution("TS29.214", like=citing) == (None, None)


def test_a_non_specific_reference_past_the_documents_end_means_its_final_version():
    """TS 32.299 V18.0.0 cites TS 29.140 non-specifically, which TR 21.801
    clause 6.6.6.5.3 reads as the latest version in Release 18; TS 29.140
    ended at V7.0.0 (`corpus.FINAL_VERSIONS`), which the corpus reads it as,
    and not an earlier Release 7 copy."""
    books = corpus.Corpus([_entry("3GPP TS 29.140", v) for v in ("6.4.0", "7.0.0")])

    entry, across = books.resolution("TS29.140", like=_spec("3GPP TS 32.299", "18.0.0"))

    assert entry is not None and entry.spec.version == "7.0.0"
    assert across is not None and across.rule == corpus.NON_SPECIFIC
    assert str(across) == (
        "TS32.299 cites TS29.140: the reference is non-specific and V7.0.0 is"
        " the document's final version (corpus.FINAL_VERSIONS)"
    )
    # An ETSI document has no release; its non-specific reference is the
    # latest version, which for an ended document is the final one.
    assert books.resolve("TS29.140", like=_spec("ETSI ES 283 034", "2.2.0")) is not None


def test_the_final_version_answers_no_citation_from_its_own_release_or_earlier():
    """A Release 6 document citing TS 29.140 means Release 6's latest, which
    the corpus lacks; Release 7's own citation is today's rule, with no
    crossing; and a document with no final version is never read so."""
    books = corpus.Corpus([_entry("3GPP TS 29.140", "7.0.0")])

    assert books.resolve("TS29.140", like=_spec("3GPP TS 32.299", "6.12.0")) is None
    assert (
        books.resolution("TS29.140", like=_spec("3GPP TS 32.299", "7.9.0"))[1] is None
    )
    alive = corpus.Corpus([_entry("3GPP TS 29.229", "18.1.0")])
    assert alive.resolve("TS29.229", like=_spec("ETSI ES 283 034", "2.2.0")) is None


def test_the_tables_name_only_versions_the_catalog_pins_and_verifies():
    """A specific reference's version and a final version are the catalog's
    pins, which every download checks against the 3GPP archive (`final`):
    a version the corpus could not be shown to hold is never claimed."""
    from seanchai.downloader import load_catalog

    pinned = {
        (f"TS{pin.number}", pin.version): pin.final for pin in load_catalog().pinned
    }

    assert {
        (reference, version): "document"
        for reference, version in corpus.FINAL_VERSIONS.items()
    }.items() <= pinned.items()
    for (_, cited), version in corpus.CITED_VERSIONS.items():
        assert (cited, version) in pinned


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
