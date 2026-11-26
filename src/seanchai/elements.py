"""The element registry: what another document's information element looks
like, for the interpreted constraints that name one.

An `encoding element TS29.002 17.7.8 "E-UTRAN-CGI"` rule says an AVP carries
an element another document defines. The `.dadx` file names the element; this
module says how to check it, read from the defining document, as one
`Element` per (document, clause, name) built from a small closed set of
declarative shapes:

- `Octets`: the payload's length in octets.
- `Plmn`: a PLMN identity (MCC and MNC, the `plmn-id` codec) in three
  octets.
- `Field`: bits of one octet, or running across octets, taking one of a set
  of values: a spare field is one taking 0.
- `OneBit`: at most one bit of an octet set.
- `Integer`: an integer-typed payload's value within bounds.
- `Tbcd`: octets of TBCD digits.
- `Fqdn`: text of one of a few domain-name templates.

Each entry cites where its layout is defined, with the version read
(`Source`), says how deep its check goes (`Depth`) and what it leaves
unchecked, and why. A spare bit is checked to be what the document codes it
as, unless the document tells the receiver to ignore it; a reserved code
point is checked only where the document says it is not sent.
`problem` says why a payload is not laid out as an element says;
`seanchai.constraints.check` and the Wireshark plugin apply the same checks.
docs/constraints.md#elements lists the entries.
"""

from __future__ import annotations

import dataclasses
import enum
import re

from . import constraints
from .dad import ast

__all__ = [
    "REGISTRY",
    "Depth",
    "Element",
    "Field",
    "Fqdn",
    "Integer",
    "Octets",
    "OneBit",
    "Plmn",
    "Shape",
    "Source",
    "Tbcd",
    "breaking",
    "data_types",
    "lookup",
    "of_rule",
    "problem",
    "sample",
]


def _spaced(reference: str) -> str:
    """A reference as a document's cover spells it: `TS29.002` as
    `TS 29.002`, `3GPP2-A.S0022` as `3GPP2 A.S0022`."""
    for prefix in ("3GPP2-", "ITU-T-", "ETSI-"):
        if reference.startswith(prefix):
            return prefix[:-1] + " " + reference[len(prefix) :]
    return re.sub(r"^(TS|TR|RFC)(?=[0-9])", r"\1 ", reference)


class Depth(enum.StrEnum):
    """How far an entry checks its element: its whole layout (`full`), part
    of it (`partial`), its length alone (`length`), or nothing (`none`)."""

    FULL = "full"
    PARTIAL = "partial"
    LENGTH = "length"
    NONE = "none"


@dataclasses.dataclass(frozen=True)
class Source:
    """Where a layout is written: the document, the edition read as its
    cover prints it (`V19.1.0`, `-0 v2.0`, `(12/1999)`), the clause, and the
    table, figure or ASN.1 type within it."""

    document: str
    edition: str
    clause: str
    where: str

    def read(self) -> str:
        """The document and edition: `TS 29.002 V19.1.0`."""
        joiner = "" if self.edition.startswith("-") else " "
        return f"{_spaced(self.document)}{joiner}{self.edition}"

    def said(self) -> str:
        return f"{self.read()} clause {self.clause}, {self.where}"


def _bounds(low: int | None, high: int | None) -> str:
    if low == high:
        return str(low)
    if high is None:
        return f"at least {low}"
    if low is None:
        return f"at most {high}"
    return f"{low} to {high}"


@dataclasses.dataclass(frozen=True)
class Octets:
    """The payload has `low` to `high` octets; `high` None for no bound."""

    low: int
    high: int | None

    def bounds_text(self) -> str:
        return _bounds(self.low, self.high)

    def said(self) -> str:
        single = self.low == 1 and self.high in (1, None)
        return f"{self.bounds_text()} octet{'' if single else 's'}"


@dataclasses.dataclass(frozen=True)
class Plmn:
    """A PLMN identity in octets `octet` to `octet` + 2: MCC digits 2 and 1,
    MNC digit 3 ("1111" for a 2-digit MNC) and MCC digit 3, MNC digits 2
    and 1, as the `plmn-id` codec."""

    octet: int = 1

    def said(self) -> str:
        return f"a PLMN identity in octets {self.octet} to {self.octet + 2}"


@dataclasses.dataclass(frozen=True)
class Field:
    """Bits `high` of octet `octet` down to bit `low` of octet `last` (the
    same octet unless given), bits numbered 8 (most significant) to 1 as the
    documents number them, read as one number, taking a value within one of
    the inclusive ranges `allowed`. `meaning` says the allowed values in
    words where listing them would not."""

    name: str
    octet: int
    high: int
    low: int
    allowed: tuple[tuple[int, int], ...]
    last: int | None = None
    meaning: str | None = None

    @property
    def width(self) -> int:
        last = self.octet if self.last is None else self.last
        return self.high - self.low + 1 + 8 * (last - self.octet)

    def place(self) -> str:
        last = self.octet if self.last is None else self.last
        if last != self.octet and (self.high, self.low) == (8, 1):
            return f"octets {self.octet} to {last}"
        if last != self.octet:
            return f"octet {self.octet} bit {self.high} to octet {last} bit {self.low}"
        if (self.high, self.low) == (8, 1):
            return f"octet {self.octet}"
        if self.high == self.low:
            return f"octet {self.octet} bit {self.high}"
        return f"octet {self.octet} bits {self.high}-{self.low}"

    def value_text(self, value: int) -> str:
        if self.width <= 8:
            return format(value, f"0{self.width}b")
        return f"0x{value:0{(self.width + 3) // 4}x}"

    def allowed_text(self) -> str:
        if self.meaning is not None:
            return self.meaning
        parts = [
            self.value_text(low)
            if low == high
            else f"{self.value_text(low)} to {self.value_text(high)}"
            for low, high in self.allowed
        ]
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " or " + parts[-1]

    def said(self) -> str:
        return f"{self.place()} ({self.name}) {self.allowed_text()}"

    def read(self, payload: bytes) -> int | None:
        """The field's value, or None where the payload is too short."""
        last = self.octet if self.last is None else self.last
        if len(payload) < last:
            return None
        number = int.from_bytes(payload[self.octet - 1 : last], "big")
        return number >> (self.low - 1) & ((1 << self.width) - 1)


@dataclasses.dataclass(frozen=True)
class OneBit:
    """At most one bit of octet `octet` is set."""

    octet: int

    def said(self) -> str:
        return f"at most one bit of octet {self.octet} set"


@dataclasses.dataclass(frozen=True)
class Integer:
    """An integer-typed payload's value is `low` to `high`, None for an open
    bound."""

    low: int | None
    high: int | None

    def bounds_text(self) -> str:
        return _bounds(self.low, self.high)

    def said(self) -> str:
        return f"an integer {self.bounds_text()}"


@dataclasses.dataclass(frozen=True)
class Tbcd:
    """Octets `first` on are TBCD digits (TS 29.002 clause 17.7.8's
    TBCD-STRING): 0 to 9, *, #, a, b and c coded 0000 to 1110, the first of
    each octet in bits 4-1, "1111" filling bits 8-5 of the last octet after
    an odd count."""

    first: int

    def said(self) -> str:
        return (
            f"octets {self.first} on TBCD digits (0-9, *, #, a, b, c),"
            " '1111' filling only the last octet's bits 8-5"
        )


# A template's field: <NAME:hex:N> or <NAME:digit:N>.
_SLOT = re.compile(r"<(?P<name>[A-Z]+):(?P<kind>hex|digit):(?P<count>[0-9]+)>")


@dataclasses.dataclass(frozen=True)
class Fqdn:
    """Text matching one of `templates`, in any case: literal text and fields
    `<NAME:hex:N>` (N hexadecimal digits) or `<NAME:digit:N>` (N decimal
    digits)."""

    templates: tuple[str, ...]

    def shown(self, template: str) -> str:
        return _SLOT.sub(lambda match: f"<{match['name']}>", template)

    def said(self) -> str:
        slots = {
            match["name"]: (match["kind"], int(match["count"]))
            for template in self.templates
            for match in _SLOT.finditer(template)
        }
        sizes = ", ".join(
            f"{name} {count} {'hexadecimal digits' if kind == 'hex' else 'digits'}"
            for name, (kind, count) in slots.items()
        )
        forms = " or ".join(self.shown(each) for each in self.templates)
        return f"{forms} ({sizes}), in any case"

    def regex(self, template: str) -> re.Pattern[str]:
        parts: list[str] = []
        position = 0
        for match in _SLOT.finditer(template):
            parts.append(re.escape(template[position : match.start()]))
            digit = "[0-9a-f]" if match["kind"] == "hex" else "[0-9]"
            parts.append(f"{digit}{{{match['count']}}}")
            position = match.end()
        parts.append(re.escape(template[position:]))
        return re.compile("".join(parts), re.IGNORECASE)

    def lua(self, template: str) -> str:
        """`template` as an anchored Lua pattern over lowercased text."""
        parts: list[str] = []
        position = 0
        for match in _SLOT.finditer(template):
            parts.append(_lua_literal(template[position : match.start()]))
            parts.append(
                ("%x" if match["kind"] == "hex" else "%d") * int(match["count"])
            )
            position = match.end()
        parts.append(_lua_literal(template[position:]))
        return "^" + "".join(parts) + "$"

    def example(self) -> bytes:
        text = _SLOT.sub(
            lambda match: (
                ("0a" if match["kind"] == "hex" else "01")[0] * int(match["count"])
            ),
            self.templates[0],
        )
        return text.encode()


def _lua_literal(text: str) -> str:
    return "".join(f"%{char}" if not char.isalnum() else char for char in text.lower())


type Shape = Octets | Plmn | Field | OneBit | Integer | Tbcd | Fqdn


@dataclasses.dataclass(frozen=True)
class Element:
    """One element another document defines, as the interpretations name it
    (`document`, `clause` and `name`, None where the rule names none), with
    `title`, what it is, the `sources` its layout was read from, the
    `checks` made of a payload, how deep they go (`depth`) and what they
    leave unchecked and why (`unchecked`). `valid` is, for an entry with no
    checks because every value is one the document defines, what says so in
    their place. `example` is a payload laid out
    as the element, for test messages; an integer element has none, its
    payload being its AVP's type."""

    document: str
    clause: str | None
    name: str | None
    title: str
    sources: tuple[Source, ...]
    checks: tuple[Shape, ...]
    depth: Depth
    unchecked: str | None = None
    example: bytes | None = None
    valid: str | None = None

    @property
    def key(self) -> tuple[str, str | None, str | None]:
        return (self.document, self.clause, self.name)

    def cited(self) -> str:
        """The element as a rule names it: `TS 29.002 17.7.8 E-UTRAN-CGI`."""
        parts = [_spaced(self.document)]
        if self.clause is not None:
            parts.append(self.clause)
        if self.name is not None:
            parts.append(self.name)
        return " ".join(parts)

    def said(self) -> str:
        """The checks in words, or what is said in their place."""
        if not self.checks:
            return self.valid or "nothing checked"
        return "; ".join(shape.said() for shape in self.checks)

    @property
    def text(self) -> bool:
        return any(isinstance(shape, Fqdn) for shape in self.checks)

    @property
    def integer(self) -> bool:
        return any(isinstance(shape, Integer) for shape in self.checks)


def _shape_problem(
    shape: Shape, payload: bytes, data_type: ast.DataType | None
) -> str | None:
    match shape:
        case Octets(low=low, high=high):
            if len(payload) < low or (high is not None and len(payload) > high):
                return f"{len(payload)} octets, not {shape.bounds_text()}"
            return None
        case Plmn(octet=octet):
            part = payload[octet - 1 : octet + 2]
            if len(part) < 3:
                return f"no PLMN identity in octets {octet} to {octet + 2}"
            found = constraints.codec_problem(ast.Codec.PLMN_ID, part)
            return None if found is None else f"PLMN identity: {found}"
        case Field():
            value = shape.read(payload)
            if value is None:
                return None
            if any(low <= value <= high for low, high in shape.allowed):
                return None
            return (
                f"{shape.place()} ({shape.name}) {shape.value_text(value)},"
                f" not {shape.allowed_text()}"
            )
        case OneBit(octet=octet):
            if len(payload) < octet:
                return None
            held = [
                bit for bit in range(8, 0, -1) if payload[octet - 1] >> (bit - 1) & 1
            ]
            if len(held) > 1:
                named = " and ".join(map(str, held))
                return f"bits {named} of octet {octet} set, at most one may be"
            return None
        case Integer(low=low, high=high):
            value = (
                None
                if data_type is None
                else constraints.integer_value(data_type, payload)
            )
            if value is None:
                return None
            if (low is not None and value < low) or (high is not None and value > high):
                return f"{value}, not {shape.bounds_text()}"
            return None
        case Tbcd(first=first):
            digits = payload[first - 1 :]
            for index, octet in enumerate(digits):
                low_nibble, high_nibble = octet & 0x0F, octet >> 4
                last = index == len(digits) - 1
                if low_nibble == 0x0F or (high_nibble == 0x0F and not last):
                    return f"octet {first + index}: '1111' filler before the last digit"
            return None
        case Fqdn():
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                return "not UTF-8 text"
            if any(shape.regex(each).fullmatch(text) for each in shape.templates):
                return None
            return "not " + " or ".join(shape.shown(each) for each in shape.templates)
    raise AssertionError(shape)


def problem(
    element: Element, payload: bytes, data_type: ast.DataType | None = None
) -> str | None:
    """Why `payload`, an AVP's data of `data_type`, is not laid out as
    `element` says, or None if it is. The first check broken answers."""
    for shape in element.checks:
        found = _shape_problem(shape, payload, data_type)
        if found is not None:
            return found
    return None


def sample(element: Element, data_type: ast.DataType) -> bytes | None:
    """A payload of `data_type` laid out as `element`, or None where the
    entry gives none."""
    if element.example is not None:
        return element.example
    for shape in element.checks:
        if isinstance(shape, Integer):
            bounds = constraints.integer_bounds(data_type)
            if bounds is None:
                return None
            value = shape.low if shape.low is not None else min(0, shape.high or 0)
            size = (
                8
                if data_type in (ast.DataType.INTEGER64, ast.DataType.UNSIGNED64)
                else 4
            )
            return value.to_bytes(size, "big", signed=bounds[0] < 0)
        if isinstance(shape, Fqdn):
            return shape.example()
    return None


def breaking(element: Element, good: bytes, data_type: ast.DataType) -> list[bytes]:
    """Payloads of `data_type` like `good` that break one of `element`'s
    checks each, for negative test messages; a check no change breaks
    without breaking the payload's type gives none. A length comes last, so
    a test message breaks the layout within it where it can."""
    found: list[bytes] = []
    lengths: list[bytes] = []
    for shape in element.checks:
        match shape:
            case Octets(low=low, high=high):
                if high is not None:
                    lengths.append((good + b"\x00" * (high + 1))[: high + 1])
                if low > 0:
                    lengths.append(good[: low - 1])
            case Plmn(octet=octet):
                if len(good) >= octet + 2:
                    found.append(good[: octet - 1] + b"\xaa" + good[octet:])
            case Field():
                last = shape.octet if shape.last is None else shape.last
                if len(good) < last:
                    continue
                bad = next(
                    (
                        value
                        for value in range(1 << shape.width)
                        if not any(low <= value <= high for low, high in shape.allowed)
                    ),
                    None,
                )
                if bad is None:
                    continue
                number = int.from_bytes(good[shape.octet - 1 : last], "big")
                mask = ((1 << shape.width) - 1) << (shape.low - 1)
                number = number & ~mask | bad << (shape.low - 1)
                span = number.to_bytes(last - shape.octet + 1, "big")
                found.append(good[: shape.octet - 1] + span + good[last:])
            case OneBit(octet=octet):
                if len(good) >= octet:
                    found.append(good[: octet - 1] + b"\x03" + good[octet:])
            case Integer(low=low, high=high):
                bounds = constraints.integer_bounds(data_type)
                if bounds is None:
                    continue
                size = len(good)
                for value in (
                    (high + 1) if high is not None else None,
                    (low - 1) if low is not None else None,
                ):
                    if value is not None and bounds[0] <= value <= bounds[1]:
                        found.append(value.to_bytes(size, "big", signed=bounds[0] < 0))
            case Tbcd(first=first):
                if len(good) > first:
                    found.append(good[: first - 1] + b"\xff" + good[first:])
            case Fqdn():
                found.append(b"x" + good)
    return found + lengths


# --- the registry -----------------------------------------------------------

# The versions read: Release 19's latest of each document the interpreted
# documents cite non-specifically, as their references clauses mean.
_MAP = ("TS29.002", "19.1.0")
_TRACE = ("TS32.422", "19.7.0")
_NUMBERING = ("TS23.003", "19.8.0")
_NAS = ("TS24.008", "19.5.0")
_SAE_SECURITY = ("TS33.401", "19.2.0")
_SECURITY = ("TS33.102", "19.1.0")
_SGSAP = ("TS29.118", "19.1.0")
_GTPV2 = ("TS29.274", "19.6.0")
_GTPV1 = ("TS29.060", "19.0.0")
_NGAP = ("TS38.413", "19.4.0")
_GAD = ("TS23.032", "19.0.0")
_SH = ("TS29.328", "19.2.0")
_NON_3GPP_ACCESS = ("TS24.302", "19.0.0")
_NON_3GPP_SECURITY = ("TS33.402", "19.0.0")
_GBA = ("TS33.220", "19.1.0")
_NAS_5GS = ("TS24.501", "19.8.0")
_CAP = ("TS29.078", "19.0.0")
_GI = ("TS29.061", "19.1.0")
_SMS = ("TS23.040", "19.0.0")
_S1AP = ("TS36.413", "19.2.0")
_RANAP = ("TS25.413", "19.0.0")
_BSSGP = ("TS48.018", "19.0.0")
_EPS_NAS = ("TS24.301", "19.8.0")
_RRC = ("TS36.331", "19.4.0")


def _network_name(clause: str, attribute: str, field: str) -> Element:
    """TS 24.302's full or short name value: TS 24.008's Network Name from
    its octet 3, the IEI and length left out."""
    return Element(
        "TS24.302",
        clause,
        f"{field.capitalize()} name value",
        f"the {field} name value field of the {attribute} attribute: a"
        " Network Name's contents without its IEI and length",
        (
            _source(
                _NON_3GPP_ACCESS,
                clause,
                f"table {clause}-1, the {field} name value field 'the same as"
                " the structure of the Network Name defined in 3GPP TS 24.008"
                " [46] clause 10.5.3.5a except for the Network Name IEI and the"
                " Length of Network Name contents'",
            ),
            _source(
                _NAS,
                "10.5.3.5a",
                "figure 10.5.80, octet 3: ext 1, coding scheme, Add CI, number"
                " of spare bits in last octet; octets 4 on the text string",
            ),
        ),
        (
            Octets(1, None),
            Field("ext", 1, 8, 8, _codes(1)),
        ),
        Depth.PARTIAL,
        "the coding scheme's reserved values 010 to 111 are not refused, since"
        " the clause does not say they are not sent, and the text string, with"
        " the spare bits its last octet holds, is not decoded",
        example=b"\x80\x41\x42",
    )


def _source(document: tuple[str, str], clause: str, where: str) -> Source:
    return Source(document[0], f"V{document[1]}", clause, where)


def _codes(*values: int | tuple[int, int]) -> tuple[tuple[int, int], ...]:
    return tuple(each if isinstance(each, tuple) else (each, each) for each in values)


_SPARE_ZERO = ((0, 0),)

# The SS-Codes TS 29.002 clause 17.7.5 defines: allSS, the line and name
# identification, forwarding, call offering, completion, multiparty,
# community of interest, charging, additional information transfer,
# barring, call priority, LCS privacy exception and MO-LR groups and their
# services, and the PLMN-specific codes.
_SS_CODES = _codes(
    0x00,
    (0x10, 0x15),
    (0x18, 0x19),
    (0x20, 0x21),
    0x24,
    (0x28, 0x2B),
    (0x30, 0x32),
    (0x40, 0x45),
    (0x50, 0x51),
    (0x60, 0x61),
    (0x70, 0x72),
    (0x80, 0x83),
    (0x90, 0x94),
    (0x99, 0x9B),
    (0xA0, 0xA1),
    (0xB0, 0xB5),
    (0xC0, 0xC3),
    (0xF0, 0xFF),
)

# The teleservice codes TS 29.002 clause 17.7.9 defines.
_TELESERVICE_CODES = _codes(
    0x00,
    (0x10, 0x12),
    (0x20, 0x22),
    (0x60, 0x63),
    0x70,
    0x80,
    (0x90, 0x92),
    (0xD0, 0xDF),
)

_LOCATION_SPARE = (
    "the spare bits TS 29.274 clause 8.1 says are sent as 0 and not evaluated"
    " by the receiver"
)

REGISTRY: tuple[Element, ...] = (
    Element(
        "3GPP2-A.S0022",
        "A",
        "Mobile Identity (MEID)",
        "the Mobile Equipment Identifier, octets 3 to 10 of the A9 Mobile"
        " Identity (MEID) element",
        (
            Source(
                "3GPP2-A.S0022",
                "-0 v2.0",
                "Annex A",
                "A9-Setup-A8's Mobile Identity (MEID): A9 Element Identifier 0DH,"
                " Length 08H, octets 3 to 10",
            ),
        ),
        (
            Octets(8, 8),
            Field(
                "odd/even indicator 0, type of identity 001", 1, 4, 1, _codes(0b0001)
            ),
            Field("fill", 8, 8, 5, _codes(0b1111)),
        ),
        Depth.FULL,
        "the 14 MEID hex digits take any value 0H to FH. 3gpp2.org publishes"
        " A.S0022-0 v2.0 (April 2010) as the newest revision; later revisions"
        " TIA republishes were not read",
        example=bytes([0xA1, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFE]),
    ),
    Element(
        "TS29.303",
        "4.3.2",
        None,
        'a host name of the form <"topon" | "topoff">'
        " . <single-label-interface-name> . <canonical-node-name>",
        (
            _source(
                ("TS29.303", "19.1.0"),
                "4.3.2",
                "the host names' form",
            ),
        ),
        (),
        Depth.NONE,
        "the clause binds the operator provisioning host names to the form,"
        " and tells implementations to treat a host name not of the form as"
        " valid, so a breach is no error of the message; the host name"
        " itself is checked as a DiameterIdentity",
    ),
    Element(
        "TS23.003",
        "4.4",
        "Zone Code",
        "a Zone Code (ZC) of a Regional Subscription Zone Identity",
        (_source(_NUMBERING, "4.4", "'ZC has fixed length of two octets'"),),
        (Octets(2, 2),),
        Depth.FULL,
        "the code is in full hexadecimal representation: any value",
        example=b"\x00\x01",
    ),
    Element(
        "TS33.401",
        None,
        "RAND",
        "the random challenge of an EPS authentication vector",
        (
            _source(
                _SAE_SECURITY,
                "6.1.2",
                "an EPS authentication vector is derived from TS 33.102's,"
                " clause 6.3.2",
            ),
            _source(_SECURITY, "6.3.7", "'RAND shall have a length of 128 bits'"),
        ),
        (Octets(16, 16),),
        Depth.FULL,
        "a random number: any value",
        example=bytes(range(16)),
    ),
    Element(
        "TS33.401",
        None,
        "XRES",
        "the expected response of an EPS authentication vector",
        (
            _source(
                _SAE_SECURITY,
                "6.1.2",
                "an EPS authentication vector is derived from TS 33.102's,"
                " clause 6.3.2",
            ),
            _source(
                _SECURITY,
                "6.3.7",
                "'RES shall have a variable length of 4-16 octets', XRES being"
                " f2's output compared with RES (clause 6.3.3)",
            ),
        ),
        (Octets(4, 16),),
        Depth.FULL,
        "a function's output: any value",
        example=bytes(range(8)),
    ),
    Element(
        "TS33.401",
        None,
        "AUTN",
        "the authentication token of an EPS authentication vector,"
        " SQN ⊕ AK || AMF || MAC",
        (
            _source(
                _SAE_SECURITY,
                "6.1.2",
                "an EPS authentication vector is derived from TS 33.102's,"
                " clause 6.3.2",
            ),
            _source(_SECURITY, "6.3.2", "AUTN = SQN ⊕ AK || AMF || MAC"),
            _source(
                _SECURITY,
                "6.3.7",
                "SQN and AK 48 bits, AMF 16 bits, MAC 64 bits",
            ),
        ),
        (Octets(16, 16),),
        Depth.FULL,
        "its fields take any value: the AMF's bits are the operator's",
        example=bytes(range(16, 32)),
    ),
    Element(
        "TS33.401",
        None,
        "K_ASME",
        "the key K_ASME",
        (
            _source(
                _SAE_SECURITY,
                "6.2",
                "'the length of KASME, KeNB and NH is 256 bits'",
            ),
        ),
        (Octets(32, 32),),
        Depth.FULL,
        "a key: any value",
        example=bytes(range(32)),
    ),
    Element(
        "TS33.102",
        None,
        "SRES",
        "the GSM signed response",
        (
            _source(
                _SECURITY,
                "6.8.1.2",
                "c2: SRES = XRES*1 xor XRES*2 xor XRES*3 xor XRES*4, each"
                " XRES*i 4 octets",
            ),
        ),
        (Octets(4, 4),),
        Depth.FULL,
        "a function's output: any value",
        example=b"\x01\x02\x03\x04",
    ),
    Element(
        "TS32.422",
        "5.4",
        "List of NE Types",
        "the network element types a trace session is activated in, a bitmap",
        (_source(_TRACE, "5.4", "the List of NE Types bitmap's three octets"),),
        (
            Octets(3, 3),
            Field("spare", 3, 8, 7, _SPARE_ZERO),
        ),
        Depth.FULL,
        "every other bit is an NE type, set or not",
        example=b"\x40\x00\x00",
    ),
    Element(
        "TS32.422",
        "5.5",
        "List of Interfaces",
        "the interfaces to trace, a bitmap per network element type",
        (
            _source(
                _TRACE,
                "5.5",
                "the bitmaps' table, an octet per row: MSC Server 2, MGW,"
                " SGSN 2, GGSN, RNC, BM-SC, MME, SGW, PDN GW, eNB/en-gNB,"
                " HSS 2, EIR, AMF 2, PCF, SMF 2, UPF, NG-RAN node, UDM",
            ),
        ),
        (Octets(23, 23),),
        Depth.LENGTH,
        "the spare bits in each network element's bitmap are not checked:"
        " several of the bitmaps print fewer cells than bits, so which bits a"
        " spare cell spans is not certain, and NOTE 5 says the bitmaps may"
        " number bits otherwise than the signalling specifications do",
        example=bytes(23),
    ),
    Element(
        "TS32.422",
        "5.1",
        "Triggering Events",
        "the events starting and stopping a trace recording session, a"
        " bitmap per network element type",
        (
            _source(
                _TRACE,
                "5.1",
                "the bitmaps' table, an octet per row: MSC Server 2, MGW,"
                " SGSN 2, GGSN, BM-SC, MME, PGW and SGW, AMF, SMF 2, PCF, NEF"
                " and UPF, NSSF and AUSF, UDM and NRF, spare and SMSF",
            ),
        ),
        (Octets(17, 17),),
        Depth.LENGTH,
        "the spare bits in each network element's bitmap are not checked:"
        " several of the bitmaps print fewer cells than bits, so which bits a"
        " spare cell spans is not certain",
        example=bytes(17),
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "AddressString",
        "an address: a nature of address and numbering plan octet, then TBCD"
        " digits (the omc-Id of ActivateTraceModeArg, clause 17.7.2)",
        (
            _source(_MAP, "17.7.2", "ActivateTraceModeArg: omc-Id [3] AddressString"),
            _source(
                _MAP,
                "17.7.8",
                "AddressString ::= OCTET STRING (SIZE (1..maxAddressLength)),"
                " maxAddressLength 20; TBCD-STRING",
            ),
        ),
        (
            Octets(1, 20),
            Field("extension, 1 for no extension", 1, 8, 8, _codes(1)),
            Tbcd(2),
        ),
        Depth.FULL,
        "the nature of address and numbering plan values the type marks"
        " reserved are not refused, since it does not say they are not sent",
        example=b"\x91\x21\x43\x65",
    ),
    Element(
        "TS29.002",
        "17.7.1",
        "PDP-Type",
        "the PDP type organisation and number of TS 29.060's End User Address",
        (
            _source(
                _MAP,
                "17.7.1",
                "PDP-Type ::= OCTET STRING (SIZE (2)): 'Only the values PPP,"
                " IPv4, IPv6 and Non-IP are allowed'",
            ),
            _source(
                _GTPV1,
                "7.7.27",
                "figure 35, octets 4 and 5: spare '1111', PDP type"
                " organisation, PDP type number; ETSI (0) PPP 1 and Non-IP 2,"
                " IETF (1) numbers the PPP DLL protocol numbers, IPv4 21H and"
                " IPv6 57H",
            ),
        ),
        (
            Octets(2, 2),
            Field("spare", 1, 8, 5, _codes(0b1111)),
            Field(
                "PDP type organisation and number",
                1,
                4,
                1,
                _codes(0x001, 0x002, 0x121, 0x157),
                last=2,
                meaning="PPP (0x001), Non-IP (0x002), IPv4 (0x121) or IPv6 (0x157)",
            ),
        ),
        Depth.FULL,
        None,
        example=b"\xf1\x21",
    ),
    Element(
        "TS29.002",
        "17.7.1",
        "Ext-PDP-Type",
        "the PDP type organisation and number of a dual-stack PDP context",
        (
            _source(
                _MAP,
                "17.7.1",
                "Ext-PDP-Type ::= OCTET STRING (SIZE (2)): 'Octets are coded,"
                " similarly to PDP-Type, according to TS 3GPP TS 29.060' and"
                " 'Only the value IPv4v6 is allowed for this parameter'",
            ),
            _source(
                _GTPV1,
                "7.7.27",
                "figure 35, octets 4 and 5: spare '1111', PDP type"
                " organisation, PDP type number; IETF (1) IPv4v6 8DH, 'There is"
                " no IANA defined PDP type for IPv4v6'",
            ),
        ),
        (
            Octets(2, 2),
            Field("spare", 1, 8, 5, _codes(0b1111)),
            Field(
                "PDP type organisation and number",
                1,
                4,
                1,
                _codes(0x18D),
                last=2,
                meaning="IPv4v6 (0x18D)",
            ),
        ),
        Depth.FULL,
        None,
        example=b"\xf1\x8d",
    ),
    Element(
        "TS29.002",
        "17.7.1",
        "QoS-Subscribed",
        "QoS-Subscribed and its extensions concatenated: TS 24.008's Quality"
        " of Service octets 3 to 5, then Ext-QoS-Subscribed (an"
        " allocation/retention priority and octets 6 to 13), Ext2- (14 to 16),"
        " Ext3- (17 and 18) and Ext4-QoS-Subscribed (an evolved ARP)",
        (
            _source(
                _MAP,
                "17.7.1",
                "QoS-Subscribed SIZE (3), Ext-QoS-Subscribed SIZE (1..9),"
                " Ext2-QoS-Subscribed SIZE (1..3), Ext3-QoS-Subscribed"
                " SIZE (1..2), Ext4-QoS-Subscribed SIZE (1)",
            ),
            _source(_NAS, "10.5.6.5", "the Quality of service information element"),
        ),
        (Octets(3, 18),),
        Depth.LENGTH,
        "the octets' fields are not checked: TS 24.008 has the receiver map"
        " a reserved value to another rather than refuse it, and its spare"
        " bits are ignored by the receiving side (clause 10.5)",
        example=b"\x23\x93\x1f",
    ),
    Element(
        "TS23.003",
        "4.7",
        "CSG-ID",
        "a Closed Subscriber Group Identity",
        (_source(_NUMBERING, "4.7", "'The CSGID shall be fix length 27 bit value'"),),
        (),
        Depth.NONE,
        "the document fixes only the identity's 27 bits; where they sit in"
        " the Unsigned32 AVP is TS 29.272's own sentence, read as a bits rule"
        " beside it",
    ),
    Element(
        "TS29.002",
        "17.7.5",
        "SS-Code",
        "the code of a supplementary service or group of them",
        (
            _source(
                _MAP, "17.7.5", "SS-Code ::= OCTET STRING (SIZE (1)) and its values"
            ),
        ),
        (
            Octets(1, 1),
            Field(
                "SS-Code", 1, 8, 1, _SS_CODES, meaning="a code clause 17.7.5 defines"
            ),
        ),
        Depth.FULL,
        None,
        example=b"\xb1",
    ),
    Element(
        "TS29.002",
        "17.7.4",
        "SS-Status",
        "a supplementary service's state, its Q, P, R and A bits",
        (
            _source(
                _MAP,
                "17.7.4",
                "SS-Status ::= OCTET STRING (SIZE (1)): bits 8765 0000"
                " (unused), bits 4321 the Q, P, R and A bits",
            ),
        ),
        (Octets(1, 1), Field("unused", 1, 8, 5, _SPARE_ZERO)),
        Depth.FULL,
        None,
        example=b"\x05",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "LCSServiceTypeID",
        "an LCS service type",
        (
            _source(
                _MAP,
                "17.7.8",
                "LCSServiceTypeID ::= INTEGER (0..127), 0 to 63 standard and"
                " 64 to 127 non-standard types",
            ),
        ),
        (Integer(0, 127),),
        Depth.FULL,
        "a standard type the clause has not yet named is reserved for one, not refused",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "AgeOfLocationInformation",
        "the minutes since the mobile station's last contact with the network",
        (
            _source(
                _MAP,
                "17.7.8",
                "AgeOfLocationInformation ::= INTEGER (0..32767), '32767'"
                " indicating the location information is at least 32767"
                " minutes old",
            ),
        ),
        (Integer(0, 32767),),
        Depth.FULL,
        None,
    ),
    Element(
        "TS29.002",
        "17.7.9",
        "TeleserviceCode",
        "the code of a teleservice or group of them",
        (
            _source(
                _MAP,
                "17.7.9",
                "TeleserviceCode ::= OCTET STRING (SIZE (1)) and its values",
            ),
        ),
        (
            Octets(1, 1),
            Field(
                "TeleserviceCode",
                1,
                8,
                1,
                _TELESERVICE_CODES,
                meaning="a code clause 17.7.9 defines",
            ),
        ),
        Depth.FULL,
        "Ext-TeleserviceCode's octets 2 to 5, reserved for future use, are"
        " not the type named",
        example=b"\x21",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "E-UTRAN-CGI",
        "an E-UTRAN Cell Global Identifier: a PLMN identity and a 28-bit"
        " E-UTRAN cell identifier",
        (
            _source(
                _MAP,
                "17.7.8",
                "E-UTRAN-CGI ::= OCTET STRING (SIZE (7)), coded as TS 29.118 describes",
            ),
            _source(_SGSAP, "9.4.3a", "octets 3 to 9 coded as TS 29.274's ECGI field"),
            _source(_GTPV2, "8.21.5", "figure 8.21.5-1, the ECGI field"),
        ),
        (Octets(7, 7), Plmn()),
        Depth.FULL,
        "octet 4's bits 8-5 are " + _LOCATION_SPARE + "; the ECI takes any value",
        example=b"\x21\xf3\x54\x00\x00\x00\x01",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "TA-Id",
        "a Tracking Area Identity: a PLMN identity and a tracking area code",
        (
            _source(
                _MAP,
                "17.7.8",
                "TA-Id ::= OCTET STRING (SIZE (5)), coded as TS 29.118 describes",
            ),
            _source(
                _SGSAP,
                "9.4.21a",
                "octets 3 to 7 the value part of TS 24.301's Tracking Area Identity",
            ),
            _source(_GTPV2, "8.21.4", "figure 8.21.4-1, the TAI field"),
        ),
        (Octets(5, 5), Plmn()),
        Depth.FULL,
        "the tracking area code takes any value, its coding being each"
        " administration's",
        example=b"\x21\xf3\x54\x00\x01",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "CellGlobalIdOrServiceAreaIdFixedLength",
        "a Cell Global Identification or Service Area Identification: a PLMN"
        " identity, a location area code and a cell identity or service area"
        " code",
        (
            _source(
                _MAP,
                "17.7.8",
                "CellGlobalIdOrServiceAreaIdFixedLength ::= OCTET STRING"
                " (SIZE (7)) and its internal structure",
            ),
        ),
        (Octets(7, 7), Plmn()),
        Depth.FULL,
        "the location area code and the cell identity or service area code"
        " take any value",
        example=b"\x21\xf3\x54\x00\x01\x00\x01",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "RAIdentity",
        "a Routing Area Identity: a PLMN identity, a location area code and a"
        " routing area code",
        (
            _source(
                _MAP,
                "17.7.8",
                "RAIdentity ::= OCTET STRING (SIZE (6)), TS 29.060's value part",
            ),
            _source(_GTPV1, "7.7.3", "figure 11, the RAI information element"),
        ),
        (Octets(6, 6), Plmn()),
        Depth.FULL,
        "the location and routing area codes take any value",
        example=b"\x21\xf3\x54\x00\x01\x01",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "LAIFixedLength",
        "a Location Area Identification: a PLMN identity and a location area code",
        (
            _source(
                _MAP,
                "17.7.8",
                "LAIFixedLength ::= OCTET STRING (SIZE (5)) and its internal structure",
            ),
        ),
        (Octets(5, 5), Plmn()),
        Depth.FULL,
        "the location area code takes any value",
        example=b"\x21\xf3\x54\x00\x01",
    ),
    Element(
        "TS29.002",
        "17.7.1",
        "GeographicalInformation",
        "an ellipsoid point with uncertainty circle",
        (
            _source(
                _MAP,
                "17.7.1",
                "GeographicalInformation ::= OCTET STRING (SIZE (8)): 'Only"
                " the description of an ellipsoid point with uncertainty"
                " circle ... is allowed to be used'",
            ),
            _source(
                _GAD,
                "7.3.2",
                "figure 6: type of shape 0001 and spare in octet 1, a 0 spare"
                " bit before the uncertainty code in octet 8",
            ),
            _source(
                _GAD, "7.2", "table 2a, 0001 an ellipsoid point with uncertainty circle"
            ),
        ),
        (
            Octets(8, 8),
            Field("type of shape", 1, 8, 5, _codes(0b0001)),
            Field("spare", 1, 4, 1, _SPARE_ZERO),
            Field("spare", 8, 8, 8, _SPARE_ZERO),
        ),
        Depth.FULL,
        "the latitude, longitude and uncertainty code take any value",
        example=b"\x10\x00\x00\x01\x00\x00\x01\x05",
    ),
    Element(
        "TS29.002",
        "17.7.1",
        "GeodeticInformation",
        "ITU-T Q.763's calling geodetic location, an ellipsoid point with uncertainty",
        (
            _source(
                _MAP,
                "17.7.1",
                "GeodeticInformation ::= OCTET STRING (SIZE (10)): 'Only the"
                " description of an ellipsoid point with uncertainty circle as"
                " specified in Q.763 (1999) is allowed to be used'",
            ),
            Source(
                "ITU-T-Q.763",
                "(12/1999)",
                "3.88",
                "figure 82.1: spare, LPRI and screening in octet 1, the"
                " extension bit and type of shape (0000001, ellipsoid point"
                " with uncertainty) in octet 2; 3.88.2, figure 82.3: a spare"
                " bit before the uncertainty code and before the confidence,"
                " 'K = 0 ... no information, and 100 < K = 128 which are not"
                " used'; clause 1.10, 'Spare bits are coded 0'",
            ),
        ),
        (
            Octets(10, 10),
            Field("spare", 1, 8, 5, _SPARE_ZERO),
            Field("type of shape", 2, 7, 1, _codes(0b0000001)),
            Field("spare", 9, 8, 8, _SPARE_ZERO),
            Field("spare", 10, 8, 8, _SPARE_ZERO),
            Field("confidence", 10, 7, 1, ((0, 100),), meaning="0 to 100"),
        ),
        Depth.FULL,
        "the extension bit's value for a parameter of one octet of shape is"
        " not stated; the LPRI's spare code 11 is one for future use, not"
        " refused",
        example=b"\x03\x81\x00\x00\x01\x00\x00\x01\x05\x32",
    ),
    Element(
        "TS32.422",
        "5.10.3",
        "List of Measurements",
        "the MDT measurements to collect, a 4-octet bitmap, its first octet"
        " the AVP's most significant",
        (
            _source(
                _TRACE,
                "5.10.3",
                "'The parameter is 4 octet long bitmap' and its UMTS, LTE and"
                " NR tables",
            ),
        ),
        (
            Field("spare", 2, 8, 8, _SPARE_ZERO),
            Field("spare", 3, 8, 1, _SPARE_ZERO, last=4, meaning="all 0"),
        ),
        Depth.PARTIAL,
        "only the bits spare in every RAT's table are checked: the AVP does"
        " not say which RAT its bits are read for, and octet 2's other spare"
        " bits are measurements in another RAT",
        example=b"\x01\x00\x00\x00",
    ),
    Element(
        "TS32.422",
        "5.10.4",
        "Reporting Trigger",
        "the MDT reporting triggers, a one-octet bitmap",
        (
            _source(
                _TRACE,
                "5.10.4",
                "'The parameter is one octet long bitmap', and only one of bits"
                " 1, 2 and 5 set for LTE and NR, bit 1 not with bit 3 or 4 for"
                " UMTS",
            ),
        ),
        (),
        Depth.NONE,
        "the document defines one octet, TS 29.272 an Unsigned32 whose most"
        " significant bit is bit 8 of its first octet, so which of the four"
        " octets holds the bitmap is said by neither",
    ),
    Element(
        "TS32.422",
        "5.10.7",
        "Event Threshold for Event A2",
        "an A2 event threshold for RSRP, RSRQ or SINR",
        (
            _source(
                _TRACE,
                "5.10.7",
                "RSRP 0-97 in LTE and 0-127 in NR, RSRQ 0-34 in LTE and 0-127"
                " in NR, SINR 0-127 in both",
            ),
        ),
        (Integer(0, 127),),
        Depth.PARTIAL,
        "an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not"
        " checked: the AVP does not say which RAT it is for",
    ),
    Element(
        "TS32.422",
        "5.10.13",
        "Event Threshold for Event 1f",
        "a UMTS 1f event threshold",
        (
            _source(
                _TRACE,
                "5.10.13",
                "'an Integer number with the value range -120..165'",
            ),
        ),
        (Integer(-120, 165),),
        Depth.PARTIAL,
        "the narrower range of the measurement quantity (CPICH RSCP"
        " -120..-25, Ec/No -24..0, pathloss 30..165) is not checked: it is"
        " another AVP's",
    ),
    Element(
        "TS32.422",
        "5.10.14",
        "Event Threshold for Event 1i",
        "a UMTS 1i event threshold in dBm",
        (
            _source(
                _TRACE,
                "5.10.14",
                "'an Integer number with the value range -120..-25'",
            ),
        ),
        (Integer(-120, -25),),
        Depth.FULL,
    ),
    Element(
        "TS32.422",
        "5.10.19",
        "Positioning Method",
        "the MDT positioning methods, a bitmap",
        (
            _source(
                _TRACE,
                "5.10.19",
                "the LTE table (spare, E-Cell ID bit 2, GNSS bit 1) and the NR"
                " table (spare, GNSS bit 1)",
            ),
        ),
        (Field("spare", 1, 8, 3, _SPARE_ZERO),),
        Depth.PARTIAL,
        "bit 2, spare in NR, is E-Cell ID in LTE, and the AVP does not say"
        " which RAT it is for",
        example=b"\x01",
    ),
    Element(
        "TS32.422",
        "5.10.15",
        "Measurement Quantity",
        "the UMTS M1 measurement the 1f event threshold applies to, a bitmap",
        (
            _source(
                _TRACE,
                "5.10.15",
                "'No more than one bit shall be selected at a time'",
            ),
        ),
        (OneBit(1),),
        Depth.FULL,
        "bits 8-4 are reserved, not refused, since the clause does not say"
        " they are not sent",
        example=b"\x02",
    ),
    Element(
        "TS32.422",
        "5.10.35",
        "Collection Period M7 in NR",
        "the collection period of NR packet loss rate measurements, in minutes",
        (_source(_TRACE, "5.10.35", "'1..60 min'"),),
        (Integer(1, 60),),
        Depth.FULL,
    ),
    Element(
        "TS23.003",
        "19.4.2.4",
        "MME node FQDN",
        "an MME's node FQDN",
        (
            _source(
                _NUMBERING,
                "19.4.2.4",
                "mmec<MMEC>.mmegi<MMEGI>.mme.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org,"
                " MMEC 2 and MMEGI 4 hexadecimal digits",
            ),
            _source(_NUMBERING, "19.2", "MNC and MCC 3 digits each"),
        ),
        (
            Fqdn(
                (
                    "mmec<MMEC:hex:2>.mmegi<MMEGI:hex:4>.mme.epc"
                    ".mnc<MNC:digit:3>.mcc<MCC:digit:3>.3gppnetwork.org",
                )
            ),
        ),
        Depth.FULL,
    ),
    Element(
        "TS23.003",
        "19.4.2",
        "MME or SGSN node FQDN",
        "an MME's node FQDN (clause 19.4.2.4) or an SGSN's (clause 19.4.2.6)",
        (
            _source(
                _NUMBERING,
                "19.4.2.4",
                "mmec<MMEC>.mmegi<MMEGI>.mme.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org",
            ),
            _source(
                _NUMBERING,
                "19.4.2.6",
                "nri-sgsn<NRI>.rac<RAC>.lac<LAC>.rac.epc.mnc<MNC>.mcc<MCC>"
                ".3gppnetwork.org, NRI, RAC and LAC 4 hexadecimal digits",
            ),
            _source(_NUMBERING, "19.2", "MNC and MCC 3 digits each"),
        ),
        (
            Fqdn(
                (
                    "mmec<MMEC:hex:2>.mmegi<MMEGI:hex:4>.mme.epc"
                    ".mnc<MNC:digit:3>.mcc<MCC:digit:3>.3gppnetwork.org",
                    "nri-sgsn<NRI:hex:4>.rac<RAC:hex:4>.lac<LAC:hex:4>.rac.epc"
                    ".mnc<MNC:digit:3>.mcc<MCC:digit:3>.3gppnetwork.org",
                )
            ),
        ),
        Depth.FULL,
    ),
    Element(
        "TS24.008",
        "10.5.5.32",
        "eDRX value",
        "the eDRX value field of the Extended DRX parameters, 4 bits",
        (
            _source(
                _NAS,
                "10.5.5.32",
                "table 10.5.5.32, eDRX value (octet 3 bits 4 to 1): 'All other"
                " values shall be interpreted as 0000'",
            ),
        ),
        (),
        Depth.FULL,
        "the octet carrying the field is held to TS 29.272's own length and bits"
        " rules instead",
        valid="every 4-bit value is valid, an undefined one read as 0000;"
        " nothing to refuse",
    ),
    Element(
        "TS24.008",
        "10.5.5.32",
        "Paging Time Window",
        "the Paging Time Window field of the Extended DRX parameters, 4 bits",
        (
            _source(
                _NAS,
                "10.5.5.32",
                "table 10.5.5.32, Paging Time Window (octet 3 bits 8 to 5),"
                " every 4-bit value defined",
            ),
        ),
        (),
        Depth.FULL,
        "the octet carrying the field is held to TS 29.272's own length and bits"
        " rules instead",
        valid="every 4-bit value is defined; nothing to refuse",
    ),
    Element(
        "TS23.501",
        None,
        "5QI",
        "a 5G QoS Identifier",
        (
            _source(
                ("TS23.501", "19.9.0"),
                "5.7.2.1",
                "'A 5QI is a scalar', standardized values in table 5.7.4-1",
            ),
        ),
        (),
        Depth.NONE,
        "the document gives no range: beside the standardized values a 5QI"
        " may be a pre-configured or dynamically assigned one",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "NR-CGI",
        "an NR Cell Global Identity: a PLMN identity and a 36-bit NR cell identity",
        (
            _source(
                _MAP,
                "17.7.8",
                "NR-CGI ::= OCTET STRING (SIZE (8)), coded as TS 38.413 describes",
            ),
            _source(
                _NGAP,
                "9.3.1.7",
                "NR CGI: PLMN Identity (9.3.3.5, OCTET STRING (SIZE(3))) and"
                " NR Cell Identity BIT STRING (SIZE(36))",
            ),
        ),
        (Octets(8, 8), Plmn()),
        Depth.PARTIAL,
        "where the 36 bits of the NR cell identity sit in the last five octets,"
        " and what the other four are, neither document says",
        example=b"\x21\xf3\x54\x00\x00\x00\x00\x10",
    ),
    # TS 29.329's.
    Element(
        "TS29.328",
        "C",
        "Sh-Data",
        "the user data an AS reads, is notified of or updates over Sh, an XML document",
        (
            _source(_SH, "Annex C", "Figure C.1.1: Sh-Data, the UML model"),
            _source(
                _SH,
                "Annex D",
                "the XML schema for the Sh interface user profile, ShDataType.xsd",
            ),
        ),
        (),
        Depth.NONE,
        "an XML document the schema of Annex D defines: no shape of the"
        " registry reads XML",
    ),
    Element(
        "TS29.002",
        "17.7.3",
        "CallReferenceNumber",
        "a call reference number (the callReferenceNumber of SendRoutingInfoArg"
        " and ProvideRoamingNumberArg)",
        (
            _source(
                _MAP, "17.7.3", "CallReferenceNumber ::= OCTET STRING (SIZE (1..8))"
            ),
        ),
        (Octets(1, 8),),
        Depth.FULL,
        "the octets take any value: the type says nothing more of them",
        example=b"\x01\x02\x03\x04",
    ),
    Element(
        "TS29.002",
        "17.7.8",
        "ISDN-AddressString",
        "an ISDN number as an AddressString: a nature of address and numbering"
        " plan octet, then TBCD digits (the gmsc-Address of"
        " ProvideRoamingNumberArg, clause 17.7.3)",
        (
            _source(
                _MAP,
                "17.7.3",
                "ProvideRoamingNumberArg: gmsc-Address [8] ISDN-AddressString",
            ),
            _source(
                _MAP,
                "17.7.8",
                "ISDN-AddressString ::= AddressString (SIZE"
                " (1..maxISDN-AddressLength)), maxISDN-AddressLength 9;"
                " AddressString's TBCD-STRING",
            ),
        ),
        (
            Octets(1, 9),
            Field("extension, 1 for no extension", 1, 8, 8, _codes(1)),
            Tbcd(2),
        ),
        Depth.FULL,
        "the nature of address and numbering plan values the type marks"
        " reserved are not refused, since it does not say they are not sent",
        example=b"\x91\x21\x43\x65",
    ),
    # TS 29.273's.
    Element(
        "TS24.302",
        "8.1.1",
        "Access Network Identity",
        "an Access Network Identity: an ANID prefix and any additional ANID"
        " strings, joined by ':'",
        (
            _source(
                _NON_3GPP_ACCESS,
                "8.1.1.1",
                "UTF-8 text in NFKC, an octet string of at most 253 octets",
            ),
            _source(
                _NON_3GPP_ACCESS,
                "8.1.1.2",
                "tables 8.1.1.2-1 and 8.1.1.2-2, the prefixes HRPD, WIMAX, WLAN,"
                " ETHERNET and 5G",
            ),
        ),
        (),
        Depth.NONE,
        "no shape of the registry bounds a text's octets, and a prefix the"
        " tables do not name is 'Not defined', not refused: NOTE 6 leaves"
        " further prefixes to be defined",
    ),
    _network_name("8.2.5.1", "AT_FULL_NAME_FOR_NETWORK", "full"),
    _network_name("8.2.5.2", "AT_SHORT_NAME_FOR_NETWORK", "short"),
    Element(
        "TS33.402",
        "9.2.1.2.2",
        "FA-RK",
        "the FA root key the authenticator derives MN-FA keys from",
        (
            _source(
                _NON_3GPP_SECURITY,
                "9.2.1.2.2",
                "'FA-RK = HMAC-SHA1(MIP-RK, \"FA-RK\")', a 160-bit output",
            ),
        ),
        (Octets(20, 20),),
        Depth.FULL,
        "a key: any value",
        example=bytes(range(20)),
    ),
    Element(
        "TS33.402",
        "9.2.1.2.2",
        "FA-RK-SPI",
        "the security parameter index identifying the FA-RK, the MIP-SPI",
        (
            _source(
                _NON_3GPP_SECURITY,
                "9.2.1.2.2",
                "'MIP-SPI = the 4 most significant bytes of HMAC-SHA256 (MIP-RK,"
                " \"SPI CMIP PMIP \"| APN))', distributed 'in AAA protocol"
                " attribute FA-RK-SPI'",
            ),
        ),
        (),
        Depth.NONE,
        "a derived index: the clause steps it clear of the other active SPIs"
        " and of the top of the range, which a single message cannot show",
    ),
    Element(
        "TS33.402",
        "A.3",
        "WLCP key",
        "the key protecting WLCP signalling between the UE and the TWAG,"
        " derived from the EMSK",
        (
            _source(
                _NON_3GPP_SECURITY,
                "A.3",
                'the input S to the KDF, FC = 0x21, P0 = "wlcp-key"',
            ),
            _source(
                _NON_3GPP_SECURITY,
                "A.1",
                "'the key derivation function (KDF) specified in TS 33.220'",
            ),
            _source(_GBA, "B.2.0", "'derived key = HMAC-SHA-256 ( Key , S )'"),
        ),
        (Octets(32, 32),),
        Depth.FULL,
        "a key: any value",
        example=bytes(range(32)),
    ),
    Element(
        "TS29.274",
        "8.103",
        "RAN/NAS Cause",
        "the RAN/NAS Cause information element from its octet 5: the protocol"
        " and cause types, then the cause value",
        (
            _source(
                _GTPV2,
                "8.103",
                "figure 8.103-1: octet 5 Protocol Type (bits 8-5) and Cause"
                " Type (bits 4-1), octets 6 to m the Cause Value, one octet for"
                " an S1AP, EMM or ESM cause, two for a Diameter or IKEv2 one;"
                " octets (m+1) to (n+4) present only if explicitly specified",
            ),
        ),
        (Octets(2, None),),
        Depth.PARTIAL,
        "that a Diameter or IKEv2 cause takes two octets is not checked: no"
        " shape ties a length to a field's value; the protocol types 6 to 15"
        " are spare, not refused, since the clause does not say they are not"
        " sent, and the cause type and value take any value",
        example=b"\x10\x05",
    ),
    Element(
        "TS29.274",
        "8.108",
        "Presence Reporting Area Action",
        "the Presence Reporting Area Action information element from its"
        " octet 9: the counts of the elements composing the area, then the"
        " elements",
        (
            _source(
                _GTPV2,
                "8.108",
                "figure 8.108-1: octets 9 to 14 the numbers of TAIs, RAIs,"
                " macro eNodeBs, home eNodeBs, ECGIs, SAIs and CGIs, octets 15"
                " on the elements, then the number of extended macro eNodeBs"
                " and their IDs",
            ),
        ),
        (Octets(6, None),),
        Depth.PARTIAL,
        "that the elements' octets add up to the counts is not checked: no"
        " shape sums them; the spare bits of octets 10 to 14 are the ones TS"
        " 29.274 clause 8.1 says are sent as 0 and not evaluated by the"
        " receiver, and each count's own bits bound it at 15 or 63",
        example=bytes(6),
    ),
    Element(
        "TS29.274",
        "8.109",
        "PRA Identifier",
        "the PRA Identifier of the Presence Reporting Area Information"
        " information element, its octets 5 to 7",
        (
            _source(
                _GTPV2,
                "8.109",
                "figure 8.109-1, octets 5 to 7 'PRA Identifier', 'encoded using"
                " full hexadecimal representation (binary, not ASCII encoding)'",
            ),
            _source(
                _NUMBERING,
                "19.10",
                "'The PRA ID shall be encoded as an integer on 3 octets'",
            ),
        ),
        (Octets(3, 3),),
        Depth.FULL,
        "the identifier takes any value, its most significant bit telling a"
        " UE-dedicated area from a core network predefined one",
        example=b"\x00\x00\x01",
    ),
    Element(
        "RFC3162",
        "2.3",
        "Framed-IPv6-Prefix",
        "the Framed-IPv6-Prefix attribute's value: a reserved octet, the"
        " prefix length and the prefix",
        (
            Source(
                "RFC3162",
                "(August 2001)",
                "2.3",
                "Reserved 'always set to zero', Prefix-Length 'At least 0 and no"
                " larger than 128', Prefix 'up to 16 octets in length', the"
                " attribute's Length 'At least 4 and no larger than 20'",
            ),
        ),
        (
            Octets(2, 18),
            Field("Reserved", 1, 8, 1, _SPARE_ZERO),
            Field("Prefix-Length", 2, 8, 1, ((0, 128),)),
        ),
        Depth.PARTIAL,
        "that the bits beyond the prefix length are zero is not checked: no"
        " shape reads a length from a field",
        example=b"\x00\x40\x20\x01\x0d\xb8\x00\x00\x00\x00",
    ),
    Element(
        "TS29.212",
        "5b.4.0",
        "Framed-IPv6-Prefix",
        "the UE's full IPv6 address as the TDF's unsolicited Sd CC-Request"
        " carries it: RFC 3162's Framed-IPv6-Prefix with a prefix length of 128",
        (
            Source(
                "TS29.212",
                "V19.1.0",
                "5b.4.0",
                "table 5b.4.0.1, Framed-Ipv6-Prefix: 'The TDF shall set the"
                ' "Prefix Length" to 128 and encode the Ipv6 address of the UE'
                ' within the "Prefix" field\'',
            ),
            Source(
                "RFC3162",
                "(August 2001)",
                "2.3",
                "Reserved 'always set to zero', Prefix-Length, Prefix 'up to 16"
                " octets in length'",
            ),
        ),
        (
            Octets(18, 18),
            Field("Reserved", 1, 8, 1, _SPARE_ZERO),
            Field("Prefix-Length", 2, 8, 1, ((128, 128),)),
        ),
        Depth.FULL,
        "the address takes any value",
        example=b"\x00\x80\x20\x01\x0d\xb8" + bytes(11) + b"\x01",
    ),
    Element(
        "TS29.214",
        "5.4.0",
        "Framed-IPv6-Prefix",
        "the UE's full IPv6 address as the AF's Rx requests carry it: RFC"
        " 3162's Framed-IPv6-Prefix with a prefix length of 128",
        (
            Source(
                "TS29.214",
                "V19.3.0",
                "5.4.0",
                "table 5.4.0.1, Framed-IPv6-Prefix: 'The AF shall set the"
                ' "Prefix Length" to 128 and encode the Ipv6 address of the UE'
                ' within the "Prefix" field\'',
            ),
            Source(
                "RFC3162",
                "(August 2001)",
                "2.3",
                "Reserved 'always set to zero', Prefix-Length, Prefix 'up to 16"
                " octets in length'",
            ),
        ),
        (
            Octets(18, 18),
            Field("Reserved", 1, 8, 1, _SPARE_ZERO),
            Field("Prefix-Length", 2, 8, 1, ((128, 128),)),
        ),
        Depth.FULL,
        "the address takes any value",
        example=b"\x00\x80\x20\x01\x0d\xb8" + bytes(11) + b"\x01",
    ),
    Element(
        "TS23.003",
        "12.7.1",
        "NID",
        "a Network Identifier of a Stand-Alone Non-Public Network",
        (
            _source(
                _NUMBERING,
                "12.7.1",
                "'The NID shall consist of 11 hexadecimal digits, one digit for"
                " representing an assignment mode and 10 digits for a NID"
                " value'; assignment modes 0, 1 and 2, 'Other Assignment mode"
                " values are spare, for future use'",
            ),
        ),
        (),
        Depth.NONE,
        "the clause gives the NID as 11 hexadecimal digits, and neither it"
        " nor TS 29.214 clause 5.3.68 says how an OctetString carries them,"
        " as 11 characters or packed in 44 bits",
    ),
    Element(
        "TS24.501",
        "9.11.3.2",
        "5GMM cause",
        "the 5GMM cause, a type 3 information element of 2 octets, its cause"
        " value in octet 2",
        (
            _source(
                _NAS_5GS,
                "9.11.3.2",
                "'The 5GMM cause is a type 3 information element with length"
                " of 2 octets'; table 9.11.3.2.1, the cause value in octet 2,"
                " 'Any other value received by the mobile station shall be"
                " treated as 0110 1111'",
            ),
        ),
        (Integer(0, 65535),),
        Depth.PARTIAL,
        "whether the Unsigned32 carries the cause value alone or the element's"
        " two octets with its IEI the clauses do not say, so only that it"
        " fits in two octets is checked; a value table 9.11.3.2.1 does not"
        " name is read as 'protocol error, unspecified', not refused",
    ),
    Element(
        "TS24.501",
        "9.11.4.2",
        "5GSM cause",
        "the 5GSM cause, a type 3 information element of 2 octets, its cause"
        " value in octet 2",
        (
            _source(
                _NAS_5GS,
                "9.11.4.2",
                "'The 5GSM cause is a type 3 information element with a length"
                " of 2 octets'; table 9.11.4.2.1, the cause value in octet 2,"
                " 'Any other value received by the UE shall be treated as 0001"
                " 1111'",
            ),
        ),
        (Integer(0, 65535),),
        Depth.PARTIAL,
        "whether the Unsigned32 carries the cause value alone or the element's"
        " two octets with its IEI the clauses do not say, so only that it"
        " fits in two octets is checked; a value table 9.11.4.2.1 does not"
        " name is read as 'Request rejected, unspecified', not refused",
    ),
    Element(
        "TS38.413",
        "9.4.5",
        "Cause",
        "the group of an NGAP Cause, the index of its CHOICE alternative",
        (
            _source(
                _NGAP,
                "9.4.5",
                "Cause ::= CHOICE { radioNetwork, transport, nas, protocol,"
                " misc, choice-Extensions }, Cause-ExtIEs holding no IE",
            ),
        ),
        (Integer(0, 4),),
        Depth.FULL,
        "the CHOICE's choice-Extensions holds no IE in this edition, so the"
        " five groups 0 to 4 are all",
    ),
    Element(
        "TS29.078",
        "5.1",
        "BearerCapability",
        "CAP's bearer capability, its bearerCap octets",
        (
            _source(
                _CAP,
                "5.1",
                "bearerCap [0] OCTET STRING"
                " (SIZE(2..bound.&maxBearerCapabilityLength)),"
                " 'the ISUP User Service Information, ETSI EN 300 356-1 [23]"
                " encoding shall be used'",
            ),
            _source(_CAP, "5.5", "MAXIMUM-FOR-BEARER-CAPABILITY 11"),
        ),
        (Octets(2, 11),),
        Depth.LENGTH,
        "the User Service Information's fields are ETSI EN 300 356-1's, a"
        " document the corpus does not hold, and are not read",
        example=bytes([0x80, 0x90]),
    ),
    Element(
        "TS23.032",
        "7",
        "Geographical area description",
        "a geographical area description of any shape: the type of shape in"
        " octet 1's bits 8-5, then the shape",
        (
            _source(
                _GAD,
                "7.2",
                "table 2a, the types of shape 0000 to 1110, 'other values"
                " reserved for future use'",
            ),
            _source(_GAD, "7.3.1", "figure 5, an ellipsoid point in 7 octets"),
        ),
        (Octets(7, None),),
        Depth.PARTIAL,
        "the shape's own layout and length are not checked: the AVP may carry"
        " any of them; the type codes table 2a reserves are not refused,"
        " since the clause does not say they are not sent",
        example=bytes(7),
    ),
    Element(
        "TS29.061",
        "16.4.7.2",
        "3GPP-Charging-Id",
        "the Charging ID of the 3GPP-Charging-Id sub-attribute",
        (
            _source(
                _GI,
                "16.4.7.2",
                "sub-attribute 2, 3GPP-Charging ID: 'Length: 6', 'Charging ID"
                " value: 32 bits unsigned integer'",
            ),
        ),
        (),
        Depth.FULL,
        valid="a 32-bit charging identifier: every value of the Unsigned32",
    ),
    Element(
        "TS23.003",
        "2.5",
        "LMSI",
        "a Local Mobile Station Identity a VLR allocates",
        (
            _source(
                _NUMBERING,
                "2.5",
                "'The LMSI consists of 4 octets and may be allocated by the VLR."
                " The VLR shall not allocate the value zero.'",
            ),
        ),
        (Octets(4, 4), Field("LMSI", 1, 8, 1, ((1, 0xFFFFFFFF),), last=4)),
        Depth.FULL,
        "any value but zero, which the clause reserves for an LMSI the VLR is"
        " not to interpret",
        example=b"\x00\x00\x12\x34",
    ),
    Element(
        "TS29.274",
        "8.100",
        "TWAN Identifier",
        "the TWAN Identifier information element from its octet 5: its flags,"
        " the SSID's length and the SSID, then the fields the flags name",
        (
            _source(
                _GTPV2,
                "8.100",
                "figure 8.100-1, octet 5 the spare bits and the LAII, OPNAI,"
                " PLMNI, CIVAI and BSSIDI flags, octet 6 the SSID Length, octets"
                " 7 to k the SSID; 'The SSID is an Octet String which shall have"
                " a maximum length of 32 octets'",
            ),
        ),
        (Octets(2, None), Field("SSID Length", 2, 8, 1, ((0, 32),))),
        Depth.PARTIAL,
        "the fields the flags make present, and that the lengths add up to the"
        " payload's, are not checked: no shape reads a length or a flag from a"
        " field; the spare bits of octet 5, the payload's first, are the ones"
        " TS 29.274 clause 8.1 says are sent as 0 and not evaluated by the"
        " receiver",
        example=b"\x00\x04ssid",
    ),
    Element(
        "TS24.008",
        "10.5.6.13",
        "Temporary Mobile Group Identity",
        "a Temporary Mobile Group Identity: an MBMS Service ID, and an MCC and MNC",
        (
            _source(
                _NAS,
                "10.5.6.13",
                "figure 10.5.154, the IEI and length in octets 1 and 2, the MBMS"
                " Service ID in octets 3 to 5 and the MCC and MNC in octets 6 to"
                " 8, 'If octet 6 is included, then octets 7 and 8 shall also be"
                " included'",
            ),
        ),
        (),
        Depth.NONE,
        "the element is a type 4 information element of 5 to 8 octets, and"
        " neither it nor TS 29.061 clause 17.7.2 says whether the AVP carries"
        " its IEI and length octets or its contents alone",
    ),
    Element(
        "TS24.008",
        "10.5.6.14",
        "MBMS bearer capabilities",
        "an MS's MBMS bearer capabilities: the maximum bit rate for downlink"
        " it supports",
        (
            _source(
                _NAS,
                "10.5.6.14",
                "figure 10.5.155, the IEI and length in octets 1 and 2, the"
                " maximum bit rate for downlink in octet 3 and its extension in"
                " octet 4",
            ),
        ),
        (),
        Depth.NONE,
        "the element's octets are binary, and neither it nor TS 29.061 clause"
        " 17.7.3, which types the AVP UTF8String and calls its content UTF-8"
        " encoded, says how a UTF8String spells them",
    ),
    Element(
        "TS29.060",
        "7.7.54",
        "CAMEL Charging Information Container",
        "the CAMELInformationPDP of an SGSN's S-CDR, with its tag and length",
        (
            _source(
                _GTPV1,
                "7.7.54",
                "figure 7.7.54.1, octets 4 to m the CAMELInformationPDP IE, 'used"
                " to copy the CAMELInformationPDP IE including Tag and Length"
                " from the SGSN's CDR (SCDR)', which 'is defined in 3GPP TS"
                " 32.298'",
            ),
        ),
        (),
        Depth.NONE,
        "the container holds TS 32.298's CAMELInformationPDP in its ASN.1"
        " encoding, tag and length included, which no shape of the registry"
        " decodes",
    ),
    Element(
        "TS29.060",
        "7.7.68",
        "Additional MBMS Trace Info",
        "the BM-SC's trace parameters: Trace Reference2, Trace Recording"
        " Session Reference, the triggering events, trace depth and list of"
        " interfaces in the BM-SC and its Trace Activity Control",
        (
            _source(
                _GTPV1,
                "7.7.68",
                "figure 7.7.68.1, 'Length = 8' after the type and length octets;"
                " figure 7.7.68.2, Trace Activation 1, Trace Deactivation 0,"
                " 'All other values are reserved'",
            ),
        ),
        (Octets(8, 8),),
        Depth.LENGTH,
        "the fields are not placed: figure 7.7.68.1 numbers Trace Reference2"
        " octets 4 to 6 and the Trace Recording Session Reference no octets of"
        " its own, so where each field sits is not certain; the Trace Activity"
        " Control's reserved values would not be refused, since the figure"
        " does not say they are not sent",
        example=bytes(range(1, 9)),
    ),
    Element(
        "TS48.018",
        "11.3.92",
        "Time to MBMS Data Transfer",
        "the value part of the Time to MBMS Data Transfer IE: the time to the"
        " start of the data transfer, 1 to 256 seconds",
        (
            _source(
                _BSSGP,
                "11.3.92",
                "table 11.3.92.a, the value part in octet 3; table 11.3.92.b,"
                " 0 0 0 0 0 0 0 0 1s to 1 1 1 1 1 1 1 1 256s",
            ),
        ),
        (Octets(1, 1),),
        Depth.FULL,
        "every value of the octet is a time, 1 to 256 seconds",
        example=b"\x09",
    ),
    Element(
        "TS23.040",
        "9.2.3.24",
        "User-Data-Header",
        "the header of an SM's TP-User-Data: its length, then information"
        " elements, each an identifier, a length and its data",
        (
            _source(
                _SMS,
                "9.2.3.24",
                "'Length of User Data Header 1 octet', each information element"
                " 'Information-Element-Identifier 1 octet', 'Length of"
                " Information-Element 1 octet' and '0 to \"n\" octets' of data",
            ),
        ),
        (Octets(1, None),),
        Depth.LENGTH,
        "whether the AVP carries the Length of User Data Header octet before"
        " the information elements neither document says, so the lengths"
        " the header's fields give are not checked; an identifier the"
        " clause reserves is skipped by the receiver, not refused",
        example=bytes([0x05, 0x00, 0x03, 0x01, 0x02, 0x01]),
    ),
    Element(
        "TS23.003",
        "19.8",
        "TWAN Operator Name",
        "the name of a TWAN operator that is no mobile operator, a realm",
        (
            _source(
                _NUMBERING,
                "19.8",
                "'encoded as a realm in the form of an Internet domain name',"
                " labels of 'the alphabetic characters (A-Z and a-z), digits"
                " (0-9) and the hyphen (-)', each beginning and ending 'with"
                " either an alphabetic character or a digit'",
            ),
        ),
        (),
        Depth.NONE,
        "no shape of the registry reads a domain name's labels, their"
        " characters and how each begins and ends",
    ),
    Element(
        "TS23.003",
        "19.6A",
        "NCGI",
        "an NR Cell Global Identity: a PLMN identity and a 36-bit NR cell identity",
        (
            _source(
                _NUMBERING,
                "19.6A",
                "'composed of the concatenation of the PLMN Identifier"
                " (PLMN-Id) and the NR Cell Identity (NCI)', the NCI 'of fixed"
                " length of 36 bits' and 'coded using full hexadecimal"
                " representation'",
            ),
        ),
        (),
        Depth.NONE,
        "the clause gives the NCGI as a PLMN identity and 36 bits, and"
        " neither it nor TS 32.299 clause 7.2.254 says how a UTF8String"
        " spells them",
    ),
    Element(
        "TS36.331",
        "6.3.4",
        "ARFCN-ValueEUTRA-r9",
        "an E-UTRA carrier frequency's ARFCN, 0 to maxEARFCN2 (262143)",
        (
            _source(
                _RRC,
                "6.3.4",
                "'ARFCN-ValueEUTRA-r9 ::= INTEGER (0..maxEARFCN2)'",
            ),
            _source(
                _RRC,
                "8.1",
                "'Transfer syntax for RRC PDUs is derived from their ASN.1"
                " definitions by use of Packed Encoding Rules, unaligned'",
            ),
        ),
        (),
        Depth.NONE,
        "the clause gives an ASN.1 type, and clause 8.1's unaligned PER is"
        " the transfer syntax of RRC PDUs: neither it nor TS 32.299 clause"
        " 7.2.160A says by which rules the OctetString encodes the value",
    ),
    Element(
        "TS36.331",
        "9.3.2",
        "SL-Preconfiguration-r12",
        "a UE's sidelink pre-configured parameters: the general, the"
        " synchronisation and the communication pools' parameters",
        (
            _source(
                _RRC,
                "9.3.2",
                "'SL-Preconfiguration-r12 ::= SEQUENCE {', its"
                " preconfigGeneral-r12, preconfigSync-r12 and"
                " preconfigComm-r12 and their extensions",
            ),
            _source(
                _RRC,
                "8.1",
                "'Transfer syntax for RRC PDUs is derived from their ASN.1"
                " definitions by use of Packed Encoding Rules, unaligned'",
            ),
        ),
        (),
        Depth.NONE,
        "the clause gives an ASN.1 type, which no shape of the registry"
        " decodes, and neither it nor TS 32.299 clause 7.2.160C says by"
        " which encoding rules the OctetString carries it",
    ),
    Element(
        "TS23.040",
        "9.1.2.5",
        "Address fields",
        "an SM-TL address field: an Address-Length octet, a Type-of-Address"
        " octet and the Address-Value",
        (
            _source(
                _SMS,
                "9.1.2.5",
                "'an Address-Length field of one octet, a Type-of-Address field"
                " of one octet, and one Address-Value field of variable"
                " length', 'The maximum length of the full address field"
                " (Address-Length, Type-of-Address and Address-Value) is 12"
                " octets'",
            ),
        ),
        (Octets(2, 12),),
        Depth.LENGTH,
        "the Type-of-Address is not checked: a receiver reads its reserved"
        " values as Unknown, and the octets the clause draws are a figure;"
        " that the Address-Length counts the Address-Value's semi-octets is"
        " not checked: no shape ties a length to a field",
        example=bytes([0x0B, 0x91, 0x21, 0x43, 0x65, 0x87, 0x09, 0xF1]),
    ),
    Element(
        "TS23.040",
        "3.3.2",
        "Reason for absence",
        "the diagnostic of an absent user, a reason for absence",
        (
            _source(
                _SMS,
                "3.3.2",
                "table 1a, 'Assignment of values to reasons for absence (values"
                " must be in the range of 0 to 255', 0 to 13, 'All other"
                " integer values are reserved.'",
            ),
        ),
        (Integer(0, 255),),
        Depth.FULL,
        "the values 14 to 255 the table reserves are not refused, since it"
        " does not say they are not sent",
    ),
    Element(
        "TS23.040",
        "9.2.2",
        "TPDU",
        "an SM-TL protocol data unit, the TP-Message-Type-Indicator in its first octet",
        (
            _source(
                _SMS,
                "9.2.2",
                "'The SM-TL comprises the following six PDUs'",
            ),
            _source(
                _SMS,
                "9.2.3.1",
                "the TP-MTI in 'bits no 0 and 1 of the first octet of all"
                " PDUs', '1 1 Reserved', 'If an MS receives a TPDU with a"
                ' "Reserved" value in the TP-MTI it shall process the message'
                ' as if it were an "SMS-DELIVER"\'',
            ),
        ),
        (Octets(1, None),),
        Depth.LENGTH,
        "the PDU's type and fields are not checked: what a TP-MTI value"
        " means turns on the direction, which the AVP does not carry, and a"
        " receiver reads the reserved one as an SMS-DELIVER",
        example=bytes([0x04, 0x0B, 0x91, 0x21, 0x43, 0x65, 0x87, 0x09, 0xF1]),
    ),
    Element(
        "TS23.003",
        "5.3",
        "HSS-ID",
        "the identity of an HSS for SMS: decimal digits, an MCC, an MNC and an index",
        (
            _source(
                _NUMBERING,
                "5.3",
                "'The HSS-ID shall consist of decimal digits (0 through 9) only"
                " and be composed of the MCC consisting of three digits, the MNC"
                " consisting of two or three digits and an index consisting of"
                " one to several digits. The number of digits in the HSS-ID"
                " shall not exceed 15.'",
            ),
        ),
        (),
        Depth.NONE,
        "no shape of the registry bounds a text's digits",
    ),
    Element(
        "TS36.413",
        "9.2.1.3",
        "Cause",
        "the cause value of an S1AP Cause, the index of its group's ENUMERATED",
        (
            _source(
                _S1AP,
                "9.3.4",
                "Cause ::= CHOICE { radioNetwork CauseRadioNetwork, transport"
                " CauseTransport, nas CauseNas, protocol CauseProtocol, misc"
                " CauseMisc, ... }, each group an extensible ENUMERATED",
            ),
        ),
        (),
        Depth.NONE,
        "how many values a cause has turns on its group, which another AVP"
        " (Cause-Type) carries, and every group's ENUMERATED is extensible,"
        " so no bound holds of each",
    ),
    Element(
        "TS25.413",
        "9.2.1.4",
        "Cause",
        "the cause value of a RANAP Cause, an INTEGER numbered across the groups",
        (
            _source(
                _RANAP,
                "9.3.4",
                "Cause ::= CHOICE of CauseRadioNetwork (1..64),"
                " CauseTransmissionNetwork (65..80), CauseNAS (81..96),"
                " CauseProtocol (97..112), CauseMisc (113..128),"
                " CauseNon-Standard (129..256) and CauseRadioNetworkExtension"
                " (257..512), '-- Cause value 256 shall not be used --'",
            ),
        ),
        (Integer(1, 512),),
        Depth.PARTIAL,
        "value 256, which the module's comment says 'shall not be used', is"
        " not refused: no shape leaves out one value of a range; a value its"
        " group's INTEGER names no cause for is not refused either, since the"
        " groups leave room for causes to come",
    ),
    Element(
        "TS48.018",
        "11.3.8",
        "Cause",
        "the cause value of a BSSGP Cause IE, its one octet",
        (
            _source(
                _BSSGP,
                "11.3.8",
                "table 11.3.8.b, the cause values x00 to x8f, 'All values not"
                ' listed below shall be treated as "protocol error -'
                " unspecified\"'",
            ),
        ),
        (Integer(0, 255),),
        Depth.FULL,
        "a value the table does not list is treated as 'protocol error -"
        " unspecified', not refused",
    ),
    Element(
        "TS24.008",
        "10.5.5.14",
        "GMM cause",
        "the cause value of the GMM cause information element, its octet 2",
        (
            _source(
                _NAS,
                "10.5.5.14",
                "'a type 3 information element with 2 octets length', the cause"
                " value in octet 2, 'Any other value received by the mobile"
                " station shall be treated as 0110 1111'",
            ),
        ),
        (Integer(0, 255),),
        Depth.FULL,
        "a value table 10.5.147 does not name is read as 'Protocol error,"
        " unspecified', not refused",
    ),
    Element(
        "TS24.008",
        "10.5.6.6",
        "SM cause",
        "the cause value of the SM cause information element, its octet 2,"
        " which SM cause 2 carries in its octet 3",
        (
            _source(
                _NAS,
                "10.5.6.6",
                "'a type 3 information element with 2 octets length', the cause"
                " value in octet 2, 'Any other value received by the mobile"
                " station shall be treated as 0010 0010'",
            ),
            _source(
                _NAS,
                "10.5.6.6A",
                "'SM cause 2 value is coded as octet 2 of the SM cause"
                " information element'",
            ),
        ),
        (Integer(0, 255),),
        Depth.FULL,
        "a value table 10.5.157 does not name is read as another, not refused",
    ),
    Element(
        "TS24.301",
        "9.9.4.26",
        "Extended protocol configuration options",
        "the contents of the extended protocol configuration options IE from"
        " its octet 4: the configuration protocol octet, then the protocol"
        " and container entries",
        (
            _source(
                _EPS_NAS,
                "9.9.4.26",
                "'See clause 10.5.6.3A in 3GPP TS 24.008 [13].'",
            ),
            _source(
                _NAS,
                "10.5.6.3A",
                "'Extended protocol configuration options contents (octet 4 to"
                " octet n); Max value of 65535 octets', 'coded as octet 3 and"
                " above of protocol configuration options IE'",
            ),
            _source(
                _NAS,
                "10.5.6.3",
                "figure 10.5.136, octet 3: '1 ext', '0 0 0 0 Spare',"
                " 'Configuration protocol'",
            ),
        ),
        (Octets(1, 65535), Field("ext", 1, 8, 8, ((1, 1),))),
        Depth.PARTIAL,
        "the spare bits, which the receiver ignores (TS 24.008 clause 10.5),"
        " the configuration protocol and the protocol and container entries"
        " are not checked: no shape walks a list of entries",
        example=bytes([0x80, 0x00, 0x0D, 0x00]),
    ),
    Element(
        "TS29.274",
        "8.38",
        "Uplink number of packets allowed",
        "a field of the MM Context's APN Rate Control Status, octets (k+1) to (k+4)",
        (
            _source(
                _GTPV2,
                "8.38",
                "figure 8.38-10, APN Rate Control Status, octets (k+1) to (k+4)"
                " 'Uplink number of packets allowed'",
            ),
        ),
        (),
        Depth.FULL,
        valid="4 octets the Unsigned32 carries whole: every value",
    ),
    Element(
        "TS29.274",
        "8.38",
        "Number of additional exception reports",
        "a field of the MM Context's APN Rate Control Status, octets (k+5) to (k+8)",
        (
            _source(
                _GTPV2,
                "8.38",
                "figure 8.38-10, APN Rate Control Status, octets (k+5) to (k+8)"
                " 'Number of additional exception reports'",
            ),
        ),
        (),
        Depth.FULL,
        valid="4 octets the Unsigned32 carries whole: every value",
    ),
    Element(
        "TS29.274",
        "8.38",
        "Downlink number of packets allowed",
        "a field of the MM Context's APN Rate Control Status, octets (k+9) to (k+12)",
        (
            _source(
                _GTPV2,
                "8.38",
                "figure 8.38-10, APN Rate Control Status, octets (k+9) to (k+12)"
                " 'Downlink number of packets allowed'",
            ),
        ),
        (),
        Depth.FULL,
        valid="4 octets the Unsigned32 carries whole: every value",
    ),
    Element(
        "TS29.274",
        "8.38",
        "APN Rate Control Status validity Time",
        "a field of the MM Context's APN Rate Control Status, octets (k+13) to (k+20)",
        (
            _source(
                _GTPV2,
                "8.38",
                "figure 8.38-10, APN Rate Control Status, octets (k+13) to (k+20)"
                " 'APN Rate Control Status validity Time'",
            ),
        ),
        (),
        Depth.FULL,
        valid="8 octets the Unsigned64 carries whole: every value",
    ),
    Element(
        "TS23.003",
        "6.2.2",
        "IMEISV",
        "the International Mobile station Equipment Identity and Software"
        " Version Number",
        (
            _source(
                _NUMBERING,
                "6.2.2",
                "a Type Allocation Code of 8 digits, a Serial Number of 6 and a"
                " Software Version Number of 2, 'each element shall consist of"
                " decimal digits only'",
            ),
        ),
        (),
        Depth.NONE,
        "the clause gives the IMEISV as 16 decimal digits, and neither it"
        " nor RFC 8506 clause 8.53 says how an OctetString carries them, as"
        " 16 characters or packed two to an octet",
    ),
    Element(
        "TS23.003",
        "6.2.1",
        "IMEI",
        "the International Mobile station Equipment Identity",
        (
            _source(
                _NUMBERING,
                "6.2.1",
                "a Type Allocation Code of 8 digits, a Serial Number of 6 and a"
                " Check Digit or Spare Digit, 'each element shall consist of"
                " decimal digits only'",
            ),
        ),
        (),
        Depth.NONE,
        "the clause gives the IMEI as 15 decimal digits, and neither it nor"
        " RFC 8506 clause 8.57 says how an OctetString carries them, as 15"
        " characters or packed two to an octet",
    ),
    Element(
        "RFC5777",
        "4.1.7.8",
        "MAC-Address",
        "a layer 2 address in MAC-48 format",
        (
            Source(
                "RFC5777",
                "(February 2010)",
                "4.1.7.8",
                "'The value is a 6-octet encoding of the address as it would"
                " appear in the frame header'",
            ),
        ),
        (Octets(6, 6),),
        Depth.FULL,
        "the address takes any value",
        example=bytes.fromhex("0010a42319c0"),
    ),
    Element(
        "RFC4291",
        "2.5.1",
        "Modified EUI-64",
        "an interface identifier in Modified EUI-64 format",
        (
            Source(
                "RFC4291",
                "(February 2006)",
                "2.5.1",
                "interface identifiers 'required to be 64 bits long and to be"
                " constructed in Modified EUI-64 format', its 'u' bit telling"
                " universal from local scope",
            ),
        ),
        (Octets(8, 8),),
        Depth.FULL,
        "the identifier takes any value, its 'u' bit set or not",
        example=bytes.fromhex("021122fffe334455"),
    ),
)

_BY_KEY = {element.key: element for element in REGISTRY}
assert len(_BY_KEY) == len(REGISTRY), "an element is registered twice"


def lookup(document: str, clause: str | None, name: str | None) -> Element | None:
    """The entry for the element a rule names, or None where the registry
    has none."""
    return _BY_KEY.get((document, clause, name))


def of_rule(rule: ast.EncodingRule) -> Element | None:
    """The entry for an `encoding element` rule, None for another codec or
    an element the registry does not have."""
    if rule.codec is not ast.Codec.ELEMENT or rule.document is None:
        return None
    return lookup(rule.document, rule.clause, rule.element)


def data_types(element: Element) -> frozenset[ast.DataType] | None:
    """The AVP types an element's checks can describe, None for any."""
    if element.integer:
        return frozenset(
            {
                ast.DataType.UNSIGNED32,
                ast.DataType.INTEGER32,
                ast.DataType.UNSIGNED64,
                ast.DataType.INTEGER64,
            }
        )
    if element.text:
        return frozenset(
            {
                ast.DataType.OCTET_STRING,
                ast.DataType.UTF8_STRING,
                ast.DataType.DIAMETER_IDENTITY,
            }
        )
    if any(isinstance(shape, Octets | Plmn | Tbcd) for shape in element.checks):
        return frozenset({ast.DataType.OCTET_STRING})
    if element.checks:
        # Bits of the payload's octets: an octet string's, or an unsigned
        # integer's, its first octet the most significant.
        return frozenset(
            {
                ast.DataType.OCTET_STRING,
                ast.DataType.UNSIGNED32,
                ast.DataType.UNSIGNED64,
            }
        )
    return None
