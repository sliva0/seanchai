"""`seanchai export`: the resolved corpus as JSON for the static site.

The export holds every file's text as token spans, each name's resolution
target, the holes, the linter's findings, each correction's reason and a
search index. `export_schema` defines the shape; see docs/website.md.

The output depends only on the corpus, its corrections record, the catalog
and the grammar: no timestamps, no absolute paths, the same bytes under any
hash seed. An export replaces its output directory whole.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import tempfile
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import pydantic

from . import _correction_record, export_schema, model
from .corpus import (
    CitationRule,
    Corpus,
    CorpusError,
    CorpusNotInstalledError,
    CrossRelease,
    Entry,
    installed_directory,
)
from .dad import abnf, ast, corrections, formatter, parser
from .downloader.catalog import Catalog, load_catalog
from .export_schema import (
    GENERATOR,
    SCHEMA_VERSION,
    Allocation,
    ApplicationIdentity,
    AvpHeader,
    AvpIdentity,
    Block,
    Citation,
    Command,
    CommandIdentity,
    CommandSpan,
    Document,
    DocumentSummary,
    EnumEntry,
    Finding,
    FlagRules,
    Hole,
    Index,
    Line,
    Member,
    Mention,
    RawDocument,
    RegistryIdentity,
    Reservation,
    Rule,
    Search,
    SearchEntry,
    Section,
    Source,
    TableRow,
    Target,
    Token,
    UndefinedBlock,
    ValueIdentity,
    ValueRow,
)
from .linter import lint_with_corpus

__all__ = ["export_corpus"]

# What a line is split on to find the spans worth marking. A comment, a URL and
# a quoted string come first, so that nothing inside them is taken for a name.
# Everything between matches stays plain text; classing it is the grammar's job.
_WORD = re.compile(
    r';;[^\n]*?(?=;;|\n|$)|https?://[^\s]+|"(?:[^"\\]|\\.)*"'
    r"|[A-Za-z0-9_]+(?:[.\-/][A-Za-z0-9_*]+)*"
)
_CORRECTION = re.compile(r"\(([\w.-]+\.py#[\w-]+)\)")
_DIRECTIVE = re.compile(r"; ([\w-]+):")
# The TextMate grammar's source of truth, package data as `specs.toml` is.
_GRAMMAR = Path(__file__).resolve().parent / "dad" / "syntax" / "dad.tmLanguage.json"
# Where an export carries it.
SYNTAX_FILE = "syntax/dad.tmLanguage.json"


def document_id(entry: Entry) -> str:
    """A document's name in the export, and in its URLs: its file's stem."""
    return entry.path.stem


def _avp_names(spec: ast.Specification) -> set[str]:
    """Every name `spec` uses as an AVP."""
    names = set()
    for section in spec.sections:
        if isinstance(
            section,
            ast.GroupedAvp | ast.ReprintedAvp | ast.EnumeratedAvp | ast.UndefinedAvp,
        ):
            names.add(section.name)
        if isinstance(section, ast.AvpTable | ast.ReusedAvps):
            names.update(row.name for row in section.rows)
        if isinstance(
            section,
            ast.GroupedAvp | ast.ReprintedAvp | ast.Message | ast.AnswerMessage,
        ):
            names.update(rule.name for rule in section.avps if rule.name != "AVP")
    return names


def _citations(spec: ast.Specification) -> dict[str, Citation]:
    """Return every clause `spec` places something in, with its page. A clause
    only a table row names takes its table's page."""
    found: dict[str, Citation] = {}
    for section in spec.sections:
        source = section.source
        found.setdefault(
            source.section, Citation(section=source.section, page=source.page)
        )
    for section in spec.sections:
        if isinstance(section, ast.AvpTable):
            for row in section.rows:
                if row.section:
                    found.setdefault(
                        row.section,
                        Citation(section=row.section, page=section.source.page),
                    )
        if isinstance(section, ast.ValueTable):
            for row in section.rows:
                if row.section:
                    found.setdefault(
                        row.section,
                        Citation(section=row.section, page=section.source.page),
                    )
    return found


def _block_title(section: ast.Section) -> str:
    """A block's `; Type:` plus its `; Name:` (definition), `; AVP:` (value
    table) or re-used names (re-used rows from prose)."""
    name = section.avp if isinstance(section, ast.ValueTable) else None
    if isinstance(section, ast.ReusedAvps) and section.table is None:
        name = ", ".join(row.name for row in section.rows)
    name = getattr(section, "name", name)
    return section.type if name is None else f"{section.type} {name}"


def _sections(
    spec: ast.Specification, citations: dict[str, Citation]
) -> tuple[Section, ...]:
    """Return `citations` in document order, each with what the file places
    there. A clause with several blocks names each kind once; a clause only
    table rows name takes its first row's."""
    blocks: dict[str, dict[str, None]] = {}
    for section in spec.sections:
        blocks.setdefault(section.source.section, {})[_block_title(section)] = None
    rows: dict[str, list[str]] = {}
    for section in spec.sections:
        if isinstance(section, ast.AvpTable):
            for row in section.rows:
                if row.section:
                    rows.setdefault(row.section, []).append(f"AVP {row.name}")
        if isinstance(section, ast.ValueTable):
            for row in section.rows:
                if row.section:
                    rows.setdefault(row.section, []).append(f"Value {row.name}")

    def title(clause: str) -> str:
        if clause in blocks:
            return ", ".join(blocks[clause])
        first, *others = rows[clause]
        return first + (f" and {len(others)} more" if others else "")

    return tuple(
        Section(section=clause, page=citations[clause].page, title=title(clause))
        for clause in sorted(citations, key=ast.section_sort_key)
    )


def _locations(spec: ast.Specification) -> dict[str, str]:
    """Where each AVP `spec` places is defined, a definition over a table row."""
    places: dict[str, str] = {}
    for section in spec.sections:
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
            places[section.name] = section.source.section
    for section in spec.sections:
        if isinstance(section, ast.AvpTable):
            for row in section.rows:
                places.setdefault(row.name, row.section or section.source.section)
    return places


@dataclass(frozen=True)
class _Links:
    """What the names in one document's text link to."""

    entry: Entry
    # An AVP's target, None for a hole; a command or application named outside
    # its own clause, where its name means one clause.
    names: dict[str, Target | None]
    # A cited document's page.
    references: dict[str, Target]
    # A re-used row's origin cell, by (origin, row name): the AVP there.
    row_references: dict[tuple[str, str], Target]

    def value_origin(self, origin: str, name: str) -> Target | None:
        """Where a result code's `from` document links: the clause listing
        the code there, else the document, at the row named `name`."""
        found = self.row_references.get((origin, name))
        if found is None and origin in self.references:
            found = self.references[origin].model_copy(update={"name": name})
        return found

    def spelled_as_raw(self, renames: tuple[_correction_record.Rename, ...]) -> _Links:
        """These links for the raw file, with renamed names linked through the
        rename."""
        names = dict(self.names)
        row_references = dict(self.row_references)
        for rename in reversed(renames):
            if not names.get(rename.expect) and rename.replace in names:
                names[rename.expect] = names[rename.replace]
                for (reference, name), target in list(row_references.items()):
                    if name == rename.replace:
                        row_references[reference, rename.expect] = target
        return _Links(self.entry, names, self.references, row_references)


def _table_row(
    section: ast.Section | None, line: str
) -> ast.AvpTableRow | ast.ReusedAvpRow | None:
    """The table row `line` prints, if `section` is a table and it prints one."""
    if not isinstance(section, ast.AvpTable | ast.ReusedAvps) or line.startswith(
        (";", " ", "\n")
    ):
        return None
    return next((row for row in section.rows if line.startswith(row.name + " ")), None)


def _value_row(section: ast.Section | None, line: str) -> ast.ValueRow | None:
    """The value row `line` prints, if `section` is a value table and it prints
    one."""
    if not isinstance(section, ast.ValueTable) or line.startswith(";"):
        return None
    return next(
        (
            row
            for row in section.rows
            if line.startswith(f"{formatter.value_name(row.name)} ")
        ),
        None,
    )


def _lines(
    text: str,
    spec: ast.Specification,
    links: _Links,
    changed: frozenset[int] = frozenset(),
) -> tuple[Line, ...]:
    """Return `text` (parsed as `spec`) line by line in token spans.

    Each `; Type:` line starts the next section of `spec`. `changed` holds
    the indexes of raw lines the corrected file changes.
    """
    lines = []
    block = -1
    anchored: set[str] = set()
    defined_sections = {section.source.section for section in spec.sections}
    avp_names = _avp_names(spec) | {
        section.avp for section in spec.sections if isinstance(section, ast.ValueTable)
    }
    for index, line in enumerate(text.splitlines(keepends=True)):
        if line.startswith("; Type:"):
            block += 1
        section = spec.sections[block] if block >= 0 else None
        source = section.source if section is not None else None
        row = _table_row(section, line)
        value = _value_row(section, line)
        anchor = None
        if source and line.startswith("; Type:"):
            anchor = source.section
        elif isinstance(row, ast.AvpTableRow) and row.section not in defined_sections:
            anchor = row.section
        elif value is not None and value.section not in defined_sections:
            anchor = value.section
        if anchor in anchored:
            anchor = None
        if anchor:
            anchored.add(anchor)
        lines.append(
            Line(
                tokens=_tokens(line, section, row, value, avp_names, links),
                anchor=anchor,
                section=source.section if source else None,
                warning=index in changed,
            )
        )
    return tuple(lines)


def _tokens(
    line: str,
    section: ast.Section | None,
    row: ast.AvpTableRow | ast.ReusedAvpRow | None,
    value_row: ast.ValueRow | None,
    avp_names: set[str],
    links: _Links,
) -> tuple[Token, ...]:
    """One line's spans: what links or says something, and plain text between."""
    source = section.source if section is not None else None
    directive = _DIRECTIVE.match(line)
    key = directive[1] if directive else None
    naming = key in (None, "Name", "AVP") and not (
        isinstance(section, ast.EnumeratedAvp | ast.ValueTable) and " = " in line
    )
    # A command or application names its own clause, whatever else in the file
    # shares its name: TS 29.212 defines CC-Request once per interface.
    own = (
        {
            section.name: Target(
                document=document_id(links.entry), section=section.source.section
            )
        }
        if isinstance(section, ast.Message | ast.ApplicationScope)
        else {}
    )
    tokens: list[Token] = []
    end = 0
    for match in _WORD.finditer(line):
        value = match[0]
        fields: dict[str, Any] = {}
        if value in avp_names and naming:
            fields["avp"] = value
        if value.startswith(";;"):
            correction = _CORRECTION.search(value)
            fields["kind"] = "correction-note" if correction else "comment"
            if correction:
                fields["correction"] = correction[1]
        elif directive and match.start() < directive.end():
            pass
        elif key in ("Section", "Page") and source:
            fields["source"] = Citation(section=source.section, page=source.page)
        elif value in links.references and key in ("Bases", "From", None):
            fields["target"] = links.references[value]
            if isinstance(section, ast.ReusedAvps) and key is None:
                fields["target"] = links.row_references.get(
                    (value, line.split(maxsplit=1)[0]), fields["target"]
                )
            elif value_row is not None and key is None:
                fields["target"] = links.value_origin(value, value_row.name)
        elif naming and (target := own.get(value) or links.names.get(value)):
            fields["target"] = target
        if value_row is not None and source:
            # A value's name is defined where it stands, in its own clause.
            if match.start() == 0:
                fields["target"] = Target(
                    document=document_id(links.entry),
                    section=value_row.section or source.section,
                )
            elif value == value_row.section:
                fields["source"] = Citation(section=value, page=source.page)
        if row and source and match.start() == 0 and value == row.name:
            fields["source"] = Citation(
                section=source.section, page=source.page, name=value, row=True
            )
        elif (
            isinstance(row, ast.AvpTableRow)
            and source
            and row.section
            and value == row.section
        ):
            fields["source"] = Citation(section=row.section, page=source.page)
        if fields:
            if match.start() > end:
                tokens.append(Token(text=line[end : match.start()]))
            tokens.append(Token(text=value, **fields))
            end = match.end()
    if end < len(line):
        tokens.append(Token(text=line[end:]))
    return tuple(tokens)


# The sections whose block holds an ABNF rule.
_RULED = (ast.Message, ast.AnswerMessage, ast.GroupedAvp, ast.ReprintedAvp)


def _content(line: str) -> str:
    """`line` without its comment, as the parser reads it."""
    return line.split(";;", 1)[0].rstrip()


def _member(
    rule: ast.AvpRule, qualifier: str, index: int, struck: bool = False
) -> Member:
    """`rule` as a member, with RFC 6733 clause 3.2's bounds: no qualifier is
    exactly one of a fixed or required member and at most one of an optional
    one; a qualifier's missing min is 0, but a required member is there at
    least once, and its missing max is no bound."""
    if qualifier:
        least, most = rule.min_occurs, rule.max_occurs
        if rule.presence is ast.Presence.REQUIRED:
            least = max(1, least)
    else:
        least = 0 if rule.presence is ast.Presence.OPTIONAL else 1
        most = 1
    return Member(
        name=rule.name,
        presence=rule.presence,
        qualifier=qualifier,
        min=least,
        max=most,
        bold=rule.bold,
        strikethrough=rule.strikethrough and not struck,
        struck=struck,
        line=index,
    )


def _commands_of(spec: ast.Specification) -> dict[int, Command]:
    """Each Message section's header, by section index, its application as
    `Model.applications` names it: the effective id from the first scope
    covering its clause, named by the first scope stating that id among the
    commands of its interface's clause."""
    scopes = [s for s in spec.sections if isinstance(s, ast.ApplicationScope)]
    covering: dict[int, ast.ApplicationScope | None] = {}
    effective: dict[int, int | None] = {}
    stating: dict[tuple[int | None, str], ast.ApplicationScope] = {}
    for index, section in enumerate(spec.sections):
        if not isinstance(section, ast.Message):
            continue
        scope = next((s for s in scopes if s.covers(section.source.section)), None)
        covering[index] = scope
        found = section.application_id
        if found is None and scope is not None:
            found = scope.application_id
        effective[index] = found
        if scope is not None and scope.application_id == found:
            key = (found, ast.interface_clause(section.source.section))
            stating.setdefault(key, scope)
    commands = {}
    for index, found in effective.items():
        section = spec.sections[index]
        assert isinstance(section, ast.Message)
        named = stating.get((found, ast.interface_clause(section.source.section)))
        # A bare header's id is the covering block's statement, so that block's
        # clause is the one to cite; a printed id's is the clause naming it.
        cited = named if section.application_id is not None else covering[index]
        commands[index] = Command(
            code=section.command_code,
            request=ast.CommandFlag.REQUEST in section.flags,
            flags=tuple(flag for flag in ast.CommandFlag if flag in section.flags),
            header_application_id=section.application_id,
            application_id=found,
            application=None if named is None else named.name,
            application_clause=None
            if named is None or cited is None
            else cited.source.section,
        )
    return commands


def _halves(
    name: str, start: int, abbreviation: str | None
) -> list[tuple[int, int, str, bool, str | None]]:
    """A Command Codes name cell's halves, `User-Authorization-Request/-Answer`
    or `Insert Subscriber Data-Request/Answer`, as spans from `start` and the
    names they stand for, request first, each with its abbreviation where the
    cell's `UAR/UAA` gives one per half. A name with no slash is one half,
    whichever its name ends in."""
    slash = name.find("/")
    if slash < 0:
        request = (
            True
            if name.endswith("-Request")
            else False
            if name.endswith("-Answer")
            else None
        )
        if request is None:
            return []
        short = None if abbreviation is None or "/" in abbreviation else abbreviation
        return [(start, start + len(name), name, request, short)]
    first = name[:slash]
    second = name[slash + 1 :].removeprefix("-")
    answer = (
        first.removesuffix("Request") + second if first.endswith("Request") else second
    )
    shorts = (abbreviation or "").split("/")
    pair = shorts if len(shorts) == 2 else [None, None]
    return [
        (start, start + slash, first, True, pair[0]),
        (start + len(name) - len(second), start + len(name), answer, False, pair[1]),
    ]


@dataclass(frozen=True)
class _Placed:
    """One file's text, tree and layout, as `_blocks` reads them: 0-based line
    indexes throughout."""

    lines: list[str]
    spec: ast.Specification
    layout: parser.Layout
    links: _Links
    # A body item's line, by section index, field and item index.
    items: dict[tuple[int, str, int], int]
    # A section's header rule line, by section index.
    heads: dict[int, int]

    @classmethod
    def of(
        cls, text: str, spec: ast.Specification, layout: parser.Layout, links: _Links
    ) -> _Placed:
        items: dict[tuple[int, str, int], int] = {}
        heads: dict[int, int] = {}
        for lineno, path in layout.paths.items():
            match path:
                case ("sections", int(section)):
                    heads[section] = lineno - 1
                case ("sections", int(section), str(field), int(item)):
                    items[section, field, item] = lineno - 1
        return cls(text.splitlines(), spec, layout, links, items, heads)

    def cells(self, line: int) -> tuple[str, ...]:
        """The cells table row `line` prints, as printed."""
        return tuple(self.lines[line][a:b] for a, b in self.layout.cells[line + 1])


def _blocks(
    text: str, spec: ast.Specification, layout: parser.Layout, links: _Links
) -> tuple[Block, ...]:
    """`spec`'s sections as blocks of `text`'s lines, which `layout` places."""
    placed = _Placed.of(text, spec, layout, links)
    commands = _commands_of(spec)
    # A table's column names one of the file's commands by its abbreviation:
    # the first Message block of that abbreviation.
    abbreviations: dict[str, int] = {}
    for index, section in enumerate(spec.sections):
        if isinstance(section, ast.Message):
            abbreviations.setdefault(section.abbreviation, index)
    blocks = []
    for index, (section, placement) in enumerate(
        zip(spec.sections, layout.sections, strict=True)
    ):
        fields: dict[str, Any] = {
            "type": section.type,
            "line": placement.first - 1,
            "last": placement.last - 1,
            "section": section.source.section,
            "page": section.source.page,
            "fields": {
                key: value
                for key, (_, value) in placement.directives.items()
                if key != "Type"
            },
        }
        spans: list[CommandSpan] = []
        if isinstance(section, ast.ValueTable):
            fields["name"] = section.avp
            fields["value_kind"] = section.kind
            fields["feature_list_id"] = section.feature_list_id
            fields["application"] = section.application
            # What the `; AVP:` line's name links to, as `_tokens` links it.
            fields["avp_target"] = links.names.get(section.avp)
            fields["value_rows"] = _value_rows(placed, index, section)
        elif not isinstance(section, ast.AvpTable | ast.ReusedAvps | ast.Registry):
            fields["name"] = getattr(section, "name", None)
        if isinstance(section, _RULED):
            fields["rule"] = _rule(placed, index, placement, section)
        if isinstance(section, ast.GroupedAvp | ast.ReprintedAvp | ast.EnumeratedAvp):
            fields["avp"] = AvpHeader(code=section.code, vendor_id=section.vendor_id)
        if isinstance(section, ast.EnumeratedAvp):
            fields["values"] = _enum_entries(placed, index, section)
        if isinstance(section, ast.Message):
            fields["abbreviation"] = section.abbreviation
            fields["command"] = commands[index]
            spans += _message_spans(placed, index, placement, section, commands[index])
        if isinstance(section, ast.AvpTable | ast.ReusedAvps | ast.Registry):
            fields["columns"] = tuple(column.value for column in section.columns)
        if isinstance(section, ast.AvpTable | ast.ReusedAvps):
            fields["rows"] = _table_rows(placed, index, section)
            spans += _column_spans(placed.lines, spec, placement, abbreviations)
        if isinstance(section, ast.Registry):
            fields["allocations"], fields["reservations"], registry_spans = _registry(
                placed, index, section
            )
            spans += registry_spans
        fields["commands"] = tuple(spans)
        blocks.append(Block(**fields))
    return tuple(blocks)


def _rule(
    placed: _Placed,
    index: int,
    placement: parser.Placement,
    section: ast.Message | ast.AnswerMessage | ast.GroupedAvp | ast.ReprintedAvp,
) -> Rule:
    """A block's rule: its members as their lines print them, the struck
    ones the extractor comments out (TS 32.299 clause 6.2.2) included."""
    head = placed.heads[index]
    live = {
        placed.items[index, "avps", item]: rule
        for item, rule in enumerate(section.avps)
    }
    members = []
    for line in range(head + 1, placement.last):
        content = _content(placed.lines[line])
        rule = live.get(line)
        if rule is not None:
            read = parser.avp_rule_line(content)
            qualifier = (
                abnf.qualifier(rule.min_occurs, rule.max_occurs)
                if read is None
                else read[1]
            )
            members.append(_member(rule, qualifier, line))
        elif not content:
            struck = parser.avp_rule_line(
                _content(placed.lines[line].lstrip().removeprefix(";;"))
            )
            if struck is not None and struck[0].strikethrough:
                members.append(_member(*struck, line, struck=True))
    return Rule(
        name=getattr(section, "name", "answer-message"),
        line=head,
        members=tuple(members),
    )


def _enum_entries(
    placed: _Placed, index: int, section: ast.EnumeratedAvp
) -> tuple[EnumEntry, ...]:
    entries = []
    for item, entry in enumerate(section.values):
        line = placed.items[index, "values", item]
        if isinstance(entry, ast.EnumValue):
            entries.append(
                EnumEntry(
                    line=line,
                    kind="value",
                    name=entry.name,
                    first=entry.value,
                    last=entry.value,
                    description=entry.description,
                )
            )
            continue
        kind: Literal["reserved", "void", "vendor-specific"] = (
            "reserved"
            if isinstance(entry, ast.ReservedValues)
            else "void"
            if isinstance(entry, ast.VoidValues)
            else "vendor-specific"
        )
        entries.append(
            EnumEntry(
                line=line,
                kind=kind,
                first=entry.first,
                last=entry.last,
                description=getattr(entry, "description", None),
            )
        )
    return tuple(entries)


def _message_spans(
    placed: _Placed,
    index: int,
    placement: parser.Placement,
    section: ast.Message,
    command: Command,
) -> list[CommandSpan]:
    """Where a Message block names its command: its `; Name:` name and
    abbreviation, and its rule's head."""
    name_line, value = placement.directives["Name"]
    # The value is found on its line: any run of spaces may precede it.
    start = placed.lines[name_line - 1].index(value)
    head = placed.heads[index]
    places = (
        (name_line - 1, start + value.index(section.name), section.name),
        (
            name_line - 1,
            start + value.rindex(section.abbreviation),
            section.abbreviation,
        ),
        (head, placed.lines[head].index(section.name), section.name),
    )
    return [
        CommandSpan(
            line=line,
            start=at,
            end=at + len(spelled),
            code=command.code,
            request=command.request,
            name=section.name,
            abbreviation=section.abbreviation,
            block=index,
        )
        for line, at, spelled in places
    ]


def _column_spans(
    lines: list[str],
    spec: ast.Specification,
    placement: parser.Placement,
    abbreviations: dict[str, int],
) -> list[CommandSpan]:
    """Where a table's `; Columns:` names a command of the file, as TS
    32.299's ACR to CCA columns do."""
    line, value = placement.directives["Columns"]
    start = lines[line - 1].index(value)
    spans = []
    for match in re.finditer(r"\S+", value):
        found = abbreviations.get(match[0])
        if found is None:
            continue
        message = spec.sections[found]
        assert isinstance(message, ast.Message)
        spans.append(
            CommandSpan(
                line=line - 1,
                start=start + match.start(),
                end=start + match.end(),
                code=message.command_code,
                request=ast.CommandFlag.REQUEST in message.flags,
                name=message.name,
                abbreviation=message.abbreviation,
                block=found,
            )
        )
    return spans


def _table_rows(
    placed: _Placed, index: int, section: ast.AvpTable | ast.ReusedAvps
) -> tuple[TableRow, ...]:
    return tuple(
        TableRow(
            line=placed.items[index, "rows", item],
            name=row.name,
            cells=placed.cells(placed.items[index, "rows", item]),
            code=row.code,
            type=row.data_type,
            vendor=row.stated_vendor(placed.spec.vendor_id)
            if isinstance(row, ast.AvpTableRow)
            else None,
            marks=row.marks,
        )
        for item, row in enumerate(section.rows)
    )


def _registry(
    placed: _Placed, index: int, section: ast.Registry
) -> tuple[tuple[Allocation, ...], tuple[Reservation, ...], list[CommandSpan]]:
    """A registry's rows and reservations, and where a Command Codes row
    names its commands."""
    allocations = []
    reservations = []
    spans = []
    references = placed.links.references
    for item, row in enumerate(section.rows):
        allocation = len(allocations)
        line = placed.items[index, "rows", item]
        if isinstance(row, ast.RegistryReservation):
            reservations.append(
                Reservation(
                    line=line,
                    first=row.first,
                    last=row.last,
                    defined_in=row.defined_in,
                    purpose=row.purpose,
                )
            )
            continue
        allocations.append(
            Allocation(
                line=line,
                cells=placed.cells(line),
                code=row.code,
                name=row.name,
                abbreviation=row.abbreviation,
                type=row.data_type,
                documents=tuple(
                    dict.fromkeys(
                        references[reference].document
                        for reference in row.defined_in
                        if reference in references
                    )
                ),
                vendor=placed.spec.vendor_id
                if section.registry is ast.RegistryKind.AVP_CODES
                else None,
            )
        )
        if section.registry is ast.RegistryKind.COMMAND_CODES:
            spans += _registry_spans(placed, section, row, line, allocation)
    return tuple(allocations), tuple(reservations), spans


def _registry_spans(
    placed: _Placed,
    section: ast.Registry,
    row: ast.RegistryRow,
    line: int,
    allocation: int,
) -> list[CommandSpan]:
    """Where a Command Codes row's name and abbreviation cells name its
    request and answer (TS 29.230 table 5.1/1's `UAR/UAA`); `allocation` is
    the row's index among the block's allocations."""
    if row.code is None or row.name is None:
        return []
    columns = [column.value for column in section.columns]
    cells = placed.layout.cells[line + 1]
    name_at = cells[columns.index(ast.RegistryColumn.NAME.value)]
    printed = placed.lines[line][slice(*name_at)]
    quoted = int(printed.startswith('"'))
    if printed[quoted : len(printed) - quoted] != row.name:
        return []  # an escape inside the quotes would move every offset
    abbreviation = (
        placed.lines[line][
            slice(*cells[columns.index(ast.RegistryColumn.ABBREVIATION.value)])
        ]
        if ast.RegistryColumn.ABBREVIATION in section.columns
        else None
    )
    abbreviation_at = (
        cells[columns.index(ast.RegistryColumn.ABBREVIATION.value)][0]
        if abbreviation is not None
        else 0
    )
    places = []
    for position, (start, end, name, request, short) in enumerate(
        _halves(row.name, name_at[0] + quoted, row.abbreviation)
    ):
        places.append((start, end, name, request, short))
        if short and abbreviation is not None:
            offset = abbreviation.find(short, abbreviation.find("/") if position else 0)
            if offset >= 0:
                at = abbreviation_at + offset
                places.append((at, at + len(short), name, request, short))
    return [
        CommandSpan(
            line=line,
            start=start,
            end=end,
            code=row.code,
            request=request,
            name=name,
            abbreviation=short,
            allocation=allocation,
        )
        for start, end, name, request, short in places
    ]


def _value_rows(
    placed: _Placed, index: int, section: ast.ValueTable
) -> tuple[ValueRow, ...]:
    return tuple(
        ValueRow(
            line=placed.items[index, "rows", item],
            name=row.name,
            value=row.value,
            section=row.section,
            mark=row.mark,
            origin=row.origin,
            origin_target=None
            if row.origin is None
            else placed.links.value_origin(row.origin, row.name),
        )
        for item, row in enumerate(section.rows)
    )


def _changed_lines(raw: str, corrected: str) -> frozenset[int]:
    """The raw file's lines the corrected file replaces or deletes, comments and
    layout aside."""

    def normalized(text: str) -> str:
        return " ".join(text.split(";;", 1)[0].split())

    old = [normalized(line) for line in raw.splitlines()]
    new = [normalized(line) for line in corrected.splitlines()]
    return frozenset(
        index
        for tag, first, last, _, _ in difflib.SequenceMatcher(
            None, old, new, autojunk=False
        ).get_opcodes()
        if tag in ("replace", "delete")
        for index in range(first, last)
        if old[index]
    )


def _corpus_root(entry: Entry) -> Path | None:
    """Return the corpus directory above `entry`: the one holding the raw
    mirror or the corrections record."""
    return next(
        (
            parent
            for parent in entry.path.parents
            if (parent / "raw").is_dir()
            or (parent / _correction_record.RECORD_NAME).is_file()
        ),
        None,
    )


def _raw_path(entry: Entry) -> Path | None:
    """`entry`'s raw mirror, if its corpus holds one."""
    root = _corpus_root(entry)
    if root is None:
        return None
    path = root / "raw" / entry.path.relative_to(root).with_suffix(".raw.dad")
    return path if path.is_file() else None


class _Declarations:
    """The corrections an export reads: the corpus's record, or the modules
    in a given directory, which it executes."""

    def __init__(self, directory: Path | None) -> None:
        self._directory = directory
        self._records: dict[Path, _correction_record.CorrectionRecord] = {}

    def _record_path(self, entry: Entry) -> Path | None:
        root = _corpus_root(entry)
        path = root / _correction_record.RECORD_NAME if root is not None else None
        return path if path is not None and path.is_file() else None

    def answers(self, entry: Entry) -> bool:
        """Whether a record or a directory explains `entry`'s citations."""
        return self._directory is not None or self._record_path(entry) is not None

    def of(self, entry: Entry) -> _correction_record.RecordedDocument | None:
        """Return `entry`'s record, or None if there is none."""
        spec = entry.spec
        if self._directory is not None:
            declared = corrections.in_release(
                corrections.load(self._directory, spec.specification), spec.version
            )
            return (
                _correction_record.RecordedDocument.of(spec, declared)
                if declared
                else None
            )
        path = self._record_path(entry)
        if path is None:
            return None
        record = self._records.get(path)
        if record is None:
            record = self._records[path] = _correction_record.load(path)
        found = record.documents.get(document_id(entry))
        if found is not None and found.version != spec.version:
            raise CorpusError(
                f"{path} records {document_id(entry)} at V{found.version}, the"
                f" file is V{spec.version}: run `seanchai corpus regenerate`"
            )
        return found


def _check_citations(
    entry: Entry, lines: tuple[Line, ...], known: dict[str, Any]
) -> None:
    """Refuse a note citing a declaration the record lacks; the record is
    stale."""
    unknown = sorted(
        {
            token.correction
            for line in lines
            for token in line.tokens
            if token.correction is not None
        }
        - known.keys()
    )
    if unknown:
        raise CorpusError(
            f"{entry.path} cites {', '.join(unknown)}, which the corrections"
            " record does not hold: run `seanchai corpus regenerate`"
        )


def cross_release_entry(
    crossing: CrossRelease | None,
) -> export_schema.CrossRelease | None:
    if crossing is None:
        return None
    return export_schema.CrossRelease(
        citing=crossing.citing,
        cited=crossing.cited,
        version=crossing.version,
        rule=crossing.rule,
        cited_revision=crossing.cited_revision,
        revision=crossing.revision,
        meant=crossing.meant,
    )


def hole_entry(hole: model.Hole) -> Hole:
    """`hole` as an export or a dictionary writes it."""
    block = hole.undefined
    return Hole(
        name=hole.name,
        reference=hole.reference,
        version=hole.version,
        missing=hole.missing,
        vendor_id=hole.vendor_id,
        code=hole.code,
        data_type=hole.data_type,
        flag_rules=None
        if hole.flag_rules is None
        else FlagRules.model_validate(hole.flag_rules.model_dump(mode="json")),
        section=hole.section,
        origin=hole.origin,
        conflict=hole.conflict,
        wireshark_name=hole.wireshark_name,
        across_releases=cross_release_entry(hole.across_releases),
        undefined=None
        if block is None
        else UndefinedBlock(
            section=block.section,
            page=block.page,
            note=block.note,
            cited_in=block.cited_in,
        ),
        recorded=hole.recorded,
    )


class _Lookups:
    """What every document's page and search entries look things up in."""

    def __init__(self, books: Corpus, built: model.Model) -> None:
        self.books = books
        self.model = built
        self.entries = sorted(books, key=document_id)
        self.by_copy = {
            (entry.reference, entry.spec.version): entry for entry in self.entries
        }
        self.citations = {
            document_id(entry): _citations(entry.spec) for entry in self.entries
        }
        self.locations = {
            document_id(entry): _locations(entry.spec) for entry in self.entries
        }

    def references(self, spec: ast.Specification) -> dict[str, Target]:
        """Each document `spec` can cite, as `spec`'s release reads it."""
        found = {}
        for reference in sorted(
            {e.reference for e in self.entries} | set(self.books.rules.cited_as)
        ):
            resolved = self.books.resolve(reference, like=spec)
            if resolved is not None:
                found[reference] = Target(document=document_id(resolved))
        return found

    def row_references(self, spec: ast.Specification) -> dict[tuple[str, str], Target]:
        """Each re-used row's origin cell, at the AVP it names there, and each
        result code's origin, at the clause listing the code there."""
        found = {}
        for section in spec.sections:
            if isinstance(section, ast.ValueTable):
                for value in section.rows:
                    if value.origin is None:
                        continue
                    origin = self.books.resolve(value.origin, like=spec)
                    if origin is None:
                        continue
                    found[value.origin, value.name] = Target(
                        document=document_id(origin),
                        name=value.name,
                        section=next(
                            (
                                their.section or table.source.section
                                for table in origin.spec.sections
                                if isinstance(table, ast.ValueTable)
                                and table.avp == section.avp
                                for their in table.rows
                                if their.value == value.value
                            ),
                            None,
                        ),
                    )
            if isinstance(section, ast.ReusedAvps):
                for row in section.rows:
                    origin = self.books.resolve(row.origin, like=spec)
                    if origin is not None:
                        identifier = document_id(origin)
                        found[row.origin, row.name] = Target(
                            document=identifier,
                            section=self.locations[identifier].get(row.name),
                            name=row.name,
                        )
        return found

    def avp_target(self, entry: Entry, avp: model.Avp) -> Target | None:
        """Where `avp`, as `entry` reads it, is defined."""
        spec = entry.spec
        origin = (
            entry
            if avp.defined_in == entry.reference
            else self.books.resolve(avp.defined_in, like=spec)
        )
        crossing = avp.across_releases
        # A later release's copy stating a field defines nothing: the citation's
        # own copy does.
        if (
            crossing
            and crossing.cited == avp.defined_in
            and crossing.rule is not CitationRule.LATER_RELEASE
        ):
            origin = self.by_copy.get((avp.defined_in, crossing.version), origin)
        if origin is None:
            return None
        identifier = document_id(origin)
        clause = (
            avp.section
            if avp.section in self.citations[identifier]
            else self.locations[identifier].get(avp.name)
        )
        return Target(document=identifier, section=clause)


def _avps(
    corpus: _Lookups, entry: Entry
) -> tuple[dict[str, Target | None], list[Hole], list[SearchEntry]]:
    """`entry`'s AVP names: their targets, holes and search entries."""
    spec = entry.spec
    names: dict[str, Target | None] = {}
    holes = []
    search = []
    for name in sorted(_avp_names(spec)):
        avp = corpus.model.resolve(entry.reference, name, version=spec.version)
        hole = corpus.model.hole(entry.reference, name, version=spec.version)
        target = corpus.avp_target(entry, avp) if avp is not None else None
        if hole is not None:
            holes.append(hole_entry(hole))
        names[name] = target
        search.append(
            SearchEntry(
                name=name,
                kind="avp",
                document=document_id(entry),
                target=target,
                identity=AvpIdentity(
                    kind="avp", vendor_id=avp.identity[0], code=avp.identity[1]
                )
                if avp
                else None,
                defined_in=(avp.defined_in,) if avp else (),
                abbreviation=None,
                wireshark_name=avp.wireshark_name
                if avp
                else (hole.wireshark_name if hole else None),
                data_type=avp.data_type if avp else None,
                across_releases=cross_release_entry(
                    avp.across_releases if avp else None
                ),
            )
        )
    return names, holes, search


def _sections_search(corpus: _Lookups, entry: Entry) -> list[SearchEntry]:
    """`entry`'s commands, applications, registry rows and value names, as search
    entries."""
    spec = entry.spec
    identifier = document_id(entry)
    # The header's id is part of the key: TS 29.272 clause 7.2.9 prints
    # Insert-Subscriber-Data-Request twice, once per application.
    resolved = {
        (
            message.name,
            message.section,
            message.command_code,
            message.header_application_id,
        ): (message, application)
        for application in corpus.model.applications(
            entry.reference, version=spec.version
        )
        for message in application.messages
    }

    def named(
        name: str,
        kind: Literal["command", "application", "registry", "value"],
        section: ast.Section,
        identity: CommandIdentity
        | ApplicationIdentity
        | RegistryIdentity
        | ValueIdentity,
        defined_in: tuple[str, ...] = (entry.reference,),
        abbreviation: str | None = None,
        data_type: ast.DataType | None = None,
        clause: str | None = None,
    ) -> SearchEntry:
        return SearchEntry(
            name=name,
            kind=kind,
            document=identifier,
            target=Target(
                document=identifier, section=clause or section.source.section
            ),
            identity=identity,
            defined_in=defined_in,
            abbreviation=abbreviation,
            wireshark_name=None,
            data_type=data_type,
            across_releases=None,
        )

    search = []
    for section in spec.sections:
        if isinstance(section, ast.Message):
            message, application = resolved[
                section.name,
                section.source.section,
                section.command_code,
                section.application_id,
            ]
            search.append(
                named(
                    section.name,
                    "command",
                    section,
                    CommandIdentity(
                        kind="command",
                        command_code=section.command_code,
                        application_id=message.application_id,
                        header_application_id=message.header_application_id,
                        application=application.name,
                    ),
                    abbreviation=section.abbreviation,
                )
            )
        elif isinstance(section, ast.ApplicationScope):
            search.append(
                named(
                    section.name,
                    "application",
                    section,
                    ApplicationIdentity(
                        kind="application", application_id=section.application_id
                    ),
                )
            )
        elif isinstance(section, ast.Registry):
            search.extend(
                named(
                    row.name,
                    "registry",
                    section,
                    RegistryIdentity(
                        kind="registry", registry=section.registry, code=row.code
                    ),
                    defined_in=row.defined_in,
                    abbreviation=row.abbreviation,
                    data_type=row.data_type,
                )
                for row in section.rows
                if isinstance(row, ast.RegistryRow)
                and row.name
                and row.code is not None
            )
        elif isinstance(section, ast.ValueTable):
            search.extend(
                named(
                    row.name,
                    "value",
                    section,
                    ValueIdentity(
                        kind="value",
                        value_kind=section.kind,
                        avp=section.avp,
                        value=row.value,
                        application=section.application,
                        feature_list_id=section.feature_list_id,
                    ),
                    defined_in=(row.origin or entry.reference,),
                    clause=row.section,
                )
                for row in section.rows
            )
    return search


def _clause_names(entry: Entry) -> dict[str, Target]:
    """Return the command and application names defined in one clause only,
    which a mention elsewhere can link to."""
    clauses: dict[str, set[str]] = {}
    for section in entry.spec.sections:
        if isinstance(section, ast.Message | ast.ApplicationScope):
            clauses.setdefault(section.name, set()).add(section.source.section)
    return {
        name: Target(document=document_id(entry), section=clause)
        for name, places in clauses.items()
        if len(places) == 1
        for clause in places
    }


def _value_table_avps(
    corpus: _Lookups, entry: Entry, names: dict[str, Target | None]
) -> dict[str, Target | None]:
    """Return where a value table's `; AVP:` line links: the AVP as `entry`
    reads it, or else as its defining document does."""
    found: dict[str, Target | None] = {}
    for section in entry.spec.sections:
        if not isinstance(section, ast.ValueTable) or names.get(section.avp):
            continue
        avp = corpus.model.resolve(
            entry.reference, section.avp, version=entry.spec.version
        )
        if avp is None:
            try:
                avp = corpus.model.definition(section.avp)
            except model.ModelError:
                avp = None
        if avp is not None:
            found[section.avp] = corpus.avp_target(entry, avp)
    return found


def _titles(catalog: Catalog) -> dict[str, str]:
    """Each catalogued document's title, by reference."""
    titles = {f"{s.document_type}{s.number}": s.title for s in catalog.pinned}
    titles.update({f"{s.document_type}{s.number}": s.title for s in catalog.tgpp})
    titles.update({f"RFC{s.number}": s.title for s in catalog.rfc})
    titles.update({ast.spec_ref(s.identifier): s.title for s in catalog.onem2m})
    titles.update({s.reference: s.title for s in catalog.transcribed})
    return titles


def _publisher(entry: Entry) -> Any:
    """Who publishes `entry`; `DocumentSummary.publisher` checks the spelling."""
    specification = entry.spec.specification
    if specification.startswith("3GPP "):
        return "3GPP"
    if entry.reference.startswith("RFC"):
        return "IETF"
    # OMA's names lead with the publisher and carry no space.
    if entry.reference.startswith("OMA-"):
        return "OMA"
    return specification.split(" ", 1)[0]


def _source_kind(entry: Entry, link: str) -> Literal["etsi-pdf", "rfc-text", "other"]:
    url = urlparse(link)
    path = url.path.lower()
    if entry.reference.startswith("RFC") and path.endswith(".txt"):
        return "rfc-text"
    if (url.hostname or "").endswith("etsi.org") and path.endswith(".pdf"):
        return "etsi-pdf"
    return "other"


class _Sources:
    """The source documents an export copies in, from a `seanchai corpus download`."""

    def __init__(
        self, output: Path, specifications: Path | None, include_pdfs: bool
    ) -> None:
        if include_pdfs and (specifications is None or not specifications.is_dir()):
            raise CorpusError(
                "including PDFs needs a specifications directory: run"
                " `seanchai corpus download --only 3gpp --only transcribed`"
            )
        self._output = output
        self._specifications = specifications
        self._include_pdfs = include_pdfs
        self._pdfs: dict[str, list[Path]] = {}
        if include_pdfs and specifications is not None:
            for path in sorted(specifications.rglob("*.pdf")):
                self._pdfs.setdefault(path.name, []).append(path)

    def _copy(self, path: Path, name: str) -> str:
        relative = f"sources/{name}"
        destination = self._output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        return relative

    def source(self, entry: Entry) -> Source:
        """Where `entry` was read from, copying what the export carries of it."""
        spec = entry.spec
        identifier = document_id(entry)
        link = str(spec.link or spec.transcribed or "")
        text = None
        if entry.reference.startswith("RFC") and self._specifications is not None:
            path = self._specifications / "rfc" / f"{entry.reference.lower()}.txt"
            if path.is_file():
                text = self._copy(path, f"{identifier}.txt")
        local = None
        if self._include_pdfs and urlparse(link).path.lower().endswith(".pdf"):
            candidates = self._pdfs.get(unquote(urlparse(link).path.rsplit("/", 1)[-1]))
            if not candidates:
                remedy = (
                    "run `seanchai corpus download --only transcribed`"
                    if spec.transcribed
                    else "run `seanchai corpus download --only 3gpp`"
                )
                raise CorpusError(
                    f"{identifier}: no downloaded PDF matches {link}: {remedy}"
                )
            if len({hashlib.sha256(p.read_bytes()).digest() for p in candidates}) > 1:
                raise CorpusError(f"{identifier}: conflicting PDF copies for {link}")
            local = self._copy(candidates[0], f"{identifier}.pdf")
        return Source(
            kind=_source_kind(entry, link), url=link or None, local=local, text=text
        )


def _write(path: Path, value: pydantic.BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(export_schema.dumps(value), encoding="utf-8")


def _write_grammar(output: Path) -> None:
    """Copy the editors' TextMate grammar for the site's highlighting."""
    path = output / SYNTAX_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_GRAMMAR, path)


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _corpus_version(books: Corpus) -> str | None:
    """The installed corpus's version, if `books` is read from it."""
    try:
        directory = installed_directory().resolve()
    except CorpusNotInstalledError:
        return None
    if all(entry.path.resolve().is_relative_to(directory) for entry in books):
        return _distribution_version("seanchai-corpus")
    return None


def _is_export_index(index: Any) -> bool:
    """Whether a parsed `index.json` names this generator, of any version."""
    return isinstance(index, dict) and index.get("generator") == GENERATOR


def _refuse_foreign(output: Path) -> None:
    """Refuse an `output` that is not absent, empty or a previous export."""
    if not output.exists():
        return
    if not output.is_dir():
        raise CorpusError(f"{output} exists and is not a directory")
    if not any(output.iterdir()):
        return
    try:
        index = json.loads((output / "index.json").read_bytes())
    except (OSError, ValueError):
        index = None
    if not _is_export_index(index):
        raise CorpusError(
            f"{output} is not empty and holds no Seanchaí export's index.json; an"
            " export replaces its whole output directory, so name another"
        )


@contextlib.contextmanager
def _replacing(output: Path) -> Generator[Path]:
    """Yield a directory to build the export in. It replaces `output` when
    the block ends, and is removed if the block raises.

    It sits beside `output` so the swap is two renames and a reader never
    sees a mix. It is created inside a private `mkdtemp` directory, with the
    old export's mode or a plain `mkdir`'s.
    """
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.", dir=output.parent
    ) as scratch:
        staged = Path(scratch) / "new"
        staged.mkdir()
        yield staged
        _publish(staged, output)


def _publish(staged: Path, output: Path) -> None:
    """Move `staged` to `output`.

    The previous export waits in `<output>.previous-<pid>` until the swap
    completes or is undone, so one of the two is always whole on disk. A
    failed restore reports where it is.
    """
    if not output.exists():
        staged.rename(output)
        return
    shutil.copymode(output, staged)
    backup = output.with_name(f"{output.name}.previous-{os.getpid()}")
    try:
        output.rename(backup)
        staged.rename(output)
    except BaseException as error:
        # With `output` in place nothing was moved aside, or the new export
        # arrived just before an interruption, so there is nothing to restore.
        if backup.exists() and not output.exists():
            try:
                backup.rename(output)
            except OSError as failure:
                raise CorpusError(
                    f"cannot replace {output}: {error}; nor could the previous"
                    f" export be restored: {failure}. It is kept in {backup};"
                    f" move it back to {output}"
                ) from failure
        raise
    # The new export is published, so a backup left here fails nothing.
    shutil.rmtree(backup, ignore_errors=True)


def export_corpus(
    books: Corpus,
    output: Path,
    *,
    wireshark: Path | None = None,
    corrections_directory: Path | None = None,
    specifications: Path | None = None,
    include_pdfs: bool = False,
) -> Index:
    """Write `books` as the site's JSON, replacing `output` whole.

    `wireshark` is a Wireshark Diameter dictionary directory whose names the
    export adds. `corrections_directory` reads corrections from the modules
    there (executing them) instead of the corpus's record. `specifications`
    is a `seanchai corpus download` to copy RFC texts from, and with
    `include_pdfs` the source PDFs. `output` is untouched until the export
    succeeds. An `output` holding anything but a previous export, and an
    empty corpus, are refused.
    """
    if not len(books):
        raise CorpusError("nothing to export: the corpus holds no documents")
    _refuse_foreign(output)
    with _replacing(output) as staged:
        return _write_export(
            books,
            staged,
            wireshark,
            _Declarations(corrections_directory),
            specifications,
            include_pdfs,
        )


def _write_export(
    books: Corpus,
    output: Path,
    wireshark: Path | None,
    declarations: _Declarations,
    specifications: Path | None,
    include_pdfs: bool,
) -> Index:
    corpus = _Lookups(
        books,
        model.Model.build(books, holes=model.HolePolicy.ANY, wireshark=wireshark),
    )
    ids = [document_id(entry) for entry in corpus.entries]
    if len(set(ids)) != len(ids):
        raise CorpusError("export needs unique document file names")
    catalog = load_catalog()
    titles = _titles(catalog)
    pinned = {(f"TS{s.number}", s.version): s.reason for s in catalog.pinned}
    sources = _Sources(output, specifications, include_pdfs)
    summaries = []
    search = []
    mentions = []
    for entry in corpus.entries:
        document = _write_document(
            corpus, entry, output, declarations, sources, titles, pinned, search
        )
        summaries.append(
            DocumentSummary.model_validate(
                {name: getattr(document, name) for name in DocumentSummary.model_fields}
            )
        )
        mentions.extend(_mentions(document))
    _write(
        output / "search.json",
        Search(
            schema_version=SCHEMA_VERSION,
            entries=tuple(search),
            mentions=tuple(mentions),
        ),
    )
    _write_grammar(output)
    (output / "schema.json").write_text(
        json.dumps(
            export_schema.json_schema(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    index = Index(
        schema_version=SCHEMA_VERSION,
        generator=GENERATOR,
        seanchai_version=_distribution_version("seanchai"),
        corpus_version=_corpus_version(books),
        mode="self-hosted" if include_pdfs else "public",
        documents=tuple(summaries),
    )
    _write(output / "index.json", index)
    return index


def _write_document(
    corpus: _Lookups,
    entry: Entry,
    output: Path,
    declarations: _Declarations,
    sources: _Sources,
    titles: dict[str, str],
    pinned: dict[tuple[str, str], str],
    search: list[SearchEntry],
) -> Document:
    """Write `entry`'s files, add its names to `search`, and return its page."""
    spec = entry.spec
    identifier = document_id(entry)
    names, holes, entries = _avps(corpus, entry)
    search.extend(entries)
    search.extend(_sections_search(corpus, entry))
    for name, target in _clause_names(entry).items():
        names.setdefault(name, target)
    names.update(_value_table_avps(corpus, entry, names))
    links = _Links(entry, names, corpus.references(spec), corpus.row_references(spec))
    declared = declarations.of(entry)
    edits = dict(declared.edits) if declared else {}
    text = entry.path.read_text(encoding="utf-8")
    _, layout = parser.parse_with_layout(text)
    lines = _lines(text, spec, links)
    raw_path = _raw_path(entry)
    raw = None
    if raw_path is not None:
        raw_text = raw_path.read_text(encoding="utf-8")
        raw = f"documents/{identifier}.raw.json"
        raw_spec, raw_layout = parser.parse_with_layout(raw_text)
        raw_links = links.spelled_as_raw(declared.renames if declared else ())
        raw_lines = _lines(
            raw_text, raw_spec, raw_links, _changed_lines(raw_text, text)
        )
        if declarations.answers(entry):
            _check_citations(entry, raw_lines, edits)
        _write(
            output / raw,
            RawDocument(
                schema_version=SCHEMA_VERSION,
                id=identifier,
                lines=raw_lines,
                blocks=_blocks(raw_text, raw_spec, raw_layout, raw_links),
            ),
        )
    if declarations.answers(entry):
        _check_citations(entry, lines, edits)
    path = f"documents/{identifier}.json"
    document = Document(
        schema_version=SCHEMA_VERSION,
        id=identifier,
        path=path,
        raw=raw,
        reference=entry.reference,
        specification=spec.specification,
        version=spec.version,
        publisher=_publisher(entry),
        release=int(spec.version.split(".")[0])
        if spec.specification.startswith("3GPP ") and spec.version
        else None,
        title=titles.get(entry.reference, spec.specification),
        pinned=pinned.get((entry.reference, spec.version)) if spec.version else None,
        interfaces=corpus.books.interfaces.of(entry),
        source=sources.source(entry),
        sections=_sections(spec, corpus.citations[identifier]),
        lines=lines,
        blocks=_blocks(text, spec, layout, links),
        corrections={
            cited: export_schema.Correction(kind=edit.kind, reason=edit.reason)
            for cited, edit in edits.items()
        },
        holes=tuple(holes),
        findings=tuple(
            Finding(
                severity=finding.severity,
                rule=finding.rule,
                message=finding.message,
                section=finding.section,
                origin=finding.origin,
                accepted_by=finding.accepted_by,
            )
            for finding in lint_with_corpus(
                spec, corpus.books, declared.acceptances() if declared else ()
            )
        ),
    )
    _write(output / path, document)
    return document


def _mentions(document: Document) -> Iterator[Mention]:
    """The document's non-blank lines, with the AVPs each names."""
    for index, line in enumerate(document.lines):
        text = "".join(token.text for token in line.tokens).strip()
        if text:
            yield Mention(
                document=document.id,
                section=line.section,
                line=index,
                text=text,
                avps=tuple(
                    sorted(
                        {token.avp for token in line.tokens if token.avp is not None}
                    )
                ),
            )
