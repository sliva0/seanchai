"""`_View`: one specification copy indexed for resolution, and helpers for
its references, lateness and application scopes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import corpus
from ..dad import ast
from ._types import Marks, ValueTable, _value_table


def _folded(reference: str) -> str:
    """A reference folded for comparison: "3GPP TS 29.229", "ts29229" and
    `TS29.229` fold alike."""
    folded = re.sub(r"[\s.\-_]", "", reference).casefold()
    return re.sub(r"^3gpp(?=t[rs])", "", folded)


def _generation(spec: ast.Specification) -> int:
    """How late a document is: its major version, or an RFC's number."""
    if spec.version is not None:
        return int(spec.version.split(".")[0])
    return int(re.sub(r"\D", "", spec.specification) or 0)


def _scope(view: _View, message: ast.Message) -> ast.ApplicationScope | None:
    """The first application scope covering `message`'s clause."""
    return next(
        (each for each in view.applications if each.covers(message.source.section)),
        None,
    )


def _effective_id(
    message: ast.Message, block: ast.ApplicationScope | None
) -> int | None:
    if message.application_id is None and block is not None:
        return block.application_id
    return message.application_id


@dataclass
class _View:
    """One specification's file, indexed the way resolution reads it."""

    entry: corpus.Entry
    defined: dict[str, ast.GroupedAvp | ast.EnumeratedAvp]
    # Every row per name, in file order. Resolution reads the first; the rest
    # are other tables' copies, which may disagree (`table-row-mismatch`).
    tabled: dict[str, list[ast.AvpTableRow]]
    reused: dict[str, str]
    # Every re-used row per name, in file order; `reused` takes the origin
    # from the first.
    reused_rows: dict[str, list[ast.ReusedAvpRow]]
    messages: list[ast.Message]
    applications: list[ast.ApplicationScope]
    # Every row of a table printing mark columns, per name, in file order.
    marked: dict[str, list[Marks]]
    registries: list[ast.Registry]
    # `Undefined AVP` blocks by name; resolution reads one last.
    undefined: dict[str, ast.UndefinedAvp] = field(default_factory=dict)
    # Every value table, in file order.
    value_tables: list[ValueTable] = field(default_factory=list)
    # `<answer-message>` rules, in file order.
    answers: list[ast.AnswerMessage] = field(default_factory=list)

    @classmethod
    def index(cls, entry: corpus.Entry) -> _View:
        view = cls(entry, {}, {}, {}, {}, [], [], {}, [])
        for section in entry.spec.sections:
            if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
                view.defined.setdefault(section.name, section)
            elif isinstance(section, ast.AvpTable):
                for row in section.rows:
                    view.tabled.setdefault(row.name, []).append(row)
            elif isinstance(section, ast.ReusedAvps):
                for row in section.rows:
                    view.reused.setdefault(row.name, row.origin)
                    view.reused_rows.setdefault(row.name, []).append(row)
            if isinstance(section, ast.AvpTable | ast.ReusedAvps):
                columns = [
                    marked
                    for column in section.columns
                    if (marked := ast.mark_column(column)) is not None
                ]
                for row in section.rows if columns else ():
                    view.marked.setdefault(row.name, []).append(
                        Marks(
                            section.table,
                            section.source.section,
                            {column: row.marks.get(column) for column in columns},
                        )
                    )
            elif isinstance(section, ast.Message):
                view.messages.append(section)
            elif isinstance(section, ast.ApplicationScope):
                view.applications.append(section)
            elif isinstance(section, ast.Registry):
                view.registries.append(section)
            elif isinstance(section, ast.UndefinedAvp):
                view.undefined.setdefault(section.name, section)
            elif isinstance(section, ast.ValueTable):
                view.value_tables.append(_value_table(entry, section))
            elif isinstance(section, ast.AnswerMessage):
                view.answers.append(section)
        return view

    def cited_in(self, name: str) -> tuple[str, ...]:
        """The clauses whose message or grouped bodies name `name`, in file
        order."""
        return tuple(
            dict.fromkeys(
                section.source.section
                for section in self.entry.spec.sections
                if isinstance(section, ast.Message | ast.AnswerMessage | ast.GroupedAvp)
                and any(rule.name == name for rule in section.avps)
            )
        )
