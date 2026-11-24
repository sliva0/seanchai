"""Information-element tables: a stage-3 procedure clause's per-command
table, "Information element name | Mapping to Diameter AVP | Cat. |
Description", each row an element, the AVPs it maps to and its category.

The table's header is its exact structure. Which command a table describes
is read from the clause's sentence mapping the procedure to a command pair,
and only where the clause holds the two tables of that pair; anywhere else
the block names no command and a correction supplies it.

TS 32.299 prints its commands' members so too, "AVP | Category |
Description", in the clause printing the command's ABNF, which names the
command: each row an AVP, set off a tab a level under the grouped AVP it is
a member of, and its category under TS 32.240, M, C, OM, OC or a dash for
"Not used in 3GPP"."""

from __future__ import annotations

import re

from ...dad import ast
from ..errors import ExtractionError
from ._base import _Section, _Table

# The header, by label: TS 29.272's "Information element name", TS 29.128's
# "Information Element Name", TS 29.336's "Cat" without a full stop.
_NAME_LABELS = frozenset({"information element name"})
_MAPPING_LABELS = frozenset({"mapping to diameter avp"})
_CATEGORY_LABELS = frozenset({"cat.", "cat"})
_DESCRIPTION_LABELS = frozenset({"description"})
# TS 32.299's message tables (clauses 6.2.2-6.4.5), by label.
_CATEGORY_HEADER = ("avp", "category", "description")
# The categories an "Information element name" table prints, and those TS
# 32.299's add (clauses 6.2.1.2 and 6.4.1.2: "a category as specified in TS
# 32.240").
_STAGE_3_CATEGORIES = frozenset(
    {ast.Category.MANDATORY, ast.Category.CONDITIONAL, ast.Category.OPTIONAL}
)
_CHARGING_CATEGORIES = frozenset(
    {
        ast.Category.MANDATORY,
        ast.Category.CONDITIONAL,
        ast.Category.OPERATOR_MANDATORY,
        ast.Category.OPERATOR_CONDITIONAL,
        ast.Category.NOT_USED,
    }
)

# The sentence mapping a procedure to its commands, in its three wordings:
# "This procedure is mapped to the commands Update-Location-Request/Answer
# (ULR/ULA) in the Diameter application specified in clause 7." (TS 29.272
# clause 5.2.1.1.1 and most), "mapped to the Spending-Limit-Request/Answer
# commands" (TS 29.219 clause 4.5.1.1, once with a space before the slash),
# and "mapped to the Diameter command codes Push-Profile-Request (PPR) and
# Push-Profile-Answer (PPA)" (TS 29.273 clause 8.1.2.3.1). A name printed
# with spaces, "Insert Subscriber Data-Request/Answer" (TS 29.272 clause
# 5.2.2.1.1), is no name, and an input patch hyphenates it.
_PAIR_RES = (
    re.compile(r"\bmapped to the commands (?P<name>\S+)-Request ?/ ?Answer\b"),
    re.compile(r"\bmapped to the (?P<name>\S+)-Request ?/ ?Answer commands\b"),
)
_HALVES_RE = re.compile(
    r"\bmapped to the Diameter command codes (?P<request>\S+)-Request"
    r" \([A-Z]{2,5}\) and (?P<answer>\S+)-Answer \([A-Z]{2,5}\)"
)
_NAME_RE = re.compile(f"^{ast.AVP_NAME_PATTERN}$")
# Where the sentence goes on to say the commands are specified: "in the
# Diameter application specified in TS 29.229 [5]" (TS 29.228), "specified in
# clause 7 of TS 29.272 [29]" (TS 29.273 clause 11.1.2.1.1), "specified in
# IETF RFC 6733 [23]" (TS 29.219 clause 4.5.3.1). A clause alone is the
# document's own.
_SPECIFIED_RE = re.compile(r"\bspecified in (?P<where>.*?)(?:\.\s|\.$|$)")
_DOCUMENT_RE = re.compile(
    r"\b(?:3GPP )?TS (?P<ts>\d{2}\.\d{3})\b|\b(?:IETF )?RFC ?(?P<rfc>\d+)\b"
)

# What a mapping cell prints after a name, which names nothing: a citation,
# "User-Name (See IETF RFC 6733 [61])", or a note, "Physical-Access-ID (NOTE
# 1)" (TS 29.219 table 4.5.1.1/1).
_ASIDE_RE = re.compile(r"\s*\((?:[Ss]ee|NOTE|Note)\b[^()]*\)")
# "/" or "or" offers one of two AVPs; a comma joins AVPs carried together.
_EITHER_RE = re.compile(r"\s*/\s*|\s+or\s+")
_BOTH_RE = re.compile(r"\s*,\s*")


def _header(table: _Table) -> list[str] | None:
    """The table's labels where it is an information-element table, with an
    adjacent repeat folded where the rows are that much narrower: TS 29.344
    table 5.2.1-1 prints its first label over two cells."""
    if not table.rows:
        return None
    labels = [cell.strip().lower() for cell in table.rows[0].cells]
    widths = {len(row.cells) for row in table.rows[1:]}
    if widths and len(labels) not in widths:
        folded = [
            label
            for index, label in enumerate(labels)
            if index == 0 or label != labels[index - 1]
        ]
        if len(folded) in widths:
            labels = folded
    if (
        len(labels) == 4
        and labels[0] in _NAME_LABELS
        and labels[1] in _MAPPING_LABELS
        and labels[2] in _CATEGORY_LABELS
        and labels[3] in _DESCRIPTION_LABELS
    ):
        return labels
    return None


def _mapping(text: str) -> tuple[tuple[str, ...], bool, str | None]:
    """A mapping cell as names, whether it offers one of them, and as
    printed where it names no AVP: TS 29.273's "EAP payload", or a name the
    document misprints with a space ("Trace- Reference")."""
    if not text:
        return (), False, None
    cleaned = _ASIDE_RE.sub("", text).strip()
    either = bool(_EITHER_RE.search(cleaned))
    both = bool(_BOTH_RE.search(cleaned))
    if either and both:
        return (), False, text
    parts = (_EITHER_RE if either else _BOTH_RE).split(cleaned)
    names = tuple(part.removesuffix(" AVP") for part in parts)
    if not all(_NAME_RE.match(name) for name in names):
        return (), False, text
    return names, either, None


def _rows(table: _Table, section: str, warnings: list[str]) -> list[ast.ElementRow]:
    rows = []
    for row in table.rows[1:]:
        cells = row.cells
        if len(set(cells)) == 1:
            continue  # a full-width NOTE row, prose
        if len(cells) != 4:
            raise ExtractionError(
                f"{section}: information elements table {table.caption} has a row"
                f" of {len(cells)} cells: {cells!r}"
            )
        name, mapping, category, _ = cells
        if not name:
            warnings.append(
                f"{section}: information elements table {table.caption} has a row"
                f" naming no element, skipped: {cells[:3]!r}"
            )
            continue
        if category and category not in _STAGE_3_CATEGORIES:
            raise ExtractionError(
                f"{section}: information element {name!r} has category"
                f" {category!r}, none of M, C and O"
            )
        avps, either, printed = _mapping(mapping)
        rows.append(
            ast.ElementRow(
                name=name,
                avps=avps,
                either=either,
                printed=printed,
                category=ast.Category(category) if category else None,
            )
        )
    return rows


def _category_rows(table: _Table, section: str) -> list[ast.ElementRow]:
    """A TS 32.299 message table's rows: the AVP, its category, and how many
    tabs set it off, its depth."""
    rows = []
    for row in table.rows[1:]:
        cells = row.cells
        if len(set(cells)) == 1:
            continue  # a blank or full-width row
        if len(cells) != 3:
            raise ExtractionError(
                f"{section}: message table {table.caption} has a row of"
                f" {len(cells)} cells: {cells!r}"
            )
        avp, category, _ = cells
        if category and category not in _CHARGING_CATEGORIES:
            raise ExtractionError(
                f"{section}: {avp!r} in table {table.caption} has category"
                f" {category!r}, none of M, C, OM, OC and a dash"
            )
        avps, either, printed = _mapping(avp)
        try:
            rows.append(
                ast.ElementRow(
                    avps=avps,
                    either=either,
                    printed=printed,
                    category=ast.Category(category) if category else None,
                    depth=row.indent,
                )
            )
        except ValueError as error:
            raise ExtractionError(
                f"{section}: table {table.caption}: {error}"
            ) from None
    return rows


def _category_tables(
    sections: list[_Section], commands: dict[str, list[str]]
) -> list[ast.InformationElements]:
    """TS 32.299's message tables, each naming the command the clause prints
    the ABNF of, where it prints one."""
    found = []
    for section in sections:
        for table in section.tables:
            labels = tuple(cell.strip().lower() for cell in table.rows[0].cells)
            if labels != _CATEGORY_HEADER:
                continue
            table.claimed = True
            printed = commands.get(section.number, [])
            try:
                found.append(
                    ast.InformationElements(
                        command=printed[0] if len(printed) == 1 else None,
                        table=table.caption,
                        source=ast.SourceRef(section=section.number),
                        rows=tuple(_category_rows(table, section.number)),
                    )
                )
            except ValueError as error:
                raise ExtractionError(
                    f"{section.number}: table {table.caption}: {error}"
                ) from None
    return found


def _specifying(text: str, own: str) -> str | None:
    """The document `text`, the sentence after its command pair, says
    specifies the commands, or None for the document's own clause."""
    specified = _SPECIFIED_RE.search(text)
    if specified is None:
        return None
    document = _DOCUMENT_RE.search(specified["where"])
    if document is None:
        return None
    reference = f"TS{document['ts']}" if document["ts"] else f"RFC{document['rfc']}"
    return None if reference == own else reference


def _commands(section: _Section, own: str) -> tuple[str, str, str | None] | None:
    """The request and answer the clause's sentence maps its procedure to,
    and the document it says specifies them, or None where it names none or
    several pairs."""
    pairs: set[tuple[str, str, str | None]] = set()
    for paragraph in section.paragraphs:
        text = paragraph.text
        for pattern in _PAIR_RES:
            for match in pattern.finditer(text):
                pairs.add(
                    (
                        f"{match['name']}-Request",
                        f"{match['name']}-Answer",
                        _specifying(text[match.end() :], own),
                    )
                )
        for match in _HALVES_RE.finditer(text):
            pairs.add(
                (
                    f"{match['request']}-Request",
                    f"{match['answer']}-Answer",
                    _specifying(text[match.end() :], own),
                )
            )
    named = {pair for pair in pairs if all(map(_NAME_RE.match, pair[:2]))}
    return named.pop() if len(named) == 1 and len(pairs) == 1 else None


def _element_tables(
    sections: list[_Section],
    warnings: list[str],
    own: str,
    commands: dict[str, list[str]],
) -> list[ast.InformationElements]:
    """Every information-element table of the document, in document order.
    A clause mapping its procedure to one command pair and holding two
    tables gives the first the request and the second the answer; a TS
    32.299 message table describes the command whose ABNF its clause prints,
    `commands` by clause."""
    found = _category_tables(sections, commands)
    for section in sections:
        tables = [table for table in section.tables if _header(table) is not None]
        if not tables:
            continue
        pair = _commands(section, own)
        if pair is not None and len(tables) != 2:
            warnings.append(
                f"{section.number}: {len(tables)} information elements tables"
                f" under one command pair, {pair[0]}/Answer; a correction names"
                " each table's command"
            )
            pair = None
        for position, table in enumerate(tables):
            table.claimed = True
            rows = _rows(table, section.number, warnings)
            if not rows:
                warnings.append(
                    f"{section.number}: information elements table"
                    f" {table.caption} holds no element"
                )
                continue
            found.append(
                ast.InformationElements(
                    command=None if pair is None else pair[position],
                    origin=None if pair is None else pair[2],
                    table=table.caption,
                    source=ast.SourceRef(section=section.number),
                    rows=tuple(rows),
                )
            )
    return found


# A procedure's table of the result codes its answer may carry, "Result-Code
# AVP value | Condition" (TS 29.228 table 6.2.2.1.1), by label.
_RESULT_CODE_HEADER = ("result-code avp value", "condition")


def _parent(section: str) -> str:
    return section.rpartition(".")[0]


def _result_code_tables(
    sections: list[_Section], elements: list[ast.InformationElements]
) -> list[ast.CommandResultCodes]:
    """Each table of the result codes a procedure's answer may carry, in a
    procedure's "Detailed behaviour" clause (TS 29.228 6.2.2.1, TS 29.273
    8.1.2.3.3), naming the answer the procedure's information-element
    tables describe, in the clause above (6.2.2) or beside it (8.1.2.3.1),
    where exactly one of them describes an answer; else none, and a
    correction names it."""
    found = []
    for section in sections:
        for table in section.tables:
            labels = tuple(cell.strip().lower() for cell in table.rows[0].cells)
            if labels != _RESULT_CODE_HEADER:
                continue
            table.claimed = True
            above = _parent(section.number)
            answers = [
                block
                for block in elements
                if block.command is not None
                and block.command.endswith("-Answer")
                and block.avp is None
                and (
                    block.source.section == above
                    or _parent(block.source.section) == above
                )
            ]
            answer = answers[0] if len(answers) == 1 else None
            names = [
                row.cells[0]
                for row in table.rows[1:]
                if len(set(row.cells)) > 1 and row.cells[0]
            ]
            if not names:
                continue
            found.append(
                ast.CommandResultCodes(
                    command=None if answer is None else answer.command,
                    application_id=None if answer is None else answer.application_id,
                    command_section=None if answer is None else answer.command_section,
                    origin=None if answer is None else answer.origin,
                    table=table.caption,
                    source=ast.SourceRef(section=section.number),
                    rows=tuple(ast.ResultCodeRow(name=name) for name in names),
                )
            )
    return found
