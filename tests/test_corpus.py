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
