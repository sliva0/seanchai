"""`seanchai dictionary`: the resolved corpus as one JSON file, for Diameter
stacks generating dictionaries or codecs; also the JSON `seanchai show` and
`seanchai commands` print.

These models are the shape and `json_schema` describes them; docs/consumers.md
explains it. Every field is always written, null or empty when unstated. AVPs
are a separate list, each distinct reading once, and members refer to them by
`id`. An id depends on the reading and the corpus, not on what was selected,
and the same corpus and options give the same bytes.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal

import pydantic
from pydantic.json_schema import models_json_schema

from . import __version__, _json, model
from ._json import CrossRelease, FlagRules, UndefinedBlock
from .dad import ast

if TYPE_CHECKING:
    from . import corpus

__all__ = [
    "FORMAT_VERSION",
    "Alias",
    "AnswerMessage",
    "Application",
    "Avp",
    "Command",
    "CommandHeading",
    "CommandPair",
    "Conflict",
    "ConflictingReading",
    "CrossRelease",
    "Dictionary",
    "Document",
    "FlagRules",
    "Hole",
    "HoleError",
    "ListedApplication",
    "Listing",
    "Lookup",
    "Marks",
    "Member",
    "Path",
    "UndefinedBlock",
    "Value",
    "ValueRow",
    "ValueTable",
    "Vendor",
    "avp_id",
    "build",
    "dumps",
    "json_schema",
    "listing",
    "lookup",
]

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
    or `reserved`, `void` or `vendor-specific`, a range from `first` to `last`.
    `description` is the document's words."""

    kind: Literal["value", "reserved", "void", "vendor-specific"]
    name: str | None
    value: int | None
    first: int | None
    last: int | None
    description: str | None


class Avp(_Model):
    """One reading of an AVP (`model.Avp`). `id` is `vendor:code` for the
    defining document's reading (`defining`); another reading's adds
    `@read_through`, then ` in DOCUMENT` where it is defined elsewhere and
    ` via DOCUMENT` where a citation outside the citing release reached it
    (`avp_id`). `kind` says which of `members` and `values` can hold anything.
    `basic_type` is the RFC 6733 section 4.2 format `data_type` is carried in.
    `version` is `defined_in`'s for an older copy. The rest are as
    `model.Avp` has them, and `dropped` is the members `drop` took out."""

    id: str
    defining: bool
    kind: Literal["plain", "grouped", "enumerated"]
    name: str
    vendor_id: int
    code: int
    data_type: ast.DataType
    basic_type: ast.DataType
    flag_rules: FlagRules
    may_encrypt: bool | None
    defined_in: str
    version: str | None
    section: str | None
    read_through: str
    completed_by: tuple[tuple[str, str], ...]
    across_releases: CrossRelease | None
    supplied: str | None
    wireshark_name: str | None
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


class CommandPair(_Model):
    """A command code's requests and answers in one application, as indexes
    into its `commands` (`model.Command`): usually one of each, two where the
    document prints a half twice, none where it prints no such half."""

    command_code: int
    requests: tuple[int, ...]
    answers: tuple[int, ...]


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


class Marks(_Model):
    """What one of an application's document's tables marks about a name its
    commands reach, in a row within the application's clause
    (`model.Marks`). `avp` is the `avps` entry the document reads the name as,
    null where the dictionary holds none. A column's marks are null for a
    blank cell and empty for a dash."""

    name: str
    avp: str | None
    table: str | None
    section: str
    marks: dict[str, tuple[str, ...] | None]


class _ApplicationFields(_Model):
    id: str
    reference: str
    version: str | None
    application_id: int | None
    clause: str
    name: str | None
    stated_in: str | None


class Application(_ApplicationFields):
    """A document's commands for one application id on one interface
    (`model.Application`). `id` is `reference/clause/application_id`, with
    the version after the reference for an older copy and `-` for no id.
    `pairs` pairs the commands by code; `marks` is what the document's tables
    in the application's clause mark about the names it reaches."""

    commands: tuple[Command, ...]
    pairs: tuple[CommandPair, ...]
    marks: tuple[Marks, ...]


class ListedApplication(_ApplicationFields):
    """An `Application` whose commands are headings, as `seanchai commands`
    lists them."""

    commands: tuple[CommandHeading, ...]
    pairs: tuple[CommandPair, ...]


class Hole(_json.Hole):
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
    `avp_ids` are the `avps` entries met carrying it, or the entry its
    document reads `avp` as; `applications` the `applications` entries
    reaching it. A features table is kept only for the applications whose
    feature list it numbers (`model.Model.feature_owners`)."""

    kind: ast.ValueKind
    avp: str
    avp_ids: tuple[str, ...]
    applications: tuple[str, ...]
    reference: str
    version: str | None
    vendor_id: int
    section: str
    page: int | None
    table: str | None
    application: str | None
    feature_list_id: int | None
    rows: tuple[ValueRow, ...]


class Path(_Model):
    """Where a reading is met: the `applications` entry (null for an error
    answer's body), the command by abbreviation and clause, and the member
    names from the command's body down to it (`model.MemberPath`)."""

    application: str | None
    command: str
    section: str
    names: tuple[str, ...]


class ConflictingReading(_Model):
    """One of a conflict's readings, by `avps` id, and where it is met.
    `obsoleted_by` names the documents of the corpus whose headers obsolete
    the document the reading is defined in or read through
    (`model.Model.obsoleted_by`): RFC 7155 for a reading of RFC 4005's."""

    avp: str
    obsoleted_by: tuple[str, ...]
    paths: tuple[Path, ...]


class Conflict(_Model):
    """An identity the output holds several readings of that disagree on a
    field a codec stores (`model.Reached.conflicts`): `fields` names them,
    `defining` is the defining reading's id where the output holds it. A
    backend keeping one reading per AVP has to choose here. `obsolete` says
    the readings no obsoleted document gives agree, so the conflict is only
    with a document a newer one replaces: RFC 4005's NAS-Port against RFC
    7155's."""

    vendor_id: int
    code: int
    defining: str | None
    fields: tuple[str, ...]
    obsolete: bool
    readings: tuple[ConflictingReading, ...]


class Vendor(_Model):
    """A vendor id the output's AVPs use, the organisation it names, and where
    that is stated (`model.VENDORS`); null name and source for one the
    library does not know."""

    vendor_id: int
    name: str | None
    source: str | None


class Document(_Model):
    """A document copy the output was resolved from."""

    reference: str
    version: str | None


class _Versions(_Model):
    """What produced a document: this format, the library and the corpus."""

    format_version: Annotated[int, pydantic.Field(ge=FORMAT_VERSION, le=FORMAT_VERSION)]
    seanchai_version: str
    corpus_version: str | None


class Dictionary(_Versions):
    """The file. `documents`, `version` and `application_ids` are what was
    selected, `application_ids` empty for every application of those
    documents. `strict` refused any hole. `undefined_policy` is what became of
    the names an `Undefined AVP` block declares. `resolved` lists every
    document copy the output was read from, transitively. `value_tables` are
    those of the readings the selection reaches, and without
    `application_ids` every table the documents print. `answer_messages` are
    those the selected answers take. `conflicts` lists the identities read
    two ways that disagree. `vendors` names the vendor ids used."""

    undefined_policy: model.UndefinedPolicy
    strict: bool
    documents: tuple[str, ...]
    version: str | None
    application_ids: tuple[int, ...]
    resolved: tuple[Document, ...]
    vendors: tuple[Vendor, ...]
    applications: tuple[Application, ...]
    answer_messages: tuple[AnswerMessage, ...]
    avps: tuple[Avp, ...]
    holes: tuple[Hole, ...]
    value_tables: tuple[ValueTable, ...]
    conflicts: tuple[Conflict, ...]


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


class HoleError(model.ModelError):
    """A strict build reached names the corpus cannot complete; `holes` lists
    them."""

    def __init__(self, holes: Sequence[model.Hole]) -> None:
        self.holes = tuple(holes)
        listing = "".join(f"\n  {hole}" for hole in self.holes)
        count = f"{len(self.holes)} hole{'' if len(self.holes) == 1 else 's'}"
        super().__init__(
            f"strict: the selection reaches {count} the corpus cannot complete"
            f" (a sidecar or an alias answers for an undefined name):{listing}"
        )


def avp_id(built: model.Model, avp: model.Avp) -> str:
    """The dictionary's `id` for `avp`, one of `built`'s readings: `vendor:code`
    for the defining document's reading, else `vendor:code@read_through`,
    with ` in DOCUMENT` where the reading is defined elsewhere than it is read
    through and ` via DOCUMENT` where a citation outside the citing release
    reached it.

    A reading is read through one copy at most once, so these tell every
    reading the corpus resolves apart; versions come in where a document is an
    older copy, as "TS32.299 V11.20.0"."""
    base = f"{avp.vendor_id}:{avp.code}"
    if avp == built.definition(avp.identity):
        return base
    identifier = f"{base}@{avp.read_through}"
    if avp.document != avp.read_through:
        identifier += f" in {avp.document}"
    if avp.across_releases is not None:
        identifier += f" via {avp.across_releases.citing}"
    return identifier


def _hole_id(hole: model.Hole) -> str:
    return f"{hole.document}/{hole.name}"


def _answer_id(answer: model.AnswerMessage) -> str:
    return f"{answer.read_through}/{answer.defined_in}:{answer.section}"


def _application_id(application: model.Application) -> str:
    document = application.reference + (
        "" if application.version is None else f" V{application.version}"
    )
    number = "-" if application.application_id is None else application.application_id
    return f"{document}/{application.clause}/{number}"


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
        """Give each reading its `id` (`avp_id`)."""
        owners: dict[str, model.Avp] = {}
        for avp in self.readings:
            identifier = avp_id(self._built, avp)
            other = owners.setdefault(identifier, avp)
            if other != avp:
                raise model.ModelError(
                    f"two readings would both be {identifier}: {other!r} and"
                    f" {avp!r}; this is a bug in seanchai"
                )
            self.ids[avp] = identifier

    def member(self, member: model.Member) -> Member:
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
            placeholder=None
            if member.placeholder is None
            else _json.undefined_block(member.placeholder.undefined),
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
            if not _is_cut(member)
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
            basic_type=avp.basic_type,
            flag_rules=_json.flag_rules(avp.flag_rules),
            may_encrypt=avp.may_encrypt,
            defined_in=avp.defined_in,
            version=avp.version,
            section=avp.section,
            read_through=avp.read_through,
            completed_by=avp.completed_by,
            across_releases=_json.cross_release(avp.across_releases),
            supplied=avp.supplied,
            wireshark_name=avp.wireshark_name,
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


def _is_cut(member: model.Member) -> bool:
    """Whether a member is where the model cut a recursive body: no reading,
    hole or placeholder, and not the wildcard."""
    return (
        member.avp is None
        and member.hole is None
        and member.placeholder is None
        and member.name != "AVP"
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


def _pairs(application: model.Application) -> tuple[CommandPair, ...]:
    index = {id(message): at for at, message in enumerate(application.messages)}
    return tuple(
        CommandPair(
            command_code=command.command_code,
            requests=tuple(index[id(each)] for each in command.requests),
            answers=tuple(index[id(each)] for each in command.answers),
        )
        for command in application.commands
    )


def _application_fields(application: model.Application) -> dict[str, Any]:
    return {
        "id": _application_id(application),
        "reference": application.reference,
        "version": application.version,
        "application_id": application.application_id,
        "clause": application.clause,
        "name": application.name,
        "stated_in": application.stated_in,
    }


def _value(fields: dict[str, Any]) -> Value:
    """`Enumerated.to_dict`'s line, every field of `Value` present."""
    return Value.model_validate({name: fields.get(name) for name in Value.model_fields})


class _Tables:
    """The value tables an output holds, each with the readings and
    applications it was met with."""

    def __init__(self) -> None:
        self.met: dict[model.ValueTable, tuple[dict[model.Avp, None], dict[str, None]]]
        self.met = {}

    def add(
        self,
        table: model.ValueTable,
        avps: Iterable[model.Avp] = (),
        application: str | None = None,
    ) -> None:
        readings, applications = self.met.setdefault(table, ({}, {}))
        readings.update(dict.fromkeys(avps))
        if application is not None:
            applications[application] = None

    def entries(self, built: model.Model, builder: _Builder) -> tuple[ValueTable, ...]:
        found = []
        for table, (readings, applications) in self.met.items():
            ids = [builder.ids[avp] for avp in readings if avp in builder.ids]
            if not ids:
                # A table only its document's listing holds: name that
                # document's reading, where the output has it.
                own = built.resolve(table.reference, table.avp, version=table.version)
                if own is not None and own in builder.ids:
                    ids.append(builder.ids[own])
            found.append(
                ValueTable(
                    kind=table.kind,
                    avp=table.avp,
                    avp_ids=tuple(sorted(set(ids))),
                    applications=tuple(sorted(applications)),
                    reference=table.reference,
                    version=table.version,
                    vendor_id=table.vendor_id,
                    section=table.section,
                    page=table.page,
                    table=table.table,
                    application=table.application,
                    feature_list_id=table.feature_list_id,
                    rows=tuple(
                        ValueRow(
                            name=row.name,
                            value=row.value,
                            section=row.section,
                            mark=row.mark,
                        )
                        for row in table.rows
                    ),
                )
            )
        return tuple(
            sorted(
                found,
                key=lambda each: (
                    each.reference,
                    each.version or "",
                    ast.section_sort_key(each.section),
                    each.table or "",
                    each.avp,
                    each.application or "",
                    -1 if each.feature_list_id is None else each.feature_list_id,
                ),
            )
        )


class _Paths:
    """Where each reading is met, over every application and error answer
    the output holds."""

    def __init__(self) -> None:
        self.at: dict[model.Avp, dict[Path, None]] = {}

    def add(self, reached: model.Reached, application: str | None) -> None:
        for met in reached.readings:
            paths = self.at.setdefault(met.avp, {})
            for where in met.paths:
                path = Path(
                    application=application,
                    command=where.command,
                    section=where.section,
                    names=where.names,
                )
                paths[path] = None


_SPELLED = re.compile(r"^(?P<reference>\S+) V(?P<version>\S+)$")


class _Resolved:
    """The document copies an output was read from."""

    def __init__(self, built: model.Model) -> None:
        self._built = built
        self.copies: dict[tuple[str, str | None], None] = {}

    def document(self, spelled: str) -> None:
        """A document as `Hole.document` spells it: its newest copy, or the
        version it names."""
        found = _SPELLED.match(spelled)
        if found is not None:
            self.copies[found["reference"], found["version"]] = None
        else:
            self.copy(spelled, None)

    def copy(self, reference: str, version: str | None) -> None:
        if version is None:
            # A document the corpus cites and does not hold stays versionless.
            with contextlib.suppress(model.ModelError):
                version = self._built.version(reference)
        self.copies[reference, version] = None

    def avp(self, avp: model.Avp) -> None:
        self.document(avp.document)
        self.document(avp.read_through)
        for _, stating in avp.completed_by:
            self.document(stating)
        self.crossing(avp.across_releases)

    def hole(self, hole: model.Hole) -> None:
        self.document(hole.document)
        self.crossing(hole.across_releases)

    def crossing(self, crossing: corpus.CrossRelease | None) -> None:
        if crossing is not None:
            self.copies[crossing.cited, crossing.version] = None

    def entries(self) -> tuple[Document, ...]:
        return tuple(
            Document(reference=reference, version=version)
            for reference, version in sorted(
                self.copies, key=lambda each: (each[0], each[1] or "")
            )
        )


def _vendors(avps: Iterable[Avp], holes: Iterable[Hole]) -> tuple[Vendor, ...]:
    used = {avp.vendor_id for avp in avps} | {
        hole.vendor_id for hole in holes if hole.vendor_id is not None
    }
    return tuple(
        Vendor(
            vendor_id=vendor_id,
            name=None if known is None else known.name,
            source=None if known is None else known.source,
        )
        for vendor_id in sorted(used)
        for known in [model.VENDORS.get(vendor_id)]
    )


def _conflicts(
    built: model.Model, builder: _Builder, paths: _Paths
) -> tuple[Conflict, ...]:
    by_identity: dict[tuple[int, int], list[model.Avp]] = {}
    for avp in builder.readings:
        by_identity.setdefault(avp.identity, []).append(avp)
    found = []
    for identity in sorted(by_identity):
        readings = sorted(by_identity[identity], key=lambda avp: builder.ids[avp])
        if len(readings) < 2:
            continue
        defining = built.definition(identity)
        reached = model.Reached(
            vendor_id=identity[0],
            code=identity[1],
            definition=defining,
            readings=tuple(model.Met(avp, ()) for avp in readings),
        )
        if not reached.conflicts:
            continue
        obsoleted = {avp: _obsoleted_by(built, avp) for avp in readings}
        current = [avp for avp in readings if not obsoleted[avp]]
        found.append(
            Conflict(
                vendor_id=identity[0],
                code=identity[1],
                defining=builder.ids.get(defining) if defining is not None else None,
                fields=reached.conflicts,
                obsolete=bool(current)
                and not model.Reached(
                    vendor_id=identity[0],
                    code=identity[1],
                    definition=defining,
                    readings=tuple(model.Met(avp, ()) for avp in current),
                ).conflicts,
                readings=tuple(
                    ConflictingReading(
                        avp=builder.ids[avp],
                        obsoleted_by=obsoleted[avp],
                        paths=tuple(paths.at.get(avp, ())),
                    )
                    for avp in readings
                ),
            )
        )
    return tuple(found)


def _obsoleted_by(built: model.Model, avp: model.Avp) -> tuple[str, ...]:
    """The documents obsoleting the one `avp` is defined in or read through."""
    documents = {avp.defined_in, _SPELLED.sub(r"\g<reference>", avp.read_through)}
    return tuple(
        sorted({newer for each in documents for newer in built.obsoleted_by(each)})
    )


def _marks(
    built: model.Model, builder: _Builder, application: model.Application
) -> tuple[Marks, ...]:
    names = dict.fromkeys(member.name for member in application.walk())
    found = []
    for name in names:
        marked = [
            each
            for each in built.marks(
                application.reference, name, version=application.version
            )
            if ast.interface_clause(each.section) == application.clause
        ]
        if not marked:
            continue
        reading = built.resolve(
            application.reference, name, version=application.version
        )
        for each in marked:
            found.append(
                Marks(
                    name=name,
                    avp=None if reading is None else builder.ids.get(reading),
                    table=each.table,
                    section=each.section,
                    marks=dict(each.marks),
                )
            )
    return tuple(found)


def build(
    built: model.Model,
    *,
    corpus_version: str | None = None,
    documents: Sequence[str] = (),
    application_ids: Sequence[int] = (),
    version: str | None = None,
    strict: bool = False,
) -> Dictionary:
    """Build the dictionary of `built`, limited to `documents` and
    `application_ids` (all when not given). `version` reads an older held
    copy of the one document `documents` names.

    AVPs are those the selected commands and their error answers use at any
    depth; without `application_ids`, also those the selected documents'
    tables list. Value tables are those of the readings met, and the
    application's document's own for the names it reaches, a feature list
    only for its application; without `application_ids`, also every table the
    documents print. An id no selected document uses raises
    `model.ModelError`; with `strict`, so does any hole the output would hold
    (`HoleError`).
    """
    if version is not None and len(documents) != 1:
        raise model.ModelError("version= reads one document: name it, and only it")
    references = tuple(
        sorted({built.canonical(each) for each in documents}) or built.references()
    )
    applications = [
        application
        for reference in references
        for application in built.applications(reference, version=version)
        if not application_ids or application.application_id in application_ids
    ]
    found = {application.application_id for application in applications}
    if unknown := sorted(set(application_ids) - found):
        raise model.ModelError(
            f"no application {', '.join(map(str, unknown))} in"
            f" {', '.join(references)}: `seanchai commands` lists them"
        )
    builder = _Builder(built)
    tables = _Tables()
    paths = _Paths()
    resolved = _Resolved(built)
    # What the answers of each document holding a selected command take.
    answers = {
        reference: built.answer_message(reference, version=version)
        for reference in sorted({application.reference for application in applications})
    }
    taken = {
        _answer_id(answer): answer
        for application in applications
        if any(not message.is_request for message in application.messages)
        and (answer := answers[application.reference]) is not None
    }
    for application in applications:
        identifier = _application_id(application)
        resolved.copy(application.reference, application.version)
        for message in application.messages:
            builder.hold_members((*message.avps, *message.dropped))
        for reached in built.reached(application):
            paths.add(reached, identifier)
            readings = [met.avp for met in reached.readings]
            for table in reached.value_tables:
                tables.add(table, readings, identifier)
    for answer in taken.values():
        resolved.document(answer.defined_in)
        builder.hold_members((*answer.avps, *answer.dropped))
        for reached in built.reached(answer):
            paths.add(reached, None)
            readings = [met.avp for met in reached.readings]
            for table in reached.value_tables:
                tables.add(table, readings)
    if not application_ids:
        for reference in references:
            listed = built.avps(reference, version=version)
            builder.hold(listed)
            for avp in listed:
                for table in avp.value_tables:
                    tables.add(table, (avp,))
            for table in built.value_tables(reference, version=version):
                tables.add(table)
            for hole in built.holes(reference, version=version):
                builder.holes.setdefault(_hole_id(hole), hole)
    if strict and builder.holes:
        raise HoleError([builder.holes[each] for each in sorted(builder.holes)])
    builder.number()
    for avp in builder.readings:
        resolved.avp(avp)
    for hole in builder.holes.values():
        resolved.hole(hole)
    for table in tables.met:
        resolved.copy(table.reference, table.version)
    avps = tuple(builder.avp(avp) for avp in _in_order(builder))
    holes = _holes(builder)
    return Dictionary(
        format_version=FORMAT_VERSION,
        seanchai_version=__version__,
        corpus_version=corpus_version,
        undefined_policy=built.undefined_policy,
        strict=strict,
        documents=references,
        version=version,
        application_ids=tuple(sorted(set(application_ids))),
        resolved=resolved.entries(),
        vendors=_vendors(avps, holes),
        applications=tuple(
            Application(
                **_application_fields(application),
                commands=tuple(
                    builder.command(each, answers[application.reference])
                    for each in application.messages
                ),
                pairs=_pairs(application),
                marks=_marks(built, builder, application),
            )
            for application in applications
        ),
        answer_messages=tuple(builder.answer(taken[each]) for each in sorted(taken)),
        avps=avps,
        holes=holes,
        value_tables=tables.entries(built, builder),
        conflicts=_conflicts(built, builder, paths),
    )


def _in_order(builder: _Builder) -> list[model.Avp]:
    """The readings by identity, the defining one first, then by `id`."""
    return sorted(
        builder.readings,
        key=lambda avp: (
            avp.vendor_id,
            avp.code,
            "@" in builder.ids[avp],
            builder.ids[avp],
        ),
    )


def _holes(builder: _Builder) -> tuple[Hole, ...]:
    return tuple(
        Hole.model_validate({**dict(_json.hole(hole)), "id": identifier})
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
    tables = _Tables()
    for reading in readings:
        for table in reading.value_tables:
            tables.add(table, (reading,))
    return Lookup(
        format_version=FORMAT_VERSION,
        seanchai_version=__version__,
        corpus_version=corpus_version,
        undefined_policy=built.undefined_policy,
        avp=builder.ids[avp],
        avps=tuple(builder.avp(each) for each in (*readings, *named)),
        holes=_holes(builder),
        value_tables=tables.entries(built, builder),
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
                **_application_fields(application),
                commands=tuple(_heading(each) for each in application.messages),
                pairs=_pairs(application),
            )
            for application in applications
        ),
    )


def dumps(dictionary: Dictionary | Lookup | Listing) -> str:
    """The file's text: compact, keys sorted, every field written, one final
    newline."""
    return _json.dumps(dictionary, exclude_defaults=False)


def json_schema() -> dict[str, Any]:
    """The JSON Schema of the three documents this module writes: a
    `Dictionary`, a `Lookup` or a `Listing`."""
    roots = (Dictionary, Lookup, Listing)
    _, schema = models_json_schema(
        [(root, "validation") for root in roots], title="Seanchaí dictionary"
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **schema,
        "oneOf": [{"$ref": f"#/$defs/{root.__name__}"} for root in roots],
    }
