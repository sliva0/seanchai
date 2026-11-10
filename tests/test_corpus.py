"""Loading several `.dad` files, and choosing which one an origin means."""

import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
import seanchai_corpus
from conftest import _CORPUS_DIR, _ROOT, _RULES

import seanchai
from seanchai import corpus, model, oracle
from seanchai._regenerate import ManifestError
from seanchai.dad import abnf, ast, corrections, formatter, parser
from seanchai.downloader import DownloadError
from seanchai.extractor import errors, sources


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


def _books(entries, rules=_RULES):
    """A fixture corpus, resolving by the committed corpus's rules."""
    return corpus.Corpus(entries, rules=rules)


def _without(table, key):
    """The committed rules lacking one entry of `table`."""
    rules = _RULES
    return replace(
        rules, **{table: {k: v for k, v in getattr(rules, table).items() if k != key}}
    )


def _entry(specification, version):
    return corpus.Entry(
        path=Path(f"{specification}-{version}.dad"), spec=_spec(specification, version)
    )


def test_the_newest_matching_version_wins():
    books = _books(
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
    books = _books([_entry("3GPP TS 29.272", "19.0.0")])

    assert books.resolve("TS29.272", like=_spec("3GPP TS 29.388", "18.1.0")) is None


def test_an_external_origin_resolves_to_any_copy():
    """ETSI's versions are not 3GPP's releases: a hand-written V3.2.1 of
    ETSI TS 183 017 is what a Release 18 citation means."""
    books = _books([_entry("ETSI TS 183 017", "3.2.1")])

    resolved = books.resolve("ETSI-TS183.017", like=_spec("3GPP TS 29.214", "18.4.0"))

    assert resolved is not None
    assert resolved.reference == "ETSI-TS183.017"


def test_onem2m_ts_0004_resolves_for_ts_32_299_from_the_committed_corpus():
    """TS 32.299 table 7.5.1 cites `oneM2M-TS-0004` ([301], Release 2 by no
    version); the corpus holds V2.35.0, oneM2M's own numbering, which a
    Release 18 citation reads as any external document's."""
    books = corpus.Corpus.load([_CORPUS_DIR])
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
    books = corpus.Corpus.load([_CORPUS_DIR])
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
    """TS 29.212 [24] names revision B of 3GPP2 X.S0057 (a `cited_revision`):
    a copy of revision B answers it, unreported, ahead of a newer one."""
    books = _books([_tgpp2_entry("0"), _tgpp2_entry("B", "1.0")])

    entry, across = books.resolution(
        "3GPP2-X.S0057", like=_spec("3GPP TS 29.212", "18.2.0")
    )

    assert entry is not None and corpus.revision(entry.spec) == "B"
    assert across is None


def test_another_revision_stands_in_only_by_its_table_entry():
    """Revision 0 V2.0 answers the citation of revision B because
    a `stand_in` says so, and says so in turn; without the entry, the
    citation of an absent revision resolves to nothing, whatever the
    corpus holds of other revisions."""
    books = _books([_tgpp2_entry("0")])
    citing = _spec("3GPP TS 29.212", "18.2.0")

    entry, across = books.resolution("3GPP2-X.S0057", like=citing)

    assert entry is not None and corpus.revision(entry.spec) == "0"
    assert across == corpus.CrossRelease(
        "TS29.212",
        "3GPP2-X.S0057",
        "2.0",
        corpus.CitationRule.STAND_IN,
        cited_revision="B",
        revision="0",
    )
    assert str(across) == (
        "TS29.212 cites 3GPP2-X.S0057 revision B, which the corpus lacks:"
        " revision 0 V2.0 stands in (corpus.toml, stand_in)"
    )
    # Only the version the entry names stands in.
    assert _books([_tgpp2_entry("0", "1.0")]).resolution(
        "3GPP2-X.S0057", like=citing
    ) == (None, None)

    books.rules = _without("stand_ins", ("TS29.212", "3GPP2-X.S0057"))
    assert books.resolution("3GPP2-X.S0057", like=citing) == (None, None)
    # A citation naming no revision takes whatever copy the corpus holds.
    other = _spec("3GPP TS 29.999", "18.0.0")
    assert books.resolve("3GPP2-X.S0057", like=other) is not None


def test_a_later_release_stands_in_only_by_its_table_entry():
    """TS 32.299 V11.20.0 cites TS 29.229 non-specifically, meaning V11.5.0,
    Release 11's last, which the corpus lacks; V19.1.0 answers by its
    `release_stand_in` entry and says so. Another release's copy of the
    citing document, or the held copy at another version, gets nothing,
    and without the entry nor does V11.20.0."""
    citing = _spec("3GPP TS 32.299", "11.20.0")
    books = _books([_entry("3GPP TS 29.229", "19.1.0")])

    entry, across = books.resolution("TS29.229", like=citing)

    assert entry is not None and entry.spec.version == "19.1.0"
    assert across == corpus.CrossRelease(
        "TS32.299", "TS29.229", "19.1.0", corpus.CitationRule.STAND_IN, meant="11.5.0"
    )
    assert str(across) == (
        "TS32.299 cites TS29.229 non-specifically, meaning V11.5.0, which the"
        " corpus lacks: V19.1.0 stands in (corpus.toml, release_stand_in)"
    )
    # A Release 11 copy, were the corpus to hold one, is the answer itself.
    held = _books([_entry("3GPP TS 29.229", v) for v in ("11.5.0", "19.1.0")])
    assert held.resolution("TS29.229", like=citing)[1] is None
    assert _books([_entry("3GPP TS 29.229", "18.2.0")]).resolution(
        "TS29.229", like=citing
    ) == (None, None)
    assert books.resolution("TS29.229", like=_spec("3GPP TS 32.299", "11.19.0")) == (
        None,
        None,
    )

    books.rules = _without("release_stand_ins", ("TS32.299", "11.20.0", "TS29.229"))
    assert books.resolution("TS29.229", like=citing) == (None, None)


def test_a_later_release_states_a_field_only_by_its_table_entry():
    """TS 29.210 V6.7.0's TS 29.061 is V6.15.0, which still answers the citation;
    its `release_fill` entry lets V19.1.0 state the named field and says so.
    Another copy of the citing document, or a corpus lacking V19.1.0, gets
    nothing, and without the entry nor does V6.7.0."""
    citing = _spec("3GPP TS 29.210", "6.7.0")
    books = _books([_entry("3GPP TS 29.061", v) for v in ("6.15.0", "19.1.0")])

    entry, across = books.resolution("TS29.061", like=citing)
    assert entry is not None and entry.spec.version == "6.15.0"
    assert across is None

    found = books.release_fill("TS29.061", like=citing)
    assert found is not None
    later, fill, crossing = found
    assert later.spec.version == "19.1.0"
    assert fill.fields == ("data_type",)
    assert crossing == corpus.CrossRelease(
        "TS29.210",
        "TS29.061",
        "19.1.0",
        corpus.CitationRule.LATER_RELEASE,
        meant="6.15.0",
    )
    assert str(crossing) == (
        "TS29.210 cites TS29.061 non-specifically, meaning V6.15.0, which leaves a"
        " field unstated: V19.1.0 states it (corpus.toml, release_fill)"
    )
    assert books.release_fill("TS29.061", like=_spec("3GPP TS 29.210", "6.6.0")) is None
    assert (
        _books([_entry("3GPP TS 29.061", "6.15.0")]).release_fill(
            "TS29.061", like=citing
        )
        is None
    )

    books.rules = _without("release_fills", ("TS29.210", "6.7.0", "TS29.061"))
    assert books.release_fill("TS29.061", like=citing) is None


def test_a_misnamed_citation_resolves_to_the_publishers_document():
    """3GPP cites the e4 document as "ETSI TS 283 034"; ETSI publishes it
    as ES 283 034, which is the title its transcription carries."""
    books = _books([_entry("ETSI ES 283 034", "2.2.0")])

    resolved = books.resolve("ETSI-TS283.034", like=_spec("3GPP TS 29.212", "18.2.0"))

    assert resolved is not None
    assert resolved.reference == "ETSI-ES283.034"
    assert books.versions("ETSI-TS283.034") == ["2.2.0"]


def test_another_publishers_document_resolves_no_3gpp_citation_by_its_version():
    """ETSI TS 183 017 V3.2.1 cites TS 29.214 Release 7 (its clause 2); its
    own version names no 3GPP release, so a Release 18 copy is no answer."""
    books = _books([_entry("3GPP TS 29.214", "18.4.0"), _entry("RFC 4005", None)])
    citing = _spec("ETSI TS 183 017", "3.2.1")

    assert books.resolve("TS29.214", like=citing) is None
    assert books.resolve("RFC4005", like=citing) is not None


def test_a_specific_reference_resolves_to_the_version_it_names_and_no_other():
    """TS 183 017 V3.2.1 clause 2 [19] names "3GPP TS 29.214 Release 7",
    whose last version is V7.12.0 (a `cited_version`): the Release 18
    copy is no answer, nor is another Release 7 version."""
    citing = _spec("ETSI TS 183 017", "3.2.1")
    books = _books(
        [_entry("3GPP TS 29.214", v) for v in ("7.11.0", "7.12.0", "18.4.0")]
    )

    entry, across = books.resolution("TS29.214", like=citing)

    assert entry is not None and entry.spec.version == "7.12.0"
    assert across == corpus.CrossRelease(
        "ETSI-TS183.017", "TS29.214", "7.12.0", corpus.CitationRule.SPECIFIC
    )
    lacking = _books([_entry("3GPP TS 29.214", "7.11.0")])
    assert lacking.resolution("TS29.214", like=citing) == (None, None)


def test_a_non_specific_reference_past_the_documents_end_means_its_final_version():
    """TS 32.299 V18.0.0 cites TS 29.140 non-specifically, which TR 21.801
    clause 6.6.6.5.3 reads as the latest version in Release 18; TS 29.140
    ended at V7.0.0 (a `final_version`), which the corpus reads it as,
    and not an earlier Release 7 copy."""
    books = _books([_entry("3GPP TS 29.140", v) for v in ("6.4.0", "7.0.0")])

    entry, across = books.resolution("TS29.140", like=_spec("3GPP TS 32.299", "18.0.0"))

    assert entry is not None and entry.spec.version == "7.0.0"
    assert across is not None and across.rule == corpus.CitationRule.NON_SPECIFIC
    assert str(across) == (
        "TS32.299 cites TS29.140: the reference is non-specific and V7.0.0 is"
        " the document's final version (corpus.toml, final_version)"
    )
    # An ETSI document has no release; its non-specific reference is the
    # latest version, which for an ended document is the final one.
    assert books.resolve("TS29.140", like=_spec("ETSI ES 283 034", "2.2.0")) is not None


def test_the_final_version_answers_no_citation_from_its_own_release_or_earlier():
    """A Release 6 document citing TS 29.140 means Release 6's latest, which
    the corpus lacks; Release 7's own citation is today's rule, with no
    crossing; and a document with no final version is never read so."""
    books = _books([_entry("3GPP TS 29.140", "7.0.0")])

    assert books.resolve("TS29.140", like=_spec("3GPP TS 32.299", "6.12.0")) is None
    assert (
        books.resolution("TS29.140", like=_spec("3GPP TS 32.299", "7.9.0"))[1] is None
    )
    alive = _books([_entry("3GPP TS 29.229", "18.1.0")])
    assert alive.resolve("TS29.229", like=_spec("ETSI ES 283 034", "2.2.0")) is None


def test_a_clause_saying_the_latest_edition_applies_reads_the_newest_copy():
    """ES 283 035 clause 2.1: 'For non-specific references, the latest edition
    of the referenced document (including any amendments) applies'."""
    books = _books(
        [_entry("3GPP TS 29.329", "18.0.0"), _entry("3GPP TS 29.329", "11.0.0")]
    )

    entry, across = books.resolution("TS29.329", like=_spec("ETSI ES 283 035", "2.5.1"))

    assert entry is not None and entry.spec.version == "18.0.0"
    assert across == corpus.CrossRelease(
        "ETSI-ES283.035", "TS29.329", "18.0.0", corpus.CitationRule.LATEST_EDITION
    )
    assert "latest edition" in str(across)
    # Nothing says so for another document, whose citation stays unanswered.
    assert books.resolution("TS29.329", like=_spec("ETSI TS 183 066", "2.1.1")) == (
        None,
        None,
    )


def test_a_version_an_etsi_document_names_is_answered_by_its_stand_in_alone():
    """TS 183 033 clause 2.1 [2] names TS 29.229 V6.6.0, which the catalog cannot
    pin, being no release's last, and V19.1.0 stands in on the entry's evidence."""
    citing = _spec("ETSI TS 183 033", "1.2.0")

    entry, across = _books([_entry("3GPP TS 29.229", "19.1.0")]).resolution(
        "TS29.229", like=citing
    )

    assert entry is not None and entry.spec.version == "19.1.0"
    assert across == corpus.CrossRelease(
        "ETSI-TS183.033",
        "TS29.229",
        "19.1.0",
        corpus.CitationRule.STAND_IN,
        meant="6.6.0",
        specific=True,
    )
    assert "naming V6.6.0" in str(across)
    # The evidence is about that copy, so no other answers.
    assert _books([_entry("3GPP TS 29.229", "17.0.0")]).resolution(
        "TS29.229", like=citing
    ) == (None, None)


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
        for reference, version in _RULES.final_versions.items()
    }.items() <= pinned.items()
    for (_, cited), version in _RULES.cited_versions.items():
        assert (cited, version) in pinned


def test_an_absent_origin_resolves_to_nothing_rather_than_raising():
    """A partial corpus is the normal state, and callers report the gap as a
    note rather than failing the run."""
    books = _books([])

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


_RECORDED = """
[[hole]]
document = "TS29.900"
name = "Thing"
missing = ["data_type", "flag_rules"]
reason = "clause 6.3.1 states no type"
"""


def _corpus_directory(tmp_path, record: str | None = _RECORDED) -> Path:
    tree = tmp_path / "dad" / "3gpp"
    tree.mkdir(parents=True)
    (tree / "29900.dad").write_text(
        formatter.format_spec(_spec("3GPP TS 29.900", "18.0.0")), encoding="utf-8"
    )
    if record is not None:
        (tmp_path / "dad" / corpus.HOLE_RECORD).write_text(record, encoding="utf-8")
    return tmp_path / "dad"


def test_a_corpus_directory_brings_its_record_of_known_holes(tmp_path):
    directory = _corpus_directory(tmp_path)

    books = corpus.Corpus.load([directory])

    assert books.record == corpus.HoleRecord(
        directory / "holes.toml",
        (
            corpus.KnownHole(
                "TS29.900",
                "Thing",
                (corpus.Missing.DATA_TYPE, corpus.Missing.FLAG_RULES),
                "clause 6.3.1 states no type",
            ),
        ),
    )
    assert len(books) == 1


def test_only_a_whole_corrected_corpus_has_the_record(tmp_path):
    """A subdirectory or a file list is partial, and raw files are not what
    the record describes."""
    directory = _corpus_directory(tmp_path)

    assert corpus.Corpus.load([directory / "3gpp"]).record is None
    assert corpus.Corpus.load([directory / "3gpp" / "29900.dad"]).record is None
    assert corpus.Corpus.load([directory], raw=True).record is None
    assert (
        corpus.Corpus.load([_corpus_directory(tmp_path / "bare", None)]).record is None
    )


def test_two_records_in_one_corpus_are_refused(tmp_path):
    one = _corpus_directory(tmp_path / "one")
    two = _corpus_directory(tmp_path / "two")

    with pytest.raises(corpus.CorpusError, match="two hole records"):
        corpus.Corpus.load([one, two])


def test_a_directory_named_twice_is_one_directory(tmp_path):
    directory = _corpus_directory(tmp_path)
    spelled = directory / "3gpp" / ".."

    books = corpus.Corpus.load([directory, spelled, directory / "3gpp"])

    assert len(books) == 1
    assert books.record is not None


def test_two_files_claiming_one_copy_are_refused_in_either_order(tmp_path):
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    text = formatter.format_spec(_spec("3GPP TS 29.229", "18.1.0"))
    one, two = tmp_path / "one" / "a.dad", tmp_path / "two" / "b.dad"
    one.write_text(text, encoding="utf-8")
    two.write_text(text, encoding="utf-8")

    for paths in ([one, two], [two, one]):
        with pytest.raises(corpus.CorpusError) as raised:
            corpus.Corpus.load(paths)
        assert str(one) in str(raised.value) and str(two) in str(raised.value)
        assert "TS29.229 18.1.0" in str(raised.value)


def test_a_file_reached_through_a_symlink_is_one_copy(tmp_path):
    (tmp_path / "real").mkdir()
    path = tmp_path / "real" / "a.dad"
    path.write_text(
        formatter.format_spec(_spec("3GPP TS 29.229", "18.1.0")), encoding="utf-8"
    )
    (tmp_path / "link").symlink_to(tmp_path / "real")

    books = corpus.Corpus.load([path, tmp_path / "link" / "a.dad"])

    assert [entry.path for entry in books] == [path]


def test_one_entry_given_twice_is_one_copy():
    entry = _entry("3GPP TS 29.229", "18.1.0")

    assert len(_books([entry, entry])) == 1


def test_3gpp2_revisions_of_one_version_are_two_documents():
    """A spec-ref keeps no revision letter, so version alone does not identify
    a 3GPP2 copy: X.S0057-0 and -B may both print V2.0."""
    books = _books([_tgpp2_entry("0"), _tgpp2_entry("B")])
    assert len(books) == 2

    twin = corpus.Entry(Path("twin.dad"), _tgpp2_entry("0").spec)
    with pytest.raises(corpus.CorpusError, match=r"xs0057-0\.dad and twin\.dad"):
        _books([_tgpp2_entry("0"), twin])


def test_rfc_copies_conflict_without_a_version():
    rfc = _spec("RFC 6733", None)
    with pytest.raises(corpus.CorpusError, match="are both RFC6733; give one copy"):
        _books([corpus.Entry(Path(n), rfc) for n in ("a.dad", "b.dad")])


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ("[[hole]\n", "holes.toml"),
        ('[[gap]]\nname = "Thing"\n', "only .*hole.* tables"),
        (_RECORDED + _RECORDED, "TS29.900 Thing is listed twice"),
        (_RECORDED + 'extra = "no"\n', "states exactly"),
        (_RECORDED.replace('reason = "clause 6.3.1 states no type"', ""), "states"),
        (_RECORDED.replace("clause 6.3.1 states no type", " "), "non-empty"),
        (_RECORDED.replace('["data_type", "flag_rules"]', "[]"), "non-empty"),
        (_RECORDED.replace('["data_type", "flag_rules"]', "1"), "non-empty"),
        (_RECORDED.replace('["data_type", "flag_rules"]', '"undefined"'), "non-empty"),
        (_RECORDED.replace('["data_type", "flag_rules"]', "[1]"), "non-empty"),
        ("hole = 1\n", "only .*hole.* tables"),
        ('[hole]\nname = "Thing"\n', "only .*hole.* tables"),
        ("hole = [1]\n", "states exactly"),
    ],
    ids=[
        "toml",
        "table",
        "twice",
        "extra",
        "no-reason",
        "blank-reason",
        "no-missing",
        "missing-number",
        "missing-text",
        "missing-of-numbers",
        "hole-number",
        "hole-table",
        "hole-of-numbers",
    ],
)
def test_a_malformed_record_fails_the_load(tmp_path, record, message):
    directory = _corpus_directory(tmp_path, record)

    with pytest.raises(corpus.CorpusError, match=message):
        corpus.Corpus.load([directory])


def test_a_hole_reads_its_reason_as_prose_and_the_rest_exactly(tmp_path):
    path = tmp_path / "holes.toml"
    path.write_text(
        _RECORDED.replace(
            '"clause 6.3.1 states no type"',
            '"""\n    clause 6.3.1\n    states   no type\n    """',
        )
    )

    (hole,) = corpus.HoleRecord.load(path).holes

    assert hole == corpus.KnownHole(
        "TS29.900",
        "Thing",
        (corpus.Missing.DATA_TYPE, corpus.Missing.FLAG_RULES),
        "clause 6.3.1 states no type",
    )


def test_a_hole_missing_what_no_hole_can_miss_is_refused(tmp_path):
    path = tmp_path / "holes.toml"
    path.write_text(_RECORDED.replace('"data_type"', '"type"'))

    with pytest.raises(corpus.CorpusError, match="missing holds type, which is not"):
        corpus.HoleRecord.load(path)


# A corpus file the fixture corpus of `_corpus_directory` satisfies: TS 29.900
# V18.0.0 is all it holds.
_DESCRIBED = '''format = 1

[[final_version]]
document = "TS29.900"
version = "18.0.0"
evidence = """
    clause 1
    says   so
    """
'''


def _described(tmp_path, text: str = _DESCRIBED) -> Path:
    directory = _corpus_directory(tmp_path)
    (directory / corpus.CORPUS_FILE).write_text(text, encoding="utf-8")
    return directory


def test_a_corpus_directory_brings_its_rules_raw_mirror_included(tmp_path):
    """Unlike the record of holes, the rules answer raw files too: a raw From
    cell is what `cited_as` exists for."""
    directory = _described(tmp_path)
    (directory / "3gpp" / "29900.raw.dad").write_text(
        formatter.format_spec(_spec("3GPP TS 29.900", "18.0.0")), encoding="utf-8"
    )

    for raw in (False, True):
        rules = corpus.Corpus.load([directory], raw=raw).rules
        assert rules == corpus.Rules(
            path=directory / "corpus.toml",
            format=1,
            final_versions={"TS29.900": "18.0.0"},
        )


def test_a_corpus_without_its_file_has_empty_rules_and_no_format(tmp_path):
    """No file, no marker: nothing to hold the corpus to, and nothing a
    citation could resolve by. A subdirectory or a file list is partial, and
    has none either."""
    bare = _corpus_directory(tmp_path / "bare")
    assert corpus.Corpus.load([bare]).rules == corpus.Rules()
    assert corpus.Corpus.load([bare]).rules.format is None

    directory = _described(tmp_path / "described")
    assert corpus.Corpus.load([directory / "3gpp"]).rules == corpus.Rules()
    assert corpus.Corpus.load([directory / "3gpp" / "29900.dad"]).rules == (
        corpus.Rules()
    )
    assert corpus.Corpus([]).rules == corpus.Rules()


def test_the_committed_corpus_states_the_format_this_library_reads():
    assert corpus.Corpus.load([_CORPUS_DIR]).rules.format in corpus.FORMATS
    assert _RULES.format == 1


@pytest.mark.parametrize(
    ("found", "upgrade"), [(2, "upgrade seanchai$"), (0, "upgrade seanchai-corpus$")]
)
def test_a_corpus_of_another_format_names_both_and_the_package_to_upgrade(
    tmp_path, found, upgrade
):
    """The format is read before any `.dad` file, so a newer grammar the
    library cannot parse is refused as a format, not as a parse error."""
    directory = _described(
        tmp_path, _DESCRIBED.replace("format = 1", f"format = {found}")
    )
    (directory / "newer.dad").write_text("; Specification: nonsense\n", "utf-8")

    for raw in (False, True):
        with pytest.raises(corpus.CorpusFormatError, match=upgrade) as raised:
            corpus.Corpus.load([directory], raw=raw)
        assert raised.value.found == found
        assert raised.value.reads == corpus.FORMATS
        message = str(raised.value)
        assert f"the corpus is format {found}" in message
        assert f"seanchai {seanchai.__version__} reads format 1" in message
        assert str(directory / "corpus.toml") in message
    assert issubclass(corpus.CorpusFormatError, corpus.CorpusError)


def test_installed_refuses_a_corpus_of_a_format_the_library_does_not_read(
    monkeypatch,
):
    monkeypatch.setattr(corpus, "FORMATS", (2,))

    with pytest.raises(corpus.CorpusFormatError) as raised:
        corpus.Corpus.installed()
    assert str(raised.value).endswith(
        "the corpus is format 1, and seanchai"
        f" {seanchai.__version__} reads format 2: upgrade seanchai-corpus"
    )
    with pytest.raises(corpus.CorpusFormatError):
        corpus.Corpus.installed(raw=True)


def test_two_corpus_files_in_one_corpus_are_refused(tmp_path):
    one = _described(tmp_path / "one")
    two = _described(tmp_path / "two")

    # Raw, which has no record of holes to be refused for first.
    with pytest.raises(corpus.CorpusError, match="two corpus files"):
        corpus.Corpus.load([one, two], raw=True)


_ENTRY = """
evidence = "clause 2"
"""
_F = "format = 1\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("format = [\n", "corpus.toml"),
        ('[[final_version]]\ndocument = "TS29.900"\n', "states no corpus format"),
        ('format = "1"\n', "states no corpus format"),
        ("format = true\n", "states no corpus format"),
        ("format = 1\n[[stand_ins]]\n", "stand_ins: not a table"),
        ("format = 1\nfinal_version = 1\n", r"must be \[\[final_version\]\]"),
        ("format = 1\n[final_version]\n", r"must be \[\[final_version\]\]"),
        ("format = 1\nfinal_version = [1]\n", "states document, evidence, version"),
        (
            _F + '[[final_version]]\ndocument = "TS29.900"\nversion = "18.0.0"\n',
            "states document, evidence, version",
        ),
        (
            _F + '[[final_version]]\ndocument = "TS29.900"\nversion = "18.0.0"\n'
            'evidence = "x"\nreason = "y"\n',
            "states document, evidence, version",
        ),
        (
            _F + '[[final_version]]\ndocument = "TS29.900"\nversion = "18.0.0"\n'
            'evidence = "  "\n',
            "evidence must be non-empty text",
        ),
        (
            _F + '[[final_version]]\ndocument = "TS29.900"\nversion = 18\n'
            'evidence = "x"\n',
            "version must be non-empty text",
        ),
        (
            _F + '[[final_version]]\ndocument = "TS29.900"\nversion = "18.0.0"\n'
            'evidence = "x"\n' * 2,
            r"\[\[final_version\]\] TS29.900 is stated twice",
        ),
        (
            _F + '[[stand_in]]\ncited = "TS29.900"\nciting = "TS29.900"\n'
            'revision = "0"\nversion = "18.0.0"\nevidence = "x"\n',
            "no \\[\\[cited_revision\\]\\] names the revision",
        ),
        (
            _F + '[[release_stand_in]]\ncited = "TS29.900"\nciting = "TS29.900"\n'
            'citing_version = "18.0.0"\nmeant = "17.0.0"\nversion = "18.0.0"\n'
            'specific = "yes"\nevidence = "x"\n',
            "specific must be true or false",
        ),
        (
            _F + '[[release_fill]]\ncited = "TS29.900"\nciting = "TS29.900"\n'
            'citing_version = "18.0.0"\nmeant = "17.0.0"\nversion = "18.0.0"\n'
            'names = ["Thing"]\nfields = ["code"]\nevidence = "x"\n',
            "fields must be a non-empty list of distinct names of data_type",
        ),
        (
            _F + '[[release_fill]]\ncited = "TS29.900"\nciting = "TS29.900"\n'
            'citing_version = "18.0.0"\nmeant = "17.0.0"\nversion = "18.0.0"\n'
            'names = []\nfields = ["data_type"]\nevidence = "x"\n',
            "names must be a non-empty list",
        ),
    ],
    ids=[
        "toml",
        "no-format",
        "format-text",
        "format-bool",
        "unknown-table",
        "table-number",
        "table-not-array",
        "entry-number",
        "no-evidence",
        "unknown-field",
        "blank-evidence",
        "version-number",
        "twice",
        "stand-in-for-nothing",
        "specific-text",
        "fill-code",
        "no-names",
    ],
)
def test_a_malformed_corpus_file_fails_the_load(tmp_path, text, message):
    directory = _described(tmp_path, text)

    with pytest.raises(corpus.CorpusError, match=message):
        corpus.Corpus.load([directory])


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            '[[final_version]]\ndocument = "TS29.900"\nversion = "17.0.0"\n',
            r"\[\[final_version\]\] names TS29.900 V17.0.0, which the corpus lacks",
        ),
        (
            '[[cited_version]]\nciting = "TS29.999"\ncited = "TS29.900"\n'
            'version = "18.0.0"\n',
            "names TS29.999, which the corpus lacks",
        ),
        (
            '[[cited_as]]\ncited = "TS29.900"\ndocument = "TS29.900"\n',
            "TS29.900 is a document the corpus holds, not a misnaming",
        ),
        (
            '[[cited_as]]\ncited = "ETSI-TS283.034"\ndocument = "ETSI-ES283.034"\n',
            "names ETSI-ES283.034, which the corpus lacks",
        ),
        (
            '[[latest_edition]]\nciting = "TS29.900"\ncited = "TS29.329"\n',
            r"\[\[latest_edition\]\] names TS29.329",
        ),
        (
            '[[release_stand_in]]\nciting = "TS29.900"\nciting_version = "18.0.0"\n'
            'cited = "TS29.900"\nmeant = "17.0.0"\nversion = "19.0.0"\n',
            r"\[\[release_stand_in\]\] names TS29.900 V19.0.0",
        ),
        (
            '[[release_fill]]\nciting = "TS29.900"\nciting_version = "18.0.0"\n'
            'cited = "TS29.900"\nmeant = "17.0.0"\nversion = "18.0.0"\n'
            'names = ["Thing"]\nfields = ["data_type"]\n',
            r"\[\[release_fill\]\] names TS29.900 V17.0.0",
        ),
        (
            '[[cited_revision]]\nciting = "TS29.900"\ncited = "TS29.900"\n'
            'revision = "B"\n[[stand_in]]\nciting = "TS29.900"\n'
            'cited = "TS29.900"\nrevision = "0"\nversion = "18.0.0"\n',
            r"\[\[stand_in\]\] names TS29.900 revision 0 V18.0.0",
        ),
    ],
    ids=[
        "final-version",
        "citing",
        "cited-as-held",
        "cited-as-target",
        "latest-edition",
        "release-stand-in",
        "release-fill-meant",
        "stand-in-revision",
    ],
)
def test_an_entry_naming_what_the_corpus_lacks_fails_the_load(tmp_path, entry, message):
    """An entry answering no citation is stale, as a hole record's entry is:
    the rules describe the corpus beside them."""
    text = "format = 1\n" + entry.replace("\n[[", '\nevidence = "x"\n[[') + _ENTRY
    directory = _described(tmp_path, text)

    with pytest.raises(corpus.CorpusError, match=message):
        corpus.Corpus.load([directory])
    # Taken as given, the same rules are not checked.
    rules = corpus.Rules.load(directory / corpus.CORPUS_FILE)
    assert corpus.Corpus([], rules=rules).rules is rules


def test_the_installed_corpus_is_the_workspace_copy_here():
    assert corpus.installed_directory() == _CORPUS_DIR
    assert seanchai_corpus.CORPUS_DIR == _CORPUS_DIR


def test_installed_loads_as_load_loads_its_directory():
    installed = corpus.Corpus.installed()
    loaded = corpus.Corpus.load([_CORPUS_DIR])

    assert [entry.path for entry in installed] == [entry.path for entry in loaded]
    assert installed.record == loaded.record is not None
    assert not any(entry.path.name.endswith(".raw.dad") for entry in installed)


def test_installed_raw_is_the_raw_mirror_and_has_no_record():
    raw = corpus.Corpus.installed(raw=True)

    assert raw.record is None
    assert all(entry.path.name.endswith(".raw.dad") for entry in raw)
    assert len(raw) == len(corpus.Corpus.installed())


def test_installed_without_the_package_names_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "seanchai_corpus", None)

    with pytest.raises(corpus.CorpusNotInstalledError, match="seanchai-corpus"):
        corpus.Corpus.installed()


def test_load_takes_one_path_as_a_path_or_a_string():
    rfc = _CORPUS_DIR / "rfc" / "rfc6733.dad"

    for given in (rfc, str(rfc), [str(rfc)], (rfc,)):
        assert [entry.reference for entry in corpus.Corpus.load(given)] == ["RFC6733"]


@pytest.mark.parametrize(
    ("given", "says"),
    [
        (Path("/nonexistent/corpus"), "no such file"),
        ("/nonexistent/corpus", "no such file"),
        ([Path("/nonexistent/corpus")], "no such file"),
        (None, "a path or a list of paths"),
        (7, "a path or a list of paths"),
        ([7], "a path or a list of paths"),
    ],
)
def test_load_refuses_what_is_no_corpus_with_its_own_error(given, says):
    with pytest.raises(corpus.CorpusError, match=says):
        corpus.Corpus.load(given)


@pytest.mark.parametrize(
    "error",
    [
        corpus.CorpusError,
        corpus.CorpusNotInstalledError,
        model.ModelError,
        model.IncompleteCorpusError,
        model.StaleHoleRecordError,
        oracle.OracleError,
        abnf.AbnfError,
        ast.SpecRefError,
        corrections.CorrectionError,
        parser.DadParseError,
        errors.ExtractionError,
        sources.PatchError,
        sources.QuirkError,
        DownloadError,
        ManifestError,
    ],
)
def test_every_error_shares_one_base(error):
    assert issubclass(error, seanchai.SeanchaiError)


def test_an_installed_corpus_knows_its_version_and_a_loaded_one_does_not():
    assert corpus.Corpus.installed().version == seanchai_corpus.__version__
    assert corpus.Corpus.installed(raw=True).version == seanchai_corpus.__version__
    assert corpus.Corpus.load(_CORPUS_DIR).version is None


def test_the_library_knows_its_version():
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text("utf-8"))

    assert seanchai.__version__ == pyproject["project"]["version"]
