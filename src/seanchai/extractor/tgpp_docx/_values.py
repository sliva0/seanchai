"""Value tables: the numbers a document names for a numeric AVP that is
no Enumerated, its result codes, bits and features, with the notes each
prints among its rows."""

from __future__ import annotations

import re

from ...dad import ast
from .. import sources
from ..errors import ExtractionError
from ._base import _avp_title, _Section, _Table, _ValueNotes
from ._origins import _named_document
from ._tables import _COLUMN_NOTE_RE, _strip_note_ref

# --- value tables ------------------------------------------------------------
#
# The numbers a document names for a numeric AVP that is no Enumerated: result
# codes, bits, features. The pass reads the sections on its own, so that nothing
# the rest of the extractor does with a clause bears on it.

# The clause holding a document's result codes, and its subclauses. Spelled out,
# so that "Service-Result-Code" (TS 29.336 clause 8.4.38) and "API-Result-Code
# AVP" (TS 32.299 clause 7.2.20fA), AVPs holding such values, are no such clause.
_RESULT_CLAUSE_RE = re.compile(
    r"(?:\S+ specific )?(?:Result[- ]Codes?|Experimental-Result(?:-Code)?)(?: AVP)?"
    r"(?: and Experimental-Result(?:-Code)?(?: AVP)?)?(?: [Vv]alues)?"
)
_RESULT_NAME = r"[A-Z][A-Z0-9_-]*(?: [A-Z0-9_-]+)*"
# Each wording a code takes, on a heading or on a line of its own: "DIAMETER_X
# (5001)" mostly, with a colon in TS 29.217 clause 5.5.3, "DIAMETER_X 4010" in TS
# 32.299 V11.20.0 clause 7.1.11 and "4010 DIAMETER_X" in its Release 19. A name
# may hold a space the document misprints in it (TS 29.128 clause 6.3.3.10).
# TS 29.345 clauses 6.4.3.15 and 6.4.3.16 head a code whose number is unallocated:
# "DIAMETER_ERROR_REVOCATION_FAILURE (56x1)".
_UNNUMBERED_RESULT_RE = re.compile(rf"{_RESULT_NAME} ?\(\d*x+\d*\)")
_RESULT_VALUE_RES = (
    re.compile(rf"(?P<name>{_RESULT_NAME}) ?\((?P<value>\d+)\):?"),
    re.compile(rf"(?P<name>{_RESULT_NAME}) (?P<value>\d{{4}})"),
    re.compile(rf"(?P<value>\d{{4}}) (?P<name>{_RESULT_NAME})"),
)
_BIT_LABELS = frozenset({"bit"})
# What a bit table's second column heads: TS 29.172 clause 7.4.36 "Event Type",
# clause 7.4.69 "Requirement". TS 29.272's "Bit | Description" tables have the
# name in the description (clause 7.3.31, "UTRAN Not Allowed").
_BIT_NAME_LABELS = frozenset({"name", "event type", "requirement", "description"})
_FEATURE_LABELS = frozenset({"feature bit"})
_FEATURE_NAME_LABELS = frozenset({"feature", "remote target feature"})
# "Table 7.3.10/1: Features of Feature-List-ID 1 used in S6a/S6d", TS 29.329's
# "Features of feature list 1 used in Sh", TS 29.336's with no number, and what
# the rest print after the application: TS 29.219's "used on the Sy interface",
# TS 29.468's "used for MB2-C application", TS 29.212 clause 5c.4.2's "used in St
# Protocol".
_FEATURE_CAPTION_RE = re.compile(
    r"^Table [^:]+: ?Features of (?:Feature-List-ID|feature list)(?: (?P<id>\d+))?"
    r" used (?:in|on|for) (?:the )?(?P<application>.+?)"
    r"(?: (?:interface|application|Protocol))?$"
)
# TS 29.272 clause 7.3.10.1 "Feature-List AVP for the S6a/S6d application", TS
# 29.337 clause 6.3.5 "Supported-Feature-List AVP for the T4 application", TS
# 29.368 clause 6.4.13 "Feature-Supported-In-Final-Target AVP". Every other
# feature table sits under a clause naming no AVP ("Use of the Supported-Features
# AVP on the Gx reference point") and numbers the bits of its Feature-List.
_FEATURE_AVP_RE = re.compile(r"^(?P<name>[A-Za-z0-9-]*Feature[A-Za-z0-9-]*) AVP\b")
_FEATURE_LIST = "Feature-List"
_EXPERIMENTAL_RESULT = "Experimental-Result"
_RESULT_CODE_INTRO = "following Result-Code AVP value"
# What a code's own text says defines it: "This error code is defined in 3GPP TS
# 29.229 [6]." (TS 29.283 clause 7.4.3.2), "The error code is defined in" (TS
# 29.330 clause 6.4.3.7), "This value is defined in TS 29.229 [204]" on the line
# after the code's (TS 32.299 clause 7.1.8A). "This value is defined in the
# present document" says it is the document's own.
_RESULT_DEFINED_RE = re.compile(
    r"\b(?:This|The) (?:error code|result code|value) is defined in"
    r" (?:(?P<here>the present document|this (?:document|specification))\b"
    r"|(?:the )?(?P<document>(?:(?!\. )[^,;\[])+?)\s*\[\d+\])"
)
# What an intro says of the codes after it: "the following Experimental-Result
# AVP values defined in 3GPP TS 29.273 [48] are applicable:" (TS 29.212 clause
# 5.5.3), and with no document "the following specific Gx Experimental-Result-
# Codes values are defined:", the document's own again.
_RESULT_FOLLOWING_RE = re.compile(
    r"\bfollowing\b(?:[^:\[]*?\bdefined in (?:the )?((?:(?!\. )[^:\[])+?)\s*\[\d+\])?"
)
# Behind `see-result-code-origins`: a code's clause pointing at the document
# that defines it and saying no more, in one of two shapes. A line that is the
# pointer alone, "See 3GPP TS 29.229 [6] clause 6.2.2.11." (TS 29.329 clause
# 6.2.2.8, and with no clause or full stop 6.2.2.12), and a parenthetical ending
# the line describing the code, "... is unknown (see TS 29.229 [24])." (TS
# 29.273 clauses 10.3.2 to 10.3.5). A "see" anywhere else, "For retry handling
# see TS 29.229 [6] clause 5.", points at a procedure or an encoding and names
# nothing defining the code.
_SEE_DOCUMENT = r"(?P<document>(?:3GPP |IETF )?(?:TS \d{2}\.\d{3}|RFC ?\d{4}))"
_RESULT_SEE_ALONE_RE = re.compile(
    rf"See {_SEE_DOCUMENT} \[\d+\](?: clause \d+(?:\.\d+)*)?\.?"
)
_RESULT_SEE_TERMINAL_RE = re.compile(rf"\(see {_SEE_DOCUMENT} \[\d+\]\)\.?$")
# Behind `trailing-result-codes`: a code printed as the last sentence of the
# paragraph describing the one before it, "... or is treated for offline
# charging). DIAMETER_CREDIT_LIMIT_REACHED 4012" (TS 32.299 V11.20.0 clause
# 7.1.11), which the PDF prints as an entry of its own.
_TRAILING_RESULT_RE = re.compile(rf"\. (?P<code>{_RESULT_NAME} \d{{4}})$")


def _result_row(text: str, section: str | None) -> ast.ValueRow | None:
    """The result code `text` states and nothing else, if it does. A name has an
    underscore, which is what tells it from the words of a sentence, and from TS
    32.299 V11.20.0's "Permanent Failures (5xxx):"."""
    for pattern in _RESULT_VALUE_RES:
        match = pattern.fullmatch(text)
        if match and "_" in match["name"]:
            return ast.ValueRow(
                name=match["name"], value=int(match["value"]), section=section
            )
    return None


def _with_origin(row: ast.ValueRow, origin: str | None) -> ast.ValueRow:
    return ast.ValueRow.model_validate({**row.model_dump(), "origin": origin})


def _result_origin(text: str, own_reference: str) -> str | None:
    """The document `text`, a citation, names, unless it is this one."""
    origin = _named_document(text)
    return None if origin == own_reference else origin


def _result_tables(
    sections: list[_Section],
    own_reference: str = "",
    quirks: sources.Quirks | None = None,
) -> tuple[list[ast.ValueTable], _ValueNotes]:
    """A value table per result-code clause printing any code: its subclause
    headings and its lines. TS 29.229 heads each code's clause (6.2.2.1
    "DIAMETER_ERROR_USER_UNKNOWN (5001)"), TS 29.212 lists them (clause 5.5.3).
    A heading printing no number is a note where it stood.

    The document says which AVP carries them. "Result-Code AVP values" still go
    "inside an Experimental-Result AVP" (TS 29.229 clause 6.2), so a clause
    naming it anywhere holds experimental codes, and only TS 32.299's Result-Code
    AVP (clause 7.1.11) names it nowhere. In such a clause "the following
    Result-Code AVP value defined in IETF RFC 8506" (TS 29.212 clause 5.5.3) lists
    what is no experimental code, in a table of its own, until a line names the
    experimental ones again.

    A code is another document's where its text says so: the intro over it
    names where the codes it lists are defined, or the code's own text says it
    "is defined in" one (`_RESULT_DEFINED_RE`). A pointer saying no more than
    "see" is read only behind `see-result-code-origins`. Neither says the
    document defines a code it does not, so "The Result-Code AVP values defined
    in Diameter BASE IETF RFC 6733 [61] are applicable", naming no code, is no
    origin of the ones after it. A code's own text naming this document makes
    the code local whatever its intro said.
    """
    see = quirks is not None and quirks.enabled("see-result-code-origins")
    trailing = quirks is not None and quirks.enabled("trailing-result-codes")
    tables = []
    commented: _ValueNotes = []
    position = 0
    while position < len(sections):
        root = sections[position]
        position += 1
        if not _RESULT_CLAUSE_RE.fullmatch(root.title):
            continue
        tree = [root]
        while position < len(sections) and sections[position].number.startswith(
            f"{root.number}."
        ):
            tree.append(sections[position])
            position += 1
        rows: list[ast.ValueRow] = []
        plain: list[ast.ValueRow] = []
        notes: list[tuple[int, str]] = []
        # What each code's own text said defines it, by its list and position:
        # a document, or None for this one.
        asserted: dict[tuple[int, int], str | None] = {}
        for section in tree:
            clause = None if section is root else section.number
            # The row the text read now describes, as its list and position.
            current: tuple[list[ast.ValueRow], int] | None = None
            headed = False
            if (row := _result_row(section.title, clause)) is not None:
                rows.append(row)
                current, headed = (rows, len(rows) - 1), True
            elif _UNNUMBERED_RESULT_RE.fullmatch(section.title):
                notes.append((len(rows), f"{section.title} ; {section.number}"))
            of_result_code = False
            following: str | None = None
            for line in section.lines:
                if _RESULT_CODE_INTRO in line.text:
                    of_result_code = True
                elif _EXPERIMENTAL_RESULT in line.text:
                    of_result_code = False
                row = _result_row(line.text, clause)
                if (
                    row is None
                    and trailing
                    and (glued := _TRAILING_RESULT_RE.search(line.text))
                ):
                    assert quirks is not None
                    row = _result_row(glued["code"], clause)
                    if row is not None:
                        quirks.fire("trailing-result-codes")
                if row is not None:
                    found = plain if of_result_code else rows
                    found.append(_with_origin(row, following))
                    current, headed = (found, len(found) - 1), False
                    continue
                # A code's own clause lists no codes: its "following reasons"
                # are prose (TS 29.329 clause 6.2.3.2).
                if not headed and (intro := _RESULT_FOLLOWING_RE.search(line.text)):
                    following = intro[1] and _result_origin(intro[1], own_reference)
                    current = None
                    continue
                if current is None:
                    continue
                stated = _RESULT_DEFINED_RE.search(line.text)
                pointer = (
                    _RESULT_SEE_ALONE_RE.fullmatch(line.text)
                    or _RESULT_SEE_TERMINAL_RE.search(line.text)
                    if see and headed and stated is None
                    else None
                )
                if (match := stated or pointer) is None:
                    continue
                # A citation naming no document a reading knows says nothing
                # of where the code is defined. One naming this document says
                # the code is defined here, which outweighs an intro's word on
                # the codes it lists; another document against the intro's, or
                # two the code's own text names, is two definitions.
                if match.groupdict().get("here"):
                    document = own_reference
                elif (document := _named_document(match["document"])) is None:
                    continue
                origin = None if document == own_reference else document
                found, at = current
                key = (id(found), at)
                if key in asserted:
                    said = asserted[key]
                    conflict = said != origin
                else:
                    said = found[at].origin
                    conflict = origin is not None and said not in (None, origin)
                if conflict:
                    raise ExtractionError(
                        f"{section.number}: {found[at].name} is defined in"
                        f" {said or own_reference} and in {origin or own_reference}"
                    )
                if pointer is not None:
                    assert quirks is not None
                    quirks.fire("see-result-code-origins")
                asserted[key] = origin
                found[at] = _with_origin(found[at], origin)
        experimental = _EXPERIMENTAL_RESULT in root.title or any(
            _EXPERIMENTAL_RESULT in line.text
            for section in tree
            for line in section.lines
        )
        for avp, found in (
            ("Experimental-Result-Code" if experimental else "Result-Code", rows),
            ("Result-Code", plain),
        ):
            if found:
                tables.append(
                    ast.ValueTable(
                        avp=avp,
                        kind=ast.ValueKind.RESULT_CODES,
                        source=ast.SourceRef(section=root.number),
                        rows=tuple(found),
                    )
                )
                if found is rows and notes:
                    commented.append((tables[-1], notes))
    return tables, commented


def _value_columns(
    table: _Table, labels: frozenset[str], names: frozenset[str]
) -> tuple[int, int, int | None] | None:
    """The positions of a value table's number, name and M/O columns, or None for
    any other table: a header is read as the labels it prints, its note
    references aside (TS 29.468's "Feature bit (NOTE 1)")."""
    header = [
        _COLUMN_NOTE_RE.sub("", cell).strip().casefold() for cell in table.rows[0].cells
    ]
    if header[0] not in labels or len(header) < 2:
        return None
    # The first label other than the number's: a merged cell repeats.
    name = next((i for i, label in enumerate(header) if label in names), None)
    if name is None:
        return None
    mark = next((i for i, label in enumerate(header) if label == "m/o"), None)
    return 0, name, mark


def _value_rows(
    table: _Table, columns: tuple[int, int, int | None]
) -> tuple[list[ast.ValueRow], list[tuple[int, str]]]:
    """A table's rows that name a number, and each row printing no such pair as
    the note that stands for it, with the number of rows before it: TS 29.172
    clause 7.4.69's "1-31 None", TS 29.217 clause 5.3.5's "1+n Congestion level
    1+n", TS 29.283 clause 7.3.16's "0" and nothing else. A full-width row is a
    note on the table, and prose."""
    number, name, mark = columns
    rows: list[ast.ValueRow] = []
    notes: list[tuple[int, str]] = []
    for row in table.rows[1:]:
        cells = row.cells
        if len(set(cells)) == 1 or max(number, name) >= len(cells):
            continue
        label, _ = _strip_note_ref(cells[name])
        if cells[number].isdecimal() and label:
            marked = cells[mark] if mark is not None and mark < len(cells) else ""
            rows.append(
                ast.ValueRow(name=label, value=int(cells[number]), mark=marked or None)
            )
        else:
            printed = f"{cells[number]} {label}".strip()
            notes.append((len(rows), printed))
    return rows, notes


def _value_tables(
    sections: list[_Section],
    warnings: list[str],
    quirks: sources.Quirks,
    own_reference: str = "",
) -> tuple[list[ast.ValueTable], _ValueNotes]:
    """Every value table of the document, with the notes each prints beside its
    rows (`_value_rows`)."""
    tables, commented = _result_tables(sections, own_reference, quirks)
    for section in sections:
        for table in section.tables:
            bits = _value_columns(table, _BIT_LABELS, _BIT_NAME_LABELS)
            features = _value_columns(table, _FEATURE_LABELS, _FEATURE_NAME_LABELS)
            columns = bits or features
            if columns is None:
                continue
            rows, notes = _value_rows(table, columns)
            where = f"{section.number}: table {table.caption}"
            if not rows:
                # TS 29.153 clause 5.4.2's table has its header and a blank row.
                warnings.append(f"{where} defines no value")
                continue
            if features is not None:
                found = _feature_table(section, table, rows)
            else:
                title = _avp_title(section.title, quirks)
                if title is None:
                    warnings.append(f"{where} is under no AVP's clause")
                    continue
                found = ast.ValueTable(
                    avp=title["name"],
                    kind=ast.ValueKind.BITS,
                    table=table.caption,
                    source=ast.SourceRef(section=section.number),
                    rows=tuple(rows),
                )
            tables.append(found)
            if notes:
                commented.append((found, notes))
    return tables, commented


def _feature_table(
    section: _Section, table: _Table, rows: list[ast.ValueRow]
) -> ast.ValueTable:
    avp = _FEATURE_AVP_RE.match(section.title)
    caption = _FEATURE_CAPTION_RE.match(table.caption_text or "")
    return ast.ValueTable(
        avp=avp["name"] if avp else _FEATURE_LIST,
        kind=ast.ValueKind.FEATURES,
        feature_list_id=int(caption["id"]) if caption and caption["id"] else None,
        application=caption["application"] if caption else None,
        table=table.caption,
        source=ast.SourceRef(section=section.number),
        rows=tuple(rows),
    )
