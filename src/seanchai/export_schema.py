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
    "ApplicationIdentity",
    "AvpIdentity",
    "Citation",
    "CommandIdentity",
    "Correction",
    "CrossRelease",
    "Document",
    "DocumentSummary",
    "Finding",
    "FlagRules",
    "Hole",
    "Index",
    "Line",
    "Mention",
    "RawDocument",
    "RegistryIdentity",
    "Search",
    "SearchEntry",
    "Section",
    "Source",
    "Target",
    "Token",
    "UndefinedBlock",
    "ValueIdentity",
    "dumps",
    "json_schema",
]

SCHEMA_VERSION = 1

# What `index.json` says wrote it, and so what an export may replace.
GENERATOR: Literal["seanchai"] = "seanchai"

_Version = Annotated[int, pydantic.Field(ge=SCHEMA_VERSION, le=SCHEMA_VERSION)]


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


class Target(_Model):
    """Where a link goes: a document's page, at a clause when `section` is set.
    `name` is the AVP a re-used row's origin cell links to there."""

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


class DocumentSummary(_Model):
    """A document as the index lists it. `path` and `raw` are its files in the
    export; `raw` is null for a corpus with no raw mirror. `pinned` says why an
    older release is held."""

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
    source: Source


class Document(DocumentSummary):
    """`documents/<id>.json`: one corrected file, with what the page shows of
    it. `corrections` is keyed by citation, `TS29.272.py#area-scope-code`."""

    schema_version: _Version
    sections: tuple[Section, ...]
    lines: tuple[Line, ...]
    corrections: dict[str, Correction]
    holes: tuple[Hole, ...]
    findings: tuple[Finding, ...]


class RawDocument(_Model):
    """`documents/<id>.raw.json`: the raw mirror of a file, for the raw view."""

    schema_version: _Version
    id: str
    lines: tuple[Line, ...]


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
