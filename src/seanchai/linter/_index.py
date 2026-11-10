"""The one pass over a file that every rule reads from, and the spellings
of its parts that rules of several modules share.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..dad import ast


@dataclass
class _Index:
    """The one pass over the file that every rule reads from."""

    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp] = field(default_factory=list)
    messages: list[ast.Message] = field(default_factory=list)
    applications: list[ast.ApplicationScope] = field(default_factory=list)
    # `Undefined AVP` blocks: names the file declares defined nowhere.
    undefined: list[ast.UndefinedAvp] = field(default_factory=list)
    # `Reprinted AVP` blocks: another document's rule, as this one prints it.
    reprints: list[ast.ReprintedAvp] = field(default_factory=list)
    tables: list[ast.AvpTable] = field(default_factory=list)
    value_tables: list[ast.ValueTable] = field(default_factory=list)
    # Result codes whose text names the document defining them, with their
    # table: TS 29.283's DIAMETER_ERROR_USER_UNKNOWN, "defined in 3GPP TS 29.229".
    reused_values: list[tuple[ast.ValueTable, ast.ValueRow]] = field(
        default_factory=list
    )
    reused: dict[str, str] = field(default_factory=dict)  # AVP name -> origin
    # Names a re-used table cites from this file itself. TS 29.212's Gxx, S9,
    # Sd and St tables list Gx's AVPs "from" TS 29.212: those are this file's
    # own definitions, so no rule treats them as belonging elsewhere.
    self_cited: list[str] = field(default_factory=list)
    # Re-used rows printing the AVP's code or type (TS 29.172 table
    # 7.4.1-2), with their block, for comparing against the origin.
    reused_cells: list[tuple[ast.ReusedAvps, ast.ReusedAvpRow]] = field(
        default_factory=list
    )
    # Each section, body rule and row's tree path, by object identity:
    # equal nodes in two places are two nodes.
    paths: dict[int, ast.TreePath] = field(default_factory=dict)
    # Re-used rows' paths by AVP name.
    reused_paths: dict[str, list[ast.TreePath]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def path(self, node: ast.Node) -> ast.TreePath:
        return self.paths[id(node)]

    @property
    def rows(self) -> list[ast.AvpTableRow]:
        return [row for table in self.tables for row in table.rows]


def _index(spec: ast.Specification) -> _Index:
    index = _Index()
    try:
        own = ast.spec_ref(spec.specification)
    except ast.SpecRefError:
        # A hand-authored file may name a document no From cell can cite.
        own = None
    for position, section in enumerate(spec.sections):
        at: ast.TreePath = ("sections", position)
        index.paths[id(section)] = at
        if isinstance(section, ast.Message | ast.GroupedAvp | ast.ReprintedAvp):
            for number, rule in enumerate(section.avps):
                index.paths[id(rule)] = (*at, "avps", number)
        if isinstance(section, ast.AvpTable | ast.ReusedAvps | ast.ValueTable):
            for number, row in enumerate(section.rows):
                index.paths[id(row)] = (*at, "rows", number)
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
            index.definitions.append(section)
        elif isinstance(section, ast.Message):
            index.messages.append(section)
        elif isinstance(section, ast.ApplicationScope):
            index.applications.append(section)
        elif isinstance(section, ast.UndefinedAvp):
            index.undefined.append(section)
        elif isinstance(section, ast.ReprintedAvp):
            index.reprints.append(section)
        elif isinstance(section, ast.AvpTable):
            index.tables.append(section)
        elif isinstance(section, ast.ValueTable):
            index.value_tables.append(section)
            index.reused_values += [
                (section, row)
                for row in section.rows
                if row.origin is not None and row.origin != own
            ]
        elif isinstance(section, ast.ReusedAvps):
            for row in section.rows:
                index.reused_paths[row.name].append(index.path(row))
                if row.origin == own:
                    index.self_cited.append(row.name)
                else:
                    index.reused[row.name] = row.origin
                    if row.code is not None or row.data_type is not None:
                        index.reused_cells.append((section, row))
    return index


def _repeats[T](items) -> list[T]:
    seen: dict[T, int] = defaultdict(int)
    for item in items:
        seen[item] += 1
    return [item for item, count in seen.items() if count > 1]


def _table_labels(tables: list[ast.AvpTable]) -> str:
    # RFC 6733 §4.5 captions its table with prose, so there may be no label.
    labels = [table.table or f"(clause {table.source.section})" for table in tables]
    return f"table{'s' if len(labels) > 1 else ''} {', '.join(labels)}"


def _references(index: _Index) -> dict[str, list[str]]:
    """The clauses of the message and grouped bodies naming each member,
    in file order, `* [ AVP ]` aside."""
    cited_by: dict[str, list[str]] = defaultdict(list)
    for section in (*index.messages, *index.definitions):
        if not isinstance(section, ast.Message | ast.GroupedAvp):
            continue
        for rule in section.avps:
            if rule.name != "AVP":
                cited_by[rule.name].append(section.source.section)
    return {name: list(dict.fromkeys(where)) for name, where in cited_by.items()}


def _clauses(where: list[str]) -> str:
    return f"clause{'s' if len(where) > 1 else ''} {', '.join(where)}"
