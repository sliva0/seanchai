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
import re
from typing import Annotated, Literal

import pydantic
from pydantic import Field

# AVP and message names as they appear in specs: "User-Data", "3GPP-Charging-Id".
# RFC 6733's name-fmt excludes "_", but TS 29.109 consistently publishes
# GBA_U-Awareness-Indicator in its heading, ABNF, table and defining prose.
# The source-fidelity AST must represent what a specification actually names.
# Enum value names are the same minus the leading-character restriction.
AvpName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
EnumValueName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]

# Free text the line-oriented format writes onto a single line, next to a
# directive keyword or after a `;`. Only what survives a round-trip is
# accepted: an embedded newline produces a file that does not parse back — and
# in a header value can inject another directive — while empty or
# space-padded text is written out as a line the parser then reads back
# differently, or rejects as trailing whitespace. `;;` is excluded for the
# same reason: it starts a trailing comment, so everything from it onward
# would be discarded on the way back in. (A validator rather than a lookahead
# in the pattern — pydantic's regex engine supports no lookaround.)


def _no_comment_start(value: str) -> str:
    if ";;" in value:
        raise ValueError("';;' starts a comment and cannot appear in a value")
    return value


InlineText = Annotated[
    str,
    Field(pattern=r"^\S([^\r\n]*\S)?$"),
    pydantic.AfterValidator(_no_comment_start),
]

# Single-token reference to a defining document: "TS29.336", "RFC7683".
SPEC_REF_PATTERN = r"^(TS\d{2}\.\d{3}|RFC\d+)$"
SpecRef = Annotated[str, Field(pattern=SPEC_REF_PATTERN)]

# Table label as printed in the spec, carried by `; Table:`: "6.3.1", "6.3/2".
# Not a `SectionNumber`: labels use "/" separators and suffixes freely, so only
# the shape the directive can round-trip is enforced.
TableLabel = InlineText

# Section numbers as printed in the spec: "6.3", "6.3.7A".
SectionNumber = Annotated[str, Field(pattern=r"^\d+(\.\d+[A-Z]*)*$")]

# A document's own version numbering: "18.6.0".
Version = Annotated[str, Field(pattern=r"^\d+(\.\d+)*$")]

# RFC 6733 §4.1: an AVP without the V bit belongs to the IETF, whose vendor-id
# is 0. `.dad` spells that as no vendor in a header rule, so the two spellings
# have to be reconciled before any identity is compared.
IETF_VENDOR = 0

Unsigned32 = Annotated[int, Field(ge=0, lt=2**32)]
Unsigned24 = Annotated[int, Field(ge=0, lt=2**24)]

# `; Page:` counts printed pages of the PDF rendering, from 1. Page 0 is not a
# small page number, it is an off-by-one in whatever produced it.
PageNumber = Annotated[int, Field(ge=1, lt=2**32)]


class Node(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class SourceRef(Node):
    """`; Section:` / `; Page:` directives — where a block sits in the source
    document. Pages are PDF page numbers of the ETSI rendering."""

    section: SectionNumber
    page: PageNumber | None = None


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

    @pydantic.model_validator(mode="after")
    def _ordered(self) -> AvpRule:
        if self.max_occurs is not None and self.max_occurs < self.min_occurs:
            raise ValueError(
                f"occurrence range {self.min_occurs}*{self.max_occurs} is inverted"
            )
        return self


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
    # None when the source document itself omits it (TS 29.272 VCSG commands
    # print "< Diameter Header: 8388638, REQ, PXY, >") — to be fixed by patches.
    application_id: Unsigned32 | None
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
    """`SomeName = 7` line of an enumerated AVP body, optionally annotated
    with the spec's one-line description: `Subscribe = 0 ; This value ...`."""

    name: EnumValueName
    value: Unsigned32
    description: InlineText | None = None


class ReservedValues(Node):
    """`; RESERVED = 20` / `; RESERVED = 34-99` directive: value(s) the spec
    reserves without defining. Distinct from merely-unassigned values —
    validators must reject dictionaries that assign them."""

    first: Unsigned32
    last: Unsigned32

    @pydantic.model_validator(mode="after")
    def _ordered(self) -> ReservedValues:
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
    """AVP header bits an AVP table's flag-rule columns can name.

    `P` is RFC 3588's "protected" bit. RFC 6733 deprecated it, but the
    specifications did not stop printing it — TS 29.061, 29.212, 29.214 and
    29.273 all write flags cells like `V, P` — and a file that records what its
    source document says has to be able to hold it.

    Declaration order is the canonical spelling order of a flags cell, so `P`
    goes last: putting it anywhere else would rewrite every committed file for
    no gain.
    """

    MANDATORY = "M"
    VENDOR = "V"
    PROTECTED = "P"


class DataType(enum.StrEnum):
    """The closed set of Diameter AVP data types: the basic formats of
    RFC 6733 §4.2 and the common derived formats of §4.3.1, spelled as the
    specifications print them.

    Closed rather than free text because the alternative silently accepts
    typos: TS 29.272 clause 7.3.83 gives `Alert-Reason` the type "Enumerate",
    which no reader would defend and nothing else would have caught. A source
    typo is what the input-patch layer is for.

    RFC 3588 additionally defined `QoSFilterRule`, which RFC 6733 dropped and
    no specification in the corpus uses; it is left out until one does.
    RFC 6733 §4.3 also lets an application define *new* derived formats, so a
    specification may eventually print a type that belongs here and is not a
    mistake. That case has not appeared yet, and it — not convenience — is what
    would justify opening this set.
    """

    # §4.2 basic formats.
    OCTET_STRING = "OctetString"
    INTEGER32 = "Integer32"
    INTEGER64 = "Integer64"
    UNSIGNED32 = "Unsigned32"
    UNSIGNED64 = "Unsigned64"
    FLOAT32 = "Float32"
    FLOAT64 = "Float64"
    GROUPED = "Grouped"

    # §4.3.1 common derived formats.
    ADDRESS = "Address"
    TIME = "Time"
    UTF8_STRING = "UTF8String"
    DIAMETER_IDENTITY = "DiameterIdentity"
    DIAMETER_URI = "DiameterURI"
    ENUMERATED = "Enumerated"
    IP_FILTER_RULE = "IPFilterRule"


class AvpFlagRules(Node):
    """The four "AVP Flag rules" columns of a spec AVP table."""

    must: frozenset[AvpFlag] = frozenset()
    may: frozenset[AvpFlag] = frozenset()
    should_not: frozenset[AvpFlag] = frozenset()
    must_not: frozenset[AvpFlag] = frozenset()

    @pydantic.model_validator(mode="after")
    def _disjoint(self) -> AvpFlagRules:
        """The four columns partition the flags: one flag cannot be both
        required and optional, and a table saying so is a source or extraction
        error rather than a state a consumer has to resolve."""
        columns = ("must", "may", "should_not", "must_not")
        seen: dict[AvpFlag, str] = {}
        for column in columns:
            for flag in getattr(self, column):
                if flag in seen:
                    raise ValueError(
                        f"AVP flag {flag.value!r} appears in both"
                        f" {seen[flag]} and {column}"
                    )
                seen[flag] = column
        return self


class AvpColumn(enum.StrEnum):
    """Columns of an AVP table that the format models, spelled as the
    `; Columns:` directive writes them."""

    NAME = "Name"
    CODE = "Code"
    SECTION = "Section"
    TYPE = "Type"
    MUST = "Must"
    MAY = "May"
    SHOULD_NOT = "S.not"
    MUST_NOT = "M.not"
    ENCRYPT = "Encrypt"


class ReusedColumn(enum.StrEnum):
    """Columns of a re-used AVPs table that the format models."""

    NAME = "Name"
    FROM = "From"
    M_BIT = "M-bit"


REUSED_COLUMNS: tuple[ReusedColumn, ...] = tuple(ReusedColumn)


def _check_columns(columns: tuple[AvpColumn | ReusedColumn, ...]) -> None:
    """`; Columns:` records which of the source table's columns the format
    models, in source order. Unmodelled source columns are dropped — why, and
    when one deserves modelling instead, is covered in
    docs/extractor.md#columns-the-format-does-not-model."""
    labels = [column.value for column in columns]
    if len(set(labels)) != len(labels):
        raise ValueError(f"duplicate column in {labels}")


class AvpTableRow(Node):
    """One row of an AVP table.

    Every modelled field is optional, because AVP tables do not all have the
    same columns — TS 29.273's has no Encrypt column at all, and RFC 6733 §4.5
    has neither MAY nor SHOULD NOT nor Encrypt. Which columns a table has is
    recorded once on `AvpTable.columns` rather than per row, and the two are
    checked against each other there.

    A field is None when its column is absent *or* when the column is present
    and the cell is empty: `code` is None both ways — TS 29.329's Load row
    defers its definition to another spec — and `section` likewise (TS 29.272's
    3GPP2-MEID is defined in a 3GPP2 document, so its clause cell is blank).
    Telling the two apart is what `columns` is for.
    """

    name: AvpName
    code: Unsigned32 | None = None
    section: SectionNumber | None = None
    data_type: DataType | None = None
    flag_rules: AvpFlagRules = AvpFlagRules()
    may_encrypt: bool | None = None


class AvpTable(Node):
    """`; Type: AVP Table` — mirrors the spec's own per-application AVP table
    (e.g. TS 29.329 table 6.3.1). `table` is the label from the `; Table:`
    directive, as printed in the spec ("6.3.1", "6.3/2").

    `columns` records the source table's columns in the source table's order,
    and is the file's own statement of its shape: an absent Encrypt column and
    an Encrypt column reading "No" are different claims, and before this
    existed they were the same `False`.
    """

    type: Literal["AVP Table"] = "AVP Table"
    # None when the source prints no label at all: RFC 6733 §4.5 introduces
    # its table with prose, not a "Table N" caption, so there is nothing for
    # `; Table:` to record.
    table: TableLabel | None = None
    source: SourceRef
    columns: Annotated[tuple[AvpColumn, ...], Field(min_length=1)]
    # A table section with no rows carries no information, and would mean the
    # extractor found a caption but lost its contents.
    rows: Annotated[tuple[AvpTableRow, ...], Field(min_length=1)]

    @pydantic.model_validator(mode="after")
    def _rows_match_columns(self) -> AvpTable:
        _check_columns(self.columns)
        if AvpColumn.NAME not in self.columns:
            raise ValueError("AVP table has no Name column")

        # A value under a column the table does not have is unattributable: it
        # cannot be written out, so it cannot survive a round-trip.
        absent = {
            AvpColumn.CODE: "code",
            AvpColumn.SECTION: "section",
            AvpColumn.TYPE: "data_type",
            AvpColumn.ENCRYPT: "may_encrypt",
        }
        flags = {
            AvpColumn.MUST: "must",
            AvpColumn.MAY: "may",
            AvpColumn.SHOULD_NOT: "should_not",
            AvpColumn.MUST_NOT: "must_not",
        }
        for row in self.rows:
            for column, field in absent.items():
                if column not in self.columns and getattr(row, field) is not None:
                    raise ValueError(
                        f"{row.name}: {field} set but the table has no"
                        f" {column.value} column"
                    )
            for column, field in flags.items():
                if column not in self.columns and getattr(row.flag_rules, field):
                    raise ValueError(
                        f"{row.name}: {field} flags set but the table has no"
                        f" {column.value} column"
                    )
        return self


class MBitOverride(enum.StrEnum):
    """M-bit column of a re-used AVPs table: local override of the defining
    spec's M-bit rule. Absence (None in the row) means the defining spec applies."""

    MUST = "MUST"
    MUST_NOT = "MUST-NOT"


class ReusedAvpRow(Node):
    name: AvpName
    origin: SpecRef
    # None when the table has no M-bit column (TS 29.128, 29.173, 29.336) or
    # when it has one and this row's cell is empty.
    m_bit: MBitOverride | None = None


class ReusedAvps(Node):
    """`; Type: Reused AVPs` — AVPs this spec takes from other specs/RFCs by
    name, mirroring 3GPP "re-used Diameter AVPs" tables. Names are unique
    within one specification's scope; resolving a row against the origin
    spec's `.dad` yields the AVP's (vendor-id, code).

    Like `AvpTable`, the table declares its own columns: these vary too, and
    by more. TS 29.128, 29.173 and 29.336 print no M-bit column; TS 29.172
    prints AVP Code and Value Type ones; TS 29.212 and 29.214 add the same
    per-specification columns their AVP tables carry.
    """

    type: Literal["Reused AVPs"] = "Reused AVPs"
    table: TableLabel
    source: SourceRef
    columns: Annotated[tuple[ReusedColumn, ...], Field(min_length=1)] = REUSED_COLUMNS
    rows: Annotated[tuple[ReusedAvpRow, ...], Field(min_length=1)]

    @pydantic.model_validator(mode="after")
    def _rows_match_columns(self) -> ReusedAvps:
        _check_columns(self.columns)
        for required in (ReusedColumn.NAME, ReusedColumn.FROM):
            if required not in self.columns:
                raise ValueError(f"re-used table has no {required.value} column")
        for row in self.rows:
            if ReusedColumn.M_BIT not in self.columns and row.m_bit is not None:
                raise ValueError(
                    f"{row.name}: m_bit set but the table has no M-bit column"
                )
        return self


Section = Annotated[
    Message | GroupedAvp | EnumeratedAvp | AvpTable | ReusedAvps,
    Field(discriminator="type"),
]


class SpecRefError(ValueError):
    """A specification title that names no supported document."""


SPEC_REF_RE = re.compile(SPEC_REF_PATTERN)


def spec_ref(specification: str) -> str:
    """The `SpecRef` form of a cover-page title: "3GPP TS 29.272" → "TS29.272".

    Per-spec side files — input patches, corrections — are named by it, so the
    rule lives here rather than in whichever loader needed it first. Because
    the result becomes a file name in a directory the user named, this
    validates rather than merely cleans up: only the canonical forms are
    accepted, so no title can produce a path separator, a `..` component or an
    absolute path.
    """
    reference = specification.removeprefix("3GPP ").replace(" ", "")
    if not SPEC_REF_RE.match(reference):
        raise SpecRefError(
            f"specification {specification!r} does not name a supported document"
            " (expected e.g. '3GPP TS 29.272' or 'RFC 6733')"
        )
    return reference


class Specification(Node):
    """One `.dad` file: the top-of-file directive header plus its sections."""

    specification: InlineText  # "3GPP TS 29.329"
    # None for a document that has no version axis: an RFC number names one
    # immutable document, so an RFC `.dad` carries no `; Version:` line rather
    # than a fabricated one.
    version: Version | None = None
    # `; Vendor-ID:` — the vendor-id this document's own AVPs are defined in.
    #
    # It has to be stated, because an AVP's identity is `(vendor-id, code)` and
    # nothing else in the file supplies the first half: AVP tables have no
    # vendor column, and a clause header omits the vendor both when the AVP
    # really is IETF-space and when the document forgot. TS 29.229 gives 621 to
    # `Primary-Charging-Collection-Function-Name` while RFC 7683 gives 621 to
    # `OC-Supported-Features`, and 29.229's table lists both.
    #
    # One value per document: a specification defines its AVPs in one vendor's
    # space. An AVP it merely re-uses belongs to the origin's space, which is
    # that document's `; Vendor-ID:` to state, not this one's to guess.
    vendor_id: Unsigned32
    link: pydantic.HttpUrl | None = None
    sections: tuple[Section, ...]
