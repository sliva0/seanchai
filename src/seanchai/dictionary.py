"""`seanchai dictionary`: the resolved corpus as one JSON file, for non-Python
Diameter stacks; also the JSON `seanchai show` and `seanchai commands` print.

These models are the shape; docs/consumers.md explains it. Every field is
always written, null or empty when unstated. AVPs are a separate list, each
reading once, and members refer to them by `id`. The same corpus and the
same options give the same bytes.
"""

import json
from collections.abc import Iterable, Sequence
from typing import Annotated, Any, Literal

import pydantic

from . import __version__, export_schema, model
from .dad import ast
from .export import cross_release_entry, hole_entry
from .export_schema import CrossRelease, FlagRules, UndefinedBlock
from .model._types import is_cut

__all__ = [
    "FORMAT_VERSION",
    "Alias",
    "AnswerMessage",
    "Application",
    "Avp",
    "Command",
    "CommandHeading",
    "CrossRelease",
    "Dictionary",
    "FlagRules",
    "Hole",
    "ListedApplication",
    "Listing",
    "Lookup",
    "Member",
    "UndefinedBlock",
    "Value",
    "ValueRow",
    "ValueTable",
    "build",
    "dumps",
    "listing",
    "lookup",
]

# Changes when a reader would have to.
FORMAT_VERSION = 1


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class Alias(_Model):
    """What a consumer's `model.Alias` read an undefined name as."""

    reference: str
    name: str
    source: str


class Member(_Model):
    """One line of a body. `kind` says what it is: `avp`, naming an entry of
    `avps` in `avp`; `hole`, naming an entry of `holes` in `hole`; `placeholder`,
    an undefined name kept untyped, its block in `placeholder`; or `wildcard`,
    the `* [ AVP ]` line. `min_occurs` and `max_occurs` are RFC 6733 section
    3.2's reading, `max_occurs` null where it is unbounded."""

    name: str
    kind: Literal["avp", "hole", "placeholder", "wildcard"]
    presence: ast.Presence
    min_occurs: int
    max_occurs: int | None
    avp: str | None
    hole: str | None
    placeholder: UndefinedBlock | None
    alias: Alias | None


class Value(_Model):
    """One line of an enumerated AVP. `kind` is `value`, with `name` and `value`;
    or `reserved`, `void` or `vendor-specific`, a range from `first` to `last`.
    `description` is the document's words."""

    kind: Literal["value", "reserved", "void", "vendor-specific"]
    name: str | None
    value: int | None
    first: int | None
    last: int | None
    description: str | None


class Avp(_Model):
    """One reading of an AVP. `id` is `vendor:code`, with `#2` and so on after it
    where the selection holds several readings of the identity, since a citing
    table can change the flags. `defining` marks the defining document's reading.
    `kind` says which of `members` and `values` can hold anything. `defined_in`,
    `section`, `read_through`, `completed_by` and `supplied` are as `model.Avp`
    has them, and so is `dropped`, the members `drop` took out."""

    id: str
    defining: bool
    kind: Literal["plain", "grouped", "enumerated"]
    name: str
    vendor_id: int
    code: int
    data_type: ast.DataType
    flag_rules: FlagRules
    defined_in: str
    section: str | None
    read_through: str
    completed_by: tuple[tuple[str, str], ...]
    across_releases: CrossRelease | None
    supplied: str | None
    members: tuple[Member, ...]
    dropped: tuple[Member, ...]
    values: tuple[Value, ...]
    values_source: str | None


class CommandHeading(_Model):
    """One command as `defined_in` prints it, without its body: what `seanchai
    commands` lists. `application_id` is the id on the wire and
    `header_application_id` the one its header prints."""

    name: str
    abbreviation: str
    command_code: int
    is_request: bool
    flags: tuple[ast.CommandFlag, ...]
    application_id: int | None
    header_application_id: int | None
    defined_in: str
    section: str


class Command(CommandHeading):
    """One command with its body. `members` is the body; `walk` is
    `Message.walk`, each AVP at any depth, by `id`. An answer's `answer_message`
    names the `answer_messages` entry it takes with the E bit set, null for a
    request and where no document gives one."""

    members: tuple[Member, ...]
    dropped: tuple[Member, ...]
    walk: tuple[str, ...]
    answer_message: str | None


class AnswerMessage(_Model):
    """RFC 6733 section 7.2's `<answer-message>` as `defined_in` prints it, read
    through `read_through`, whose commands' answers take it with the E bit set
    (`model.AnswerMessage`). `id` is `read_through/defined_in:section`."""

    id: str
    defined_in: str
    section: str
    read_through: str
    members: tuple[Member, ...]
    dropped: tuple[Member, ...]
    walk: tuple[str, ...]


class _ApplicationFields(_Model):
    reference: str
    application_id: int | None
    clause: str
    name: str | None
    stated_in: str | None


class Application(_ApplicationFields):
    """A document's commands for one application id on one interface
    (`model.Application`)."""

    commands: tuple[Command, ...]


class ListedApplication(_ApplicationFields):
    """An `Application` whose commands are headings, as `seanchai commands`
    lists them."""

    commands: tuple[CommandHeading, ...]


class Hole(export_schema.Hole):
    """A name the corpus cannot complete, as the export has it. `id` is what a
    member's `hole` names."""

    id: str


class ValueRow(_Model):
    """A number and the name a document gives it. `section` is a result code's
    own clause, `mark` a feature's M/O column."""

    name: str
    value: int
    section: str | None
    mark: str | None


class ValueTable(_Model):
    """What one document names a numeric AVP's numbers (`model.ValueTable`).
    `avp_id` is the `avps` entry the document's reading of `avp` is, null where
    the selection holds none."""

    kind: ast.ValueKind
    avp: str
    avp_id: str | None
    reference: str
    version: str | None
    vendor_id: int
    section: str
    page: int | None
    table: str | None
    application: str | None
    feature_list_id: int | None
    rows: tuple[ValueRow, ...]


class _Versions(_Model):
    """What produced a document: this format, the library and the corpus."""

    format_version: Annotated[int, pydantic.Field(ge=FORMAT_VERSION, le=FORMAT_VERSION)]
    seanchai_version: str
    corpus_version: str | None


class Dictionary(_Versions):
    """The file. `documents` and `application_ids` are what was selected, the
    second empty for every application of those documents. `undefined_policy` is
    what became of the names an `Undefined AVP` block declares. `value_tables` are
    the selected documents'; with `application_ids`, those of the documents
    holding one. `answer_messages` are those the selected answers take."""

    undefined_policy: model.UndefinedPolicy
    documents: tuple[str, ...]
    application_ids: tuple[int, ...]
    applications: tuple[Application, ...]
    answer_messages: tuple[AnswerMessage, ...]
    avps: tuple[Avp, ...]
    holes: tuple[Hole, ...]
    value_tables: tuple[ValueTable, ...]


class Lookup(_Versions):
    """What `seanchai show --json` prints: one AVP, in the dictionary's shapes.
    `avp` is the `id` of the reading asked for, the first of `avps`; the
    identity's other readings follow it, then every AVP their bodies name at
    any depth, so that each member's `avp` and `hole` name an entry here, as in
    the dictionary. `value_tables` are those of the identity's readings."""

    undefined_policy: model.UndefinedPolicy
    avp: str
    avps: tuple[Avp, ...]
    holes: tuple[Hole, ...]
    value_tables: tuple[ValueTable, ...]


class Listing(_Versions):
    """What `seanchai commands --json` prints: the applications selected, each
    command a heading, without the bodies the dictionary gives."""

    applications: tuple[ListedApplication, ...]


def _hole_id(hole: model.Hole) -> str:
    return f"{hole.document}/{hole.name}"


def _answer_id(answer: model.AnswerMessage) -> str:
    return f"{answer.read_through}/{answer.defined_in}:{answer.section}"


class _Builder:
    """The readings a selection holds, and the `id` of each."""

    def __init__(self, built: model.Model) -> None:
        self._built = built
        self.readings: dict[model.Avp, None] = {}
        self.holes: dict[str, model.Hole] = {}
        self.ids: dict[model.Avp, str] = {}

    def hold(self, avps: Iterable[model.Avp]) -> None:
        """Hold `avps`, and everything their bodies name."""
        for avp in avps:
            if avp in self.readings:
                continue
            self.readings[avp] = None
            if isinstance(avp, model.Grouped):
                self.hold_members((*avp.members, *avp.dropped))

    def hold_members(self, members: Iterable[model.Member]) -> None:
        for member in members:
            if member.hole is not None:
                self.holes.setdefault(_hole_id(member.hole), member.hole)
            if member.avp is not None:
                self.hold((member.avp,))

    def number(self) -> None:
        """Give each reading its `id`: the defining document's reading first,
        then the rest ordered by content, independent of hash seed or
        selection order."""
        identities: dict[tuple[int, int], list[model.Avp]] = {}
        for avp in self.readings:
            identities.setdefault(avp.identity, []).append(avp)
        for (vendor_id, code), readings in identities.items():
            defining = self._built.definition((vendor_id, code))
            if len(readings) > 1:
                readings.sort(
                    key=lambda avp: (
                        avp != defining,
                        json.dumps(avp.to_dict(), sort_keys=True),
                    )
                )
            for index, avp in enumerate(readings, 1):
                suffix = "" if index == 1 else f"#{index}"
                self.ids[avp] = f"{vendor_id}:{code}{suffix}"

    def member(self, member: model.Member) -> Member:
        block = None
        if member.placeholder is not None:
            undefined = member.placeholder.undefined
            block = UndefinedBlock(
                section=undefined.section,
                page=undefined.page,
                note=undefined.note,
                cited_in=undefined.cited_in,
            )
        kind: Literal["avp", "hole", "placeholder", "wildcard"]
        if member.avp is not None:
            kind = "avp"
        elif member.hole is not None:
            kind = "hole"
        elif member.placeholder is not None:
            kind = "placeholder"
        else:
            kind = "wildcard"
        return Member(
            name=member.name,
            kind=kind,
            presence=member.rule.presence,
            min_occurs=member.min_occurs,
            max_occurs=member.max_occurs,
            avp=None if member.avp is None else self.ids[member.avp],
            hole=None if member.hole is None else _hole_id(member.hole),
            placeholder=block,
            alias=None
            if member.alias is None
            else Alias(
                reference=member.alias.reference,
                name=member.alias.name,
                source=member.alias.source,
            ),
        )

    def members(self, members: Iterable[model.Member]) -> tuple[Member, ...]:
        return tuple(
            self.member(member)
            for member in members
            # A body among its own descendants, `Message.walk`'s cut: the corpus
            # holds none, and the entry it would name is the one being read.
            if not is_cut(member)
        )

    def avp(self, avp: model.Avp) -> Avp:
        members: tuple[model.Member, ...] = ()
        dropped: tuple[model.Member, ...] = ()
        values: tuple[Value, ...] = ()
        values_source = None
        kind: Literal["plain", "grouped", "enumerated"] = "plain"
        if isinstance(avp, model.Grouped):
            kind = "grouped"
            members, dropped = avp.members, avp.dropped
        elif isinstance(avp, model.Enumerated):
            kind = "enumerated"
            values = tuple(_value(each) for each in avp.to_dict()["values"])
            values_source = avp.values_source
        return Avp(
            id=self.ids[avp],
            defining=avp == self._built.definition(avp.identity),
            kind=kind,
            name=avp.name,
            vendor_id=avp.vendor_id,
            code=avp.code,
            data_type=avp.data_type,
            flag_rules=FlagRules.model_validate(avp.flag_rules.to_dict()),
            defined_in=avp.defined_in,
            section=avp.section,
            read_through=avp.read_through,
            completed_by=avp.completed_by,
            across_releases=cross_release_entry(avp.across_releases),
            supplied=avp.supplied,
            members=self.members(members),
            dropped=self.members(dropped),
            values=values,
            values_source=values_source,
        )

    def walk(self, members: Iterable[model.Member]) -> tuple[str, ...]:
        return tuple(
            self.ids[member.avp] for member in members if member.avp is not None
        )

    def answer(self, answer: model.AnswerMessage) -> AnswerMessage:
        return AnswerMessage(
            id=_answer_id(answer),
            defined_in=answer.defined_in,
            section=answer.section,
            read_through=answer.read_through,
            members=self.members(answer.avps),
            dropped=self.members(answer.dropped),
            walk=self.walk(answer.walk()),
        )

    def command(
        self, message: model.Message, answer: model.AnswerMessage | None
    ) -> Command:
        return Command(
            **dict(_heading(message)),
            members=self.members(message.avps),
            dropped=self.members(message.dropped),
            walk=self.walk(message.walk()),
            answer_message=None
            if message.is_request or answer is None
            else _answer_id(answer),
        )


def _heading(message: model.Message) -> CommandHeading:
    return CommandHeading(
        name=message.name,
        abbreviation=message.abbreviation,
        command_code=message.command_code,
        is_request=message.is_request,
        flags=tuple(sorted(message.flags)),
        application_id=message.application_id,
        header_application_id=message.header_application_id,
        defined_in=message.defined_in,
        section=message.section,
    )


def _value_table(
    built: model.Model, builder: _Builder, table: model.ValueTable
) -> ValueTable:
    reading = built.resolve(table.reference, table.avp, version=table.version)
    return ValueTable(
        kind=table.kind,
        avp=table.avp,
        avp_id=None if reading is None else builder.ids.get(reading),
        reference=table.reference,
        version=table.version,
        vendor_id=table.vendor_id,
        section=table.section,
        page=table.page,
        table=table.table,
        application=table.application,
        feature_list_id=table.feature_list_id,
        rows=tuple(
            ValueRow(name=row.name, value=row.value, section=row.section, mark=row.mark)
            for row in table.rows
        ),
    )


def _value(fields: dict[str, Any]) -> Value:
    """`Enumerated.to_dict`'s line, every field of `Value` present."""
    return Value.model_validate({name: fields.get(name) for name in Value.model_fields})


def build(
    built: model.Model,
    *,
    corpus_version: str | None = None,
    documents: Sequence[str] = (),
    application_ids: Sequence[int] = (),
) -> Dictionary:
    """Build the dictionary of `built`, limited to `documents` and
    `application_ids` (all when not given).

    AVPs are those the selected commands use at any depth; without
    `application_ids`, also those the selected documents' tables list. An id
    no selected document uses raises `model.ModelError`.
    """
    references = tuple(
        sorted({built.canonical(each) for each in documents}) or built.references()
    )
    applications = [
        application
        for reference in references
        for application in built.applications(reference)
        if not application_ids or application.application_id in application_ids
    ]
    found = {application.application_id for application in applications}
    if unknown := sorted(set(application_ids) - found):
        raise model.ModelError(
            f"no application {', '.join(map(str, unknown))} in"
            f" {', '.join(references)}: `seanchai commands` lists them"
        )
    builder = _Builder(built)
    # What the answers of each document holding a selected command take.
    answers = {
        reference: built.answer_message(reference)
        for reference in sorted({application.reference for application in applications})
    }
    taken = {
        _answer_id(answer): answer
        for application in applications
        if any(not message.is_request for message in application.messages)
        and (answer := answers[application.reference]) is not None
    }
    for application in applications:
        for message in application.messages:
            builder.hold_members((*message.avps, *message.dropped))
    for answer in taken.values():
        builder.hold_members((*answer.avps, *answer.dropped))
    if not application_ids:
        for reference in references:
            builder.hold(built.avps(reference))
            for hole in built.holes(reference):
                builder.holes.setdefault(_hole_id(hole), hole)
    builder.number()
    avps = _in_order(builder)
    holding = (
        sorted({application.reference for application in applications})
        if application_ids
        else references
    )
    return Dictionary(
        format_version=FORMAT_VERSION,
        seanchai_version=__version__,
        corpus_version=corpus_version,
        undefined_policy=built.undefined_policy,
        documents=references,
        application_ids=tuple(sorted(set(application_ids))),
        applications=tuple(
            Application(
                reference=application.reference,
                application_id=application.application_id,
                clause=application.clause,
                name=application.name,
                stated_in=application.stated_in,
                commands=tuple(
                    builder.command(each, answers[application.reference])
                    for each in application.messages
                ),
            )
            for application in applications
        ),
        answer_messages=tuple(builder.answer(taken[each]) for each in sorted(taken)),
        avps=tuple(builder.avp(avp) for avp in avps),
        holes=_holes(builder),
        value_tables=tuple(
            _value_table(built, builder, table)
            for reference in holding
            for table in built.value_tables(reference)
        ),
    )


def _in_order(builder: _Builder) -> list[model.Avp]:
    """The readings by identity, each identity's by `id`."""
    return sorted(
        builder.readings,
        key=lambda avp: (
            avp.vendor_id,
            avp.code,
            # `10415:601#10` after `10415:601#9`, and no `#` first.
            int(builder.ids[avp].partition("#")[2] or 1),
        ),
    )


def _holes(builder: _Builder) -> tuple[Hole, ...]:
    return tuple(
        Hole.model_validate(
            {**hole_entry(hole).model_dump(mode="json"), "id": identifier}
        )
        for identifier, hole in sorted(builder.holes.items())
    )


def lookup(
    built: model.Model, avp: model.Avp, *, corpus_version: str | None = None
) -> Lookup:
    """Return `avp` (one of `built`'s readings) with the other readings of
    its identity and everything their bodies name at any depth."""
    builder = _Builder(built)
    others = [each for each in built.readings(avp.identity) if each != avp]
    builder.hold((avp, *others))
    builder.number()
    readings = [avp, *sorted(others, key=lambda each: builder.ids[each])]
    named = [each for each in _in_order(builder) if each.identity != avp.identity]
    tables = {
        _value_table(built, builder, table): None
        for reading in readings
        for table in reading.value_tables
    }
    return Lookup(
        format_version=FORMAT_VERSION,
        seanchai_version=__version__,
        corpus_version=corpus_version,
        undefined_policy=built.undefined_policy,
        avp=builder.ids[avp],
        avps=tuple(builder.avp(each) for each in (*readings, *named)),
        holes=_holes(builder),
        value_tables=tuple(tables),
    )


def listing(
    applications: Iterable[model.Application], *, corpus_version: str | None = None
) -> Listing:
    """`applications`, each command a heading."""
    return Listing(
        format_version=FORMAT_VERSION,
        seanchai_version=__version__,
        corpus_version=corpus_version,
        applications=tuple(
            ListedApplication(
                reference=application.reference,
                application_id=application.application_id,
                clause=application.clause,
                name=application.name,
                stated_in=application.stated_in,
                commands=tuple(_heading(each) for each in application.messages),
            )
            for application in applications
        ),
    )


def dumps(dictionary: Dictionary) -> str:
    """Return the file's text via `export_schema.dumps`."""
    return export_schema.dumps(dictionary)
