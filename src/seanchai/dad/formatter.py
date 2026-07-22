"""Canonical formatter: AST → `.dad` text.

`format(parse(text))` must be idempotent — the patch-based review workflow
depends on stable diffs. Canonical rules:

- sections separated by two blank lines; file ends with one newline;
- ABNF bodies: 8-space indent with the repetition qualifier right-aligned in
  front of it; `; bold` markers aligned one column past the longest ABNF body
  line in the whole file;
- enum bodies: `=` aligned per section (RESERVED counts as a name);
- tables: columns split by 3 spaces, widths from data cells only (minimum 3);
  the `;;` column-header line is cosmetic — labels sit at column starts,
  overflowing into gaps when wider than the column.
"""

from . import ast

_PRESENCE_BRACKETS = {ast.Presence.FIXED: "<>",
                      ast.Presence.REQUIRED: "{}",
                      ast.Presence.OPTIONAL: "[]"}
# Canonical command-flag order in a Diameter header line.
_COMMAND_FLAG_ORDER = [ast.CommandFlag.REQUEST, ast.CommandFlag.PROXIABLE,
                       ast.CommandFlag.ERROR]
_MIN_COLUMN_WIDTH = 3
_COLUMN_GAP = 3


def _qualifier(rule: ast.AvpRule) -> str:
    if (rule.min_occurs, rule.max_occurs) == (1, 1):
        return ""
    minimum = str(rule.min_occurs) if rule.min_occurs else ""
    maximum = str(rule.max_occurs) if rule.max_occurs is not None else ""
    return f"{minimum}*{maximum}"


def _avp_line(rule: ast.AvpRule) -> str:
    open_bracket, close_bracket = _PRESENCE_BRACKETS[rule.presence]
    return f"{_qualifier(rule):>7} {open_bracket} {rule.name} {close_bracket}"


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


def _flags_cell(flags: frozenset[ast.AvpFlag]) -> str:
    return ",".join(flag.value for flag in ast.AvpFlag if flag in flags) or "-"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(_MIN_COLUMN_WIDTH, max(len(row[i]) for row in rows))
              for i in range(len(headers))]
    starts = [0]
    for width in widths[:-1]:
        starts.append(starts[-1] + width + _COLUMN_GAP)

    header_line = ";;"
    for header, start in zip(headers, starts):
        header_line += " " * max(start - len(header_line), 1) + header
    lines = [header_line]
    for row in rows:
        line = ""
        for cell, start in zip(row, starts):
            line += " " * (start - len(line)) + cell
        lines.append(line)
    return lines


def _format_message(message: ast.Message, bold_column: int) -> list[str]:
    flags = [flag.value for flag in _COMMAND_FLAG_ORDER if flag in message.flags]
    header_items = ", ".join([str(message.command_code), *flags,
                              str(message.application_id)])
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
    width = max((len(value.name) if isinstance(value, ast.EnumValue) else len("RESERVED")
                 for value in avp.values), default=0)
    lines = [
        "; Type: Enumerated AVP",
        *_header_directives(avp.name, avp.source),
        f"{avp.name} ::= < Enumerated AVP header:"
        f" {_avp_header_items(avp.code, avp.vendor_id)} >",
    ]
    value_width = max((len(str(value.value)) for value in avp.values
                       if isinstance(value, ast.EnumValue)), default=0)
    for value in avp.values:
        if isinstance(value, ast.EnumValue):
            line = f"        {value.name:<{width}} = {value.value:<{value_width}}"
            if value.description is not None:
                line += f" ; {value.description}"
            lines.append(line.rstrip())
        else:
            numbers = (str(value.first) if value.first == value.last
                       else f"{value.first}-{value.last}")
            lines.append(f"      ; {'RESERVED':<{width}} = {numbers}")
    return lines


def _format_avp_table(table: ast.AvpTable, bold_column: int) -> list[str]:
    del bold_column
    rows = [[row.name, "-" if row.code is None else str(row.code), row.section,
             row.data_type,
             _flags_cell(row.flag_rules.must), _flags_cell(row.flag_rules.may),
             _flags_cell(row.flag_rules.should_not), _flags_cell(row.flag_rules.must_not),
             "Yes" if row.may_encrypt else "No"]
            for row in table.rows]
    return [
        "; Type: AVP Table",
        f"; Table: {table.table}",
        f"; Section: {table.source.section}",
        *([f"; Page: {table.source.page}"] if table.source.page is not None else []),
        *_table(["Name", "Code", "Section", "Type",
                 "Must", "May", "S.not", "M.not", "Encrypt"], rows),
    ]


def _format_reused(reused: ast.ReusedAvps, bold_column: int) -> list[str]:
    del bold_column
    rows = [[row.name, row.origin, row.m_bit.value if row.m_bit else "-"]
            for row in reused.rows]
    return [
        "; Type: Reused AVPs",
        f"; Table: {reused.table}",
        f"; Section: {reused.source.section}",
        *([f"; Page: {reused.source.page}"] if reused.source.page is not None else []),
        *_table(["Name", "From", "M-bit"], rows),
    ]


_SECTION_FORMATTERS = {
    ast.Message: _format_message,
    ast.GroupedAvp: _format_grouped,
    ast.EnumeratedAvp: _format_enumerated,
    ast.AvpTable: _format_avp_table,
    ast.ReusedAvps: _format_reused,
}


def _bold_column(spec: ast.Specification) -> int:
    lengths = [len(_avp_line(rule))
               for section in spec.sections
               if isinstance(section, (ast.Message, ast.GroupedAvp))
               for rule in section.avps]
    return max(lengths, default=0) + 1


def format(spec: ast.Specification) -> str:
    header = [f"; Specification: {spec.specification}", f"; Version: {spec.version}"]
    if spec.link is not None:
        header.append(f"; Link: {spec.link}")

    bold_column = _bold_column(spec)
    parts = [header]
    parts.extend(_SECTION_FORMATTERS[type(section)](section, bold_column)
                 for section in spec.sections)
    return "\n\n\n".join("\n".join(part) for part in parts) + "\n"
