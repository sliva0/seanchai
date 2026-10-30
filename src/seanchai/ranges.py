"""Widening declared version ranges in the edit files, in place.

Every input patch, quirk and correction carries an advisory version range,
and `regenerate` warns when the parsed version falls outside it. When the
rebuild succeeded anyway, every declaration fired exactly as declared — the
patches' and quirks' must-fire accounting and the corrections' `expect`
checks all passed — so the range is merely stale, and widening it to the
parsed version is a mechanical edit (TS 29.272's 18.6.0 → 18.7.0 upgrade
widened twenty-odd by hand). `seanchai regenerate --expand-ranges` makes it.

Both rewrites replace the text of one bound or one literal and nothing else:
no re-serialisation, so comments, block order and layout stay byte for byte.
A source declaration's bound is located in the TOML text and the result is
checked against what `tomllib` reads back. A corrections module's
`versions=` literal is located with `ast`, and only where the loader is
known to apply it: inside the top-level `CORRECTIONS` assignments, outside
lambdas, conditionals and filtered comprehensions. Anything this cannot
rewrite safely — a literal elsewhere, one split by comments, a range built
by an expression — is reported for a person to widen instead.

An `Accept` is no edit, so a clean rebuild says nothing about it: its range
is widened only when the caller found it still matching its finding on the
rebuilt file (`accepted`), and is reported stale otherwise.
"""

import ast
import dataclasses
import io
import re
import tempfile
import tokenize
import tomllib
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from pathlib import Path

from .dad import corrections
from .versions import VersionRange


@dataclass
class Expansion:
    """What widening one file did, and what it could not."""

    # "TS29.272.toml: input patch 'M. V' 18.6.0 -> 18.6.0..18.7.0", one per
    # declaration (a comprehension's literal is one change for all of them).
    widened: list[str]
    # Declarations still outside the range afterwards, each with the reason
    # it was left for a person.
    remaining: list[str]
    # Acceptances left out of range because they no longer match a finding.
    stale: list[str] = dataclasses.field(default_factory=list)


# --- source declarations ----------------------------------------------------

_BLOCK = re.compile(r"^[ \t]*\[\[[ \t]*(patch|quirk)[ \t]*\]\]", re.MULTILINE)
_ANY_TABLE = re.compile(r"^[ \t]*\[", re.MULTILINE)
_KINDS = {"patch": "input patch", "quirk": "quirk"}


def expand_sources(path: Path, version: str) -> Expansion:
    """Widen every `[[patch]]` and `[[quirk]]` range in `path` to `version`."""
    if not path.is_file():
        return Expansion([], [])
    # TOML is UTF-8 by definition; bytes in and out keep line endings as they
    # are.
    text = path.read_bytes().decode("utf-8")
    data = tomllib.loads(text)
    regions = _block_regions(text)
    replacements: list[tuple[int, int, str]] = []
    expected = {kind: [dict(entry) for entry in data.get(kind, ())] for kind in _KINDS}
    widened = []
    for kind, label, index, entry in _source_entries(data):
        declared = _source_range(entry)
        expanded = declared.expanded(version)
        if expanded == declared:
            continue
        described = f"{path.name}: {_KINDS[kind]} {label!r} {declared}"
        moved = [
            (key, value)
            for key, value, old in (
                ("first_version", expanded.first, declared.first),
                ("last_version", expanded.last, declared.last),
            )
            if value != old
        ]
        spans = [_bound_span(text, regions, kind, index, key) for key, _value in moved]
        if any(span is None for span in spans):
            # Reported below, as still uncovered.
            continue
        for (key, value), span in zip(moved, spans, strict=True):
            assert span is not None and value is not None
            begin, end = span
            quote = text[begin]
            replacements.append((begin, end, f"{quote}{value}{quote}"))
            expected[kind][index][key] = value
        widened.append(f"{described} -> {expanded}")
    rewritten = _replaced(text, replacements)
    if replacements:
        reread = tomllib.loads(rewritten)
        if {kind: reread.get(kind, []) for kind in _KINDS} != expected or {
            key: value for key, value in reread.items() if key not in _KINDS
        } != {key: value for key, value in data.items() if key not in _KINDS}:
            # A bound found somewhere other than the block it belongs to;
            # nothing is written rather than something wrong.
            return Expansion(
                [], _uncovered_sources(path, data, version, "did not read back")
            )
        path.write_bytes(rewritten.encode("utf-8"))
        data = reread
    return Expansion(
        widened, _uncovered_sources(path, data, version, "bound not found in the text")
    )


def _block_regions(text: str) -> dict[str, list[tuple[int, int]]]:
    """Each `[[patch]]`/`[[quirk]]` block's text span, per kind in file
    order — the order `tomllib` lists them in."""
    regions: dict[str, list[tuple[int, int]]] = {kind: [] for kind in _KINDS}
    for header in _BLOCK.finditer(text):
        following = _ANY_TABLE.search(text, header.end())
        regions[header.group(1)].append(
            (header.end(), len(text) if following is None else following.start())
        )
    return regions


def _bound_span(
    text: str,
    regions: dict[str, list[tuple[int, int]]],
    kind: str,
    index: int,
    key: str,
) -> tuple[int, int] | None:
    if index >= len(regions[kind]):
        return None
    begin, end = regions[kind][index]
    found = re.compile(
        rf"^[ \t]*{key}[ \t]*=[ \t]*(\"[^\"\\\n]*\"|'[^'\n]*')", re.MULTILINE
    ).search(text, begin, end)
    return None if found is None else found.span(1)


def _source_entries(data: dict) -> Iterator[tuple[str, str, int, dict]]:
    for kind, label in (("patch", "find"), ("quirk", "name")):
        for index, entry in enumerate(data.get(kind, ())):
            yield kind, str(entry[label]), index, entry


def _source_range(entry: dict) -> VersionRange:
    return VersionRange(entry.get("first_version"), entry.get("last_version"))


def _uncovered_sources(path: Path, data: dict, version: str, why: str) -> list[str]:
    return [
        f"{path.name}: {_KINDS[kind]} {label!r} {_source_range(entry)}: {why}"
        for kind, label, _index, entry in _source_entries(data)
        if not _source_range(entry).covers(version)
    ]


# --- corrections modules ----------------------------------------------------

_DECLARATIONS = {"Correction", "Delete", "Insert", "Supply", "Accept"}


def expand_corrections(
    directory: Path,
    specification: str,
    version: str,
    accepted: Collection[str] = (),
) -> Expansion:
    """Widen the `versions=` literals in `specification`'s corrections module
    that the loader applies and that do not cover `version`.

    An `Accept`'s literal is widened only when its id, cited as
    `<module>#<id>`, is in `accepted`: the acceptances the caller checked
    against the rebuilt file and found matching. One that is not is
    reported in `stale`; one whose id is not a string literal cannot be
    told apart and is left for a person."""
    path = corrections.module_path(directory, specification)
    if not path.is_file():
        return Expansion([], [])
    raw = path.read_bytes()
    # Python reads a module in its declared encoding, so the text is decoded
    # the same way and re-encoded the same way; `ast` columns are UTF-8 byte
    # offsets into each *decoded* line, converted below.
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    text = raw.decode(encoding)
    tree = ast.parse(text)
    starts = _line_starts(text)
    applied = _applied_literals(tree)

    def offset(line: int, column: int) -> int:
        start = starts[line - 1]
        stop = starts[line] if line < len(starts) else len(text)
        utf8 = text[start:stop].encode("utf-8")
        return start + len(utf8[:column].decode("utf-8"))

    replacements: list[tuple[int, int, str]] = []
    widened, manual, stale = [], [], []
    # Ranges a reported literal declares: the declarations it builds are
    # covered by that line and not listed again by id.
    explained: set[str] = set()
    for literal, value, acceptance in _range_literals(tree):
        declared = VersionRange.parse(value)
        expanded = declared.expanded(version)
        if expanded == declared:
            continue
        where = f"{path.name}:{literal.lineno}: versions {declared}"
        if id(literal) not in applied:
            manual.append(f"{where}: outside the CORRECTIONS the loader applies")
            explained.add(str(declared))
            continue
        if acceptance is not None:
            cited = f"{path.name}#{acceptance}" if acceptance else None
            if cited is None:
                manual.append(f"{where}: an acceptance whose id is not a literal")
                explained.add(str(declared))
                continue
            if cited not in accepted:
                stale.append(f"{where}: acceptance {cited} matches no finding")
                explained.add(str(declared))
                continue
        assert literal.end_lineno is not None and literal.end_col_offset is not None
        begin = offset(literal.lineno, literal.col_offset)
        end = offset(literal.end_lineno, literal.end_col_offset)
        if _has_comments(text[begin:end]):
            manual.append(f"{where}: its parts are split by comments")
            explained.add(str(declared))
            continue
        # Keep the author's quote character; a prefixed or implicitly
        # concatenated literal becomes one plain literal.
        quote = text[end - 1]
        replacements.append((begin, end, f"{quote}{expanded}{quote}"))
        widened.append(f"{where} -> {expanded}")

    declared_edits = corrections.load(directory, specification)
    edits = declared_edits
    if replacements:
        rewritten = _replaced(text, replacements).encode(encoding)
        edits = _checked_rewrite(rewritten, path, specification, declared_edits)
        path.write_bytes(rewritten)
    remaining = manual + [
        f"correction {edit.cited} {edit.versions}: not a string literal"
        for edit in edits
        if not VersionRange.parse(edit.versions).covers(version)
        and str(edit.versions) not in explained
    ]
    return Expansion(widened, remaining, stale)


def _checked_rewrite(
    rewritten: bytes,
    path: Path,
    specification: str,
    declared: list[corrections.Declaration],
) -> list[corrections.Declaration]:
    """Load the rewritten module from a scratch copy and require it to declare
    exactly what the original did, ranges aside, before anything is replaced."""
    with tempfile.TemporaryDirectory() as scratch:
        (Path(scratch) / path.name).write_bytes(rewritten)
        loaded = corrections.load(Path(scratch), specification)

    def unranged(edit: corrections.Declaration) -> corrections.Declaration:
        return dataclasses.replace(edit, versions="*..*")

    if [unranged(edit) for edit in loaded] != [unranged(edit) for edit in declared]:
        raise corrections.CorrectionError(
            f"{path}: widening its ranges would change what it declares;"
            " the file was left as it was"
        )
    return loaded


def _line_starts(text: str) -> list[int]:
    """Offsets of each line as the tokenizer counts them (`\\r\\n`, `\\r` or
    `\\n`; `str.splitlines` also splits on form feeds and the like)."""
    return [0] + [match.end() for match in re.finditer(r"\r\n|\r|\n", text)]


def _range_literals(
    tree: ast.Module,
) -> Iterator[tuple[ast.Constant, str, str | None]]:
    """The `versions=` string literals of every declaration call in the
    module, in source order, each with the declaring `Accept`'s id: None for
    an edit, "" for an acceptance whose id is no string literal."""
    calls = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.Call)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for node in calls:
        called = node.func
        name = called.attr if isinstance(called, ast.Attribute) else None
        if isinstance(called, ast.Name):
            name = called.id
        if name not in _DECLARATIONS:
            continue
        acceptance = None
        if name == "Accept":
            ids = [
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "id"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ]
            acceptance = ids[0] if ids else ""
        for keyword in node.keywords:
            value = keyword.value
            if (
                keyword.arg == "versions"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                yield value, value.value, acceptance


def _applied_literals(tree: ast.Module) -> set[int]:
    """Identities of the nodes the loader's `CORRECTIONS` is built from:
    the last top-level `CORRECTIONS = ...` and every top-level
    `CORRECTIONS += ...` after it; any other shape is reported, not guessed.
    Code that runs only sometimes (a lambda, either arm of a conditional, a
    comprehension with a filter) is left out, since a literal there may
    belong to a declaration that never applied."""
    values: list[ast.expr] = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CORRECTIONS"
            for target in statement.targets
        ):
            values = [statement.value]
        elif (
            isinstance(statement, ast.AugAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "CORRECTIONS"
            and isinstance(statement.op, ast.Add)
        ):
            values.append(statement.value)
    found: set[int] = set()
    for value in values:
        found |= {id(node) for node in _unconditional(value)}
    return found


def _unconditional(node: ast.AST) -> Iterator[ast.AST]:
    yield node
    if isinstance(node, ast.Lambda | ast.IfExp | ast.BoolOp):
        return
    if isinstance(
        node, ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
    ) and any(generator.ifs for generator in node.generators):
        return
    for child in ast.iter_child_nodes(node):
        yield from _unconditional(child)


def _has_comments(literal: str) -> bool:
    """Whether an implicitly concatenated literal carries comments between
    its parts, which replacing the whole span would delete."""
    # Parenthesised so a literal continued over lines tokenizes on its own.
    tokens = tokenize.generate_tokens(io.StringIO(f"({literal})").readline)
    return any(token.type == tokenize.COMMENT for token in tokens)


def _replaced(text: str, replacements: list[tuple[int, int, str]]) -> str:
    for begin, end, new in sorted(replacements, reverse=True):
        text = text[:begin] + new + text[end:]
    return text
