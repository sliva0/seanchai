"""AST for the `.dad` specification format.

The tree mirrors the file structure: a `Specification` is a file-level header
followed by sections, each of which corresponds to one `; Type: X` block.
Everything the parser reads — including directive comments — is represented
here; `;;` free-text comments are not (`parser.parse_with_comments` returns
them beside the tree, keyed by `TreePath`, and the canonical formatter
regenerates cosmetic lines such as table column headers).

All nodes are frozen pydantic models: extractor output and hand patches are
exactly the kind of data worth validating eagerly, and `model_dump_json()`
gives downstream generator/validator scripts a serialized form for free.

Not-yet-final corners of the format are marked with `TODO(format)`.
"""

import enum
import re
from typing import Annotated, Any, Literal

import pydantic
from pydantic import Field

# AVP and message names as they appear in specs: "User-Data", "3GPP-Charging-Id".
# RFC 6733's name-fmt excludes "_", but TS 29.109 consistently publishes
# GBA_U-Awareness-Indicator in its heading, ABNF, table and defining prose.
# The source-fidelity AST must represent what a specification actually names.
AVP_NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]*"
AvpName = Annotated[str, Field(pattern=f"^{AVP_NAME_PATTERN}$")]

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

# Enum value names are free text: TS 32.299 labels its values in words ("0 PS
# to CS Transfer", clause 7.2.1B; "Virtual Private Network (VPN)", 7.2.213),
# and an identifier derived from the label would be a spelling no document
# prints. A file quotes any name that is not an `AvpName`, escaping `"` and
# `\` inside the quotes (RFC 4005 clause 7.3 labels a value `802 (includes
# all 802 media plus Ethernet "canonical format")`), so a name is whatever
# the quotes can hold: no `;;`, which starts a comment wherever it stands,
# and no control characters or padding, which the formatter could not print
# back as written.
EnumValueName = Annotated[
    str,
    Field(pattern=r"^[^\x00-\x20\x7f]([^\x00-\x1f\x7f]*[^\x00-\x20\x7f])?$"),
    pydantic.AfterValidator(_no_comment_start),
]

# Single-token reference to a defining document: "TS29.336", "RFC7683".
# A document outside 3GPP and IETF leads with its publisher and keeps the
# publisher's own numbering: ETSI's "ETSI-TS283.034" (29.212's TISPAN
# origin, dotted as a 3GPP number is), 3GPP2's "3GPP2-X.S0057", OMA's
# "OMA-DDS-Charging_Data", whose name already leads with it, and oneM2M's
# "oneM2M-TS-0004" (TS 32.299 tables 7.2.0.1 and 7.5.1).
EXTERNAL_REF_PATTERN = (
    r"ETSI-(?:TS|ES)\d{3}\.\d{3}|3GPP2-[A-Z]\.[A-Z]\d{4}"
    r"|OMA-[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*|oneM2M-TS-\d{4}"
)
SPEC_REF_PATTERN = rf"^(TS\d{{2}}\.\d{{3}}|RFC\d+|{EXTERNAL_REF_PATTERN})$"
SpecRef = Annotated[str, Field(pattern=SPEC_REF_PATTERN)]

# Table label as printed in the spec, carried by `; Table:`: "6.3.1", "6.3/2".
# Not a `SectionNumber`: labels use "/" separators and suffixes freely, so only
# the shape the directive can round-trip is enforced.
TableLabel = InlineText

# Section numbers as printed in the spec: "6.3", "6.3.7A".
# Components are digits with an optional letter suffix, either case: 3GPP
# numbers clauses "6.3.7A" (29.272), "5b.3.1" (29.212) and "20.5a.5" (29.061).
# An annex clause leads with the annex letter instead: "E.6.3.6" (29.212).
SectionNumber = Annotated[
    str, Field(pattern=r"^([A-Za-z]+|\d+[A-Za-z]*)(\.\d+[A-Za-z]*)*$")
]


def interface_clause(section: str) -> str:
    """The clause that scopes one interface's commands: `5a` of `5a.6.2`,
    `A.7` of `A.7.6.2`. A 3GPP document gives each interface a top-level
    clause (TS 29.212's 5, 5a, 5b, 5c) or annex clause (29.215's A.7 and
    A.8), and an annex letter alone spans several interfaces."""
    parts = section.split(".")
    return ".".join(parts[:2]) if parts[0].isalpha() else parts[0]


# A document's own version numbering: "18.6.0".
Version = Annotated[str, Field(pattern=r"^\d+(\.\d+)*$")]

# RFC 6733 §4.1: an AVP without the V bit belongs to the IETF, whose vendor-id
# is 0. `.dad` spells that as no vendor in a header rule, so the two spellings
# have to be reconciled before any identity is compared.
IETF_VENDOR = 0

# The base protocol every Diameter application builds on. Extractors stamp it
# into `; Bases:` for every document except RFC 6733 itself.
BASE_PROTOCOL = "RFC6733"

Unsigned32 = Annotated[int, Field(ge=0, lt=2**32)]
Unsigned24 = Annotated[int, Field(ge=0, lt=2**24)]

# `; Page:` counts printed pages of the PDF rendering, from 1. Page 0 is not a
# small page number, it is an off-by-one in whatever produced it.
PageNumber = Annotated[int, Field(ge=1, lt=2**32)]


class Node(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


# Where something sits in a `Specification`: the field names and tuple indices
# leading to it from the root — `()` is the specification itself,
# `("sections", 3)` its fourth section, `("sections", 3, "avps", 0)` that
# section's first AVP rule. Formatter notes and correction edits are keyed by
# it rather than by `id(node)`: a path means the same place in a copy, a
# rebuild or a re-parse of the tree, and an identity only lasts as long as
# the object does. An index one past a tuple's end names the position after
# its last item, where the note of a deleted last item stands.
type TreePath = tuple[str | int, ...]


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
    # `; strikethrough` — the source strikes the member through. TS 32.299's
    # legend (clauses 6.2.1.2, 6.4.1.2) says a struck AVP "is not used by
    # 3GPP", and there the extractor comments the line out instead; a struck
    # member that is still a member is one whose document gives the strike
    # no meaning the extractor reads.
    strikethrough: bool = False

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
    # print "< Diameter Header: 8388638, REQ, PXY, >"); an `ApplicationScope`
    # block records an id the document states elsewhere.
    application_id: Unsigned32 | None
    avps: tuple[AvpRule, ...]


# One `; Applies-To:` entry: a clause and every subclause under it, "5.*"
# for clause 5, 5.1 and 5.6.2. The wildcard is spelled out so that a bare
# clause number stays free to mean that clause alone, a form no document has
# needed yet.
ClauseWildcard = Annotated[
    str, Field(pattern=r"^([A-Za-z]+|\d+[A-Za-z]*)(\.\d+[A-Za-z]*)*\.\*$")
]


class ApplicationScope(Node):
    """`; Type: Application Scope` — an application id the document states
    outside its command headers, with the clause stating it and the clauses
    whose commands it applies to.

    TS 29.212 prints its Gx commands with bare `272, REQ, PXY` headers and
    says in clause 5.1 that "the Application-ID for the Gx Application in
    the present release is 16777238"; RFC 4006 assigns 4 in its IANA
    considerations. A command's own header, where it prints one, is still
    what that header says: this states the id for the commands whose
    headers print none.
    """

    type: Literal["Application Scope"] = "Application Scope"
    # The document's name for the application or interface: "Gx", "Diameter
    # Credit Control".
    name: InlineText
    source: SourceRef
    application_id: Unsigned32
    # The clauses whose commands belong to the application: "5.*" for TS
    # 29.212's Gx, "5.1.*" and "5.2.*" for RFC 5778's two applications, which
    # share a clause.
    applies_to: Annotated[tuple[ClauseWildcard, ...], Field(min_length=1)]

    @pydantic.model_validator(mode="after")
    def _distinct_clauses(self) -> ApplicationScope:
        if len(set(self.applies_to)) != len(self.applies_to):
            raise ValueError(f"applies_to {list(self.applies_to)} names a clause twice")
        return self

    def covers(self, section: str) -> bool:
        """Whether a command defined in clause `section` is in scope."""
        return any(
            section == clause or section.startswith(f"{clause}.")
            for clause in (entry.removesuffix(".*") for entry in self.applies_to)
        )


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
    # `; Values:` — where the clause says the values are defined, in its own
    # words, when that is somewhere else: TS 29.272 clause 7.3.67 gives
    # `Trace-Depth` "those defined in TS 32.422 [23] for Trace Depth", TS
    # 32.299 clause 7.2.238 takes `Type-Number`'s from "OMNA WSP Content Type
    # Numbers [210]". None when the clause names no other source. Values a
    # `Supply` correction fills in keep it, since the document still says it.
    values_source: InlineText | None = None
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

    RFC 3588 additionally defined `QoSFilterRule`, which RFC 4005 uses. RFC
    6733 later dropped it, but the historical source still needs to round-trip.
    RFC 6733 §4.3 also lets an application define *new* derived formats, so a
    specification may eventually print another type that belongs here and is
    not a mistake. That case has not appeared yet, and it — not convenience —
    is what would justify opening this set.
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
    QOS_FILTER_RULE = "QoSFilterRule"


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


class MarkColumn(enum.StrEnum):
    """Columns in which a table marks where its row applies, each cell a
    list of the document's marks. Both table kinds may carry them.

    What a mark means is the document's legend's to say, so the cells keep
    its spelling and the model and consumers interpret them per label:

    - `Acc-Type`: TS 29.212's and 29.215's "Acc. Type", the IP-CAN access
      types the AVP applies to (`All`, `3GPP-EPS`, `Non-3GPP-EPS`, ...).
    - `Applicability`: the supported features an AVP belongs to ("AVPs
      marked with a supported feature are applicable as described in clause
      5.4.1", TS 29.212 table 5.3.0.1 note 9; TS 29.468's `V2X Localized
      User Plane`), and in TS 29.212 and 29.215 also the function: `CC`
      charging control, `PC` policy control, `Both`, `ADC`, `ABC` (note 3).
    - `Reference-Points`: TS 29.061's "Applicable Reference Points" (`Gi`,
      `Sgi`).
    - `ACR`, `ACA`, `CCR`, `CCA`: TS 32.299's "Used in" columns, one per
      command: `M`, `OM` or `OC` (table 7.1.0.1, clause 7.1.0) or `X`
      (tables 7.2.0.1 and 7.3.1-7.5.1) where the AVP is used in it, a dash
      where it is not.
    """

    ACCESS_TYPES = "Acc-Type"
    APPLICABILITY = "Applicability"
    REFERENCE_POINTS = "Reference-Points"
    ACR = "ACR"
    ACA = "ACA"
    CCR = "CCR"
    CCA = "CCA"


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
    ACCESS_TYPES = MarkColumn.ACCESS_TYPES.value
    APPLICABILITY = MarkColumn.APPLICABILITY.value
    REFERENCE_POINTS = MarkColumn.REFERENCE_POINTS.value
    ACR = MarkColumn.ACR.value
    ACA = MarkColumn.ACA.value
    CCR = MarkColumn.CCR.value
    CCA = MarkColumn.CCA.value


class ReusedColumn(enum.StrEnum):
    """Columns of a re-used AVPs table that the format models."""

    NAME = "Name"
    FROM = "From"
    M_BIT = "M-bit"
    # TS 29.172 table 7.4.1-2 and TS 32.299's tables 7.3.1-7.5.1 print the
    # code, 29.172 the type too, of the AVPs they re-use.
    CODE = "Code"
    TYPE = "Type"
    ACCESS_TYPES = MarkColumn.ACCESS_TYPES.value
    APPLICABILITY = MarkColumn.APPLICABILITY.value
    REFERENCE_POINTS = MarkColumn.REFERENCE_POINTS.value
    ACR = MarkColumn.ACR.value
    ACA = MarkColumn.ACA.value
    CCR = MarkColumn.CCR.value
    CCA = MarkColumn.CCA.value


REUSED_COLUMNS: tuple[ReusedColumn, ...] = (
    ReusedColumn.NAME,
    ReusedColumn.FROM,
    ReusedColumn.M_BIT,
)


def mark_column(column: AvpColumn | ReusedColumn) -> MarkColumn | None:
    """The `MarkColumn` a table column is, or None for any other column."""
    return MarkColumn(column.value) if column.value in MarkColumn else None


def _check_columns(columns: tuple[AvpColumn | ReusedColumn, ...]) -> None:
    """`; Columns:` records which of the source table's columns the format
    models, in source order. Unmodelled source columns are dropped — why, and
    when one deserves modelling instead, is covered in
    docs/extractor.md."""
    labels = [column.value for column in columns]
    if len(set(labels)) != len(labels):
        raise ValueError(f"duplicate column in {labels}")


# One mark in a `MarkColumn` cell, as the document prints it: `Rel8`,
# `3GPP-EPS`, `OC`, and with what the document prints beside it, `All (NOTE
# 5)` (TS 29.212, whose note 5 excludes 3GPP-GPRS) or `V2X Localized User
# Plane` (TS 29.468). A file quotes a mark that is not a plain token, as it
# does an enum value name, so a mark may hold what an enum value name may.
# A lone `-` is not one: it is the dash a cell prints in place of a mark.
def _not_the_dash(value: str) -> str:
    if value == "-":
        raise ValueError("'-' is a cell's printed dash, not a mark")
    return value


Mark = Annotated[EnumValueName, pydantic.AfterValidator(_not_the_dash)]

# A row's marks per mark column its table prints, three ways: marks; `()`
# where the cell prints a dash, which TS 32.299 clause 7.1.0 gives a meaning
# ("Those Diameter AVPs that are not used are marked '-'"); and no entry
# where the cell is blank. `columns` tells a blank cell from an absent
# column.
Marks = dict[MarkColumn, tuple[Mark, ...]]


def _check_marks(
    name: str, marks: Marks, columns: tuple[AvpColumn | ReusedColumn, ...]
) -> None:
    declared = {mark_column(column) for column in columns}
    for column in marks:
        if column not in declared:
            raise ValueError(
                f"{name}: {column.value} marks set but the table has no"
                f" {column.value} column"
            )


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
    # Per mark column (`MarkColumn`), what the row marks: TS 29.212's
    # `Acc-Type` and `Applicability`, TS 32.299's per-command use.
    marks: Marks = Field(default_factory=dict)

    def stated_vendor(self, file_vendor: int) -> int | None:
        """The vendor space the row's V flag places the AVP in, or None
        where the row leaves it to the file.

        A row prints no vendor-id; its V flag is the one cell that says
        whether the AVP carries one. Forbidding it is IETF space: TS
        29.229's `Digest-QoP` row (clause 6.3.40) prints V under Must-not
        in vendor 10415's table, and is RFC 4590's code 110 in vendor 0.
        Requiring it is the file's own `; Vendor-ID:`. A row with V in
        neither column, or no flag cells at all, states neither.
        """
        if AvpFlag.VENDOR in self.flag_rules.must_not:
            return IETF_VENDOR
        if AvpFlag.VENDOR in self.flag_rules.must:
            return file_vendor
        return None


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
            _check_marks(row.name, row.marks, self.columns)
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
    # What the citing table says of the AVP's code and type, where it prints
    # them; the origin defines both, and the linter compares the two.
    code: Unsigned32 | None = None
    data_type: DataType | None = None
    marks: Marks = Field(default_factory=dict)


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
        absent = {
            ReusedColumn.M_BIT: "m_bit",
            ReusedColumn.CODE: "code",
            ReusedColumn.TYPE: "data_type",
        }
        for row in self.rows:
            for column, field in absent.items():
                if column not in self.columns and getattr(row, field) is not None:
                    raise ValueError(
                        f"{row.name}: {field} set but the table has no"
                        f" {column.value} column"
                    )
            _check_marks(row.name, row.marks, self.columns)
        return self


class RegistryKind(enum.StrEnum):
    """The code space a registry table allocates, as `; Registry:` writes it.

    TS 29.230 allocates four: application ids (table 4.1), command codes
    (5.1/1-5.1/4), the 3GPP vendor's AVP codes (7.1) and its experimental
    result codes (8.1.2-8.1.4)."""

    APPLICATION_IDS = "Application IDs"
    COMMAND_CODES = "Command Codes"
    AVP_CODES = "AVP Codes"
    RESULT_CODES = "Result Codes"


class RegistryColumn(enum.StrEnum):
    """Columns of a registry table that the format models."""

    CODE = "Code"
    NAME = "Name"
    # TS 29.230's command tables print "UAR/UAA" beside the command's name.
    ABBREVIATION = "Abbreviation"
    TYPE = "Type"
    # "Specified in 3GPP TS": the documents the row cites as defining it.
    DEFINED_IN = "Defined-In"


# A registry cell's text, quoted where it is not a plain token, as a mark
# is: TS 29.230 names applications "3GPP Cx/Px" and result codes "Deprecated
# value", and prints `Visited PLMN Id` in its AVP table.
RegistryText = Mark


class RegistryRow(Node):
    """One allocation: a code and what the registry says it is.

    Every field but the code is None, or empty, where the cell is blank: TS
    29.230 table 5.1/2 allocates command code 313 to nothing yet ("allocated
    to 3GPP, but they have not been used yet"), and table 7.1's TS 29.273
    rows 1530-1542 print no document."""

    code: Unsigned32
    # "User-Authorization-Request/-Answer", "3GPP Gx", as printed.
    name: RegistryText | None = None
    abbreviation: RegistryText | None = None
    # Informational: the registry's own statement of the AVP's type.
    data_type: DataType | None = None
    # A Type cell naming no Diameter type, as printed: TS 29.230 table 7.1
    # types 314 "Integer". Kept apart from `data_type`, whose set stays
    # closed, so the statement survives without becoming a type.
    printed_type: RegistryText | None = None
    # The documents the row cites. Usually one; TS 29.230 table 4.1 gives
    # Cx "29.228 [1] and 29.229 [2]", and table 7.1 gives codes 500-581
    # "29.209 [8], 29.211 [17], 29.214 [18]".
    defined_in: tuple[SpecRef, ...] = ()

    @pydantic.model_validator(mode="after")
    def _one_type(self) -> RegistryRow:
        if self.printed_type is not None and (
            self.data_type is not None or self.printed_type in DataType
        ):
            raise ValueError(
                f"code {self.code}: printed_type {self.printed_type!r} is for a"
                " Type cell naming no Diameter type"
            )
        return self


class RegistryReservation(Node):
    """`; RESERVED 320..399 TS29.234 "TS 29.234"`: a range the registry
    reserves without allocating, with the documents it names and what the
    range is reserved for, in the document's words.

    TS 29.230 states them as notes: "The AVP codes from 320 to 399 are
    reserved for TS 29.234", "... from 256 to 299 are reserved for future
    use", "... from 1 to 255 are reserved for backwards compatibility with
    3GPP RADIUS Vendor Specific Attributes (See 3GPP TS 29.061 [13], ...)".
    `defined_in` is every document the purpose names, so it is empty for
    "future use"."""

    first: Unsigned32
    last: Unsigned32
    defined_in: tuple[SpecRef, ...] = ()
    purpose: RegistryText | None = None

    @pydantic.model_validator(mode="after")
    def _ordered(self) -> RegistryReservation:
        if self.last < self.first:
            raise ValueError(f"reserved range {self.first}..{self.last} is inverted")
        return self

    def covers(self, code: int) -> bool:
        return self.first <= code <= self.last


class Registry(Node):
    """`; Type: Registry` — a table allocating codes to the documents that
    define them, rather than defining anything itself: TS 29.230's
    application ids, command codes, AVP codes and result codes.

    Rows and reservations keep the table's order, which TS 29.230 does not
    keep numeric (table 5.1/4 lists 8388731 among the 8388637s, table 7.1
    reserves 4703-4799 for TS 29.389 inside 4605-4799 for TS 29.388)."""

    type: Literal["Registry"] = "Registry"
    registry: RegistryKind
    table: TableLabel
    source: SourceRef
    columns: Annotated[tuple[RegistryColumn, ...], Field(min_length=1)]
    rows: Annotated[tuple[RegistryRow | RegistryReservation, ...], Field(min_length=1)]

    @pydantic.model_validator(mode="after")
    def _rows_match_columns(self) -> Registry:
        labels = [column.value for column in self.columns]
        if len(set(labels)) != len(labels):
            raise ValueError(f"duplicate column in {labels}")
        if RegistryColumn.CODE not in self.columns:
            raise ValueError("registry has no Code column")
        absent = {
            RegistryColumn.NAME: "name",
            RegistryColumn.ABBREVIATION: "abbreviation",
            RegistryColumn.TYPE: "data_type",
            RegistryColumn.DEFINED_IN: "defined_in",
        }
        if RegistryColumn.TYPE not in self.columns and any(
            isinstance(row, RegistryRow) and row.printed_type is not None
            for row in self.rows
        ):
            raise ValueError("printed_type set but the table has no Type column")
        for row in self.rows:
            if not isinstance(row, RegistryRow):
                continue
            for column, field in absent.items():
                if column not in self.columns and getattr(row, field):
                    raise ValueError(
                        f"code {row.code}: {field} set but the table has no"
                        f" {column.value} column"
                    )
        return self

    def allocations(self, code: int) -> list[RegistryRow]:
        """The rows allocating `code`; TS 29.230 table 7.1 prints 318 twice."""
        return [
            row
            for row in self.rows
            if isinstance(row, RegistryRow) and row.code == code
        ]

    def reservations(self, code: int) -> list[RegistryReservation]:
        """The reservations covering `code`."""
        return [
            row
            for row in self.rows
            if isinstance(row, RegistryReservation) and row.covers(code)
        ]


def node_at(root: Node, path: TreePath) -> Any:
    """What `path` names under `root`: a node, or a field's value."""
    found: Any = root
    for step in path:
        found = found[step] if isinstance(step, int) else getattr(found, step)
    return found


Section = Annotated[
    ApplicationScope
    | Message
    | GroupedAvp
    | EnumeratedAvp
    | AvpTable
    | ReusedAvps
    | Registry,
    Field(discriminator="type"),
]


class SpecRefError(ValueError):
    """A specification title that names no supported document."""


SPEC_REF_RE = re.compile(SPEC_REF_PATTERN)
EXTERNAL_REF_RE = re.compile(rf"^(?:{EXTERNAL_REF_PATTERN})$")

# A title naming a document outside 3GPP and IETF, as the publisher prints
# it ("ETSI TS 283 034", "3GPP2 X.S0057", "oneM2M TS-0004"); OMA's names
# carry no spaces and need no rule.
_EXTERNAL_TITLE_RE = re.compile(
    r"^(?:ETSI (?P<etsi>TS|ES) (?P<series>\d{3}) (?P<number>\d{3})"
    r"|(?P<publisher>3GPP2|oneM2M) (?P<document>\S+))$"
)


def is_external(reference: str) -> bool:
    """Whether a `SpecRef` names a document outside 3GPP and IETF, which no
    extractor reads and the corpus holds only if someone writes it by hand."""
    return EXTERNAL_REF_RE.match(reference) is not None


def spec_ref(specification: str) -> str:
    """The `SpecRef` form of a cover-page title: "3GPP TS 29.272" → "TS29.272",
    "ETSI TS 283 034" → "ETSI-TS283.034".

    Per-spec side files — input patches, corrections — are named by it, so the
    rule lives here rather than in whichever loader needed it first. Because
    the result becomes a file name in a directory the user named, this
    validates rather than merely cleans up: only the canonical forms are
    accepted, so no title can produce a path separator, a `..` component or an
    absolute path.
    """
    if match := _EXTERNAL_TITLE_RE.match(specification):
        reference = (
            f"ETSI-{match['etsi']}{match['series']}.{match['number']}"
            if match["etsi"]
            else f"{match['publisher']}-{match['document']}"
        )
    else:
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
    # `; Bases:` — the documents this one builds on without citing them
    # anywhere: RFC 6733's base-protocol AVPs (`Session-Id`, `Origin-Host`,
    # the trailing `* [ AVP ]`) appear in every Diameter application's ABNF
    # and in no re-used table, because every application is assumed to have
    # them. Extractors stamp `RFC6733` for every document except RFC 6733
    # itself, which is why the directive is optional: the base of the tree
    # has nothing to put in it. Spelled as `SpecRef`s, the same form re-used
    # rows cite origins by, so resolution shares their machinery.
    bases: tuple[SpecRef, ...] = ()
    link: pydantic.HttpUrl | None = None
    sections: tuple[Section, ...]
