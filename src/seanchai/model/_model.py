"""`Model`: the resolved corpus, its constructors and its queries.
Resolution itself lives in `_Resolver`, its base."""

from __future__ import annotations

import contextlib
import os
import re
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
    Constraint,
    Element,
    ElementTable,
    Grouped,
    Hole,
    HolePolicy,
    Marks,
    Member,
    MemberPath,
    Message,
    Met,
    Placeholder,
    Reached,
    ResultCode,
    ResultCodeTable,
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


def _member_constraints(avp: Avp) -> tuple[Constraint, ...]:
    return avp.member_constraints if isinstance(avp, Grouped) else ()


def _by_citing_document(found: Avp | Hole) -> tuple[str, str]:
    across = found.across_releases
    return ("" if across is None else across.citing, found.name)


def _by_defining_document(avp: Avp) -> tuple[str, str, str, str]:
    return (avp.defined_in, avp.name, avp.version or "", avp.read_through)


def _application_key(
    application: Application,
) -> tuple[str, str | None, int | None, str]:
    """What tells one application from another, without comparing bodies."""
    return (
        application.reference,
        application.version,
        application.application_id,
        application.clause,
    )


# A registry's or caption's name for an interface, after its publisher:
# "3GPP S6a", "3GPP T6a/T6b".
_PUBLISHER = re.compile(r"^(?:3GPP2?|ETSI|oneM2M)\s+", re.IGNORECASE)


def _components(name: str) -> frozenset[str]:
    """The interfaces a name lists: "S6a/S6d" is S6a and S6d, "3GPP Cx/Px" Cx
    and Px, folded for comparison."""
    return frozenset(
        part.strip().casefold()
        for part in _PUBLISHER.sub("", name.strip()).split("/")
        if part.strip()
    )


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
        release: int | None = None,
    ) -> Model:
        """Build the model over `books`.

        `release` is the 3GPP release the corpus holds whole to read
        (`corpus.Corpus.at`): its copy of each document answers every
        reference-level query. None reads the release `books` is viewed at,
        by default its newest. A release held only in part raises
        `corpus.CorpusError`.

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
        if release is not None:
            books = books.at(release)
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
        release: int | None = None,
    ) -> Model:
        """`build` over the installed corpus (`corpus.Corpus.installed`)."""
        return cls.build(
            corpus.Corpus.installed(),
            holes=holes,
            wireshark=wireshark,
            undefined=undefined,
            supply=supply,
            release=release,
        )

    @property
    def release(self) -> int | None:
        """The 3GPP release the model reads, the one its corpus holds whole
        and is viewed at; None for a corpus stating none."""
        return self._books.release

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

    def obsoletes(self, reference: str) -> tuple[str, ...]:
        """The documents `reference`'s header says it obsoletes, held or not:
        `("RFC4005",)` for RFC 7155."""
        return self._view(reference).entry.spec.obsoletes

    def obsoleted_by(self, reference: str) -> tuple[str, ...]:
        """The documents of the corpus whose headers obsolete `reference`, in
        reference order: `("RFC7155",)` for RFC 4005. `reference` itself need
        not be held."""
        with contextlib.suppress(ModelError):
            reference = self.canonical(reference)
        return tuple(
            each
            for each in self.references()
            if reference in self._view(each).entry.spec.obsoletes
        )

    def version(self, reference: str) -> str | None:
        """The version of the copy of `reference` that reference-level queries
        read, its newest; None for a document printing none, as an RFC."""
        return self._view(reference).entry.spec.version

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
        return tuple(self._message_of(view, message) for message in view.messages)

    def _message_of(self, view: _View, message: ast.Message) -> Message:
        avps, dropped = self._split(self._body(view, message.avps))
        elements = tuple(
            element
            for printing, block in self._described.get(id(message), ())
            for element in self._rows_of(printing, block)
        )
        return Message(
            name=message.name,
            abbreviation=message.abbreviation,
            command_code=message.command_code,
            flags=message.flags,
            application_id=_effective_id(message, _scope(view, message)),
            header_application_id=message.application_id,
            defined_in=view.entry.reference,
            section=message.source.section,
            avps=tuple(
                replace(member, elements=mapping)
                if (
                    mapping := tuple(
                        element
                        for element in elements
                        if element.within is None
                        and not element.parents
                        and member.name in element.avps
                    )
                )
                else member
                for member in avps
            ),
            dropped=dropped,
            version=self._older(view),
            elements=elements,
            constraints=self._command_constraints(view, message),
            result_codes=tuple(
                code
                for printing, block in self._listed.get(id(message), ())
                for code in self._codes_of(printing, block, view)
            ),
        )

    def _codes_of(
        self, view: _View, block: ast.CommandResultCodes, printing: _View | None
    ) -> tuple[ResultCode, ...]:
        """`block`'s codes as `view` prints them, each with the number the
        result-code tables of `view`, of `printing`, the command's document,
        or of their bases, in that order, give its name, else the one every
        document of the corpus defining the name gives it: TS 29.328's Sh
        tables list TS 29.229's DIAMETER_ERROR_USER_UNKNOWN, which neither
        TS 29.329 nor its bases define. Where documents of several vendor
        spaces give the name, those of the table's file's space answer."""
        known: dict[str, tuple[int, int, str]] = {}
        seen: set[Path] = set()
        pending = [view] if printing is None else [view, printing]
        while pending:
            each = pending.pop(0)
            if each.entry.path in seen:
                continue
            seen.add(each.entry.path)
            for table in each.value_tables:
                if table.kind is ast.ValueKind.RESULT_CODES:
                    for row in table.rows:
                        known.setdefault(
                            row.name,
                            (row.value, table.vendor_id, row.origin or table.reference),
                        )
            for base in each.entry.spec.bases:
                cited, _ = self._cited(each, base)
                if cited is not None:
                    pending.append(cited)
        own = view.entry.spec.vendor_id
        for name, defined in self._result_names.items():
            if name in known:
                continue
            # Where documents of several vendor spaces name the code, the
            # table's own space's: RFC 4740 numbers its
            # DIAMETER_ERROR_USER_UNKNOWN 5032, 3GPP's documents 5001.
            ours = [found for found in defined if found[1] == own]
            for candidates in (defined, ours):
                if len({found[:2] for found in candidates}) == 1:
                    known[name] = candidates[0]
                    break
        return tuple(
            ResultCode(
                name=row.name,
                value=None if (found := known.get(row.name)) is None else found[0],
                vendor_id=None if found is None else found[1],
                defined_in=None if found is None else found[2],
                reference=view.entry.reference,
                version=self._older(view),
                section=block.source.section,
                table=block.table,
                page=block.source.page,
            )
            for row in block.rows
        )

    def result_code_tables(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[ResultCodeTable, ...]:
        """Every table of a command's result codes `reference` (or the
        corpus) prints, in file order, with the commands it describes, found
        as `element_tables`' are. `version` selects an older held copy."""
        found = []
        for view in self._selected_views(reference, version):
            for block in view.result_codes:
                commanded = self._commanded(view, block, ())
                found.append(
                    ResultCodeTable(
                        reference=view.entry.reference,
                        version=self._older(view),
                        section=block.source.section,
                        table=block.table,
                        page=block.source.page,
                        command=block.command,
                        application_id=block.application_id,
                        origin=block.origin,
                        codes=self._codes_of(
                            view, block, commanded[0][0] if commanded else None
                        ),
                        commands=tuple(
                            self._message_of(printing, message)
                            for printing, message in commanded
                        ),
                    )
                )
        return tuple(found)

    @cached_property
    def _result_names(self) -> dict[str, list[tuple[int, int, str]]]:
        """Each result code's number, vendor space and defining document, by
        name, as every newest copy's result-code tables give it."""
        found: dict[str, list[tuple[int, int, str]]] = {}
        for reference in self.references():
            for table in self._view(reference).value_tables:
                if table.kind is ast.ValueKind.RESULT_CODES:
                    for row in table.rows:
                        found.setdefault(row.name, []).append(
                            (row.value, table.vendor_id, row.origin or table.reference)
                        )
        return found

    @cached_property
    def _listed(
        self,
    ) -> dict[int, list[tuple[_View, ast.CommandResultCodes]]]:
        """The tables of result codes describing each command block, by the
        block's identity, with the copy printing each table."""
        found: dict[int, list[tuple[_View, ast.CommandResultCodes]]] = {}
        for view in self._copies.values():
            for block in view.result_codes:
                for _, message in self._commanded(view, block, ()):
                    found.setdefault(id(message), []).append((view, block))
        return found

    def _rows_of(
        self, view: _View, block: ast.InformationElements
    ) -> tuple[Element, ...]:
        """`block`'s rows, as `view` prints them."""
        return tuple(
            Element(
                name=row.name,
                category=row.category,
                avps=row.avps,
                either=row.either,
                printed=row.printed,
                within=block.avp,
                parents=parents,
                reference=view.entry.reference,
                version=self._older(view),
                section=block.source.section,
                table=block.table,
                page=block.source.page,
            )
            for row, (parents, _) in zip(block.rows, block.placed(), strict=True)
        )

    def element_tables(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[ElementTable, ...]:
        """Every information-element table `reference` (or the corpus)
        prints, in file order, each with the commands it describes: none
        where it names no command, or one printed under several applications
        it does not choose between, or printed several times and the table
        names no clause. `version` selects an older held copy."""
        return tuple(
            ElementTable(
                reference=view.entry.reference,
                version=self._older(view),
                section=block.source.section,
                table=block.table,
                page=block.source.page,
                command=block.command,
                application_id=block.application_id,
                origin=block.origin,
                within=block.avp,
                elements=self._rows_of(view, block),
                commands=tuple(
                    self._message_of(printing, message)
                    for printing, message in self._commanded(view, block, ())
                ),
            )
            for view in self._selected_views(reference, version)
            for block in view.elements
        )

    @cached_property
    def _described(
        self,
    ) -> dict[int, list[tuple[_View, ast.InformationElements]]]:
        """The information-element tables describing each command block, by
        the block's identity, with the copy printing each table."""
        found: dict[int, list[tuple[_View, ast.InformationElements]]] = {}
        for view in self._copies.values():
            for block in view.elements:
                for _, message in self._commanded(view, block, ()):
                    found.setdefault(id(message), []).append((view, block))
        return found

    def _commanded(
        self,
        view: _View,
        block: ast.InformationElements | ast.CommandResultCodes,
        seen: tuple[Path, ...],
    ) -> list[tuple[_View, ast.Message]]:
        """The command blocks an information-element table describes: those
        of its command in `view`, of its application where it states one, or
        else in the document the table says specifies it, or else in the
        first of `view`'s bases printing it, depth first. Names compare
        without regard to case: TS 29.338 prints its SRA rule
        `Send-Routing-info-for-SM-Answer`. Of a document printing the command
        more than once under the one application, the block at the table's
        `command_section`. None where the command prints under several
        applications, or several times, the table does not choose between, or
        at no such clause; the linter reports each."""
        if block.command is None:
            return []
        named = [
            message
            for message in view.messages
            if message.name.casefold() == block.command.casefold()
            and block.application_id
            in (None, _effective_id(message, _scope(view, message)))
        ]
        if named:
            if block.command_section is not None:
                named = [
                    message
                    for message in named
                    if message.source.section == block.command_section
                ]
            return [(view, message) for message in named] if len(named) == 1 else []
        cited = [] if block.origin is None else [block.origin]
        for base in (*cited, *view.entry.spec.bases):
            cited, _ = self._cited(view, base)
            if cited is None or cited.entry.path in seen:
                continue
            if found := self._commanded(cited, block, (*seen, view.entry.path)):
                return found
        return []

    def answer_message(
        self, reference: str, *, version: str | None = None
    ) -> AnswerMessage | None:
        """The `<answer-message>` that `reference`'s answers with the E bit set
        take: the document's first, else the first from its `; Bases:`
        documents, depth first. The body is read through `reference`. None if
        no document prints one. `version` selects an older held copy."""
        return self._answer_of(self._view(reference, version))

    def _command_constraints(
        self, view: _View, message: ast.Message
    ) -> tuple[Constraint, ...]:
        """The constraints on a command's members: its document's on it, and
        those holding in every answer or request of the documents it is
        built on (`; Messages:`) on an AVP its document reads in none of its
        blocks on the command (Precedence)."""
        own = tuple(
            each
            for each in view.constraints
            if each.command == message.name
            and each.application_id in (None, message.application_id)
            and each.command_section in (None, message.source.section)
        )
        requesting = ast.CommandFlag.REQUEST in message.flags
        wide = [
            each
            for each in self._message_wide(view, ())
            if each.messages == ("requests" if requesting else "answers")
            and each.avp not in {mine.avp for mine in own}
        ]
        if not wide:
            return own
        # The request a rule reads is the command's own: its one print under
        # the answer's application, as an answer's own block reads it.
        application = _effective_id(message, _scope(view, message))
        asked = [
            each
            for each in view.messages
            if ast.CommandFlag.REQUEST in each.flags
            and each.command_code == message.command_code
            and _effective_id(each, _scope(view, each)) == application
        ]
        section = asked[0].source.section if len(asked) == 1 else None
        return own + tuple(
            replace(each, request_section=section) if each.reads_request else each
            for each in wide
        )

    def _message_wide(
        self, view: _View, seen: tuple[Path, ...]
    ) -> tuple[Constraint, ...]:
        """The constraints holding in every answer or request (`; Messages:`)
        of `view`'s document and of its `; Bases:` documents, depth first:
        RFC 6733's, which every document built on it takes."""
        found = [each for each in view.constraints if each.messages is not None]
        for base in view.entry.spec.bases:
            cited, _ = self._cited(view, base)
            if cited is None or cited.entry.path in seen:
                continue
            for each in self._message_wide(cited, (*seen, view.entry.path)):
                if each not in found:
                    found.append(each)
        return tuple(found)

    def _answer_of(self, view: _View) -> AnswerMessage | None:
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
            version=self._older(view),
            defined_version=self._older(printing),
            # A rule reading the request is a command's: an <answer-message>
            # answers any.
            constraints=tuple(
                each
                for each in self._message_wide(view, ())
                if each.messages == "answers" and not each.reads_request
            ),
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

    def undefined(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[Undefined, ...]:
        """Every `Undefined AVP` block in `reference` (or the corpus), in file
        order, under any policy. `version` selects an older held copy."""
        return tuple(
            self._undefined_of(view, block)
            for view in self._selected_views(reference, version)
            for block in view.undefined.values()
        )

    def placeholders(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[Placeholder, ...]:
        """Every placeholder in `reference`'s reading (or the corpus's), found
        as `holes` finds holes, sorted by document and name. Empty unless
        built with `UndefinedPolicy.PLACEHOLDER`. `version` selects an older
        held copy."""
        if self._policy is not UndefinedPolicy.PLACEHOLDER:
            return ()
        found: dict[Placeholder, None] = {}
        for view in self._selected_views(reference, version):
            for name in self._names(view):
                hole = self._final(view, name)
                if isinstance(hole, Hole) and hole.undefined is not None:
                    found[Placeholder(hole.undefined)] = None
            for body in self._bodies(view):
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
        same command twice, as the document prints it; `Application.commands`
        pairs requests and answers.
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
                version=self._older(view),
            )
            for (application_id, clause), messages in groups.items()
            for block in [stating.get((application_id, clause))]
        )

    def avps(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[Avp, ...]:
        """Every AVP `reference` defines, tabulates or re-uses, resolved, or
        every distinct reading in the corpus; sorted by defining document and
        name. `version` selects an older held copy of `reference`.

        Re-used AVPs keep the origin's `defined_in`. Names with a hole are
        left out (see `holes`). Without `reference`, AVPs only an older copy
        holds are included where a citation reaches them.

        This lists what the tables say, not what the commands use; for a
        dictionary generator use `reached`, `Application.walk` or
        `Message.walk`.
        """
        if reference is None:
            self._selected_views(reference, version)
            found: Iterable[Avp] = self._everything
        else:
            found = self._avps_of(self._view(reference, version))
        return tuple(sorted(found, key=_by_defining_document))

    def _avps_of(self, view: _View) -> tuple[Avp, ...]:
        found = (self._final(view, name) for name in self._names(view))
        return tuple(avp for avp in found if isinstance(avp, Avp))

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

    def holes(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[Hole, ...]:
        """Every hole in `reference`'s reading (or the corpus's), sorted by
        document and name. `version` selects an older held copy.

        This covers names its tables and bodies cannot complete, plus holes
        in older copies reached across releases, which carry that copy's
        `version`. A hole belongs to the document that falls short.
        """
        found: dict[Hole, None] = {}
        for view in self._selected_views(reference, version):
            for name in self._names(view):
                hole = self._final(view, name)
                if isinstance(hole, Hole) and self._open(hole):
                    found[hole] = None
            for body in self._bodies(view):
                found.update(
                    (member.hole, None) for member in body if member.hole is not None
                )
            found.update(dict.fromkeys(self._holes_across(view)))
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

    def _bodies(self, view: _View) -> list[tuple[Member, ...]]:
        """`view`'s resolved command and grouped bodies, minus dropped
        members."""
        reference = view.entry.reference
        bodies = [message.avps for message in self._messages_of(view)]
        if view.answers and (answer := self._answer_of(view)) is not None:
            bodies.append(answer.avps)
        bodies += [
            avp.members
            for avp in self._avps_of(view)
            if isinstance(avp, Grouped) and avp.defined_in == reference
        ]
        # A grouped definition with a hole is no `Grouped`, but its body
        # is still this document's to resolve.
        bodies += [
            self._split(self._body(view, definition.avps))[0]
            for name, definition in view.defined.items()
            if isinstance(definition, ast.GroupedAvp)
            and isinstance(hole := self._final(view, name), Hole)
            and self._open(hole)
        ]
        return bodies

    def _holes_across(self, view: _View) -> Iterator[Hole]:
        """Holes of older copies inside grouped AVPs `view` reaches across
        releases, at any depth. Reference-level queries read only the
        newest copies, so nothing else reports these. Holes in a newest copy
        are left to that copy's own reading."""
        pending = [*self._avps_of(view)]
        pending += [
            member.avp
            for message in self._messages_of(view)
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

    def across_releases(
        self, reference: str | None = None, *, version: str | None = None
    ) -> tuple[Avp | Hole, ...]:
        """Every name in `reference`'s reading (or the corpus's) that took a
        field from outside the citing document's release, each with its
        `corpus.CrossRelease`, sorted by citing document and name. `version`
        selects an older held copy.

        Includes, at any depth, what older copies reached this way cite
        across releases in turn. See docs/consumers.md."""
        found: dict[Avp | Hole, None] = {}
        for view in self._selected_views(reference, version):
            for name in self._names(view):
                resolved = self._final(view, name)
                if resolved.across_releases is not None:
                    found[resolved] = None
                    found.update(dict.fromkeys(_reached_across(resolved)))
        return tuple(sorted(found, key=_by_citing_document))

    def table_rows(
        self, reference: str, name: str, *, version: str | None = None
    ) -> tuple[ast.AvpTableRow, ...]:
        """Every AVP-table row `reference` prints for `name`, in file order.
        `resolve` reads the first; later rows may differ
        (`table-row-mismatch`). `version` selects an older held copy.
        """
        return tuple(self._view(reference, version).tabled.get(name, ()))

    def marks(
        self, reference: str, name: str, *, version: str | None = None
    ) -> tuple[Marks, ...]:
        """`name`'s marks in `reference`, one per row of an AVP or re-used
        table with mark columns, in file order. For one interface, keep the
        rows whose `section` lies in its clause. `version` selects an older
        held copy.
        """
        return tuple(self._view(reference, version).marked.get(name, ()))

    def reached(
        self, *of: Application | Message | AnswerMessage
    ) -> tuple[Reached, ...]:
        """One entry per `(vendor-id, code)` that the bodies of `of`, one or
        more applications, commands and error answers, reach at any depth,
        by identity: the defining document's reading, every distinct reading
        met with the member paths it is met at, and whether those readings
        conflict (`Reached.conflicts`).

        Each entry's `value_tables` are those its readings carry where met,
        those the document of what is walked prints for its names and the
        defining reading's result codes, which a reading's own set aside,
        without another application's feature lists: `Feature-List` numbers
        other features on each interface. Holes, placeholders and the
        wildcard reach no identity; `walk` yields them.
        """
        views: dict[Path, _View] = {}
        roots: list[tuple[str, str, tuple[Member, ...]]] = []
        context: list[tuple[str, str | None, int | None, str]] = []
        for each in of:
            if isinstance(each, Application):
                view = self._view(each.reference, each.version)
                roots += [
                    (message.abbreviation, message.section, message.avps)
                    for message in each.messages
                ]
                context.append(_application_key(each))
            elif isinstance(each, Message):
                view = self._view(each.defined_in, each.version)
                roots.append((each.abbreviation, each.section, each.avps))
                context += [
                    _application_key(application)
                    for application in self._applications_of(view)
                    if each in application.messages
                ]
            else:
                view = self._view(each.read_through, each.version)
                roots.append(("answer-message", each.section, each.avps))
                context += map(_application_key, self._applications_of(view))
            views[view.entry.path] = view
        met: dict[tuple[int, int], dict[Avp, list[MemberPath]]] = {}
        tables: dict[tuple[int, int], dict[ValueTable, None]] = {}

        def visit(
            members: tuple[Member, ...],
            command: str,
            section: str,
            prefix: tuple[str, ...],
            above: frozenset[int],
        ) -> None:
            for member in members:
                avp = member.avp
                if avp is None:
                    continue
                names = (*prefix, member.name)
                paths = met.setdefault(avp.identity, {}).setdefault(avp, [])
                paths.append(MemberPath(command, section, names))
                tables.setdefault(avp.identity, {}).update(
                    dict.fromkeys(avp.value_tables)
                )
                # The model cuts a body among its own descendants; this
                # guards a walk of one regardless.
                if isinstance(avp, Grouped) and id(avp) not in above:
                    visit(avp.members, command, section, names, above | {id(avp)})

        for command, section, members in roots:
            visit(members, command, section, (), frozenset())
        printed: dict[str, list[ValueTable]] = {}
        for view in views.values():
            for table in self._tables(view):
                printed.setdefault(table.avp, []).append(table)
        found = []
        for identity in sorted(met):
            readings = met[identity]
            for name in dict.fromkeys(avp.name for avp in readings):
                tables[identity].update(dict.fromkeys(printed.get(name, ())))
            # A document's result codes add to the defining document's,
            # which its reading sets aside (TS 29.212's clause 5.5 over RFC
            # 6733's 7.1): an answer may carry any of them.
            definition = self.definition(identity)
            if definition is not None:
                tables[identity].update(
                    dict.fromkeys(
                        table
                        for table in definition.value_tables
                        if table.kind is ast.ValueKind.RESULT_CODES
                    )
                )
            found.append(
                Reached(
                    vendor_id=identity[0],
                    code=identity[1],
                    definition=definition,
                    readings=tuple(
                        Met(avp, tuple(paths)) for avp, paths in readings.items()
                    ),
                    value_tables=tuple(
                        table
                        for table in tables[identity]
                        if table.kind is not ast.ValueKind.FEATURES
                        or not context
                        or set(map(_application_key, self.feature_owners(table)))
                        & set(context)
                    ),
                )
            )
        return tuple(found)

    def feature_owners(self, table: ValueTable) -> tuple[Application, ...]:
        """The applications of `table`'s document whose features a features
        table numbers.

        Those the caption names, matched against each application's name and
        its Application IDs registry rows ("S6a/S6d" is TS 29.230's "3GPP
        S6a"); failing a match, those of the interface clause holding the
        table; failing that, every application of the document.
        """
        view = self._view(table.reference, table.version)
        applications = self._applications_of(view)
        if table.application is not None:
            captioned = _components(table.application)
            named = [
                application
                for application in applications
                if captioned & self._application_names(application)
            ]
            if named:
                return tuple(named)
        clause = ast.interface_clause(table.section)
        within = [each for each in applications if each.clause == clause]
        return tuple(within or applications)

    def _application_names(self, application: Application) -> frozenset[str]:
        names = set() if application.name is None else _components(application.name)
        if application.application_id is not None:
            for allocation in self.registry(
                ast.RegistryKind.APPLICATION_IDS, application.application_id
            ):
                if isinstance(allocation.entry, ast.RegistryRow) and (
                    allocation.entry.name is not None
                ):
                    names |= _components(allocation.entry.name)
        return frozenset(names)

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
            for table in self._tables(view)
            if (avp is None or table.avp == avp)
            and (kind is None or table.kind is kind)
        )

    def constraints(
        self,
        reference: str | None = None,
        *,
        avp: str | None = None,
        version: str | None = None,
    ) -> tuple[Constraint, ...]:
        """The interpreted constraints `reference` (or the corpus) holds, in
        file order, optionally of one AVP. `version` selects an older held
        copy. Each is read from prose, not printed (`Constraint`)."""
        return tuple(
            each
            for view in self._selected_views(reference, version)
            for each in view.constraints
            if avp is None or each.avp == avp
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
        for view in self._views.values():
            found.update(dict.fromkeys(self._avps_of(view)))
        known = {avp.identity for avp in found}
        found.update(
            (avp, None) for avp in self._reached(found) if avp.identity not in known
        )
        return [self._as_read_through(avp) for avp in found]

    def _as_read_through(self, avp: Avp) -> Avp:
        """`avp` with the value tables and constraints of the document it is
        read through.

        Equal readings are one, and the first met stands for them; its
        tables are those of whichever document resolved it first. TS 32.299
        reads RFC 6733's `Result-Code` with its own codes; the reading names
        RFC 6733, so it carries RFC 6733's.
        """
        view = self._by_document.get(avp.read_through)
        own = None if view is None else self._final(view, avp.name)
        if not isinstance(own, Avp) or (
            own.value_tables == avp.value_tables
            and own.constraints == avp.constraints
            and _member_constraints(own) == _member_constraints(avp)
        ):
            return avp
        if isinstance(avp, Grouped):
            return replace(
                avp,
                value_tables=own.value_tables,
                constraints=own.constraints,
                member_constraints=_member_constraints(own),
            )
        return replace(avp, value_tables=own.value_tables, constraints=own.constraints)

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
            for view in self._views.values()
            for avp in self._avps_of(view)
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
