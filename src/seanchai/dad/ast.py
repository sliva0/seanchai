"""AST for the `.dad` specification format.

The tree mirrors the file structure: a `Specification` is a file-level header
followed by sections, each of which corresponds to one `; Type: X` block.
Everything the parser reads — including directive comments — is represented
here; `;;` free-text comments are not (the parser discards them, and the
canonical formatter regenerates cosmetic lines such as table column headers).

All nodes are frozen pydantic models: extractor output and hand patches are
exactly the kind of data worth validating eagerly, and `model_dump_json()`
gives downstream generator/validator scripts a serialized form for free.

Not-yet-final corners of the format are marked with `TODO(format)`.
"""

import enum
from typing import Annotated, Literal, Union

import pydantic
from pydantic import Field

# AVP and message names as they appear in specs: "User-Data", "3GPP-Charging-Id".
# Enum value names are the same minus the leading-character restriction.
AvpName = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9-]*$")]
EnumValueName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")]

# Single-token reference to a defining document: "TS29.336", "RFC7683".
SpecRef = Annotated[str, Field(pattern=r"^(TS\d{2}\.\d{3}|RFC\d+)$")]

# Section numbers as printed in the spec: "6.3", "6.3.7A".
SectionNumber = Annotated[str, Field(pattern=r"^\d+(\.\d+[A-Z]*)*$")]

Unsigned32 = Annotated[int, Field(ge=0, lt=2**32)]
Unsigned24 = Annotated[int, Field(ge=0, lt=2**24)]


class Node(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class SourceRef(Node):
    """`; Section:` / `; Page:` directives — where a block sits in the source
    document. Pages are PDF page numbers of the ETSI rendering."""

    section: SectionNumber
    page: Unsigned32 | None = None


class Presence(enum.StrEnum):
    """ABNF bracket around an AVP reference inside a message/grouped rule."""

    FIXED = "fixed"  # < Session-Id > — required, fixed position
    REQUIRED = "required"  # { Origin-Host }
    OPTIONAL = "optional"  # [ Destination-Host ]


class AvpRule(Node):
    """One line of a message or grouped-AVP body: `* [ Supported-Features ] ; bold`."""

    name: AvpName
    presence: Presence
    # ABNF repetition qualifier `min*max`; bare `*` is (0, None), absent is
    # exactly-once, which is stored as (1, 1) so consumers need no special case.
    min_occurs: Unsigned32 = 1
    max_occurs: Unsigned32 | None = 1
    # `; bold` — bold in 3GPP ABNF marks AVPs defined/modified in this spec.
    bold: bool = False


class CommandFlag(enum.StrEnum):
    REQUEST = "REQ"
    PROXIABLE = "PXY"
    ERROR = "ERR"


class Message(Node):
    """`; Type: Message` — a command-code ABNF rule.

    `< Diameter Header: 306, REQ, PXY, 16777217 >` carries the command code,
    command flags and application id; `; Name:` carries the long name and the
    abbreviation ("User-Data-Request, UDR").
    """

    type: Literal["Message"] = "Message"
    name: AvpName
    abbreviation: Annotated[str, Field(pattern=r"^[A-Z]{2,5}$")]
    source: SourceRef
    command_code: Unsigned24
    flags: frozenset[CommandFlag]
    application_id: Unsigned32
    avps: tuple[AvpRule, ...]


class GroupedAvp(Node):
    """`; Type: Grouped AVP` — `Name ::= < AVP header: code vendor-id >` plus body."""

    type: Literal["Grouped AVP"] = "Grouped AVP"
    name: AvpName
    source: SourceRef
    code: Unsigned32
    vendor_id: Unsigned32 | None = None
    avps: tuple[AvpRule, ...]


class EnumValue(Node):
    """`SomeName = 7` line of an enumerated AVP body."""

    name: EnumValueName
    value: Unsigned32


class ReservedValues(Node):
    """`; RESERVED = 20` / `; RESERVED = 34-99` directive: value(s) the spec
    reserves without defining. Distinct from merely-unassigned values —
    validators must reject dictionaries that assign them."""

    first: Unsigned32
    last: Unsigned32

    @pydantic.model_validator(mode="after")
    def _ordered(self) -> "ReservedValues":
        if self.last < self.first:
            raise ValueError(f"reserved range {self.first}-{self.last} is inverted")
        return self


class EnumeratedAvp(Node):
    """`; Type: Enumerated AVP` — header rule plus value list in source order."""

    type: Literal["Enumerated AVP"] = "Enumerated AVP"
    name: AvpName
    source: SourceRef
    code: Unsigned32
    vendor_id: Unsigned32 | None = None
    values: tuple[EnumValue | ReservedValues, ...]


class AvpFlag(enum.StrEnum):
    MANDATORY = "M"
    VENDOR = "V"


class AvpFlagRules(Node):
    """The four "AVP Flag rules" columns of a spec AVP table."""

    must: frozenset[AvpFlag] = frozenset()
    may: frozenset[AvpFlag] = frozenset()
    should_not: frozenset[AvpFlag] = frozenset()
    must_not: frozenset[AvpFlag] = frozenset()


class AvpTableRow(Node):
    """One row of an AVP table. `code` is None when the source table itself
    omits it (AVPs whose definition is deferred to another spec, e.g. Load in
    TS 29.329 table 6.3.1 — resolved via the Reused AVPs section)."""

    name: AvpName
    code: Unsigned32 | None
    section: SectionNumber
    # Base data type name as printed ("OctetString", "Time", "Grouped").
    # TODO(format): restrict to the closed set of Diameter base/derived types.
    data_type: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9]*$")]
    flag_rules: AvpFlagRules
    may_encrypt: bool


class AvpTable(Node):
    """`; Type: AVP Table` — mirrors the spec's own per-application AVP table
    (e.g. TS 29.329 table 6.3.1). `table` is the label from the `; Table:`
    directive, as printed in the spec ("6.3.1", "6.3/2")."""

    type: Literal["AVP Table"] = "AVP Table"
    table: str
    source: SourceRef
    rows: tuple[AvpTableRow, ...]


class MBitOverride(enum.StrEnum):
    """M-bit column of a re-used AVPs table: local override of the defining
    spec's M-bit rule. Absence (None in the row) means the defining spec applies."""

    MUST = "MUST"
    MUST_NOT = "MUST-NOT"


class ReusedAvpRow(Node):
    name: AvpName
    origin: SpecRef
    m_bit: MBitOverride | None = None


class ReusedAvps(Node):
    """`; Type: Reused AVPs` — AVPs this spec takes from other specs/RFCs by
    name, mirroring 3GPP "re-used Diameter AVPs" tables. Names are unique
    within one specification's scope; resolving a row against the origin
    spec's `.dad` yields the AVP's (vendor-id, code)."""

    type: Literal["Reused AVPs"] = "Reused AVPs"
    table: str
    source: SourceRef
    rows: tuple[ReusedAvpRow, ...]


Section = Annotated[
    Union[Message, GroupedAvp, EnumeratedAvp, AvpTable, ReusedAvps],
    Field(discriminator="type"),
]


class Specification(Node):
    """One `.dad` file: the top-of-file directive header plus its sections."""

    specification: str  # "3GPP TS 29.329"
    version: Annotated[str, Field(pattern=r"^\d+(\.\d+)*$")]
    link: pydantic.HttpUrl | None = None
    sections: tuple[Section, ...]
