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

A name that resolves nowhere stays a name: `Member.avp` is `None` both for
an unresolved reference (the linter's `unresolved-reference` note lists
them) and for RFC 6733's `* [ AVP ]` wildcard, which is grammar rather than
a reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from . import corpus
from .dad import ast


class ModelError(ValueError):
    pass


@dataclass(frozen=True)
class Avp:
    """One resolved AVP, as the specification `defined_in` states it."""

    name: str
    vendor_id: int
    # A table row may print no code — TS 29.229's raw extraction tabulates
    # `Load` with `-`, which the linter's `row-without-code` rule reports —
    # and an AVP without one has no wire identity, only a name.
    code: int | None
    data_type: ast.DataType | None
    # Absent when the defining document never tabulates the AVP.
    flag_rules: ast.AvpFlagRules | None
    # The reference re-used rows cite: `TS29.229`, `RFC6733`.
    defined_in: str
    section: str | None

    @property
    def identity(self) -> tuple[int, int] | None:
        """`(vendor-id, code)`, the pair that distinguishes AVPs on the wire."""
        return None if self.code is None else (self.vendor_id, self.code)


@dataclass(frozen=True)
class Member:
    """One line of an ABNF body, with the name resolved to an object."""

    rule: ast.AvpRule
    # None for the `* [ AVP ]` wildcard and for a reference the corpus cannot
    # resolve — the two cases where a name is all there is.
    avp: Avp | None

    @property
    def name(self) -> str:
        return self.rule.name


@dataclass(frozen=True)
class Grouped(Avp):
    members: tuple[Member, ...] = ()


@dataclass(frozen=True)
class Enumerated(Avp):
    values: tuple[ast.EnumValue | ast.ReservedValues, ...] = ()


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


@dataclass
class _View:
    """One specification's file, indexed the way resolution reads it."""

    entry: corpus.Entry
    defined: dict[str, ast.GroupedAvp | ast.EnumeratedAvp]
    tabled: dict[str, ast.AvpTableRow]
    reused: dict[str, str]
    messages: list[ast.Message]

    @classmethod
    def index(cls, entry: corpus.Entry) -> _View:
        view = cls(entry, {}, {}, {}, [])
        for section in entry.spec.sections:
            if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
                view.defined.setdefault(section.name, section)
            elif isinstance(section, ast.AvpTable):
                for row in section.rows:
                    view.tabled.setdefault(row.name, row)
            elif isinstance(section, ast.ReusedAvps):
                for row in section.rows:
                    view.reused.setdefault(row.name, row.origin)
            elif isinstance(section, ast.Message):
                view.messages.append(section)
        return view


class Model:
    """The resolved corpus. Build it once with `Model.build`."""

    def __init__(self, books: corpus.Corpus) -> None:
        self._books = books
        # One view per reference: the corpus sorts candidates newest first,
        # so the first entry seen for a reference is the one every
        # reference-level query answers from — the same copy `; Bases:` and
        # re-used rows resolve to when the citing document is that version.
        self._views: dict[str, _View] = {}
        for entry in books:
            if entry.reference not in self._views:
                self._views[entry.reference] = _View.index(entry)
        # Memo of resolved AVPs, keyed by the view that defined the name.
        self._resolved: dict[tuple[str, str], Avp | None] = {}

    @classmethod
    def build(cls, books: corpus.Corpus) -> Model:
        return cls(books)

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

    def avps(self, reference: str) -> tuple[Avp, ...]:
        """Every AVP `reference` defines, tabulates or re-uses, resolved.

        This is the specification's dictionary view: a re-printed or re-used
        AVP appears with the origin's `defined_in`, so a consumer that wants
        only the document's own AVPs filters on that field.
        """
        view = self._view(reference)
        names = dict.fromkeys((*view.defined, *view.tabled, *view.reused))
        found = (self.resolve(reference, name) for name in names)
        return tuple(avp for avp in found if avp is not None)

    def resolve(self, reference: str, name: str) -> Avp | None:
        """`name` as `reference` means it, or None when it resolves nowhere."""
        return self._resolve(self._view(reference), name, ())

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

    def _resolve(self, view: _View, name: str, stack: tuple) -> Avp | None:
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

    def _resolve_here(self, view: _View, name: str, stack: tuple) -> Avp | None:
        definition = view.defined.get(name)
        if definition is not None:
            return self._from_definition(view, definition, stack)
        origin = view.reused.get(name)
        if origin is not None:
            entry = self._books.resolve(origin, like=view.entry.spec)
            if entry is not None:
                theirs = self._views.get(entry.reference)
                if theirs is not None:
                    resolved = self._resolve(theirs, name, stack)
                    if resolved is not None:
                        return resolved
        row = view.tabled.get(name)
        if row is not None:
            return Avp(
                name=name,
                vendor_id=view.entry.spec.vendor_id,
                code=row.code,
                data_type=row.data_type,
                flag_rules=row.flag_rules,
                defined_in=view.entry.reference,
                section=row.section,
            )
        for base in view.entry.spec.bases:
            entry = self._books.resolve(base, like=view.entry.spec)
            if entry is None:
                continue
            theirs = self._views.get(entry.reference)
            if theirs is None:
                continue
            resolved = self._resolve(theirs, name, stack)
            if resolved is not None:
                return resolved
        return None

    def _from_definition(
        self,
        view: _View,
        definition: ast.GroupedAvp | ast.EnumeratedAvp,
        stack: tuple,
    ) -> Avp:
        row = view.tabled.get(definition.name)
        common = {
            "name": definition.name,
            # A definition written with no vendor-id is IETF-space; the wire
            # format calls that vendor 0.
            "vendor_id": (
                ast.IETF_VENDOR
                if definition.vendor_id is None
                else definition.vendor_id
            ),
            "code": definition.code,
            "flag_rules": None if row is None else row.flag_rules,
            "defined_in": view.entry.reference,
            "section": definition.source.section,
        }
        if isinstance(definition, ast.GroupedAvp):
            return Grouped(
                **common,
                data_type=ast.DataType.GROUPED,
                members=self._body(view, definition.avps, stack),
            )
        return Enumerated(
            **common,
            data_type=ast.DataType.ENUMERATED,
            values=definition.values,
        )

    def _body(
        self, view: _View, rules: tuple[ast.AvpRule, ...], stack: tuple = ()
    ) -> tuple[Member, ...]:
        return tuple(
            Member(
                rule=rule,
                # `AVP` is RFC 6733's any-AVP wildcard — grammar, not a name.
                avp=(
                    None
                    if rule.name == "AVP"
                    else self._resolve(view, rule.name, stack)
                ),
            )
            for rule in rules
        )

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
            if avp.identity is not None:
                table.setdefault(avp.identity, []).append(avp)
        return {identity: tuple(avps) for identity, avps in table.items()}
