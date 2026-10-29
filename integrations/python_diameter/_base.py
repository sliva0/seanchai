"""Support for the protocol-specific command classes `generate.py` emits.

The generator copies this module verbatim into every package it writes, as
`_base.py`. It stands in for the base classes python-diameter would ship
with protocol-specific commands: a deduplicated AVP definition (`AvpDef`), a
per-command member rule (`Rule`) that references one, and a message base
(`ProtocolMessage`) that encodes and decodes by those rules.

Every AVP a rule names is built and read with its definition's own value
class, code and vendor, never through the library's global dictionary: the
point of a protocol-specific class is that TS 29.214's `Codec-Data` is the
OctetString TS 29.214 says, whatever the dictionary holds under its code.
The dictionary is the fallback only for what the generated set does not
know: the AVPs that land in `* [ AVP ]` and a hole whose type no document
states. The library's `avp_def` tuples are still derived, for code that
introspects them.
"""

from __future__ import annotations

import dataclasses
import enum
import keyword
import logging
from functools import cached_property
from typing import Any, ClassVar, NamedTuple

from diameter.message._base import DefinedMessage, MessageHeader
from diameter.message.avp import Avp, AvpAddress, AvpGrouped
from diameter.message.avp.avp import get_avp_dictionary_entry
from diameter.message.avp.errors import AvpDecodeError, AvpEncodeError
from diameter.message.avp.generator import AvpGenDef, AvpGenType

logger = logging.getLogger("diameter.message.avp")


def attribute_name(avp_name: str) -> str:
    """The instance attribute an AVP's value lives in: `Session-Id` is
    `session_id`. A leading `3GPP` reads `tgpp`, as the library's constants
    spell the vendor, and any other leading digit gets an `avp_` prefix.
    `generate.py` derives the annotations it writes with the same rule."""
    name = avp_name.lower().replace("-", "_")
    if name.startswith("3gpp"):
        name = "tgpp" + name.removeprefix("3gpp")
    elif name[0].isdigit():
        name = "avp_" + name
    return name + "_" if keyword.iskeyword(name) else name


class OccurrenceError(AvpEncodeError):
    """A value set for a member breaks the member's occurrence bounds."""


class FlagRules(NamedTuple):
    """An AVP table's four flag-rule columns, as flag letters."""

    must: str = ""
    may: str = ""
    should_not: str = ""
    must_not: str = ""


class Presence(enum.Enum):
    """The bracket pair around a member in its ABNF."""

    FIXED = "<>"
    REQUIRED = "{}"
    OPTIONAL = "[]"


FIXED = Presence.FIXED
REQUIRED = Presence.REQUIRED
OPTIONAL = Presence.OPTIONAL


class Grouped:
    """Base of the value classes built for grouped AVPs, which hold one
    attribute per member like the library's `grouped.py` dataclasses."""

    avp_def: ClassVar[AvpGenType] = ()
    avp_rules: ClassVar[tuple[Rule, ...]] = ()
    additional_avps: list[Avp]


@dataclasses.dataclass(frozen=True, eq=False)
class AvpDef:
    """One AVP as its defining documents state it.

    `type_class` and `flags` are None only on a `hole`: an AVP the corpus
    knows the identity of but cannot complete, kept so a member naming it
    still decodes. `values` are an enumerated AVP's `(name, value)` pairs,
    `reserved` its reserved `(first, last)` ranges.
    """

    name: str
    code: int
    vendor_id: int
    type_class: type[Avp] | None
    flags: FlagRules | None
    members: tuple[Rule, ...] = ()
    values: tuple[tuple[str, int], ...] = ()
    reserved: tuple[tuple[int, int], ...] = ()
    defined_in: tuple[str, ...] = ()
    hole: str | None = None

    @property
    def attr_name(self) -> str:
        return attribute_name(self.name)

    @property
    def is_mandatory(self) -> bool | None:
        """The M bit the flag rules fix, or None where they leave it open."""
        if self.flags is None:
            return None
        if "M" in self.flags.must:
            return True
        if "M" in self.flags.must_not:
            return False
        return None

    @property
    def is_grouped(self) -> bool:
        return self.type_class is not None and issubclass(self.type_class, AvpGrouped)

    @cached_property
    def grouped_class(self) -> type[Grouped] | None:
        """The value class a grouped AVP decodes into, built from `members`."""
        if not self.is_grouped:
            return None
        fields: list[tuple[str, Any, Any]] = []
        for rule in self.members:
            if isinstance(rule.avp, AvpDef):
                default = (
                    dataclasses.field(default_factory=list)
                    if rule.is_repeated
                    else dataclasses.field(default=None)
                )
                fields.append((rule.attr_name, Any, default))
        fields.append(
            ("additional_avps", list[Avp], dataclasses.field(default_factory=list))
        )
        name = "".join(part.capitalize() for part in self.attr_name.split("_"))
        built = dataclasses.make_dataclass(name, fields, bases=(Grouped,))
        built.avp_rules = self.members
        built.avp_def = generation_defs(self.members)
        return built

    def build(self, value: Any) -> Avp:
        """`value` as this AVP, with this definition's class, code and vendor;
        a grouped value is encoded member by member under `members`."""
        type_class = self.type_class
        if type_class is None:
            # A hole states no type: the library's dictionary may know one.
            return Avp.new(
                self.code, self.vendor_id, value=value, is_mandatory=self.is_mandatory
            )
        avp = type_class(self.code, vendor_id=self.vendor_id)
        avp.name = self.name
        try:
            if self.is_grouped:
                avp.value = [
                    *encode(value, self.members, self.name),
                    *getattr(value, "additional_avps", ()),
                ]
            elif isinstance(avp, AvpAddress) and isinstance(value, tuple):
                # `AvpAddress.value` reads back as `(family, address)`; the
                # library's `Avp.new` takes that shape back as well.
                avp.value = value[1]
            else:
                avp.value = value
        except AvpEncodeError:
            raise
        except Exception as error:
            raise AvpEncodeError(
                f"{self.name} ({self.code}) cannot hold {value!r}: {error}"
            ) from None
        mandatory = self.is_mandatory
        if mandatory is None and self.flags is None:
            entry = get_avp_dictionary_entry(self.code, self.vendor_id)
            mandatory = None if entry is None else entry.get("mandatory")
        if mandatory is not None:
            avp.is_mandatory = mandatory
        return avp

    def read(self, avp: Avp) -> Any:
        """A received AVP's value, decoded as this definition's class from
        its payload, whatever class the library's dictionary gave it."""
        type_class = self.type_class
        typed = avp
        if type_class is not None and type(avp) is not type_class:
            typed = type_class(avp.code, vendor_id=avp.vendor_id, payload=avp.payload)
            typed.flags = avp.flags
            typed.name = self.name
        grouped_class = self.grouped_class
        try:
            if grouped_class is None:
                return typed.value
            found = grouped_class()
            decode(found, typed.value, self.members, found.additional_avps)
            return found
        except AvpDecodeError as error:
            logger.warning(str(error))
            return None


@dataclasses.dataclass(frozen=True)
class AvpHole:
    """A member name the corpus resolves to no `(vendor-id, code)`; `hole`
    says why. It stays in its rule table and has no attribute."""

    name: str
    hole: str


class AnyAvp:
    """RFC 6733's `* [ AVP ]` wildcard: the place unlisted AVPs may go."""

    name = "AVP"


ANY_AVP = AnyAvp()


class Rule(NamedTuple):
    """One member of a command or grouped AVP body.

    `min` is None where the presence's default applies: none for an
    optional member, one otherwise. `max` None is unbounded. `attr` is set
    only where one body names one AVP twice, so each occurrence has an
    attribute of its own.
    """

    avp: AvpDef | AvpHole | AnyAvp
    presence: Presence = OPTIONAL
    min: int | None = None
    max: int | None = 1
    attr: str | None = None

    @property
    def min_occurs(self) -> int:
        if self.min is not None:
            return self.min
        return 0 if self.presence is OPTIONAL else 1

    @property
    def is_required(self) -> bool:
        """Whether the member must appear: `0*1< X >` is fixed in position
        but may be absent."""
        return self.min_occurs > 0

    @property
    def is_repeated(self) -> bool:
        return self.max != 1

    @property
    def attr_name(self) -> str:
        return self.attr or attribute_name(self.avp.name)

    def bounds(self) -> str:
        """The occurrence bounds as ABNF writes them: `1*`, `0*1`."""
        return f"{self.min_occurs}*{'' if self.max is None else self.max}"


def generation_defs(rules: tuple[Rule, ...]) -> AvpGenType:
    """The library's `avp_def` for a rule table: every member with an
    identity, in table order."""
    found = []
    for rule in rules:
        avp = rule.avp
        if not isinstance(avp, AvpDef):
            continue
        found.append(
            AvpGenDef(
                rule.attr_name,
                avp.code,
                avp.vendor_id,
                is_required=rule.is_required,
                is_mandatory=avp.is_mandatory,
                type_class=avp.grouped_class,
            )
        )
    return tuple(found)


def encode(obj: Any, rules: tuple[Rule, ...], owner: str) -> list[Avp]:
    """The AVPs `obj`'s attributes hold, in rule order, each checked
    against its rule's occurrence bounds; `owner` names the command or
    grouped AVP in an `OccurrenceError`."""
    found: list[Avp] = []
    for rule in rules:
        avp = rule.avp
        if not isinstance(avp, AvpDef):
            continue
        value = getattr(obj, rule.attr_name, None)
        if value is None:
            values = []
        elif isinstance(value, list):
            # No AVP value is a list, so a list is occurrences, even on a
            # member that allows one.
            values = [each for each in value if each is not None]
        else:
            values = [value]
        if len(values) < rule.min_occurs or (
            rule.max is not None and len(values) > rule.max
        ):
            raise OccurrenceError(
                f"{owner}: {avp.name} ({rule.attr_name}) is set {len(values)}"
                f" times, outside its {rule.bounds()} bounds"
            )
        found += [avp.build(each) for each in values]
    return found


def decode(
    obj: Any, avps: list[Avp], rules: tuple[Rule, ...], additional: list[Avp]
) -> None:
    """Set `obj`'s attributes from received AVPs.

    Each AVP fills the first rule naming its `(vendor-id, code)` that still
    has room, so a body naming one AVP twice (TS 29.345's
    `WiFi-P2P-Assistance-Info`) gets its occurrences in order. An AVP no
    rule names, or one past every rule's maximum, goes to `additional`, so
    re-encoding keeps it.
    """
    slots: dict[tuple[int, int], list[Rule]] = {}
    for rule in rules:
        if isinstance(rule.avp, AvpDef):
            slots.setdefault((rule.avp.code, rule.avp.vendor_id), []).append(rule)
            if rule.is_repeated:
                setattr(obj, rule.attr_name, [])
    filled: dict[str, int] = {}
    for avp in avps:
        rule = next(
            (
                rule
                for rule in slots.get((avp.code, avp.vendor_id), ())
                if rule.max is None or filled.get(rule.attr_name, 0) < rule.max
            ),
            None,
        )
        if rule is None:
            additional.append(avp)
            continue
        assert isinstance(rule.avp, AvpDef)
        filled[rule.attr_name] = filled.get(rule.attr_name, 0) + 1
        value = rule.avp.read(avp)
        if rule.is_repeated:
            getattr(obj, rule.attr_name).append(value)
        else:
            setattr(obj, rule.attr_name, value)


class ProtocolMessage(DefinedMessage):
    """A command as one application on one interface defines it.

    A command class sets `code`, `name` and `application_id`; its Request
    and Answer subclasses set `is_request`, `is_proxyable` and the
    `avp_rules` it encodes and decodes by.
    """

    application_id: ClassVar[int | None] = None
    is_request: ClassVar[bool | None] = None
    is_proxyable: ClassVar[bool] = False
    is_error: ClassVar[bool] = False
    avp_rules: ClassVar[tuple[Rule, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "avp_rules" in vars(cls):
            cls.avp_def = generation_defs(cls.avp_rules)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.header.command_code = self.code
        if self.application_id is not None and not self.header.application_id:
            self.header.application_id = self.application_id
        if self.is_request is None:
            return
        self.header.is_request = self.is_request
        self.header.is_proxyable = self.is_proxyable
        self.header.is_error = self.is_error
        for rule in self.avp_rules:
            if isinstance(rule.avp, AvpDef) and rule.is_repeated:
                setattr(self, rule.attr_name, [])
        decode(self, self._avps, self.avp_rules, self._additional_avps)
        self._avps = []

    @property
    def avps(self) -> list[Avp]:
        """Every AVP of the message: the received ones while unchanged,
        otherwise the attributes encoded in rule order, then any others."""
        if self._avps:
            return self._avps
        return [
            *encode(self, self.avp_rules, type(self).__name__),
            *self._additional_avps,
        ]

    @avps.setter
    def avps(self, new_avps: list[Avp]) -> None:
        self._avps = new_avps

    @classmethod
    def type_factory(cls, header: MessageHeader) -> type[ProtocolMessage] | None:
        for subclass in cls.__subclasses__():
            if subclass.is_request == header.is_request:
                return subclass
        return None
