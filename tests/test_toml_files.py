"""Every tracked TOML file keeps to 80 columns (CONTRIBUTING.md)."""

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import _CORPUS_DIR

from seanchai import _ranges
from seanchai._prose import collapse, collapse_fields

_ROOT = Path(__file__).parent.parent
_COLUMNS = 80
# Fields whose whitespace is significant cannot wrap: a line break in a `find`
# is a different string to look for, and a line continuation would hide a
# trailing space. A catalog's `url` has none, and no place to break.
_EXACT_FIELD = re.compile(r"""(?:find|replace|url) = (?:"(?:[^"\\]|\\.)*"|'[^']*')""")
# What `.gitignore` names, none of it ours to hold to a line length.
_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "specifications",
        "wheels",
    }
)


def _toml_files(root: Path) -> Iterator[Path]:
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in _IGNORED_DIRECTORIES and not name.endswith(".egg-info")
        ]
        for name in files:
            if name.endswith(".toml"):
                yield Path(directory) / name


def _long_lines(path: Path, root: Path) -> list[str]:
    """Lines over the limit. An exact field is judged with multi-line strings
    blanked, so wrapped prose that reads "find = ..." gets no exemption."""
    text = path.read_text("utf-8")
    # `\n` only: `str.splitlines` also breaks at characters TOML keeps in text.
    lines = zip(
        text.split("\n"),
        _ranges.without_multiline_strings(text).split("\n"),
        strict=True,
    )
    return [
        f"{path.relative_to(root)}:{number}: {len(line)} columns"
        for number, (line, structure) in enumerate(lines, 1)
        if len(line) > _COLUMNS and not _EXACT_FIELD.fullmatch(structure)
    ]


def test_every_toml_file_keeps_to_80_columns():
    files = list(_toml_files(_ROOT))
    assert {
        _ROOT / "pyproject.toml",
        _CORPUS_DIR / "holes.toml",
        _CORPUS_DIR / "corpus.toml",
        _ROOT / "edits" / "sources" / "TS29.272.toml",
        _ROOT / "integrations" / "wireshark" / "aliases.toml",
        _ROOT / "src" / "seanchai" / "downloader" / "specs.toml",
    } <= set(files)

    long_lines = [line for path in files for line in _long_lines(path, _ROOT)]

    assert not long_lines, "\n".join(long_lines)


def test_only_a_whole_exact_field_may_run_long(tmp_path):
    long = "x" * _COLUMNS
    path = tmp_path / "TS29.999.toml"
    path.write_text(
        f'find = "{long}"\n'
        f"replace = '{long}'\n"
        f'reason = "{long}"\n'
        f"# {long}\n"
        f'find = "x" # {long}\n'
        f'other = """\n'
        f"    find = {long}\n"
        f'find = "{long}"\n'
        f'    """\n'
    )

    assert _long_lines(path, tmp_path) == [
        "TS29.999.toml:3: 91 columns",
        "TS29.999.toml:4: 82 columns",
        "TS29.999.toml:5: 93 columns",
        "TS29.999.toml:7: 91 columns",
        "TS29.999.toml:8: 89 columns",
    ]


def test_the_walk_skips_what_git_ignores(tmp_path):
    (tmp_path / "edits").mkdir()
    (tmp_path / "edits" / "kept.toml").touch()
    for ignored in ("specifications", ".venv", "seanchai.egg-info"):
        (tmp_path / ignored).mkdir()
        (tmp_path / ignored / "skipped.toml").touch()

    assert list(_toml_files(tmp_path)) == [tmp_path / "edits" / "kept.toml"]


@pytest.mark.parametrize(
    "text",
    [
        "one two",
        "\n    one\n    two\n    ",
        "one  \t two\n",
    ],
)
def test_collapse_makes_any_layout_one_line(text):
    assert collapse(text) == "one two"


def test_collapse_fields_leaves_other_keys_and_non_text_alone():
    table = {"reason": " a\n b ", "find": " a\n b ", "title": 5}

    assert collapse_fields(table, {"reason", "title"}) == {
        "reason": "a b",
        "find": " a\n b ",
        "title": 5,
    }
    assert table["reason"] == " a\n b "
