"""The model's value types, from `Avp` and `Hole` to `Message` and
`Application`, plus the undefined-name policies and member walks. Each is a
frozen dataclass with `to_dict`; none resolves anything."""

from __future__ import annotations

import enum
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from typing import TYPE_CHECKING, Any, cast

import pydantic

from .. import corpus
from ..corpus import Missing
from ..dad import ast
from ._flags import FlagRules

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def _plain(value: Any) -> Any:
    """`value` as JSON: an enum as its value, a set as a sorted list, a model
    or dataclass as a dict of its fields."""
    if isinstance(value, _Plain | FlagRules):
        return value.to_dict()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, set | frozenset):
        return sorted(_plain(each) for each in value)
    if isinstance(value, list | tuple):
        return [_plain(each) for each in value]
    if isinstance(value, Mapping):
        return {str(_plain(key)): _plain(each) for key, each in value.items()}
    if isinstance(value, pydantic.BaseModel):
        return {name: _plain(getattr(value, name)) for name in type(value).model_fields}
    if is_dataclass(value):
        return {each.name: _plain(getattr(value, each.name)) for each in fields(value)}
    if value is None or isinstance(value, str | int | float):
        return value
    return str(value)


class _Plain:
    """What the model's dataclasses share: `to_dict`."""

    def to_dict(self) -> dict[str, Any]:
        """This object's fields as JSON-ready values, for `json.dumps`."""
        return {
            each.name: _plain(getattr(self, each.name))
            for each in fields(cast("DataclassInstance", self))
        }


@dataclass(frozen=True)
class ValueTable(_Plain):
    """The named numbers one document gives a numeric AVP: result codes, bit
    mask bits or feature-list features (`ast.ValueKind`).

    `rows` are `ast.ValueRow`s. `vendor_id` is the file's vendor, except that
    plain Result-Code values are always IETF. `application` and
    `feature_list_id` identify a feature table's list, as its caption does."""

    kind: ast.ValueKind
    avp: str
    reference: str
    version: str | None
    vendor_id: int
    section: str
    page: int | None
    table: str | None
    application: str | None
    feature_list_id: int | None
    rows: tuple[ast.ValueRow, ...]

    def __repr__(self) -> str:
        which = f" {self.application}" if self.application else ""
        if self.feature_list_id is not None:
            which += f" list {self.feature_list_id}"
        return (
            f"<ValueTable {self.avp} {self.kind}{which} in {self.reference},"
            f" {len(self.rows)} rows>"
        )


def _value_table(entry: corpus.Entry, table: ast.ValueTable) -> ValueTable:
    return ValueTable(
        kind=table.kind,
        avp=table.avp,
        reference=entry.reference,
        version=entry.spec.version,
        vendor_id=ast.IETF_VENDOR
        if table.avp == "Result-Code"
        else entry.spec.vendor_id,
        section=table.source.section,
        page=table.source.page,
        table=table.table,
        application=table.application,
        feature_list_id=table.feature_list_id,
        rows=table.rows,
    )


@dataclass(frozen=True)
class Avp(_Plain):
    """One resolved AVP, as the specification `defined_in` states it.

    Every field is stated by some corpus document, by RFC 6733's default
    for unplaced IETF bits (`FlagRules`), or by the consumer when `supplied`
    is set. An AVP missing a field is a `Hole`, never an `Avp`.
    """

    name: str
    vendor_id: int
    code: int
    data_type: ast.DataType
    flag_rules: FlagRules
    # The reference re-used rows cite: `TS29.229`, `RFC6733`.
    defined_in: str
    section: str | None
    # Wireshark's dictionary name for `(vendor-id, code)`, when the model is
    # built with one and it says: `Call-Barring-Infor-List` for TS 29.272's
    # `Call-Barring-Info`. Extra information beside `name`, never instead.
    wireshark_name: str | None
    # Set when a reading this AVP took a field from was reached through a
    # citation outside the citing document's release, with the rule that
    # allowed it: TS 32.299's `VAS-ID` is TS 29.140 V7.0.0's, the final
    # version its non-specific reference means (docs/consumers.md).
    across_releases: corpus.CrossRelease | None = None
    # Set for a definition the consumer supplied for a name an `Undefined
    # AVP` block declares (`UndefinedPolicy.SUPPLY`): where it came from,
    # "ACME HSS dictionary (acme.dad)". `defined_in` and `section` are then
    # the block's, the document using the name.
    supplied: str | None = None
    # The fields `defined_in`'s reading leaves unstated, each with the
    # document that states it instead: TS 29.229's clause 6.3.43 gives
    # `Wildcarded-IMPU` no code, vendor or flags, so through TS 29.329 they
    # are its table 6.3.1's. Provenance only: two readings stating the same
    # facts are one AVP.
    completed_by: tuple[tuple[Missing, str], ...] = field(default=(), compare=False)
    # The document whose table produced this reading, spelled as
    # `Hole.document` for an older copy: `defined_in`, unless a table elsewhere
    # changed the flag rules or a grouped member. TS 29.229 reads RFC 6733's
    # `Session-Id` as RFC 6733 does, so that reading names RFC 6733; oneM2M
    # TS-0004's table adds P under May, so its reading names it. Provenance
    # only, as `completed_by`: two documents giving one reading are one AVP,
    # which names the first in corpus order.
    read_through: str = field(default="", compare=False)
    # What the reading document names this AVP's numbers, its own tables, or
    # failing any the origin's: TS 29.272's `ULR-Flags` bits, the features of
    # each of a `Feature-List`'s lists. Not a fact of the AVP's: every document
    # numbering its result codes reads RFC 6733's `Experimental-Result-Code`,
    # one AVP.
    value_tables: tuple[ValueTable, ...] = field(default=(), compare=False)

    @property
    def identity(self) -> tuple[int, int]:
        """`(vendor-id, code)`, the pair that distinguishes AVPs on the wire."""
        return (self.vendor_id, self.code)

    @property
    def value_table(self) -> ValueTable | None:
        """The first of `value_tables`, or None."""
        return self.value_tables[0] if self.value_tables else None

    def _repr_tail(self) -> str:
        return ""

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} {self.name} {self.identity} {self.data_type}"
            f" in {self.defined_in}{self._repr_tail()}>"
        )


@dataclass(frozen=True)
class Undefined(_Plain):
    """A resolved `Undefined AVP` block: the name, the document using it,
    the cited clause, the document's note, and the clauses whose bodies name
    it."""

    reference: str
    name: str
    section: str
    page: int | None
    note: str | None
    cited_in: tuple[str, ...]
    # As `Hole.version`, for a block in an older copy.
    version: str | None = None

    def __repr__(self) -> str:
        return f"<Undefined {self.reference} {self.name}, clause {self.section}>"


@dataclass(frozen=True)
class Placeholder(_Plain):
    """An undefined name kept untyped in its body
    (`UndefinedPolicy.PLACEHOLDER`)."""

    undefined: Undefined

    @property
    def name(self) -> str:
        return self.undefined.name

    def __repr__(self) -> str:
        return f"<Placeholder {self.undefined.reference} {self.name}>"


@dataclass(frozen=True)
class Supplied(_Plain):
    """A consumer's definition for an undefined name
    (`UndefinedPolicy.SUPPLY`). `source` names where it came from.
    `members` are for a Grouped AVP and resolve in the document using the
    name; `values` are for an Enumerated one."""

    vendor_id: int
    code: int
    data_type: ast.DataType
    flag_rules: ast.AvpFlagRules
    source: str
    members: tuple[ast.AvpRule, ...] = ()
    values: tuple[ast.EnumEntry, ...] = ()

    def __repr__(self) -> str:
        identity = (self.vendor_id, self.code)
        return f"<Supplied {identity} {self.data_type} from {self.source!r}>"


@dataclass(frozen=True)
class Alias(_Plain):
    """Reads an undefined name as `reference`'s AVP `name`, which the corpus
    defines. The member keeps its own name; `source` says on whose word."""

    reference: str
    name: str
    source: str

    def __repr__(self) -> str:
        return f"<Alias {self.reference} {self.name} from {self.source!r}>"


class UndefinedPolicy(enum.StrEnum):
    """What the model makes of a name an `Undefined AVP` block declares."""

    # A `Hole` missing `UNDEFINED`, as any name the corpus cannot complete.
    HOLE = "hole"
    # The member leaves its body; `Grouped.dropped` and `Message.dropped`
    # keep it, with its hole.
    DROP = "drop"
    # The member stays in place, `Member.placeholder` set, no `Avp`.
    PLACEHOLDER = "placeholder"
    # The definition the consumer supplied, or the AVP an `Alias` names;
    # a name it supplies nothing for stays a hole.
    SUPPLY = "supply"


class HolePolicy(enum.StrEnum):
    """Which holes `Model.build` allows (docs/consumers.md)."""

    # Those the corpus's record of known holes lists, and only while every
    # entry still names one: an unlisted hole raises `IncompleteCorpusError`,
    # an entry naming none `StaleHoleRecordError`.
    RECORDED = "recorded"
    # No hole at all, recorded or not: every member is an `Avp`, the
    # wildcard, or what `undefined` asked for.
    NONE = "none"
    # Any hole; the record is not read. For a partial or foreign corpus.
    ANY = "any"


type SupplyKey = str | tuple[str, str]


@dataclass(frozen=True)
class Hole(_Plain):
    """A name the corpus cannot turn into a complete `Avp`.

    `reference` is the document that falls short: the one defining or
    tabulating the AVP incompletely, or the one naming a name that resolves
    nowhere. Stated code, type, vendor and flag rules are kept; members and
    values are not (read them from the AST).
    """

    reference: str
    name: str
    # `Missing.CODE`, `DATA_TYPE`, `FLAG_RULES`, or `DEFINITION` or
    # `UNDEFINED` alone.
    missing: tuple[Missing, ...]
    vendor_id: int | None = None
    code: int | None = None
    data_type: ast.DataType | None = None
    flag_rules: FlagRules | None = None
    section: str | None = None
    # The re-used origin the corpus holds no copy of, when one is cited:
    # RFC 6736's `Egress-VLANID` from RFC 4675.
    origin: str | None = None
    # The document whose reading states a missing field but disagrees with
    # this one on a field both state, so nothing was taken from it or from
    # any reading after it.
    conflict: str | None = None
    wireshark_name: str | None = None
    # As `Avp.across_releases`, for a reading that still falls short.
    across_releases: corpus.CrossRelease | None = None
    # The version of `reference` falling short, when that is an older copy
    # the corpus holds for a citation (TS 32.299 V11.20.0, which oneM2M
    # TS-0004 cites), not the one reference-level queries answer from.
    version: str | None = None
    # The block declaring the name, for a hole missing `UNDEFINED`.
    undefined: Undefined | None = None
    # Why the hole stands, from the entry of the corpus's record of known
    # holes that lists it; None for a hole no entry lists as it is.
    recorded: str | None = None

    def __str__(self) -> str:
        if self.undefined is not None:
            return f"{self.document} {self.name}: undefined (clause {self.section})"
        if self.missing == (Missing.DEFINITION,):
            what = "resolves nowhere"
        else:
            what = "no " + ", no ".join(self.missing)
        if self.origin is not None:
            what += f" (re-used from {self.origin}, which the corpus lacks)"
        if self.conflict is not None:
            what += f"; {self.conflict}'s reading, which states it, disagrees"
        return f"{self.document} {self.name}: {what}"

    def __repr__(self) -> str:
        return f"<Hole {self}>"

    @property
    def document(self) -> str:
        """`reference`, plus the version for an older copy:
        "TS32.299 V11.20.0"."""
        return self.reference + ("" if self.version is None else f" V{self.version}")


@dataclass(frozen=True)
class Member(_Plain):
    """One line of an ABNF body, with the name resolved to an object."""

    rule: ast.AvpRule
    # None for the `* [ AVP ]` wildcard, for a name the corpus cannot
    # complete, and for an undefined name kept as a placeholder; `hole` or
    # `placeholder` says which.
    avp: Avp | None
    hole: Hole | None = None
    placeholder: Placeholder | None = None
    # The `Alias` `avp` was read through, for an undefined name the
    # consumer reads as another AVP: `avp.name` is then the alias's.
    alias: Alias | None = None

    @property
    def name(self) -> str:
        return self.rule.name

    @property
    def min_occurs(self) -> int:
        """The fewest times the member may appear, per RFC 6733 section 3.2:
        0 for an optional rule, at least 1 for a required one. Unlike
        `rule.min_occurs`, which keeps what the brackets spell."""
        if self.rule.presence is ast.Presence.OPTIONAL:
            return 0
        if self.rule.presence is ast.Presence.REQUIRED:
            return max(self.rule.min_occurs, 1)
        return self.rule.min_occurs

    @property
    def max_occurs(self) -> int | None:
        """The most times the member may appear; None is unbounded."""
        return self.rule.max_occurs

    def to_dict(self) -> dict[str, Any]:
        """As `_Plain.to_dict`, with the occurrences as RFC 6733 reads them."""
        return {
            "name": self.name,
            "min_occurs": self.min_occurs,
            "max_occurs": self.max_occurs,
            **super().to_dict(),
        }

    def __repr__(self) -> str:
        most = "*" if self.max_occurs is None else self.max_occurs
        if self.avp is not None:
            what = str(self.avp.identity)
        elif self.hole is not None:
            what = "hole"
        elif self.placeholder is not None:
            what = "placeholder"
        else:
            what = "wildcard" if self.name == "AVP" else "cut"
        return (
            f"<Member {self.name} {self.rule.presence}"
            f" {self.min_occurs}..{most}: {what}>"
        )


@dataclass(frozen=True, repr=False)
class Grouped(Avp):
    members: tuple[Member, ...] = ()
    # The undefined members `UndefinedPolicy.DROP` took out of `members`,
    # each with its hole and rule, so what the ABNF requires stays readable.
    dropped: tuple[Member, ...] = ()

    def _repr_tail(self) -> str:
        return f", {len(self.members)} members"


@dataclass(frozen=True, repr=False)
class Enumerated(Avp):
    values: tuple[ast.EnumEntry, ...] = ()
    # Where the defining clause says the values are defined instead, in its
    # words: TS 29.272's `Trace-Depth` takes "TS 32.422 [23] for Trace
    # Depth". With no values beside it that is the whole statement, not a
    # gap: the document defines the AVP and points elsewhere for the list.
    values_source: str | None = None

    @property
    def vendor_specific(self) -> tuple[ast.VendorSpecificValues, ...]:
        """The value ranges the document leaves to vendors or operators, in
        body order. A validator should accept values in them."""
        return tuple(
            value
            for value in self.values
            if isinstance(value, ast.VendorSpecificValues)
        )

    def to_dict(self) -> dict[str, Any]:
        """As `_Plain.to_dict`, each value saying which kind of line it is."""
        kinds: dict[type, str] = {
            ast.EnumValue: "value",
            ast.ReservedValues: "reserved",
            ast.VoidValues: "void",
            ast.VendorSpecificValues: "vendor-specific",
        }
        return {
            **super().to_dict(),
            "values": [
                {"kind": kinds[type(value)], **_plain(value)} for value in self.values
            ],
        }

    def _repr_tail(self) -> str:
        return f", {len(self.values)} values"


@dataclass(frozen=True)
class Message(_Plain):
    """One command, its header numbers and its body resolved."""

    name: str
    abbreviation: str
    command_code: int
    flags: frozenset[ast.CommandFlag]
    # The id on the wire: the header's, or for a header printing none, the one
    # an application scope covering the command's clause states (TS 29.212's
    # bare `272, REQ, PXY` CCR, 16777238 from clause 5.1). None when neither
    # says.
    application_id: int | None
    defined_in: str
    section: str
    avps: tuple[Member, ...]
    # As `Grouped.dropped`.
    dropped: tuple[Member, ...] = ()
    # The id the header prints, None where it prints none.
    header_application_id: int | None = None

    @property
    def is_request(self) -> bool:
        """Whether the header's R bit is set."""
        return ast.CommandFlag.REQUEST in self.flags

    def walk(self) -> tuple[Member, ...]:
        """The command's members at every depth, each reading once, a grouped
        member before its own members.

        The `* [ AVP ]` wildcard appears once, a recursive body is not walked
        twice, and dropped members stay in `dropped`. Two readings of one
        name are two entries.
        """
        return tuple(_walk(self.avps, set()))

    def to_dict(self) -> dict[str, Any]:
        """As `_Plain.to_dict`, with `is_request`."""
        return {**super().to_dict(), "is_request": self.is_request}

    def __repr__(self) -> str:
        flags = ",".join(sorted(self.flags))
        return (
            f"<Message {self.defined_in} {self.abbreviation} {self.command_code}"
            f" {flags or '-'} application {self.application_id},"
            f" {len(self.avps)} members>"
        )


@dataclass(frozen=True)
class AnswerMessage(_Plain):
    """RFC 6733 section 7.2's `<answer-message>`, the body of any answer with
    the E bit set, as `defined_in` prints it and read through
    `read_through`. A document printing none takes its `; Bases:`
    documents'."""

    defined_in: str
    section: str
    read_through: str
    avps: tuple[Member, ...]
    # As `Grouped.dropped`.
    dropped: tuple[Member, ...] = ()

    def walk(self) -> tuple[Member, ...]:
        """The members at every depth, as `Message.walk` reads them."""
        return tuple(_walk(self.avps, set()))

    def __repr__(self) -> str:
        return (
            f"<AnswerMessage {self.defined_in} {self.section} through"
            f" {self.read_through}, {len(self.avps)} members>"
        )


@dataclass(frozen=True)
class Application(_Plain):
    """The commands one document defines for one application on one
    interface.

    Documents share an application id across interfaces or print none, so
    an application is identified by its id and clause. Each interface has
    its own top-level or annex clause.
    """

    reference: str
    # The header's id, or for commands whose headers print none, the id an
    # application scope covering them states; None when neither says.
    application_id: int | None
    # "5a", or "A.7" for an annex: the leading clause component, with the
    # next one for an annex, whose letter alone spans several interfaces.
    clause: str
    messages: tuple[Message, ...]
    # The application scope that states `application_id`, when one does:
    # its name for the application ("Gx") and the clause stating the id.
    name: str | None = None
    stated_in: str | None = None

    def walk(self) -> tuple[Member, ...]:
        """The members the application's commands reach at any depth, as
        `Message.walk` reads them. Unlike `Model.avps`, this includes AVPs
        the document's tables do not list."""
        seen: set[tuple[str, object]] = set()
        return tuple(
            member for message in self.messages for member in _walk(message.avps, seen)
        )

    def __repr__(self) -> str:
        named = "" if self.name is None else f" {self.name}"
        return (
            f"<Application {self.reference} {self.application_id}{named}, clause"
            f" {self.clause}, {len(self.messages)} messages>"
        )


@dataclass(frozen=True)
class Allocation(_Plain):
    """A registry row allocating a code, or a range reserving it, with its
    table.

    This is evidence beside the model and never changes an AVP's reading;
    the linter's `registry-*` rules report disagreements.
    """

    reference: str  # "TS29.230"
    table: str  # "7.1"
    section: str
    entry: ast.RegistryRow | ast.RegistryReservation

    def __repr__(self) -> str:
        return f"<Allocation {self.reference} table {self.table}: {self.entry!r}>"


@dataclass(frozen=True)
class Marks(_Plain):
    """One table row's marks of where its AVP applies, per mark column, in
    the document's spelling: `()` for a dash, None for a blank cell.

    Each column means what its table's legend says (`ast.MarkColumn`). A
    blank cell states nothing.
    """

    # The table's label and the clause it sits in: "5a.4.0.1" and "5a.4.0".
    table: str | None
    section: str
    marks: dict[ast.MarkColumn, tuple[str, ...] | None]

    def __repr__(self) -> str:
        return f"<Marks table {self.table}, clause {self.section}: {self.marks}>"


def _identity(member: Member) -> tuple[int, int] | None:
    """The `(vendor-id, code)` a member's reading states, or None where it
    states no code or is the wildcard."""
    found = member.avp or member.hole
    if found is None or found.vendor_id is None or found.code is None:
        return None
    return (found.vendor_id, found.code)


def is_cut(member: Member) -> bool:
    """Whether a member is where `_body` cut a recursive body: no reading,
    hole or placeholder, and not the wildcard."""
    return (
        member.avp is None
        and member.hole is None
        and member.placeholder is None
        and member.name != "AVP"
    )


def _walk(
    members: tuple[Member, ...], seen: set[tuple[str, object]]
) -> Iterator[Member]:
    """`members` and their grouped AVPs' members, depth first, skipping what
    `seen` holds. The key includes the member's name, so two aliased names
    of one AVP are both yielded."""
    for member in members:
        if is_cut(member):
            continue
        key = (member.name, member.avp or member.hole or member.placeholder)
        if key in seen:
            continue
        seen.add(key)
        yield member
        if isinstance(member.avp, Grouped):
            yield from _walk(member.avp.members, seen)
