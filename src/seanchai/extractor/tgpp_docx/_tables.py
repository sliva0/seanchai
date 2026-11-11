"""What the AVP, re-used and value tables share: note references in
cells, the Value Type cell, column labels mapped to the modelled columns,
the mark columns, and the row walk from the label row on."""

from __future__ import annotations

import enum
import re
from collections.abc import Callable

from ...dad import ast
from .. import sources
from ..errors import ExtractionError
from ._base import _Row, _Table

# The spellings a table cell uses to point at a note below the table: bare
# "NOTE 1" (29.272 and most others) and parenthesized "(NOTE 3)" / "(Note 2)"
# (29.212, 29.214 name cells — 29.212 mixes both casings, and V11.19.0's
# table 5a.4.1 writes "(note 2)" too). The parenthesized form must strip as
# a whole, or "3GPP-RAT-Type (NOTE 3)" would be left as the non-name
# "3GPP-RAT-Type ()".
_NOTE_REF_RE = re.compile(
    r"\s*\(\s*(?:NOTE|Note|note)\s*(?P<number>\d+)\s*\)\s*"
    r"|\s*(?:NOTE|Note)\s*(?P<bare>\d+)\s*"
)


def _strip_note_ref(text: str) -> tuple[str, str | None]:
    """Remove every note reference from a cell, keeping the first number —
    29.212 stacks two on one name cell ("Granted-Service-Unit (NOTE 5)
    (NOTE 7)")."""
    first: str | None = None
    while match := _NOTE_REF_RE.search(text):
        if first is None:
            first = match["number"] if match["number"] is not None else match["bare"]
        text = (text[: match.start()] + text[match.end() :]).strip()
    return text, first


def _data_type(text: str | None) -> ast.DataType | None:
    """Strict, like the flags cells: a type outside RFC 6733's closed set is a
    source typo ("Enumerate" in TS 29.272, "Enumarated" in TS 29.212), and
    typos are the input-patch layer's job."""
    if text is None:
        return None
    try:
        return ast.DataType(text)
    except ValueError:
        raise ExtractionError(f"AVP table Value Type cell {text!r}") from None


# A column label may carry a note reference ("Value Type (NOTE 2)",
# "Applicability (notes 3, 9)"). The reference points at prose this format does
# not carry, so it is not part of the label.
_COLUMN_NOTE_RE = re.compile(r"\s*\((?:NOTE|Note|note)S?s?[^)]*\)$")


# Source columns of prose about how an AVP is used, which `.dad` does not
# carry. They are dropped silently; any other unmodelled column gets a warning
# (`ast._check_columns`).
_PROSE_COLUMNS = frozenset({"Comments", "Comment", "Description"})


# Columns marking where a row applies (`ast.MarkColumn`), keyed by the label
# they print. A cell lists the document's marks, and what separates them is
# the document's convention: TS 29.212 writes "Both Rel8" and "3GPP-EPS,
# Non-3GPP-EPS", where TS 29.468 names a feature "V2X Localized User Plane"
# (`worded-marks`). So each column is read only where its quirk is declared,
# the declaration naming the legend; elsewhere it is dropped with the
# unmodelled columns' warning.
_MARK_COLUMNS = {
    "Acc. Type": ast.MarkColumn.ACCESS_TYPES,
    "Acc. type": ast.MarkColumn.ACCESS_TYPES,  # TS 29.215
    "Applicability": ast.MarkColumn.APPLICABILITY,
    # TS 29.215 tables A.7.4.1.1 and A.8.4.1.1, the note reference unbracketed.
    "Applicability Note 1": ast.MarkColumn.APPLICABILITY,
    "Applicable Reference Points": ast.MarkColumn.REFERENCE_POINTS,
    # TS 32.299's "Used in" columns, under a spanning header.
    "ACR": ast.MarkColumn.ACR,
    "ACA": ast.MarkColumn.ACA,
    "CCR": ast.MarkColumn.CCR,
    "CCA": ast.MarkColumn.CCA,
}
_MARK_QUIRKS = {
    ast.MarkColumn.ACCESS_TYPES: "access-type-column",
    ast.MarkColumn.APPLICABILITY: "applicability-column",
    ast.MarkColumn.REFERENCE_POINTS: "reference-points-column",
    ast.MarkColumn.ACR: "command-columns",
    ast.MarkColumn.ACA: "command-columns",
    ast.MarkColumn.CCR: "command-columns",
    ast.MarkColumn.CCA: "command-columns",
}


def _with_marks[T: enum.StrEnum](
    known: dict[str, T], kind: type[T], quirks: sources.Quirks
) -> dict[str, T]:
    """`known` plus the mark columns this document's quirks read."""
    return known | {
        label: kind(column.value)
        for label, column in _MARK_COLUMNS.items()
        if quirks.enabled(_MARK_QUIRKS[column])
    }


# A mark as a cell prints it: a word, followed by what the document prints
# beside it in parentheses, a note reference mostly ("All (NOTE 5)", "All
# (see NOTE 3 and NOTE 6)", "EPC-routed (See NOTE 8)"). The parenthetical
# stays with its mark: TS 29.212's note 5 says the AVP "does not apply to
# 3GPP-GPRS access type", which a bare `All` would lose. Behind
# `worded-marks` a mark may be several words, separated from the next by a
# comma only (TS 29.468's "V2X Localized User Plane", "ROHC, FEC").
_MARK_WORD = r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?"
_PARENTHETICAL = r"(?:\s*\([^()]*\))?"
_SPACED_MARK_RE = re.compile(rf"{_MARK_WORD}{_PARENTHETICAL}")
_SPACED_SEPARATOR_RE = re.compile(r"\s*,\s*|\s+")
_WORDED_MARK_RE = re.compile(rf"{_MARK_WORD}(?: {_MARK_WORD})*{_PARENTHETICAL}")
_WORDED_SEPARATOR_RE = re.compile(r"\s*,\s*")


def _split_marks(
    text: str, mark: re.Pattern[str], separator: re.Pattern[str]
) -> list[str] | None:
    """`text` as marks, or None where something between them is neither a
    mark nor a separator."""
    marks: list[str] = []
    position = 0
    while (found := mark.match(text, position)) is not None:
        marks.append(found.group())
        if found.end() == len(text):
            return marks
        gap = separator.match(text, found.end())
        if gap is None:
            return None
        position = gap.end()
    return None


def _mark_cell(
    text: str, column: ast.MarkColumn, name: str, quirks: sources.Quirks
) -> tuple[str, ...] | None:
    """A mark column's cell: None where it is blank, no marks where it
    prints a dash (TS 32.299 clause 7.1.0: "Those Diameter AVPs that are not
    used are marked '-'"), and otherwise its marks, separated by commas or
    spaces, or behind `worded-marks` by commas only. A mark that is not
    words — a hyphen left by a line wrap ("NetLoc- Untrusted-WLAN" in TS
    29.212), a full stop for a comma — fails, for an input patch."""
    quirks.fire(_MARK_QUIRKS[column])
    if not text:
        return None
    if text == "-":
        return ()
    if quirks.enabled("worded-marks"):
        quirks.fire("worded-marks")
        marks = _split_marks(text, _WORDED_MARK_RE, _WORDED_SEPARATOR_RE)
    else:
        marks = _split_marks(text, _SPACED_MARK_RE, _SPACED_SEPARATOR_RE)
    if marks is None:
        raise ExtractionError(
            f"row {name!r}: {column.value} cell {text!r} is no list of marks"
        )
    return tuple(marks)


def _map_columns[T](
    labels: list[str], known: dict[str, T], kind: str, warnings: list[str]
) -> tuple[tuple[T, ...], list[int]]:
    """Modelled columns in source order, plus the cell indices they sit at.

    Rows are read by position in the source table; the indices let
    unmodelled columns be skipped.
    """
    columns: list[T] = []
    positions: list[int] = []
    for index, label in enumerate(labels):
        stripped = _COLUMN_NOTE_RE.sub("", label).strip()
        if not stripped:
            # 29.212 prints one re-used table with a fourth, label-less
            # column whose cells are empty. Dropped like an unmodelled
            # column: visible in the warning, not fatal.
            warnings.append(f"{kind} column {index + 1} has no label and was dropped")
            continue
        if (column := known.get(stripped)) is not None:
            columns.append(column)
            positions.append(index)
        elif stripped not in _PROSE_COLUMNS:
            warnings.append(
                f"{kind} column {stripped!r} is not modelled and was dropped"
            )
    return tuple(columns), positions


# The label a table prints over its name column. A row starting with one is
# the column-label row.
_NAME_LABELS = frozenset({"Attribute Name", "AVP Name"})


def _walk_table[T](
    table: _Table,
    known: dict[str, T],
    kind: str,
    warnings: list[str],
    skip: Callable[[_Row], bool],
) -> tuple[tuple[T, ...], list[int], list[list[str]]]:
    """The row walk both table kinds share: the `Attribute Name` label row
    defines the columns, every later data row is width-checked against it.
    Returns the modelled columns, the cell indices they sit at, and every
    data row's cells. `skip` is the caller's row filter (spanning headers,
    NOTE rows); it never sees the label row.
    """
    columns: tuple[T, ...] | None = None
    positions: list[int] = []
    width = 0
    data_rows: list[list[str]] = []
    stacked = False
    for index, row in enumerate(table.rows):
        cells = row.cells
        if not cells:
            raise ExtractionError(f"{kind} row with no cells")
        if stacked:
            stacked = False
            continue
        if cells[0] in _NAME_LABELS:
            # A two-row header: the upper row groups ("Used in", "AVP Flag
            # rules"), the lower one labels. TS 32.299 table 7.1.0.1 repeats
            # "AVP Name" in both rows; table 7.2.0.1 prints it only in the
            # upper one, leaving the lower row's first cell blank. The lower
            # row is a label row because it carries known labels, which no
            # data row does.
            following = (
                table.rows[index + 1].cells if index + 1 < len(table.rows) else []
            )
            if (
                following
                and following[0] in ("", cells[0])
                and any(
                    label in known and known[label] != known.get(cells[0])
                    for label in following[1:]
                )
            ):
                cells = [cells[0], *following[1:]]
                stacked = True
            columns, positions = _map_columns(cells, known, kind, warnings)
            width = len(cells)
            continue
        if skip(row):
            continue
        if columns is None:
            raise ExtractionError(f"{kind} row before its column labels")
        # The width check comes before every other cell is read: a malformed
        # table must report its width, not an IndexError from column two.
        if len(cells) != width:
            raise ExtractionError(
                f"{kind} row with {len(cells)} cells for"
                f" {width} source columns: {cells!r}"
            )
        data_rows.append(cells)
    if columns is None:
        raise ExtractionError(f"{kind} without column labels")
    return columns, positions, data_rows
