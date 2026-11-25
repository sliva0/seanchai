"""What changed between two versions of a document, or two corpora, for a
Diameter stack: not the text, but the commands, members, AVPs, flags, types
and values a codec or a validator holds.

`compare` takes two dictionaries (`seanchai.dictionary.build`) and lists their
differences as `Change`s. Commands match by application id, command code and
direction, AVPs by `(vendor-id, code)` and the document they are read through,
members by the AVP they name, values by number, so a rename is a rename and
not a removal and an addition. Each change says whether it breaks the wire
(`breaking`), keeps old peers working (`compatible`) or changes only words
(`editorial`), and the command paths it affects.

`diff` builds both dictionaries from two models. Given each side's raw mirror,
it also says where a change comes from: the `document` (the raw files differ
the same way, across versions), our `extraction` (they differ, the version
being the same) or our `corrections` (they do not differ).

`overlay` reads one document's file in place of a corpus's copy, for diffing
an older version the corpus does not hold.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

import pydantic
from pydantic.json_schema import models_json_schema

from . import __version__, dictionary, model
from .corpus import Corpus, Entry, Rules
from .dad import ast

__all__ = [
    "FORMAT_VERSION",
    "Change",
    "Diff",
    "Side",
    "Where",
    "compare",
    "diff",
    "dumps",
    "json_schema",
    "overlay",
    "render",
]

# Changes when a reader would have to.
FORMAT_VERSION = 1

type Impact = Literal["breaking", "compatible", "editorial"]
type Origin = Literal["document", "corrections", "extraction"]
type Kind = Literal[
    "application-added",
    "application-removed",
    "command-added",
    "command-removed",
    "command-renamed",
    "command-flags",
    "member-added",
    "member-removed",
    "member-presence",
    "member-occurrence",
    "member-order",
    "avp-added",
    "avp-removed",
    "avp-renamed",
    "avp-kind",
    "avp-type",
    "avp-flags",
    "avp-encrypt",
    "value-added",
    "value-removed",
    "value-renamed",
    "value-voided",
    "value-range",
    "row-added",
    "row-removed",
    "row-renamed",
    "element-added",
    "element-removed",
    "element-renamed",
    "element-category",
    "result-code-added",
    "result-code-removed",
    "constraint-added",
    "constraint-removed",
    "constraint-changed",
    "hole-added",
    "hole-removed",
]
_IMPACTS: tuple[Impact, ...] = ("breaking", "compatible", "editorial")


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class Where(_Model):
    """Where a side states what changed: the document, its version and the
    clause."""

    reference: str
    version: str | None
    section: str | None


class Change(_Model):
    """One difference. `subject` names what changed, as `S6a/ULR` for a
    command, `ULR-Flags (10415:1405)` for an AVP, or the member path from the
    command down; `field` the part of it, where there is one; `before` and
    `after` each side's value as text, null where a side has none. `impact`
    is `breaking` where a peer built on one side rejects or misreads what the
    other sends, `compatible` where old peers keep working (an optional
    member, a new value), `editorial` where only a name or a description
    changed. `origin` is null where `diff` had no raw mirrors to tell.
    `paths` are the command paths it affects, from the side holding it (the
    new one where both do), at most `_PATHS` of them."""

    kind: Kind
    impact: Impact
    origin: Origin | None
    subject: str
    field: str | None
    before: str | None
    after: str | None
    old: Where | None
    new: Where | None
    paths: tuple[str, ...]


class Side(_Model):
    """What one side was built from: the corpus version where installed, the
    3GPP release the corpus was read at, and each selected document's copy."""

    corpus_version: str | None
    release: int | None
    documents: tuple[dictionary.Document, ...]


class Diff(_Model):
    """`seanchai diff --json`: both sides, the number of changes by impact,
    and the changes, breaking first, each kind in a fixed order."""

    format_version: Annotated[int, pydantic.Field(ge=FORMAT_VERSION, le=FORMAT_VERSION)]
    seanchai_version: str
    old: Side
    new: Side
    counts: dict[str, int]
    changes: tuple[Change, ...]


# How many paths a change lists.
_PATHS = 8


# --- comparing two dictionaries -----------------------------------------


@dataclasses.dataclass(frozen=True)
class _Found:
    """A change with what matches it against another diff: its kind, the
    subject's identity and the field, and both values."""

    key: tuple[Any, ...]
    change: Change


def compare(old: dictionary.Dictionary, new: dictionary.Dictionary) -> list[Change]:
    """Every difference between `old` and `new`, in the order `render` lists
    them, without origins."""
    return [found.change for found in _ordered(_Comparison(old, new).run())]


def _ordered(found: Iterable[_Found]) -> list[_Found]:
    kinds = Kind.__value__.__args__  # pyright: ignore[reportAttributeAccessIssue]
    return sorted(
        found,
        key=lambda each: (
            _IMPACTS.index(each.change.impact),
            kinds.index(each.change.kind),
            each.change.subject,
            each.change.field or "",
            each.change.before or "",
            each.change.after or "",
        ),
    )


type _Identity = tuple[int, int]


class _Side:
    """One dictionary, indexed."""

    def __init__(self, built: dictionary.Dictionary) -> None:
        self.built = built
        self.avps = {avp.id: avp for avp in built.avps}
        self.holes = {hole.id: hole for hole in built.holes}
        # Readings by identity, each by the document it is read through.
        self.readings: dict[_Identity, dict[str, dictionary.Avp]] = {}
        for avp in built.avps:
            self.readings.setdefault((avp.vendor_id, avp.code), {})[
                avp.read_through
            ] = avp
        self.applications: dict[tuple[str, int | None], list[dictionary.Application]]
        self.applications = {}
        for application in built.applications:
            self.applications.setdefault(
                (application.reference, application.application_id), []
            ).append(application)
        self.paths = _paths(built)
        # Each document's version where the output reads one copy of it; the
        # dictionary leaves the newest copy's out of most entries.
        copies: dict[str, set[str | None]] = {}
        for document in built.resolved:
            copies.setdefault(document.reference, set()).add(document.version)
        self.versions = {
            reference: next(iter(versions))
            for reference, versions in copies.items()
            if len(versions) == 1
        }

    def located(self, where: Where | None) -> Where | None:
        if where is None or where.version is not None:
            return where
        return where.model_copy(update={"version": self.versions.get(where.reference)})

    def member_key(self, member: dictionary.Member) -> tuple[Any, ...]:
        if member.kind == "avp" and member.avp is not None:
            avp = self.avps[member.avp]
            return ("avp", avp.vendor_id, avp.code)
        return (member.kind, member.name)

    def where_avp(self, avp: dictionary.Avp) -> Where:
        return Where(
            reference=avp.read_through, version=avp.version, section=avp.section
        )


def _application_name(application: dictionary.Application) -> str:
    return application.name or (
        f"{application.reference} {application.application_id}"
        if application.application_id is not None
        else application.reference
    )


def _command_name(
    application: dictionary.Application, command: dictionary.Command
) -> str:
    return f"{_application_name(application)}/{command.abbreviation}"


def _by_document(
    olds: dict[str, dictionary.Avp],
    news: dict[str, dictionary.Avp],
    pairs: list[tuple[dictionary.Avp, dictionary.Avp]],
) -> list[tuple[dictionary.Avp, dictionary.Avp]]:
    """The readings `pairs` leaves unpaired, each paired with the other side's
    reading through a copy of the same document. Two readings of a corpus at
    different releases read one copy under two spellings: Release 18's reads
    TS 29.061 V19.1.0, which a citation reaches outside it, as
    `TS29.061 V19.1.0` and Release 19's as `TS29.061`, beside Release 18's own
    copy, `TS29.061`, which also stands against it."""

    def document(through: str) -> str:
        return through.partition(" V")[0]

    paired_old = {old.id for old, _ in pairs}
    paired_new = {new.id for _, new in pairs}
    found = []
    for through, old in sorted(olds.items()):
        if old.id in paired_old:
            continue
        match = news.get(document(through)) or next(
            (
                new
                for key, new in sorted(news.items())
                if document(key) == document(through)
            ),
            None,
        )
        if match is not None:
            found.append((old, match))
    matched = {new.id for _, new in found}
    for through, new in sorted(news.items()):
        if new.id in paired_new or new.id in matched:
            continue
        match = olds.get(document(through)) or next(
            (
                old
                for key, old in sorted(olds.items())
                if document(key) == document(through)
            ),
            None,
        )
        if match is not None:
            found.append((match, new))
    return found


def _paths(built: dictionary.Dictionary) -> dict[_Identity, list[str]]:
    """Every command path reaching each identity, as `S6a/ULR >
    Subscription-Data > AMBR`, breadth first, at most `_PATHS` each."""
    avps = {avp.id: avp for avp in built.avps}
    found: dict[_Identity, list[str]] = {}
    for application in built.applications:
        for command in application.commands:
            queue: list[tuple[str, tuple[dictionary.Member, ...], frozenset[str]]] = [
                (_command_name(application, command), command.members, frozenset())
            ]
            while queue:
                prefix, members, seen = queue.pop(0)
                for member in members:
                    if member.avp is None:
                        continue
                    avp = avps[member.avp]
                    path = f"{prefix} > {avp.name}"
                    listed = found.setdefault((avp.vendor_id, avp.code), [])
                    if len(listed) < _PATHS and path not in listed:
                        listed.append(path)
                    if avp.members and avp.id not in seen:
                        queue.append((path, avp.members, seen | {avp.id}))
    return found


def _flags(rules: dictionary.FlagRules, flag: ast.AvpFlag) -> str:
    """Where a flag's rule places it: `must`, `may`, `should not`, `must
    not`, `application` or `unstated`."""
    for column, name in (
        (rules.must, "must"),
        (rules.may, "may"),
        (rules.should_not, "should not"),
        (rules.must_not, "must not"),
        (rules.application_defined, "application"),
    ):
        if flag in column:
            return name
    return "unstated"


def _occurs(member: dictionary.Member) -> str:
    high = "*" if member.max_occurs is None else str(member.max_occurs)
    return f"{member.min_occurs}..{high}"


def _value_text(value: dictionary.Value) -> str:
    if value.kind == "value":
        return f"{value.name} ({value.value})"
    return f"{value.kind} {value.first}..{value.last}"


def _rule_text(rule: dictionary.Rule) -> str:
    return json.dumps(
        rule.model_dump(mode="json", exclude_defaults=True), sort_keys=True
    )


class _Comparison:
    def __init__(self, old: dictionary.Dictionary, new: dictionary.Dictionary) -> None:
        self.old = _Side(old)
        self.new = _Side(new)
        self.found: list[_Found] = []

    def add(
        self,
        kind: Kind,
        impact: Impact,
        subject: str,
        key: tuple[Any, ...],
        *,
        field: str | None = None,
        before: str | None = None,
        after: str | None = None,
        old: Where | None = None,
        new: Where | None = None,
        where: Mapping[str, Where | None] | None = None,
        paths: Sequence[str] = (),
    ) -> None:
        if where is not None:
            old, new = where["old"], where["new"]
        self.found.append(
            _Found(
                (kind, *key, field, before, after),
                Change(
                    kind=kind,
                    impact=impact,
                    origin=None,
                    subject=subject,
                    field=field,
                    before=before,
                    after=after,
                    old=self.old.located(old),
                    new=self.new.located(new),
                    paths=tuple(paths[:_PATHS]),
                ),
            )
        )

    def run(self) -> list[_Found]:
        self.applications()
        self.avps()
        self.value_tables()
        self.constraints()
        self.holes()
        return self.found

    # Commands.

    def applications(self) -> None:
        for key in sorted(
            self.old.applications.keys() | self.new.applications.keys(),
            key=lambda key: (key[0], -1 if key[1] is None else key[1]),
        ):
            olds = self.old.applications.get(key, [])
            news = self.new.applications.get(key, [])
            if not olds or not news:
                application = (olds or news)[0]
                added = not olds
                self.add(
                    "application-added" if added else "application-removed",
                    "compatible" if added else "breaking",
                    _application_name(application),
                    ("application", *key),
                    old=None if added else _application_where(application),
                    new=_application_where(application) if added else None,
                )
                continue
            self.commands(olds, news)

    def commands(
        self,
        olds: list[dictionary.Application],
        news: list[dictionary.Application],
    ) -> None:
        def indexed(
            applications: list[dictionary.Application],
        ) -> dict[tuple[int, bool, int], tuple[dictionary.Application, Any]]:
            found: dict[tuple[int, bool, int], tuple[dictionary.Application, Any]] = {}
            for application in applications:
                for command in application.commands:
                    ordinal = 0
                    while (command.command_code, command.is_request, ordinal) in found:
                        ordinal += 1
                    found[command.command_code, command.is_request, ordinal] = (
                        application,
                        command,
                    )
            return found

        before, after = indexed(olds), indexed(news)
        for key in sorted(before.keys() | after.keys()):
            identity = ("command", olds[0].reference, olds[0].application_id, *key)
            if key not in after or key not in before:
                application, command = before.get(key) or after[key]
                added = key not in before
                self.add(
                    "command-added" if added else "command-removed",
                    "compatible" if added else "breaking",
                    _command_name(application, command),
                    identity,
                    old=None if added else _command_where(application, command),
                    new=_command_where(application, command) if added else None,
                )
                continue
            (old_application, old), (new_application, new) = before[key], after[key]
            subject = _command_name(new_application, new)
            where = {
                "old": _command_where(old_application, old),
                "new": _command_where(new_application, new),
            }
            if (old.name, old.abbreviation) != (new.name, new.abbreviation):
                self.add(
                    "command-renamed",
                    "editorial",
                    subject,
                    identity,
                    before=f"{old.name} ({old.abbreviation})",
                    after=f"{new.name} ({new.abbreviation})",
                    where=where,
                )
            if old.flags != new.flags:
                self.add(
                    "command-flags",
                    "breaking",
                    subject,
                    identity,
                    before=", ".join(old.flags) or "none",
                    after=", ".join(new.flags) or "none",
                    where=where,
                )
            self.members(old.members, new.members, subject, identity, where, [subject])
            self.elements(old, new, subject, identity, where)
            self.result_codes(old, new, subject, identity)

    def result_codes(
        self,
        old: dictionary.Command,
        new: dictionary.Command,
        subject: str,
        identity: tuple[Any, ...],
    ) -> None:
        """The codes the tables of a command's result codes list, by name:
        a list no table says is all an answer carries, so a change is
        editorial."""
        before = {code.name: code for code in old.result_codes}
        after = {code.name: code for code in new.result_codes}
        for name in sorted(before.keys() ^ after.keys()):
            was, now = before.get(name), after.get(name)
            code = now or was
            assert code is not None
            self.add(
                "result-code-added" if was is None else "result-code-removed",
                "editorial",
                f"{subject} result code {name}",
                (*identity, "result-code", name),
                before=None if was is None else str(was.value),
                after=None if now is None else str(now.value),
                where={
                    "old": None if was is None else _code_where(was),
                    "new": None if now is None else _code_where(now),
                },
            )

    def members(
        self,
        olds: Sequence[dictionary.Member],
        news: Sequence[dictionary.Member],
        subject: str,
        identity: tuple[Any, ...],
        where: Mapping[str, Where],
        paths: Sequence[str],
    ) -> None:
        """A body's members, matched by the AVP each names."""

        def keyed(
            side: _Side, members: Sequence[dictionary.Member]
        ) -> dict[tuple[Any, ...], dictionary.Member]:
            found: dict[tuple[Any, ...], dictionary.Member] = {}
            for member in members:
                key = side.member_key(member)
                while key in found:
                    key = (*key, "again")
                found[key] = member
            return found

        before, after = keyed(self.old, olds), keyed(self.new, news)
        # A name one side completes and the other leaves a hole is one member;
        # the holes say what changed.
        by_name = {
            member.name: key for key, member in after.items() if key not in before
        }
        for key, member in list(before.items()):
            other = by_name.get(member.name)
            if key not in after and other is not None and "hole" in (key[0], other[0]):
                after[key] = after.pop(other)
        wildcard = any(member.kind == "wildcard" for member in news)
        for key in [*before, *(key for key in after if key not in before)]:
            old, new = before.get(key), after.get(key)
            present = new or old
            assert present is not None
            named = f"{subject} > {present.name}"
            member_identity = (*identity, *key)
            member_paths = [f"{path} > {present.name}" for path in paths]
            if old is None or new is None:
                optional = present.presence == "optional"
                if new is None:
                    impact: Impact = (
                        "compatible" if optional and wildcard else "breaking"
                    )
                else:
                    impact = "compatible" if optional else "breaking"
                self.add(
                    "member-added" if old is None else "member-removed",
                    impact,
                    named,
                    member_identity,
                    before=None if old is None else _member_text(old),
                    after=None if new is None else _member_text(new),
                    paths=member_paths,
                    where=where,
                )
                continue
            if old.presence != new.presence:
                self.add(
                    "member-presence",
                    "breaking",
                    named,
                    member_identity,
                    field="presence",
                    before=old.presence,
                    after=new.presence,
                    paths=member_paths,
                    where=where,
                )
            elif (old.min_occurs, old.max_occurs) != (new.min_occurs, new.max_occurs):
                self.add(
                    "member-occurrence",
                    "breaking",
                    named,
                    member_identity,
                    field="occurrence",
                    before=_occurs(old),
                    after=_occurs(new),
                    paths=member_paths,
                    where=where,
                )
        fixed_before = [
            self.old.member_key(member) for member in olds if member.presence == "fixed"
        ]
        fixed_after = [
            self.new.member_key(member) for member in news if member.presence == "fixed"
        ]
        common = set(fixed_before) & set(fixed_after)
        if [key for key in fixed_before if key in common] != [
            key for key in fixed_after if key in common
        ]:
            self.add(
                "member-order",
                "breaking",
                subject,
                (*identity, "order"),
                field="fixed members",
                before=", ".join(m.name for m in olds if m.presence == "fixed"),
                after=", ".join(m.name for m in news if m.presence == "fixed"),
                paths=paths,
                where=where,
            )

    def elements(
        self,
        old: dictionary.Command,
        new: dictionary.Command,
        subject: str,
        identity: tuple[Any, ...],
        where: Mapping[str, Where],
    ) -> None:
        """Information-element rows, matched by the AVPs each maps to (or its
        printed cell where it names none), the grouped AVP whose members
        their table describes and those the row is set off under. An
        element's name holds its citation, "(See 3GPP TS 29.229 [9])", which
        a document rewords."""

        def keyed(command: dictionary.Command) -> dict[tuple[Any, ...], Any]:
            found: dict[tuple[Any, ...], dictionary.Element] = {}
            for each in command.elements:
                key = (
                    each.within or "",
                    *each.parents,
                    *(each.avps or (each.printed or each.name or "",)),
                )
                while key in found:
                    key = (*key, "again")
                found[key] = each
            return found

        before, after = keyed(old), keyed(new)
        for key in sorted(before.keys() | after.keys()):
            was, now = before.get(key), after.get(key)
            element = now or was
            assert element is not None
            within = [*([element.within] if element.within else []), *element.parents]
            named = (
                f"{subject} element "
                + (", ".join(element.avps) or element.printed or element.name or "")
                + (f" within {' > '.join(within)}" if within else "")
            )
            element_where = {
                "old": None if was is None else _element_where(was),
                "new": None if now is None else _element_where(now),
            }
            if was is None or now is None:
                self.add(
                    "element-added" if was is None else "element-removed",
                    "editorial",
                    named,
                    (*identity, "element", *key),
                    before=None if was is None else str(was.category),
                    after=None if now is None else str(now.category),
                    where=element_where,
                )
            if was is not None and now is not None and was.name != now.name:
                self.add(
                    "element-renamed",
                    "editorial",
                    named,
                    (*identity, "element", *key),
                    before=was.name,
                    after=now.name,
                    where=element_where,
                )
            if was is not None and now is not None and was.category != now.category:
                self.add(
                    "element-category",
                    "breaking"
                    if ast.Category.MANDATORY in (was.category, now.category)
                    else "compatible",
                    named,
                    (*identity, "element", *key),
                    field="category",
                    before=str(was.category),
                    after=str(now.category),
                    where=element_where,
                )

    # AVPs.

    def avps(self) -> None:
        # A name one side leaves a hole is no AVP added or removed: the holes
        # say what changed.
        holes = [
            {hole.name for hole in side.built.holes} for side in (self.old, self.new)
        ]
        for identity in sorted(self.old.readings.keys() | self.new.readings.keys()):
            olds = {
                through: avp
                for through, avp in self.old.readings.get(identity, {}).items()
                if identity in self.new.readings or avp.name not in holes[1]
            }
            news = {
                through: avp
                for through, avp in self.new.readings.get(identity, {}).items()
                if identity in self.old.readings or avp.name not in holes[0]
            }
            pairs = [(olds[k], news[k]) for k in sorted(olds.keys() & news.keys())]
            if not pairs and len(olds) == 1 and len(news) == 1:
                pairs = [(next(iter(olds.values())), next(iter(news.values())))]
            pairs += _by_document(olds, news, pairs)
            paired_old = {old.id for old, _ in pairs}
            paired_new = {new.id for _, new in pairs}
            for old in olds.values():
                if old.id not in paired_old:
                    self.add(
                        "avp-removed",
                        "breaking",
                        _avp_subject(old),
                        ("avp", *identity, old.read_through),
                        old=self.old.where_avp(old),
                        paths=self.old.paths.get(identity, ()),
                    )
            for new in news.values():
                if new.id not in paired_new:
                    self.add(
                        "avp-added",
                        "compatible",
                        _avp_subject(new),
                        ("avp", *identity, new.read_through),
                        new=self.new.where_avp(new),
                        paths=self.new.paths.get(identity, ()),
                    )
            for old, new in pairs:
                self.avp(old, new, identity)

    def avp(
        self, old: dictionary.Avp, new: dictionary.Avp, identity: _Identity
    ) -> None:
        subject = _avp_subject(new)
        key = ("avp", *identity, new.read_through)
        where = {"old": self.old.where_avp(old), "new": self.new.where_avp(new)}
        paths = self.new.paths.get(identity, ())

        def add(kind: Kind, impact: Impact, **fields: Any) -> None:
            self.add(kind, impact, subject, key, paths=paths, where=where, **fields)

        if old.name != new.name:
            add("avp-renamed", "editorial", before=old.name, after=new.name)
        if old.kind != new.kind:
            add("avp-kind", "breaking", before=old.kind, after=new.kind)
        if old.data_type != new.data_type:
            add(
                "avp-type",
                "breaking" if old.basic_type != new.basic_type else "compatible",
                field="data type",
                before=old.data_type,
                after=new.data_type,
            )
        for flag in ast.AvpFlag:
            was = _flags(old.flag_rules, flag)
            now = _flags(new.flag_rules, flag)
            if was != now:
                add(
                    "avp-flags",
                    "breaking"
                    if flag in (ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR)
                    else "compatible",
                    field=f"{flag} bit",
                    before=was,
                    after=now,
                )
        if old.may_encrypt != new.may_encrypt:
            add(
                "avp-encrypt",
                "editorial",
                before=str(old.may_encrypt),
                after=str(new.may_encrypt),
            )
        self.members(
            old.members,
            new.members,
            subject,
            key,
            where,
            paths or [subject],
        )
        self.values(old.values, new.values, subject, key, where, paths)

    def values(
        self,
        olds: Sequence[dictionary.Value],
        news: Sequence[dictionary.Value],
        subject: str,
        key: tuple[Any, ...],
        where: Mapping[str, Where],
        paths: Sequence[str],
    ) -> None:
        """An enumerated AVP's values by number, and its ranges."""
        before = {v.value: v for v in olds if v.kind == "value"}
        after = {v.value: v for v in news if v.kind == "value"}
        voided = [v for v in news if v.kind in ("void", "reserved")]

        def withdrawn(number: int | None) -> bool:
            return number is not None and any(
                v.first is not None
                and v.last is not None
                and v.first <= number <= v.last
                for v in voided
            )

        for number in sorted(
            (before.keys() | after.keys()) - {None},
            key=lambda n: -1 if n is None else n,
        ):
            was, now = before.get(number), after.get(number)
            field = f"value {number}"
            if was is not None and now is None:
                self.add(
                    "value-voided" if withdrawn(number) else "value-removed",
                    "breaking",
                    subject,
                    key,
                    field=field,
                    before=_value_text(was),
                    paths=paths,
                    where=where,
                )
            elif was is None and now is not None:
                self.add(
                    "value-added",
                    "compatible",
                    subject,
                    key,
                    field=field,
                    after=_value_text(now),
                    paths=paths,
                    where=where,
                )
            elif was is not None and now is not None and was.name != now.name:
                self.add(
                    "value-renamed",
                    "editorial",
                    subject,
                    key,
                    field=field,
                    before=was.name,
                    after=now.name,
                    paths=paths,
                    where=where,
                )
        ranges_before = sorted(_value_text(v) for v in olds if v.kind != "value")
        ranges_after = sorted(_value_text(v) for v in news if v.kind != "value")
        if ranges_before != ranges_after:
            self.add(
                "value-range",
                "compatible",
                subject,
                key,
                field="ranges",
                before=", ".join(ranges_before) or None,
                after=", ".join(ranges_after) or None,
                paths=paths,
                where=where,
            )

    # Value tables, constraints and holes.

    def value_tables(self) -> None:
        def keyed(
            built: dictionary.Dictionary,
        ) -> dict[tuple[Any, ...], dictionary.ValueTable]:
            found = {}
            for table in built.value_tables:
                key = (
                    table.kind,
                    table.avp,
                    table.vendor_id,
                    table.reference,
                    table.application,
                    table.feature_list_id,
                )
                while key in found:
                    key = (*key, "again")
                found[key] = table
            return found

        before, after = keyed(self.old.built), keyed(self.new.built)
        for key in sorted(before.keys() | after.keys(), key=repr):
            was, now = before.get(key), after.get(key)
            table = now or was
            assert table is not None
            subject = f"{table.kind} {table.avp} in {table.reference}" + (
                f" ({table.application})" if table.application else ""
            )
            where = {
                "old": None if was is None else _table_where(was),
                "new": None if now is None else _table_where(now),
            }
            rows_before = {row.value: row for row in was.rows} if was else {}
            rows_after = {row.value: row for row in now.rows} if now else {}
            for number in sorted(rows_before.keys() | rows_after.keys()):
                old_row, new_row = rows_before.get(number), rows_after.get(number)
                field = f"{number}"
                if old_row is None and new_row is not None:
                    self.add(
                        "row-added",
                        "compatible",
                        subject,
                        ("table", *key),
                        field=field,
                        after=new_row.name,
                        where=where,
                    )
                elif new_row is None and old_row is not None:
                    self.add(
                        "row-removed",
                        "breaking",
                        subject,
                        ("table", *key),
                        field=field,
                        before=old_row.name,
                        where=where,
                    )
                elif (
                    old_row is not None
                    and new_row is not None
                    and (old_row.name, old_row.mark) != (new_row.name, new_row.mark)
                ):
                    self.add(
                        "row-renamed",
                        "editorial",
                        subject,
                        ("table", *key),
                        field=field,
                        before=old_row.name
                        + (f" {old_row.mark}" if old_row.mark else ""),
                        after=new_row.name
                        + (f" {new_row.mark}" if new_row.mark else ""),
                        where=where,
                    )

    def constraints(self) -> None:
        def keyed(
            built: dictionary.Dictionary,
        ) -> dict[tuple[Any, ...], dictionary.Constraint]:
            return {
                (
                    c.reference,
                    c.avp,
                    c.command,
                    c.application_id,
                    c.command_section,
                    c.request_section,
                    c.within,
                ): c
                for c in built.constraints
            }

        before, after = keyed(self.old.built), keyed(self.new.built)
        for key in sorted(before.keys() | after.keys(), key=repr):
            was, now = before.get(key), after.get(key)
            constraint = now or was
            assert constraint is not None
            scope = constraint.command or constraint.within
            subject = constraint.avp + (f" in {scope}" if scope else "")
            where = {
                "old": None if was is None else _constraint_where(was),
                "new": None if now is None else _constraint_where(now),
            }
            rules_before = _constraint_rules(was)
            rules_after = _constraint_rules(now)
            # A constraint is a reading of prose, not a structure the wire
            # carries: one read where none was is compatible, one rule turning
            # into another, in a constraint both sides read, breaks a checker.
            changed = was is not None and now is not None
            for rule in sorted(rules_after - rules_before):
                self.add(
                    "constraint-added",
                    "editorial"
                    if '"text-only"' in rule
                    else "breaking"
                    if changed and rules_before - rules_after
                    else "compatible",
                    subject,
                    ("constraint", *key),
                    after=rule,
                    where=where,
                )
            for rule in sorted(rules_before - rules_after):
                self.add(
                    "constraint-removed",
                    "editorial" if '"text-only"' in rule else "compatible",
                    subject,
                    ("constraint", *key),
                    before=rule,
                    where=where,
                )
            if (
                was is not None
                and now is not None
                and rules_before == rules_after
                and [r.quotes for r in was.readings] != [r.quotes for r in now.readings]
            ):
                self.add(
                    "constraint-changed",
                    "editorial",
                    subject,
                    ("constraint", *key),
                    field="quotes",
                    where=where,
                )

    def holes(self) -> None:
        def keyed(
            built: dictionary.Dictionary,
        ) -> dict[tuple[str, str], dictionary.Hole]:
            return {(hole.reference, hole.name): hole for hole in built.holes}

        before, after = keyed(self.old.built), keyed(self.new.built)
        for key in sorted(before.keys() | after.keys()):
            was, now = before.get(key), after.get(key)
            hole = now or was
            if (was is None) == (now is None) or hole is None:
                continue
            where = Where(
                reference=hole.reference, version=hole.version, section=hole.section
            )
            self.add(
                "hole-added" if was is None else "hole-removed",
                "breaking" if was is None else "compatible",
                f"{hole.name} in {hole.reference}",
                ("hole", *key),
                field="missing",
                before=None if was is None else ", ".join(was.missing),
                after=None if now is None else ", ".join(now.missing),
                old=None if was is None else where,
                new=None if now is None else where,
            )


def _avp_subject(avp: dictionary.Avp) -> str:
    return f"{avp.name} ({avp.vendor_id}:{avp.code})"


def _member_text(member: dictionary.Member) -> str:
    return f"{member.presence} {_occurs(member)}"


def _application_where(application: dictionary.Application) -> Where:
    return Where(
        reference=application.reference,
        version=application.version,
        section=application.clause,
    )


def _command_where(
    application: dictionary.Application, command: dictionary.Command
) -> Where:
    return Where(
        reference=command.defined_in,
        version=application.version
        if command.defined_in == application.reference
        else None,
        section=command.section,
    )


def _element_where(element: dictionary.Element) -> Where:
    return Where(
        reference=element.reference, version=element.version, section=element.section
    )


def _code_where(code: dictionary.ResultCode) -> Where:
    return Where(reference=code.reference, version=code.version, section=code.section)


def _table_where(table: dictionary.ValueTable) -> Where:
    return Where(
        reference=table.reference, version=table.version, section=table.section
    )


def _constraint_where(constraint: dictionary.Constraint) -> Where:
    return Where(
        reference=constraint.reference,
        version=constraint.version,
        section=constraint.section,
    )


def _constraint_rules(constraint: dictionary.Constraint | None) -> set[str]:
    if constraint is None:
        return set()
    return {
        _rule_text(rule) for reading in constraint.readings for rule in reading.rules
    }


# --- two models -----------------------------------------------------------


def diff(
    old: model.Model,
    new: model.Model,
    *,
    documents: Sequence[str] = (),
    application_ids: Sequence[int] = (),
    raw: tuple[Corpus, Corpus] | None = None,
    corpus_versions: tuple[str | None, str | None] = (None, None),
) -> Diff:
    """The changes from `old` to `new` in the dictionaries of `documents`
    and `application_ids` (`dictionary.build`; nothing selected is
    everything). With `raw`, each side's raw mirror, each change gets its
    `origin`: the raw models differ the same way, or the raw files' blocks
    in the clause stating it differ, or neither."""
    built_old = dictionary.build(
        old, documents=documents, application_ids=application_ids
    )
    built_new = dictionary.build(
        new, documents=documents, application_ids=application_ids
    )
    found = _Comparison(built_old, built_new).run()
    if raw is not None:
        raw_models = [
            model.Model.build(books, holes=model.HolePolicy.ANY) for books in raw
        ]
        keys = {
            each.key
            for each in _Comparison(
                *(
                    dictionary.build(
                        built, documents=documents, application_ids=application_ids
                    )
                    for built in raw_models
                )
            ).run()
        }
        clauses = [_clauses(books) for books in raw]
        found = [
            dataclasses.replace(
                each,
                change=each.change.model_copy(
                    update={
                        "origin": _origin(each, keys, clauses, built_old, built_new)
                    }
                ),
            )
            for each in found
        ]
    changes = tuple(each.change for each in _ordered(found))
    return Diff(
        format_version=FORMAT_VERSION,
        seanchai_version=__version__,
        old=_side(built_old, corpus_versions[0]),
        new=_side(built_new, corpus_versions[1]),
        counts={
            impact: sum(1 for change in changes if change.impact == impact)
            for impact in _IMPACTS
        },
        changes=changes,
    )


def _clauses(books: Corpus) -> dict[tuple[str, str], set[str]]:
    """Each newest copy's blocks by reference and clause, as JSON, pages
    left out."""
    found: dict[tuple[str, str], set[str]] = {}
    for entry in books.newest():
        for section in entry.spec.sections:
            found.setdefault((entry.reference, section.source.section), set()).add(
                json.dumps(
                    section.model_dump(mode="json", exclude={"source": {"page"}}),
                    sort_keys=True,
                )
            )
    return found


def _origin(
    found: _Found,
    raw: set[tuple[Any, ...]],
    clauses: Sequence[dict[tuple[str, str], set[str]]],
    old: dictionary.Dictionary,
    new: dictionary.Dictionary,
) -> Origin:
    """Whether the raw mirrors differ the same way: `corrections` where they
    do not, else `document` where the version of the document stating it
    moved and `extraction` where not.

    The raw diff answers where it sees the change, or another change to the
    same subject (then the raw files agree on this one). Where it sees nothing
    of the subject, as an information-element row only a correction ties to
    its command, the raw blocks of the clauses stating it answer."""
    if found.key not in raw:
        subjects = {key[1:-3] for key in raw}
        places = {
            (where.reference, where.section)
            for where in (found.change.old, found.change.new)
            if where is not None and where.section is not None
        }
        if found.key[1:-3] in subjects or all(
            clauses[0].get(place) == clauses[1].get(place) for place in places
        ):
            return "corrections"
    where = found.change.new or found.change.old
    reference = None if where is None else where.reference
    versions = [
        {
            document.version
            for document in side.resolved
            if document.reference == reference
        }
        for side in (old, new)
    ]
    return "extraction" if versions[0] == versions[1] else "document"


def _side(built: dictionary.Dictionary, corpus_version: str | None) -> Side:
    selected = set(built.documents) or {
        application.reference for application in built.applications
    }
    return Side(
        corpus_version=corpus_version,
        release=built.release,
        documents=tuple(
            document for document in built.resolved if document.reference in selected
        ),
    )


# --- a file in place of a corpus's copy -------------------------------------


def overlay(base: Corpus, files: Iterable[Path], *, raw: bool = False) -> Corpus:
    """`base` reading each of `files` in place of its copies of the same
    document in that release or later, as a corpus holding an older version
    would. Rules keyed by a replaced copy are read as the file's, and the
    record of holes is dropped, since it speaks for the copies replaced: build
    the model with `HolePolicy.ANY`."""
    from .dad import parser

    added = []
    for path in files:
        added.append(
            Entry(path=path, spec=parser.parse(path.read_text(encoding="utf-8")))
        )
    replaced: dict[tuple[str, str], str] = {}
    entries = []
    for entry in base:
        overriding = next(
            (
                each
                for each in added
                if each.reference == entry.reference
                and _release(entry.spec.version) >= _release(each.spec.version)
            ),
            None,
        )
        if overriding is None:
            entries.append(entry)
        else:
            replaced[entry.reference, entry.spec.version or ""] = (
                overriding.spec.version or ""
            )
    del raw  # Raw or not, the files are read as given.
    return Corpus(
        [*entries, *added],
        rules=_rekeyed(base.rules, replaced),
        interfaces=base.interfaces,
    )


def _release(version: str | None) -> int:
    if version is None:
        return 0
    head = version.split(".")[0]
    return int(head) if head.isdigit() else 0


def _rekeyed(rules: Rules, replaced: Mapping[tuple[str, str], str]) -> Rules:
    """`rules` with every entry a replaced copy keys moved to its replacement."""

    def moved[V](entries: Mapping[tuple[str, str, str], V]) -> dict:
        return {
            (citing, replaced.get((citing, version), version), cited): value
            for (citing, version, cited), value in entries.items()
        }

    return dataclasses.replace(
        rules,
        cited_versions=moved(rules.cited_versions),
        latest_editions=moved(rules.latest_editions),
        cited_revisions=moved(rules.cited_revisions),
        stand_ins=moved(rules.stand_ins),
        release_stand_ins=moved(rules.release_stand_ins),
        release_fills=moved(rules.release_fills),
    )


# --- output -----------------------------------------------------------------


def render(found: Diff) -> str:
    """The human report: a summary line, then each impact's changes."""
    lines = [
        f"{_sides_text(found.old, found.new)}: "
        + ", ".join(f"{found.counts.get(i, 0)} {i}" for i in _IMPACTS)
    ]
    for impact in _IMPACTS:
        changes = [c for c in found.changes if c.impact == impact]
        if not changes:
            continue
        lines += ["", impact]
        for change in changes:
            lines.append(f"  {change.kind:<18} {_change_text(change)}")
            for path in change.paths[:3]:
                lines.append(f"      at {path}")
            if len(change.paths) > 3:
                lines.append(f"      and {len(change.paths) - 3} more paths")
    return "\n".join(lines) + "\n"


# How many documents at another version the summary line names; more are
# counted. `--json` lists every side's documents.
_NAMED = 5


def _sides_text(old: Side, new: Side) -> str:
    """Both sides for the summary line: two releases, or two corpora, by name
    with the documents read at another version, else each side's
    documents."""
    if (
        old.release is not None
        and new.release is not None
        and old.release != new.release
    ):
        names = f"Release {old.release} -> Release {new.release}"
    elif old.corpus_version is not None and new.corpus_version is not None:
        names = f"corpus {old.corpus_version} -> corpus {new.corpus_version}"
    else:
        return f"{_side_text(old)} -> {_side_text(new)}"
    versions: dict[str, tuple[list[str], list[str]]] = {}
    for index, side in enumerate((old, new)):
        for document in side.documents:
            versions.setdefault(document.reference, ([], []))[index].append(
                document.version or "-"
            )
    moved = {
        reference: (", ".join(sorted(before)) or "-", ", ".join(sorted(after)) or "-")
        for reference, (before, after) in versions.items()
        if sorted(before) != sorted(after)
    }
    if not moved:
        return names
    if len(moved) > _NAMED:
        return f"{names}, {len(moved)} documents at another version"
    return (
        names
        + ", "
        + ", ".join(
            f"{reference} {before} -> {after}"
            for reference, (before, after) in sorted(moved.items())
        )
    )


def _side_text(side: Side) -> str:
    return (
        ", ".join(
            document.reference
            + ("" if document.version is None else f" {document.version}")
            for document in side.documents
        )
        or "nothing"
    )


def _change_text(change: Change) -> str:
    text = change.subject
    if change.field:
        text += f" {change.field}"
    if change.before is not None or change.after is not None:
        text += f": {change.before or '-'} -> {change.after or '-'}"
    where = change.new or change.old
    notes: list[str] = [change.origin] if change.origin else []
    if where is not None and where.section:
        notes.append(f"{where.reference} {where.section}")
    return text + (f"  [{', '.join(notes)}]" if notes else "")


def json_schema() -> dict[str, Any]:
    """The JSON Schema of `Diff`."""
    _, schema = models_json_schema([(Diff, "serialization")], title="seanchai diff")
    return schema


def dumps(found: Diff) -> str:
    """`found` as JSON, indented, keys sorted."""
    return (
        json.dumps(
            found.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=1
        )
        + "\n"
    )
