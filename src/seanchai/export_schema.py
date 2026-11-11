"""The data contract of `seanchai export`, as frozen models.

The export is written from these models and described by the `schema.json`
it carries (`json_schema`). `SCHEMA_VERSION` changes when a reader would
have to. See docs/website.md.

A field with no default is always written, null when unstated. A field with
a default is omitted while it holds the default, which keeps mostly-empty
per-token and per-line fields out of large files.
"""

import json
from typing import Annotated, Any, Literal

import pydantic
from pydantic.json_schema import models_json_schema

from .dad import ast
from .linter import Severity

__all__ = [
    "GENERATOR",
    "SCHEMA_VERSION",
    "Allocation",
    "ApplicationIdentity",
    "AvpHeader",
    "AvpIdentity",
    "Block",
    "Citation",
    "Command",
    "CommandIdentity",
    "CommandSpan",
    "Correction",
    "CrossRelease",
    "Document",
    "DocumentSummary",
    "EnumEntry",
    "Finding",
    "FlagRules",
    "Hole",
    "Index",
    "Line",
    "Member",
    "Mention",
    "RawDocument",
    "RegistryIdentity",
    "Reservation",
    "Rule",
    "Search",
    "SearchEntry",
    "Section",
    "Source",
    "TableRow",
    "Target",
    "Token",
    "UndefinedBlock",
    "ValueIdentity",
    "ValueRow",
    "dumps",
    "json_schema",
]

SCHEMA_VERSION = 2

# What `index.json` says wrote it, and so what an export may replace.
GENERATOR: Literal["seanchai"] = "seanchai"

_Version = Annotated[int, pydantic.Field(ge=SCHEMA_VERSION, le=SCHEMA_VERSION)]


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class Target(_Model):
    """Where a link goes: a document's page, at a clause when `section` is set.
    `name` is the AVP a re-used row's origin cell links to there, or the value
    a result code's origin links to."""

    document: str
    section: str | None = None
    name: str | None = None


class Citation(_Model):
    """A place in the source document, for a link into it. `name` and `row` mark
    an AVP-table row's name, whose source is its table and not its definition."""

    section: str
    page: int | None = None
    name: str | None = None
    row: bool = False


class Section(_Model):
    """A clause of the file, for its table of contents. `title` is what the file
    places there: "Message User-Data-Request", "AVP Table", "Grouped AVP
    Server-Capabilities", or "AVP PCSCF-FQDN" for a clause only a table row names."""

    section: str
    page: int | None
    title: str


class Token(_Model):
    """A span of a file's text. Every token joined gives the file, byte for
    byte. Highlighting is the client's, from the editor grammar; `kind` marks
    only the `;;` comments, a note citing a declaration as `correction-note`."""

    text: str
    kind: Literal["comment", "correction-note"] | None = None
    target: Target | None = None
    source: Citation | None = None
    avp: str | None = None
    correction: str | None = None


class Line(_Model):
    """One line of a file. `anchor` is the clause this line is the link target
    of, `section` the clause it sits in, and `warning` marks a raw line the
    corrected file changes."""

    tokens: tuple[Token, ...]
    anchor: str | None = None
    section: str | None = None
    warning: bool = False


class Source(_Model):
    """The document a file was read from. `local` and `text` are paths in the
    export, the PDF of a self-hosted one and an RFC's text, null where absent."""

    kind: Literal["etsi-pdf", "rfc-text", "other"]
    url: str | None
    local: str | None
    text: str | None


class FlagRules(_Model):
    """AVP flag rules, as a table's columns place the flags. `application_defined`
    holds a bit RFC 6733 leaves to the application using the AVP."""

    must: tuple[ast.AvpFlag, ...]
    may: tuple[ast.AvpFlag, ...]
    should_not: tuple[ast.AvpFlag, ...]
    must_not: tuple[ast.AvpFlag, ...]
    application_defined: tuple[ast.AvpFlag, ...]


class CrossRelease(_Model):
    """A citation resolved outside the citing document's release, and the rule
    that allowed it (`corpus.CrossRelease`)."""

    citing: str
    cited: str
    version: str
    rule: str
    cited_revision: str | None
    revision: str | None
    meant: str | None


class UndefinedBlock(_Model):
    """The `Undefined AVP` block declaring a name no document defines."""

    section: str
    page: int | None
    note: str | None
    cited_in: tuple[str, ...]


class Hole(_Model):
    """A name the corpus cannot complete (`model.Hole`): the document that falls
    short, what it leaves unstated in `missing`, and what it does state.
    `recorded` is the reason the corpus's record of known holes gives."""

    name: str
    reference: str
    version: str | None
    missing: tuple[str, ...]
    vendor_id: int | None
    code: int | None
    data_type: ast.DataType | None
    flag_rules: FlagRules | None
    section: str | None
    origin: str | None
    conflict: str | None
    wireshark_name: str | None
    across_releases: CrossRelease | None
    undefined: UndefinedBlock | None
    recorded: str | None


class Finding(_Model):
    """A linter finding on the file. `accepted_by` cites the acceptance, whose
    reason is in the document's `corrections`."""

    severity: Severity
    rule: str
    message: str
    section: str | None
    origin: str | None
    accepted_by: str | None


class Correction(_Model):
    """A declaration the file cites, by its reason."""

    kind: Literal["correction", "delete", "insert", "supply", "accept"]
    reason: str


class Member(_Model):
    """A member of a rule, at its `line`. `qualifier` is as printed (`1*`,
    `*2`, or empty); `min` and `max` are RFC 6733 clause 3.2's bounds, `max`
    null for none. A `strikethrough` member is one the document prints struck
    through and the rule keeps. A `struck` member is a commented-out line keeping its `;
    strikethrough`, as the document strikes it, and no member of the rule the
    corpus reads."""

    name: str
    presence: ast.Presence
    qualifier: str = ""
    min: int
    max: int | None
    bold: bool = False
    strikethrough: bool = False
    struck: bool = False
    line: int


class Rule(_Model):
    """A block's ABNF rule: the name its `::=` line at `line` defines
    (`answer-message` for an Answer Message block) and its members in file
    order, struck ones included."""

    name: str
    line: int
    members: tuple[Member, ...]


class AvpHeader(_Model):
    """What an AVP's `< AVP header: code vendor-id >` says; `vendor_id` is
    null where it prints none."""

    code: int
    vendor_id: int | None


class Command(_Model):
    """A Message block's header. `flags` in printed order; `application_id`
    is the effective id, the header's or for a bare header the one the first
    Application Scope block covering its clause states (`scope`, that block's
    clause). `application` names the application, and `stated_in` is the
    clause of the scope block naming it, as `CommandIdentity` reads them."""

    code: int
    request: bool
    flags: tuple[ast.CommandFlag, ...]
    header_application_id: int | None
    application_id: int | None
    application: str | None = None
    stated_in: str | None = None
    scope: str | None = None


class CommandSpan(_Model):
    """Characters `start` to `end` of line `line` name a command: a Message
    block's name, abbreviation or rule head, a half of a Command Codes row's
    name or abbreviation, or a table's column for it. `block` indexes the
    document's Message block for it; a registry half has none."""

    line: int
    start: int
    end: int
    code: int
    request: bool
    name: str
    abbreviation: str | None = None
    block: int | None = None


class TableRow(_Model):
    """A row of an AVP Table or Reused AVPs block at `line`. `cells` are as
    printed, one per column, quotes kept: `""` is a blank cell, `-` a dash.
    The rest is what needs more than a cell to read: `name` unquoted, `vendor`
    the vendor space the row places the AVP in (its Vendor-ID cell, else its V
    flag read with the file's `; Vendor-ID:`), and `marks` each mark column's
    marks, unquoted, with no marks for a dash and no entry for a blank cell."""

    line: int
    name: str
    cells: tuple[str, ...]
    vendor: int | None = None
    marks: dict[ast.MarkColumn, tuple[str, ...]] = pydantic.Field(default_factory=dict)


class Allocation(_Model):
    """A row of a Registry block at `line`, `cells` as a `TableRow`'s. `code`
    is null where the row prints a placeholder; `name` and `abbreviation` are
    unquoted, null for a dash. `documents` are the exported documents its
    Defined-In cell resolves to; `vendor` is an AVP Codes row's, the file's
    `; Vendor-ID:`."""

    line: int
    cells: tuple[str, ...]
    code: int | None
    name: str | None = None
    abbreviation: str | None = None
    documents: tuple[str, ...] = ()
    vendor: int | None = None


class Reservation(_Model):
    """A registry's `; RESERVED first..last` line at `line`."""

    line: int
    first: int
    last: int
    defined_in: tuple[str, ...] = ()
    purpose: str | None = None


class ValueRow(_Model):
    """A Value Table row at `line`. `section` is a result code's own clause,
    `mark` a feature's M/O, `origin` the document a result code's row says
    defines it, and `origin_target` where its token links."""

    line: int
    name: str
    value: int
    section: str | None = None
    mark: str | None = None
    origin: str | None = None
    origin_target: Target | None = None


class EnumEntry(_Model):
    """A line of an Enumerated AVP's body at `line`: a `value` with its
    `name`, or a `reserved`, `void` or `vendor-specific` range `first` to
    `last`. `description` is what the line says of it."""

    line: int
    kind: Literal["value", "reserved", "void", "vendor-specific"]
    name: str | None = None
    first: int
    last: int
    description: str | None = None


class Block(_Model):
    """A `; Type:` block of a file: lines `line` (its `; Type:` line) to
    `last`, comments included. `fields` holds its other directives as printed,
    `Name` to `Applies-To`; `name` and `abbreviation` are what its `; Name:`
    or `; AVP:` names. What else it holds depends on `type`:

    - `rule` for a Message, Answer Message, Grouped AVP or Reprinted AVP, with
      `command` for a Message and `avp` for a Grouped or Reprinted AVP;
    - `avp` and `values` for an Enumerated AVP;
    - `columns` and `rows` for an AVP Table or Reused AVPs block;
    - `columns`, `allocations` and `reservations` for a Registry;
    - `value_rows` for a Value Table.

    `commands` marks where its lines name a command.
    """

    type: str
    line: int
    last: int
    section: str
    page: int | None
    fields: dict[str, str]
    name: str | None = None
    abbreviation: str | None = None
    rule: Rule | None = None
    command: Command | None = None
    avp: AvpHeader | None = None
    values: tuple[EnumEntry, ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[TableRow, ...] = ()
    allocations: tuple[Allocation, ...] = ()
    reservations: tuple[Reservation, ...] = ()
    value_rows: tuple[ValueRow, ...] = ()
    commands: tuple[CommandSpan, ...] = ()


class DocumentSummary(_Model):
    """A document as the index lists it. `path` and `raw` are its files in the
    export; `raw` is null for a corpus with no raw mirror. `pinned` says why an
    older release is held. `interfaces` are the Diameter interfaces or
    reference points it specifies, or an RFC's application, from the corpus's
    `interfaces.toml`: empty for none, null where the corpus does not say."""

    id: str
    path: str
    raw: str | None
    reference: str
    specification: str
    version: str | None
    publisher: Literal["3GPP", "3GPP2", "ETSI", "IETF", "OMA", "oneM2M"]
    release: int | None
    title: str
    pinned: str | None
    interfaces: tuple[str, ...] | None
    source: Source


class Document(DocumentSummary):
    """`documents/<id>.json`: one corrected file, with what the page shows of
    it. `corrections` is keyed by citation, `TS29.272.py#area-scope-code`.
    `blocks` are its `; Type:` blocks in file order, by index into `lines`."""

    schema_version: _Version
    sections: tuple[Section, ...]
    lines: tuple[Line, ...]
    blocks: tuple[Block, ...]
    corrections: dict[str, Correction]
    holes: tuple[Hole, ...]
    findings: tuple[Finding, ...]


class RawDocument(_Model):
    """`documents/<id>.raw.json`: the raw mirror of a file, for the raw view,
    with its own `blocks`, by index into its own `lines`."""

    schema_version: _Version
    id: str
    lines: tuple[Line, ...]
    blocks: tuple[Block, ...]


class Index(_Model):
    """`index.json`: what the export is and which documents it holds. `generator`
    marks the directory as an export, which a later export may replace.
    `corpus_version` is null for a corpus other than the installed one."""

    schema_version: _Version
    generator: Literal["seanchai"]
    seanchai_version: str | None
    corpus_version: str | None
    mode: Literal["public", "self-hosted"]
    documents: tuple[DocumentSummary, ...]


class AvpIdentity(_Model):
    """An AVP's identity on the wire."""

    kind: Literal["avp"]
    vendor_id: int
    code: int


class CommandIdentity(_Model):
    """A command's identity. `application_id` is the effective one: the header's,
    or for a header printing none the one an Application Scope block covering
    its clause states, named in `application`. `header_application_id` is what
    the header prints, null for a bare one."""

    kind: Literal["command"]
    command_code: int
    application_id: int | None
    header_application_id: int | None
    application: str | None


class ApplicationIdentity(_Model):
    """An application a document names in an Application Scope block."""

    kind: Literal["application"]
    application_id: int


class RegistryIdentity(_Model):
    """A row of a registry table, by the code space it allocates in."""

    kind: Literal["registry"]
    registry: ast.RegistryKind
    code: int


class ValueIdentity(_Model):
    """A name a value table gives a number: `value_kind` says of which sort, and
    `avp` of which AVP; a feature's `application` and `feature_list_id` say which
    list, as the table's caption does."""

    kind: Literal["value"]
    value_kind: ast.ValueKind
    avp: str
    value: int
    application: str | None
    feature_list_id: int | None


class SearchEntry(_Model):
    """A name as one document means it. `target` is where the name is defined,
    null for a hole. `defined_in` is the documents defining it, several for a
    registry row. `abbreviation` is a command's or a registry row's own,
    `wireshark_name` Wireshark's name for an AVP."""

    name: str
    kind: Literal["avp", "command", "application", "registry", "value"]
    document: str
    target: Target | None
    identity: (
        AvpIdentity
        | CommandIdentity
        | ApplicationIdentity
        | RegistryIdentity
        | ValueIdentity
        | None
    )
    defined_in: tuple[str, ...]
    abbreviation: str | None
    wireshark_name: str | None
    data_type: ast.DataType | None
    across_releases: CrossRelease | None


class Mention(_Model):
    """A non-blank line of a corrected file, with the AVPs it names."""

    document: str
    section: str | None
    line: int
    text: str
    avps: tuple[str, ...]


class Search(_Model):
    """`search.json`: what only the search page needs."""

    schema_version: _Version
    entries: tuple[SearchEntry, ...]
    mentions: tuple[Mention, ...]


def dumps(model: pydantic.BaseModel) -> str:
    """Serialise a model as the export writes it: compact, keys sorted, one
    final newline."""
    return (
        json.dumps(
            model.model_dump(mode="json", exclude_defaults=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def json_schema() -> dict[str, Any]:
    """Return the JSON Schema in `schema.json`: one of the export's four
    file kinds, as `dumps` writes them."""
    roots = (Index, Search, Document, RawDocument)
    _, schema = models_json_schema(
        [(root, "validation") for root in roots], title="Seanchaí export"
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **schema,
        "oneOf": [{"$ref": f"#/$defs/{root.__name__}"} for root in roots],
    }
