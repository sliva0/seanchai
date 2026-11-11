"""`Model`: the resolved corpus, its constructors and its queries.
Resolution itself lives in `_Resolver`, its base."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import replace
from functools import cached_property
from pathlib import Path

from .. import corpus, oracle
from ..dad import ast
from ._errors import IncompleteCorpusError, ModelError, StaleHoleRecordError
from ._resolution import _Resolver
from ._types import (
    Alias,
    Allocation,
    AnswerMessage,
    Application,
    Avp,
    Grouped,
    Hole,
    HolePolicy,
    Marks,
    Member,
    Message,
    Placeholder,
    Supplied,
    SupplyKey,
    Undefined,
    UndefinedPolicy,
    ValueTable,
)
from ._view import _effective_id, _generation, _scope, _View


def _reached_across(avp: Avp | Hole) -> Iterator[Avp | Hole]:
    """The members, at any depth, of a grouped AVP reached across releases
    that themselves took a field across releases."""
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


class Model(_Resolver):
    """The resolved corpus. Build it with `Model.build` or
    `Model.installed`, which run the hole and supply checks; `Model(...)`
    raises `TypeError`."""

    def __init__(self) -> None:
        raise TypeError("build a Model with Model.build(corpus) or Model.installed()")

    @classmethod
    def _unchecked(
        cls,
        books: corpus.Corpus,
        wireshark: oracle.Oracle | None = None,
        undefined: UndefinedPolicy = UndefinedPolicy.HOLE,
        supply: Mapping[SupplyKey, Supplied | Alias] | None = None,
    ) -> Model:
        """The model over `books` with none of `build`'s checks."""
        built = cls.__new__(cls)
        built._index(books, wireshark, UndefinedPolicy(undefined), supply)
        return built

    @classmethod
    def build(
        cls,
        books: corpus.Corpus,
        *,
        holes: HolePolicy = HolePolicy.RECORDED,
        wireshark: str | os.PathLike[str] | None = None,
        undefined: UndefinedPolicy = UndefinedPolicy.HOLE,
        supply: Mapping[SupplyKey, Supplied | Alias] | None = None,
    ) -> Model:
        """Build the model over `books`.

        `holes` (`HolePolicy`) sets which holes are allowed. `RECORDED`, the
        default, checks the corpus's record of known holes
        (`corpus.Corpus.record`): an unlisted hole raises
        `IncompleteCorpusError`, and an entry naming no hole raises
        `StaleHoleRecordError` unless `undefined` answered for it. A corpus
        with no record has no known holes. `NONE` refuses every hole; `ANY`
        allows all.

        `wireshark` is a Wireshark Diameter dictionary directory; with it,
        AVPs and holes with an identity get `wireshark_name`. An unreadable
        one raises `ModelError`.

        `undefined` (`UndefinedPolicy`) says what to do with names `Undefined
        AVP` blocks declare. `supply` holds `SUPPLY`'s answers, `Supplied` or
        `Alias`, keyed by name or by `(reference, name)`, which wins. It is
        required with `SUPPLY` and refused otherwise. `ModelError` is raised
        for a key naming no block, a `Supplied` claiming an identity the
        corpus or another `Supplied` holds, and a cycle of `Alias`es.

        See docs/consumers.md.
        """
        allowed = HolePolicy(holes)
        policy = UndefinedPolicy(undefined)
        if policy is UndefinedPolicy.SUPPLY and supply is None:
            raise ModelError("undefined=SUPPLY needs supply=")
        if policy is not UndefinedPolicy.SUPPLY and supply is not None:
            raise ModelError(
                f"supply= is read only with undefined=SUPPLY, not {policy}"
            )
        try:
            loaded = None if wireshark is None else oracle.Oracle.load(wireshark)
        except (ValueError, LookupError) as error:
            # An `OracleError`, or a dictionary whose XML parses but lacks an
            # attribute or holds no number where the wire format needs one.
            raise ModelError(
                f"cannot read the Wireshark dictionary at {wireshark}: {error!r}"
            ) from error
        built = cls._unchecked(books, loaded, policy, supply)
        built._check_supply()
        if allowed is HolePolicy.RECORDED:
            if unrecorded := built.unrecorded_holes():
                raise IncompleteCorpusError(unrecorded, unrecorded=True)
            if stale := built.stale_record_entries():
                raise StaleHoleRecordError(stale)
        elif allowed is HolePolicy.NONE and (found := built.holes()):
            raise IncompleteCorpusError(found)
        return built

    @classmethod
    def installed(
        cls,
        *,
        holes: HolePolicy = HolePolicy.RECORDED,
        wireshark: str | os.PathLike[str] | None = None,
        undefined: UndefinedPolicy = UndefinedPolicy.HOLE,
        supply: Mapping[SupplyKey, Supplied | Alias] | None = None,
    ) -> Model:
        """`build` over the installed corpus (`corpus.Corpus.installed`)."""
        return cls.build(
            corpus.Corpus.installed(),
            holes=holes,
            wireshark=wireshark,
            undefined=undefined,
            supply=supply,
        )

    @property
    def undefined_policy(self) -> UndefinedPolicy:
        """The policy for names `Undefined AVP` blocks declare."""
        return self._policy

    def _check_supply(self) -> None:
        """Check that every key names a block, every `Supplied` fits its type
        and claims no defined identity, and every `Alias` names a complete
        AVP."""
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
                for avp in self.readings((answer.vendor_id, answer.code))
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

    def _chosen(self, reference: str | None) -> tuple[str, ...]:
        """The references a query over `reference`, or over the corpus, reads."""
        return self.references() if reference is None else (self.canonical(reference),)

    def messages(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[Message, ...]:
        """Every command `reference` (or the corpus) defines, bodies resolved.
        `version` selects an older held copy of `reference`."""
        return tuple(
            message
            for view in self._selected_views(reference, version)
            for message in self._messages_of(view)
        )

    def _selected_views(
        self, reference: str | None, version: str | None
    ) -> tuple[_View, ...]:
        """The views a query over `reference`, or over the corpus, reads."""
        if reference is not None:
            return (self._view(reference, version),)
        if version is not None:
            raise ModelError(f"version={version!r} reads one document: name it")
        return tuple(self._view(each) for each in self.references())

    def _messages_of(self, view: _View) -> tuple[Message, ...]:
        return tuple(
            Message(
                name=message.name,
                abbreviation=message.abbreviation,
                command_code=message.command_code,
                flags=message.flags,
                application_id=_effective_id(message, _scope(view, message)),
                header_application_id=message.application_id,
                defined_in=view.entry.reference,
                section=message.source.section,
                avps=avps,
                dropped=dropped,
            )
            for message in view.messages
            for avps, dropped in [self._split(self._body(view, message.avps))]
        )

    def answer_message(
        self, reference: str, *, version: str | None = None
    ) -> AnswerMessage | None:
        """The `<answer-message>` that `reference`'s answers with the E bit set
        take: the document's first, else the first from its `; Bases:`
        documents, depth first. The body is read through `reference`. None if
        no document prints one. `version` selects an older held copy."""
        view = self._view(reference, version)
        found = self._answering(view, ())
        if found is None:
            return None
        printing, block = found
        avps, dropped = self._split(self._body(view, block.avps))
        return AnswerMessage(
            defined_in=printing.entry.reference,
            section=block.source.section,
            read_through=view.entry.reference,
            avps=avps,
            dropped=dropped,
        )

    def _answering(
        self, view: _View, seen: tuple[Path, ...]
    ) -> tuple[_View, ast.AnswerMessage] | None:
        """The document printing the `<answer-message>` `view` takes, and
        the rule."""
        if view.answers:
            return view, view.answers[0]
        for base in view.entry.spec.bases:
            cited, _ = self._cited(view, base)
            if cited is None or cited.entry.path in seen:
                continue
            if found := self._answering(cited, (*seen, view.entry.path)):
                return found
        return None

    def undefined(self, reference: str | None = None) -> tuple[Undefined, ...]:
        """Every `Undefined AVP` block in `reference` (or the corpus), in file
        order, under any policy."""
        references = self._chosen(reference)
        return tuple(
            self._undefined_of(view, block)
            for each in references
            for view in [self._view(each)]
            for block in view.undefined.values()
        )

    def placeholders(self, reference: str | None = None) -> tuple[Placeholder, ...]:
        """Every placeholder in `reference`'s reading (or the corpus's), found
        as `holes` finds holes, sorted by document and name. Empty unless
        built with `UndefinedPolicy.PLACEHOLDER`."""
        if self._policy is not UndefinedPolicy.PLACEHOLDER:
            return ()
        references = self._chosen(reference)
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
        self,
        reference: str | None = None,
        *,
        application_id: int | None = None,
        version: str | None = None,
    ) -> tuple[Application, ...]:
        """`reference`'s (or the corpus's) commands grouped by application id
        and clause, in file order. `application_id` keeps only that id's
        groups; `version` selects an older held copy.

        A command whose header prints no id takes it from the first
        `Application Scope` block covering its clause. A group may hold the
        same command twice, as the document prints it.
        """
        return tuple(
            application
            for view in self._selected_views(reference, version)
            for application in self._applications_of(view)
            if application_id is None or application.application_id == application_id
        )

    def _applications_of(self, view: _View) -> tuple[Application, ...]:
        groups: dict[tuple[int | None, str], list[Message]] = {}
        stating: dict[tuple[int | None, str], ast.ApplicationScope] = {}
        for message, printed in zip(
            self._messages_of(view), view.messages, strict=True
        ):
            block = _scope(view, printed)
            key = (message.application_id, ast.interface_clause(message.section))
            groups.setdefault(key, []).append(message)
            if block is not None and block.application_id == message.application_id:
                stating.setdefault(key, block)
        return tuple(
            Application(
                view.entry.reference,
                application_id,
                clause,
                tuple(messages),
                name=None if block is None else block.name,
                stated_in=None if block is None else block.source.section,
            )
            for (application_id, clause), messages in groups.items()
            for block in [stating.get((application_id, clause))]
        )

    def avps(self, reference: str | None = None) -> tuple[Avp, ...]:
        """Every AVP `reference` defines, tabulates or re-uses, resolved, or
        every distinct reading in the corpus; sorted by defining document and
        name.

        Re-used AVPs keep the origin's `defined_in`. Names with a hole are
        left out (see `holes`). Without `reference`, AVPs only an older copy
        holds are included where a citation reaches them.

        This lists what the tables say, not what the commands use; for a
        dictionary generator use `Application.walk` or `Message.walk`.
        """
        if reference is None:
            return tuple(
                sorted(self._everything, key=lambda avp: (avp.defined_in, avp.name))
            )
        return self._avps_of(self.canonical(reference))

    def _avps_of(self, reference: str) -> tuple[Avp, ...]:
        found = (self.resolve(reference, name) for name in self._names(reference))
        return tuple(avp for avp in found if avp is not None)

    def resolve(
        self, reference: str, name: str, *, version: str | None = None
    ) -> Avp | None:
        """`name` as `reference` means it. None if it is a hole (see `hole`)
        or an undefined name the policy drops or keeps untyped."""
        found = self._final(self._view(reference, version), name)
        return found if isinstance(found, Avp) else None

    def hole(
        self, reference: str, name: str, *, version: str | None = None
    ) -> Hole | None:
        """The hole in `reference`'s reading of `name`, or None if it resolves
        or the policy answers for it."""
        found = self._final(self._view(reference, version), name)
        return found if isinstance(found, Hole) and self._open(found) else None

    def _open(self, hole: Hole) -> bool:
        """Whether a hole stays one under the policy, i.e. is not an undefined
        name the policy drops or keeps as a placeholder."""
        return hole.undefined is None or self._policy in (
            UndefinedPolicy.HOLE,
            UndefinedPolicy.SUPPLY,
        )

    def holes(self, reference: str | None = None) -> tuple[Hole, ...]:
        """Every hole in `reference`'s reading (or the corpus's), sorted by
        document and name.

        This covers names its tables and bodies cannot complete, plus holes
        in older copies reached across releases, which carry that copy's
        `version`. A hole belongs to the document that falls short.
        """
        references = self._chosen(reference)
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
        """Every hole the record of known holes does not list with the same
        missing fields."""
        return tuple(hole for hole in self.holes() if hole.recorded is None)

    def stale_record_entries(self) -> tuple[corpus.KnownHole, ...]:
        """Every record entry that names no hole in the corpus's own reading.
        An entry unused only because `undefined` answered for it is not
        stale."""
        present = {(hole.document, hole.name) for hole in self.holes()}
        unanswered = (
            self
            if self._policy is UndefinedPolicy.HOLE
            else Model._unchecked(self._books)
        ).holes()
        listed = {(hole.document, hole.name, hole.missing) for hole in unanswered}
        return tuple(
            entry
            for key, entry in self._known.items()
            if key not in present and (*key, entry.missing) not in listed
        )

    def _bodies(self, reference: str) -> list[tuple[Member, ...]]:
        """`reference`'s resolved command and grouped bodies, minus dropped
        members."""
        view = self._view(reference)
        bodies = [message.avps for message in self.messages(reference)]
        if view.answers and (answer := self.answer_message(reference)) is not None:
            bodies.append(answer.avps)
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
        """Holes of older copies inside grouped AVPs `reference` reaches
        across releases, at any depth. Reference-level queries read only the
        newest copies, so nothing else reports these. Holes in a newest copy
        are left to that copy's own reading."""
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
        """Every name in `reference`'s reading (or the corpus's) that took a
        field from outside the citing document's release, each with its
        `corpus.CrossRelease`, sorted by citing document and name.

        Includes, at any depth, what older copies reached this way cite
        across releases in turn. See docs/consumers.md."""
        references = self._chosen(reference)
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
        `resolve` reads the first; later rows may differ
        (`table-row-mismatch`).
        """
        return tuple(self._view(reference).tabled.get(name, ()))

    def marks(self, reference: str, name: str) -> tuple[Marks, ...]:
        """`name`'s marks in `reference`, one per row of an AVP or re-used
        table with mark columns, in file order. For one interface, keep the
        rows whose `section` lies in its clause.
        """
        return tuple(self._view(reference).marked.get(name, ()))

    def registry(
        self, kind: ast.RegistryKind, code: int | None = None
    ) -> tuple[Allocation, ...]:
        """The registry rows and reserved ranges for `kind`, in file order;
        with `code`, only those covering it. No other query reads them.
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

    def value_tables(
        self,
        reference: str | None = None,
        *,
        avp: str | None = None,
        kind: ast.ValueKind | None = None,
        version: str | None = None,
    ) -> tuple[ValueTable, ...]:
        """The value tables `reference` (or the corpus) prints, in file order,
        optionally of one AVP or kind. `version` selects an older held
        copy."""
        return tuple(
            table
            for view in self._selected_views(reference, version)
            for table in view.value_tables
            if (avp is None or table.avp == avp)
            and (kind is None or table.kind is kind)
        )

    def feature_lists(
        self, reference: str | None = None
    ) -> dict[tuple[str, int | None], ValueTable]:
        """Feature tables keyed by (application as captioned, Feature-List-ID),
        e.g. `("S6a/S6d", 1)` or `("S6t", None)`. Tables naming no application
        are only in `value_tables`. If two documents print one list, the
        first in reference order wins."""
        found: dict[tuple[str, int | None], ValueTable] = {}
        for table in self.value_tables(reference, kind=ast.ValueKind.FEATURES):
            if table.application is not None:
                found.setdefault((table.application, table.feature_list_id), table)
        return found

    def readings(self, name_or_identity: str | tuple[int, int]) -> tuple[Avp, ...]:
        """Every distinct reading under a name or `(vendor-id, code)`.
        `Avp.read_through` says which table gives each; `definition` picks
        one.

        Several readings mean the corpus disagrees with itself
        (`duplicate-identity`), or copies differ in body or in flag rules a
        citing table sets.
        """
        if isinstance(name_or_identity, str):
            return self._by_name.get(name_or_identity, ())
        vendor_id, code = name_or_identity
        return self._by_identity.get((vendor_id, code), ())

    def definition(self, name_or_identity: str | tuple[int, int]) -> Avp | None:
        """The defining document's reading of a name or `(vendor-id, code)`,
        or None if no reading is complete.

        Among the readings' `defined_in` documents it prefers one that does
        not itself re-use the name, then the newest, then the one most
        readings name. A name two AVPs claim raises `ModelError`; ask by
        identity instead.
        """
        readings = self.readings(name_or_identity)
        if isinstance(name_or_identity, str):
            identities = sorted({avp.identity for avp in readings})
            if len(identities) > 1:
                raise ModelError(
                    f"{name_or_identity} names {len(identities)} AVPs,"
                    f" {', '.join(map(str, identities))}: ask for one of them"
                )
        if not readings:
            return None
        identity = readings[0].identity
        name = readings[0].name
        document = max(
            {avp.defined_in for avp in readings},
            key=lambda each: (
                # TS 29.212's Gxx tables cite TS 29.212 itself, which is no re-use.
                self._views[each].reused.get(name, each) == each,
                _generation(self._views[each].entry.spec),
                self._citations[identity, each],
                each,
            ),
        )
        ours = [avp for avp in readings if avp.defined_in == document]
        own = self.resolve(document, ours[0].name)
        if own is not None and (own.identity, own.defined_in) == (identity, document):
            return own
        # An older copy's definition, or a name the newest copy reads otherwise.
        return next((avp for avp in ours if avp.read_through == document), ours[0])

    # --- corpus-wide lookup -------------------------------------------------

    @cached_property
    def _everything(self) -> list[Avp]:
        found: dict[Avp, None] = {}
        for reference in self._views:
            found.update(dict.fromkeys(self._avps_of(reference)))
        known = {avp.identity for avp in found}
        found.update(
            (avp, None) for avp in self._reached(found) if avp.identity not in known
        )
        return [self._as_read_through(avp) for avp in found]

    def _as_read_through(self, avp: Avp) -> Avp:
        """`avp` with the value tables of the document it is read through.

        Equal readings are one, and the first met stands for them; its
        tables are those of whichever document resolved it first. TS 32.299
        reads RFC 6733's `Result-Code` with its own codes; the reading names
        RFC 6733, so it carries RFC 6733's.
        """
        view = self._by_document.get(avp.read_through)
        own = None if view is None else self._final(view, avp.name)
        if not isinstance(own, Avp) or own.value_tables == avp.value_tables:
            return avp
        return replace(avp, value_tables=own.value_tables)

    @cached_property
    def _by_document(self) -> dict[str, _View]:
        """Every copy by its document spelling, as `Avp.read_through`."""
        return {self._document(view): view for view in self._copies.values()}

    def _reached(self, avps: Iterable[Avp]) -> dict[Avp, None]:
        """Every reading `avps` and the newest copies' commands hold, at any
        depth, including AVPs only an older copy defines."""
        reached: dict[Avp, None] = {}
        pending = [
            *avps,
            *(
                member.avp
                for view in self._views.values()
                for message in self._messages_of(view)
                for member in (*message.avps, *message.dropped)
                if member.avp is not None
            ),
        ]
        while pending:
            avp = pending.pop()
            if avp in reached:
                continue
            reached[avp] = None
            if isinstance(avp, Grouped):
                pending.extend(
                    member.avp
                    for member in (*avp.members, *avp.dropped)
                    if member.avp is not None
                )
        return reached

    @cached_property
    def _citations(self) -> Counter[tuple[tuple[int, int], str]]:
        """How many documents read each identity as each `defined_in`."""
        return Counter(
            (avp.identity, avp.defined_in)
            for reference in self._views
            for avp in self._avps_of(reference)
        )

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
