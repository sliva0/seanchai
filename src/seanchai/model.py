"""The consumer model: the corpus resolved into objects a consumer can use.

The `.dad` AST mirrors a file one-to-one and is allowed to contradict itself;
this layer is the opposite. It is built once from a `corpus.Corpus` and hands
a consumer what a generator or validator actually wants: a message whose ABNF
entries point at real AVP objects rather than names, a grouped AVP that can
enumerate its members, an AVP that knows its `(vendor-id, code)` identity, its
type and its flag rules. The AST stays public underneath for anything this
model does not cover.

Where the AST keeps two disagreeing statements, this layer has to pick one,
and the policy is deliberately small:

- A name resolves, in order, to the specification's own definition, then to
  the origin a re-used row cites (read recursively in the origin's own
  context, so an indirect citation still lands on the real definition), then
  to an AVP-table row, then to a `; Bases:` document. A local definition
  winning over the re-used listing is what makes an *extension* (TS 29.272
  re-defines nine of RFC 6733's AVPs with extra members) mean what the
  extending document says; a plain re-print resolves to the origin's copy,
  which is also the copy the linter checks.
- A re-used name's flag rules are the citing document's where its own AVP
  table states them (RFC 6733 sections 4.1 and 4.5 leave them to the
  application): through TS 29.229, RFC 4590's `Digest-Qop` is M in Must, as
  table 6.3.0.1 says, and through RFC 4590 M in May. The origin supplies the
  rest, each flag the row places in no column included, and its own reading
  is untouched. The re-used table's M-bit cell ranks between the two: TS
  29.272's `RAT-Type`, `MUST` there, is M in Must, where TS 29.212 forbids
  it. The linter's `reused-row-mismatch` reports the disagreement between
  table row and origin and says which side this follows.
- A grouped AVP defined elsewhere keeps its defining document's body, but
  each member the citing document defines, tabulates or re-uses is read
  through the citing document, by the rules above, where that reading is
  the same `(vendor-id, code)`; one it says nothing of, or reads as another
  AVP, stays the origin's reading. TS 32.299's `Supported-Features` holds
  TS 32.299's `Feature-List`, M in Must, where TS 29.229's holds M in Must
  not; its `M2M-Information` holds oneM2M's `Originator`, not its own.
- A citation means the copy the drafting rules on references say
  (`corpus.Corpus.resolution`): the newest in the citing document's
  release, the version a specific reference names, or the final version of
  a document that ended before the citing release, or a 3GPP2 revision or
  later release's copy a table entry lets stand in for the one cited
  (`corpus.STAND_INS`, `corpus.RELEASE_STAND_INS`). An AVP
  reached outside the citing document's release, or revision, says so in
  `across_releases`; an older
  copy answers only through such a citation, never a reference-level query.
- The linter, not this module, is where the conflicts live: anything
  `reused-body-differs` or `table-definition-mismatch` would report is
  resolved here by the order above without comment. Run the linter to see
  what the policy papered over.
- An AVP-table row with no matching definition and no re-used listing is
  in the vendor its Vendor-ID cell states where its table prints one (oneM2M
  TS-0004), else IETF-space (vendor 0) where its V flag is Must-not and the
  file's own `; Vendor-ID:` space otherwise, exactly as the linter's
  `duplicate-identity` rule reads it (`AvpTableRow.stated_vendor`); a
  definition written with no vendor-id is IETF-space, the wire format's
  reading of an absent vendor.
- A name tabulated in more than one of a file's AVP tables takes its table
  facts (flag rules; type and code when nothing defines it) from the first
  row in file order. `Model.table_rows` returns all of them, for the
  documents whose per-interface tables disagree.
- A field the first reading in that order leaves unstated is taken from the
  next reading, as long as every field both state agrees (a table row whose
  V flag states no vendor infers it from its file, and agrees with any): a
  re-print tabulated
  nowhere takes its origin's flag rules. A disagreeing reading fills
  nothing and is named in the hole instead.
- An IETF-space AVP whose readings leave the M or V bit unplaced takes
  RFC 6733's rule for it (`FlagRules`): V is Must-not (section 4.1.1), and
  M is the using application's to set (section 4.1), which no document
  along the order did.

An `Avp` has every field; a name the corpus cannot complete is a `Hole`
instead, whether a field is unstated everywhere along the order or the name
resolves nowhere at all. `Model.build` refuses any hole the corpus's record
of known holes does not list (`corpus.HoleRecord`), and any entry naming a
hole that no longer exists; `strict=True` refuses recorded holes too, and
`strict=False` builds anything. `Model.holes` lists them and `Member.avp` is
`None` with `Member.hole` saying why. `Member.avp` is also `None`, with no
hole, for RFC 6733's `* [ AVP ]` wildcard, which is grammar rather than a
reference.

A name an `Undefined AVP` block declares is the last reading along the
order, after the bases: it explains the failure and defines nothing, so a
definition that appears upstream or in a base wins without it. By default
it is a `Hole` missing `UNDEFINED`; `Model.build(..., undefined=...)` takes
the consumer's answer instead (`UndefinedPolicy`): drop the member, keep it
as an untyped `Placeholder`, or read a definition the consumer `Supplied`
(or an `Alias` for an AVP the corpus does define). Only a block's name is
open to that choice: a name resolving nowhere without one, and a field no
reading states, stay holes under every policy.
"""

from __future__ import annotations

import enum
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path

import pydantic

from . import corpus, oracle
from .dad import ast, parser
from .errors import SeanchaiError


class ModelError(SeanchaiError, ValueError):
    pass


class IncompleteCorpusError(ModelError):
    """A build over a corpus with holes it refuses: every hole under
    `strict=True`, and by default those its record does not list. `holes`
    lists every one."""

    def __init__(self, holes: tuple[Hole, ...], *, unrecorded: bool = False) -> None:
        self.holes = holes
        listing = "".join(f"\n  {hole}" for hole in holes)
        # Only an undefined name is the consumer's to answer for.
        answer = (
            ", and undefined=... answers for the undefined names"
            if any(hole.undefined is not None for hole in holes)
            else ""
        )
        count = f"{len(holes)} hole{'' if len(holes) == 1 else 's'}"
        what = f"{count} its record does not list" if unrecorded else count
        super().__init__(
            f"the corpus has {what}"
            f" (Model.build(..., strict=False) builds the rest{answer}):"
            f"{listing}"
        )


class StaleHoleRecordError(ModelError):
    """A record of known holes listing what no longer is one, so that working
    a hole off shrinks the record; `entries` lists every stale one."""

    def __init__(self, entries: tuple[corpus.KnownHole, ...]) -> None:
        self.entries = entries
        listing = "".join(f"\n  {_known(entry)}" for entry in entries)
        count = f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}"
        super().__init__(
            f"the corpus's record of known holes has {count} naming no hole, which"
            f" belong{'s' if len(entries) == 1 else ''} out of it:{listing}"
        )


def _known(entry: corpus.KnownHole) -> str:
    return f"{entry.document} {entry.name}: missing {', '.join(entry.missing)}"


class FlagRules(ast.AvpFlagRules):
    """Flag rules holding the one setting no table cell prints: a bit RFC
    6733 leaves to whichever application uses the AVP.

    RFC 6733 section 4.1: "The 'M' bit MUST be set according to the rules
    defined in the application specification that introduces or reuses this
    AVP", and RFC 7423 section 4.4.1 has a re-using application "specify
    the setting of the M-bit". An IETF AVP whose defining RFC states no M
    rule (RFC 4072, 5447, 5777 and 6734 print no flag columns) therefore has
    none of its own, by rule rather than by omission, and Must or May would
    each be a guess. Its V bit is no guess: section 4.1.1 forbids a Vendor-ID
    of zero, so an IETF-space AVP carries none and its V bit is Must-not.

    Every `Avp.flag_rules` and `Hole.flag_rules` is one of these, so a consumer
    reads one type. `application_defined` is set only on vendor 0's
    (`_ietf_rules`); everywhere else it is empty and the columns are the
    document's as printed.
    """

    application_defined: frozenset[ast.AvpFlag] = frozenset()

    @classmethod
    def printed(cls, rules: ast.AvpFlagRules) -> FlagRules:
        """A table's four columns as the model's type; rules already of it are
        returned as they are."""
        if isinstance(rules, cls):
            return rules
        return cls(
            must=rules.must,
            may=rules.may,
            should_not=rules.should_not,
            must_not=rules.must_not,
        )

    @pydantic.field_serializer("application_defined", when_used="json")
    def _application_defined_in_cell_order(
        self, flags: frozenset[ast.AvpFlag]
    ) -> list[ast.AvpFlag]:
        """As `AvpFlagRules`' columns."""
        return [flag for flag in ast.AvpFlag if flag in flags]

    @pydantic.model_validator(mode="after")
    def _defined_once(self) -> FlagRules:
        placed = self.must | self.may | self.should_not | self.must_not
        if overlap := placed & self.application_defined:
            raise ValueError(
                f"AVP flag {min(overlap).value!r} is both placed and"
                " application-defined"
            )
        return self


def _reached_across(avp: Avp | Hole) -> Iterator[Avp | Hole]:
    """The members, at any depth, of a grouped AVP reached across releases
    that took a field from a document resolved across releases in turn."""
    pending = [avp]
    seen: set[int] = set()
    while pending:
        each = pending.pop()
        if id(each) in seen or not isinstance(each, Grouped):
            continue
        seen.add(id(each))
        for member in each.members:
            found = member.avp or member.hole
            if found is None:
                continue
            if found.across_releases is not None:
                yield found
            pending.append(found)


def _by_citing_document(found: Avp | Hole) -> tuple[str, str]:
    across = found.across_releases
    return ("" if across is None else across.citing, found.name)


def _ietf_rules(flag_rules: ast.AvpFlagRules | None) -> FlagRules:
    """An IETF-space AVP's flag rules with RFC 6733's rule for each of M and
    V that no reading places: V under Must-not (section 4.1.1), M
    application-defined (section 4.1). Rules placing both are returned as
    they are; so are a document's own rules for the P bit, which RFC 6733
    reserves. RFC 7683 and 8583 place V only, and say in prose that "the
    M-bit usage for a given AVP in a given command may be defined by the
    application"."""
    rules = ast.AvpFlagRules() if flag_rules is None else flag_rules
    placed = rules.must | rules.may | rules.should_not | rules.must_not
    if {ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR} <= placed:
        return FlagRules.printed(rules)
    return FlagRules(
        must=rules.must,
        may=rules.may,
        should_not=rules.should_not,
        must_not=rules.must_not | ({ast.AvpFlag.VENDOR} - placed),
        application_defined=frozenset({ast.AvpFlag.MANDATORY}) - placed,
    )


@dataclass(frozen=True)
class Avp:
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
    completed_by: tuple[tuple[str, str], ...] = field(default=(), compare=False)

    @property
    def identity(self) -> tuple[int, int]:
        """`(vendor-id, code)`, the pair that distinguishes AVPs on the wire."""
        return (self.vendor_id, self.code)


def supplied_from(*paths: Path) -> dict[str, Supplied]:
    """The definitions hand-authored `.dad` sidecars supply, by name, for
    `Model.build(..., undefined=UndefinedPolicy.SUPPLY, supply=...)`.

    A sidecar is an ordinary `.dad` file, the format's hand-authored
    input, but no corpus document: nothing cites it, and only its own
    statements count, so each entry must be complete in its file. Every
    `Grouped AVP` and `Enumerated AVP` section and every AVP-table row is
    one `Supplied`: a definition's code and vendor from its header rule (no
    vendor-id is IETF space), its flag rules from the table row of its
    name; a row alone gives code, type and flag rules, its vendor read as
    `AvpTableRow.stated_vendor` reads it. The source is the file's `;
    Specification:` and name. A missing field, a row contradicting its
    definition or its own V flag, and a name given twice, defined or tabled
    twice in one sidecar or supplied by two, raise `ModelError`.
    """
    found: dict[str, Supplied] = {}
    for path in paths:
        spec = parser.parse(path.read_text(encoding="utf-8"))
        source = f"{spec.specification} ({path.name})"
        defined: dict[str, ast.GroupedAvp | ast.EnumeratedAvp] = {}
        rows: dict[str, ast.AvpTableRow] = {}
        for section in spec.sections:
            if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
                if section.name in defined:
                    raise ModelError(f"{path}: {section.name} is defined twice")
                defined[section.name] = section
            elif isinstance(section, ast.AvpTable):
                for row in section.rows:
                    if row.name in rows:
                        raise ModelError(f"{path}: {row.name} is tabled twice")
                    rows[row.name] = row
        for name in dict.fromkeys((*defined, *rows)):
            if name in found:
                raise ModelError(f"{path}: {name} is supplied twice")
            found[name] = _supplied(
                spec, source, name, defined.get(name), rows.get(name)
            )
    return found


def _supplied(
    spec: ast.Specification,
    source: str,
    name: str,
    definition: ast.GroupedAvp | ast.EnumeratedAvp | None,
    row: ast.AvpTableRow | None,
) -> Supplied:
    if row is None or not _stated(row.flag_rules):
        raise ModelError(f"{source}: {name} states no flag rules")
    stated = row.stated_vendor(spec.vendor_id)
    if definition is None:
        if row.code is None or row.data_type is None:
            raise ModelError(f"{source}: {name} states no code or no type")
        vendor_id = spec.vendor_id if stated is None else stated
        _refuse_conflicts(source, name, _flag_conflict(row, vendor_id))
        return Supplied(
            vendor_id=vendor_id,
            code=row.code,
            data_type=row.data_type,
            flag_rules=row.flag_rules,
            source=source,
        )
    grouped = isinstance(definition, ast.GroupedAvp)
    data_type = ast.DataType.GROUPED if grouped else ast.DataType.ENUMERATED
    vendor_id = (
        ast.IETF_VENDOR if definition.vendor_id is None else definition.vendor_id
    )
    printed_type = row.data_type or row.printed_type
    conflicts = []
    if row.code is not None and row.code != definition.code:
        conflicts.append(f"row gives code {row.code}, definition {definition.code}")
    if printed_type is not None and printed_type != data_type:
        conflicts.append(f"row gives type {printed_type}, definition {data_type}")
    if stated is not None and stated != vendor_id:
        conflicts.append(f"row gives vendor {stated}, definition {vendor_id}")
    conflicts += _flag_conflict(row, vendor_id if stated is None else stated)
    _refuse_conflicts(source, name, conflicts)
    return Supplied(
        vendor_id=vendor_id,
        code=definition.code,
        data_type=data_type,
        flag_rules=row.flag_rules,
        source=source,
        members=definition.avps if isinstance(definition, ast.GroupedAvp) else (),
        values=definition.values if isinstance(definition, ast.EnumeratedAvp) else (),
    )


def _flag_conflict(row: ast.AvpTableRow, vendor_id: int) -> list[str]:
    """How `row`'s V flag contradicts the vendor it is read in: RFC 6733
    section 4.1.1, as `AvpTableRow.vendor_flag_conflict` reads it."""
    conflict = row.model_copy(update={"vendor_id": vendor_id}).vendor_flag_conflict()
    return [] if conflict is None else [f"row gives {conflict}"]


def _refuse_conflicts(source: str, name: str, conflicts: list[str]) -> None:
    if conflicts:
        raise ModelError(f"{source}: {name}: {'; '.join(conflicts)}")


# `Avp` field names, as `Hole.missing` and `Avp.completed_by` spell them.
VENDOR_ID = "vendor_id"
CODE = "code"
DATA_TYPE = "data_type"
FLAG_RULES = "flag_rules"
# A name nothing in the corpus defines, tabulates or can be followed to.
DEFINITION = "definition"
# A name an `Undefined AVP` block declares defined nowhere.
UNDEFINED = "undefined"
# Marks a resolution stack entry as an `Alias` being followed, beside the
# `(path, name)` entries of the names being resolved.
_ALIASED = object()


@dataclass(frozen=True)
class Undefined:
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


@dataclass(frozen=True)
class Placeholder:
    """An undefined name kept in its place untyped, by the consumer's
    choice (`UndefinedPolicy.PLACEHOLDER`): no identity, type or flags, only
    what the block says."""

    undefined: Undefined

    @property
    def name(self) -> str:
        return self.undefined.name


@dataclass(frozen=True)
class Supplied:
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


@dataclass(frozen=True)
class Alias:
    """An undefined name read as an AVP the corpus does define: TS 29.154's
    `External-Group-Identifier` as TS 29.336's `External-Identifier`. The
    member resolves to `reference`'s `name`, unchanged, under its own name;
    `source` says on whose word."""

    reference: str
    name: str
    source: str


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


type SupplyKey = str | tuple[str, str]


@dataclass(frozen=True)
class Hole:
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
    # `CODE`, `DATA_TYPE`, `FLAG_RULES`, or `DEFINITION` or `UNDEFINED`
    # alone.
    missing: tuple[str, ...]
    vendor_id: int | None = None
    code: int | None = None
    data_type: ast.DataType | None = None
    flag_rules: FlagRules | None = None
    section: str | None = None
    # The re-used origin the corpus holds no copy of, when one is cited:
    # TS 32.299 V11.20.0's `DCD-Information` from OMA-DDS-Charging_Data.
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
        if self.missing == (DEFINITION,):
            what = "resolves nowhere"
        else:
            what = "no " + ", no ".join(self.missing)
        if self.origin is not None:
            what += f" (re-used from {self.origin}, which the corpus lacks)"
        if self.conflict is not None:
            what += f"; {self.conflict}'s reading, which states it, disagrees"
        return f"{self.document} {self.name}: {what}"

    @property
    def document(self) -> str:
        """`reference`, with the version when it is an older copy's:
        "TS32.299 V11.20.0"."""
        return self.reference + ("" if self.version is None else f" V{self.version}")


@dataclass(frozen=True)
class Member:
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


@dataclass(frozen=True)
class Grouped(Avp):
    members: tuple[Member, ...] = ()
    # The undefined members `UndefinedPolicy.DROP` took out of `members`,
    # each with its hole and rule, so what the ABNF requires stays readable.
    dropped: tuple[Member, ...] = ()


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class Message:
    """One command, its header numbers and its body resolved."""

    name: str
    abbreviation: str
    command_code: int
    flags: frozenset[ast.CommandFlag]
    application_id: int | None
    defined_in: str
    section: str
    avps: tuple[Member, ...]
    # As `Grouped.dropped`.
    dropped: tuple[Member, ...] = ()


@dataclass(frozen=True)
class Application:
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


@dataclass(frozen=True)
class Allocation:
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


@dataclass(frozen=True)
class Marks:
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


def _stated(flag_rules: ast.AvpFlagRules) -> bool:
    """Whether a row's flag cells say anything. A table with no flag columns
    (RFC 4072, 5447, 5777 and 6734 print none) and a row with every
    flag cell blank (TS 32.299 table 7.2.0.1 for most re-printed rows) both
    parse to empty rules, and neither is a claim that no flag applies."""
    return bool(
        flag_rules.must
        or flag_rules.may
        or flag_rules.should_not
        or flag_rules.must_not
    )


def _overlay(
    own: ast.AvpFlagRules, theirs: ast.AvpFlagRules | None
) -> ast.AvpFlagRules:
    """`own`'s placements, with each flag `own` places in no column placed
    where `theirs` places it: TS 29.229's `Digest-Qop` row puts M in Must
    and V in Must not, and RFC 4590's stand-in rules add P under May."""
    if theirs is None:
        return own
    placed = own.must | own.may | own.should_not | own.must_not
    return ast.AvpFlagRules(
        must=own.must | (theirs.must - placed),
        may=own.may | (theirs.may - placed),
        should_not=own.should_not | (theirs.should_not - placed),
        must_not=own.must_not | (theirs.must_not - placed),
    )


def _identity(member: Member) -> tuple[int, int] | None:
    """The `(vendor-id, code)` a member's reading states, or None where it
    states no code or is the wildcard."""
    found = member.avp or member.hole
    if found is None or found.vendor_id is None or found.code is None:
        return None
    return (found.vendor_id, found.code)


def _cut(member: Member) -> bool:
    """Whether a member is a body among its own descendants, which `_body`
    stops at: no reading, no hole and no placeholder, and not the
    wildcard."""
    return (
        member.avp is None
        and member.hole is None
        and member.placeholder is None
        and member.name != "AVP"
    )


@dataclass
class _Draft:
    """One reading of a name while resolution assembles it: `Avp`'s fields,
    any of them possibly unknown, until `final` turns it into an `Avp` or a
    `Hole`."""

    # Avp, Grouped or Enumerated; None when nothing defines the name, and the
    # draft carries only the unreadable `origin` that would have.
    kind: type[Avp] | None
    name: str
    reference: str
    # `reference`'s version when the reading is an older copy's, which a
    # hole names (`Hole.version`).
    version: str | None = None
    vendor_id: int | None = None
    # False for a table row whose V flag states no vendor space, so that the
    # vendor is the file's `; Vendor-ID:` rather than anything the row says.
    vendor_stated: bool = False
    code: int | None = None
    data_type: ast.DataType | None = None
    flag_rules: ast.AvpFlagRules | None = None
    section: str | None = None
    origin: str | None = None
    conflict: str | None = None
    wireshark_name: str | None = None
    across: corpus.CrossRelease | None = None
    members: tuple[Member, ...] = ()
    dropped: tuple[Member, ...] = ()
    values: tuple[ast.EnumEntry, ...] = ()
    values_source: str | None = None
    # The block declaring the name, on a draft of kind None that only
    # explains the failure.
    undefined: Undefined | None = None
    supplied: str | None = None
    completed_by: tuple[tuple[str, str], ...] = ()

    def stating(self, name: str) -> str:
        """The document stating this reading's field `name`."""
        return dict(self.completed_by).get(name, self.reference)

    def fill(self, other: _Draft) -> _Draft:
        """This reading with what it leaves unstated taken from `other`, the
        next document along the resolution order, when the two are the same
        AVP saying the same thing.

        Every field both readings state must be equal: code, type, flag
        rules, and vendor where both state one. A table row states its
        vendor through its V flag (`AvpTableRow.stated_vendor`); one whose
        V flag says neither is inferred from its file, and agrees with any:
        TS 29.229's row for RFC 4590's `Digest-Realm` sits in vendor 10415's
        file, the origin's row in vendor 0's. A reading that disagrees fills
        nothing, and neither does any after it; the hole names it instead, since taking
        a `Time` row's missing flags from an `Unsigned32` reading would make
        one complete AVP out of two documents that disagree about it.
        """
        if self.kind is None:
            # Nothing here yet: any definition wins, and failing one, the
            # first unreadable origin stays the explanation, then the block
            # declaring the name undefined.
            return other if other.kind is not None or self.origin is None else self
        if other.kind is None or self.conflict is not None:
            return self
        pairs = [
            (self.code, other.code),
            (self.data_type, other.data_type),
            (self.flag_rules, other.flag_rules),
        ]
        if not any(mine is None and theirs is not None for mine, theirs in pairs):
            return self
        if self.vendor_stated and other.vendor_stated:
            pairs.append((self.vendor_id, other.vendor_id))
        if any(
            mine is not None and theirs is not None and mine != theirs
            for mine, theirs in pairs
        ):
            return replace(self, conflict=other.reference)
        kind, members, dropped = self.kind, self.members, self.dropped
        values, values_source = self.values, self.values_source
        if self.data_type is None and other.kind is not Avp:
            # A row printing no type, for an AVP another document defines
            # as grouped or enumerated, takes the definition's body too.
            kind, members, dropped = other.kind, other.members, other.dropped
            values, values_source = other.values, other.values_source
        completed = dict(self.completed_by)
        for each in (CODE, DATA_TYPE, FLAG_RULES):
            if getattr(self, each) is None and getattr(other, each) is not None:
                completed[each] = other.stating(each)
        vendor_id, vendor_stated = self.vendor_id, self.vendor_stated
        if not vendor_stated and other.vendor_stated:
            vendor_id, vendor_stated = other.vendor_id, True
            completed[VENDOR_ID] = other.stating(VENDOR_ID)
        return replace(
            self,
            across=self.across or other.across,
            completed_by=tuple(completed.items()),
            kind=kind,
            members=members,
            dropped=dropped,
            values=values,
            values_source=values_source,
            vendor_id=vendor_id,
            vendor_stated=vendor_stated,
            code=other.code if self.code is None else self.code,
            data_type=other.data_type if self.data_type is None else self.data_type,
            flag_rules=(
                other.flag_rules if self.flag_rules is None else self.flag_rules
            ),
        )

    @property
    def complete(self) -> bool:
        """Whether this reading states every field itself, so that no later
        reading has anything to fill. RFC 6733's rule for an IETF AVP's
        unplaced bits is no statement: TS 29.273's row setting M for RFC
        5777's `QoS-Capability` still fills the origin's reading."""
        return self.kind is not None and None not in (
            self.vendor_id,
            self.code,
            self.data_type,
            self.flag_rules,
        )

    @cached_property
    def final(self) -> Avp | Hole:
        flag_rules = (
            None if self.flag_rules is None else FlagRules.printed(self.flag_rules)
        )
        if self.kind is not None and self.vendor_id == ast.IETF_VENDOR:
            flag_rules = _ietf_rules(self.flag_rules)
        if (
            self.kind is None
            or self.vendor_id is None
            or self.code is None
            or self.data_type is None
            or flag_rules is None
        ):
            missing = (
                ((DEFINITION,) if self.undefined is None else (UNDEFINED,))
                if self.kind is None
                else tuple(
                    name
                    for name, value in (
                        (CODE, self.code),
                        (DATA_TYPE, self.data_type),
                        (FLAG_RULES, flag_rules),
                    )
                    if value is None
                )
            )
            return Hole(
                reference=self.reference,
                name=self.name,
                missing=missing,
                vendor_id=self.vendor_id,
                code=self.code,
                data_type=self.data_type,
                flag_rules=flag_rules,
                section=self.section,
                origin=self.origin,
                conflict=self.conflict,
                wireshark_name=self.wireshark_name,
                across_releases=self.across,
                version=self.version,
                undefined=self.undefined if self.kind is None else None,
            )
        common = (
            self.name,
            self.vendor_id,
            self.code,
            self.data_type,
            flag_rules,
            self.reference,
            self.section,
            self.wireshark_name,
        )
        if self.kind is Grouped:
            return Grouped(
                *common,
                across_releases=self.across,
                supplied=self.supplied,
                completed_by=self.completed_by,
                members=self.members,
                dropped=self.dropped,
            )
        if self.kind is Enumerated:
            return Enumerated(
                *common,
                across_releases=self.across,
                supplied=self.supplied,
                completed_by=self.completed_by,
                values=self.values,
                values_source=self.values_source,
            )
        return Avp(
            *common,
            across_releases=self.across,
            supplied=self.supplied,
            completed_by=self.completed_by,
        )


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
        return view

    def cited_in(self, name: str) -> tuple[str, ...]:
        """The clauses whose message or grouped bodies name `name`, in file
        order."""
        return tuple(
            dict.fromkeys(
                section.source.section
                for section in self.entry.spec.sections
                if isinstance(section, ast.Message | ast.GroupedAvp)
                and any(rule.name == name for rule in section.avps)
            )
        )


class Model:
    """The resolved corpus. Build it once with `Model.build`."""

    def __init__(
        self,
        books: corpus.Corpus,
        dictionary: oracle.Oracle | None = None,
        undefined: UndefinedPolicy = UndefinedPolicy.HOLE,
        supply: Mapping[SupplyKey, Supplied | Alias] | None = None,
    ) -> None:
        self._books = books
        self._dictionary = dictionary
        self._policy = UndefinedPolicy(undefined)
        self._supply: dict[SupplyKey, Supplied | Alias] = dict(supply or {})
        self._known: dict[tuple[str, str], corpus.KnownHole] = {
            (entry.document, entry.name): entry
            for entry in (() if books.record is None else books.record.holes)
        }
        # Supplied readings, by the copy declaring the name, built once.
        self._supplied: dict[tuple[Path, str], Avp] = {}
        # One view per copy, and per reference the newest, which every
        # reference-level query answers from: the corpus sorts candidates
        # newest first. An older copy (TS 32.299 V11.20.0) is read only
        # where a citation resolves to it (`corpus.Corpus.resolution`).
        self._copies: dict[Path, _View] = {
            entry.path: _View.index(entry) for entry in books
        }
        self._views: dict[str, _View] = {
            entry.reference: self._copies[entry.path] for entry in books.newest()
        }
        # Memo of resolved readings, keyed by the copy that reads the name.
        self._resolved: dict[tuple[Path, str], _Draft | None] = {}
        # The identity each reading still being resolved has settled, which
        # `_through` compares a cut member against: a key is resolved once,
        # so an entry is read only while its key is on the stack.
        self._settled: dict[tuple[Path, str], tuple[int, int]] = {}

    @classmethod
    def build(
        cls,
        books: corpus.Corpus,
        *,
        strict: bool | None = None,
        dictionary: str | os.PathLike[str] | None = None,
        undefined: UndefinedPolicy = UndefinedPolicy.HOLE,
        supply: Mapping[SupplyKey, Supplied | Alias] | None = None,
    ) -> Model:
        """The model over `books`.

        By default the build holds the corpus to its record of known holes
        (`corpus.Corpus.record`, docs/consumers.md): a hole the record does
        not list raises `IncompleteCorpusError` with all such, and an entry
        naming no hole raises `StaleHoleRecordError`, unless the entry is an
        undefined name `undefined` answered for. A corpus with no record has
        no known holes. A recorded hole stays one: the name resolves to no
        `Avp`, `holes` reports it and `Hole.recorded` says why it stands.

        `strict=True` refuses every hole, recorded or not, so a consumer that
        needs every AVP complete learns at build time rather than from a
        missing member later; what it guarantees is that every member is an
        `Avp`, the wildcard, or what `undefined` asked for. `strict=False`
        holds the corpus to nothing, for a partial or foreign one.

        `dictionary` is a Wireshark dictionary directory (the downloader's
        `specifications/wireshark`); with one, every AVP and hole with an
        identity carries Wireshark's name for it in `wireshark_name`.
        Without one that field is None and nothing else changes. One that
        cannot be read raises `ModelError`.

        `undefined` is the consumer's answer for the names `Undefined AVP`
        blocks declare (`UndefinedPolicy`), and `supply` what `SUPPLY`
        reads, keyed by name or, winning over it, by `(reference, name)`:
        a `Supplied` definition (`supplied_from` reads them from a `.dad`
        sidecar) or an `Alias`. `supply` is required with `SUPPLY` and
        refused otherwise; a key naming no block is refused as a stale
        correction is, since either it is a typo or upstream has defined
        the name; so is a `Supplied` claiming the identity of an AVP the
        corpus defines, which an `Alias` says instead, or of another name's
        `Supplied`, and a cycle of `Alias`es.
        """
        policy = UndefinedPolicy(undefined)
        if policy is UndefinedPolicy.SUPPLY and supply is None:
            raise ModelError("undefined=SUPPLY needs supply=")
        if policy is not UndefinedPolicy.SUPPLY and supply is not None:
            raise ModelError(
                f"supply= is read only with undefined=SUPPLY, not {policy}"
            )
        try:
            loaded = None if dictionary is None else oracle.Oracle.load(dictionary)
        except (ValueError, LookupError) as error:
            # An `OracleError`, or a dictionary whose XML parses but lacks an
            # attribute or holds no number where the wire format needs one.
            raise ModelError(
                f"cannot read the dictionary at {dictionary}: {error!r}"
            ) from error
        built = cls(books, loaded, policy, supply)
        built._check_supply()
        if strict is None:
            if unrecorded := built.unrecorded_holes():
                raise IncompleteCorpusError(unrecorded, unrecorded=True)
            if stale := built.stale_record_entries():
                raise StaleHoleRecordError(stale)
        elif strict and (holes := built.holes()):
            raise IncompleteCorpusError(holes)
        return built

    @property
    def undefined_policy(self) -> UndefinedPolicy:
        """What the model makes of the names `Undefined AVP` blocks
        declare."""
        return self._policy

    def _check_supply(self) -> None:
        """Every key names a block, every `Supplied` is shaped for its
        type and claims no identity the corpus defines, and every `Alias`
        names an AVP the corpus completes."""
        declared = {
            (view.entry.reference, name)
            for view in self._copies.values()
            for name in view.undefined
        }
        names = {name for _, name in declared}
        for key, answer in self._supply.items():
            if key not in (declared if isinstance(key, tuple) else names):
                raise ModelError(
                    f"supply names {key!r}, which no Undefined AVP block"
                    " declares: a typo, or the corpus now defines it"
                )
            if isinstance(answer, Alias):
                if self.resolve(answer.reference, answer.name) is None:
                    raise ModelError(
                        f"supply reads {key!r} as {answer.reference}"
                        f" {answer.name}, which the corpus does not complete"
                    )
                continue
            if answer.members and answer.data_type is not ast.DataType.GROUPED:
                raise ModelError(f"supply for {key!r} has members but is no Grouped")
            if answer.values and answer.data_type is not ast.DataType.ENUMERATED:
                raise ModelError(f"supply for {key!r} has values but is no Enumerated")
        for key, answer in self._supply.items():
            if not isinstance(answer, Supplied):
                continue
            claimed = [
                avp
                for avp in self.identified(answer.vendor_id, answer.code)
                if avp.supplied is None
            ]
            if claimed:
                raise ModelError(
                    f"supply for {key!r} claims (vendor {answer.vendor_id},"
                    f" code {answer.code}), which is {claimed[0].defined_in}'s"
                    f" {claimed[0].name}; an Alias reads one name as another"
                )
        # Two supplied names on one identity are as bad as a supplied name on
        # a corpus AVP's. Only the answers a block takes count: a name key
        # every document key shadows supplies nothing.
        claimants: dict[tuple[int, int], tuple[str, str]] = {}
        for reference, name in sorted(declared):
            answer = self._supply.get((reference, name))
            if answer is None:
                answer = self._supply.get(name)
            if not isinstance(answer, Supplied):
                continue
            identity = (answer.vendor_id, answer.code)
            first = claimants.setdefault(identity, (reference, name))
            if first[1] != name:
                raise ModelError(
                    f"supply for {first[0]} {first[1]} and for {reference} {name}"
                    f" both claim (vendor {answer.vendor_id}, code {answer.code});"
                    " two names on one identity are no dictionary"
                )

    def references(self) -> list[str]:
        """Every specification the model answers for, `TS29.229`-spelled."""
        return sorted(self._views)

    def _view(self, reference: str, version: str | None = None) -> _View:
        if version is not None:
            for view in self._copies.values():
                if (
                    view.entry.reference == reference
                    and view.entry.spec.version == version
                ):
                    return view
            raise ModelError(f"the corpus holds no copy of {reference} V{version}")
        try:
            return self._views[reference]
        except KeyError:
            raise ModelError(f"the corpus holds no copy of {reference}") from None

    def messages(
        self, reference: str, *, version: str | None = None
    ) -> tuple[Message, ...]:
        """Every command `reference` defines, bodies resolved; `version` reads
        an older copy the corpus holds."""
        view = self._view(reference, version)
        return tuple(
            Message(
                name=message.name,
                abbreviation=message.abbreviation,
                command_code=message.command_code,
                flags=message.flags,
                application_id=message.application_id,
                defined_in=view.entry.reference,
                section=message.source.section,
                avps=avps,
                dropped=dropped,
            )
            for message in view.messages
            for avps, dropped in [self._split(self._body(view, message.avps))]
        )

    def undefined(self, reference: str | None = None) -> tuple[Undefined, ...]:
        """Every `Undefined AVP` block in `reference`, or in the corpus,
        under any policy, in file order."""
        references = self.references() if reference is None else [reference]
        return tuple(
            self._undefined_of(view, block)
            for each in references
            for view in [self._view(each)]
            for block in view.undefined.values()
        )

    def placeholders(self, reference: str | None = None) -> tuple[Placeholder, ...]:
        """Every placeholder in `reference`'s reading, or in the whole
        corpus's, as `holes` finds holes; none unless the model was built
        with `UndefinedPolicy.PLACEHOLDER`. Sorted by document and name."""
        if self._policy is not UndefinedPolicy.PLACEHOLDER:
            return ()
        references = self.references() if reference is None else [reference]
        found: dict[Placeholder, None] = {}
        for each in references:
            view = self._view(each)
            for name in self._names(each):
                hole = self._final(view, name)
                if isinstance(hole, Hole) and hole.undefined is not None:
                    found[Placeholder(hole.undefined)] = None
            for body in self._bodies(each):
                found.update(
                    (member.placeholder, None)
                    for member in body
                    if member.placeholder is not None
                )
        return tuple(
            sorted(
                found,
                key=lambda each: (
                    each.undefined.reference,
                    each.undefined.version or "",
                    each.name,
                ),
            )
        )

    def applications(
        self, reference: str, *, version: str | None = None
    ) -> tuple[Application, ...]:
        """`reference`'s commands, grouped by application id and the clause
        they sit under, in file order.

        A command whose header prints no id takes the one an `Application
        Scope` block covering its clause states (the first, where scopes
        overlap): TS 29.212's clause 5.1 gives the Gx commands of `5.*`
        16777238, and RFC 5778's two blocks split its clause 5 between 7 and
        8. A header that prints an id keeps it; the linter reports one that
        disagrees with its block.

        One group can still define a command twice: TS 29.273 prints the
        STa Session-Termination-Request in clauses 5.2.2.2.3 and 5.2.2.4.1,
        once per procedure. Which copy a consumer keeps is its business.

        `version` reads an older copy the corpus holds.
        """
        view = self._view(reference, version)
        groups: dict[tuple[int | None, str], list[Message]] = {}
        stating: dict[tuple[int | None, str], ast.ApplicationScope] = {}
        for message in self.messages(reference, version=version):
            block = next(
                (each for each in view.applications if each.covers(message.section)),
                None,
            )
            application_id = message.application_id
            if application_id is None and block is not None:
                application_id = block.application_id
            key = (application_id, ast.interface_clause(message.section))
            groups.setdefault(key, []).append(message)
            if block is not None and block.application_id == application_id:
                stating.setdefault(key, block)
        return tuple(
            Application(
                reference,
                application_id,
                clause,
                tuple(messages),
                name=None if block is None else block.name,
                stated_in=None if block is None else block.source.section,
            )
            for (application_id, clause), messages in groups.items()
            for block in [stating.get((application_id, clause))]
        )

    def avps(self, reference: str) -> tuple[Avp, ...]:
        """Every AVP `reference` defines, tabulates or re-uses, resolved.

        This is the specification's dictionary view: a re-printed or re-used
        AVP appears with the origin's `defined_in`, so a consumer that wants
        only the document's own AVPs filters on that field. A name with a
        hole is left out; `holes` lists it.
        """
        found = (self.resolve(reference, name) for name in self._names(reference))
        return tuple(avp for avp in found if avp is not None)

    def resolve(
        self, reference: str, name: str, *, version: str | None = None
    ) -> Avp | None:
        """`name` as `reference` means it, or None when the corpus cannot
        complete it — `hole` says why — or the consumer chose to drop or
        keep it untyped (`undefined` says what was declared)."""
        found = self._final(self._view(reference, version), name)
        return found if isinstance(found, Avp) else None

    def hole(
        self, reference: str, name: str, *, version: str | None = None
    ) -> Hole | None:
        """What `reference`'s reading of `name` lacks, or None when it
        resolves completely or is an undefined name the policy answers
        for."""
        found = self._final(self._view(reference, version), name)
        return found if isinstance(found, Hole) and self._open(found) else None

    def _open(self, hole: Hole) -> bool:
        """Whether a hole stays one under the policy: every hole but an
        undefined name the consumer drops or keeps as a placeholder."""
        return hole.undefined is None or self._policy in (
            UndefinedPolicy.HOLE,
            UndefinedPolicy.SUPPLY,
        )

    def holes(self, reference: str | None = None) -> tuple[Hole, ...]:
        """Every hole in `reference`'s reading, or in the whole corpus.

        A reading's holes are the names its dictionary view and its command
        and grouped bodies cannot complete, and those of the grouped AVPs it
        reaches in an older copy through a citation across releases, which
        carry that copy's `version`. A hole belongs to the document that
        falls short, so a citing reading reports an origin's untyped rows
        only where its own table does not type them (TS 29.229's did RFC
        4590's `Digest-*` rows before RFC 4590's corrections typed them).
        Sorted by document and name.
        """
        references = self.references() if reference is None else [reference]
        found: dict[Hole, None] = {}
        for each in references:
            for name in self._names(each):
                hole = self.hole(each, name)
                if hole is not None:
                    found[hole] = None
            for body in self._bodies(each):
                found.update(
                    (member.hole, None) for member in body if member.hole is not None
                )
            found.update(dict.fromkeys(self._holes_across(each)))
        return tuple(sorted(found, key=lambda hole: (hole.document, hole.name)))

    def unrecorded_holes(self) -> tuple[Hole, ...]:
        """Every hole the corpus's record of known holes does not list as it
        is: no entry names it, or the entry names other missing fields."""
        return tuple(hole for hole in self.holes() if hole.recorded is None)

    def stale_record_entries(self) -> tuple[corpus.KnownHole, ...]:
        """Every entry of the record naming no hole: its document is gone, the
        name is defined upstream, or a stand-in resolved it. An entry that
        lists a hole of the corpus's own, the reading with no consumer's
        answer, and goes unused only because `undefined` answered for it is
        not stale; one no such reading has is, under every policy."""
        present = {(hole.document, hole.name) for hole in self.holes()}
        unanswered = (
            self if self._policy is UndefinedPolicy.HOLE else Model(self._books)
        ).holes()
        listed = {(hole.document, hole.name, hole.missing) for hole in unanswered}
        return tuple(
            entry
            for key, entry in self._known.items()
            if key not in present and (*key, entry.missing) not in listed
        )

    def _bodies(self, reference: str) -> list[tuple[Member, ...]]:
        """The command and grouped bodies `reference` defines, resolved,
        without what the policy dropped."""
        view = self._view(reference)
        bodies = [message.avps for message in self.messages(reference)]
        bodies += [
            avp.members
            for avp in self.avps(reference)
            if isinstance(avp, Grouped) and avp.defined_in == reference
        ]
        # A grouped definition with a hole is no `Grouped`, but its body
        # is still this document's to resolve.
        bodies += [
            self._split(self._body(view, definition.avps))[0]
            for name, definition in view.defined.items()
            if isinstance(definition, ast.GroupedAvp)
            and self.hole(reference, name) is not None
        ]
        return bodies

    def _holes_across(self, reference: str) -> Iterator[Hole]:
        """The holes of older copies in the grouped AVPs `reference`'s
        reading reaches through a citation across releases, at any depth:
        oneM2M TS-0004's `Service-Information` is TS 32.299 V11.20.0's, a
        hole of whose would carry its version. No reading of that older
        copy's own reports them, since reference-level queries answer from
        the newest. A hole in a newest copy, reached through a later
        release's copy standing in (TS 29.061's
        `3GPP-Session-Stop-Indicator` from V11.20.0's `PS-Information`), is
        that copy's own reading's to report."""
        pending = [*self.avps(reference)]
        pending += [
            member.avp
            for message in self.messages(reference)
            for member in message.avps
            if member.avp is not None
        ]
        seen: set[int] = set()
        while pending:
            avp = pending.pop()
            if id(avp) in seen or not isinstance(avp, Grouped):
                continue
            seen.add(id(avp))
            for member in avp.members:
                if member.hole is not None and member.hole.version is not None:
                    yield member.hole
                elif member.avp is not None:
                    pending.append(member.avp)

    def across_releases(self, reference: str | None = None) -> tuple[Avp | Hole, ...]:
        """Every name in `reference`'s reading, or in the whole corpus's,
        that took a field from a document resolved outside the citing
        document's release, each carrying the `corpus.CrossRelease` that
        says by which drafting rule: TS 32.299's `VAS-ID` from TS 29.140
        V7.0.0, ETSI TS 183 017's `Codec-Data` from TS 29.214 V7.12.0. The
        audit list for a reader who wants to check the corpus's reading of
        the citing documents' references (docs/consumers.md). It includes
        what an older copy reached across releases cites across releases in
        turn, at any depth, which no reading of that copy's own lists:
        oneM2M TS-0004's `Service-Information` is TS 32.299 V11.20.0's,
        whose `Server-Capabilities` is TS 29.229 V18.1.0's, standing in.
        Sorted by citing document and name."""
        references = self.references() if reference is None else [reference]
        found: dict[Avp | Hole, None] = {}
        for each in references:
            view = self._view(each)
            for name in self._names(each):
                resolved = self._final(view, name)
                if resolved.across_releases is not None:
                    found[resolved] = None
                    found.update(dict.fromkeys(_reached_across(resolved)))
        return tuple(sorted(found, key=_by_citing_document))

    def table_rows(self, reference: str, name: str) -> tuple[ast.AvpTableRow, ...]:
        """Every AVP-table row `reference` prints for `name`, in file order.

        `resolve` takes its table facts from the first; a document that
        tabulates one AVP per interface may print the others differently
        (TS 29.061's `3GPP-IMSI` in tables 9a and 10), and this is where a
        consumer sees the alternatives the linter's `table-row-mismatch`
        reports.
        """
        return tuple(self._view(reference).tabled.get(name, ()))

    def marks(self, reference: str, name: str) -> tuple[Marks, ...]:
        """What `reference`'s tables mark about `name`, one entry per row of
        a table printing mark columns, AVP and re-used tables alike, in file
        order.

        A document tabulating per interface marks per interface: TS 29.212
        lists Gx's AVPs again in Gxx's re-used table 5a.4.0.1 with Gxx's
        access types and features, so a consumer generating one interface
        reads the rows whose `section` lies in its clause.
        """
        return tuple(self._view(reference).marked.get(name, ()))

    def registry(
        self, kind: ast.RegistryKind, code: int | None = None
    ) -> tuple[Allocation, ...]:
        """What the corpus's registries say of `kind`'s codes, in file
        order: every row and reserved range, or with `code`, the rows
        allocating it and the ranges reserving it.

        TS 29.230's table 4.1 allocates 16777216 to "3GPP Cx/Px" in TS
        29.228 and 29.229; table 7.1 allocates 318 twice and reserves 1-255
        for RADIUS compatibility. Read-only evidence: nothing else the model
        answers takes from it.
        """
        return tuple(
            Allocation(view.entry.reference, table.table, table.source.section, row)
            for reference in self.references()
            for view in [self._views[reference]]
            for table in view.registries
            if table.registry is kind
            for row in table.rows
            if code is None
            or (isinstance(row, ast.RegistryRow) and row.code == code)
            or (isinstance(row, ast.RegistryReservation) and row.covers(code))
        )

    def find(self, name: str) -> tuple[Avp, ...]:
        """Every distinct AVP the corpus knows under `name`."""
        return self._by_name.get(name, ())

    def identified(self, vendor_id: int, code: int) -> tuple[Avp, ...]:
        """Every distinct AVP claiming `(vendor-id, code)`.

        More than one entry is the corpus disagreeing with itself — the
        linter's `duplicate-identity` — or two documents' differing copies of
        one AVP surviving deduplication because their bodies differ, or
        because a citing document's table sets its own flag rules: RFC
        4590's code 110 is `Digest-Qop` M in May and, through TS 29.229, M
        in Must.
        """
        return self._by_identity.get((vendor_id, code), ())

    # --- resolution ---------------------------------------------------------

    def _names(self, reference: str) -> dict[str, None]:
        view = self._view(reference)
        return dict.fromkeys(
            (*view.defined, *view.tabled, *view.reused, *view.undefined)
        )

    def _final(self, view: _View, name: str, stack: tuple = ()) -> Avp | Hole:
        draft = self._resolve(view, name, stack)
        if draft is None:
            return self._on_record(
                Hole(
                    view.entry.reference, name, (DEFINITION,), version=self._older(view)
                )
            )
        found = draft.final
        if (
            isinstance(found, Hole)
            and found.undefined is not None
            and self._policy is UndefinedPolicy.SUPPLY
        ):
            answered = self._answered(found.undefined, stack)
            if answered is None:
                return self._on_record(found)
            if answered.supplied is not None and found.across_releases is not None:
                # The supplied definition is the declaring document's; the
                # citation that reached it is this reading's, as it is for
                # any field a reading takes across releases.
                return replace(answered, across_releases=found.across_releases)
            return answered
        return self._on_record(found) if isinstance(found, Hole) else found

    def _on_record(self, hole: Hole) -> Hole:
        """`hole` with the reason the record states for it, when an entry
        lists it as it is."""
        entry = self._known.get((hole.document, hole.name))
        if entry is None or entry.missing != hole.missing:
            return hole
        return replace(hole, recorded=entry.reason)

    def _undefined_of(self, view: _View, block: ast.UndefinedAvp) -> Undefined:
        return Undefined(
            reference=view.entry.reference,
            name=block.name,
            section=block.source.section,
            page=block.source.page,
            note=block.note,
            cited_in=view.cited_in(block.name),
            version=self._older(view),
        )

    def _declaring(self, undefined: Undefined) -> _View:
        """The copy whose block `undefined` is."""
        return next(
            view
            for view in self._copies.values()
            if view.entry.reference == undefined.reference
            and self._older(view) == undefined.version
        )

    def _answer(self, undefined: Undefined) -> Supplied | Alias | None:
        """What `supply` says of a declared name, a document key first."""
        answer = self._supply.get((undefined.reference, undefined.name))
        return self._supply.get(undefined.name) if answer is None else answer

    def _answered(self, undefined: Undefined, stack: tuple) -> Avp | None:
        """What `supply` answers for a declared name: the `Supplied`
        definition read in the declaring document, or the AVP an `Alias`
        names; None where it says nothing of it."""
        answer = self._answer(undefined)
        if answer is None:
            return None
        if isinstance(answer, Alias):
            # The stack carries each alias being followed, so one leading
            # back to a name already being answered is refused rather than
            # followed forever.
            mark = (_ALIASED, undefined.reference, undefined.version, undefined.name)
            if mark in stack:
                chain = [each for each in stack if each[0] is _ALIASED]
                cycle = [*chain[chain.index(mark) :], mark]
                raise ModelError(
                    "supply aliases form a cycle: "
                    + " -> ".join(f"{each[1]} {each[3]}" for each in cycle)
                )
            found = self._final(
                self._view(answer.reference), answer.name, (*stack, mark)
            )
            return found if isinstance(found, Avp) else None
        view = self._declaring(undefined)
        key = (view.entry.path, undefined.name)
        if key in self._supplied:
            return self._supplied[key]
        kind = {
            ast.DataType.GROUPED: Grouped,
            ast.DataType.ENUMERATED: Enumerated,
        }.get(answer.data_type, Avp)
        draft = _Draft(
            kind,
            undefined.name,
            undefined.reference,
            undefined.version,
            vendor_id=answer.vendor_id,
            vendor_stated=True,
            code=answer.code,
            data_type=answer.data_type,
            flag_rules=answer.flag_rules,
            section=undefined.section,
            values=answer.values,
            supplied=answer.source,
        )
        if kind is Grouped:
            # A member that is itself declared undefined follows the
            # policy, and the name among its own members is cut.
            members = self._body(view, answer.members, (*stack, key))
            draft.members, draft.dropped = self._split(members)
        if self._dictionary is not None:
            draft.wireshark_name = self._dictionary.name_for(
                answer.vendor_id, answer.code, undefined.name, answer.data_type
            )
        found = draft.final
        assert isinstance(found, Avp)
        self._supplied[key] = found
        return found

    def _older(self, view: _View) -> str | None:
        """`view`'s version when it is an older copy the corpus holds for a
        citation, not the one reference-level queries answer from: the
        version a hole falling short there names (TS 32.299 V11.20.0)."""
        if view is self._views[view.entry.reference]:
            return None
        return view.entry.spec.version

    def _resolve(self, view: _View, name: str, stack: tuple) -> _Draft | None:
        key = (view.entry.path, name)
        if key in self._resolved:
            return self._resolved[key]
        if key in stack:
            # A grouped AVP among its own descendants. No real specification
            # does this; stopping here keeps a defective one from recursing.
            return None
        result = self._resolve_here(view, name, (*stack, key))
        self._resolved[key] = result
        return result

    def _resolve_here(self, view: _View, name: str, stack: tuple) -> _Draft | None:
        """The first reading along the resolution order, with whatever it
        leaves unstated filled from the readings after it.

        A re-print that tabulates no flag rules (TS 29.272's
        `Allocation-Retention-Priority`, re-used from TS 29.212) takes them
        from its origin, and an origin that states no Diameter type (RFC
        4590's RADIUS-derived `Digest-*` rows, uncorrected) takes it from
        the citing document's table. The first reading still names the defining
        document.

        A re-used name whose row in the citing document's own AVP table
        states flag cells takes those cells over every other reading's
        (`_own_flags`), the others supplying only the flags the row places
        in no column: TS 29.229's `Digest-Qop` is M in Must through TS
        29.229 and M in May through RFC 4590. Below those cells and above
        the origin ranks the M-bit cell of the citing document's re-used
        row (`_own_m_bit`): TS 29.272's `RAT-Type` is M in Must, TS 29.212's
        M in Must not.

        A grouped AVP defined elsewhere keeps its defining document's body,
        but each member this document says anything of is read through it
        (`_through`): TS 32.299's `Supported-Features` is TS 29.229's, and
        its `Feature-List` member TS 32.299's, M in Must.
        """
        own = self._own_flags(view, name)
        m_bit = self._own_m_bit(view, name)
        found: _Draft | None = None
        for reading in self._readings(view, name, stack, own is None):
            found = reading if found is None else found.fill(reading)
            if found.complete or found.conflict is not None:
                break
        if found is not None and found.kind is not None:
            rules = found.flag_rules
            if m_bit is not None and (
                rules is not None or found.vendor_id == ast.IETF_VENDOR
            ):
                # Over an IETF reading stating no flags, RFC 6733's V rule
                # completes the M-bit (`_ietf_rules`); anywhere else an M
                # alone would complete rules nothing else states.
                rules = _overlay(m_bit, rules)
            if own is not None:
                rules = _overlay(own, rules)
            completed = found.completed_by
            if (
                rules is not None
                and found.flag_rules is None
                and found.reference != view.entry.reference
            ):
                completed += ((FLAG_RULES, view.entry.reference),)
            found = replace(found, flag_rules=rules, completed_by=completed)
            if found.kind is Grouped and not isinstance(
                view.defined.get(name), ast.GroupedAvp
            ):
                self._settle(stack[-1], found.vendor_id, found.code)
                found.members = self._through(view, found.members, stack)
        if (
            found is not None
            and self._dictionary is not None
            and found.vendor_id is not None
            and found.code is not None
        ):
            # Looked up once the identity is final: a reading filled through
            # may take its code from the next document.
            wireshark_name = self._dictionary.name_for(
                found.vendor_id, found.code, found.name, found.data_type
            )
            found = replace(found, wireshark_name=wireshark_name)
        return found

    def _own_flags(self, view: _View, name: str) -> ast.AvpFlagRules | None:
        """The flag rules `view`'s AVP-table rows state for a name it
        re-uses, each flag where the first row placing it puts it, or None
        when it re-uses no such name or no row places any flag.

        RFC 6733 section 4.1 leaves the M bit to "the application
        specification that introduces or reuses this AVP" and section 4.5
        has each application state its AVPs' flag rules, so where the citing
        table states them they are its application's, and resolution through
        the citing document reads them rather than the origin's. Per flag,
        since a row leaving a flag in no column says nothing of it: a later
        row is read only for a flag no earlier row places. A file citing
        itself (TS 29.212's Gxx tables, "from" TS 29.212) re-uses
        nothing, and its rows are read as any other."""
        rows = view.tabled.get(name)
        origin = view.reused.get(name)
        if origin is None or rows is None:
            return None
        if self._cited(view, origin)[0] is view:
            return None
        rules = rows[0].flag_rules
        for row in rows[1:]:
            rules = _overlay(rules, row.flag_rules)
        return rules if _stated(rules) else None

    def _own_m_bit(self, view: _View, name: str) -> ast.AvpFlagRules | None:
        """The M rule the first of `view`'s re-used rows for a name whose
        M-bit cell states one gives, as flag rules placing M alone, or None
        when no row's cell does (a dash, a blank, no M-bit column) or the
        rows cite `view` itself.

        The column is the citing interface's own M setting (TS 29.272 table
        7.3.1/2 marks TS 29.212's `RAT-Type` `MUST`), so it outranks the
        origin's rule as `_own_flags` does, and ranks below the citing
        document's AVP-table cells, the fuller statement. A row whose cell
        says nothing is passed over: TS 29.336's `DRMP` rows read `-` for
        its first interface and `MUST-NOT` for its second, so M is in Must
        not."""
        for row in view.reused_rows.get(name, ()):
            if row.m_bit is None or self._cited(view, row.origin)[0] is view:
                continue
            if row.m_bit is ast.MBitOverride.MUST:
                return ast.AvpFlagRules(must=frozenset({ast.AvpFlag.MANDATORY}))
            return ast.AvpFlagRules(must_not=frozenset({ast.AvpFlag.MANDATORY}))
        return None

    def _through(
        self, view: _View, members: tuple[Member, ...], stack: tuple
    ) -> tuple[Member, ...]:
        """A body another document resolved, with each member `view`
        defines, tabulates or re-uses read through `view` instead, so that
        its own rules for the member (`_own_flags`, `_own_m_bit`) hold
        inside the grouped AVP as they do at top level. A member `view` says
        nothing of keeps the other document's reading, and so does one
        `view` reads as another AVP: the body names its members in the
        defining document's sense, and a name is no identity. TS 32.299's
        own `Originator` is (10415, 864) Enumerated, but the re-used
        `M2M-Information` it reads through oneM2M TS-0004 holds oneM2M's,
        (45687, 1008) UTF8String. Only a reading whose vendor and code are
        both known and both the member's is read through `view`: two holes
        stating no code are no evidence of one AVP. A grouped member read
        through `view` has
        its own members read the same way; one already being resolved
        through `view` (a body among its own descendants) is cut as `_body`
        cuts it, but only where the identity that reading has settled
        (`_settled`) is known and the member's: a citing document's own
        `Feature` holding a re-used `Bundle` whose `Feature` is the
        origin's, another AVP, keeps the origin's member."""
        says = view.defined.keys() | view.tabled.keys() | view.reused.keys()
        read = []
        for member in members:
            mine = member
            if member.name in says:
                mine = self._member(view, member.rule, stack)
                identity = (
                    self._settled.get((view.entry.path, member.name))
                    if _cut(mine)
                    else _identity(mine)
                )
                if identity is None or identity != _identity(member):
                    mine = member
            read.append(mine)
        return tuple(read)

    def _settle(
        self, key: tuple[Path, str], vendor_id: int | None, code: int | None
    ) -> None:
        """Record the identity the reading under `key`, still being
        resolved, has settled before its members are read, if it is
        known."""
        if vendor_id is not None and code is not None:
            self._settled[key] = (vendor_id, code)

    def _readings(
        self, view: _View, name: str, stack: tuple, own_flags: bool = True
    ) -> Iterator[_Draft]:
        """Every document's reading of `name`, in resolution order, lazily:
        the local definition, the re-used origin, the local table row, the
        `; Bases:` documents.

        Without `own_flags` the local readings carry no flag rules, so that
        flags the caller lays over the result (`_own_flags`) neither fill nor
        disagree with another document's."""
        rows = view.tabled.get(name)
        origin = view.reused.get(name)
        theirs, across = (None, None) if origin is None else self._cited(view, origin)
        unread = origin if theirs is None else None
        definition = view.defined.get(name)
        if definition is not None:
            draft = self._from_definition(view, definition, rows, unread, stack)
            yield draft if own_flags else replace(draft, flag_rules=None)
        if theirs is not None and (found := self._resolve(theirs, name, stack)):
            yield found if across is None else replace(found, across=across)
        if rows is not None and definition is None:
            draft = self._from_row(view, name, rows[0], unread)
            yield draft if own_flags else replace(draft, flag_rules=None)
        for base in view.entry.spec.bases:
            cited, across = self._cited(view, base)
            if cited is not None and (found := self._resolve(cited, name, stack)):
                yield found if across is None else replace(found, across=across)
        if unread is not None:
            yield _Draft(
                None, name, view.entry.reference, self._older(view), origin=unread
            )
        if (block := view.undefined.get(name)) is not None:
            # Last: it explains the failure and defines nothing.
            yield _Draft(
                None,
                name,
                view.entry.reference,
                self._older(view),
                section=block.source.section,
                undefined=self._undefined_of(view, block),
            )

    def _cited(
        self, view: _View, reference: str
    ) -> tuple[_View | None, corpus.CrossRelease | None]:
        """The copy `reference` names when cited from `view`, if the corpus
        holds the one the drafting rules mean, and how it was reached when
        that is outside `view`'s release (`corpus.Corpus.resolution`)."""
        entry, across = self._books.resolution(reference, like=view.entry.spec)
        return (None, None) if entry is None else (self._copies[entry.path], across)

    def _from_row(
        self, view: _View, name: str, row: ast.AvpTableRow, unread: str | None
    ) -> _Draft:
        file_vendor = view.entry.spec.vendor_id
        stated = row.stated_vendor(file_vendor)
        return _Draft(
            Avp,
            name,
            view.entry.reference,
            self._older(view),
            vendor_id=file_vendor if stated is None else stated,
            vendor_stated=stated is not None,
            code=row.code,
            data_type=row.data_type,
            flag_rules=row.flag_rules if _stated(row.flag_rules) else None,
            section=row.section,
            origin=unread,
        )

    def _from_definition(
        self,
        view: _View,
        definition: ast.GroupedAvp | ast.EnumeratedAvp,
        rows: list[ast.AvpTableRow] | None,
        unread: str | None,
        stack: tuple,
    ) -> _Draft:
        flag_rules = None if rows is None else rows[0].flag_rules
        draft = _Draft(
            Grouped if isinstance(definition, ast.GroupedAvp) else Enumerated,
            definition.name,
            view.entry.reference,
            self._older(view),
            # A definition written with no vendor-id is IETF-space; the wire
            # format calls that vendor 0.
            vendor_id=(
                ast.IETF_VENDOR
                if definition.vendor_id is None
                else definition.vendor_id
            ),
            vendor_stated=True,
            code=definition.code,
            flag_rules=(
                flag_rules if flag_rules is not None and _stated(flag_rules) else None
            ),
            section=definition.source.section,
            origin=unread,
        )
        if isinstance(definition, ast.GroupedAvp):
            draft.data_type = ast.DataType.GROUPED
            self._settle(stack[-1], draft.vendor_id, draft.code)
            draft.members, draft.dropped = self._split(
                self._body(view, definition.avps, stack)
            )
        else:
            draft.data_type = ast.DataType.ENUMERATED
            draft.values = definition.values
            draft.values_source = definition.values_source
        return draft

    def _body(
        self, view: _View, rules: tuple[ast.AvpRule, ...], stack: tuple = ()
    ) -> tuple[Member, ...]:
        return tuple(self._member(view, rule, stack) for rule in rules)

    def _member(self, view: _View, rule: ast.AvpRule, stack: tuple) -> Member:
        """One body line, its name read through `view`."""
        # `AVP` is RFC 6733's any-AVP wildcard — grammar, not a name.
        if rule.name == "AVP" or (view.entry.path, rule.name) in stack:
            return Member(rule=rule, avp=None)
        found = self._final(view, rule.name, stack)
        if isinstance(found, Avp):
            return Member(rule=rule, avp=found, alias=self._alias(view, rule.name))
        if found.undefined is not None and self._policy is UndefinedPolicy.PLACEHOLDER:
            return Member(rule=rule, avp=None, placeholder=Placeholder(found.undefined))
        return Member(rule=rule, avp=None, hole=found)

    def _alias(self, view: _View, name: str) -> Alias | None:
        """The `Alias` `name` resolves through in `view`, if it does."""
        if self._policy is not UndefinedPolicy.SUPPLY:
            return None
        draft = self._resolved.get((view.entry.path, name))
        hole = None if draft is None else draft.final
        if not isinstance(hole, Hole) or hole.undefined is None:
            return None
        answer = self._answer(hole.undefined)
        return answer if isinstance(answer, Alias) else None

    def _split(
        self, members: tuple[Member, ...]
    ) -> tuple[tuple[Member, ...], tuple[Member, ...]]:
        """A body's members, and those `UndefinedPolicy.DROP` takes out of
        it: the undefined ones, required or not."""
        if self._policy is not UndefinedPolicy.DROP:
            return members, ()
        kept: list[Member] = []
        dropped: list[Member] = []
        for member in members:
            undefined = member.hole is not None and member.hole.undefined is not None
            (dropped if undefined else kept).append(member)
        return tuple(kept), tuple(dropped)

    # --- corpus-wide lookup -------------------------------------------------

    @cached_property
    def _everything(self) -> list[Avp]:
        found: dict[Avp, None] = {}
        for reference in self._views:
            found.update(dict.fromkeys(self.avps(reference)))
        return list(found)

    @cached_property
    def _by_name(self) -> dict[str, tuple[Avp, ...]]:
        table: dict[str, list[Avp]] = {}
        for avp in self._everything:
            table.setdefault(avp.name, []).append(avp)
        return {name: tuple(avps) for name, avps in table.items()}

    @cached_property
    def _by_identity(self) -> dict[tuple[int, int], tuple[Avp, ...]]:
        table: dict[tuple[int, int], list[Avp]] = {}
        for avp in self._everything:
            table.setdefault(avp.identity, []).append(avp)
        return {identity: tuple(avps) for identity, avps in table.items()}
