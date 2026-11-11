"""The AVP-flags tables and the re-used AVPs tables: the AVP table's
rows, cells and notes, what its clause's sentences add to it, the re-used
table's origins and M-bit overrides, and the tables of other vendors'
AVPs."""

from __future__ import annotations

import re

from ...dad import abnf, ast
from .. import sources
from ..errors import ExtractionError
from ._base import _AVP_TITLE_RE, _ReusedTable, _Row, _Section, _Table
from ._origins import (
    _SECTION_REF_RE,
    _entry_document,
    _named_document,
    _origin,
    _referred_origin,
)
from ._tables import (
    _data_type,
    _mark_cell,
    _strip_note_ref,
    _walk_table,
    _with_marks,
)

_NOTE_RFC_RE = re.compile(
    r"^NOTE\s*(?P<number>\d+):\s*The values? of th(?:is|ese) attributes? "
    r"is defined in IETF\s+RFC\s+(?P<rfc>\d+)"
)


_M_BIT_OVERRIDES = {
    "": None,
    # TS 29.338 uses the shorter forms in its re-used tables even though the
    # notes below those tables document only "Must set" and "Must not set".
    "Must": ast.MBitOverride.MUST,
    "Must set": ast.MBitOverride.MUST,
    "Must not": ast.MBitOverride.MUST_NOT,
    "Must not set": ast.MBitOverride.MUST_NOT,
}


# Clause cells in 29.061's tables annotate the number: "16.4.7 (see Note)",
# 37 times across two clauses in both spellings. Dropping the trailing
# parenthetical is a declared reading, the `clause-parenthetical` quirk.
_CLAUSE_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _clause_cell(text: str, quirks: sources.Quirks) -> str:
    if _CLAUSE_PARENTHETICAL_RE.search(text):
        if not quirks.enabled("clause-parenthetical"):
            raise ExtractionError(
                f"clause cell {text!r} carries a parenthetical, which this"
                " document's source declaration does not strip (the"
                " `clause-parenthetical` quirk)"
            )
        quirks.fire("clause-parenthetical")
        return _CLAUSE_PARENTHETICAL_RE.sub("", text)
    return text


# Both spellings of the Encrypt column, normalized to one on the way in:
# TS 29.061, 29.212 and 29.214 write "Y"/"N" throughout, the rest write
# "Yes"/"No". A dash states nothing,
# as in the flag cells beside it: TS 32.299 V11.20.0's table 7.1 dashes
# every cell of the fifteen rows it does not use (CC-Sub-Session-Id,
# Vendor-Id), Encrypt included.
_ENCRYPT_CELLS = {"Yes": True, "Y": True, "No": False, "N": False, "": None, "-": None}


def _encrypt_cell(text: str) -> bool | None:
    if text not in _ENCRYPT_CELLS:
        raise ExtractionError(f"AVP table Encrypt cell {text!r}")
    return _ENCRYPT_CELLS[text]


def _flags_cell(text: str, quirks: sources.Quirks) -> frozenset[ast.AvpFlag]:
    # Strict: typos like "M. V" or lowercase "v" are fixed by input patches,
    # not tolerated here. Space-less "M.V" is different — 29.061 writes it 11
    # times and 29.212 seven, so the period is those documents' separator
    # convention — but a convention is per-document, so reading it is the
    # declared `dotted-flags` quirk rather than a global rewrite.
    # An empty cell, or TS 32.299's dash for one (tables 7.1.0.1, 7.2.0.1):
    # a lone dash names no flag and cannot be read as anything else.
    if text in ("", "-"):
        return frozenset()
    if "." in text and " " not in text:
        if not quirks.enabled("dotted-flags"):
            raise ExtractionError(
                f"flags cell {text!r} separates flags with periods, which"
                " this document's source declaration does not accept (the"
                " `dotted-flags` quirk)"
            )
        quirks.fire("dotted-flags")
        text = text.replace(".", ",")
    try:
        return abnf.avp_flags(text)
    except abnf.AbnfError as error:
        raise ExtractionError(str(error)) from None


# The nine columns 3GPP AVP tables share, keyed by the label they print. The
# same column is spelled differently across specifications ("Clause defined"
# and "Section defined", "May Encr." and "May Encrypt").
_AVP_TABLE_COLUMNS = {
    "Attribute Name": ast.AvpColumn.NAME,
    "AVP Name": ast.AvpColumn.NAME,  # TS 32.299 tables 7.1.0.1 and 7.2.0.1
    # oneM2M TS-0004 table A.4-1, "The entity defining the AVP code in the
    # next column" (clause A.4).
    "AVP Vendor Id": ast.AvpColumn.VENDOR,
    "AVP Code": ast.AvpColumn.CODE,
    "Clause defined": ast.AvpColumn.SECTION,
    "Section defined": ast.AvpColumn.SECTION,
    "Value Type": ast.AvpColumn.TYPE,
    "Must": ast.AvpColumn.MUST,
    "May": ast.AvpColumn.MAY,
    "Should not": ast.AvpColumn.SHOULD_NOT,
    "Must not": ast.AvpColumn.MUST_NOT,
    "May Encr.": ast.AvpColumn.ENCRYPT,
    "May Encrypt": ast.AvpColumn.ENCRYPT,
}


def _extract_avp_table(
    table: _Table,
    section_number: str,
    warnings: list[str],
    quirks: sources.Quirks,
    references: dict[str, str] | None = None,
    own_reference: str = "",
    wildcards: list[tuple[int, str]] | None = None,
) -> tuple[ast.AvpTable, list[ast.ReusedAvpRow]]:
    """Read an AVP-flags table by its column labels. The set of columns varies
    (TS 29.273's table has no Encrypt column, TS 29.212's has two the format
    does not model), and the labels keep a missing column apart from an empty
    cell.

    Behind `wildcard-avp-row`, a row tabulating the `* [ AVP ]` wildcard (TS
    32.299 tables 7.1 and 7.1.0.1, `AVP | *`) is no AVP and no row: it goes to
    `wildcards` as the note standing where it was printed, with the number of
    rows before it."""
    rows: list[ast.AvpTableRow] = []
    note_refs: list[tuple[str, str]] = []  # (avp name, note number)
    note_rfcs: dict[str, str] = {}  # note number -> RFC number
    referred: list[ast.ReusedAvpRow] = []  # from `refer [n]` type cells

    def skip(row: _Row) -> bool:
        cells = row.cells
        if cells[0].startswith("NOTE"):  # merged full-width row, 1 note per line
            for line in row.first_cell_lines:
                if match := _NOTE_RFC_RE.match(line):
                    # A note is prose; deriving a re-used AVP row from one is
                    # a prose harvest, declared like the RFC extractor's.
                    if not quirks.enabled("note-defined-in-rfc"):
                        raise ExtractionError(
                            f"table note {line!r} names a defining RFC, which"
                            " this document's source declaration does not"
                            " derive re-used rows from (the"
                            " `note-defined-in-rfc` quirk)"
                        )
                    quirks.fire("note-defined-in-rfc")
                    note_rfcs[match["number"]] = match["rfc"]
            return True
        # Spanning header rows (merged cells repeat the same text).
        return cells[0] == "" or cells[0] == cells[1]

    known = _with_marks(_AVP_TABLE_COLUMNS, ast.AvpColumn, quirks)
    if quirks.enabled("reference-cells"):
        known["Reference"] = ast.AvpColumn.SECTION
    columns, positions, data_rows = _walk_table(
        table, known, "AVP table", warnings, skip
    )
    name_at = positions[columns.index(ast.AvpColumn.NAME)]
    code_at = (
        positions[columns.index(ast.AvpColumn.CODE)]
        if ast.AvpColumn.CODE in columns
        else None
    )
    for cells in data_rows:
        if (
            code_at is not None
            and cells[name_at] == "AVP"
            and _strip_note_ref(cells[code_at])[0] == "*"
        ):
            # Any AVP, ABNF grammar: TS 32.299 clause 7.1.0's table lists the
            # members its commands may carry, and "* [ AVP ]" is one.
            if not quirks.enabled("wildcard-avp-row"):
                raise ExtractionError(
                    "AVP table row 'AVP' with code '*', which this document's"
                    " source declaration does not read (the `wildcard-avp-row`"
                    " quirk)"
                )
            quirks.fire("wildcard-avp-row")
            printed = " ".join(cells[position] or "-" for position in positions)
            if wildcards is not None:
                wildcards.append((len(rows), f"{printed} ; the * [ AVP ] wildcard"))
            continue
        name = ""
        marks: dict[ast.MarkColumn, tuple[str, ...]] = {}
        vendor_value: int | None = None
        code_value: int | None = None
        section_value: str | None = None
        type_value: str | None = None
        printed_type: str | None = None
        encrypt: bool | None = None
        must = may = should_not = must_not = frozenset[ast.AvpFlag]()
        note: str | None = None
        for column, position in zip(columns, positions, strict=True):
            text = cells[position]
            match column:
                case ast.AvpColumn.NAME:
                    name, name_note = _strip_note_ref(text)
                    if " " in name:
                        # AVP names never contain spaces; line-wrap artifacts
                        # eating a hyphen (29.272 "MME-Location Information")
                        # are input-patched.
                        raise ExtractionError(
                            f"AVP table name cell {name!r} contains spaces"
                        )
                    note = name_note or note
                case ast.AvpColumn.VENDOR:
                    if text and not text.isdigit():
                        raise ExtractionError(f"AVP table vendor cell {text!r}")
                    vendor_value = int(text) if text else None
                case ast.AvpColumn.CODE:
                    code, code_note = _strip_note_ref(text)
                    if code and not code.isdigit():
                        raise ExtractionError(f"AVP table code cell {code!r}")
                    code_value = int(code) if code else None
                    note = note or code_note
                case ast.AvpColumn.SECTION if quirks.enabled("reference-cells"):
                    section_value, origin = _reference_cell(name, text, quirks)
                    if origin is not None:
                        referred.append(ast.ReusedAvpRow(name=name, origin=origin))
                case ast.AvpColumn.SECTION:
                    section_value = _clause_cell(text, quirks) or None
                    # TS 29.561 table 12.4-1's "Section defined" holds its own
                    # clause ("11.3.1") or another document ("3GPP TS 29.061
                    # [5]"), a re-use, as a `reference-cells` document is.
                    if (
                        section_value is not None
                        and quirks.enabled("document-clause-cells")
                        and (origin := _named_document(section_value)) is not None
                    ):
                        quirks.fire("document-clause-cells")
                        referred.append(ast.ReusedAvpRow(name=name, origin=origin))
                        section_value = None
                    # Checked here so a typo (TS 29.368 table 6.4.1.1's
                    # "6. 4.2") names its row, not a pydantic pattern.
                    if section_value is not None and not _SECTION_REF_RE.match(
                        section_value
                    ):
                        raise ExtractionError(
                            f"{section_number}: AVP table row {name!r} has"
                            f" clause cell {section_value!r}, which is not a"
                            " clause number"
                        )
                case ast.AvpColumn.TYPE:
                    type_value = text or None
                    if match := _REFER_RE.fullmatch(text):
                        type_value = None
                        origin = _referred_origin(
                            name, match["number"], references, own_reference, quirks
                        )
                        if origin is None:
                            warnings.append(
                                f"AVP table row {name!r} is typed by reference"
                                f" [{match['number']}], which names no document"
                                " a From cell can cite; kept without a type"
                            )
                        else:
                            referred.append(ast.ReusedAvpRow(name=name, origin=origin))
                    elif type_value in _TYPE_SHORT_FORMS:
                        if not quirks.enabled("type-short-forms"):
                            raise ExtractionError(
                                f"AVP table Value Type cell {text!r} is a short"
                                " form, which this document's source declaration"
                                " does not read (the `type-short-forms` quirk)"
                            )
                        quirks.fire("type-short-forms")
                        type_value = _TYPE_SHORT_FORMS[type_value]
                    elif (
                        type_value is not None
                        and type_value not in ast.DataType
                        and quirks.enabled("unknown-type-tokens")
                    ):
                        # TS 29.234 V11.2.0 table 10.1.1 and clause 10.1.27
                        # type code 314 "Integer", which names no width.
                        quirks.fire("unknown-type-tokens")
                        printed_type, type_value = type_value, None
                case ast.AvpColumn.ENCRYPT:
                    encrypt = _encrypt_cell(text)
                case ast.AvpColumn.MUST:
                    must = _flags_cell(text, quirks)
                case ast.AvpColumn.MAY:
                    may = _flags_cell(text, quirks)
                case ast.AvpColumn.SHOULD_NOT:
                    should_not = _flags_cell(text, quirks)
                case ast.AvpColumn.MUST_NOT:
                    must_not = _flags_cell(text, quirks)
                case _:
                    marked = ast.MarkColumn(column.value)
                    found = _mark_cell(text, marked, name, quirks)
                    if found is not None:
                        marks[marked] = found
        if note is not None:
            note_refs.append((name, note))
        rows.append(
            ast.AvpTableRow(
                name=name,
                vendor_id=vendor_value,
                code=code_value,
                section=section_value,
                data_type=_data_type(type_value),
                printed_type=printed_type,
                flag_rules=ast.AvpFlagRules(
                    must=must, may=may, should_not=should_not, must_not=must_not
                ),
                may_encrypt=encrypt,
                marks=marks,
            )
        )
    if table.caption is None:
        raise ExtractionError("AVP table without a caption")
    if not rows:
        # Notes, spanning rows and the `* [ AVP ]` row are no AVP's.
        raise ExtractionError(
            f"{section_number}: AVP table {table.caption} has no row naming an AVP"
        )
    reused = [
        ast.ReusedAvpRow(name=name, origin=f"RFC{note_rfcs[note]}")
        for name, note in note_refs
        if note in note_rfcs
    ] + referred
    avp_table = ast.AvpTable(
        table=table.caption,
        columns=columns,
        rows=tuple(rows),
        source=ast.SourceRef(section=section_number),
    )
    return avp_table, reused


# oneM2M TS-0004 table A.4-1's Reference cell: a bracketed clause of the
# document itself ("[A.5.1]"), or another document by its clause-2 entry
# ("IETF RFC 6733 [14]", "3GPP TS 32.299 [31]").
_BRACKETED_CLAUSE_RE = re.compile(r"\[(?P<clause>[^\[\]]+)\]")


def _reference_cell(
    name: str, text: str, quirks: sources.Quirks
) -> tuple[str | None, str | None]:
    """A Reference cell as (the row's defining clause, the document it is
    re-used from), the `reference-cells` quirk.

    Clause A.4 of oneM2M TS-0004 calls the column "a reference to where
    this AVP is defined": a bracketed clause number is the document's own,
    which a 3GPP table prints under "Clause defined"; a document's name is
    a re-use, as `refer [n]` is in TS 32.299. Anything else fails."""
    quirks.fire("reference-cells")
    if not text:
        return None, None
    if match := _BRACKETED_CLAUSE_RE.fullmatch(text):
        clause = match["clause"]
        if not _SECTION_REF_RE.match(clause):
            raise ExtractionError(
                f"AVP table row {name!r} has Reference cell {text!r}, whose"
                " bracket holds no clause number"
            )
        return clause, None
    origin = _named_document(text)
    if origin is None:
        raise ExtractionError(
            f"AVP table row {name!r} has Reference cell {text!r}, which names"
            " neither a clause nor a document"
        )
    return None, origin


# "The DCD-Information AVP (AVP code 2115) is of type Grouped.", TS 32.299
# clause 7.2.50: the sentence every AVP clause of the document opens with.
_TYPE_SENTENCE_RE = re.compile(
    r"^The (?P<name>\S+) AVP \(AVP code (?P<code>\d+)\) is of type"
    r" (?P<type>[A-Za-z0-9]+)\b"
)


def _referred_type_sentences(
    table: ast.AvpTable,
    referred: list[ast.ReusedAvpRow],
    sections: list[_Section],
    warnings: list[str],
    quirks: sources.Quirks,
) -> ast.AvpTable:
    """`table` with each row typed `refer [n]` typed from its own clause,
    where the document has one stating the type. The
    `referred-type-sentences` quirk.

    TS 32.299 table 7.2.0.1 types thirteen AVPs "refer [223]",
    OMA-DDS-Charging_Data, and for three of them clauses 7.2.50, 7.2.69
    and 7.2.191 say "The DCD-Information AVP (AVP code 2115) is of type
    Grouped" before "The AVP is defined in OMA-DDS-Charging_Data [223]",
    printing no body: the document's own statement of the type, which the
    row's cell defers. The re-used row stays, since the definition is
    still OMA's. A clause naming another code fails.
    """
    names = {row.name for row in referred}
    titled: dict[str, _Section] = {}
    for section in sections:
        if (match := _AVP_TITLE_RE.match(section.title)) and match["name"] in names:
            titled.setdefault(match["name"], section)
    rows = []
    for row in table.rows:
        section = titled.get(row.name) if row.data_type is None else None
        if section is not None:
            opening = section.paragraphs[0].text if section.paragraphs else ""
            match = _TYPE_SENTENCE_RE.match(opening)
            if match is None or match["name"] != row.name:
                warnings.append(
                    f"{section.number}: {row.name} is typed by reference in"
                    f" table {table.table}, and its clause states no type"
                )
            elif row.code is not None and int(match["code"]) != row.code:
                raise ExtractionError(
                    f"{section.number}: {row.name} has code {match['code']},"
                    f" table {table.table} {row.code}"
                )
            else:
                data_type = _data_type(match["type"])
                row = row.model_copy(update={"data_type": data_type})
                quirks.fire("referred-type-sentences")
        rows.append(row)
    return table.model_copy(update={"rows": tuple(rows)})


_VENDOR_ID_SENTENCE = (
    "The Vendor-ID header of all AVPs defined in this specification shall be"
    " set to 3GPP (10415)."
)


def _vendor_id_sentence(
    table: ast.AvpTable, section: _Section, quirks: sources.Quirks
) -> ast.AvpTable:
    """`table` with V under Must in every row whose flag cells are all
    blank, read from its clause's sentence setting the Vendor-ID header of
    all the document's AVPs. The `vendor-id-sentence` quirk.

    Most documents print the sentence above a table whose V cells say the
    same. TS 29.389 table 6.3.1-1 leaves every flag cell of its three rows
    blank, in every version from V14.0.0 to V19.0.0, and clause 6.3.1's
    sentence is its one statement of the V bit: RFC 6733 section 4.1.1
    puts a Vendor-ID in the header exactly when V is set. The M bit stays
    blank, as printed. A row printing any flag keeps its cells.
    """
    prose = " ".join(paragraph.text for paragraph in section.paragraphs)
    if _VENDOR_ID_SENTENCE not in prose:
        raise ExtractionError(
            f"{section.number}: AVP table {table.table} sits in a clause not"
            f" saying {_VENDOR_ID_SENTENCE!r} (the `vendor-id-sentence` quirk)"
        )
    rows = []
    for row in table.rows:
        if row.flag_rules == ast.AvpFlagRules():
            vendor = ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR}))
            row = row.model_copy(update={"flag_rules": vendor})
            quirks.fire("vendor-id-sentence")
        rows.append(row)
    return table.model_copy(update={"rows": tuple(rows)})


# RFC 6733 §4.5's abbreviations, printed in TS 32.299 table 7.1.0.1 as the
# RFC extractor's `type-short-forms` reads them in RFC 6733's own table.
_TYPE_SHORT_FORMS = {"DiamIdent": "DiameterIdentity", "DiamURI": "DiameterURI"}


# TS 32.299 table 7.2.0.1 types a borrowed AVP by pointing at its definition:
# "refer [207]", once spaced and once not ("refer[223]"). Clause 7.2.0 says
# so: "for AVPs that are just borrowed from other applications only the
# reference ... is provided in the following table".
_REFER_RE = re.compile(r"refer ?\[(?P<number>\d+)\]")


_REUSED_TABLE_COLUMNS = {
    "Attribute Name": ast.ReusedColumn.NAME,
    "Reference": ast.ReusedColumn.FROM,
    "M-bit": ast.ReusedColumn.M_BIT,
    # TS 29.172 table 7.4.1-2.
    "AVP Code": ast.ReusedColumn.CODE,
    "Value Type": ast.ReusedColumn.TYPE,
}


def _reused_code(text: str, name: str) -> int | None:
    if text and not text.isdigit():
        raise ExtractionError(f"re-used AVPs row {name!r}: code cell {text!r}")
    return int(text) if text else None


def _extract_reused_table(
    table: _Table,
    warnings: list[str],
    own_reference: str,
    quirks: sources.Quirks,
    references: dict[str, str],
) -> tuple[list[ast.ReusedAvpRow], tuple[ast.ReusedColumn, ...]]:
    rows = []
    columns, positions, data_rows = _walk_table(
        table,
        _with_marks(_REUSED_TABLE_COLUMNS, ast.ReusedColumn, quirks),
        "re-used AVPs",
        warnings,
        lambda row: row.cells[0] == "" or row.cells[0].startswith("NOTE"),
    )
    for cells in data_rows:
        name, _ = _strip_note_ref(cells[0])
        if " " in name:
            # As in the AVP table: a line-wrap artifact (TS 29.154 table
            # 5.4.1's "CC-Total- Octets") is input-patched.
            raise ExtractionError(f"re-used AVPs name cell {name!r} contains spaces")
        origin: str | None = None
        m_bit: ast.MBitOverride | None = None
        code: int | None = None
        data_type: ast.DataType | None = None
        marks: dict[ast.MarkColumn, tuple[str, ...]] = {}
        for column, position in zip(columns, positions, strict=True):
            text = cells[position]
            match column:
                case ast.ReusedColumn.NAME:
                    pass  # already read, so that the M-bit check can name it
                case ast.ReusedColumn.CODE:
                    code = _reused_code(text, name)
                case ast.ReusedColumn.TYPE:
                    data_type = _data_type(text or None)
                case (
                    ast.ReusedColumn.ACCESS_TYPES
                    | ast.ReusedColumn.APPLICABILITY
                    | ast.ReusedColumn.REFERENCE_POINTS
                    | ast.ReusedColumn.ACR
                    | ast.ReusedColumn.ACA
                    | ast.ReusedColumn.CCR
                    | ast.ReusedColumn.CCA
                ):
                    marked = ast.MarkColumn(column.value)
                    found = _mark_cell(text, marked, name, quirks)
                    if found is not None:
                        marks[marked] = found
                case ast.ReusedColumn.FROM:
                    origin = _origin(text, own_reference, references, quirks)
                case ast.ReusedColumn.M_BIT:
                    if text == cells[0]:
                        # Horizontally merged row: python-docx repeats the first
                        # cell's text in the missing position (TS 29.272
                        # Battery-Indicator row).
                        warnings.append(
                            f"re-used AVPs row {name!r} has a merged M-bit cell,"
                            " treating as empty"
                        )
                        text = ""
                    if text not in _M_BIT_OVERRIDES:
                        raise ExtractionError(
                            f"re-used AVPs row {name!r}:"
                            f" unrecognized M-bit cell {text!r}"
                        )
                    m_bit = _M_BIT_OVERRIDES[text]
        if origin is None:
            raise ExtractionError(f"re-used AVPs row {name!r} has no Reference column")
        rows.append(
            ast.ReusedAvpRow(
                name=name,
                origin=origin,
                m_bit=m_bit,
                code=code,
                data_type=data_type,
                marks=marks,
            )
        )
    return rows, columns


# TS 32.299 clauses 7.3-7.5 tabulate AVPs other vendors define, each row
# pointing at its definition: "the specification including the detailed
# definition and description, is referred to" (7.3), the Reference cell
# holding a clause-2 number ("[215]"). The AVP Code column is the table's
# statement of the code, and the "Used in" columns are read behind
# `command-columns`, as in the AVP tables.
_VENDOR_TABLE_COLUMNS = {
    "AVP Name": ast.ReusedColumn.NAME,
    "AVP Code": ast.ReusedColumn.CODE,
    "Reference": ast.ReusedColumn.FROM,
}
_REFERENCE_CELL_RE = re.compile(r"\[(?P<number>\d+)\]")


def _extract_vendor_table(
    table: _Table,
    section_number: str,
    warnings: list[str],
    quirks: sources.Quirks,
    references: dict[str, str],
) -> _ReusedTable:
    """A table of other vendors' AVPs as a re-used block, the
    `vendor-avp-tables` quirk. A reference naming no document a From cell
    can cite warns and adds no row, as `refer [n]` does."""
    if table.caption is None:
        raise ExtractionError(f"{section_number}: AVP table without a caption")
    columns, positions, data_rows = _walk_table(
        table,
        _with_marks(_VENDOR_TABLE_COLUMNS, ast.ReusedColumn, quirks),
        "re-used AVPs",
        warnings,
        lambda row: row.cells[0] == "",
    )
    rows = []
    for cells in data_rows:
        named = dict(zip(columns, (cells[i] for i in positions), strict=True))
        name = named[ast.ReusedColumn.NAME]
        marks = {
            marked: found
            for column, text in named.items()
            if (marked := ast.mark_column(column)) is not None
            and (found := _mark_cell(text, marked, name, quirks)) is not None
        }
        match = _REFERENCE_CELL_RE.fullmatch(named[ast.ReusedColumn.FROM])
        if match is None:
            raise ExtractionError(
                f"{section_number}: re-used AVPs row {name!r} has Reference"
                f" cell {named[ast.ReusedColumn.FROM]!r}, which is no"
                " reference number"
            )
        entry = references.get(match["number"])
        if entry is None:
            raise ExtractionError(
                f"re-used AVPs row {name!r} refers to [{match['number']}],"
                " which clause 2 does not list"
            )
        quirks.fire("vendor-avp-tables")
        origin = _entry_document(entry)
        if origin is None:
            warnings.append(
                f"re-used AVPs row {name!r} refers to [{match['number']}],"
                " which names no document a From cell can cite; no row added"
            )
            continue
        rows.append(
            ast.ReusedAvpRow(
                name=name,
                origin=origin,
                code=_reused_code(named.get(ast.ReusedColumn.CODE, ""), name),
                marks=marks,
            )
        )
    return _ReusedTable(
        rows=rows, columns=columns, label=table.caption, section=section_number
    )
