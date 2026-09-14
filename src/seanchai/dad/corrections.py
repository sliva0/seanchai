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


@dataclass(frozen=True)
class Selector:
    """Base for the ways a correction names its target. Subclasses yield the
    nodes they match, in document order, from a whole specification.

    The subclasses are deliberately lower-case: a corrections file is data, and
    `table_row("MME-Location-Information")` reads as such where
    `TableRow(...)` would read as machinery.
    """

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        raise NotImplementedError

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

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
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
            yield section

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

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        yield spec

    def describe(self) -> str:
        return "file header"


@dataclass(frozen=True)
class table_row(Selector):
    """One row of an AVP table, by AVP name and optionally table label."""

    name: str
    table: str | None = None

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if isinstance(section, ast.AvpTable) and (
                self.table is None or section.table == self.table
            ):
                yield from (row for row in section.rows if row.name == self.name)

    def describe(self) -> str:
        suffix = f" (table {self.table})" if self.table is not None else ""
        return f"AVP table row {self.name!r}{suffix}"


@dataclass(frozen=True)
class avp_table(Selector):
    """An AVP-table section, by its printed label."""

    label: str

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        yield from (
            section
            for section in spec.sections
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

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        yield from (
            section
            for section in spec.sections
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

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if isinstance(section, ast.ReusedAvps) and (
                self.section is None or section.source.section == self.section
            ):
                yield from (row for row in section.rows if row.name == self.name)

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

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if isinstance(section, ast.EnumeratedAvp) and section.name == self.avp:
                yield from (
                    value
                    for value in section.values
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
    """

    parent: str | definition
    name: str

    @property
    def _parent(self) -> definition:
        if isinstance(self.parent, str):
            return definition(self.parent)
        return self.parent

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in self._parent.find(spec):
            # An enumerated AVP matches `definition` but has no ABNF body.
            if isinstance(section, ast.Message | ast.GroupedAvp):
                yield from (rule for rule in section.avps if rule.name == self.name)

    def describe(self) -> str:
        return f"AVP rule {self.name!r} in {self._parent.describe()}"


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
    # Identity of the edited node *in the returned tree* — the new node for an
    # `Insert`; for a `Delete`, the sibling that now stands where the node
    # stood (or the parent, when the last sibling went), since the node
    # itself produces no lines — so a formatter can mark what an edit reached.
    # Set after the rebuild, because rebuilding constructs new objects: the
    # identity an edit was resolved by belongs to the input tree and is gone.
    node_id: int = 0


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


def _resolve(spec: ast.Specification, edit: Edit) -> ast.Node:
    target = edit.into if isinstance(edit, Insert) else edit.target
    found = list(target.find(spec))
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


def _inserted(parent: ast.Node, insert: Insert) -> ast.Node:
    """Return the table with the declared row inserted and validated."""
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
    if any(row.name == insert.node.name for row in parent.rows):
        raise CorrectionError(
            f"{described}: row {insert.node.name!r} is already present"
        )
    rows = list(parent.rows)
    if insert.after is None:
        rows.append(insert.node)
    else:
        positions = [
            index for index, row in enumerate(rows) if row.name == insert.after
        ]
        if not positions:
            raise CorrectionError(
                f"{described}: after row {insert.after!r} is not present"
            )
        if len(positions) > 1:
            raise CorrectionError(
                f"{described}: after row {insert.after!r} is ambiguous"
            )
        rows.insert(positions[0] + 1, insert.node)
    values = {name: getattr(parent, name) for name in type(parent).model_fields}
    values["rows"] = tuple(rows)
    try:
        return type(parent)(**values)
    except pydantic.ValidationError as error:
        raise CorrectionError(
            f"{described}: inserted row is not valid: {error.errors()[0]['msg']}"
        ) from None


def _replaced(
    node: Any,
    edits: dict[int, ast.Node],
    deletions: set[int],
    tracked: set[int],
    applied: dict[int, int],
    rebuilt: dict[int, int],
) -> Any:
    """Rebuild the tree, swapping in corrected parents (including those
    extended by `Insert`) and dropping deleted nodes, by identity.

    A chosen replacement is descended into rather than returned whole: a
    correction to a message and a correction to one of its AVP rules are both
    legal, and stopping at the message would silently drop the second. Because
    `_corrected` rebuilds through pydantic, which keeps already-valid submodels
    as they are, the replacement's children still carry the identities the
    remaining edits are keyed by.

    The rebuild goes through validation for the same reason `_corrected` does:
    a correction that satisfies its own field's rules can still break a
    cross-field invariant of an ancestor, and that has to fail here rather than
    downstream. Deleting a table's last row fails the same way, on the table's
    own non-empty invariant.
    """
    if isinstance(node, ast.Node):
        original_id = id(node)
        replacement = edits.get(original_id)
        if replacement is not None:
            applied[original_id] = applied.get(original_id, 0) + 1
            node = replacement
        deleted_here: list[tuple[int, str, int]] = []  # id, field, position kept
        values = {}
        for name in type(node).model_fields:
            value = getattr(node, name)
            if isinstance(value, tuple):
                kept = []
                for item in value:
                    if isinstance(item, ast.Node) and id(item) in deletions:
                        applied[id(item)] = applied.get(id(item), 0) + 1
                        deleted_here.append((id(item), name, len(kept)))
                        continue
                    kept.append(
                        _replaced(item, edits, deletions, tracked, applied, rebuilt)
                    )
                values[name] = tuple(kept)
            else:
                values[name] = _replaced(
                    value, edits, deletions, tracked, applied, rebuilt
                )
        try:
            result = type(node)(**values)
        except pydantic.ValidationError as error:
            raise CorrectionError(
                f"corrected {type(node).__name__} is not valid:"
                f" {error.errors()[0]['msg']}"
            ) from None
        if replacement is not None or original_id in tracked:
            rebuilt[original_id] = id(result)
        # A deleted node produces no lines, so what a formatter can mark is
        # the sibling that now stands where it stood — the note then prints
        # in the deleted line's place. Only a node deleted from the end of
        # its tuple has no follower, and falls back to the parent. The
        # follower is looked up in `values`, not in `result`: pydantic keeps
        # already-valid submodels as they are, so both hold the same object.
        for deleted_id, field, position in deleted_here:
            siblings = values[field]
            if position < len(siblings) and isinstance(siblings[position], ast.Node):
                rebuilt[deleted_id] = id(siblings[position])
            else:
                rebuilt[deleted_id] = id(result)
        return result
    if isinstance(node, tuple):
        return tuple(
            _replaced(item, edits, deletions, tracked, applied, rebuilt)
            for item in node
        )
    return node


def apply(
    spec: ast.Specification, corrections: Sequence[Edit]
) -> tuple[ast.Specification, list[Result]]:
    """Apply every edit, or none of them.

    Each edit is resolved and checked against the original tree before
    anything is rebuilt, so a failing one cannot leave a half-corrected
    file behind.
    """
    edits: dict[int, ast.Node] = {}
    deletions: set[int] = set()
    targets: dict[int, str] = {}  # node id -> the selector that reached it
    claimed: set[tuple[int, str]] = set()
    tracked: set[int] = set()  # newly inserted nodes whose rebuilt ids we need
    results = []
    resolved_ids = []  # per result: the id its node had in the input tree
    for correction in corrections:
        node = _resolve(spec, correction)
        target = (
            correction.into if isinstance(correction, Insert) else correction.target
        )
        described = target.describe()
        if isinstance(correction, Delete) and id(node) in deletions:
            raise CorrectionError(f"{described}: deleted more than once")
        if id(node) in deletions or (
            isinstance(correction, Delete) and id(node) in edits
        ):
            raise CorrectionError(
                f"{described}: the node is both corrected and deleted;"
                " a deleted node has no fields worth fixing"
            )
        targets[id(node)] = described
        if isinstance(correction, Delete):
            _checked_deletion(node, correction)
            deletions.add(id(node))
            results.append(
                Result(correction=correction, node=described, old=node, new=None)
            )
            resolved_ids.append(id(node))
            continue
        if isinstance(correction, Insert):
            inserted = _inserted(edits.get(id(node), node), correction)
            edits[id(node)] = inserted
            tracked.add(id(correction.node))
            results.append(
                Result(
                    correction=correction,
                    node=f"{described}, row {correction.node.name!r}",
                    old=None,
                    new=correction.node,
                )
            )
            resolved_ids.append(id(correction.node))
            continue
        claim = (id(node), correction.field)
        if claim in claimed:
            raise CorrectionError(
                f"{described}: {correction.field} is corrected"
                " more than once; combine the corrections"
            )
        claimed.add(claim)
        # Chain onto an earlier correction of the same node, so two fields of
        # one row can be corrected independently.
        corrected = _corrected(edits.get(id(node), node), correction)
        results.append(
            Result(
                correction=correction,
                node=described,
                old=getattr(node, correction.field),
                new=correction.replace,
            )
        )
        resolved_ids.append(id(node))
        edits[id(node)] = corrected
    applied: dict[int, int] = {}
    rebuilt_ids: dict[int, int] = {}
    rebuilt = _replaced(spec, edits, deletions, tracked, applied, rebuilt_ids)
    # Identity is what maps a resolved node back to its place in the tree, so a
    # node object appearing in two places would be corrected in both while the
    # selector reported one match. Trees from `parse` and the extractor build
    # every node separately; a caller that shares one gets told, not surprised.
    for node_id, description in targets.items():
        count = applied.get(node_id, 0)
        if count > 1:
            raise CorrectionError(
                f"{description}: the selected node appears more than once in the"
                " tree; corrections address one place, not a shared object"
            )
        if count == 0:
            raise CorrectionError(
                f"{description}: the selected node sits inside a subtree another"
                " edit deleted"
            )
    for result, resolved_id in zip(results, resolved_ids, strict=True):
        result.node_id = rebuilt_ids.get(resolved_id, 0)
    return rebuilt, results


_SECTION_TYPES = (
    ast.Message,
    ast.GroupedAvp,
    ast.EnumeratedAvp,
    ast.AvpTable,
    ast.ReusedAvps,
)


def notes(
    results: list[Result],
) -> tuple[dict[int, list[str]], dict[int, list[str]], dict[int, list[str]]]:
    """`;;` note lines marking what `apply` touched, keyed by node id in the
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
    trailing: dict[int, list[str]] = {}
    standing: dict[int, list[str]] = {}
    detached: dict[int, list[str]] = {}
    for result in results:
        edit = result.correction
        if isinstance(edit, Delete):
            bucket = detached if isinstance(result.old, _SECTION_TYPES) else standing
            bucket.setdefault(result.node_id, []).append(
                f"deleted: {edit.target.describe_in_place()} ({edit.cited})"
            )
            continue
        kind = "inserted" if isinstance(edit, Insert) else "corrected"
        trailing.setdefault(result.node_id, []).append(f"{kind}: ({edit.cited})")
    return trailing, standing, detached


def _module_path(directory: Path, specification: str) -> Path:
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
    path = _module_path(directory, specification)
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
