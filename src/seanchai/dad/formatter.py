"""Canonical formatter: AST → `.dad` text.

`format(parse(text))` must be idempotent — the patch-based review workflow
depends on stable diffs. Canonical rules:

- sections separated by two blank lines; file ends with one newline;
- ABNF bodies: 8-space indent with the repetition qualifier right-aligned in
  front of it; `; bold` markers aligned one column past the longest ABNF body
  line of their own section;
- enum bodies: `=` aligned per section (RESERVED counts as a name);
- tables: columns split by 3 spaces, widths from data cells only (minimum 3);
  the `;;` column-header line is cosmetic — labels sit at column starts,
  overflowing into gaps when wider than the column.
"""

from collections.abc import Callable
from typing import Any

from . import abnf, ast

_MIN_COLUMN_WIDTH = 3
_COLUMN_GAP = 3


def _avp_line(rule: ast.AvpRule) -> str:
    open_bracket, close_bracket = abnf.brackets_for(rule.presence)
    qualifier = abnf.qualifier(rule.min_occurs, rule.max_occurs)
    return f"{qualifier:>7} {open_bracket} {rule.name} {close_bracket}"


def _abnf_body(avps: tuple[ast.AvpRule, ...], bold_column: int) -> list[str]:
    lines = []
    for rule in avps:
        line = _avp_line(rule)
        if rule.bold:
            line = f"{line:<{bold_column}}; bold"
        lines.append(line)
    return lines


def _header_directives(name: str, source: ast.SourceRef) -> list[str]:
    lines = [f"; Name: {name}", f"; Section: {source.section}"]
    if source.page is not None:
        lines.append(f"; Page: {source.page}")
    return lines


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [
        max(_MIN_COLUMN_WIDTH, max(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    starts = [0]
    for width in widths[:-1]:
        starts.append(starts[-1] + width + _COLUMN_GAP)

    header_line = ";;"
    for header, start in zip(headers, starts, strict=True):
        header_line += " " * max(start - len(header_line), 1) + header
    lines = [header_line]
    for row in rows:
        line = ""
        for cell, start in zip(row, starts, strict=True):
            line += " " * (start - len(line)) + cell
        lines.append(line)
    return lines


def _format_message(message: ast.Message, bold_column: int) -> list[str]:
    header_items = abnf.diameter_header_items(
        message.command_code, message.flags, message.application_id
    )
    return [
        "; Type: Message",
        *_header_directives(f"{message.name}, {message.abbreviation}", message.source),
        f"<{message.name}> ::= < Diameter Header: {header_items} >",
        *_abnf_body(message.avps, bold_column),
    ]


def _avp_header_items(code: int, vendor_id: int | None) -> str:
    return str(code) if vendor_id is None else f"{code} {vendor_id}"


def _format_grouped(avp: ast.GroupedAvp, bold_column: int) -> list[str]:
    return [
        "; Type: Grouped AVP",
        *_header_directives(avp.name, avp.source),
        f"{avp.name} ::= < AVP header: {_avp_header_items(avp.code, avp.vendor_id)} >",
        *_abnf_body(avp.avps, bold_column),
    ]


def _format_enumerated(avp: ast.EnumeratedAvp, bold_column: int) -> list[str]:
    del bold_column
    width = max(
        (
            len(value.name) if isinstance(value, ast.EnumValue) else len("RESERVED")
            for value in avp.values
        ),
        default=0,
    )
    lines = [
        "; Type: Enumerated AVP",
        *_header_directives(avp.name, avp.source),
        f"{avp.name} ::= < Enumerated AVP header:"
        f" {_avp_header_items(avp.code, avp.vendor_id)} >",
    ]
    value_width = max(
        (
            len(str(value.value))
            for value in avp.values
            if isinstance(value, ast.EnumValue)
        ),
        default=0,
    )
    for value in avp.values:
        if isinstance(value, ast.EnumValue):
            line = f"        {value.name:<{width}} = {value.value:<{value_width}}"
            if value.description is not None:
                line += f" ; {value.description}"
            lines.append(line.rstrip())
        else:
            numbers = (
                str(value.first)
                if value.first == value.last
                else f"{value.first}-{value.last}"
            )
            lines.append(f"      ; {'RESERVED':<{width}} = {numbers}")
    return lines


def _format_avp_table(table: ast.AvpTable, bold_column: int) -> list[str]:
    del bold_column
    rows = [
        [
            row.name,
            "-" if row.code is None else str(row.code),
            row.section if row.section is not None else "-",
            row.data_type,
            abnf.avp_flags_cell(row.flag_rules.must),
            abnf.avp_flags_cell(row.flag_rules.may),
            abnf.avp_flags_cell(row.flag_rules.should_not),
            abnf.avp_flags_cell(row.flag_rules.must_not),
            "Yes" if row.may_encrypt else "No",
        ]
        for row in table.rows
    ]
    return [
        "; Type: AVP Table",
        f"; Section: {table.source.section}",
        f"; Table: {table.table}",
        *([f"; Page: {table.source.page}"] if table.source.page is not None else []),
        *_table(
            [
                "Name",
                "Code",
                "Section",
                "Type",
                "Must",
                "May",
                "S.not",
                "M.not",
                "Encrypt",
            ],
            rows,
        ),
    ]


def _format_reused(reused: ast.ReusedAvps, bold_column: int) -> list[str]:
    del bold_column
    rows = [
        [row.name, row.origin, row.m_bit.value if row.m_bit else "-"]
        for row in reused.rows
    ]
    return [
        "; Type: Reused AVPs",
        f"; Section: {reused.source.section}",
        f"; Table: {reused.table}",
        *([f"; Page: {reused.source.page}"] if reused.source.page is not None else []),
        *_table(["Name", "From", "M-bit"], rows),
    ]


# Each formatter takes its own section type; the dispatch is keyed by that same
# type, which no type checker can express as a mapping — hence the `Any`.
_SECTION_FORMATTERS: dict[type[ast.Section], Callable[[Any, int], list[str]]] = {
    ast.Message: _format_message,
    ast.GroupedAvp: _format_grouped,
    ast.EnumeratedAvp: _format_enumerated,
    ast.AvpTable: _format_avp_table,
    ast.ReusedAvps: _format_reused,
}


def _bold_column(section: ast.Section) -> int:
    """Where `; bold` markers sit, one column past the longest ABNF line — of
    this section only. A file-wide column would make one added AVP reflow every
    marker in the file, and the review workflow lives on raw-vs-raw diffs."""
    if not isinstance(section, ast.Message | ast.GroupedAvp):
        return 0
    return max((len(_avp_line(rule)) for rule in section.avps), default=0) + 1


def format(spec: ast.Specification) -> str:
    header = [f"; Specification: {spec.specification}", f"; Version: {spec.version}"]
    if spec.link is not None:
        header.append(f"; Link: {spec.link}")

    parts = [header]
    parts.extend(
        _SECTION_FORMATTERS[type(section)](section, _bold_column(section))
        for section in spec.sections
    )
    return "\n\n\n".join("\n".join(part) for part in parts) + "\n"
