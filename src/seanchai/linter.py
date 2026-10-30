"""Structural rules over one parsed `.dad` file.

The extractor records what a specification says, including where it
contradicts itself; this is the layer that reports those contradictions
instead of resolving them. Every rule here is decided inside a single file,
and nearly every one has a real case in the committed corpus — they are not
hypothetical invariants, they are the inconsistencies three specifications
actually contain. The exceptions are the two application-scope rules, which
report what `model.Model.applications` would otherwise settle without
comment.

Findings carry a severity because not every one of them is a defect:

- `ERROR` — the file asserts two things that cannot both be true, whoever is
  at fault. Two AVPs with one identity; a table row disagreeing with the
  definition it points at.
- `NOTE` — something worth knowing that a single file cannot judge. An AVP
  both defined locally and listed as re-used is the case that forced the
  distinction: a specification may re-print another's AVP for convenience or
  *extend* it with new fields, and deciding which needs the origin document.

An AVP's identity is `(vendor-id, code)`, and the vendor half comes from the
file's own `; Vendor-ID:` directive; re-used rows belong to their origins'
vendor spaces, which the single-file rules therefore leave to the cross-file
ones — see `_duplicate_identities`.

Findings are anchored by clause and name rather than by line number. The AST
carries no line information, and a clause reference survives reformatting and
points at the same place in the specification as in the `.dad` file — which is
where the reader has to go anyway.
"""

from __future__ import annotations

import enum
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from . import corpus
from .dad import ast, formatter


@dataclass(frozen=True)
class AvpIdentity:
    """What actually distinguishes one AVP from another."""

    vendor_id: int
    code: int

    def __str__(self) -> str:
        return f"vendor {self.vendor_id}, code {self.code}"


class Severity(enum.StrEnum):
    ERROR = "error"
    NOTE = "note"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    rule: str
    message: str
    # Clause the finding sits in, when it belongs to one place. A finding about
    # two clauses disagreeing names both in `message` instead.
    section: str | None = None
    # The origin document a finding is about, for the rules that have one —
    # carried structurally so `lint_with_corpus` can decide what a resolved
    # origin supersedes without parsing it back out of `message`.
    origin: str | None = None

    def __str__(self) -> str:
        where = f" (clause {self.section})" if self.section else ""
        return f"{self.severity.value}: [{self.rule}] {self.message}{where}"


@dataclass
class _Index:
    """The one pass over the file that every rule reads from."""

    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp] = field(default_factory=list)
    messages: list[ast.Message] = field(default_factory=list)
    applications: list[ast.ApplicationScope] = field(default_factory=list)
    tables: list[ast.AvpTable] = field(default_factory=list)
    reused: dict[str, str] = field(default_factory=dict)  # AVP name -> origin
    # Names a re-used table cites from this file itself. TS 29.212's Gxx, S9,
    # Sd and St tables list Gx's AVPs "from" TS 29.212: those are this file's
    # own definitions, so no rule treats them as belonging elsewhere.
    self_cited: list[str] = field(default_factory=list)

    @property
    def rows(self) -> list[ast.AvpTableRow]:
        return [row for table in self.tables for row in table.rows]


def _index(spec: ast.Specification) -> _Index:
    index = _Index()
    try:
        own = ast.spec_ref(spec.specification)
    except ast.SpecRefError:
        # A hand-authored file may name a document no From cell can cite.
        own = None
    for section in spec.sections:
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
            index.definitions.append(section)
        elif isinstance(section, ast.Message):
            index.messages.append(section)
        elif isinstance(section, ast.ApplicationScope):
            index.applications.append(section)
        elif isinstance(section, ast.AvpTable):
            index.tables.append(section)
        elif isinstance(section, ast.ReusedAvps):
            for row in section.rows:
                if row.origin == own:
                    index.self_cited.append(row.name)
                else:
                    index.reused[row.name] = row.origin
    return index


def _identity(code: int, vendor_id: int | None) -> AvpIdentity:
    """`.dad` writes an IETF-space AVP with no vendor; the wire format calls
    that vendor 0."""
    return AvpIdentity(ast.IETF_VENDOR if vendor_id is None else vendor_id, code)


def _duplicate_definitions(index: _Index) -> list[Finding]:
    by_name: dict[str, list[ast.GroupedAvp | ast.EnumeratedAvp]] = defaultdict(list)
    for definition in index.definitions:
        by_name[definition.name].append(definition)
    findings = []
    for name, group in sorted(by_name.items()):
        if len(group) > 1:
            clauses = ", ".join(d.source.section for d in group)
            findings.append(
                Finding(
                    Severity.ERROR,
                    "duplicate-definition",
                    f"{name} is defined {len(group)} times, in clauses {clauses}",
                )
            )
    return findings


def _one_name_two_commands(index: _Index) -> list[Finding]:
    """One command name used for two command codes.

    Not folded into `_duplicate_definitions`, because a repeated *message* name
    is normal: TS 29.272 defines IDR/DSR/RSR once for S6a and once for S7a,
    same name, same code, two application ids. What cannot be true is one name
    naming two codes, and TS 29.344 does exactly that — clauses 6.2.11/6.2.12
    print clauses 6.2.3/6.2.4's rule names above command 8388713, so
    `ProSe-Subscriber-Information-Request` appeared to be both 8388664 and
    8388713.
    """
    by_name: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for message in index.messages:
        by_name[message.name][message.command_code].append(message.source.section)
    findings = []
    for name, codes in sorted(by_name.items()):
        if len(codes) > 1:
            spelled = ", ".join(
                f"{code} (clause{'s' if len(where) > 1 else ''} {', '.join(where)})"
                for code, where in sorted(codes.items())
            )
            findings.append(
                Finding(
                    Severity.ERROR,
                    "one-name-two-commands",
                    f"{name} is defined with {len(codes)} command codes: {spelled}",
                )
            )
    return findings


def _duplicate_enum_values(index: _Index) -> list[Finding]:
    findings = []
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        values = [v for v in definition.values if isinstance(v, ast.EnumValue)]
        for label, counts in (
            ("value", _repeats(v.value for v in values)),
            ("name", _repeats(v.name for v in values)),
        ):
            for repeated in counts:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "duplicate-enum-value",
                        f"{definition.name} uses the {label} {repeated!r} twice",
                        definition.source.section,
                    )
                )
    return findings


def _applications_agree_with_headers(index: _Index) -> list[Finding]:
    """A command sits in at most one application scope, and a header that
    prints an id prints the scope's.

    Both are what the model's grouping would decide quietly — the first
    block in file order, the header over the block — so a document stating
    two ids for one command is said out loud here instead.
    """
    findings = []
    for message in index.messages:
        blocks = [b for b in index.applications if b.covers(message.source.section)]
        if len(blocks) > 1:
            named = ", ".join(
                f"{b.name} ({b.application_id}, clause {b.source.section})"
                for b in blocks
            )
            findings.append(
                Finding(
                    Severity.ERROR,
                    "application-scope-overlap",
                    f"{message.name} is in the scope of {len(blocks)}"
                    f" applications: {named}",
                    message.source.section,
                )
            )
        for block in blocks:
            if message.application_id not in (None, block.application_id):
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "application-header-mismatch",
                        f"{message.name}'s header prints application"
                        f" {message.application_id}, but clause"
                        f" {block.source.section} gives {block.name}"
                        f" {block.application_id}",
                        message.source.section,
                    )
                )
    return findings


def _repeats[T](items) -> list[T]:
    seen: dict[T, int] = defaultdict(int)
    for item in items:
        seen[item] += 1
    return [item for item, count in seen.items() if count > 1]


def _duplicate_identities(
    index: _Index,
    own_vendor: int,
    reused_vendor: Callable[[str], int | None] | None = None,
) -> list[Finding]:
    """No two AVPs share a `(vendor-id, code)`.

    Not the same rule as "no duplicate names": TS 29.272's `Area-Scope` was
    printed with `Job-Type`'s code, so two differently-named AVPs had one
    identity while every name in the file stayed unique.

    A re-used AVP belongs to the origin's vendor space, which is that
    document's `; Vendor-ID:` to state — not this file's to guess. Two AVPs
    numbered 621 in TS 29.229 are 3GPP's and RFC 7683's, and a comparison that
    assumed one space would call them a collision. `reused_vendor` is the
    cross-document rules supplying that answer, origin reference → vendor-id;
    without it (single-file mode), and for any origin it cannot resolve, the
    row is skipped rather than guessed at.
    """
    holders: dict[AvpIdentity, list[tuple[str, str]]] = defaultdict(list)
    for definition in index.definitions:
        identity = _identity(definition.code, definition.vendor_id)
        holders[identity].append(
            (definition.name, f"{definition.name} (clause {definition.source.section})")
        )
    for row in index.rows:
        if row.code is None:
            continue
        origin = index.reused.get(row.name)
        if origin is None:
            identity = AvpIdentity(own_vendor, row.code)
            claim = f"{row.name} (AVP table)"
        else:
            vendor = None if reused_vendor is None else reused_vendor(origin)
            if vendor is None:
                continue
            identity = AvpIdentity(vendor, row.code)
            claim = f"{row.name} (AVP table, re-used from {origin})"
        # A row whose own definition is in this file is the same AVP, not a
        # second claimant.
        if row.name in {name for name, _ in holders[identity]}:
            continue
        holders[identity].append((row.name, claim))

    findings = []
    for identity, claims in sorted(holders.items(), key=lambda item: item[0].code):
        if len(claims) > 1:
            names = ", ".join(text for _, text in claims)
            findings.append(
                Finding(
                    Severity.ERROR,
                    "duplicate-identity",
                    f"{identity} is claimed by {len(claims)} AVPs: {names}",
                )
            )
    return findings


def _rows_without_codes(index: _Index) -> list[Finding]:
    """A table that declares a Code column fills it in every row.

    An AVP is its `(vendor-id, code)`, so a row printing `-` for its code
    describes nothing a message could carry. Both real cases are the same
    editorial slip: TS 29.229 and TS 29.329 tabulate `Load` code-less among
    their own AVPs while their prose defines it only by reference to
    RFC 8583 — a re-used AVP printed in the wrong table. Only tables that
    declare a Code column are checked: RFC 7155's tables carry no such
    column at all, which is a statement about the document's layout rather
    than about any one AVP.
    """
    findings = []
    for table in index.tables:
        if ast.AvpColumn.CODE not in table.columns:
            continue
        for row in table.rows:
            if row.code is not None:
                continue
            findings.append(
                Finding(
                    Severity.ERROR,
                    "row-without-code",
                    f"{row.name} is tabulated with no AVP code, and an AVP"
                    " without a code has no wire identity; a re-used AVP"
                    " belongs in the re-used table instead",
                    row.section or table.source.section,
                )
            )
    return findings


def _table_agrees_with_definitions(index: _Index) -> list[Finding]:
    by_name = {d.name: d for d in index.definitions}
    findings = []
    for row in index.rows:
        definition = by_name.get(row.name)
        if definition is None:
            continue
        if row.code is not None and row.code != definition.code:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "table-definition-mismatch",
                    f"{row.name}: the AVP table says code {row.code},"
                    f" clause {definition.source.section} says {definition.code}",
                )
            )
        expected = (
            ast.DataType.GROUPED
            if isinstance(definition, ast.GroupedAvp)
            else ast.DataType.ENUMERATED
        )
        if row.data_type is not None and row.data_type != expected:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "table-definition-mismatch",
                    f"{row.name}: the AVP table says type {row.data_type.value},"
                    f" clause {definition.source.section} defines it as"
                    f" {expected.value.lower()}",
                )
            )
    return findings


# What `table-row-mismatch` compares, by the columns each reading spans. The
# Section column is left out: TS 29.273 points each interface's row at its
# own re-printed clause.
_ROW_READINGS = (
    ("code", (ast.AvpColumn.CODE,)),
    ("type", (ast.AvpColumn.TYPE,)),
    (
        "flag rules",
        (
            ast.AvpColumn.MUST,
            ast.AvpColumn.MAY,
            ast.AvpColumn.SHOULD_NOT,
            ast.AvpColumn.MUST_NOT,
        ),
    ),
    ("encrypt", (ast.AvpColumn.ENCRYPT,)),
)


def _tables_agree_with_each_other(index: _Index) -> list[Finding]:
    """Rows naming one AVP in two of a file's AVP tables say the same thing.

    Per-interface tables re-print shared AVPs, and nothing keeps the copies in
    step: TS 29.061 tabulates `3GPP-IMSI` and six more with M in M.not in
    table 9a (clause 16a.5, Gi/SGi) and with M in Must in table 10 (clause
    17.7.0, Gmb). A note, because the per-interface flag rule may be
    deliberate and only the document's editor knows which; the model resolves
    a name to its first row (see `docs/consumers.md`).

    Compared only on columns every table carrying the row declares, and only
    where the cells say something, so a table without an Encrypt column (TS
    29.273's) or a blank type cell makes no claim to disagree with. A code
    disagreement is an error, since two codes are two AVPs; it is left to
    `table-definition-mismatch` when a clause defines the AVP, because that
    rule names which row is wrong.
    """
    placed: dict[str, list[tuple[ast.AvpTable, ast.AvpTableRow]]] = defaultdict(list)
    for table in index.tables:
        for row in table.rows:
            placed[row.name].append((table, row))
    defined = {definition.name for definition in index.definitions}

    findings = []
    for name, copies in placed.items():
        if len(copies) < 2:
            continue
        for label, columns in _ROW_READINGS:
            if label == "code" and name in defined:
                continue
            shared = [
                column
                for column in columns
                if all(column in table.columns for table, _ in copies)
            ]
            spelled = _disagreement(copies, shared)
            if spelled is None:
                continue
            findings.append(
                Finding(
                    Severity.ERROR if label == "code" else Severity.NOTE,
                    "table-row-mismatch",
                    f"{name} is tabulated with differing {label}: {spelled}",
                )
            )
    return findings


def _disagreement(
    copies: list[tuple[ast.AvpTable, ast.AvpTableRow]],
    columns: list[ast.AvpColumn],
) -> str | None:
    """The rows' readings of `columns` grouped by value and spelled for a
    message, or None when every row that says something agrees."""
    readings: dict[str, list[ast.AvpTable]] = defaultdict(list)
    for table, row in copies:
        cells = [formatter.avp_table_cell(row, column) for column in columns]
        if all(cell == "-" for cell in cells):
            continue
        reading = (
            cells[0]
            if len(columns) == 1
            else ", ".join(
                f"{column.value} {cell}"
                for column, cell in zip(columns, cells, strict=True)
            )
        )
        readings[reading].append(table)
    if len(readings) < 2:
        return None
    return "; ".join(
        f"{reading} in {_table_labels(tables)}" for reading, tables in readings.items()
    )


def _table_labels(tables: list[ast.AvpTable]) -> str:
    # RFC 6733 §4.5 captions its table with prose, so there may be no label.
    labels = [table.table or f"(clause {table.source.section})" for table in tables]
    return f"table{'s' if len(labels) > 1 else ''} {', '.join(labels)}"


def _vendor_id_agrees_with_header(index: _Index, own_vendor: int) -> list[Finding]:
    """A definition's vendor-id agrees with the file's `; Vendor-ID:`.

    A clause header writes no vendor-id for an IETF-space AVP, and writes no
    vendor-id when the document simply forgot — the two look identical. What
    tells them apart is the rest of the file. TS 29.272 defines
    `WLAN-offloadability` (clause 7.3.181) with a bare `< AVP header: 1667 >`
    while its own AVP table marks the `V` flag mandatory for that row: the
    document says in one place that the AVP carries a vendor-id and in another
    that it has none. `MIP6-Agent-Info` in the same file is equally vendor-less
    and entirely correct, because it is RFC 5447's and listed as re-used.
    """
    rows = {row.name: row for row in index.rows}
    findings = []
    for definition in index.definitions:
        if definition.name in index.reused:
            # Vendor-less because it belongs to the origin's space, which this
            # file does not state. The cross-document rules settle these.
            continue
        clause = definition.source.section
        if definition.vendor_id is None:
            row = rows.get(definition.name)
            if row is None or ast.AvpFlag.VENDOR not in row.flag_rules.must:
                continue
            findings.append(
                Finding(
                    Severity.ERROR,
                    "vendor-id-mismatch",
                    f"{definition.name} is defined with no vendor-id, but the AVP"
                    f" table requires its V flag; the file is vendor {own_vendor}",
                    clause,
                )
            )
        elif definition.vendor_id != own_vendor:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "vendor-id-mismatch",
                    f"{definition.name} is defined with vendor"
                    f" {definition.vendor_id}, but the file states vendor"
                    f" {own_vendor}",
                    clause,
                )
            )
    return findings


def _self_cited_exists(index: _Index) -> list[Finding]:
    """A re-used row citing this file for an AVP the file neither defines nor
    tabulates: `reused-avp-not-in-origin`, with the file as the origin."""
    local = {definition.name for definition in index.definitions} | {
        row.name for row in index.rows
    }
    return [
        Finding(
            Severity.ERROR,
            "reused-avp-not-in-origin",
            f"{name} is listed as re-used from this document, which neither"
            " defines nor tabulates it",
        )
        for name in sorted(set(index.self_cited) - local)
    ]


def _local_and_reused(index: _Index) -> list[Finding]:
    """An AVP both defined here and listed as re-used from elsewhere.

    A note, not an error. TS 29.272 does this nine times, and it is not
    necessarily a mistake: a specification may re-print another's AVP so a
    reader need not fetch the other document, or *extend* it with fields of its
    own. Which of those it is cannot be decided from this file — it needs the
    origin's definition to compare against, so the comparison belongs to the
    cross-document rules.
    """
    findings = []
    for definition in sorted(index.definitions, key=lambda d: d.name):
        origin = index.reused.get(definition.name)
        if origin is None:
            continue
        findings.append(
            Finding(
                Severity.NOTE,
                "local-and-reused",
                f"{definition.name} is defined here and also listed as re-used"
                f" from {origin}; whether this re-prints or extends it needs"
                f" {origin}",
                definition.source.section,
                origin=origin,
            )
        )
    return findings


def lint(spec: ast.Specification) -> list[Finding]:
    """Every single-file finding, errors before notes."""
    index = _index(spec)
    findings = [
        *_duplicate_definitions(index),
        *_one_name_two_commands(index),
        *_duplicate_enum_values(index),
        *_applications_agree_with_headers(index),
        *_duplicate_identities(index, spec.vendor_id),
        *_rows_without_codes(index),
        *_table_agrees_with_definitions(index),
        *_tables_agree_with_each_other(index),
        *_vendor_id_agrees_with_header(index, spec.vendor_id),
        *_self_cited_exists(index),
        *_local_and_reused(index),
    ]
    return _ordered(findings)


def _ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (f.severity != Severity.ERROR, f.rule))


# --- cross-file rules -------------------------------------------------------
#
# Everything below needs a second document. The single-file rules above decline
# to guess where a name or a vendor space belongs to another specification;
# these are what actually go and look.


@dataclass(frozen=True)
class _Origin:
    """One resolved origin document, indexed once.

    Every cross-file rule looks origins up per re-used row, so resolving and
    re-indexing inside the rules would walk each origin document once per
    citation — 29.272 alone cites eighteen origins across a hundred rows.
    """

    spec: ast.Specification
    defined: dict[str, ast.GroupedAvp | ast.EnumeratedAvp]
    tabled: dict[str, ast.AvpTableRow]
    reused: dict[str, str]
    tables: list[ast.AvpTable]

    @classmethod
    def of(cls, spec: ast.Specification) -> _Origin:
        theirs = _index(spec)
        return cls(
            spec=spec,
            defined={definition.name: definition for definition in theirs.definitions},
            tabled={row.name: row for row in theirs.rows},
            reused=theirs.reused,
            tables=theirs.tables,
        )


def _resolve_origins(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
) -> dict[str, _Origin]:
    origins = {}
    for origin in set(index.reused.values()):
        entry = books.resolve(origin, like=spec)
        if entry is None:
            continue
        origins[origin] = _Origin.of(entry.spec)
    return origins


def _unresolved_origins(
    spec: ast.Specification,
    index: _Index,
    origins: dict[str, _Origin],
    books: corpus.Corpus,
) -> list[Finding]:
    """A re-used row citing a document the corpus does not hold.

    A note, not an error: the document is fine, the corpus is incomplete. It is
    still worth saying, because every other cross-file rule silently does
    nothing for such a row, and a rule that is quiet because it had nothing to
    read looks exactly like a rule that found nothing wrong.

    One note per file rather than per origin. A Rel-18 corpus without an RFC
    extractor cannot resolve a single RFC, and 29.272 alone cites eighteen
    origins — reported individually they would bury every real finding, and
    they all say the same thing.
    """
    missing = []
    for origin in sorted(set(index.reused.values())):
        if origin in origins:
            continue
        held = books.versions(origin)
        missing.append(f"{origin} (corpus has {', '.join(held)})" if held else origin)
    if not missing:
        return []
    return [
        Finding(
            Severity.NOTE,
            "origin-not-in-corpus",
            f"{len(missing)} of {len(set(index.reused.values()))} cited origins"
            f" could not be resolved for a {spec.version or 'version-less'} document,"
            f" and the rules"
            f" needing them were skipped: {', '.join(missing)}",
        )
    ]


def _reused_avp_exists(index: _Index, origins: dict[str, _Origin]) -> list[Finding]:
    """Every re-used AVP is something the origin actually has.

    Two outcomes, because "the origin never heard of this AVP" and "the origin
    borrows it too" are different sizes of wrong. TS 29.283 cites `Feature-Id`
    from TS 29.229, which has no such AVP — 29.229 defines `Feature-List-ID`,
    and no dictionary anywhere carries a `Feature-Id`. TS 29.172 cites
    `Service-Selection` from TS 29.272, which does carry it but as a re-used
    AVP of RFC 5778's; the AVP is real and the citation names a middleman.
    """
    findings = []
    for name, origin in sorted(index.reused.items()):
        resolved = origins.get(origin)
        if resolved is None:
            continue
        if name in resolved.defined or name in resolved.tabled:
            continue
        theirs = resolved.reused.get(name)
        if theirs is not None:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "reused-origin-indirect",
                    f"{name} is listed as re-used from {origin}, which re-uses it"
                    f" from {theirs} rather than defining it",
                )
            )
            continue
        # An RFC entry has no version to name; the specification string alone
        # already names the immutable document.
        origin_doc = resolved.spec.specification
        if resolved.spec.version is not None:
            origin_doc += f" {resolved.spec.version}"
        findings.append(
            Finding(
                Severity.ERROR,
                "reused-avp-not-in-origin",
                f"{name} is listed as re-used from {origin}, but {origin_doc}"
                " neither defines, tabulates nor re-uses it",
            )
        )
    return findings


def _reused_rows_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """A row this file tabulates for an AVP it re-uses reads the origin's way.

    The cross-file counterpart of `table-row-mismatch`, with the same
    discipline: only what both rows state is compared. Type and encrypt are
    compared where both tables declare the column and both cells say
    something; with no origin row typing the AVP, an origin definition types it
    Grouped or Enumerated. A flag is compared where both rows place it in a
    column: RFC 7683's table puts M in neither Must nor Must-not, which leaves
    a citing interface free to forbid it. A row agreeing with any of the
    origin's rows agrees, since the origin's own disagreements are its
    `table-row-mismatch`. A note, because a citing interface may set its own
    flag rule on purpose. A re-used table's M-bit column is not compared: it
    states this interface's setting, which is what the column is for. Codes are
    `reused-code-conflict`'s.

    Only M and V are compared. RFC 6733 clause 4.1 reserves the P bit ("the
    'P' bit SHOULD be set to 0"), so documents written since drop it while
    their origins (RFC 4005, 4006, 5778; TS 29.212) still print it: across two
    documents a P cell records which side of RFC 6733 each was written on.
    """
    ours: dict[str, list[tuple[ast.AvpTable, ast.AvpTableRow]]] = defaultdict(list)
    for table in index.tables:
        for row in table.rows:
            ours[row.name].append((table, row))
    findings = []
    for name, origin in sorted(index.reused.items()):
        resolved = origins.get(origin)
        if resolved is None or name not in ours:
            continue
        theirs = [
            (table, row)
            for table in resolved.tables
            for row in table.rows
            if row.name == name
        ]
        definition = resolved.defined.get(name)
        for table, row in ours[name]:
            for label, compared in _row_comparisons(table, row, theirs, definition):
                if not compared or any(mine == other for mine, other, _ in compared):
                    continue
                spelled = "; ".join(
                    f"{other} in {where}" for _, other, where in compared
                )
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "reused-row-mismatch",
                        f"{name} is tabulated with {label} {compared[0][0]} in"
                        f" {_table_labels([table])}, but {origin}, which it is"
                        f" re-used from, reads {spelled}",
                    )
                )
    return findings


_CROSS_FILE_FLAGS = (ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR)
_FLAG_COLUMNS = {
    ast.AvpColumn.MUST: "must",
    ast.AvpColumn.MAY: "may",
    ast.AvpColumn.SHOULD_NOT: "should_not",
    ast.AvpColumn.MUST_NOT: "must_not",
}


def _row_comparisons(
    table: ast.AvpTable,
    row: ast.AvpTableRow,
    theirs: list[tuple[ast.AvpTable, ast.AvpTableRow]],
    definition: ast.GroupedAvp | ast.EnumeratedAvp | None,
) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Per reading, the (this row, origin row, where) pairs that both state."""
    out = []
    for label, column in (
        ("type", ast.AvpColumn.TYPE),
        ("encrypt", ast.AvpColumn.ENCRYPT),
    ):
        compared = [
            (mine, other, _table_labels([their_table]))
            for their_table, their_row in theirs
            if column in table.columns
            and column in their_table.columns
            and (mine := formatter.avp_table_cell(row, column)) != "-"
            and (other := formatter.avp_table_cell(their_row, column)) != "-"
        ]
        if (
            not compared
            and column is ast.AvpColumn.TYPE
            and definition is not None
            and column in table.columns
            and row.data_type is not None
        ):
            kind = (
                ast.DataType.GROUPED
                if isinstance(definition, ast.GroupedAvp)
                else ast.DataType.ENUMERATED
            )
            compared = [
                (
                    row.data_type.value,
                    kind.value,
                    f"its clause {definition.source.section}",
                )
            ]
        out.append((label, compared))
    for flag in _CROSS_FILE_FLAGS:
        mine = _placement(table, row, flag)
        compared = [
            (f"{flag.value} in {mine}", f"{flag.value} in {other}", _table_labels([t]))
            for t, their_row in theirs
            if mine is not None
            and (other := _placement(t, their_row, flag)) is not None
        ]
        out.append(("flag rule", compared))
    return out


def _placement(
    table: ast.AvpTable, row: ast.AvpTableRow, flag: ast.AvpFlag
) -> str | None:
    """The flag-rule column a row puts `flag` in, or None if it states none."""
    for column, field_name in _FLAG_COLUMNS.items():
        if column in table.columns and flag in getattr(row.flag_rules, field_name):
            return column.value
    return None


def _reprint_or_extension(index: _Index, origins: dict[str, _Origin]) -> list[Finding]:
    """Decide what a local-and-re-used AVP is actually doing.

    This is the answer the single-file `local-and-reused` note declines to
    give. The one thing that is unambiguously wrong is disagreeing on the
    *code*: an AVP is its `(vendor-id, code)`, so two codes are two AVPs and
    one of the documents is mistaken. Everything else is reported as what it
    is — identical, a superset, or neither — and left to a reader, because a
    body that differs is a fact about two documents rather than a defect in
    this one, and only the origin's editor knows which is current.
    """
    findings = []
    for definition in sorted(index.definitions, key=lambda d: d.name):
        origin = index.reused.get(definition.name)
        if origin is None:
            continue
        resolved = origins.get(origin)
        if resolved is None:
            continue
        theirs = resolved.defined.get(definition.name)
        if theirs is None:
            # The origin has it only as a table row, so there is no body to
            # compare; `_reused_avp_exists` has already accepted it.
            continue
        where = definition.source.section
        if definition.code != theirs.code:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reused-code-conflict",
                    f"{definition.name} is code {definition.code} here and"
                    f" {theirs.code} in {origin} clause {theirs.source.section}",
                    where,
                )
            )
            continue
        rule, message = _compare(definition, theirs, origin)
        findings.append(Finding(Severity.NOTE, rule, message, where))
    return findings


def _members(definition: ast.GroupedAvp | ast.EnumeratedAvp) -> frozenset[str]:
    """What a definition's body lists: member AVPs, or enumerated value names.
    Comparing these compares the two documents' idea of the AVP's contents."""
    if isinstance(definition, ast.GroupedAvp):
        return frozenset(rule.name for rule in definition.avps)
    return frozenset(
        value.name for value in definition.values if isinstance(value, ast.EnumValue)
    )


def _compare(mine, theirs, origin: str) -> tuple[str, str]:
    """The rule name and the finished message, as a pair."""
    subject = f"{mine.name}'s body, against {origin}'s definition:"
    if type(mine) is not type(theirs):
        return "reused-body-differs", f"{subject} a different kind of AVP entirely"
    ours, base = _members(mine), _members(theirs)
    if ours == base:
        return "reused-reprint", f"{subject} identical, so this re-prints it"
    added = ", ".join(sorted(ours - base))
    dropped = ", ".join(sorted(base - ours))
    if base < ours:
        return "reused-extension", f"{subject} extended, adding {added}"
    if ours < base:
        return "reused-body-differs", f"{subject} missing {dropped}"
    return "reused-body-differs", f"{subject} adds {added}, missing {dropped}"


def _resolve_bases(
    spec: ast.Specification, books: corpus.Corpus
) -> tuple[dict[str, _Origin], list[str]]:
    """Resolve `; Bases:` the way re-used origins resolve, keeping the misses.

    Bases are the documents a file builds on without citing them anywhere —
    RFC 6733 for every Diameter application — so they share the origin
    machinery but not the origin rules: a base supplies names for reference
    resolution rather than rows to compare against.
    """
    resolved, missing = {}, []
    for base in spec.bases:
        entry = books.resolve(base, like=spec)
        if entry is None:
            missing.append(base)
            continue
        resolved[base] = _Origin.of(entry.spec)
    return resolved, missing


def _unresolved_references(
    index: _Index, bases: dict[str, _Origin], missing_bases: list[str]
) -> list[Finding]:
    """Every AVP referenced in a message or grouped body resolves somewhere:
    a local definition, an AVP-table row, a re-used entry, or a base document.

    This is phase two's rule, enforceable now that `; Bases:` names the
    document that supplies `Session-Id`, `Origin-Host` and the rest. The
    trailing `* [ AVP ]` is RFC 6733's any-AVP wildcard — grammar, not a
    reference — and is skipped rather than resolved to the name `AVP`.

    A base missing from the corpus turns the rule off with a note instead of
    reporting every base-protocol AVP as unresolved: the document is fine, the
    corpus is incomplete, and a hundred spurious errors would bury the real
    findings.

    A note rather than an error, for now: the corrected corpus still carries
    34 of these — references to AVPs a document neither defines, tabulates
    nor lists as re-used (29.337's `MME-Name` from TS 29.336, RFC 8581's
    `OC-Report-Type` from RFC 7683) plus at least one outright source typo
    (29.345's `WiFi-P2P-Assistance-Iinfo`). Each needs a correction, a wider
    re-used table reading, or an extra `; Bases:` entry before the rule can
    promote to an error without breaking the corpus's clean exit.
    """
    if missing_bases:
        return [
            Finding(
                Severity.NOTE,
                "base-not-in-corpus",
                f"the corpus holds no copy of base"
                f" document{'s' if len(missing_bases) > 1 else ''}"
                f" {', '.join(missing_bases)}, so reference resolution was"
                " skipped",
            )
        ]
    known = (
        {definition.name for definition in index.definitions}
        | {row.name for row in index.rows}
        | set(index.reused)
    )
    for base in bases.values():
        known |= base.defined.keys() | base.tabled.keys() | base.reused.keys()
    cited_by: dict[str, list[str]] = defaultdict(list)
    for section in (*index.messages, *index.definitions):
        if not isinstance(section, ast.Message | ast.GroupedAvp):
            continue
        for rule in section.avps:
            if rule.name == "AVP" or rule.name in known:
                continue
            cited_by[rule.name].append(section.source.section)
    return [
        Finding(
            Severity.NOTE,
            "unresolved-reference",
            f"{name} is referenced in clause{'s' if len(where) > 1 else ''}"
            f" {', '.join(dict.fromkeys(where))} but resolves to no local"
            " definition, table row, re-used entry or base document",
        )
        for name, where in sorted(cited_by.items())
    ]


def lint_with_corpus(spec: ast.Specification, books: corpus.Corpus) -> list[Finding]:
    """Every finding for `spec`, single-file and cross-file together.

    The single-file rules that a second document supersedes are dropped rather
    than reported alongside their own answers: `local-and-reused` becomes
    `reused-reprint` or `reused-body-differs`, and `duplicate-identity` is
    re-run with re-used rows resolved into their origins' vendor spaces. A row
    whose origin is missing from the corpus keeps the single-file behaviour,
    which is why the superseded findings are filtered by what actually
    resolved.
    """
    index = _index(spec)
    origins = _resolve_origins(spec, index, books)
    bases, missing_bases = _resolve_bases(spec, books)

    def reused_vendor(origin: str) -> int | None:
        resolved = origins.get(origin)
        return None if resolved is None else resolved.spec.vendor_id

    superseded = {"local-and-reused", "duplicate-identity"}
    findings = [
        finding
        for finding in lint(spec)
        if finding.rule not in superseded
        or (finding.rule == "local-and-reused" and finding.origin not in origins)
    ]
    findings += [
        *_unresolved_origins(spec, index, origins, books),
        *_reused_avp_exists(index, origins),
        *_reprint_or_extension(index, origins),
        *_reused_rows_agree_with_origin(index, origins),
        *_duplicate_identities(index, spec.vendor_id, reused_vendor),
        *_unresolved_references(index, bases, missing_bases),
    ]
    return _ordered(findings)
