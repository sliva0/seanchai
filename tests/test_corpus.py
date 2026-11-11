"""Loading a corpus, its rules and record, and choosing the copy a citation
means (docs/consumers.md, "Resolution across releases").

The committed corpus shows each rule through the model (`test_model.py`).
The fixture corpora here hold the copies it lacks, to show which copy does
not answer.
"""

import importlib
import pkgutil
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
import seanchai_corpus
from conftest import _CORPUS_DIR, _ROOT, _RULES

import seanchai
from seanchai import corpus
from seanchai.dad import ast, formatter


def _spec(specification, version) -> ast.Specification:
    return ast.Specification(
        specification=specification,
        version=version,
        vendor_id=10415,
        sections=(
            ast.GroupedAvp(
                name="Example",
                source=ast.SourceRef(section="6.1"),
                code=700,
                vendor_id=10415,
                avps=(),
            ),
        ),
    )


def _entry(specification, version) -> corpus.Entry:
    return corpus.Entry(
        path=Path(f"{specification}-{version}.dad"), spec=_spec(specification, version)
    )


def _books(*entries: corpus.Entry, rules=_RULES) -> corpus.Corpus:
    """A fixture corpus, resolving by the committed corpus's rules."""
    return corpus.Corpus(entries, rules=rules)


def _held(specification, *versions) -> corpus.Corpus:
    return _books(*(_entry(specification, version) for version in versions))


def _without(table, key) -> corpus.Rules:
    """The committed rules lacking one entry of `table`."""
    entries = getattr(_RULES, table)
    assert key in entries
    return replace(_RULES, **{table: {k: v for k, v in entries.items() if k != key}})


def _tgpp2(revision, version="2.0") -> corpus.Entry:
    url = f"http://example.test/X.S0057-{revision}_v{version}_091215.pdf"
    spec = _spec("3GPP2 X.S0057", version).model_copy(update={"transcribed": url})
    return corpus.Entry(path=Path(f"xs0057-{revision}.dad"), spec=spec)


# --- resolution --------------------------------------------------------------


def test_the_newest_copy_in_the_citing_major_version_answers():
    """By version number, 18.10.0 above 18.2.0; and a release boundary is
    where 3GPP may change what an AVP means, so a Release 19 copy answers no
    Release 18 citation."""
    books = _held("3GPP TS 29.272", "17.9.0", "18.1.0", "18.10.0", "18.2.0", "19.0.0")

    found = books.resolve("TS29.272", like=_spec("3GPP TS 29.388", "18.0.0"))

    assert found is not None and found.spec.version == "18.10.0"
    later = _held("3GPP TS 29.272", "19.0.0")
    assert later.resolve("TS29.272", like=_spec("3GPP TS 29.388", "18.1.0")) is None
    assert _books().resolve("TS29.272", like=_spec("3GPP TS 29.388", "18.1.0")) is None
    assert _books().versions("TS29.272") == []
    # An RFC has no release of its own to match.
    found = books.resolve("TS29.272", like=_spec("RFC 9999", None))
    assert found is not None and found.spec.version == "19.0.0"


def test_a_3gpp_citation_of_another_publishers_document_reads_any_copy():
    """TS 32.299 cites oneM2M TS-0004 [301] and TS 29.212 cites 3GPP2
    X.S0057 by no version the corpus could match; ETSI's "TS 283 034" is the
    ES 283 034 its publisher numbers it (`cited_as`)."""
    books = corpus.Corpus.installed()

    onem2m = books.resolve("oneM2M-TS-0004", like=_spec("3GPP TS 32.299", "18.0.0"))
    tgpp2 = books.resolve("3GPP2-X.S0057", like=_spec("3GPP TS 29.212", "18.2.0"))
    misnamed = books.resolve("ETSI-TS283.034", like=_spec("3GPP TS 29.212", "18.2.0"))

    assert onem2m is not None and onem2m.spec.version == "2.35.0"
    assert tgpp2 is not None and (tgpp2.spec.version, corpus.revision(tgpp2.spec)) == (
        "2.0",
        "0",
    )
    assert misnamed is not None and misnamed.reference == "ETSI-ES283.034"
    assert books.versions("ETSI-TS283.034") == books.versions("ETSI-ES283.034")


def test_a_specific_reference_means_the_version_it_names_and_no_other():
    """TS 183 017 V3.2.1 clause 2 [19] names "3GPP TS 29.214 Release 7",
    whose last version is V7.12.0: neither the Release 18 copy nor another
    Release 7 version answers. An IETF document's citation is unaffected."""
    citing = _spec("ETSI TS 183 017", "3.2.1")
    books = _held("3GPP TS 29.214", "7.11.0", "7.12.0", "18.4.0")

    entry, across = books.resolution("TS29.214", like=citing)

    assert entry is not None and entry.spec.version == "7.12.0"
    assert across == corpus.CrossRelease(
        "ETSI-TS183.017", "TS29.214", "7.12.0", corpus.CitationRule.SPECIFIC
    )
    lacking = _held("3GPP TS 29.214", "7.11.0", "18.4.0")
    assert lacking.resolution("TS29.214", like=citing) == (None, None)
    assert _held("RFC 4005", None).resolve("RFC4005", like=citing) is not None


def test_an_entry_answers_only_for_the_citing_copy_it_names():
    """A references clause changes between versions, so two copies of one
    document can mean two versions. The corpus holds one copy of ETSI TS
    183 017, so a fixture shows the second."""
    rules = corpus.Rules(
        cited_versions={
            ("ETSI-TS183.017", "3.1.1", "TS29.214"): "6.11.0",
            ("ETSI-TS183.017", "3.2.1", "TS29.214"): "7.12.0",
        }
    )
    books = _books(
        *(_entry("3GPP TS 29.214", v) for v in ("6.11.0", "7.12.0")), rules=rules
    )

    for version, named in (("3.1.1", "6.11.0"), ("3.2.1", "7.12.0")):
        found = books.resolve("TS29.214", like=_spec("ETSI TS 183 017", version))
        assert found is not None and found.spec.version == named
    assert books.resolve("TS29.214", like=_spec("ETSI TS 183 017", "3.3.1")) is None


def test_a_non_specific_reference_past_the_documents_end_means_its_final_version():
    """TS 29.140 ended at V7.0.0 (`final_version`): TS 32.299 V18.0.0's
    non-specific citation means V7.0.0, not an earlier Release 7 copy; an
    ETSI document's latest version is that one too. A Release 6 citation
    means Release 6's latest, which the corpus lacks, and Release 7's own
    crosses nothing. A document that has not ended is never read so."""
    books = _held("3GPP TS 29.140", "6.4.0", "7.0.0")

    entry, across = books.resolution("TS29.140", like=_spec("3GPP TS 32.299", "18.0.0"))

    assert entry is not None and entry.spec.version == "7.0.0"
    assert across is not None and across.rule is corpus.CitationRule.NON_SPECIFIC
    assert books.resolve("TS29.140", like=_spec("ETSI ES 283 034", "2.2.0")) is not None
    final = _held("3GPP TS 29.140", "7.0.0")
    assert final.resolve("TS29.140", like=_spec("3GPP TS 32.299", "6.12.0")) is None
    assert (
        final.resolution("TS29.140", like=_spec("3GPP TS 32.299", "7.9.0"))[1] is None
    )
    earlier = _held("3GPP TS 29.140", "6.4.0")
    assert earlier.resolve("TS29.140", like=_spec("3GPP TS 32.299", "18.0.0")) is None
    alive = _held("3GPP TS 29.229", "18.1.0")
    assert alive.resolve("TS29.229", like=_spec("ETSI ES 283 034", "2.2.0")) is None


def test_a_clause_saying_the_latest_edition_applies_reads_the_newest_copy():
    """ES 283 035 clause 2.1: "For non-specific references, the latest
    edition of the referenced document (including any amendments) applies".
    Nothing says so for ETSI TS 183 066."""
    books = _held("3GPP TS 29.329", "18.0.0", "11.0.0")

    entry, across = books.resolution("TS29.329", like=_spec("ETSI ES 283 035", "2.5.1"))

    assert entry is not None and entry.spec.version == "18.0.0"
    assert across == corpus.CrossRelease(
        "ETSI-ES283.035", "TS29.329", "18.0.0", corpus.CitationRule.LATEST_EDITION
    )
    other = _spec("ETSI TS 183 066", "2.1.1")
    assert books.resolution("TS29.329", like=other) == (None, None)


def test_a_cited_3gpp2_revision_is_that_revision_or_the_stand_in_its_entry_names():
    """TS 29.212 V19.1.0 [24] names X.S0057 revision B, which the corpus
    lacks: a copy of B would answer unreported, ahead of revision 0, which
    answers only by its `stand_in` entry and only at the version it names. A
    version holds two revisions apart."""
    citing = _spec("3GPP TS 29.212", "19.1.0")
    standing = _books(_tgpp2("0"))

    held = _books(_tgpp2("0"), _tgpp2("B", "1.0")).resolution(
        "3GPP2-X.S0057", like=citing
    )
    entry, across = standing.resolution("3GPP2-X.S0057", like=citing)

    assert held[0] is not None and corpus.revision(held[0].spec) == "B"
    assert held[1] is None
    assert entry is not None and corpus.revision(entry.spec) == "0"
    assert across == corpus.CrossRelease(
        "TS29.212",
        "3GPP2-X.S0057",
        "2.0",
        corpus.CitationRule.STAND_IN,
        cited_revision="B",
        revision="0",
    )
    assert _books(_tgpp2("0", "1.0")).resolution("3GPP2-X.S0057", like=citing) == (
        None,
        None,
    )
    standing.rules = _without("stand_ins", ("TS29.212", "19.1.0", "3GPP2-X.S0057"))
    assert standing.resolution("3GPP2-X.S0057", like=citing) == (None, None)
    # A citation naming no revision takes the copy the corpus holds.
    assert standing.resolve("3GPP2-X.S0057", like=_spec("3GPP TS 29.999", "18.0.0"))
    assert len(_books(_tgpp2("0"), _tgpp2("B"))) == 2


@pytest.mark.parametrize(
    ("citing", "reference", "meant", "specific"),
    [
        # Non-specific, meaning V11.5.0, Release 11's last.
        (_spec("3GPP TS 32.299", "11.20.0"), "TS32.299", "11.5.0", False),
        # TS 183 033 clause 2.1 [2] names V6.6.0, no release's last.
        (_spec("ETSI TS 183 033", "1.2.0"), "ETSI-TS183.033", "6.6.0", True),
    ],
    ids=["non-specific", "specific"],
)
def test_a_later_release_stands_in_only_by_its_entry(
    citing, reference, meant, specific
):
    """TS 29.229 V19.1.0 defines alike what each citation means, by its
    `release_stand_in` entry's evidence; another held version gets nothing,
    and nor does V19.1.0 without the entry."""
    books = _held("3GPP TS 29.229", "19.1.0")
    key = (reference, citing.version, "TS29.229")

    entry, across = books.resolution("TS29.229", like=citing)

    assert entry is not None and entry.spec.version == "19.1.0"
    assert across == corpus.CrossRelease(
        reference,
        "TS29.229",
        "19.1.0",
        corpus.CitationRule.STAND_IN,
        meant=meant,
        specific=specific,
    )
    other = _held("3GPP TS 29.229", "18.2.0")
    assert other.resolution("TS29.229", like=citing) == (None, None)
    books.rules = _without("release_stand_ins", key)
    assert books.resolution("TS29.229", like=citing) == (None, None)


def test_a_later_release_states_a_field_only_by_its_entry():
    """TS 29.210 V6.7.0's TS 29.061 is V6.15.0, which still answers; its
    `release_fill` entry lets V19.1.0 state the type. Another copy of the
    citing document, or a corpus lacking V19.1.0, gets nothing, and without
    the entry nor does V6.7.0."""
    citing = _spec("3GPP TS 29.210", "6.7.0")
    books = _held("3GPP TS 29.061", "6.15.0", "19.1.0")

    entry, across = books.resolution("TS29.061", like=citing)
    found = books.release_fill("TS29.061", like=citing)

    assert entry is not None and entry.spec.version == "6.15.0"
    assert across is None
    assert found is not None
    later, fill, crossing = found
    assert (later.spec.version, fill.fields) == ("19.1.0", ("data_type",))
    assert crossing == corpus.CrossRelease(
        "TS29.210",
        "TS29.061",
        "19.1.0",
        corpus.CitationRule.LATER_RELEASE,
        meant="6.15.0",
    )
    assert books.release_fill("TS29.061", like=_spec("3GPP TS 29.210", "6.6.0")) is None
    assert (
        _held("3GPP TS 29.061", "6.15.0").release_fill("TS29.061", like=citing) is None
    )
    books.rules = _without("release_fills", ("TS29.210", "6.7.0", "TS29.061"))
    assert books.release_fill("TS29.061", like=citing) is None


_RULE = corpus.CitationRule


@pytest.mark.parametrize(
    ("crossing", "says"),
    [
        (corpus.CrossRelease("a", "b", "7.0.0", _RULE.SPECIFIC), "cited_version"),
        (corpus.CrossRelease("a", "b", "7.0.0", _RULE.NON_SPECIFIC), "final_version"),
        (
            corpus.CrossRelease("a", "b", "7.0.0", _RULE.LATEST_EDITION),
            "latest_edition",
        ),
        (
            corpus.CrossRelease(
                "a", "b", "2.0", _RULE.STAND_IN, cited_revision="B", revision="0"
            ),
            "revision 0 V2.0 stands in (corpus.toml, stand_in)",
        ),
        (
            corpus.CrossRelease("a", "b", "19.1.0", _RULE.STAND_IN, meant="11.5.0"),
            "non-specifically, meaning V11.5.0",
        ),
        (
            corpus.CrossRelease(
                "a", "b", "19.1.0", _RULE.STAND_IN, meant="6.6.0", specific=True
            ),
            "naming V6.6.0, which the corpus lacks: V19.1.0 stands in"
            " (corpus.toml, release_stand_in)",
        ),
        (
            corpus.CrossRelease(
                "a", "b", "19.1.0", _RULE.LATER_RELEASE, meant="6.15.0"
            ),
            "V19.1.0 states it (corpus.toml, release_fill)",
        ),
    ],
    ids=str,
)
def test_a_crossing_says_which_corpus_toml_entry_allowed_it(crossing, says):
    assert str(crossing).startswith("a cites b")
    assert says in str(crossing)


def test_the_rules_name_only_versions_the_catalog_pins_and_verifies():
    """A specific reference's version and a final version are the catalog's
    pins, which every download checks against the 3GPP archive (`final`):
    a version the corpus could not be shown to hold is never claimed."""
    from seanchai.downloader import load_catalog

    pinned = {
        (f"TS{pin.number}", pin.version): pin.final for pin in load_catalog().pinned
    }

    for document, version in _RULES.final_versions.items():
        assert pinned.get((document, version)) == "document", document
    for (_, _, cited), version in _RULES.cited_versions.items():
        assert (cited, version) in pinned


# --- loading -----------------------------------------------------------------

_RECORDED = """
[[hole]]
document = "TS29.900"
name = "Thing"
missing = ["data_type", "flag_rules"]
reason = "clause 6.3.1 states no type"
"""
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


def _corpus_directory(
    tmp_path, record: str | None = _RECORDED, rules: str | None = None
) -> Path:
    directory = tmp_path / "dad"
    (directory / "3gpp").mkdir(parents=True)
    (directory / "3gpp" / "29900.dad").write_text(
        formatter.format_spec(_spec("3GPP TS 29.900", "18.0.0")), encoding="utf-8"
    )
    if record is not None:
        (directory / corpus.HOLE_RECORD).write_text(record, encoding="utf-8")
    if rules is not None:
        (directory / corpus.CORPUS_FILE).write_text(rules, encoding="utf-8")
    return directory


def test_load_reads_a_directory_tree_and_its_raw_mirror_apart(tmp_path):
    directory = _corpus_directory(tmp_path)
    text = formatter.format_spec(_spec("3GPP TS 29.900", "18.0.0"))
    (directory / "3gpp" / "29900.raw.dad").write_text(text, encoding="utf-8")

    corrected = corpus.Corpus.load([directory])
    raw = corpus.Corpus.load([directory], raw=True)

    assert [entry.path.name for entry in corrected] == ["29900.dad"]
    assert [entry.path.name for entry in raw] == ["29900.raw.dad"]


def test_a_whole_corrected_corpus_directory_brings_its_record(tmp_path):
    """A subdirectory or a file list is partial, and raw files are not what
    the record describes. The reason is prose; its whitespace collapses."""
    directory = _corpus_directory(
        tmp_path,
        _RECORDED.replace(
            '"clause 6.3.1 states no type"',
            '"""\n    clause 6.3.1\n    states   no type\n    """',
        ),
    )

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
    assert corpus.Corpus.load([directory / "3gpp"]).record is None
    assert corpus.Corpus.load([directory / "3gpp" / "29900.dad"]).record is None
    assert corpus.Corpus.load([directory], raw=True).record is None
    bare = _corpus_directory(tmp_path / "bare", None)
    assert corpus.Corpus.load([bare]).record is None


def test_a_corpus_directory_brings_its_rules_raw_mirror_included(tmp_path):
    """Unlike the record, the rules answer raw files too: a raw From cell is
    what `cited_as` exists for. Without the file, or for part of a corpus,
    the rules are empty and state no format."""
    directory = _corpus_directory(tmp_path, rules=_DESCRIBED)
    (directory / "3gpp" / "29900.raw.dad").write_text(
        formatter.format_spec(_spec("3GPP TS 29.900", "18.0.0")), encoding="utf-8"
    )

    for raw in (False, True):
        assert corpus.Corpus.load([directory], raw=raw).rules == corpus.Rules(
            path=directory / "corpus.toml",
            format=1,
            final_versions={"TS29.900": "18.0.0"},
        )
    bare = corpus.Corpus.load([_corpus_directory(tmp_path / "bare")])
    assert bare.rules == corpus.Rules() and bare.rules.format is None
    assert corpus.Corpus.load([directory / "3gpp"]).rules == corpus.Rules()
    assert corpus.Corpus([]).rules == corpus.Rules()


def test_a_file_named_twice_counts_once(tmp_path):
    directory = _corpus_directory(tmp_path)
    (tmp_path / "link").symlink_to(directory / "3gpp")
    entry = _entry("3GPP TS 29.229", "18.1.0")

    books = corpus.Corpus.load(
        [directory, directory / "3gpp" / "..", tmp_path / "link" / "29900.dad"]
    )

    assert [entry.path for entry in books] == [directory / "3gpp" / "29900.dad"]
    assert books.record is not None
    assert len(_books(entry, entry)) == 1


@pytest.mark.parametrize(
    ("spec", "says"),
    [
        (_spec("3GPP TS 29.229", "18.1.0"), "TS29.229 18.1.0"),
        (_spec("RFC 6733", None), "are both RFC6733; give one copy"),
        # One 3GPP2 version may hold two revisions; one revision twice is
        # two copies.
        (_tgpp2("0").spec, "3GPP2-X.S0057 2.0"),
    ],
    ids=["3gpp", "rfc", "3gpp2"],
)
def test_two_files_of_one_copy_are_refused_naming_both(tmp_path, spec, says):
    one, two = tmp_path / "one.dad", tmp_path / "two.dad"
    for path in (one, two):
        path.write_text(formatter.format_spec(spec), encoding="utf-8")

    for paths in ([one, two], [two, one]):
        with pytest.raises(corpus.CorpusError) as raised:
            corpus.Corpus.load(paths)
        assert str(one) in str(raised.value) and str(two) in str(raised.value)
        assert says in str(raised.value)


@pytest.mark.parametrize(
    ("given", "says"),
    [
        (Path("/nonexistent/corpus"), "no such file"),
        ("/nonexistent/corpus", "no such file"),
        (None, "a path or a list of paths"),
        ([7], "a path or a list of paths"),
    ],
)
def test_load_refuses_what_is_no_corpus_with_its_own_error(given, says):
    with pytest.raises(corpus.CorpusError, match=says):
        corpus.Corpus.load(given)


def test_load_takes_one_path_as_a_path_or_a_string():
    rfc = _CORPUS_DIR / "rfc" / "rfc6733.dad"

    for given in (rfc, str(rfc), [str(rfc)], (rfc,)):
        assert [entry.reference for entry in corpus.Corpus.load(given)] == ["RFC6733"]


def test_a_vendor_extension_citing_a_document_reads_its_newest_copy():
    """A sidecar `supplied_from` reads names no supported document and no
    version, as an RFC names none."""
    books = _held("3GPP TS 29.229", "18.1.0", "19.1.0")

    found = books.resolve("TS29.229", like=_spec("ACME HSS dictionary", None))

    assert found is not None and found.spec.version == "19.1.0"


def test_load_names_the_file_it_could_not_parse(tmp_path):
    (tmp_path / "broken.dad").write_text("; Specification: nonsense\n", "utf-8")

    with pytest.raises(corpus.CorpusError, match=r"broken\.dad"):
        corpus.Corpus.load([tmp_path])


@pytest.mark.parametrize(
    ("record", "rules", "says"),
    [
        (_RECORDED, None, "two hole records"),
        (None, _DESCRIBED, "two corpus files"),
    ],
    ids=["record", "rules"],
)
def test_two_corpus_directories_in_one_load_are_refused(tmp_path, record, rules, says):
    one = _corpus_directory(tmp_path / "one", record, rules)
    two = _corpus_directory(tmp_path / "two", record, rules)

    with pytest.raises(corpus.CorpusError, match=says):
        corpus.Corpus.load([one, two])


@pytest.mark.parametrize("name", [corpus.CORPUS_FILE, corpus.HOLE_RECORD])
def test_an_unreadable_corpus_file_or_record_fails_the_load(tmp_path, name):
    """A file that is not UTF-8, or that cannot be read at all, is refused as
    a `CorpusError` naming it, as a file that is not TOML is."""
    path = _corpus_directory(tmp_path, rules=_DESCRIBED) / name
    load = corpus.Rules.load if name == corpus.CORPUS_FILE else corpus.HoleRecord.load
    path.write_bytes(b"\xff")

    with pytest.raises(corpus.CorpusError, match=f"{name}: 'utf-8' codec"):
        corpus.Corpus.load([path.parent])
    path.unlink()
    path.mkdir()
    with pytest.raises(corpus.CorpusError, match=f"{name}: .*Is a directory"):
        load(path)


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ("[[hole]\n", "holes.toml"),
        ('[[gap]]\nname = "Thing"\n', "only .*hole.* tables"),
        ('[hole]\nname = "Thing"\n', "only .*hole.* tables"),
        (_RECORDED + 'extra = "no"\n', "states exactly"),
        (_RECORDED.replace("clause 6.3.1 states no type", " "), "non-empty"),
        (_RECORDED.replace('["data_type", "flag_rules"]', "[]"), "non-empty"),
        (
            _RECORDED.replace('"data_type"', '"type"'),
            "missing holds type, which is not",
        ),
        (_RECORDED + _RECORDED, "TS29.900 Thing is listed twice"),
    ],
    ids=[
        "toml",
        "another-table",
        "not-an-array",
        "unknown-field",
        "blank-reason",
        "nothing-missing",
        "no-such-field",
        "twice",
    ],
)
def test_a_malformed_record_fails_the_load(tmp_path, record, message):
    with pytest.raises(corpus.CorpusError, match=message):
        corpus.Corpus.load([_corpus_directory(tmp_path, record)])


_FILL = (
    '[[release_fill]]\ncited = "TS29.900"\nciting = "TS29.900"\n'
    'citing_version = "18.0.0"\nmeant = "17.0.0"\nversion = "18.0.0"\n'
    'names = ["Thing"]\nfields = ["data_type"]\nevidence = "x"\n'
)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("format = [\n", "corpus.toml"),
        ('format = "1"\n', "states no corpus format"),
        ("format = true\n", "states no corpus format"),
        ("format = 1\n[[stand_ins]]\n", "stand_ins: not a table"),
        ("format = 1\n[final_version]\n", r"must be \[\[final_version\]\]"),
        (
            'format = 1\n[[final_version]]\ndocument = "TS29.900"\n'
            'version = "18.0.0"\n',
            "states document, evidence, version",
        ),
        (
            'format = 1\n[[final_version]]\ndocument = "TS29.900"\nversion = 18\n'
            'evidence = "x"\n',
            "version must be non-empty text",
        ),
        (
            "format = 1\n"
            + _FILL.replace('citing_version = "18.0.0"', "citing_version = 18"),
            'citing_version must be a version, or "" for a document without one',
        ),
        (
            "format = 1\n"
            + _FILL.replace('fields = ["data_type"]', 'fields = ["code"]'),
            "fields must be a non-empty list of distinct names of data_type",
        ),
        (
            "format = 1\n"
            + _FILL.replace("[[release_fill]]", "[[release_stand_in]]").replace(
                'names = ["Thing"]\nfields = ["data_type"]\n', 'specific = "yes"\n'
            ),
            "specific must be true or false",
        ),
        (
            "format = 1\n" + _FILL * 2,
            r"\[\[release_fill\]\] TS29.900 18.0.0 TS29.900 is stated twice",
        ),
        (
            'format = 1\n[[stand_in]]\ncited = "TS29.900"\nciting = "TS29.900"\n'
            'citing_version = "18.0.0"\nrevision = "0"\nversion = "18.0.0"\n'
            'evidence = "x"\n',
            r"no \[\[cited_revision\]\] of that citing copy names the revision",
        ),
    ],
    ids=[
        "toml",
        "format-text",
        "format-bool",
        "unknown-table",
        "not-an-array",
        "missing-field",
        "not-text",
        "citing-version",
        "unfillable-field",
        "not-a-flag",
        "twice",
        "stand-in-for-nothing",
    ],
)
def test_a_malformed_corpus_file_fails_the_load(tmp_path, text, message):
    with pytest.raises(corpus.CorpusError, match=message):
        corpus.Corpus.load([_corpus_directory(tmp_path, rules=text)])


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (
            '[[cited_as]]\ncited = "TS29.900"\ndocument = "TS29.900"\n',
            "TS29.900 is a document the corpus holds, not a misnaming",
        ),
        (
            '[[cited_as]]\ncited = "ETSI-TS283.034"\ndocument = "ETSI-ES283.034"\n',
            "names ETSI-ES283.034, which the corpus lacks",
        ),
        (
            '[[final_version]]\ndocument = "TS29.900"\nversion = "17.0.0"\n',
            r"\[\[final_version\]\] names TS29.900 V17.0.0, which the corpus lacks",
        ),
        (
            '[[latest_edition]]\nciting = "TS29.900"\nciting_version = "17.0.0"\n'
            'cited = "TS29.900"\n',
            r"\[\[latest_edition\]\] names TS29.900 V17.0.0, which the corpus lacks",
        ),
        (
            # An RFC's citations are keyed by "", which matches no versioned
            # copy.
            '[[cited_version]]\nciting = "TS29.900"\nciting_version = ""\n'
            'cited = "TS29.900"\nversion = "18.0.0"\n',
            r"\[\[cited_version\]\] names TS29.900, which the corpus lacks",
        ),
        (
            '[[release_fill]]\nciting = "TS29.900"\nciting_version = "18.0.0"\n'
            'cited = "TS29.900"\nmeant = "17.0.0"\nversion = "18.0.0"\n'
            'names = ["Thing"]\nfields = ["data_type"]\n',
            r"\[\[release_fill\]\] names TS29.900 V17.0.0",
        ),
        (
            '[[cited_revision]]\nciting = "TS29.900"\nciting_version = "18.0.0"\n'
            'cited = "TS29.900"\nrevision = "B"\n[[stand_in]]\n'
            'citing = "TS29.900"\nciting_version = "18.0.0"\ncited = "TS29.900"\n'
            'revision = "0"\nversion = "18.0.0"\n',
            r"\[\[stand_in\]\] names TS29.900 revision 0 V18.0.0",
        ),
    ],
    ids=[
        "cited-as-held",
        "cited-as-target",
        "final-version",
        "citing-copy",
        "versionless-citing-copy",
        "cited-version",
        "stand-in-revision",
    ],
)
def test_an_entry_naming_what_the_corpus_lacks_fails_the_load(tmp_path, entry, message):
    """An entry answering no citation is stale, as a hole record's entry is:
    the rules describe the corpus beside them. Taken as given, they are not
    checked."""
    text = "format = 1\n" + entry.replace("\n[[", '\nevidence = "x"\n[[')
    directory = _corpus_directory(tmp_path, rules=text + 'evidence = "x"\n')

    with pytest.raises(corpus.CorpusError, match=message):
        corpus.Corpus.load([directory])
    rules = corpus.Rules.load(directory / corpus.CORPUS_FILE)
    assert corpus.Corpus([], rules=rules).rules is rules


def test_a_rule_keyed_by_no_version_answers_the_version_less_copy(tmp_path):
    directory = _corpus_directory(
        tmp_path,
        rules='format = 1\n[[cited_version]]\nciting = "RFC9999"\nciting_version = ""\n'
        'cited = "TS29.900"\nversion = "18.0.0"\nevidence = "x"\n',
    )
    (directory / "rfc9999.dad").write_text(
        formatter.format_spec(_spec("RFC 9999", None)), encoding="utf-8"
    )

    books = corpus.Corpus.load([directory])

    assert books.rules.cited_versions == {("RFC9999", "", "TS29.900"): "18.0.0"}
    assert books.resolve("TS29.900", like=_spec("RFC 9999", None)) is not None


# --- formats -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("found", "upgrade"), [(2, "upgrade seanchai$"), (0, "upgrade seanchai-corpus$")]
)
def test_a_corpus_of_another_format_names_the_package_to_upgrade(
    tmp_path, found, upgrade
):
    """The format is read before any `.dad` file, so a newer grammar the
    library cannot parse is refused as a format, not as a parse error."""
    directory = _corpus_directory(
        tmp_path, rules=_DESCRIBED.replace("format = 1", f"format = {found}")
    )
    (directory / "newer.dad").write_text("; Specification: nonsense\n", "utf-8")

    for raw in (False, True):
        with pytest.raises(corpus.CorpusFormatError, match=upgrade) as raised:
            corpus.Corpus.load([directory], raw=raw)
        assert (raised.value.found, raised.value.reads) == (found, corpus.FORMATS)
        assert f"the corpus is format {found}" in str(raised.value)
        assert f"seanchai {seanchai.__version__} reads format 1" in str(raised.value)
        assert str(directory / "corpus.toml") in str(raised.value)


def test_installed_refuses_a_corpus_of_a_format_the_library_does_not_read(
    monkeypatch,
):
    assert corpus.Corpus.installed().rules.format in corpus.FORMATS
    monkeypatch.setattr(corpus, "FORMATS", (2,))

    with pytest.raises(corpus.CorpusFormatError, match=r"upgrade seanchai-corpus$"):
        corpus.Corpus.installed()
    with pytest.raises(corpus.CorpusFormatError):
        corpus.Corpus.installed(raw=True)


# --- the installed corpus ----------------------------------------------------


def test_installed_is_the_workspace_corpus_loaded_with_its_version():
    installed = corpus.Corpus.installed()
    loaded = corpus.Corpus.load([_CORPUS_DIR])
    raw = corpus.Corpus.installed(raw=True)

    assert corpus.installed_directory() == seanchai_corpus.CORPUS_DIR == _CORPUS_DIR
    assert [entry.path for entry in installed] == [entry.path for entry in loaded]
    assert installed.record == loaded.record is not None
    assert installed.version == raw.version == seanchai_corpus.__version__
    assert loaded.version is None
    assert raw.record is None and len(raw) == len(installed)
    assert all(entry.path.name.endswith(".raw.dad") for entry in raw)


def test_installed_without_the_package_names_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "seanchai_corpus", None)

    with pytest.raises(corpus.CorpusNotInstalledError, match="seanchai-corpus"):
        corpus.Corpus.installed()


def test_the_library_knows_its_version():
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text("utf-8"))

    assert seanchai.__version__ == pyproject["project"]["version"]


def _modules():
    for found in pkgutil.walk_packages(seanchai.__path__, "seanchai."):
        yield importlib.import_module(found.name)


def test_every_error_the_library_defines_derives_from_seanchai_error():
    errors = {
        each
        for module in _modules()
        for each in vars(module).values()
        if isinstance(each, type)
        and issubclass(each, Exception)
        and each.__module__ == module.__name__
    }

    assert seanchai.SeanchaiError in errors and len(errors) > 10
    assert {e for e in errors if not issubclass(e, seanchai.SeanchaiError)} == set()
