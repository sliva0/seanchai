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

A module may also declare `Accept`s, which change nothing: each
acknowledges one linter finding on the corrected file as a deliberate
override its document states, so `seanchai lint --corpus` reports it apart
from the open findings. Applying a module skips them.

Beside field replacement there are three narrow structural operations:
`Delete` for a node that should not exist at all, `Insert` for an AVP-table row
the source defines but omits from the table (or a body member a verified
erratum restores, an enumerated value a later document adds, or the block
declaring a name the corpus finds defined nowhere), and
`Supply` for what a document defines in another: the value list of an
enumerated AVP, or the type and flag rules of a table row typed by
reference. All fail loudly when upstream changes
the state that justified them: `Delete` expects the doomed node
field-for-field, `Insert` expects the row to be absent, so it fails the day
upstream adds it, and `Supply` expects the clause's `; Values:` citation and
no values (or, extending a printed list, none of the supplied names and
numbers), or the blank row.
"""

import dataclasses
import importlib.util
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydantic

from ..errors import SeanchaiError
from ..versions import VersionRange, applies, reviewed_release
from . import ast, formatter


class CorrectionError(SeanchaiError, ValueError):
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
    """The flag rules of one AVP-table row, whose `must`, `may`,
    `should_not` and `must_not` a correction replaces one at a time.

    The rules are a node of their own, so the row's `flag_rules` field cannot
    be replaced whole. TS 29.273's three RAT-Type rows set M in Must where TS
    29.212, which the document defers to, sets it in Must not: moving one flag
    is two field corrections, each with its own `expect`.
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
    """A re-used AVPs section, by its printed label.

    What a re-used-row `Insert` targets: TS 29.337's table 6.3.1/2 lists
    every member its Serving-Node bodies use except six, and nothing but
    adding the rows can make those references resolve. `section` narrows by
    the block's clause, which tells apart blocks printing no label: RFC 5779's
    AVP table at clause 5.2 has none, nor do the blocks of origins its clauses'
    prose states.
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
class registry_row(Selector):
    """A registry's allocation, by the code space and the code: TS 29.230
    table 7.1's 402, which the registry names `NAF-Hostname` and TS 29.109
    clause 6.3.1.3 `NAF-Id`. A code a table allocates twice matches twice,
    which fails as any ambiguous selector does (table 7.1's 318)."""

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

    `value` disambiguates when one name labels several values, and a
    correction has to name which one it means.

    `occurrence` picks the n-th (from 1) of several matching values in one
    AVP, as `avp_rule`'s does, for a list printing the same value twice. It
    matches only while the value repeats.
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
    """A value table, by its AVP and clause, and for a features table its
    application and Feature-List-ID, which tell apart one AVP's tables in one
    clause: TS 29.272 clause 7.3.10.1 prints Feature-List-ID 1 and 2."""

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
    """One row of a value table, by name, and by number where one name is
    printed for two. `parent` is a whole `value_table` selector, or as a bare
    string the AVP's."""

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

    Into `header()` it inserts an `ApplicationScope`, for an application
    id the document states in a form the extractor does not read: RFC 4006
    assigns 4 in its IANA considerations. The block goes after the file's
    other application scopes, which lead the file, so `after` must be None;
    no other scope may carry its name.

    Into `header()` it also inserts an `UndefinedAvp`, declaring a name the
    document uses as a member that nothing in the corpus defines, its
    `reason` citing what was searched: RFC 4004's `MIP-HA-to-MN-SPI`. The
    block goes after the file's last section, after any inserted before it,
    so `after` must be None. Checked against the corrected tree, so that a
    member a correction renames is the name it declares: the file must
    hold no definition, table row, re-used row or other block of that
    name, and some message or grouped body in clause `source.section` must
    name it. Once upstream defines the name, the first fails.

    Into a `definition()`, a message or grouped AVP, it inserts an
    `AvpRule`, a member the body omits and a verified erratum restores:
    RFC 5777's erratum 2333 adds three to `Time-Of-Day-Condition`. `after`
    names the member it follows, as a row's does.

    Into an enumerated AVP's `definition()`, it inserts an `EnumValue` a
    later document adds to the list: RFC 8581 clause 7.2.1 defines
    `PEER_REPORT` for RFC 7683's `OC-Report-Type`, in a clause of its own
    that the defining file has no place for. `after` names the value it
    follows; it expects neither the name nor the number to be in the list.

    Into a `value_table()`, it inserts a `ValueRow` the document states where
    no reading finds it, as a row into a table.

    `drawn_from` says what the node's fields come from where that is not the
    block it goes into, as its note prints it: TS 29.061 V6.15.0's two
    sub-attributes go into table 10 "from clause 16.4.7", which lists them and
    which the table omits. A row inserted with none is the block's own.
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
    """Fill in what a document defines in another document, as a hand-notated
    statement citing that document's clause.

    Two forms. Into an enumerated AVP (`target=definition(name)`), the values
    its clause takes from elsewhere: the clause states its values' source in
    a `; Values:` line and prints none, as TS 32.299 clause 7.2.238 takes
    `Type-Number`'s from the OMNA WSP registry. `expect` is that line's text,
    and the section must hold no values, so the declaration fails both when
    upstream re-words the citation and when it starts printing the list
    itself. The `; Values:` line stays, since the document still says it.

    With `extend=True` the section must instead print some values, and the
    supplied ones follow them: RFC 4005 clause 4.4 prints NAS-Port-Type's
    values 0-25 as informational and cites the IANA registry, which has
    added 26-43 since. Every supplied name and number must be new to the
    list, so the declaration fails the day upstream prints one of them.

    Into an AVP-table row (`target=table_row(name, table=)`), the type and
    flag rules its cells leave blank because the document types the AVP by
    reference: TS 32.299 table 7.2.0.1 prints `refer [223]` for thirteen
    rows, OMA-DDS-Charging_Data's. `expect` is the whole row, as for a
    `Delete`, with no type and no flag rules where they are supplied, and
    the file must list the AVP as re-used, the citation that says where its
    definition lives; the re-used row stays. `data_type`, `flag_rules` or
    both are what the cited document states.

    Every supplied line is marked `;; supplied:`, because none of it is the
    document's own.
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
    """Acknowledge one linter finding on the corrected file as deliberate.

    Some findings are a document saying on purpose what another says
    otherwise: TS 29.336 clause 6.4.12 prints its own `Serving-Node` body
    for T4-triggering, with the combinations its interface allows, and the
    linter's `reused-body-differs` note is then no open question. An
    acceptance changes no data; `seanchai lint --corpus` reports the
    finding as `accepted` instead of as a note, and `reason` cites the
    clause that makes the override deliberate.

    `rule` names the linter rule, `target` the node the finding is about,
    by the selectors corrections use, and `expect` is the finding's message,
    exactly. All three must match one finding, a note, so an acceptance
    stops matching when its document changes what it says, and a stale one
    is an error (`linter.accept`).
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


def _checked_supply(
    spec: ast.Specification, node: ast.Node, supply: Supply
) -> ast.AvpTableRow | None:
    """What `Supply` fills must be an enumerated AVP that cites the expected
    source for its values and prints none of them, or the expected row of
    an AVP the file re-uses; for a row, the row filled in."""
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
    """What `Supply(extend=True)` appends must share no name and no number
    with what the section prints, reserved, void and vendor-specific ranges
    included."""
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
    """The rows of the table at `path`, or the members of the body, with the
    declared one inserted, each with its origin, checked by validating the
    node they make. `rows` holds what earlier inserts made of them, None
    before the first."""
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
    """The file's sections with the declared application scope placed after
    the last one already there, or the declared undefined AVP after the last
    section, each with its origin. `sections` holds what earlier inserts
    made of them, None before the first."""
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
    """What an inserted `UndefinedAvp` expects of the corrected file: no
    definition, table row, re-used row or second block of its name, and a
    message or grouped body in its clause naming it."""
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
    `Insert` targets while no re-used block carries it (see `Insert`).

    Returns the tree to rebuild, with the placeholders in it; the index each
    input section has in that tree, and past the last one the tree's end;
    and the placeholders' paths by the selector creating each. A
    placeholder is built without validation, since a table may not be empty;
    the inserts targeting it fill it through the same `_inserted` as any
    other, and the rebuild validates the result. Selectors never see it: they
    resolve against the original tree.
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
    """Apply every edit, or none of them; acceptances are skipped.

    Each edit is resolved and checked against the original tree before
    anything is rebuilt, so a failing one cannot leave a half-corrected
    file behind.
    """
    applied = _applied(spec, edits(corrections))
    return applied.rebuilt, applied.results


def edits(declarations: Sequence[Declaration]) -> list[Edit]:
    """The declarations that change data, in declaration order."""
    return [item for item in declarations if not isinstance(item, Accept)]


def in_release(
    declarations: Sequence[Declaration], version: str | None
) -> list[Declaration]:
    """The declarations that apply to `version`: those of its release
    (`versions.reviewed_release`), each range advisory within it. A module
    holding TS 32.299's Release 19 corrections says nothing about the
    Release 11 copy the corpus holds beside it."""
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
    """What `apply` did, with what `apply_with_comments` needs to follow
    lines from the input tree to the output: the tree the rebuild walked,
    where each input section sits in it, the plan, and per result the path
    `plan.placed` knows it by."""

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
    """`apply` for a tree with `;;` comments of its own, as
    `parser.parse_with_comments` returns them: the comments come back keyed
    by where their lines landed, merged with `notes(results)`.

    A comment moves with the line it attaches to, so one standing before a
    member stays before it when an insert or a deletion shifts the body;
    TS 32.299's commented-out struck members depend on it. A deleted line
    takes nothing with it: what stood before it, or trailed it, stands where
    it stood, before the deletion's note, and what stood after it stays
    after the note; inside a deleted section, it becomes a block of its own
    there. A directive line a correction removes (`; Bases:` emptied) has
    its comments go where the correction's note goes, to the block's first
    line, ahead of the note. Where a comment and a note trail one line, the
    comment comes first.
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
    """Where a comment keyed `path` in the input (in the coordinates of the
    tree the rebuild walked) lands in the output: its placement, path, and
    the input position it orders by among a deletion's notes."""
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
    """`;;` note lines marking what `apply` touched, keyed by path in the
    rebuilt tree, as the `formatter.Comments` `format_spec` takes.

    A trailing note says only that an edit reached the line, and where the
    declaration is: the declaration carries the change and its `reason`, and
    the raw file carries the old value, so repeating either here would only
    lengthen every corrected file. It trails the line the corrected field
    prints (`_cited_line`). A deleted node produces no line for a note
    to trail, so its note *stands* — printed in the deleted line's place,
    before the sibling that moved up into it — and names what is gone,
    because unlike a trailing note it has no line saying that for it.

    Each value a `Supply` adds trails a `supplied:` note, as an inserted
    row trails `inserted:`.

    A deleted *section* gets a `detached` note instead: its place is between
    two sections, so gluing the note to the top of the following section
    would read as being about that section. The formatter prints detached
    notes as a block of their own, spaced like the section they replace.
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
    """The path of the line a correction's note trails.

    A definition is cited on its header rule, the line that states it,
    whichever field was corrected. The file header, a table, an
    application scope and an undefined AVP have no such line: each field
    they let a correction replace prints on a directive line of its own
    (`; Bases:`, `; Table:`, `; Application-ID:`, `; Note:`), so the note
    trails that line.
    A correction that removes the field's line altogether — a `; Table:`
    caption or the `; Bases:` dropped — is cited on the block's first line,
    the one left that names the block.
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
) -> list[Declaration]:
    """Read `<directory>/<SpecRef>.py` and return its `CORRECTIONS` list,
    acceptances included.

    The file name is derived from the specification, so a corrections file
    cannot be applied to the wrong document. Importing it executes Python from
    `directory`, which is why the CLI requires the path to be given explicitly
    rather than discovering it.

    `required` distinguishes the two callers. Extraction over a corpus may pass
    a directory that holds modules for some of its specifications, so a missing
    module is an ordinary empty result. `seanchai corpus correct` was asked for exactly
    one specification's corrections, so a missing module, or one declaring no
    edit, means a typo silently produced an uncorrected file, and it fails
    instead.
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
