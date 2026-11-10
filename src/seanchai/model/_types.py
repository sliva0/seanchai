"""The model's value types: what a consumer holds once the corpus is
resolved, from `Avp` and `Hole` to `Message` and `Application`, the
undefined-name policies and answers, and the walks over a body's members.
Each is a frozen dataclass with `to_dict`; none resolves anything."""

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
    """`value` as JSON holds it: an enum its value, a set a sorted list, and a
    model or dataclass a dict of its fields."""
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
        """This object's fields as JSON holds them, sorted flags and nested
        objects included, for `json.dumps`."""
        return {
            each.name: _plain(getattr(self, each.name))
            for each in fields(cast("DataclassInstance", self))
        }


@dataclass(frozen=True)
class ValueTable(_Plain):
    """The numbers one document names for a numeric AVP: result codes, the bits
    of a bit mask, the features of a feature list (`ast.ValueKind`).

    `rows` are the document's, each a name and a number (`ast.ValueRow`): a
    result code's `section` where it has a clause of its own, a feature's `mark`
    the M/O column. `vendor_id` is the space an experimental result code or a
    vendor AVP's bit lives in, the file's; a plain Result-Code value is the
    IETF's whichever document prints it. `application` and `feature_list_id`
    say which list a feature table is, as its caption does."""

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

    Every field is a fact some document in the corpus states, or for an
    IETF-space AVP's unplaced M and V bits, RFC 6733's rule (`FlagRules`),
    or, where `supplied` is set, the consumer's; an AVP missing one is a
    `Hole` instead, never an `Avp` with a gap in it.
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
        """The first of `value_tables`, the only one but for a document printing
        several: one feature list per Feature-List-ID, or a code list per
        interface."""
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
    """An `Undefined AVP` block, resolved: the name, the document using it,
    the clause its block cites, what the document says of it, and every
    clause whose body names it, in file order."""

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
    """An undefined name kept in its place untyped, by the consumer's
    choice (`UndefinedPolicy.PLACEHOLDER`): no identity, type or flags, only
    what the block says."""

    undefined: Undefined

    @property
    def name(self) -> str:
        return self.undefined.name

    def __repr__(self) -> str:
        return f"<Placeholder {self.undefined.reference} {self.name}>"


@dataclass(frozen=True)
class Supplied(_Plain):
    """A definition the consumer supplies for an undefined name
    (`UndefinedPolicy.SUPPLY`). `source` is mandatory provenance: "ACME HSS
    4.2 dictionary", a sidecar path. `members` only for a Grouped AVP,
    resolved in the document using the name; `values` only for an
    Enumerated one."""

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
    """An undefined name read as an AVP the corpus does define: TS 29.154's
    `External-Group-Identifier` as TS 29.336's `External-Identifier`. The
    member resolves to `reference`'s `name`, unchanged, under its own name;
    `source` says on whose word."""

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
    """Which holes `Model.build` allows (docs/consumers.md#known-holes)."""

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

    `reference` is the document whose statement falls short: the one that
    defines or tabulates the AVP without stating every field, or, when the
    name resolves to nothing, the one that names it. Its code, type, vendor
    and flag rules, where stated, are kept for a consumer that takes partial
    data. A grouped AVP's members and an enumerated AVP's values are not; the
    AST (`table_rows`, `corpus.Entry.spec`) has those.
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
        """`reference`, with the version when it is an older copy's:
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
        """The fewest times the member may appear, by RFC 6733 §3.2's rules
        for a qualifier: an optional rule may always be absent, whatever its
        qualifier says, and a required rule's minimum defaults to one, so
        `* { X }` means one or more. `rule.min_occurs` keeps what the bracket
        and qualifier spell, which reads `[ X ]` as exactly once."""
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
        """The ranges the document leaves to vendors or operators, in body
        order: TS 32.299's SM-Service-Type 100-199, "Vendor specific SM
        services". A value in one is legal under a name the document does
        not give, so a consumer validating values allows it."""
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
        """Whether the header's R bit is set: the request of a command code,
        and not its answer."""
        return ast.CommandFlag.REQUEST in self.flags

    def walk(self) -> tuple[Member, ...]:
        """The members of this command at every depth, each reading once, in
        definition order: a grouped member comes before its own members.

        `Member.avp`, `hole` and `placeholder` mean what they do in `avps`,
        and the `* [ AVP ]` wildcard appears once. A body among its own
        descendants is not walked twice, and what the policy dropped stays in
        `dropped`. Two readings of one name are two entries: a grouped AVP
        read through another document may hold another reading of a member.
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
    """RFC 6733 section 7.2's `<answer-message>` as `defined_in` prints it, its
    body read through `read_through`: the format an answer with the E bit set
    takes in place of its command's, there being no other.

    A document printing none takes its `; Bases:` documents', so a TS 29.272
    error answer takes RFC 6733's, read through TS 29.272, whose reading is the
    one its commands hold; a TS 29.229 one takes clause 7.3.1's own, which adds
    `[ Supported-Applications ]`."""

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
    interface: what a protocol-specific consumer generates one unit from.

    The wire tells applications apart by the header's application id, but
    documents share one between interfaces (TS 29.273's SWa, STa and SWd
    all use 16777250) or print none in their headers (TS 29.212 defines its
    Gx, Gxx, Sd and St commands with bare `272, REQ, PXY` headers and states
    each id in prose), so the clause a command sits under is the other half
    of the key. A 3GPP document gives each interface its own top-level
    clause (29.212's 5, 5a, 5b, 5c) or annex clause (29.215's A.7 and A.8).
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
        """The members this application's commands reach at any depth, as
        `Message.walk` reads them, each reading once, in definition order.
        What a dictionary generator wants: unlike `Model.avps`, which is what
        a document's tables list, it holds what the commands take from
        documents the tables do not list."""
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
    """What a registry says of a code: a row allocating it, or a range
    reserving it, with the registry table it sits in.

    TS 29.230 allocates rather than defines, so this is evidence beside the
    model, never a reading of it: an AVP is what its defining document says,
    and the linter's `registry-*` rules report where the two differ.
    """

    reference: str  # "TS29.230"
    table: str  # "7.1"
    section: str
    entry: ast.RegistryRow | ast.RegistryReservation

    def __repr__(self) -> str:
        return f"<Allocation {self.reference} table {self.table}: {self.entry!r}>"


@dataclass(frozen=True)
class Marks(_Plain):
    """What one table row marks about where its AVP applies: per mark
    column its table prints, the row's marks in the document's spelling,
    `()` where the cell prints a dash and None where it is blank.

    The labels mean what their legends say (`ast.MarkColumn`): TS 29.212's
    `Acc-Type` names IP-CAN access types and its `Applicability` functions
    and supported features, neither of them an interface, since each
    interface clause has tables of its own; TS 32.299's `ACR` to `CCA` say
    whether the AVP is used in that command, `()` for the dash clause 7.1.0
    reads as "not used". A blank cell states nothing: TS 32.299 leaves
    four, and a feature column is blank for a row of the base functionality.
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
    """Whether a member is a body among its own descendants, which `_body`
    stops at: no reading, no hole and no placeholder, and not the
    wildcard."""
    return (
        member.avp is None
        and member.hole is None
        and member.placeholder is None
        and member.name != "AVP"
    )


def _walk(
    members: tuple[Member, ...], seen: set[tuple[str, object]]
) -> Iterator[Member]:
    """`members` and those of their grouped AVPs, depth first, passing over
    what `seen` holds. A member keeps its own name in the key: an `Alias` reads
    two names as one AVP, and each is still a member."""
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
