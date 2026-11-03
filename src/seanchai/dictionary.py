"""`seanchai dictionary`: the resolved corpus as one JSON file, for a Diameter
stack that is not Python to generate its own dictionary from.

The shape is these models; docs/consumers.md#without-python says how to read it.
Every field is always written, null or empty where it says nothing. Commands
hold their applications' place and AVPs a list of their own, each reading once,
which members name by `id`, so a body shared by a hundred commands is one entry.
The same corpus and the same choices give the same bytes.
"""

import json
from collections.abc import Iterable, Sequence
from typing import Annotated, Any, Literal

import pydantic

from . import __version__, export_schema, model
from .dad import ast
from .export import cross_release_entry, hole_entry
from .export_schema import CrossRelease, FlagRules, UndefinedBlock

# Changes when a reader would have to.
FORMAT_VERSION = 2


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
    or `reserved` or `vendor-specific`, a range from `first` to `last`.
    `description` is the document's words."""

    kind: Literal["value", "reserved", "vendor-specific"]
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


class Command(_Model):
    """One command as `defined_in` prints it. `application_id` is the id on the
    wire and `header_application_id` the one its header prints. `members` is its
    body; `walk` is `Message.walk`, each AVP at any depth, by `id`."""

    name: str
    abbreviation: str
    command_code: int
    is_request: bool
    flags: tuple[ast.CommandFlag, ...]
    application_id: int | None
    header_application_id: int | None
    defined_in: str
    section: str
    members: tuple[Member, ...]
    dropped: tuple[Member, ...]
    walk: tuple[str, ...]


class Application(_Model):
    """A document's commands for one application id on one interface
    (`model.Application`)."""

    reference: str
    application_id: int | None
    clause: str
    name: str | None
    stated_in: str | None
    commands: tuple[Command, ...]


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


class Dictionary(_Model):
    """The file. `documents` and `application_ids` are what was selected, the
    second empty for every application of those documents. `undefined_policy` is
    what became of the names an `Undefined AVP` block declares. `value_tables` are
    the selected documents'; with `application_ids`, those of the documents
    holding one."""

    format_version: Annotated[int, pydantic.Field(ge=FORMAT_VERSION, le=FORMAT_VERSION)]
    seanchai_version: str
    corpus_version: str | None
    undefined_policy: model.UndefinedPolicy
    documents: tuple[str, ...]
    application_ids: tuple[int, ...]
    applications: tuple[Application, ...]
    avps: tuple[Avp, ...]
    holes: tuple[Hole, ...]
    value_tables: tuple[ValueTable, ...]


def _hole_id(hole: model.Hole) -> str:
    return f"{hole.document}/{hole.name}"


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
        """Give each reading its `id`: the identity, with the defining
        document's reading first and the rest in the order of their contents,
        which no hash seed or selection order moves."""
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
            if not model.is_cut(member)
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

    def command(self, message: model.Message) -> Command:
        return Command(
            name=message.name,
            abbreviation=message.abbreviation,
            command_code=message.command_code,
            is_request=message.is_request,
            flags=tuple(sorted(message.flags)),
            application_id=message.application_id,
            header_application_id=message.header_application_id,
            defined_in=message.defined_in,
            section=message.section,
            members=self.members(message.avps),
            dropped=self.members(message.dropped),
            walk=tuple(
                self.ids[member.avp]
                for member in message.walk()
                if member.avp is not None
            ),
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
    """`built`'s applications, commands and AVPs, of `documents` (every document)
    and `application_ids` (every application).

    The AVPs are what the selected commands use at any depth. Without
    `application_ids`, they are also what the selected documents' tables list,
    since a document can define AVPs no command of its own uses (TS 29.061). An id
    no selected document uses is refused, as `model.ModelError`, like a reference
    the corpus lacks: an empty file is no answer to it.
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
    for application in applications:
        for message in application.messages:
            builder.hold_members((*message.avps, *message.dropped))
    if not application_ids:
        for reference in references:
            builder.hold(built.avps(reference))
            for hole in built.holes(reference):
                builder.holes.setdefault(_hole_id(hole), hole)
    builder.number()
    avps = sorted(
        builder.readings,
        key=lambda avp: (
            avp.vendor_id,
            avp.code,
            # `10415:601#10` after `10415:601#9`, and no `#` first.
            int(builder.ids[avp].partition("#")[2] or 1),
        ),
    )
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
                commands=tuple(builder.command(each) for each in application.messages),
            )
            for application in applications
        ),
        avps=tuple(builder.avp(avp) for avp in avps),
        holes=tuple(
            Hole.model_validate(
                {**hole_entry(hole).model_dump(mode="json"), "id": identifier}
            )
            for identifier, hole in sorted(builder.holes.items())
        ),
        value_tables=tuple(
            _value_table(built, builder, table)
            for reference in holding
            for table in built.value_tables(reference)
        ),
    )


def dumps(dictionary: Dictionary) -> str:
    """The file's text: `export_schema.dumps`, compact with its keys sorted."""
    return export_schema.dumps(dictionary)
