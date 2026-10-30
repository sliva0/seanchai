"""Widening stale ranges rewrites the bounds and nothing else.

Synthetic edit files carry what a real one does around a range — comments,
a comprehension sharing one literal, non-ASCII reason text — so a rewrite
that reflowed or re-encoded anything shows up as a byte difference. The
TS 29.272 18.6.0 → 18.7.0 upgrade, widened by hand, is what this replaces.
"""

import tomllib
from pathlib import Path

import pytest

from seanchai import ranges
from seanchai.dad import corrections
from seanchai.versions import VersionRange

_EDITS = Path(__file__).parent.parent / "edits"

_TOML = """\
# Source declarations for 3GPP TS 29.999.

[[patch]]
find = "M. V"   # the cell as printed
replace = "M, V"
reason = "flags cell typo"
first_version = "18.6.0"
last_version = "18.6.0"

[[patch]]
find = "Enumerate"
replace = "Enumerated"
reason = "already reviewed"
first_version = "18.0.0"

[[quirk]]
name = "prose-avp-codes"
reason = "the AVP tables print no Code column"
last_version = "18.6.0"
"""


def test_a_source_declaration_keeps_everything_but_the_moved_bound(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text(_TOML, encoding="utf-8")

    expansion = ranges.expand_sources(path, "18.7.0")

    assert path.read_text(encoding="utf-8") == _TOML.replace(
        'last_version = "18.6.0"', 'last_version = "18.7.0"'
    )
    assert expansion.widened == [
        "TS29.999.toml: input patch 'M. V' 18.6.0 -> 18.6.0..18.7.0",
        "TS29.999.toml: quirk 'prose-avp-codes' *..18.6.0 -> *..18.7.0",
    ]
    assert expansion.remaining == []


def test_an_older_version_moves_the_first_bound(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text(_TOML, encoding="utf-8")

    expansion = ranges.expand_sources(path, "17.9.0")

    text = path.read_text(encoding="utf-8")
    assert text.count('first_version = "17.9.0"') == 2
    assert 'last_version = "18.6.0"' in text
    assert len(expansion.widened) == 2


def test_a_covered_version_leaves_the_file_untouched(tmp_path):
    path = tmp_path / "TS29.999.toml"
    path.write_text(_TOML, encoding="utf-8")
    before = path.stat().st_mtime_ns

    assert ranges.expand_sources(path, "18.6.0") == ranges.Expansion([], [])
    assert path.stat().st_mtime_ns == before


_PYTHON = """\
\"\"\"Corrections for 3GPP TS 29.999.\"\"\"

from seanchai.dad.corrections import Correction, definition, table_row
from seanchai.versions import VersionRange

CORRECTIONS = [
    # Comments and layout survive: only the literal changes.
    Correction(
        id="area-scope-code",
        target=definition("Area-Scope"),
        field="code",
        expect=1607,
        replace=1624,
        reason="clause 7.3.138 — the header prints Job-Type's code", versions='18.6.0',
    ),
    Correction(
        id="reviewed",
        target=definition("Other"),
        field="code",
        expect=1,
        replace=2,
        reason="already covers the version",
        versions="18.0.0..*",
    ),
]
CORRECTIONS += [
    Correction(
        id=f"{name.lower()}-type",
        target=table_row(name),
        field="data_type",
        expect=None,
        replace="Unsigned32",
        reason="one literal for every declaration the loop builds",
        versions="18.6.0",
    )
    for name in ("First", "Second")
]
"""


def test_a_corrections_literal_is_replaced_in_place(tmp_path):
    path = tmp_path / "TS29.999.py"
    path.write_text(_PYTHON, encoding="utf-8")

    expansion = ranges.expand_corrections(tmp_path, "3GPP TS 29.999", "18.7.0")

    assert path.read_text(encoding="utf-8") == _PYTHON.replace(
        "versions='18.6.0'", "versions='18.6.0..18.7.0'"
    ).replace('versions="18.6.0"', 'versions="18.6.0..18.7.0"')
    assert expansion.widened == [
        "TS29.999.py:14: versions 18.6.0 -> 18.6.0..18.7.0",
        "TS29.999.py:34: versions 18.6.0 -> 18.6.0..18.7.0",
    ]
    assert expansion.remaining == []


_ACCEPTANCE = (
    "from seanchai.dad.corrections import Accept, definition\n"
    "CORRECTIONS = [Accept(id='a', rule='reused-body-differs',"
    " target=definition('A'), expect='m', reason='r', versions='18.6.0')]\n"
)


def test_a_matching_acceptance_literal_is_widened_like_a_correction(tmp_path):
    path = tmp_path / "TS29.999.py"
    path.write_text(_ACCEPTANCE, encoding="utf-8")

    expansion = ranges.expand_corrections(
        tmp_path, "3GPP TS 29.999", "18.7.0", accepted={"TS29.999.py#a"}
    )

    assert path.read_text(encoding="utf-8") == _ACCEPTANCE.replace(
        "versions='18.6.0'", "versions='18.6.0..18.7.0'"
    )
    assert expansion.remaining == expansion.stale == []


def test_an_acceptance_matching_no_finding_is_reported_stale_not_widened(tmp_path):
    """A clean rebuild checks no acceptance: widening one the caller did not
    find matching would carry a stale acknowledgement to the new version."""
    path = tmp_path / "TS29.999.py"
    path.write_text(_ACCEPTANCE, encoding="utf-8")

    expansion = ranges.expand_corrections(tmp_path, "3GPP TS 29.999", "18.7.0")

    assert path.read_text(encoding="utf-8") == _ACCEPTANCE
    assert expansion.widened == expansion.remaining == []
    assert expansion.stale == [
        "TS29.999.py:2: versions 18.6.0: acceptance TS29.999.py#a matches no finding"
    ]


def test_a_range_built_by_an_expression_is_left_for_a_person(tmp_path):
    path = tmp_path / "TS29.999.py"
    text = _PYTHON.replace("versions='18.6.0'", 'versions=VersionRange.exact("18.6.0")')
    path.write_text(text, encoding="utf-8")

    expansion = ranges.expand_corrections(tmp_path, "3GPP TS 29.999", "18.7.0")

    assert len(expansion.widened) == 1
    assert expansion.remaining == [
        "correction TS29.999.py#area-scope-code 18.6.0: not a string literal"
    ]
    assert 'versions=VersionRange.exact("18.6.0")' in path.read_text(encoding="utf-8")


def test_a_specification_without_edit_files_expands_nothing(tmp_path):
    empty = ranges.Expansion([], [])
    assert ranges.expand_sources(tmp_path / "TS29.999.toml", "18.7.0") == empty
    assert ranges.expand_corrections(tmp_path, "3GPP TS 29.999", "18.7.0") == empty


def test_a_module_in_another_encoding_is_rewritten_in_that_encoding(tmp_path):
    """`ast` columns count UTF-8 bytes of the decoded line; a latin-1 'é'
    earlier on the line is one byte on disk and two in those columns."""
    text = (
        "# -*- coding: latin-1 -*-\n"
        "from seanchai.dad.corrections import Correction, definition\n"
        "CORRECTIONS = [Correction(id='c', target=definition('A'), field='code',"
        " expect=1, replace=2, reason='café', versions='18.6.0')]\n"
    )
    path = tmp_path / "TS29.999.py"
    path.write_bytes(text.encode("latin-1"))

    expansion = ranges.expand_corrections(tmp_path, "3GPP TS 29.999", "18.7.0")

    assert path.read_bytes() == text.replace(
        "versions='18.6.0'", "versions='18.6.0..18.7.0'"
    ).encode("latin-1")
    assert expansion.remaining == []


def test_a_declaration_the_loader_never_applies_is_reported_not_widened(tmp_path):
    text = _PYTHON + (
        "_UNUSED = lambda: Correction(id='unused', target=definition('X'),"
        " field='code', expect=1, replace=2, reason='never called',"
        " versions='18.5.0')\n"
    )
    path = tmp_path / "TS29.999.py"
    path.write_text(text, encoding="utf-8")

    expansion = ranges.expand_corrections(tmp_path, "3GPP TS 29.999", "18.7.0")

    rewritten = path.read_text(encoding="utf-8")
    assert "versions='18.5.0'" in rewritten
    assert rewritten.count("18.6.0..18.7.0") == 2
    assert expansion.remaining == [
        "TS29.999.py:38: versions 18.5.0: outside the CORRECTIONS the loader applies"
    ]


def test_a_literal_split_by_comments_is_reported_not_widened(tmp_path):
    text = _PYTHON.replace(
        "versions='18.6.0',",
        "versions=(\n            '18.6.0'  # reviewed\n            ''\n        ),",
    )
    path = tmp_path / "TS29.999.py"
    path.write_text(text, encoding="utf-8")

    expansion = ranges.expand_corrections(tmp_path, "3GPP TS 29.999", "18.7.0")

    rewritten = path.read_text(encoding="utf-8")
    assert "'18.6.0'  # reviewed" in rewritten
    assert expansion.remaining == [
        "TS29.999.py:15: versions 18.6.0: its parts are split by comments"
    ]


_SOURCE_FILES = sorted((_EDITS / "sources").glob("*.toml"))
_CORRECTION_MODULES = sorted((_EDITS / "corrections").glob("*.py"))


def _inside_every_range(entries) -> str:
    """A version every declared range covers: the latest first bound."""
    firsts = [entry["first_version"] for entry in entries if "first_version" in entry]
    version = max(firsts or ["1"], key=lambda v: tuple(map(int, v.split("."))))
    assert all(
        VersionRange(entry.get("first_version"), entry.get("last_version")).covers(
            version
        )
        for entry in entries
    )
    return version


@pytest.mark.parametrize("path", _SOURCE_FILES, ids=lambda path: path.name)
def test_a_covered_version_leaves_every_source_file_byte_identical(tmp_path, path):
    copy = tmp_path / path.name
    copy.write_bytes(path.read_bytes())
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = [*data.get("patch", ()), *data.get("quirk", ())]
    version = _inside_every_range(entries)

    expansion = ranges.expand_sources(copy, version)

    assert expansion == ranges.Expansion([], [])
    assert copy.read_bytes() == path.read_bytes()


@pytest.mark.parametrize("path", _SOURCE_FILES, ids=lambda path: path.name)
def test_widening_a_source_file_changes_only_its_bound_lines(tmp_path, path):
    """TS 29.273 interleaves its blocks (quirk, patches, quirks); a
    re-serialising writer regroups them, this must not."""
    copy = tmp_path / path.name
    copy.write_bytes(path.read_bytes())

    expansion = ranges.expand_sources(copy, "99.0.0")

    before = path.read_bytes().splitlines()
    after = copy.read_bytes().splitlines()
    assert len(before) == len(after)
    changed = [old for old, new in zip(before, after, strict=True) if old != new]
    assert all(line.startswith(b"last_version = ") for line in changed)
    assert len(changed) == len(expansion.widened)
    assert expansion.remaining == []


@pytest.mark.parametrize("path", _CORRECTION_MODULES, ids=lambda path: path.name)
def test_every_committed_range_is_one_the_rewrite_can_reach(tmp_path, path):
    """Each module's literals sit where the loader applies them, so widening
    to a far version leaves nothing for a person and changes only them."""
    copy = tmp_path / path.name
    copy.write_bytes(path.read_bytes())
    # `spec_ref` accepts its own canonical form back. Every acceptance is
    # taken as matching: what is pinned here is that each literal is reachable.
    accepted = {
        acceptance.cited
        for acceptance in corrections.acceptances(corrections.load(tmp_path, path.stem))
    }
    expansion = ranges.expand_corrections(tmp_path, path.stem, "99.0.0", accepted)

    assert expansion.remaining == expansion.stale == []
    before = path.read_bytes().splitlines()
    after = copy.read_bytes().splitlines()
    changed = [old for old, new in zip(before, after, strict=True) if old != new]
    assert all(b"versions=" in line for line in changed)
