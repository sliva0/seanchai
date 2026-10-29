"""Output corrections: typed find/replace on a parsed `.dad` tree.

The second of the two patch layers — input patches fix source typos that would
break extraction, corrections fix data that extracts and parses fine but is
*wrong*. The framing and full semantics live in docs/corrections.md; the short
version is that `expect` is mandatory, because a correction that no longer
matches has either been fixed upstream or been broken by a re-extraction, and
both are events worth failing on rather than silently skipping.

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

Applying is deterministic but deliberately not idempotent: feeding corrected
output back in makes every `expect` fail, because treating an already-applied
correction as a no-op would make "already corrected" indistinguishable from
"fixed upstream".

Beside field replacement there are two narrow structural operations: `Delete`
for a node that should not exist at all, and `Insert` for an AVP-table row the
source defines but omits from the table. Both fail loudly when upstream changes
the state that justified them: `Delete` expects the doomed node field-for-field,
and `Insert` expects the row to be absent, so it fails the day upstream adds it.
"""

import dataclasses
import importlib.util
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydantic

from ..versions import VersionRange
from . import ast


class CorrectionError(ValueError):
    pass


@dataclass(frozen=True)
class _Unspecified:
    """Sentinel for "this selector field does not filter".

    `None` cannot serve: it is a real `application_id` value — precisely the
    one the TS 29.272 VCSG headers carry — so overloading it would make the
    omitted-id definition unselectable.
    """

    def __repr__(self) -> str:
        return "<unspecified>"


UNSPECIFIED = _Unspecified()


# What a selector matches: each node with its path, in document order.
type _Located = Iterator[tuple[ast.TreePath, ast.Node]]


@dataclass(frozen=True)
class Selector:
    """Base for the ways a correction names its target. Subclasses yield the
    nodes they match with their paths, in document order, from a whole
    specification.

    The subclasses are deliberately lower-case: a corrections file is data, and
    `table_row("MME-Location-Information")` reads as such where
    `TableRow(...)` would read as machinery.
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
        """The description a note printed *inside* the target's own block can
        use: context the surrounding lines already state is dropped there,
        while `describe` keeps it for errors and logs read on their own."""
        return self.describe()


@dataclass(frozen=True)
class definition(Selector):
    """A message, grouped AVP or enumerated AVP, by name.

    `application_id` narrows the TS 29.272 case of one command defined for two
    applications. Left out it does not filter at all; given explicitly — including
    as `None` — it selects only messages carrying exactly that id.

    `section` narrows by the clause a definition was read from, which is what a
    name alone cannot do when the name itself is the error. TS 29.388 clause
    6.3.10 heads `PLMN-Allowed-PC5-RATs` and then prints 6.3.3's rule name, so
    two clauses claim one name and the correction that fixes it has to say
    which. A clause is also the stable way to point at a definition here: it is
    what the heading says and what `; Section:` records, and unlike the name it
    is not the thing under repair.
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
    """The file-level directive header — the `Specification` node itself.

    What a `bases` correction targets. The extractor stamps `; Bases:
    RFC6733` because that dependency is a fact about Diameter; a document
    that additionally builds on another application's AVPs without citing
    them anywhere — RFC 4072's command ABNFs use NASREQ's AVPs the way every
    ABNF uses `Session-Id` — states that nowhere the extractor can read, so
    the stamped default is corrected rather than a fabricated source line
    patched in.
    """

    def locate(self, spec: ast.Specification) -> _Located:
        """The specification itself, at the root path `()`."""
        yield (), spec

    def describe(self) -> str:
        return "file header"


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
class avp_table(Selector):
    """An AVP-table section, by its printed label."""

    label: str

    def locate(self, spec: ast.Specification) -> _Located:
        """Each AVP table carrying the label, at `("sections", i)`."""
        yield from (
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.AvpTable) and section.table == self.label
        )

    def describe(self) -> str:
        return f"AVP table {self.label!r}"


@dataclass(frozen=True)
class reused_avps(Selector):
    """A re-used AVPs section, by its printed label.

    What a re-used-row `Insert` targets: TS 29.337's table 6.3.1/2 lists
    every member its Serving-Node bodies use except six, and nothing but
    adding the rows can make those references resolve.
    """

    label: str

    def locate(self, spec: ast.Specification) -> _Located:
        """Each re-used block carrying the label, at `("sections", i)`."""
        yield from (
            (("sections", index), section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.ReusedAvps) and section.table == self.label
        )

    def describe(self) -> str:
        return f"re-used AVPs table {self.label!r}"


@dataclass(frozen=True)
class reused_row(Selector):
    """One row of a re-used AVPs table, by AVP name.

    `section` names the table's own clause when a document holds several
    re-used tables listing the same AVP — 29.212's Gx (5.4.0) and Sd (5b.4.0)
    tables both carry `3GPP-SGSN-Ipv6-Address`.
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
class enum_value(Selector):
    """One named value of an enumerated AVP.

    `value` disambiguates when one name labels several values — 29.214's
    Specific-Action prints "Void" at both 0 and 5, and a deletion has to name
    which one it dooms.
    """

    avp: str
    name: str
    value: int | None = None

    def locate(self, spec: ast.Specification) -> _Located:
        """Each matching value, at `("sections", i, "values", j)`."""
        for index, section in enumerate(spec.sections):
            if isinstance(section, ast.EnumeratedAvp) and section.name == self.avp:
                yield from (
                    (("sections", index, "values", position), value)
                    for position, value in enumerate(section.values)
                    if isinstance(value, ast.EnumValue)
                    and value.name == self.name
                    and (self.value is None or value.value == self.value)
                )

    def describe(self) -> str:
        return f"value {self.name!r} of {self.avp!r}" + self._value_suffix()

    def describe_in_place(self) -> str:
        # The note stands among the enum's own values, so the block already
        # names the AVP.
        return f"value {self.name!r}" + self._value_suffix()

    def _value_suffix(self) -> str:
        return "" if self.value is None else f" (= {self.value})"


@dataclass(frozen=True)
class avp_rule(Selector):
    """One AVP reference inside a message or grouped-AVP body.

    `parent` is a whole `definition` selector rather than a duplicated name, so
    a rule inside one of two same-named commands is reachable by the same
    discriminator that reaches the command itself. A bare string is shorthand
    for `definition(name)`.

    `occurrence` picks the n-th (from 1) rule of that name in one body, for
    the one case identity cannot narrow: a body printing the same rule twice.
    TS 29.229 clause 6.1.10 prints RTA's `< Session-Id >` on two consecutive
    lines, identical in every field. It matches only while the body still
    repeats the name, so the declaration fails once upstream drops the copy.
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
    """One field of one node, with the value it is expected to hold.

    `versions` is advisory, exactly as for input patches: it records where the
    correction is known to be needed and sharpens the message, and never gates
    whether the correction is applied. Gating would silently ship an
    uncorrected file the first time a version moved.
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
    """Remove one node — a table row, an enum value, an AVP rule — entirely.

    TS 29.283's re-used table cites `Feature-Id` from TS 29.229, which has no
    such AVP and never did, and no field replacement can make that row true.

    `expect` is the full node, checked field-for-field, not merely "the
    selector matched". A row that upstream has since changed may no longer
    deserve deletion, and a row upstream has removed makes the declaration
    stale; both fail loudly, which is the same contract `Correction.expect`
    carries for a single field.
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
    """Insert one table row the source omits: an AVP-table row the document
    defines but does not tabulate, or a re-used row for an AVP its ABNFs use
    without citing.

    `into` names which table, and the node's type must match it — an
    `AvpTableRow` into an `avp_table`, a `ReusedAvpRow` into `reused_avps`.
    `after` addresses an existing row by name, never position; `None` appends.
    The operation expects no row with the inserted node's name, so it fails
    the day upstream adds the missing row itself.

    A `reused_avps(label)` that matches no block, while an AVP table carries
    the same label, creates that table's re-used block right after it, with
    the table's clause and page — the block the extractor synthesises when a
    table's NOTEs name a defining RFC. TS 32.299 table 7.1.0.1 lists IETF
    AVPs without naming an origin per row, so its block exists only once
    the corrections supply the origins.
    """

    id: str
    into: avp_table | reused_avps
    node: ast.AvpTableRow | ast.ReusedAvpRow
    after: str | None
    reason: str
    versions: str | VersionRange = "*..*"
    origin: str = ""

    def __post_init__(self) -> None:
        _check_id(self.id)
        object.__setattr__(self, "versions", VersionRange.parse(self.versions))

    @property
    def cited(self) -> str:
        return _cited(self)


# What a corrections module may declare. `Supply` remains designed
# (docs/corrections.md) but deliberately unimplemented until a document forces
# its externally-defined-enum shape.
Edit = Correction | Delete | Insert


_ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def _check_id(value: object) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise CorrectionError(
            f"correction id {value!r} is not a lowercase kebab-case name"
        )


def _cited(edit: Edit) -> str:
    """How a `.dad` note refers to an edit: `TS29.272.py#area-scope-vendor`
    once loaded from a module, the bare id before that."""
    return f"{edit.origin}#{edit.id}" if edit.origin else edit.id


@dataclass
class Result:
    """What `apply()` did, one entry per edit, in declaration order."""

    correction: Edit
    node: str
    # For a `Correction`, the field's values; for a `Delete`, the removed node
    # and None; for an `Insert`, None and the new node.
    old: Any
    new: Any
    # Where the edited node sits *in the returned tree* — the new row for an
    # `Insert`; for a `Delete`, the position the node stood in, which the
    # sibling that moved up into it now holds (one past the end when the last
    # sibling went), since the node itself produces no lines — so a formatter
    # can mark what an edit reached. Set after the rebuild, because inserts
    # and deletions move what follows them: the path an edit was resolved by
    # belongs to the input tree.
    path: ast.TreePath = ()


def _holds_nodes(value: Any) -> bool:
    if isinstance(value, ast.Node):
        return True
    return isinstance(value, tuple) and any(
        isinstance(item, ast.Node) for item in value
    )


def _corrected(node: ast.Node, correction: Correction) -> ast.Node:
    """Rebuild one node with the field replaced, through validation.

    `model_copy(update=...)` would not validate the new value, so a correction
    could write a code of `"oops"` into a tree that only fails much later.
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


# Where a table row in the rebuild came from: its path in the tree being
# rebuilt, or the declaration index of the `Insert` that adds it.
type _Origin = ast.TreePath | int


def _inserted(
    parent: ast.Node,
    rows: list[tuple[_Origin, Any]] | None,
    insert: Insert,
    origin: int,
    path: ast.TreePath,
) -> list[tuple[_Origin, Any]]:
    """The rows of the table at `path` with the declared row inserted, each
    with its origin, checked by validating the table they make. `rows` holds
    what earlier inserts made of them, None before the first."""
    described = insert.into.describe()
    row_type = (
        ast.AvpTableRow if isinstance(insert.into, avp_table) else ast.ReusedAvpRow
    )
    if not isinstance(parent, ast.AvpTable | ast.ReusedAvps):
        raise CorrectionError(
            f"{described}: Insert requires a table, matched {type(parent).__name__}"
        )
    if not isinstance(insert.node, row_type):
        raise CorrectionError(
            f"{described}: the inserted node must be a {row_type.__name__},"
            f" not a {type(insert.node).__name__}"
        )
    if rows is None:
        rows = [((*path, "rows", index), row) for index, row in enumerate(parent.rows)]
    if any(row.name == insert.node.name for _, row in rows):
        raise CorrectionError(
            f"{described}: row {insert.node.name!r} is already present"
        )
    rows = list(rows)
    if insert.after is None:
        rows.append((origin, insert.node))
    else:
        positions = [
            index for index, (_, row) in enumerate(rows) if row.name == insert.after
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
    values["rows"] = tuple(row for _, row in rows)
    try:
        type(parent)(**values)
    except pydantic.ValidationError as error:
        raise CorrectionError(
            f"{described}: inserted row is not valid: {error.errors()[0]['msg']}"
        ) from None
    return rows


def _created_blocks(
    spec: ast.Specification, corrections: Sequence[Edit]
) -> tuple[ast.Specification, list[int], dict[str, ast.TreePath]]:
    """Place an empty re-used block after each AVP table whose label an
    `Insert` targets while no re-used block carries it (see `Insert`).

    Returns the tree to rebuild, with the placeholders in it; the index each
    input section has in that tree; and the placeholders' paths by label. A
    placeholder is built without validation, since a table may not be empty;
    the inserts targeting it fill it through the same `_inserted` as any
    other, and the rebuild validates the result. Selectors never see it: they
    resolve against the original tree.
    """
    labels = {
        edit.into.label
        for edit in corrections
        if isinstance(edit, Insert)
        and isinstance(edit.into, reused_avps)
        and not any(edit.into.find(spec))
    }
    created: dict[int, ast.ReusedAvps] = {}
    for label in labels:
        tables = [
            (index, section)
            for index, section in enumerate(spec.sections)
            if isinstance(section, ast.AvpTable) and section.table == label
        ]
        if len(tables) != 1:
            # Not a creation: `_resolve` reports the selector's no-match.
            continue
        index, table = tables[0]
        created[index] = ast.ReusedAvps.model_construct(
            table=label,
            source=table.source,
            columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
            rows=(),
        )
    positions: list[int] = []
    sections: list[ast.Section] = []
    placeholders: dict[str, ast.TreePath] = {}
    for index, section in enumerate(spec.sections):
        positions.append(len(sections))
        sections.append(section)
        if (placeholder := created.get(index)) is not None:
            placeholders[placeholder.table] = ("sections", len(sections))
            sections.append(placeholder)
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
    # plus "rows".
    rows: dict[ast.TreePath, list[tuple[_Origin, Any]]] = dataclasses.field(
        default_factory=dict
    )
    # Filled by the rebuild: where each node, by its path in the tree being
    # rebuilt or by its `Insert`, landed in the result.
    placed: dict[_Origin, ast.TreePath] = dataclasses.field(default_factory=dict)


def _rebuilt(node: Any, path: ast.TreePath, out: ast.TreePath, plan: _Plan) -> Any:
    """Rebuild the tree, swapping in corrected nodes, adding inserted rows and
    dropping deleted nodes, by path. `path` is where `node` sits in the tree
    being rebuilt and `out` where it lands in the result; the two differ once
    an insertion or deletion has moved a node's earlier siblings.

    A corrected replacement is descended into rather than returned whole: a
    correction to a message and a correction to one of its AVP rules are both
    legal, and stopping at the message would silently drop the second.
    Corrections never replace a field holding child nodes, so the
    replacement's children sit at the paths the original's did.

    The rebuild goes through validation for the same reason `_corrected` does:
    a correction that satisfies its own field's rules can still break a
    cross-field invariant of an ancestor, and that has to fail here rather than
    downstream. Deleting a table's last row fails the same way, on the table's
    own non-empty invariant.
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
            elif isinstance(origin, int):
                # An inserted row was validated when its edit was declared
                # and has no input to correct.
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
    spec: ast.Specification, corrections: Sequence[Edit]
) -> tuple[ast.Specification, list[Result]]:
    """Apply every edit, or none of them.

    Each edit is resolved and checked against the original tree before
    anything is rebuilt, so a failing one cannot leave a half-corrected
    file behind.
    """
    # Selectors and `expect` checks see only the input; the rebuild also
    # walks the re-used blocks `Insert`s create.
    tree, positions, placeholders = _created_blocks(spec, corrections)
    plan = _Plan()
    targets: dict[ast.TreePath, str] = {}  # path -> the selector that reached it
    claimed: set[tuple[ast.TreePath, str]] = set()
    results = []
    origins: list[_Origin] = []  # per result: what `plan.placed` knows it by
    for index, correction in enumerate(corrections):
        if (
            isinstance(correction, Insert)
            and isinstance(correction.into, reused_avps)
            and correction.into.label in placeholders
        ):
            path = placeholders[correction.into.label]
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
            and (path in plan.replaced or (*path, "rows") in plan.rows)
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
        if isinstance(correction, Insert):
            plan.rows[(*path, "rows")] = _inserted(
                plan.replaced.get(path, node),
                plan.rows.get((*path, "rows")),
                correction,
                index,
                path,
            )
            results.append(
                Result(
                    correction=correction,
                    node=f"{described}, row {correction.node.name!r}",
                    old=None,
                    new=correction.node,
                )
            )
            origins.append(index)
            continue
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
    for path, description in targets.items():
        if path not in plan.placed:
            raise CorrectionError(
                f"{description}: the selected node sits inside a subtree another"
                " edit deleted"
            )
    for result, origin in zip(results, origins, strict=True):
        if origin not in plan.placed:
            # Reporting success for a row the output does not hold would be
            # the silent loss the `expect` contract exists to prevent.
            raise CorrectionError(
                f"{result.node}: the inserted row is not in the corrected tree"
            )
        result.path = plan.placed[origin]
    return rebuilt, results


_SECTION_TYPES = (
    ast.Message,
    ast.GroupedAvp,
    ast.EnumeratedAvp,
    ast.AvpTable,
    ast.ReusedAvps,
)


type _NoteMap = dict[ast.TreePath, list[str]]


def notes(results: list[Result]) -> tuple[_NoteMap, _NoteMap, _NoteMap]:
    """`;;` note lines marking what `apply` touched, keyed by path in the
    rebuilt tree, as the `(trailing, standing, detached)` triple
    `format_spec` takes.

    A trailing note says only that an edit reached the line, and where the
    declaration is: the declaration carries the change and its `reason`, and
    the raw file carries the old value, so repeating either here would only
    lengthen every corrected file. A deleted node produces no line for a note
    to trail, so its note *stands* — printed in the deleted line's place,
    before the sibling that moved up into it — and names what is gone,
    because unlike a trailing note it has no line saying that for it.

    A deleted *section* gets a `detached` note instead: its place is between
    two sections, so gluing the note to the top of the following section
    would read as being about that section. The formatter prints detached
    notes as a block of their own, spaced like the section they replace.
    """
    trailing: _NoteMap = {}
    standing: _NoteMap = {}
    detached: _NoteMap = {}
    for result in results:
        edit = result.correction
        if isinstance(edit, Delete):
            bucket = detached if isinstance(result.old, _SECTION_TYPES) else standing
            bucket.setdefault(result.path, []).append(
                f"deleted: {edit.target.describe_in_place()} ({edit.cited})"
            )
            continue
        kind = "inserted" if isinstance(edit, Insert) else "corrected"
        trailing.setdefault(result.path, []).append(f"{kind}: ({edit.cited})")
    return trailing, standing, detached


def module_path(directory: Path, specification: str) -> Path:
    """The corrections module for `specification`, inside `directory`.

    Two independent boundaries, because loading this path executes its Python:
    `ast.spec_ref` accepts only canonical document references, so no cover-page
    title can spell a separator or a `..`; and the resolved candidate must sit
    directly in the resolved corrections directory, so neither a symlink nor a
    future spelling of the first rule can reach outside the directory the user
    named.
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
) -> list[Edit]:
    """Read `<directory>/<SpecRef>.py` and return its `CORRECTIONS` list.

    The file name is derived from the specification, so a corrections file
    cannot be applied to the wrong document. Importing it executes Python from
    `directory`, which is why the CLI requires the path to be given explicitly
    rather than discovering it.

    `required` distinguishes the two callers. Extraction over a corpus may pass
    a directory that holds modules for some of its specifications, so a missing
    module is an ordinary empty result. `seanchai correct` was asked for exactly
    one specification's corrections, so a missing or empty module there means a
    typo silently produced an uncorrected file, and it fails instead.
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
    if required and not corrections:
        raise CorrectionError(f"{path} declares no corrections")
    return corrections


def _corrections_of(path: Path) -> list[Edit]:
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
    if not all(isinstance(item, Correction | Delete | Insert) for item in corrections):
        raise CorrectionError(
            f"{path}: CORRECTIONS must hold Correction, Delete or Insert objects"
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
