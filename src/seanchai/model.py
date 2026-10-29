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
- The linter, not this module, is where the conflicts live: anything
  `reused-body-differs` or `table-definition-mismatch` would report is
  resolved here by the order above without comment. Run the linter to see
  what the policy papered over.
- An AVP-table row with no matching definition and no re-used listing claims
  the file's own `; Vendor-ID:` space, exactly as the linter's
  `duplicate-identity` rule reads it; a definition written with no vendor-id
  is IETF-space (vendor 0), the wire format's reading of an absent vendor.
- A name tabulated in more than one of a file's AVP tables takes its table
  facts (flag rules; type and code when nothing defines it) from the first
  row in file order. `Model.table_rows` returns all of them, for the
  documents whose per-interface tables disagree.
- A field the first reading in that order leaves unstated is taken from the
  next reading, as long as every field both state agrees (a table row's
  vendor, inferred from its file, agrees with any): a re-print tabulated
  nowhere takes its origin's flag rules. A disagreeing reading fills
  nothing and is named in the hole instead.

An `Avp` has every field; a name the corpus cannot complete is a `Hole`
instead, whether a field is unstated everywhere along the order or the name
resolves nowhere at all. `Model.build(..., strict=True)` refuses a corpus
with any; otherwise `Model.holes` lists them and `Member.avp` is `None` with
`Member.hole` saying why. `Member.avp` is also `None`, with no hole, for RFC
6733's `* [ AVP ]` wildcard, which is grammar rather than a reference.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from . import corpus, oracle
from .dad import ast


class ModelError(ValueError):
    pass


class IncompleteCorpusError(ModelError):
    """A strict build over a corpus with holes; `holes` lists every one."""

    def __init__(self, holes: tuple[Hole, ...]) -> None:
        self.holes = holes
        listing = "".join(f"\n  {hole}" for hole in holes)
        super().__init__(
            f"the corpus has {len(holes)} hole{'' if len(holes) == 1 else 's'}"
            f" (Model.build(..., strict=False) builds the rest):{listing}"
        )


@dataclass(frozen=True)
class Avp:
    """One resolved AVP, as the specification `defined_in` states it.

    Every field is a fact some document in the corpus states; an AVP missing
    one is a `Hole` instead, never an `Avp` with a gap in it.
    """

    name: str
    vendor_id: int
    code: int
    data_type: ast.DataType
    flag_rules: ast.AvpFlagRules
    # The reference re-used rows cite: `TS29.229`, `RFC6733`.
    defined_in: str
    section: str | None
    # Wireshark's dictionary name for `(vendor-id, code)`, when the model is
    # built with one and it says: `Call-Barring-Infor-List` for TS 29.272's
    # `Call-Barring-Info`. Extra information beside `name`, never instead.
    wireshark_name: str | None

    @property
    def identity(self) -> tuple[int, int]:
        """`(vendor-id, code)`, the pair that distinguishes AVPs on the wire."""
        return (self.vendor_id, self.code)


# `Avp` field names, as `Hole.missing` spells them.
CODE = "code"
DATA_TYPE = "data_type"
FLAG_RULES = "flag_rules"
# A name nothing in the corpus defines, tabulates or can be followed to.
DEFINITION = "definition"


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
    # `CODE`, `DATA_TYPE`, `FLAG_RULES`, or `DEFINITION` alone.
    missing: tuple[str, ...]
    vendor_id: int | None = None
    code: int | None = None
    data_type: ast.DataType | None = None
    flag_rules: ast.AvpFlagRules | None = None
    section: str | None = None
    # The re-used origin the corpus holds no copy of, when one is cited:
    # TS 29.212's `3GPP2-BSID` from 3GPP2 X.S0057.
    origin: str | None = None
    # The document whose reading states a missing field but disagrees with
    # this one on a field both state, so nothing was taken from it or from
    # any reading after it.
    conflict: str | None = None
    wireshark_name: str | None = None

    def __str__(self) -> str:
        if self.missing == (DEFINITION,):
            what = "resolves nowhere"
        else:
            what = "no " + ", no ".join(self.missing)
        if self.origin is not None:
            what += f" (re-used from {self.origin}, which the corpus lacks)"
        if self.conflict is not None:
            what += f"; {self.conflict}'s reading, which states it, disagrees"
        return f"{self.reference} {self.name}: {what}"


@dataclass(frozen=True)
class Member:
    """One line of an ABNF body, with the name resolved to an object."""

    rule: ast.AvpRule
    # None for the `* [ AVP ]` wildcard and for a name the corpus cannot
    # complete; `hole` says which of the two.
    avp: Avp | None
    hole: Hole | None = None

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


@dataclass(frozen=True)
class Enumerated(Avp):
    values: tuple[ast.EnumValue | ast.ReservedValues, ...] = ()
    # Where the defining clause says the values are defined instead, in its
    # words: TS 29.272's `Trace-Depth` takes "TS 32.422 [23] for Trace
    # Depth". With no values beside it that is the whole statement, not a
    # gap: the document defines the AVP and points elsewhere for the list.
    values_source: str | None = None


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
    # application block in scope states; None when neither says.
    application_id: int | None
    # "5a", or "A.7" for an annex: the leading clause component, with the
    # next one for an annex, whose letter alone spans several interfaces.
    clause: str
    messages: tuple[Message, ...]
    # The application block that states `application_id`, when one does:
    # its name for the application ("Gx") and the clause stating the id.
    name: str | None = None
    stated_in: str | None = None


def _stated(flag_rules: ast.AvpFlagRules) -> bool:
    """Whether a row's flag cells say anything. A table with no flag columns
    (RFC 4072, 4590, 5447, 5777 and 6734 print none) and a row with every
    flag cell blank (TS 32.299 table 7.2.0.1 for most re-printed rows) both
    parse to empty rules, and neither is a claim that no flag applies."""
    return bool(
        flag_rules.must
        or flag_rules.may
        or flag_rules.should_not
        or flag_rules.must_not
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
    vendor_id: int | None = None
    # False for a table row, whose vendor is the file's `; Vendor-ID:` rather
    # than anything the row prints.
    vendor_stated: bool = False
    code: int | None = None
    data_type: ast.DataType | None = None
    flag_rules: ast.AvpFlagRules | None = None
    section: str | None = None
    origin: str | None = None
    conflict: str | None = None
    wireshark_name: str | None = None
    members: tuple[Member, ...] = ()
    values: tuple[ast.EnumValue | ast.ReservedValues, ...] = ()
    values_source: str | None = None

    def fill(self, other: _Draft) -> _Draft:
        """This reading with what it leaves unstated taken from `other`, the
        next document along the resolution order, when the two are the same
        AVP saying the same thing.

        Every field both readings state must be equal: code, type, flag
        rules, and vendor where both state one. A table row's vendor is
        inferred from its file, so it agrees with any: TS 29.229's row for
        RFC 4590's `Digest-Realm` sits in vendor 10415's file, the origin's
        row in vendor 0's. A reading that disagrees fills nothing, and
        neither does any after it; the hole names it instead, since taking
        a `Time` row's missing flags from an `Unsigned32` reading would make
        one complete AVP out of two documents that disagree about it.
        """
        if self.kind is None:
            # Nothing here yet: any definition wins, and failing one, the
            # first unreadable origin stays the explanation.
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
        kind, members = self.kind, self.members
        values, values_source = self.values, self.values_source
        if self.data_type is None and other.kind is not Avp:
            # A row printing no type, for an AVP another document defines
            # as grouped or enumerated, takes the definition's body too.
            kind, members = other.kind, other.members
            values, values_source = other.values, other.values_source
        vendor_id, vendor_stated = self.vendor_id, self.vendor_stated
        if not vendor_stated and other.vendor_stated:
            vendor_id, vendor_stated = other.vendor_id, True
        return replace(
            self,
            kind=kind,
            members=members,
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

    @cached_property
    def final(self) -> Avp | Hole:
        if (
            self.kind is None
            or self.vendor_id is None
            or self.code is None
            or self.data_type is None
            or self.flag_rules is None
        ):
            missing = (
                (DEFINITION,)
                if self.kind is None
                else tuple(
                    name
                    for name, value in (
                        (CODE, self.code),
                        (DATA_TYPE, self.data_type),
                        (FLAG_RULES, self.flag_rules),
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
                flag_rules=self.flag_rules,
                section=self.section,
                origin=self.origin,
                conflict=self.conflict,
                wireshark_name=self.wireshark_name,
            )
        common = (
            self.name,
            self.vendor_id,
            self.code,
            self.data_type,
            self.flag_rules,
            self.reference,
            self.section,
            self.wireshark_name,
        )
        if self.kind is Grouped:
            return Grouped(*common, members=self.members)
        if self.kind is Enumerated:
            return Enumerated(
                *common, values=self.values, values_source=self.values_source
            )
        return Avp(*common)


@dataclass
class _View:
    """One specification's file, indexed the way resolution reads it."""

    entry: corpus.Entry
    defined: dict[str, ast.GroupedAvp | ast.EnumeratedAvp]
    # Every row per name, in file order. Resolution reads the first; the rest
    # are other tables' copies, which may disagree (`table-row-mismatch`).
    tabled: dict[str, list[ast.AvpTableRow]]
    reused: dict[str, str]
    messages: list[ast.Message]
    applications: list[ast.Application]

    @classmethod
    def index(cls, entry: corpus.Entry) -> _View:
        view = cls(entry, {}, {}, {}, [], [])
        for section in entry.spec.sections:
            if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
                view.defined.setdefault(section.name, section)
            elif isinstance(section, ast.AvpTable):
                for row in section.rows:
                    view.tabled.setdefault(row.name, []).append(row)
            elif isinstance(section, ast.ReusedAvps):
                for row in section.rows:
                    view.reused.setdefault(row.name, row.origin)
            elif isinstance(section, ast.Message):
                view.messages.append(section)
            elif isinstance(section, ast.Application):
                view.applications.append(section)
        return view


class Model:
    """The resolved corpus. Build it once with `Model.build`."""

    def __init__(
        self, books: corpus.Corpus, dictionary: oracle.Oracle | None = None
    ) -> None:
        self._books = books
        self._dictionary = dictionary
        # One view per reference: the corpus sorts candidates newest first,
        # so the first entry seen for a reference is the one every
        # reference-level query answers from — the same copy `; Bases:` and
        # re-used rows resolve to when the citing document is that version.
        self._views: dict[str, _View] = {}
        for entry in books:
            if entry.reference not in self._views:
                self._views[entry.reference] = _View.index(entry)
        # Memo of resolved readings, keyed by the view that reads the name.
        self._resolved: dict[tuple[str, str], _Draft | None] = {}

    @classmethod
    def build(
        cls,
        books: corpus.Corpus,
        *,
        strict: bool = False,
        dictionary: Path | None = None,
    ) -> Model:
        """The model over `books`.

        `strict` refuses a corpus with any hole, raising
        `IncompleteCorpusError` with all of them, so a consumer that needs
        every AVP complete learns at build time rather than from a missing
        member later. Off by default because the committed corpus has
        standing holes (docs/consumers.md); without it, a name with a hole
        resolves to no `Avp` and `holes` reports it.

        `dictionary` is a Wireshark dictionary directory (the downloader's
        `specifications/wireshark`); with one, every AVP and hole with an
        identity carries Wireshark's name for it in `wireshark_name`.
        Without one that field is None and nothing else changes.
        """
        loaded = None if dictionary is None else oracle.Oracle.load(dictionary)
        built = cls(books, loaded)
        if strict and (holes := built.holes()):
            raise IncompleteCorpusError(holes)
        return built

    def references(self) -> list[str]:
        """Every specification the model answers for, `TS29.229`-spelled."""
        return sorted(self._views)

    def _view(self, reference: str) -> _View:
        try:
            return self._views[reference]
        except KeyError:
            raise ModelError(f"the corpus holds no copy of {reference}") from None

    def messages(self, reference: str) -> tuple[Message, ...]:
        """Every command `reference` defines, bodies resolved."""
        view = self._view(reference)
        return tuple(
            Message(
                name=message.name,
                abbreviation=message.abbreviation,
                command_code=message.command_code,
                flags=message.flags,
                application_id=message.application_id,
                defined_in=view.entry.reference,
                section=message.source.section,
                avps=self._body(view, message.avps),
            )
            for message in view.messages
        )

    def applications(self, reference: str) -> tuple[Application, ...]:
        """`reference`'s commands, grouped by application id and the clause
        they sit under, in file order.

        A command whose header prints no id takes the one an application
        block in scope states (the first, where blocks overlap): TS 29.212's
        clause 5.1 gives the Gx commands 16777238, and RFC 5778's two blocks
        split its clause 5 between 7 and 8. A header that prints an id keeps
        it; the linter reports one that disagrees with its block.

        One group can still define a command twice: TS 29.273 prints the
        STa Session-Termination-Request in clauses 5.2.2.2.3 and 5.2.2.4.1,
        once per procedure. Which copy a consumer keeps is its business.
        """
        view = self._view(reference)
        groups: dict[tuple[int | None, str], list[Message]] = {}
        stating: dict[tuple[int | None, str], ast.Application] = {}
        for message in self.messages(reference):
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

    def resolve(self, reference: str, name: str) -> Avp | None:
        """`name` as `reference` means it, or None when the corpus cannot
        complete it — `hole` says why."""
        found = self._final(self._view(reference), name)
        return found if isinstance(found, Avp) else None

    def hole(self, reference: str, name: str) -> Hole | None:
        """What `reference`'s reading of `name` lacks, or None when it
        resolves completely."""
        found = self._final(self._view(reference), name)
        return found if isinstance(found, Hole) else None

    def holes(self, reference: str | None = None) -> tuple[Hole, ...]:
        """Every hole in `reference`'s reading, or in the whole corpus.

        A reading's holes are the names its dictionary view and its command
        and grouped bodies cannot complete. A hole belongs to the document
        that falls short, so TS 29.229's reading reports RFC 4590's untyped
        `Digest-*` rows only where TS 29.229's own table does not type them.
        Sorted by document and name.
        """
        references = self.references() if reference is None else [reference]
        found: dict[Hole, None] = {}
        for each in references:
            view = self._view(each)
            for name in self._names(each):
                hole = self.hole(each, name)
                if hole is not None:
                    found[hole] = None
            bodies = [message.avps for message in self.messages(each)]
            bodies += [
                avp.members
                for avp in self.avps(each)
                if isinstance(avp, Grouped) and avp.defined_in == each
            ]
            # A grouped definition with a hole is no `Grouped`, but its body
            # is still this document's to resolve.
            bodies += [
                self._body(view, definition.avps)
                for name, definition in view.defined.items()
                if isinstance(definition, ast.GroupedAvp)
                and self.hole(each, name) is not None
            ]
            for body in bodies:
                found.update(
                    (member.hole, None) for member in body if member.hole is not None
                )
        return tuple(sorted(found, key=lambda hole: (hole.reference, hole.name)))

    def table_rows(self, reference: str, name: str) -> tuple[ast.AvpTableRow, ...]:
        """Every AVP-table row `reference` prints for `name`, in file order.

        `resolve` takes its table facts from the first; a document that
        tabulates one AVP per interface may print the others differently
        (TS 29.061's `3GPP-IMSI` in tables 9a and 10), and this is where a
        consumer sees the alternatives the linter's `table-row-mismatch`
        reports.
        """
        return tuple(self._view(reference).tabled.get(name, ()))

    def find(self, name: str) -> tuple[Avp, ...]:
        """Every distinct AVP the corpus knows under `name`."""
        return self._by_name.get(name, ())

    def identified(self, vendor_id: int, code: int) -> tuple[Avp, ...]:
        """Every distinct AVP claiming `(vendor-id, code)`.

        More than one entry is the corpus disagreeing with itself — the
        linter's `duplicate-identity` — or two documents' differing copies of
        one AVP surviving deduplication because their bodies differ.
        """
        return self._by_identity.get((vendor_id, code), ())

    # --- resolution ---------------------------------------------------------

    def _names(self, reference: str) -> dict[str, None]:
        view = self._view(reference)
        return dict.fromkeys((*view.defined, *view.tabled, *view.reused))

    def _final(self, view: _View, name: str, stack: tuple = ()) -> Avp | Hole:
        draft = self._resolve(view, name, stack)
        if draft is None:
            return Hole(view.entry.reference, name, (DEFINITION,))
        return draft.final

    def _resolve(self, view: _View, name: str, stack: tuple) -> _Draft | None:
        key = (view.entry.reference, name)
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
        4590's RADIUS-derived `Digest-*` rows) takes it from the citing
        document's table. The first reading still names the defining
        document.
        """
        found: _Draft | None = None
        for reading in self._readings(view, name, stack):
            found = reading if found is None else found.fill(reading)
            if isinstance(found.final, Avp) or found.conflict is not None:
                break
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

    def _readings(self, view: _View, name: str, stack: tuple) -> Iterator[_Draft]:
        """Every document's reading of `name`, in resolution order, lazily:
        the local definition, the re-used origin, the local table row, the
        `; Bases:` documents."""
        rows = view.tabled.get(name)
        origin = view.reused.get(name)
        theirs = None if origin is None else self._cited(view, origin)
        unread = origin if theirs is None else None
        definition = view.defined.get(name)
        if definition is not None:
            yield self._from_definition(view, definition, rows, unread, stack)
        if theirs is not None and (found := self._resolve(theirs, name, stack)):
            yield found
        if rows is not None and definition is None:
            yield self._from_row(view, name, rows[0], unread)
        for base in view.entry.spec.bases:
            cited = self._cited(view, base)
            if cited is not None and (found := self._resolve(cited, name, stack)):
                yield found
        if unread is not None:
            yield _Draft(None, name, view.entry.reference, origin=unread)

    def _cited(self, view: _View, reference: str) -> _View | None:
        """The view `reference` names when cited from `view`, if the corpus
        holds a copy in the matching release."""
        entry = self._books.resolve(reference, like=view.entry.spec)
        return None if entry is None else self._views.get(entry.reference)

    def _from_row(
        self, view: _View, name: str, row: ast.AvpTableRow, unread: str | None
    ) -> _Draft:
        return _Draft(
            Avp,
            name,
            view.entry.reference,
            vendor_id=view.entry.spec.vendor_id,
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
            draft.members = self._body(view, definition.avps, stack)
        else:
            draft.data_type = ast.DataType.ENUMERATED
            draft.values = definition.values
            draft.values_source = definition.values_source
        return draft

    def _body(
        self, view: _View, rules: tuple[ast.AvpRule, ...], stack: tuple = ()
    ) -> tuple[Member, ...]:
        members = []
        for rule in rules:
            # `AVP` is RFC 6733's any-AVP wildcard — grammar, not a name.
            if rule.name == "AVP" or (view.entry.reference, rule.name) in stack:
                members.append(Member(rule=rule, avp=None))
                continue
            found = self._final(view, rule.name, stack)
            if isinstance(found, Avp):
                members.append(Member(rule=rule, avp=found))
            else:
                members.append(Member(rule=rule, avp=None, hole=found))
        return tuple(members)

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
