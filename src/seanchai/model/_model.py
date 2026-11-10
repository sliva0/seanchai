"""`Model`, the resolved corpus: its constructors, which hold a build to
the corpus's record of known holes and check the consumer's answers, and the
queries a consumer asks of it. How a name resolves is `_Resolver`'s, its
base."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
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


class Model(_Resolver):
    """The resolved corpus. Build it once with `Model.build`, or
    `Model.installed` over the installed corpus: they are its only
    constructors, since they hold the build to the corpus's record of known
    holes and check the consumer's answers, and `Model(...)` raises
    `TypeError`."""

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
        """The model over `books`.

        `holes` says which holes the build allows (`HolePolicy`). By default,
        `RECORDED`, it holds the corpus to its record of known holes
        (`corpus.Corpus.record`, docs/consumers.md): a hole the record does
        not list raises `IncompleteCorpusError` with all such, and an entry
        naming no hole raises `StaleHoleRecordError`, unless the entry is an
        undefined name `undefined` answered for. A corpus with no record has
        no known holes. A recorded hole stays one: the name resolves to no
        `Avp`, `holes` reports it and `Hole.recorded` says why it stands.

        `NONE` refuses every hole, recorded or not, so a consumer that needs
        every AVP complete learns at build time rather than from a missing
        member later; what it guarantees is that every member is an `Avp`,
        the wildcard, or what `undefined` asked for. `ANY` holds the corpus
        to nothing, for a partial or foreign one.

        `wireshark` is a Wireshark Diameter dictionary directory (the
        downloader's `specifications/wireshark`); with one, every AVP and hole
        with an identity carries Wireshark's name for it in `wireshark_name`.
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
        """The model over the installed corpus (`corpus.Corpus.installed`), as
        `build` builds one."""
        return cls.build(
            corpus.Corpus.installed(),
            holes=holes,
            wireshark=wireshark,
            undefined=undefined,
            supply=supply,
        )

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
        """Every command `reference` defines, or the whole corpus does, bodies
        resolved; `version` reads an older copy of `reference` the corpus
        holds."""
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
        """The format the answers of `reference`'s commands take when the E bit
        is set: the first `<answer-message>` the document prints, or failing
        one, the first its `; Bases:` documents give, depth first in the order
        they are listed. The body is read through `reference`, as its commands'
        bodies are. None where no document along the way prints one; `version`
        reads an older copy of `reference` the corpus holds."""
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
        """The document printing the `<answer-message>` `view` takes, and the
        rule."""
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
        """Every `Undefined AVP` block in `reference`, or in the corpus,
        under any policy, in file order."""
        references = self._chosen(reference)
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
        """`reference`'s commands, or the whole corpus's, grouped by
        application id and the clause they sit under, in file order;
        `application_id` keeps the groups of that id.

        A command whose header prints no id takes the one an `Application
        Scope` block covering its clause states (the first, where scopes
        overlap): TS 29.212's clause 5.1 gives the Gx commands of `5.*`
        16777238, and RFC 5778's two blocks split its clause 5 between 7 and
        8. A header that prints an id keeps it; the linter reports one that
        disagrees with its block.

        One group can still define a command twice: TS 29.273 prints the
        STa Session-Termination-Request in clauses 5.2.2.2.3 and 5.2.2.4.1,
        once per procedure. Which copy a consumer keeps is its business.

        `version` reads an older copy of `reference` the corpus holds.
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
        with no `reference` every distinct reading in the corpus, sorted by
        defining document and name.

        A re-printed or re-used AVP appears with the origin's `defined_in`, so
        a consumer that wants only the document's own AVPs filters on that
        field. A name with a hole is left out; `holes` lists it. With no
        `reference`, an identity only an older copy holds counts too, where a
        citation reaches it.

        This is what a document's tables say, not what its commands use: an
        AVP a body names that no table lists, as most of RFC 6733's in TS
        29.229's commands, is missing here. `Application.walk` and
        `Message.walk` are what a dictionary generator wants.
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
        """The command and grouped bodies `reference` defines, resolved,
        without what the policy dropped."""
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
        whose `Server-Capabilities` is TS 29.229 V19.1.0's, standing in.
        Sorted by citing document and name."""
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

    def value_tables(
        self,
        reference: str | None = None,
        *,
        avp: str | None = None,
        kind: ast.ValueKind | None = None,
        version: str | None = None,
    ) -> tuple[ValueTable, ...]:
        """The value tables `reference` prints, or the whole corpus does, in
        file order, of one AVP or one kind; `version` reads an older copy of
        `reference` the corpus holds. TS 29.336 prints its result codes once per
        interface, and each is a table."""
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
        """The feature tables naming an application, by that application as the
        caption spells it and the Feature-List-ID: `("S6a/S6d", 1)`,
        `("S6t", None)` for TS 29.336's, which numbers none. A table naming no
        application is left to `value_tables` (TS 29.368's
        `Feature-Supported-In-Final-Target`), and of two documents printing one
        list the first in reference order answers."""
        found: dict[tuple[str, int | None], ValueTable] = {}
        for table in self.value_tables(reference, kind=ast.ValueKind.FEATURES):
            if table.application is not None:
                found.setdefault((table.application, table.feature_list_id), table)
        return found

    def readings(self, name_or_identity: str | tuple[int, int]) -> tuple[Avp, ...]:
        """Every distinct reading the corpus holds under a name or claiming a
        `(vendor-id, code)`: a citing document's table may read another's AVP
        differently, and `Avp.read_through` says whose table gives which.
        `definition` is the one reading to take.

        More than one identity under a name, or more than one name on an
        identity, is the corpus disagreeing with itself (the linter's
        `duplicate-identity`), or two documents' differing copies of one AVP
        surviving deduplication because their bodies differ, or because a
        citing document's table sets its own flag rules: RFC 4590's code 110
        is `Digest-Qop` M in May and, through TS 29.229, M in Must.
        """
        if isinstance(name_or_identity, str):
            return self._by_name.get(name_or_identity, ())
        vendor_id, code = name_or_identity
        return self._by_identity.get((vendor_id, code), ())

    def definition(self, name_or_identity: str | tuple[int, int]) -> Avp | None:
        """The defining document's reading of a name or a `(vendor-id, code)`,
        None when the corpus completes no reading of it.

        Documents print each other's AVPs and succeed each other: TS 29.272
        extends TS 29.212's `Allocation-Retention-Priority`, TS 29.212 succeeds
        TS 29.210, RFC 8506 RFC 4006. So the defining document is, among those
        readings say `defined_in`, one that does not itself re-use the name
        from elsewhere, then the newest (latest release, or higher RFC number),
        then the one most documents' readings name. A name two AVPs claim
        (`Originator` is TS 32.299's and oneM2M's) raises `ModelError` listing
        them: the identity is the way to ask.
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
        return list(found)

    def _reached(self, avps: Iterable[Avp]) -> dict[Avp, None]:
        """Every reading `avps` and the newest copies' commands hold at any
        depth. A citation can reach an AVP only an older copy defines: oneM2M
        TS-0004's Service-Information is TS 32.299 V11.20.0's, whose
        WLAN-Information later releases removed."""
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
