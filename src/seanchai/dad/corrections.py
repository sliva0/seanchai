"""Output corrections: typed find/replace on a parsed `.dad` tree.

Input patches fix source typos that break extraction; corrections fix data
that parses but is wrong. docs/corrections.md describes both. Every edit
carries an `expect`, and a correction that no longer matches fails, since
upstream fixed it or a re-extraction broke it.

Corrections are declared per specification, as data:

    CORRECTIONS = [
        Correction(
            target=definition("Update-VCSG-Location-Request"),
            field="application_id",
            expect=None,
            replace=16777308,
            reason="clause 7.2.2 assigns the VCSG commands to S7a/S7d;"
            " the command header omits the id",
            versions="18.6.0",
        ),
    ]

Applying is deterministic and not idempotent: applying to corrected output
fails every `expect`, so "already corrected" never looks like "fixed
upstream".

Besides `Correction` (one field) there are `Delete`, `Insert` and `Supply`,
each failing when upstream changes the state it expects. `Accept` changes
nothing; it marks one linter finding as a deliberate override, and `apply`
skips it.
"""

import dataclasses
import importlib.util
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydantic

from .._versions import VersionRange, applies, reviewed_release
from ..errors import SeanchaiError
from . import ast, formatter

__all__ = [
    "UNSPECIFIED",
    "Accept",
    "Correction",
    "CorrectionError",
    "Declaration",
    "Delete",
    "Edit",
    "Insert",
    "Result",
    "Selector",
    "Supply",
    "VersionRange",
    "acceptances",
    "application_scope",
    "apply",
    "apply_with_comments",
    "avp_rule",
    "avp_table",
    "definition",
    "edits",
    "enum_value",
    "flag_rules",
    "header",
    "in_release",
    "load",
    "module_path",
    "notes",
    "registry_reservation",
    "registry_row",
    "reused_avps",
    "reused_row",
    "table_row",
    "undefined",
    "value_row",
    "value_table",
]


class CorrectionError(SeanchaiError, ValueError):
    pass


@dataclass(frozen=True)
class _Unspecified:
    """Sentinel for "this selector field does not filter". `None` is a real
    `application_id` value, so it cannot serve.
    """

    def __repr__(self) -> str:
        return "<unspecified>"


UNSPECIFIED = _Unspecified()


# What a selector matches: each node with its path, in document order.
type _Located = Iterator[tuple[ast.TreePath, ast.Node]]


@dataclass(frozen=True)
class Selector:
    """Base for the ways a correction names its target. Subclasses yield the
    nodes they match, with paths, in document order.

    Subclasses are lower-case so corrections files read as data.
    """

    def locate(self, spec: ast.Specification) -> _Located:
        """Every matching node with its `ast.TreePath`, in document order."""
        raise NotImplementedError

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        """The matching nodes, without their paths."""
        return (node for _, node in self.locate(spec))

    def describe(self) -> str:
        raise NotImplementedError

    def describe_in_place(self) -> str:
        """`describe` without the context the target's own block already
        states, for a note printed inside that block."""
        return self.describe()


@dataclass(frozen=True)
class definition(Selector):
    """A message, grouped AVP or enumerated AVP, by name.

    `application_id`, when given (`None` included), selects only messages
    with exactly that id. `section` selects by clause, for when the name
    itself is what the correction repairs.
    """

    name: str
    application_id: int | _Unspecified | None = UNSPECIFIED
    section: str | None = None

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching definition, at `("sections", i)`."""
        for index, section in enumerate(spec.sections):
            if not isinstance(
                section, ast.Message | ast.GroupedAvp | ast.EnumeratedAvp
            ):
                continue
            if section.name != self.name:
                continue
            if self.section is not None and section.source.section != self.section:
                continue
            if not isinstance(self.application_id, _Unspecified) and (
                not isinstance(section, ast.Message)
                or section.application_id != self.application_id
            ):
                continue
            yield ("sections", index), section

    def describe(self) -> str:
        described = f"definition {self.name!r}"
        if not isinstance(self.application_id, _Unspecified):
            described += f" (application {self.application_id})"
        if self.section is not None:
            described += f" (clause {self.section})"
        return described


@dataclass(frozen=True)
class header(Selector):
    """The file header: the `Specification` node itself, e.g. for a `bases`
    correction.
    """

    def locate(self, spec: ast.Specification) -> _Located:
        """The specification itself, at the root path `()`."""
        yield (), spec

    def describe(self) -> str:
        return "file header"


@dataclass(frozen=True)
class application_scope(Selector):
    """An application scope, by the name it gives the application."""

    name: str

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching block, at `("sections", i)`."""
        yield from (
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.ApplicationScope) and section.name == self.name
        )

    def describe(self) -> str:
        return f"application scope {self.name!r}"


@dataclass(frozen=True)
class undefined(Selector):
    """An `Undefined AVP` block, by the name it declares."""

    name: str

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching block, at `("sections", i)`."""
        yield from (
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.UndefinedAvp) and section.name == self.name
        )

    def describe(self) -> str:
        return f"undefined AVP {self.name!r}"


@dataclass(frozen=True)
class table_row(Selector):
    """One row of an AVP table, by AVP name and optionally table label."""

    name: str
    table: str | None = None

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching row, at `("sections", i, "rows", j)`."""
        for index, section in enumerate(spec.sections):
            if isinstance(section, ast.AvpTable) and (
                self.table is None or section.table == self.table
            ):
                yield from _rows(index, section, self.name)

    def describe(self) -> str:
        suffix = f" (table {self.table})" if self.table is not None else ""
        return f"AVP table row {self.name!r}{suffix}"


@dataclass(frozen=True)
class flag_rules(Selector):
    """The flag rules of one AVP-table row. A correction replaces `must`,
    `may`, `should_not` or `must_not` one at a time; the row's `flag_rules`
    field cannot be replaced whole.
    """

    row: table_row

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching row's rules, at `("sections", i, "rows", j,
        "flag_rules")`."""
        for path, row in self.row.locate(spec):
            assert isinstance(row, ast.AvpTableRow)
            yield (*path, "flag_rules"), row.flag_rules

    def describe(self) -> str:
        return f"flag rules of {self.row.describe()}"


@dataclass(frozen=True)
class avp_table(Selector):
    """An AVP-table section, by its printed label, or None for a table
    printing none, as an RFC's do (RFC 4590's attribute table)."""

    label: str | None

    def locate(self, spec: ast.Specification) -> _Located:
        """Each AVP table carrying the label, at `("sections", i)`."""
        yield from (
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.AvpTable) and section.table == self.label
        )

    def describe(self) -> str:
        if self.label is None:
            return "unlabelled AVP table"
        return f"AVP table {self.label!r}"


@dataclass(frozen=True)
class reused_avps(Selector):
    """A re-used AVPs section, by its printed label; the target of a re-used
    row `Insert`. `section` selects by clause, for blocks with no label.
    """

    label: str | None
    section: str | None = None

    def locate(self, spec: ast.Specification) -> _Located:
        """Each re-used block carrying the label, at `("sections", i)`."""
        yield from (
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.ReusedAvps)
            and section.table == self.label
            and (self.section is None or section.source.section == self.section)
        )

    def describe(self) -> str:
        described = (
            "unlabelled re-used AVPs table"
            if self.label is None
            else f"re-used AVPs table {self.label!r}"
        )
        if self.section is not None:
            described += f" (clause {self.section})"
        return described


@dataclass(frozen=True)
class reused_row(Selector):
    """One row of a re-used AVPs table, by AVP name. `section` names the
    table's clause when several re-used tables list the AVP.
    """

    name: str
    section: str | None = None

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching row, at `("sections", i, "rows", j)`."""
        for index, section in enumerate(spec.sections):
            if isinstance(section, ast.ReusedAvps) and (
                self.section is None or section.source.section == self.section
            ):
                yield from _rows(index, section, self.name)

    def describe(self) -> str:
        described = f"re-used AVPs row {self.name!r}"
        if self.section is not None:
            described += f" (clause {self.section})"
        return described


@dataclass(frozen=True)
class registry_row(Selector):
    """A registry allocation, by code space and code. A code allocated twice
    matches twice and fails as an ambiguous selector."""

    registry: ast.RegistryKind
    code: int

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching allocation, at `("sections", i, "rows", j)`."""
        for index, section in enumerate(spec.sections):
            if not isinstance(section, ast.Registry) or section.registry is not (
                self.registry
            ):
                continue
            for row_index, row in enumerate(section.rows):
                if isinstance(row, ast.RegistryRow) and row.code == self.code:
                    yield ("sections", index, "rows", row_index), row

    def describe(self) -> str:
        return f"{self.registry.value} registry row {self.code}"


@dataclass(frozen=True)
class registry_reservation(Selector):
    """A range a registry table reserves, by its first and last code: TS
    29.230 table 7.1's `; RESERVED 1324..1399`."""

    first: int
    last: int

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching reservation, at `("sections", i, "rows", j)`."""
        for index, section in enumerate(spec.sections):
            if not isinstance(section, ast.Registry):
                continue
            for row_index, row in enumerate(section.rows):
                if isinstance(row, ast.RegistryReservation) and (
                    row.first,
                    row.last,
                ) == (self.first, self.last):
                    yield ("sections", index, "rows", row_index), row

    def describe(self) -> str:
        return f"registry reservation {self.first}..{self.last}"


@dataclass(frozen=True)
class enum_value(Selector):
    """One named value of an enumerated AVP.

    `value` picks one of several values sharing a name. `occurrence` picks
    the n-th (from 1) of identical values, and matches only while the value
    repeats.
    """

    avp: str
    name: str
    value: int | None = None
    occurrence: int | None = None

    def __post_init__(self) -> None:
        if self.occurrence is not None and self.occurrence < 1:
            raise CorrectionError(
                f"value {self.name!r}: occurrence counts from 1, not {self.occurrence}"
            )

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching value, at `("sections", i, "values", j)`."""
        for index, section in enumerate(spec.sections):
            if isinstance(section, ast.EnumeratedAvp) and section.name == self.avp:
                values = [
                    (("sections", index, "values", position), value)
                    for position, value in enumerate(section.values)
                    if isinstance(value, ast.EnumValue)
                    and value.name == self.name
                    and (self.value is None or value.value == self.value)
                ]
                if self.occurrence is None:
                    yield from values
                elif len(values) > 1 and self.occurrence <= len(values):
                    yield values[self.occurrence - 1]

    def describe(self) -> str:
        return f"value {self.name!r} of {self.avp!r}" + self._value_suffix()

    def describe_in_place(self) -> str:
        # The note stands among the enum's own values, so the block already
        # names the AVP.
        return f"value {self.name!r}" + self._value_suffix()

    def _value_suffix(self) -> str:
        suffix = "" if self.value is None else f" (= {self.value})"
        if self.occurrence is not None:
            suffix += f" (occurrence {self.occurrence})"
        return suffix


@dataclass(frozen=True)
class value_table(Selector):
    """A value table, by AVP and clause; for a features table also by
    application and Feature-List-ID."""

    avp: str
    section: str | None = None
    feature_list_id: int | None = None

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching block, at `("sections", i)`."""
        yield from (
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.ValueTable)
            and section.avp == self.avp
            and (self.section is None or section.source.section == self.section)
            and (
                self.feature_list_id is None
                or section.feature_list_id == self.feature_list_id
            )
        )

    def describe(self) -> str:
        described = f"value table of {self.avp!r}"
        if self.section is not None:
            described += f" (clause {self.section})"
        if self.feature_list_id is not None:
            described += f" (Feature-List-ID {self.feature_list_id})"
        return described


@dataclass(frozen=True)
class value_row(Selector):
    """One row of a value table, by name, and by number when a name repeats.
    `parent` is a `value_table` selector, or an AVP name."""

    parent: str | value_table
    name: str
    value: int | None = None

    @property
    def _parent(self) -> value_table:
        if isinstance(self.parent, str):
            return value_table(self.parent)
        return self.parent

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching row, at `("sections", i, "rows", j)`."""
        for path, section in self._parent.locate(spec):
            assert isinstance(section, ast.ValueTable)
            yield from (
                ((*path, "rows", index), row)
                for index, row in enumerate(section.rows)
                if row.name == self.name
                and (self.value is None or row.value == self.value)
            )

    def describe(self) -> str:
        return f"{self.describe_in_place()} of {self._parent.describe()}"

    def describe_in_place(self) -> str:
        # The note stands among the table's own rows.
        suffix = "" if self.value is None else f" (= {self.value})"
        return f"value {self.name!r}{suffix}"


@dataclass(frozen=True)
class avp_rule(Selector):
    """One AVP reference inside a message or grouped-AVP body.

    `parent` is a `definition` selector, or a name as shorthand for
    `definition(name)`. `occurrence` picks the n-th (from 1) rule of that
    name in a body that repeats it, and matches only while it repeats.
    """

    parent: str | definition
    name: str
    occurrence: int | None = None

    def __post_init__(self) -> None:
        if self.occurrence is not None and self.occurrence < 1:
            raise CorrectionError(
                f"AVP rule {self.name!r}: occurrence counts from 1,"
                f" not {self.occurrence}"
            )

    @property
    def _parent(self) -> definition:
        if isinstance(self.parent, str):
            return definition(self.parent)
        return self.parent

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching rule, at `("sections", i, "avps", j)` under its parent."""
        for path, section in self._parent.locate(spec):
            # An enumerated AVP matches `definition` but has no ABNF body.
            if not isinstance(section, ast.Message | ast.GroupedAvp):
                continue
            rules = [
                ((*path, "avps", index), rule)
                for index, rule in enumerate(section.avps)
                if rule.name == self.name
            ]
            if self.occurrence is None:
                yield from rules
            elif len(rules) > 1 and self.occurrence <= len(rules):
                yield rules[self.occurrence - 1]

    def describe(self) -> str:
        return f"{self.describe_in_place()} in {self._parent.describe()}"

    def describe_in_place(self) -> str:
        # The note stands inside the parent's own body, so the block already
        # names the parent.
        return f"AVP rule {self.name!r}{self._occurrence_suffix()}"

    def _occurrence_suffix(self) -> str:
        return "" if self.occurrence is None else f" (occurrence {self.occurrence})"


def _rows(index: int, table: ast.AvpTable | ast.ReusedAvps, name: str) -> _Located:
    return (
        (("sections", index, "rows", position), row)
        for position, row in enumerate(table.rows)
        if row.name == name
    )


@dataclass(frozen=True)
class Correction:
    """Replace one field of one node, given the value it is expected to hold.

    `versions` is advisory: it improves the error message and never gates
    whether the correction applies.
    """

    # A short kebab-case name, unique within its module. A corrected `.dad`
    # file marks the lines an edit reached and cites `<module>#<id>`, so a
    # reader who does not believe a value greps the id and lands on the
    # declaration and its `reason`. A name rather than a line number, so that
    # reformatting a module does not change every corrected file.
    id: str
    target: Selector
    field: str
    expect: Any
    replace: Any
    reason: str
    # "18.6.0" or "18.0.0..18.2.0": the versions this was reviewed against.
    # Advisory: `regenerate` warns when the parsed version is outside it.
    versions: str | VersionRange = "*..*"
    # The module file that declared this edit, stamped by `load()`.
    origin: str = ""

    def __post_init__(self) -> None:
        _check_id(self.id)
        object.__setattr__(self, "versions", VersionRange.parse(self.versions))
        if self.expect == self.replace:
            raise CorrectionError(
                f"{self.target.describe()}: {self.field} correction replaces"
                " a value with itself"
            )

    @property
    def cited(self) -> str:
        return _cited(self)


@dataclass(frozen=True)
class Delete:
    """Remove one node (a table row, an enum value, an AVP rule).

    `expect` is the full node, checked field by field, so the deletion fails
    if upstream changes or removes it.
    """

    id: str
    target: Selector
    expect: ast.Node
    reason: str
    versions: str | VersionRange = "*..*"
    origin: str = ""

    def __post_init__(self) -> None:
        _check_id(self.id)
        object.__setattr__(self, "versions", VersionRange.parse(self.versions))

    @property
    def cited(self) -> str:
        return _cited(self)


@dataclass(frozen=True)
class Insert:
    """Insert one node the source omits.

    `into` and the node's type must match:

    - `AvpTableRow` into `avp_table`, `ReusedAvpRow` into `reused_avps`. A
      `reused_avps(label)` matching no block, where an AVP table has that
      label, creates the re-used block right after the table.
    - `ApplicationScope` into `header()`, placed after the existing scopes;
      no other scope may have its name.
    - `UndefinedAvp` into `header()`, placed after the last section. Checked
      on the corrected tree: nothing in the file may define, tabulate or
      re-use the name, and a body in clause `source.section` must name it.
    - `AvpRule` into a message or grouped `definition()`.
    - `EnumValue` into an enumerated `definition()`; neither its name nor
      its number may be in the list.
    - `ValueRow` into a `value_table()`.

    `after` names the sibling to follow, never a position; `None` appends
    (and is required for header inserts). The insert fails once upstream
    adds a node of that name. `drawn_from` names the clause the fields come
    from, when it is not the target block's.
    """

    id: str
    into: avp_table | reused_avps | header | definition | value_table
    node: (
        ast.AvpTableRow
        | ast.ValueRow
        | ast.ReusedAvpRow
        | ast.ApplicationScope
        | ast.UndefinedAvp
        | ast.AvpRule
        | ast.EnumValue
    )
    after: str | None
    reason: str
    versions: str | VersionRange = "*..*"
    drawn_from: str | None = None
    origin: str = ""

    def __post_init__(self) -> None:
        _check_id(self.id)
        if self.drawn_from is not None and (
            not self.drawn_from or self.drawn_from != " ".join(self.drawn_from.split())
        ):
            raise CorrectionError(
                f"{self.id}: drawn_from must be one line of text, not"
                f" {self.drawn_from!r}"
            )
        object.__setattr__(self, "versions", VersionRange.parse(self.versions))

    @property
    def cited(self) -> str:
        return _cited(self)


@dataclass(frozen=True, kw_only=True)
class Supply:
    """Fill in what a document defines elsewhere, citing the other clause.

    Into an enumerated AVP (`target=definition(name)`): the values its
    `; Values:` line cites. `expect` is that line's text and the section must
    print no values. With `extend=True` the section must print values, and
    every supplied name and number must be new to it.

    Into an AVP-table row (`target=table_row(name, table=)`): `data_type`
    and/or `flag_rules` its cells leave blank. `expect` is the whole row,
    and the file must list the AVP as re-used.

    Every supplied line is marked `;; supplied:`.
    """

    id: str
    target: definition | table_row
    expect: str | ast.AvpTableRow
    reason: str
    values: tuple[ast.EnumEntry, ...] = ()
    extend: bool = False
    data_type: ast.DataType | None = None
    flag_rules: ast.AvpFlagRules | None = None
    versions: str | VersionRange = "*..*"
    origin: str = ""

    def __post_init__(self) -> None:
        _check_id(self.id)
        object.__setattr__(self, "versions", VersionRange.parse(self.versions))
        object.__setattr__(self, "values", tuple(self.values))
        described = self.target.describe()
        if isinstance(self.target, table_row):
            if self.extend:
                raise CorrectionError(f"{described}: a table row has no list to extend")
            self._check_row_form(described)
            return
        if not isinstance(self.target, definition) or not isinstance(self.expect, str):
            raise CorrectionError(
                f"{described}: Supply fills a definition's values, expecting its"
                " `; Values:` text, or a table row's cells, expecting the row"
            )
        if self.data_type is not None or self.flag_rules is not None:
            raise CorrectionError(
                f"{described}: Supply fills an enumerated AVP's values only"
            )
        if not self.values:
            raise CorrectionError(f"{described}: Supply supplies no values")
        if not all(
            isinstance(
                value,
                ast.EnumValue
                | ast.ReservedValues
                | ast.VoidValues
                | ast.VendorSpecificValues,
            )
            for value in self.values
        ):
            raise CorrectionError(
                f"{described}: Supply takes EnumValue, ReservedValues, VoidValues"
                " and VendorSpecificValues nodes"
            )

    def _check_row_form(self, described: str) -> None:
        if not isinstance(self.expect, ast.AvpTableRow):
            raise CorrectionError(f"{described}: Supply into a row expects the row")
        if self.values:
            raise CorrectionError(f"{described}: a table row holds no values")
        if self.data_type is None and self.flag_rules is None:
            raise CorrectionError(f"{described}: Supply supplies nothing")
        if self.data_type is not None and self.expect.data_type is not None:
            raise CorrectionError(
                f"{described}: the row is typed {self.expect.data_type};"
                " Supply fills only a blank type"
            )
        if self.flag_rules is not None and (
            self.expect.flag_rules != ast.AvpFlagRules()
            or self.flag_rules == ast.AvpFlagRules()
        ):
            raise CorrectionError(
                f"{described}: Supply fills blank flag rules with stated ones"
            )

    @property
    def cited(self) -> str:
        return _cited(self)


@dataclass(frozen=True)
class Accept:
    """Acknowledge one linter note on the corrected file as deliberate.

    Changes no data; `seanchai lint --corpus` reports the note as
    `accepted`. `rule`, `target` and `expect` (the exact message) must match
    one note, else the linter reports a stale acceptance (`linter.accept`).
    `reason` cites the clause that makes the override deliberate.
    """

    id: str
    rule: str
    target: Selector
    expect: str
    reason: str
    versions: str | VersionRange = "*..*"
    origin: str = ""

    def __post_init__(self) -> None:
        _check_id(self.id)
        object.__setattr__(self, "versions", VersionRange.parse(self.versions))
        if not _ID_RE.fullmatch(self.rule):
            raise CorrectionError(f"{self.id}: {self.rule!r} names no linter rule")
        if not self.expect:
            raise CorrectionError(f"{self.id}: an acceptance expects no finding")

    @property
    def cited(self) -> str:
        return _cited(self)


# What a corrections module may declare: the edits `apply` makes, and the
# acceptances it skips.
Edit = Correction | Delete | Insert | Supply
Declaration = Edit | Accept


_ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def _check_id(value: object) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise CorrectionError(
            f"correction id {value!r} is not a lowercase kebab-case name"
        )


def _cited(edit: Declaration) -> str:
    """How a `.dad` note refers to an edit: `TS29.272.py#area-scope-vendor`
    once loaded from a module, the bare id before that."""
    return f"{edit.origin}#{edit.id}" if edit.origin else edit.id


@dataclass
class Result:
    """What `apply()` did, one entry per edit, in declaration order."""

    correction: Edit
    node: str
    # For a `Correction`, the field's values; for a `Delete`, the removed node
    # and None; for an `Insert`, None and the new node; for a `Supply`, None
    # and the supplied values.
    old: Any
    new: Any
    # Where the edited node sits *in the returned tree* — the new row for an
    # `Insert`, the enumerated AVP for a `Supply`; for a `Delete`, the
    # position the node stood in, which the sibling that moved up into it now
    # holds (one past the end when the last sibling went), since the node
    # itself produces no lines — so a formatter can mark what an edit
    # reached. Set after the rebuild, because inserts and deletions move what
    # follows them: the path an edit was resolved by belongs to the input
    # tree.
    path: ast.TreePath = ()
    # Where each value a `Supply` adds landed, in its declaration order:
    # after the printed ones for `extend=True`.
    supplied: tuple[ast.TreePath, ...] = ()


def _holds_nodes(value: Any) -> bool:
    if isinstance(value, ast.Node):
        return True
    return isinstance(value, tuple) and any(
        isinstance(item, ast.Node) for item in value
    )


def _corrected(node: ast.Node, correction: Correction) -> ast.Node:
    """Rebuild one node with the field replaced, validating it
    (`model_copy(update=...)` would not).
    """
    if correction.field not in type(node).model_fields:
        raise CorrectionError(
            f"{correction.target.describe()}: {type(node).__name__} has no field"
            f" {correction.field!r}"
        )
    found = getattr(node, correction.field)
    if _holds_nodes(found):
        # Replacing a whole subtree wholesale would have to define what happens
        # to a correction aimed at one of the children it discards. Correcting
        # the child directly is the operation that actually exists.
        raise CorrectionError(
            f"{correction.target.describe()}: {correction.field!r} holds child"
            " nodes; correct the child directly rather than replacing the"
            " structure"
        )
    if found != correction.expect:
        raise CorrectionError(
            f"{correction.target.describe()}: expected {correction.field}"
            f"={correction.expect!r}, found {found!r}"
        )
    values = {name: getattr(node, name) for name in type(node).model_fields}
    values[correction.field] = correction.replace
    try:
        return type(node)(**values)
    except pydantic.ValidationError as error:
        raise CorrectionError(
            f"{correction.target.describe()}: {correction.field}"
            f"={correction.replace!r} is not valid: {error.errors()[0]['msg']}"
        ) from None


def _resolve(spec: ast.Specification, edit: Edit) -> ast.TreePath:
    target = edit.into if isinstance(edit, Insert) else edit.target
    found = [path for path, _ in target.locate(spec)]
    if not found:
        raise CorrectionError(f"{target.describe()}: no match")
    if len(found) > 1:
        raise CorrectionError(
            f"{target.describe()}: {len(found)} matches, narrow the selector"
        )
    return found[0]


def _checked_supply(
    spec: ast.Specification, node: ast.Node, supply: Supply
) -> ast.AvpTableRow | None:
    """Check a `Supply` target (see `Supply`); for a row, return it filled
    in."""
    described = supply.target.describe()
    if isinstance(supply.target, table_row):
        assert isinstance(supply.expect, ast.AvpTableRow)
        if node != supply.expect:
            raise CorrectionError(
                f"{described}: expected {supply.expect!r}, found {node!r}"
            )
        if not any(
            row.name == supply.target.name
            for section in spec.sections
            if isinstance(section, ast.ReusedAvps)
            for row in section.rows
        ):
            raise CorrectionError(
                f"{described}: Supply fills a row whose AVP the file re-uses,"
                " and no re-used table lists it"
            )
        assert isinstance(node, ast.AvpTableRow)
        values = {name: getattr(node, name) for name in type(node).model_fields}
        if supply.data_type is not None:
            values["data_type"] = supply.data_type
        if supply.flag_rules is not None:
            values["flag_rules"] = supply.flag_rules
        return ast.AvpTableRow(**values)
    if not isinstance(node, ast.EnumeratedAvp):
        raise CorrectionError(
            f"{described}: Supply requires an enumerated AVP,"
            f" matched a {type(node).__name__}"
        )
    if node.values_source != supply.expect:
        raise CorrectionError(
            f"{described}: expected values_source={supply.expect!r},"
            f" found {node.values_source!r}"
        )
    if supply.extend:
        if not node.values:
            raise CorrectionError(
                f"{described}: the section prints no values;"
                " extend=True appends to a printed list"
            )
        _check_new_values(described, node.values, supply.values)
    elif node.values:
        raise CorrectionError(
            f"{described}: the section already holds {len(node.values)} values;"
            " Supply fills only an empty list"
        )
    return None


def _span(entry: ast.EnumEntry) -> tuple[int, int]:
    if isinstance(entry, ast.EnumValue):
        return entry.value, entry.value
    return entry.first, entry.last


def _check_new_values(
    described: str,
    printed: Sequence[ast.EnumEntry],
    supplied: Sequence[ast.EnumEntry],
) -> None:
    """Check that `Supply(extend=True)` values share no name or number with
    the section's entries, ranges included."""
    names = {entry.name for entry in printed if isinstance(entry, ast.EnumValue)}
    for entry in supplied:
        if isinstance(entry, ast.EnumValue) and entry.name in names:
            raise CorrectionError(
                f"{described}: value {entry.name!r} is already present"
            )
        first, last = _span(entry)
        for other in printed:
            low, high = _span(other)
            if first <= high and low <= last:
                number = first if first == last else f"{first}-{last}"
                raise CorrectionError(f"{described}: value {number} is already present")


def _checked_deletion(node: ast.Node, delete: Delete) -> None:
    """`expect` names the whole node: a changed row may no longer deserve
    deletion, so any difference means the declaration wants re-review."""
    if node == delete.expect:
        return
    described = delete.target.describe()
    if type(node) is not type(delete.expect):
        raise CorrectionError(
            f"{described}: expected a {type(delete.expect).__name__},"
            f" matched a {type(node).__name__}"
        )
    differing = [
        f"{name}: expected {getattr(delete.expect, name)!r},"
        f" found {getattr(node, name)!r}"
        for name in type(node).model_fields
        if getattr(node, name) != getattr(delete.expect, name)
    ]
    raise CorrectionError(
        f"{described}: the node to delete has changed — " + "; ".join(differing)
    )


@dataclass(frozen=True)
class _Added:
    """A node an edit adds rather than finds: the edit's declaration index,
    and the node's position among the ones that edit adds."""

    edit: int
    item: int = 0


# Where a tuple item in the rebuild came from: its path in the tree being
# rebuilt, or the edit that adds it.
type _Origin = ast.TreePath | _Added


def _inserted(
    parent: ast.Node,
    rows: list[tuple[_Origin, Any]] | None,
    insert: Insert,
    origin: _Added,
    path: ast.TreePath,
) -> list[tuple[_Origin, Any]]:
    """Return the rows of the table at `path` (or the body's members) with
    the declared one inserted, each with its origin, validated. `rows` holds
    earlier inserts' result, None before the first."""
    described = insert.into.describe()
    field = _inserted_field(insert)
    row_type: type[ast.Node] = (
        ast.EnumValue
        if isinstance(parent, ast.EnumeratedAvp)
        else ast.AvpRule
        if isinstance(insert.into, definition)
        else ast.AvpTableRow
        if isinstance(insert.into, avp_table)
        else ast.ValueRow
        if isinstance(insert.into, value_table)
        else ast.ReusedAvpRow
    )
    if isinstance(insert.into, definition):
        if not isinstance(parent, ast.Message | ast.GroupedAvp) and not (
            isinstance(parent, ast.EnumeratedAvp)
            and isinstance(insert.node, ast.EnumValue)
        ):
            raise CorrectionError(
                f"{described}: Insert requires a message or grouped AVP,"
                " or an enumerated AVP for a value,"
                f" matched {type(parent).__name__}"
            )
    elif not isinstance(parent, ast.AvpTable | ast.ReusedAvps | ast.ValueTable):
        raise CorrectionError(
            f"{described}: Insert requires a table, matched {type(parent).__name__}"
        )
    if not isinstance(insert.node, row_type):
        raise CorrectionError(
            f"{described}: the inserted node must be a {row_type.__name__},"
            f" not a {type(insert.node).__name__}"
        )
    if rows is None:
        rows = [
            ((*path, field, index), row)
            for index, row in enumerate(getattr(parent, field))
        ]
    if any(getattr(row, "name", None) == insert.node.name for _, row in rows):
        raise CorrectionError(
            f"{described}: row {insert.node.name!r} is already present"
        )
    if isinstance(insert.node, ast.EnumValue) and any(
        row.value == insert.node.value
        if isinstance(row, ast.EnumValue)
        else row.first <= insert.node.value <= row.last
        for _, row in rows
    ):
        raise CorrectionError(
            f"{described}: value {insert.node.value} is already present"
        )
    rows = list(rows)
    if insert.after is None:
        rows.append((origin, insert.node))
    else:
        positions = [
            index
            for index, (_, row) in enumerate(rows)
            if getattr(row, "name", None) == insert.after
        ]
        if not positions:
            raise CorrectionError(
                f"{described}: after row {insert.after!r} is not present"
            )
        if len(positions) > 1:
            raise CorrectionError(
                f"{described}: after row {insert.after!r} is ambiguous"
            )
        rows.insert(positions[0] + 1, (origin, insert.node))
    values = {name: getattr(parent, name) for name in type(parent).model_fields}
    values[field] = tuple(row for _, row in rows)
    try:
        type(parent)(**values)
    except pydantic.ValidationError as error:
        raise CorrectionError(
            f"{described}: inserted row is not valid: {error.errors()[0]['msg']}"
        ) from None
    return rows


def _inserted_field(insert: Insert) -> str:
    """The tuple field an `Insert` adds to: a body's members, an enumerated
    AVP's values or a table's rows."""
    if isinstance(insert.node, ast.EnumValue):
        return "values"
    return "avps" if isinstance(insert.into, definition) else "rows"


def _inserted_application_scope(
    spec: ast.Specification,
    sections: list[tuple[_Origin, Any]] | None,
    insert: Insert,
    origin: _Added,
) -> list[tuple[_Origin, Any]]:
    """Return the file's sections with the declared application scope or
    undefined AVP placed (see `Insert`), each with its origin. `sections`
    holds earlier inserts' result, None before the first."""
    described = insert.into.describe()
    node = insert.node
    if not isinstance(node, ast.ApplicationScope | ast.UndefinedAvp):
        raise CorrectionError(
            f"{described}: only an ApplicationScope or an UndefinedAvp can be"
            f" inserted into the file, not a {type(node).__name__}"
        )
    if sections is None:
        sections = [
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
        ]
    if isinstance(node, ast.UndefinedAvp):
        if insert.after is not None:
            raise CorrectionError(
                f"{described}: an undefined AVP ends the file; after must be None"
            )
        # What it expects is checked on the corrected tree (`_check_undefined`).
        return [*sections, (origin, node)]
    if insert.after is not None:
        raise CorrectionError(
            f"{described}: an application scope follows the others; after must be None"
        )
    if any(
        isinstance(section, ast.ApplicationScope) and section.name == node.name
        for _, section in sections
    ):
        raise CorrectionError(
            f"{described}: application scope {node.name!r} is already present"
        )
    position = max(
        (
            index + 1
            for index, (_, section) in enumerate(sections)
            if isinstance(section, ast.ApplicationScope)
        ),
        default=0,
    )
    return [*sections[:position], (origin, node), *sections[position:]]


def _check_undefined(spec: ast.Specification, node: ast.UndefinedAvp) -> None:
    """Check an inserted `UndefinedAvp` against the corrected file (see
    `Insert`)."""
    described = f"undefined AVP {node.name!r}"
    for section in spec.sections:
        if (
            isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp)
            and section.name == node.name
        ):
            raise CorrectionError(
                f"{described}: clause {section.source.section} defines it"
            )
    for section in spec.sections:
        if isinstance(section, ast.AvpTable | ast.ReusedAvps) and any(
            row.name == node.name for row in section.rows
        ):
            raise CorrectionError(
                f"{described}: the table of clause {section.source.section} lists it"
            )
    declared = sum(
        isinstance(section, ast.UndefinedAvp) and section.name == node.name
        for section in spec.sections
    )
    if declared > 1:
        raise CorrectionError(f"{described}: declared {declared} times")
    if not any(
        isinstance(section, ast.Message | ast.GroupedAvp)
        and section.source.section == node.source.section
        and any(rule.name == node.name for rule in section.avps)
        for section in spec.sections
    ):
        raise CorrectionError(
            f"{described}: no message or grouped body in clause"
            f" {node.source.section} names it"
        )


def _created_blocks(
    spec: ast.Specification, corrections: Sequence[Edit]
) -> tuple[ast.Specification, list[int], dict[reused_avps, ast.TreePath]]:
    """Place an empty re-used block after each AVP table whose label an
    `Insert` targets and no re-used block has (see `Insert`).

    Returns the tree to rebuild, each input section's index in it (plus the
    end), and the placeholders' paths by selector. Placeholders skip
    validation (a table may not be empty); the rebuild validates them once
    filled. Selectors resolve against the original tree.
    """
    labels = {
        edit.into
        for edit in corrections
        if isinstance(edit, Insert)
        and isinstance(edit.into, reused_avps)
        and not any(edit.into.find(spec))
    }
    created: dict[int, tuple[reused_avps, ast.ReusedAvps]] = {}
    for selector in labels:
        tables = [
            (index, section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.AvpTable)
            and section.table == selector.label
            and (selector.section is None or section.source.section == selector.section)
        ]
        if len(tables) != 1:
            # Not a creation: `_resolve` reports the selector's no-match.
            continue
        index, table = tables[0]
        created[index] = (
            selector,
            ast.ReusedAvps.model_construct(
                table=selector.label,
                source=table.source,
                columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
                rows=(),
            ),
        )
    positions: list[int] = []
    sections: list[ast.Section] = []
    placeholders: dict[reused_avps, ast.TreePath] = {}
    for index, section in enumerate(spec.sections):
        positions.append(len(sections))
        sections.append(section)
        if (made := created.get(index)) is not None:
            selector, placeholder = made
            placeholders[selector] = ("sections", len(sections))
            sections.append(placeholder)
    # One past the last input section is one past the tree's last: where a
    # comment block ending the file stands.
    positions.append(len(sections))
    if not placeholders:
        return spec, positions, placeholders
    tree = spec.model_copy(update={"sections": tuple(sections)})
    return tree, positions, placeholders


def _in_tree(path: ast.TreePath, positions: list[int]) -> ast.TreePath:
    """An input path in the tree `_created_blocks` returned, where only
    section indices can have moved."""
    match path:
        case ("sections", int() as index, *rest):
            return ("sections", positions[index], *rest)
        case _:
            return path


@dataclass
class _Plan:
    """What `apply` resolved, keyed by path in the tree being rebuilt."""

    # Nodes with their corrected fields, chained when one node is corrected
    # in several fields.
    replaced: dict[ast.TreePath, ast.Node] = dataclasses.field(default_factory=dict)
    deleted: set[ast.TreePath] = dataclasses.field(default_factory=set)
    # A table's rows once its `Insert`s are in, keyed by the table's path
    # plus "rows", and a body's members by its path plus "avps"; an
    # enumerated AVP's values once `Supply` fills them, by its path plus
    # "values".
    rows: dict[ast.TreePath, list[tuple[_Origin, Any]]] = dataclasses.field(
        default_factory=dict
    )
    # Filled by the rebuild: where each node, by its path in the tree being
    # rebuilt or by its `Insert`, landed in the result.
    placed: dict[_Origin, ast.TreePath] = dataclasses.field(default_factory=dict)


def _rebuilt(node: Any, path: ast.TreePath, out: ast.TreePath, plan: _Plan) -> Any:
    """Rebuild the tree by path: swap in corrected nodes, add inserted ones,
    drop deleted ones. `path` is where `node` sits in the input tree, `out`
    where it lands in the result.

    A corrected node is descended into, so corrections to its children still
    apply; corrections never replace a field holding child nodes. Every
    rebuilt node is validated, so a correction breaking an ancestor's
    invariant (or deleting a table's last row) fails here.
    """
    if not isinstance(node, ast.Node):
        return node
    plan.placed[path] = out
    node = plan.replaced.get(path, node)
    values = {}
    for name in type(node).model_fields:
        value = getattr(node, name)
        if not isinstance(value, tuple):
            values[name] = _rebuilt(value, (*path, name), (*out, name), plan)
            continue
        items = plan.rows.get((*path, name))
        if items is None:
            items = [((*path, name, index), item) for index, item in enumerate(value)]
        kept = []
        for origin, item in items:
            # A deleted node produces no lines, so what a formatter can mark
            # is the position it stood in, which the sibling that moved up
            # into it now holds — or which is one past the end, when it was
            # the last.
            if origin in plan.deleted:
                plan.placed[origin] = (*out, name, len(kept))
            elif isinstance(origin, _Added):
                # An inserted row or supplied value was validated when its
                # edit was declared and has no input to correct.
                plan.placed[origin] = (*out, name, len(kept))
                kept.append(item)
            else:
                kept.append(_rebuilt(item, origin, (*out, name, len(kept)), plan))
        values[name] = tuple(kept)
    try:
        return type(node)(**values)
    except pydantic.ValidationError as error:
        raise CorrectionError(
            f"corrected {type(node).__name__} is not valid: {error.errors()[0]['msg']}"
        ) from None


def apply(
    spec: ast.Specification, corrections: Sequence[Declaration]
) -> tuple[ast.Specification, list[Result]]:
    """Apply every edit, or none; acceptances are skipped.

    Every edit is checked against the original tree before anything is
    rebuilt.
    """
    applied = _applied(spec, edits(corrections))
    return applied.rebuilt, applied.results


def edits(declarations: Sequence[Declaration]) -> list[Edit]:
    """The declarations that change data, in declaration order."""
    return [item for item in declarations if not isinstance(item, Accept)]


def in_release(
    declarations: Sequence[Declaration], version: str | None
) -> list[Declaration]:
    """Return the declarations for `version`'s release
    (`_versions.reviewed_release`); version ranges within it are advisory."""
    release = reviewed_release(
        [VersionRange.parse(item.versions) for item in declarations], version
    )
    return [
        item
        for item in declarations
        if applies(VersionRange.parse(item.versions), release)
    ]


def acceptances(declarations: Sequence[Declaration]) -> list[Accept]:
    """The declarations acknowledging linter findings, in declaration order."""
    return [item for item in declarations if isinstance(item, Accept)]


@dataclass
class _Applied:
    """What `apply` did, plus what `apply_with_comments` needs to map input
    lines to output lines."""

    rebuilt: ast.Specification
    results: list[Result]
    tree: ast.Specification
    positions: list[int]
    plan: _Plan
    origins: list[_Origin]


def _applied(spec: ast.Specification, corrections: Sequence[Edit]) -> _Applied:
    # Selectors and `expect` checks see only the input; the rebuild also
    # walks the re-used blocks `Insert`s create.
    tree, positions, placeholders = _created_blocks(spec, corrections)
    plan = _Plan()
    targets: dict[ast.TreePath, str] = {}  # path -> the selector that reached it
    claimed: set[tuple[ast.TreePath, str]] = set()
    supplied: set[ast.TreePath] = set()  # rows a `Supply` fills
    results = []
    origins: list[_Origin] = []  # per result: what `plan.placed` knows it by
    for index, correction in enumerate(corrections):
        if (
            isinstance(correction, Insert)
            and isinstance(correction.into, reused_avps)
            and correction.into in placeholders
        ):
            path = placeholders[correction.into]
        else:
            path = _in_tree(_resolve(spec, correction), positions)
        # Looked up in the tree rather than kept from the selector, so a
        # `header()` correction rebuilds the root that holds the placeholders.
        node: ast.Node = ast.node_at(tree, path)
        target = (
            correction.into if isinstance(correction, Insert) else correction.target
        )
        described = target.describe()
        if isinstance(correction, Delete) and path in plan.deleted:
            raise CorrectionError(f"{described}: deleted more than once")
        if path in plan.deleted or (
            isinstance(correction, Delete)
            and (
                path in plan.replaced
                or (*path, "rows") in plan.rows
                or (*path, "avps") in plan.rows
                or (*path, "values") in plan.rows
            )
        ):
            raise CorrectionError(
                f"{described}: the node is both corrected and deleted;"
                " a deleted node has no fields worth fixing"
            )
        targets[path] = described
        if isinstance(correction, Delete):
            # Only an item of a tuple leaves a place behind: the file header
            # is the tree itself, and what a deletion's note stands in is the
            # position a section, rule, value or row was taken from.
            if not path or not isinstance(path[-1], int):
                raise CorrectionError(
                    f"{described}: only a section, AVP rule, enum value or"
                    " table row can be deleted"
                )
            _checked_deletion(node, correction)
            plan.deleted.add(path)
            results.append(
                Result(correction=correction, node=described, old=node, new=None)
            )
            origins.append(path)
            continue
        if isinstance(correction, Supply):
            filled = _checked_supply(tree, node, correction)
            if filled is not None:
                if path in plan.replaced or any(
                    claim[: len(path)] == path for claim, _ in claimed
                ):
                    raise CorrectionError(
                        f"{described}: the row is both corrected and supplied"
                    )
                plan.replaced[path] = filled
                supplied.add(path)
                results.append(
                    Result(correction=correction, node=described, old=node, new=filled)
                )
                origins.append(path)
                continue
            if (*path, "values") in plan.rows:
                raise CorrectionError(f"{described}: values supplied more than once")
            assert isinstance(node, ast.EnumeratedAvp)
            printed = [
                ((*path, "values", position), value)
                for position, value in enumerate(node.values)
            ]
            plan.rows[(*path, "values")] = [
                *printed,
                *(
                    (_Added(index, position), value)
                    for position, value in enumerate(correction.values)
                ),
            ]
            results.append(
                Result(
                    correction=correction,
                    node=f"{described}, {len(correction.values)} values",
                    old=None,
                    new=correction.values,
                )
            )
            origins.append(path)
            continue
        if isinstance(correction, Insert) and isinstance(correction.into, header):
            plan.rows[("sections",)] = _inserted_application_scope(
                tree, plan.rows.get(("sections",)), correction, _Added(index)
            )
            kind = (
                "undefined AVP"
                if isinstance(correction.node, ast.UndefinedAvp)
                else "application scope"
            )
            results.append(
                Result(
                    correction=correction,
                    node=f"{kind} {correction.node.name!r}",
                    old=None,
                    new=correction.node,
                )
            )
            origins.append(_Added(index))
            continue
        if isinstance(correction, Insert):
            field = _inserted_field(correction)
            plan.rows[(*path, field)] = _inserted(
                plan.replaced.get(path, node),
                plan.rows.get((*path, field)),
                correction,
                _Added(index),
                path,
            )
            kind = {"avps": "member", "values": "value"}.get(field, "row")
            results.append(
                Result(
                    correction=correction,
                    node=f"{described}, {kind} {correction.node.name!r}",
                    old=None,
                    new=correction.node,
                )
            )
            origins.append(_Added(index))
            continue
        if any(path[: len(row)] == row for row in supplied):
            raise CorrectionError(
                f"{described}: the row is both corrected and supplied"
            )
        claim = (path, correction.field)
        if claim in claimed:
            raise CorrectionError(
                f"{described}: {correction.field} is corrected"
                " more than once; combine the corrections"
            )
        claimed.add(claim)
        # Chain onto an earlier correction of the same node, so two fields of
        # one row can be corrected independently.
        plan.replaced[path] = _corrected(plan.replaced.get(path, node), correction)
        results.append(
            Result(
                correction=correction,
                node=described,
                old=getattr(node, correction.field),
                new=correction.replace,
            )
        )
        origins.append(path)
    rebuilt = _rebuilt(tree, (), (), plan)
    for edit in corrections:
        if isinstance(edit, Insert) and isinstance(edit.node, ast.UndefinedAvp):
            _check_undefined(rebuilt, edit.node)
    for path, description in targets.items():
        if path not in plan.placed:
            raise CorrectionError(
                f"{description}: the selected node sits inside a subtree another"
                " edit deleted"
            )
    # One result per edit, in declaration order.
    for index, (result, origin) in enumerate(zip(results, origins, strict=True)):
        if origin not in plan.placed:
            # Reporting success for a row the output does not hold would be
            # the silent loss the `expect` contract exists to prevent.
            raise CorrectionError(
                f"{result.node}: the inserted row is not in the corrected tree"
            )
        result.path = plan.placed[origin]
        edit = result.correction
        if isinstance(edit, Supply) and isinstance(edit.target, definition):
            result.supplied = tuple(
                plan.placed[_Added(index, position)]
                for position in range(len(edit.values))
            )
    return _Applied(rebuilt, results, tree, positions, plan, origins)


def apply_with_comments(
    spec: ast.Specification,
    comments: formatter.Comments,
    corrections: Sequence[Declaration],
) -> tuple[ast.Specification, list[Result], formatter.Comments]:
    """`apply` for a tree with `;;` comments (from
    `parser.parse_with_comments`); returns the comments re-keyed to where
    their lines landed, merged with `notes(results)`.

    A comment moves with its line. Comments on a deleted line stay in its
    place, before the deletion's note; inside a deleted section they become
    a block of their own. Comments on a removed directive line go to the
    block's first line, ahead of the note. A comment trails before a note.
    """
    applied = _applied(spec, edits(corrections))
    # Per place, in print order: each note or comment with the input
    # position it belongs at, and whether it is an edit's note.
    places: dict[tuple[str, ast.TreePath], list[tuple[int, str, bool]]] = {}
    for kind, path, note, index in _noted(applied.results):
        # Only a deletion's note shares a standing or detached place with a
        # comment; it belongs where the deleted node stood, an index in its
        # tuple. A trailing note follows the comments on its line.
        at = applied.origins[index]
        deleted = isinstance(applied.results[index].correction, Delete)
        order = at[-1] if deleted and isinstance(at, tuple) else -1
        assert isinstance(order, int)
        places.setdefault((kind, path), []).append((order, note, True))
    # Comments an edit brings to one place keep the order they printed in.
    printed = _print_order(spec, comments)
    moved = sorted(
        (
            (*_landing(kind, _in_tree(path, applied.positions), applied), note, line)
            for (kind, path), lines in _placed(comments)
            for note, line in zip(lines, printed[kind, path], strict=True)
        ),
        key=lambda each: (each[2], each[4]),
    )
    for kind, path, order, note, _ in moved:
        place = places.setdefault((kind, path), [])
        # After the notes of nodes that stood before it, and after the
        # comments placed so far, which came earlier in the input.
        position = max(
            (
                index + 1
                for index, (at, _, is_note) in enumerate(place)
                if not is_note or (at < order and at >= 0)
            ),
            default=0,
        )
        place.insert(position, (order, note, False))
    merged: dict[str, _NoteMap] = {kind: {} for kind in _KINDS}
    for (kind, path), place in places.items():
        merged[kind][path] = [note for _, note, _ in place]
    return (
        applied.rebuilt,
        applied.results,
        formatter.Comments(merged["trailing"], merged["standing"], merged["detached"]),
    )


_KINDS = ("trailing", "standing", "detached")


def _placed(
    comments: formatter.Comments,
) -> Iterator[tuple[tuple[str, ast.TreePath], Sequence[str]]]:
    """Each place's comments, by placement and path."""
    for kind, kept in zip(_KINDS, comments, strict=True):
        for path, lines in kept.items():
            yield (kind, path), lines


def _print_order(
    spec: ast.Specification, comments: formatter.Comments
) -> dict[tuple[str, ast.TreePath], list[int]]:
    """Where in `spec`'s file each comment prints, by placement and path:
    found by printing a numbered tag for each and reading them back."""
    tags: dict[tuple[str, ast.TreePath], list[str]] = {}
    for count, (place, lines) in enumerate(_placed(comments)):
        tags[place] = [f"\0{count}.{line}\0" for line in range(len(lines))]
    tagged = formatter.Comments(
        *(
            {path: tags[kind, path] for path in kept}
            for kind, kept in zip(_KINDS, comments, strict=True)
        )
    )
    text = formatter.format_spec(spec, tagged)
    return {place: [text.index(tag) for tag in found] for place, found in tags.items()}


def _landing(
    kind: str, path: ast.TreePath, applied: _Applied
) -> tuple[str, ast.TreePath, int]:
    """Return where a comment at input `path` lands: its placement, output
    path, and input position for ordering among a deletion's notes."""
    plan = applied.plan
    for depth in range(1, len(path) + 1):
        gone = path[:depth]
        if gone in plan.deleted:
            # A deleted section leaves a gap between sections, which only a
            # block of its own can fill; anything else stands in its place.
            placed = "detached" if len(gone) == 2 else "standing"
            position = gone[-1]
            assert isinstance(position, int)
            return placed, plan.placed[gone], position
    order = path[-1] if path and isinstance(path[-1], int) else -1
    for depth in range(len(path), -1, -1):
        if (found := path[:depth]) not in plan.placed:
            continue
        out = plan.placed[found]
        match path[depth:]:
            case ():
                return kind, out, order
            case (str() as field, int() as end) if end == len(
                getattr(ast.node_at(applied.tree, found), field)
            ):
                # One past a tuple's end: the end of what that tuple became.
                ended = len(getattr(ast.node_at(applied.rebuilt, out), field))
                return kind, (*out, field, ended), order
            case (str(), int()):
                pass  # an item that is neither in the tree nor its end
            case (str(), *_) as rest if _prints(applied.rebuilt, (*out, *rest)):
                return kind, (*out, *rest), order
            case (str(), *_):
                # A correction emptied the field and its directive line went
                # with it. The comments go where the correction's note does,
                # to the line naming the block, ahead of the note.
                named = ("specification",) if not out else (*out[:2], "type")
                return kind, named, -1
        break
    raise CorrectionError(f"comment at {path} attaches to nothing in the tree")


def _prints(spec: ast.Specification, path: ast.TreePath) -> bool:
    """Whether the field at `path` prints a line: an absent value, or the
    empty `; Bases:` list, prints none."""
    return ast.node_at(spec, path) not in (None, ())


_SECTION_TYPES = (
    ast.ApplicationScope,
    ast.Message,
    ast.AnswerMessage,
    ast.GroupedAvp,
    ast.ReprintedAvp,
    ast.EnumeratedAvp,
    ast.AvpTable,
    ast.ReusedAvps,
    ast.Registry,
    ast.UndefinedAvp,
    ast.ValueTable,
)


type _NoteMap = dict[ast.TreePath, list[str]]


def notes(results: list[Result]) -> formatter.Comments:
    """Return `;;` notes marking what `apply` touched, keyed by path in the
    rebuilt tree, as the `formatter.Comments` that `format_spec` takes.

    A trailing note on the corrected line (`_cited_line`) names only the
    declaration. A deleted node gets a standing note in its place naming
    what is gone; a deleted section gets a detached one. Inserted rows trail
    `inserted:` and supplied values `supplied:`.
    """
    placed: dict[str, _NoteMap] = {"trailing": {}, "standing": {}, "detached": {}}
    for kind, path, note, _ in _noted(results):
        placed[kind].setdefault(path, []).append(note)
    return formatter.Comments(
        placed["trailing"], placed["standing"], placed["detached"]
    )


def _noted(results: list[Result]) -> Iterator[tuple[str, ast.TreePath, str, int]]:
    """Each note `notes` places: its placement, path, text and the index of
    the result it marks."""
    for index, result in enumerate(results):
        edit = result.correction
        if isinstance(edit, Delete):
            kind = "detached" if isinstance(result.old, _SECTION_TYPES) else "standing"
            yield (
                kind,
                result.path,
                f"deleted: {edit.target.describe_in_place()} ({edit.cited})",
                index,
            )
            continue
        if isinstance(edit, Insert):
            # An application scope or undefined AVP has no line of its own,
            # so the line that opens it carries the note.
            line = (
                (*result.path, "type")
                if isinstance(edit.node, ast.ApplicationScope | ast.UndefinedAvp)
                else result.path
            )
            drawn = "" if edit.drawn_from is None else f"from {edit.drawn_from} "
            yield "trailing", line, f"inserted: {drawn}({edit.cited})", index
            continue
        if isinstance(edit, Supply):
            if isinstance(edit.target, table_row):
                # The supplied cells print on the row's line.
                yield "trailing", result.path, f"supplied: ({edit.cited})", index
                continue
            for path in result.supplied:
                yield "trailing", path, f"supplied: ({edit.cited})", index
            continue
        yield (
            "trailing",
            _cited_line(result, edit),
            f"corrected: ({edit.cited})",
            index,
        )


def _cited_line(result: Result, correction: Correction) -> ast.TreePath:
    """Return the path of the line a correction's note trails.

    A definition's note trails its header rule. For the file header, a
    table, an application scope or an undefined AVP it trails the field's
    directive line, or the block's first line if the correction removed it.
    """
    if isinstance(correction.target, flag_rules):
        # The rules print as cells of their row's line.
        return result.path[:-1]
    if not isinstance(
        correction.target,
        header | avp_table | reused_avps | application_scope | undefined | value_table,
    ):
        return result.path
    if result.new is not None and result.new != ():
        return (*result.path, correction.field)
    return ("specification",) if not result.path else (*result.path, "type")


def module_path(directory: Path, specification: str) -> Path:
    """Return the corrections module path for `specification` in
    `directory`.

    Loading it executes Python, so two checks hold: `ast.spec_ref` accepts
    only canonical names, and the resolved path must sit directly in the
    resolved directory, so no symlink reaches outside it.
    """
    try:
        reference = ast.spec_ref(specification)
    except ast.SpecRefError as error:
        raise CorrectionError(str(error)) from None
    root = directory.resolve()
    path = (root / f"{reference}.py").resolve()
    if path.parent != root:
        raise CorrectionError(
            f"corrections for {specification!r} would resolve to {path}, outside {root}"
        )
    return path


def load(
    directory: Path | None, specification: str, required: bool = False
) -> list[Declaration]:
    """Import `<directory>/<SpecRef>.py` and return its `CORRECTIONS` list,
    acceptances included.

    This executes Python from `directory`, so the CLI requires the path to
    be given explicitly. With `required`, a missing module or one with no
    edit is an error; otherwise a missing module gives an empty list.
    """
    if directory is None:
        if required:
            raise CorrectionError("no corrections directory was given")
        return []
    path = module_path(directory, specification)
    if not path.is_file():
        if required:
            raise CorrectionError(
                f"no corrections module for {specification!r}: {path}"
            )
        return []
    corrections = _corrections_of(path)
    if required and not edits(corrections):
        raise CorrectionError(f"{path} declares no corrections")
    return corrections


def _corrections_of(path: Path) -> list[Declaration]:
    module_spec = importlib.util.spec_from_file_location(path.stem, path)
    if module_spec is None or module_spec.loader is None:
        raise CorrectionError(f"cannot load corrections from {path}")
    module = importlib.util.module_from_spec(module_spec)
    try:
        module_spec.loader.exec_module(module)
    except CorrectionError:
        # A `Correction(...)` the module itself declares wrongly; its message
        # already names the target, and the path is added by the caller's report.
        raise
    except Exception as error:
        raise CorrectionError(
            f"{path} failed to import: {type(error).__name__}: {error}"
        ) from error
    corrections = getattr(module, "CORRECTIONS", None)
    if corrections is None:
        raise CorrectionError(f"{path} defines no CORRECTIONS list")
    # Not any iterable: a generator would be consumed by the type check below
    # and leave an empty, silently uncorrected result.
    if not isinstance(corrections, list | tuple):
        raise CorrectionError(
            f"{path}: CORRECTIONS must be a list, not a {type(corrections).__name__}"
        )
    if not all(
        isinstance(item, Correction | Delete | Insert | Supply | Accept)
        for item in corrections
    ):
        raise CorrectionError(
            f"{path}: CORRECTIONS must hold Correction, Delete, Insert, Supply"
            " or Accept objects"
        )
    seen: set[str] = set()
    for item in corrections:
        if item.id in seen:
            raise CorrectionError(
                f"{path}: correction id {item.id!r} is declared twice"
            )
        seen.add(item.id)
    # The module name is what a `.dad` note cites next to the id; stamped here
    # rather than captured at construction so a module cannot misstate it.
    return [dataclasses.replace(item, origin=path.name) for item in corrections]
