"""TS 29.230's allocation tables, read behind `registry-tables`: one
registry row per allocation, the documents each cites, and behind
`reserved-range-notes` the ranges its full-width notes reserve."""

from __future__ import annotations

import re

import pydantic

from ...dad import ast
from .. import sources
from ..errors import ExtractionError
from ._base import _Table
from ._origins import _ORIGIN_TS_RE

# TS 29.230's registry tables, by the label of their first column, and the
# labels each prints; read behind `registry-tables`.
_REGISTRY_KINDS = {
    "Application identifier": ast.RegistryKind.APPLICATION_IDS,
    "Command code value": ast.RegistryKind.COMMAND_CODES,
    "AVP Code": ast.RegistryKind.AVP_CODES,
    "Experimental Result Code": ast.RegistryKind.RESULT_CODES,
}
_REGISTRY_COLUMNS = {
    **dict.fromkeys(_REGISTRY_KINDS, ast.RegistryColumn.CODE),
    "Application": ast.RegistryColumn.NAME,
    "Command name": ast.RegistryColumn.NAME,
    "Attribute Name": ast.RegistryColumn.NAME,
    "Result text": ast.RegistryColumn.NAME,
    "Abbreviation": ast.RegistryColumn.ABBREVIATION,
    "Data Type": ast.RegistryColumn.TYPE,
    "3GPP TS": ast.RegistryColumn.DEFINED_IN,
    "Specified in 3GPP TS": ast.RegistryColumn.DEFINED_IN,
    "Specified in the 3GPP TS": ast.RegistryColumn.DEFINED_IN,
    "Specified in the TS": ast.RegistryColumn.DEFINED_IN,
}
# A "Specified in" cell: one or more "29.229 [2]", the document's number and
# its clause-2 reference, separated by commas or "and" (table 4.1's "29.228
# [1] and 29.229 [2]", table 7.1's "29.209 [8], 29.211 [17] , 29.214 [18]").
_REGISTRY_DOCUMENT = r"\d{2}\.\d{3} \[\d+\]"
_REGISTRY_DOCUMENTS_RE = re.compile(
    rf"{_REGISTRY_DOCUMENT}(?:(?:\s*,\s*| and ){_REGISTRY_DOCUMENT})*"
)
_REGISTRY_DOCUMENT_RE = re.compile(r"(?P<number>\d{2}\.\d{3}) \[(?P<reference>\d+)\]")
# A full-width note row reserving a range, behind `reserved-range-notes`:
# "Note: The AVP codes from 320 to 399 are reserved for TS 29.234" (table
# 7.1), "Note: The Experimental Result Codes from 2006 to 2020 are reserved
# for the TS 29.229." (tables 8.1.2-8.1.4). The purpose is the rest of the
# sentence, as printed, less its closing full stop.
_RESERVED_RANGE_NOTE_RE = re.compile(
    r"^Note(?: \d+)?: The (?:AVP codes|Experimental Result Codes) from"
    r" (?P<first>\d+) to (?P<last>\d+) are reserved for (?P<purpose>.+?)\.?$"
)
_NAMED_DOCUMENT_RE = re.compile(r"TS (?P<number>\d{2}\.\d{3})(?!\d)")


def _registry_documents(
    text: str, label: str, references: dict[str, str], warnings: list[str]
) -> tuple[str, ...]:
    """A "Specified in" cell's documents, read by their numbers. A number
    its reference does not name is the cell's to say and warns: TS 29.230
    table 5.1/4 cites TER, which TS 29.215 defines, as "29.215 [30]", and
    clause 2's [30] is TS 29.338."""
    if not text:
        return ()
    if not _REGISTRY_DOCUMENTS_RE.fullmatch(text):
        raise ExtractionError(f"{label}: unrecognized document cell {text!r}")
    documents = []
    for match in _REGISTRY_DOCUMENT_RE.finditer(text):
        document = f"TS{match['number']}"
        entry = references.get(match["reference"])
        cited = None if entry is None else _ORIGIN_TS_RE.search(entry)
        listed = None if cited is None else f"TS {cited['series']}.{cited['number']}"
        if listed != f"TS {match['number']}":
            warnings.append(
                f"{label}: cites {match['number']} as [{match['reference']}],"
                f" which clause 2 lists as {listed or 'no TS'}; reading {document}"
            )
        documents.append(document)
    return tuple(dict.fromkeys(documents))


def _extract_registry(
    table: _Table,
    section: str,
    warnings: list[str],
    quirks: sources.Quirks,
    references: dict[str, str],
) -> ast.Registry:
    """A TS 29.230 registry table: one row per allocation, and behind
    `reserved-range-notes` the full-width notes reserving ranges among them."""
    quirks.fire("registry-tables")
    if table.caption is None:
        raise ExtractionError(f"{section}: registry table without a caption")
    header = table.rows[0].cells
    columns = []
    for label in header:
        if label not in _REGISTRY_COLUMNS:
            raise ExtractionError(
                f"table {table.caption}: unrecognized registry column {label!r}"
            )
        columns.append(_REGISTRY_COLUMNS[label])
    rows: list[ast.RegistryRow | ast.RegistryReservation] = []
    for row in table.rows[1:]:
        cells = row.cells
        if len(cells) == 1:
            if cells[0]:
                rows.extend(
                    _reserved_ranges(
                        row.first_cell_lines, table.caption, warnings, quirks
                    )
                )
            continue
        if len(cells) != len(columns):
            raise ExtractionError(
                f"table {table.caption}: a row of {len(cells)} cells under"
                f" {len(columns)} columns: {cells!r}"
            )
        by_column = dict(zip(columns, cells, strict=True))
        code = by_column[ast.RegistryColumn.CODE]
        if not code:
            # Tables 7.1 and 8.1.2-8.1.4 print a document alone ahead of the
            # range reserved for it, with no code to allocate.
            if any(by_column.values()):
                warnings.append(
                    f"table {table.caption}: a row with no code, printing only"
                    f" {' '.join(cell for cell in cells if cell)!r}; not read"
                )
            continue
        printed_code = None
        if not code.isdigit():
            # TS 29.230 V19.3.0 allocates Sh-ee's application id "zz" in table
            # 4.1 and its command codes "xx1" and "xx2" in table 5.1/4, as TS
            # 29.329 V19.1.0 clause 8 awaits IANA's value.
            if not quirks.enabled("placeholder-codes"):
                raise ExtractionError(f"table {table.caption}: code cell {code!r}")
            quirks.fire("placeholder-codes")
            printed_code = code
        label = f"table {table.caption} code {code}"
        defined_in = _registry_documents(
            by_column.get(ast.RegistryColumn.DEFINED_IN, ""),
            label,
            references,
            warnings,
        )
        data_type = by_column.get(ast.RegistryColumn.TYPE, "")
        printed_type = None
        if data_type not in ("", "-", *ast.DataType):
            # TS 29.230 table 7.1 types code 314 "Integer", which could be
            # Integer32, Integer64 or neither; TS 29.234 would say.
            if not quirks.enabled("unknown-type-tokens"):
                raise ExtractionError(
                    f"{label}: Type cell {data_type!r} names no Diameter type,"
                    " and this document's source declaration does not keep"
                    " one (the `unknown-type-tokens` quirk)"
                )
            quirks.fire("unknown-type-tokens")
            printed_type, data_type = data_type, ""
        try:
            rows.append(
                ast.RegistryRow(
                    code=None if printed_code is not None else int(code),
                    printed_code=printed_code,
                    name=by_column.get(ast.RegistryColumn.NAME) or None,
                    abbreviation=by_column.get(ast.RegistryColumn.ABBREVIATION) or None,
                    # The registry's type is informational: a dash and a
                    # blank cell are the same absence.
                    data_type=None
                    if data_type in ("", "-")
                    else ast.DataType(data_type),
                    printed_type=printed_type,
                    defined_in=defined_in,
                )
            )
        except (ValueError, pydantic.ValidationError) as error:
            raise ExtractionError(f"{label}: {error}") from None
    return ast.Registry(
        registry=_REGISTRY_KINDS[header[0]],
        table=table.caption,
        source=ast.SourceRef(section=section),
        columns=tuple(columns),
        rows=tuple(rows),
    )


def _reserved_ranges(
    lines: list[str], caption: str, warnings: list[str], quirks: sources.Quirks
) -> list[ast.RegistryReservation]:
    """A full-width note row's reservations, one per line; a line reserving
    nothing is prose and warns (table 7.1's "Note 2: The 3GPP-AAA-Server-Name
    definition is moved to TS 29.273 starting from Rel-12.")."""
    if not quirks.enabled("reserved-range-notes"):
        raise ExtractionError(
            f"table {caption}: a full-width note row, which this document's"
            " source declaration does not read (the `reserved-range-notes`"
            f" quirk): {' '.join(lines)!r}"
        )
    reservations = []
    for line in lines:
        match = _RESERVED_RANGE_NOTE_RE.match(line)
        if match is None:
            warnings.append(f"table {caption}: note reserves nothing: {line!r}")
            continue
        quirks.fire("reserved-range-notes")
        purpose = match["purpose"]
        reservations.append(
            ast.RegistryReservation(
                first=int(match["first"]),
                last=int(match["last"]),
                defined_in=tuple(
                    dict.fromkeys(
                        f"TS{named['number']}"
                        for named in _NAMED_DOCUMENT_RE.finditer(purpose)
                    )
                ),
                purpose=purpose,
            )
        )
    return reservations
