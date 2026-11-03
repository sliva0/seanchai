"""Structural rules over one parsed `.dad` file.

The extractor records what a specification says, including where it
contradicts itself; this is the layer that reports those contradictions
instead of resolving them. Every rule here is decided inside a single file,
and nearly every one has a real case in the committed corpus — they are not
hypothetical invariants, they are the inconsistencies three specifications
actually contain. The exceptions are the two application-scope rules, which
report what `model.Model.applications` would otherwise settle without
comment, and two of the registry rules, `registry-command-name` and
`registry-application-document`, which compare the corpus with TS 29.230
and find it agreeing.

Findings carry a severity because not every one of them is a defect:

- `ERROR` — the file asserts two things that cannot both be true, whoever is
  at fault. Two AVPs with one identity; a table row disagreeing with the
  definition it points at.
- `NOTE` — something worth knowing that a single file cannot judge. An AVP
  both defined locally and listed as re-used is the case that forced the
  distinction: a specification may re-print another's AVP for convenience or
  *extend* it with new fields, and deciding which needs the origin document.
- `ACCEPTED` — a note an `Accept` in the specification's corrections module
  acknowledges as a deliberate override its document states (`accept`).

An AVP's identity is `(vendor-id, code)`, and the vendor half comes from the
file's own `; Vendor-ID:` directive, except for a table row printing a
Vendor-ID cell, which states its own, and one whose V flag is Must-not,
which is IETF space (`ast.AvpTableRow.stated_vendor`, the model's reading
too); re-used rows belong to their origins' vendor spaces, which the
single-file rules therefore leave to the cross-file ones — see
`_duplicate_identities`.

Findings are anchored by clause and name rather than by line number. The AST
carries no line information, and a clause reference survives reformatting and
points at the same place in the specification as in the `.dad` file — which is
where the reader has to go anyway.
"""

from __future__ import annotations

import dataclasses
import enum
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from . import corpus, model
from .dad import ast, corrections, formatter


@dataclass(frozen=True)
class AvpIdentity:
    """What actually distinguishes one AVP from another."""

    vendor_id: int
    code: int

    def __str__(self) -> str:
        return f"vendor {self.vendor_id}, code {self.code}"


class Severity(enum.StrEnum):
    # Declaration order is report order.
    ERROR = "error"
    NOTE = "note"
    ACCEPTED = "accepted"


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
    # The acceptance a note was accepted by, as a corrected file cites it
    # (`TS29.336.py#serving-node-t4-body`).
    accepted_by: str | None = None
    # Where in the tree the nodes the finding is about sit, as correction
    # selectors locate them: the definition whose body differs, every row
    # of a name the tables disagree on. What an acceptance's target must
    # select; a rule that sets none cannot be accepted.
    paths: tuple[ast.TreePath, ...] = ()

    def __str__(self) -> str:
        where = f" (clause {self.section})" if self.section else ""
        by = f" ({self.accepted_by})" if self.accepted_by else ""
        return f"{self.severity.value}: [{self.rule}] {self.message}{where}{by}"


@dataclass
class _Index:
    """The one pass over the file that every rule reads from."""

    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp] = field(default_factory=list)
    messages: list[ast.Message] = field(default_factory=list)
    applications: list[ast.ApplicationScope] = field(default_factory=list)
    # `Undefined AVP` blocks: names the file declares defined nowhere.
    undefined: list[ast.UndefinedAvp] = field(default_factory=list)
    # `Reprinted AVP` blocks: another document's rule, as this one prints it.
    reprints: list[ast.ReprintedAvp] = field(default_factory=list)
    tables: list[ast.AvpTable] = field(default_factory=list)
    value_tables: list[ast.ValueTable] = field(default_factory=list)
    reused: dict[str, str] = field(default_factory=dict)  # AVP name -> origin
    # Names a re-used table cites from this file itself. TS 29.212's Gxx, S9,
    # Sd and St tables list Gx's AVPs "from" TS 29.212: those are this file's
    # own definitions, so no rule treats them as belonging elsewhere.
    self_cited: list[str] = field(default_factory=list)
    # Re-used rows printing the AVP's code or type (TS 29.172 table
    # 7.4.1-2), with their block, for comparing against the origin.
    reused_cells: list[tuple[ast.ReusedAvps, ast.ReusedAvpRow]] = field(
        default_factory=list
    )
    # Each section, body rule and row's tree path, by object identity:
    # equal nodes in two places are two nodes.
    paths: dict[int, ast.TreePath] = field(default_factory=dict)
    # Re-used rows' paths by AVP name.
    reused_paths: dict[str, list[ast.TreePath]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def path(self, node: ast.Node) -> ast.TreePath:
        return self.paths[id(node)]

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
    for position, section in enumerate(spec.sections):
        at: ast.TreePath = ("sections", position)
        index.paths[id(section)] = at
        if isinstance(section, ast.Message | ast.GroupedAvp | ast.ReprintedAvp):
            for number, rule in enumerate(section.avps):
                index.paths[id(rule)] = (*at, "avps", number)
        if isinstance(section, ast.AvpTable | ast.ReusedAvps | ast.ValueTable):
            for number, row in enumerate(section.rows):
                index.paths[id(row)] = (*at, "rows", number)
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
            index.definitions.append(section)
        elif isinstance(section, ast.Message):
            index.messages.append(section)
        elif isinstance(section, ast.ApplicationScope):
            index.applications.append(section)
        elif isinstance(section, ast.UndefinedAvp):
            index.undefined.append(section)
        elif isinstance(section, ast.ReprintedAvp):
            index.reprints.append(section)
        elif isinstance(section, ast.AvpTable):
            index.tables.append(section)
        elif isinstance(section, ast.ValueTable):
            index.value_tables.append(section)
        elif isinstance(section, ast.ReusedAvps):
            for row in section.rows:
                index.reused_paths[row.name].append(index.path(row))
                if row.origin == own:
                    index.self_cited.append(row.name)
                else:
                    index.reused[row.name] = row.origin
                    if row.code is not None or row.data_type is not None:
                        index.reused_cells.append((section, row))
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
                    paths=tuple(index.path(definition) for definition in group),
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


def _duplicate_values(index: _Index) -> list[Finding]:
    """One value table giving one number twice: a number means one thing in
    one table, whether the names agree or not."""
    findings = []
    for table in index.value_tables:
        by_value: dict[int, list[ast.ValueRow]] = defaultdict(list)
        for row in table.rows:
            by_value[row.value].append(row)
        for value, rows in by_value.items():
            if len(rows) > 1:
                names = ", ".join(repr(name) for name in {r.name: None for r in rows})
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "duplicate-value",
                        f"{table.avp}'s {table.kind} table gives {value} to {names},"
                        f" {len(rows)} rows",
                        table.source.section,
                        paths=tuple(index.path(row) for row in rows),
                    )
                )
    return findings


def _values_out_of_range(index: _Index) -> list[Finding]:
    """A bit past what its AVP holds: 31 for an Unsigned32, the type every bit
    mask but a few has, and 63 for one the file's own table types Unsigned64
    (TS 29.272's `Broadcast-Location-Assistance-Data-Types`)."""
    typed = {row.name: row.data_type for row in index.rows if row.data_type}
    findings = []
    for table in index.value_tables:
        if table.kind is ast.ValueKind.RESULT_CODES:
            continue
        data_type = typed.get(table.avp, ast.DataType.UNSIGNED32)
        last = 63 if data_type is ast.DataType.UNSIGNED64 else 31
        findings.extend(
            Finding(
                Severity.ERROR,
                "value-bit-out-of-range",
                f"{table.avp}'s {table.kind} table numbers {row.name!r} bit"
                f" {row.value}, past the {last} a {data_type} holds",
                table.source.section,
                paths=(index.path(row),),
            )
            for row in table.rows
            if row.value > last
        )
    return findings


def _enum_entry_label(entry: ast.EnumEntry) -> str:
    if isinstance(entry, ast.EnumValue):
        return f"{entry.name!r} = {entry.value}"
    if isinstance(entry, ast.ReservedValues):
        kind = "reserved"
    elif isinstance(entry, ast.VoidValues):
        kind = "void"
    else:
        kind = "vendor-specific"
    return f"{kind} {entry.first}-{entry.last}"


def _vendor_specific_overlaps(index: _Index) -> list[Finding]:
    """A `; VENDOR-SPECIFIC` range covering a value the AVP names, a range it
    reserves or voids, or another vendor-specific range.

    A vendor-specific value is legal under a name the document does not
    give, a named value means what its name says, and a reserved one is
    illegal, so one value cannot be two of them. No corpus case: TS 32.299's
    SM-Service-Type and oneM2M TS-0004's Protocol-Type leave 100-199 to
    vendors above the ranges they name and reserve.
    """
    findings = []
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        entries = definition.values
        for position, vendor in enumerate(entries):
            if not isinstance(vendor, ast.VendorSpecificValues):
                continue
            for at, other in enumerate(entries):
                # A pair of vendor-specific ranges is reported once.
                if at == position or (
                    at < position and isinstance(other, ast.VendorSpecificValues)
                ):
                    continue
                first, last = (
                    (other.value, other.value)
                    if isinstance(other, ast.EnumValue)
                    else (other.first, other.last)
                )
                if vendor.first <= last and first <= vendor.last:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "vendor-specific-overlap",
                            f"{definition.name}'s {_enum_entry_label(vendor)}"
                            f" overlaps {_enum_entry_label(other)}",
                            definition.source.section,
                        )
                    )
    return findings


def _void_overlaps(index: _Index) -> list[Finding]:
    """A `; VOID` value the AVP also names or reserves, or a second `; VOID`
    over it. A withdrawn value is no longer assigned, so a name on it says the
    opposite, and it was assigned once, so a reservation does too. A
    vendor-specific range over one is `vendor-specific-overlap`'s. No corpus
    case: TS 29.214's Specific-Action names neither 0 nor 5 beside its voids.
    """
    findings = []
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        entries = definition.values
        for position, void in enumerate(entries):
            if not isinstance(void, ast.VoidValues):
                continue
            for at, other in enumerate(entries):
                # A pair of void lines is reported once.
                if (
                    at == position
                    or isinstance(other, ast.VendorSpecificValues)
                    or (at < position and isinstance(other, ast.VoidValues))
                ):
                    continue
                first, last = (
                    (other.value, other.value)
                    if isinstance(other, ast.EnumValue)
                    else (other.first, other.last)
                )
                if void.first <= last and first <= void.last:
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            "void-overlap",
                            f"{definition.name}'s {_enum_entry_label(void)}"
                            f" overlaps {_enum_entry_label(other)}",
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
            stated = row.stated_vendor(own_vendor)
            identity = AvpIdentity(own_vendor if stated is None else stated, row.code)
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

    A row with a clause and no code, flag or Encrypt cell is no such slip but
    the whole of what its clause states, inserted for a table omitting the
    AVP: TS 29.229's `Wildcarded-IMPU`, clause 6.3.43. The file cannot give
    the code it does not state, so that is a note, and the model's hole.
    """
    findings = []
    for table in index.tables:
        if ast.AvpColumn.CODE not in table.columns:
            continue
        for row in table.rows:
            if row.code is not None:
                continue
            flags = row.flag_rules
            placed = flags.must | flags.may | flags.should_not | flags.must_not
            if row.section is not None and not placed and row.may_encrypt is None:
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "row-without-code",
                        f"{row.name} is tabulated with no AVP code: clause"
                        f" {row.section} states none, so it has no wire identity"
                        " in this document",
                        row.section,
                    )
                )
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
    ("vendor", (ast.AvpColumn.VENDOR,)),
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
    or vendor disagreement is an error, since two identities are two AVPs; a
    code's is left to `table-definition-mismatch` when a clause defines the
    AVP, because that rule names which row is wrong.
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
                    Severity.ERROR if label in ("code", "vendor") else Severity.NOTE,
                    "table-row-mismatch",
                    f"{name} is tabulated with differing {label}: {spelled}",
                    paths=tuple(index.path(row) for _, row in copies),
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
    """A definition's vendor-id agrees with the file's `; Vendor-ID:`, or
    with its row's Vendor-ID cell where the table prints one.

    A clause header writes no vendor-id for an IETF-space AVP, and writes no
    vendor-id when the document simply forgot — the two look identical. What
    tells them apart is the rest of the file. TS 29.272 defines
    `WLAN-offloadability` (clause 7.3.181) with a bare `< AVP header: 1667 >`
    while its own AVP table marks the `V` flag mandatory for that row: the
    document says in one place that the AVP carries a vendor-id and in another
    that it has none. `MIP6-Agent-Info` in the same file is equally vendor-less
    and entirely correct, because it is RFC 5447's and listed as re-used.
    oneM2M TS-0004 prints `M2M-Information`'s header with no vendor-id
    (clause A.5.14) and its row in table A.4-1 with vendor 45687.
    """
    rows = {row.name: row for row in index.rows}
    findings = []
    for definition in index.definitions:
        if definition.name in index.reused:
            # Vendor-less because it belongs to the origin's space, which this
            # file does not state. The cross-document rules settle these.
            continue
        clause = definition.source.section
        row = rows.get(definition.name)
        stated = None if row is None else row.vendor_id
        if stated is not None:
            if (definition.vendor_id or ast.IETF_VENDOR) == stated:
                continue
            printed = (
                "no vendor-id"
                if definition.vendor_id is None
                else f"vendor {definition.vendor_id}"
            )
            findings.append(
                Finding(
                    Severity.ERROR,
                    "vendor-id-mismatch",
                    f"{definition.name} is defined with {printed}, but the AVP"
                    f" table gives it vendor {stated}",
                    clause,
                )
            )
        elif definition.vendor_id is None:
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


def _vendors_agree_with_flags(index: _Index) -> list[Finding]:
    """A row's Vendor-ID cell and its V flag say the same thing.

    RFC 6733 section 4.1.1 sets the V bit exactly when the header carries a
    Vendor-ID, which is never zero. oneM2M TS-0004 table A.4-1 prints
    vendor 45687 for its own AVPs, as clause A.4 assigns them ("AVPs defined
    for oneM2M specific usage are assigned Vendor-Id of 45687"), and puts V
    under Must-not in every one of those rows, as it does for its IETF rows.
    The model takes the vendor from the cell (`AvpTableRow.stated_vendor`).
    """
    return [
        Finding(
            Severity.ERROR,
            "vendor-flag-mismatch",
            f"{row.name} is tabulated with {conflict} in"
            f" {_table_labels([table])}; RFC 6733 section 4.1.1 sets V exactly"
            " when the header carries a vendor-id, which is never 0",
            row.section or table.source.section,
            paths=(index.path(row),),
        )
        for table in index.tables
        for row in table.rows
        if (conflict := row.vendor_flag_conflict()) is not None
    ]


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


def _members_marked_unused(spec: ast.Specification) -> list[Finding]:
    """A command's ABNF member its tables mark unused in that command.

    TS 32.299 tabulates per command whether an AVP is used in it, a column
    each for ACR, ACA, CCR and CCA, and clause 7.1.0 reads the dash: "Those
    Diameter AVPs that are not used are marked '-'". Table 7.1.0.1 marks
    `Error-Message` and `Failed-AVP` so under ACA, whose clause 6.2.3 ABNF
    lists both. A note: the ABNF is the wire format, and only the document's
    editor knows which statement is meant. A blank cell marks nothing, and
    the `* [ AVP ]` wildcard is grammar, not a member.
    """
    unused: dict[tuple[str, ast.MarkColumn], list[str]] = defaultdict(list)
    for section in spec.sections:
        if not isinstance(section, ast.AvpTable | ast.ReusedAvps):
            continue
        label = section.table or f"(clause {section.source.section})"
        for row in section.rows:
            for column, marks in row.marks.items():
                if marks == ():
                    unused[row.name, column].append(label)
    findings = []
    for position, section in enumerate(spec.sections):
        if (
            not isinstance(section, ast.Message)
            or section.abbreviation not in ast.MarkColumn
        ):
            continue
        command = ast.MarkColumn(section.abbreviation)
        for number, rule in enumerate(section.avps):
            if rule.name == "AVP":
                continue
            findings += [
                Finding(
                    Severity.NOTE,
                    "member-marked-unused",
                    f"{rule.name} is a member of {section.abbreviation}, but"
                    f" table {label} marks it '-', unused in"
                    f" {section.abbreviation}",
                    section.source.section,
                    paths=(("sections", position, "avps", number),),
                )
                for label in unused.get((rule.name, command), [])
            ]
    return findings


def _references(index: _Index) -> dict[str, list[str]]:
    """The clauses of the message and grouped bodies naming each member,
    in file order, `* [ AVP ]` aside."""
    cited_by: dict[str, list[str]] = defaultdict(list)
    for section in (*index.messages, *index.definitions):
        if not isinstance(section, ast.Message | ast.GroupedAvp):
            continue
        for rule in section.avps:
            if rule.name != "AVP":
                cited_by[rule.name].append(section.source.section)
    return {name: list(dict.fromkeys(where)) for name, where in cited_by.items()}


def _clauses(where: list[str]) -> str:
    return f"clause{'s' if len(where) > 1 else ''} {', '.join(where)}"


def _undefined_avps(index: _Index) -> list[Finding]:
    """What each `Undefined AVP` block declares, checked against the file.

    `undefined-avp`, a note per block a body references: the name is a
    corpus finding a consumer has to decide about (docs/consumers.md).
    `undefined-avp-unused`, an error: a block whose name no body
    references, or whose clause holds no body naming it. And
    `undefined-avp-defined`, an error: a block for a name the file defines,
    tabulates, lists as re-used or declares twice, a stale claim the model
    would quietly read past."""
    referenced = _references(index)
    known = (
        {definition.name for definition in index.definitions}
        | {row.name for row in index.rows}
        | set(index.reused)
        | set(index.self_cited)
    )
    declared: dict[str, int] = defaultdict(int)
    for block in index.undefined:
        declared[block.name] += 1
    findings = []
    for block in index.undefined:
        name, clause = block.name, block.source.section
        paths = (index.path(block),)
        where = referenced.get(name)
        if name in known:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-defined",
                    f"{name} is declared undefined, but the file defines,"
                    " tabulates or re-uses it",
                    clause,
                    paths=paths,
                )
            )
        if declared[name] > 1:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-defined",
                    f"{name} is declared undefined {declared[name]} times",
                    clause,
                    paths=paths,
                )
            )
        if where is None:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-unused",
                    f"{name} is declared undefined, but no body references it",
                    clause,
                    paths=paths,
                )
            )
        elif clause not in where:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "undefined-avp-unused",
                    f"{name} is declared undefined citing a clause whose"
                    f" bodies do not reference it; it is referenced in"
                    f" {_clauses(where)}",
                    clause,
                    paths=paths,
                )
            )
        else:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "undefined-avp",
                    f"{name} is referenced in {_clauses(where)} and declared undefined",
                    clause,
                    paths=paths,
                )
            )
    return findings


def _with_parents(clause: str) -> set[str]:
    """`clause` and every clause above it: 5.3.81, 5.3 and 5."""
    parts = clause.split(".")
    return {".".join(parts[:count]) for count in range(1, len(parts) + 1)}


# A `; Values:` naming a clause and no document, so a clause of this one:
# oneM2M TS-0004 clause A.5.25's "clause 6.6.3".
_OWN_CLAUSE = re.compile(r"^(?:clause|section) (\S+)$", re.IGNORECASE)


def _section_references(spec: ast.Specification, index: _Index) -> list[Finding]:
    """A clause the file cites against the clauses the file holds.

    `section-mismatch`: a row citing a clause for an AVP a block here holds
    elsewhere. TS 29.214 V19.3.0's table 5.3.0.1 cites 5.3.142 for
    `PC-Session-Recovery-Status`, which clause 5.3.81 defines and no 5.3.142
    exists. A definition, a re-print and a bit table are what hold an AVP, and
    a row may cite any of them or a clause above one, as a table may. A result
    code or feature table is not: TS 29.229 tabulates `Feature-List` at its
    clause 6.3.31 and lists the features in clause 7.1.1, both as they should.

    `section-unknown`: an `; Applies-To:` or a `; Values:` naming a clause no
    block sits at or under, each a sentence about a clause in particular.

    A row whose AVP no block holds is not checked. A simple-typed AVP has no
    block, so its clause is absent from any file: against the documents' own
    headings, the 1249 of 2257 citations such a check reports held one wrong,
    `PC-Session-Recovery-Status`, which the first rule finds anyway. A re-used
    row, a registry row and `; From:` cite documents and no clause.

    Notes: a file holds what its document prints, so a misprint stays, and a
    clause may exist that the file has no block for.
    """
    known: set[str] = set()
    holding: dict[str, list[str]] = defaultdict(list)
    for section in spec.sections:
        known |= _with_parents(section.source.section)
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp | ast.ReprintedAvp):
            holding[section.name].append(section.source.section)
        elif isinstance(section, ast.ValueTable):
            known.update(
                clause
                for row in section.rows
                if row.section is not None
                for clause in _with_parents(row.section)
            )
            if section.kind is ast.ValueKind.BITS:
                holding[section.avp].append(section.source.section)
    findings = []
    for table in index.tables:
        for row in table.rows:
            cited, held = row.section, holding.get(row.name)
            if (
                cited is None
                or held is None
                or any(cited in _with_parents(clause) for clause in held)
            ):
                continue
            absent = "" if cited in known else f", and nothing at clause {cited}"
            findings.append(
                Finding(
                    Severity.NOTE,
                    "section-mismatch",
                    f"{row.name} is cited at clause {cited} in"
                    f" {_table_labels([table])}, but the file holds it at"
                    f" {_clauses(list(dict.fromkeys(held)))}{absent}",
                    table.source.section,
                    paths=(index.path(row),),
                )
            )
    for block in index.applications:
        for entry in block.applies_to:
            clause = entry.removesuffix(".*")
            if clause not in known:
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "section-unknown",
                        f"{block.name} applies to clause {entry}, under which the"
                        " file holds no block",
                        block.source.section,
                        paths=(index.path(block),),
                    )
                )
    for definition in index.definitions:
        if not isinstance(definition, ast.EnumeratedAvp):
            continue
        cited = _OWN_CLAUSE.match(definition.values_source or "")
        if cited is not None and cited[1] not in known:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "section-unknown",
                    f"{definition.name}'s values are cited from clause {cited[1]},"
                    " where the file holds no block",
                    definition.source.section,
                    paths=(index.path(definition),),
                )
            )
    return findings


def _reservation_label(reservation: ast.RegistryReservation) -> str:
    purpose = "" if reservation.purpose is None else f" for {reservation.purpose!r}"
    return f"{reservation.first}..{reservation.last} (reserved{purpose})"


def _registry_overlaps(spec: ast.Specification) -> list[Finding]:
    """Within one registry table, a code it allocates twice, two reserved
    ranges that overlap, or a reservation covering a code a row allocates.

    TS 29.230 records each as printed: table 7.1 allocates 318 to
    3GPP-AAA-Server-Name in TS 29.234's block and again in TS 29.273's, and
    reserves 4703-4799 for TS 29.389 inside 4605-4799 for TS 29.388; table
    8.1.3 reserves 4182-4200 for TS 29.272 after allocating it 4182. A note:
    a range reserved for a document may well hold that document's codes,
    and which statement is meant is the registry's editor's to say.
    """
    findings = []
    for section in spec.sections:
        if not isinstance(section, ast.Registry):
            continue
        where = f"table {section.table}"
        rows = [row for row in section.rows if isinstance(row, ast.RegistryRow)]
        reservations = [
            row for row in section.rows if isinstance(row, ast.RegistryReservation)
        ]
        for code in _repeats(row.code for row in rows if row.code is not None):
            findings.append(
                Finding(
                    Severity.NOTE,
                    "registry-range-overlap",
                    f"{code} is allocated by {len(section.allocations(code))}"
                    f" rows of {where}",
                    section.source.section,
                )
            )
        for index, reservation in enumerate(reservations):
            for other in reservations[index + 1 :]:
                if reservation.first <= other.last and other.first <= reservation.last:
                    findings.append(
                        Finding(
                            Severity.NOTE,
                            "registry-range-overlap",
                            f"{_reservation_label(reservation)} overlaps"
                            f" {_reservation_label(other)} in {where}",
                            section.source.section,
                        )
                    )
            allocated = sorted(
                {
                    row.code
                    for row in rows
                    if row.code is not None and reservation.covers(row.code)
                }
            )
            if allocated:
                codes = ", ".join(map(str, allocated))
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "registry-range-overlap",
                        f"{_reservation_label(reservation)} covers"
                        f" {codes}, which {where} allocates",
                        section.source.section,
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
        *_duplicate_values(index),
        *_values_out_of_range(index),
        *_vendor_specific_overlaps(index),
        *_void_overlaps(index),
        *_applications_agree_with_headers(index),
        *_duplicate_identities(index, spec.vendor_id),
        *_rows_without_codes(index),
        *_table_agrees_with_definitions(index),
        *_tables_agree_with_each_other(index),
        *_vendor_id_agrees_with_header(index, spec.vendor_id),
        *_vendors_agree_with_flags(index),
        *_self_cited_exists(index),
        *_local_and_reused(index),
        *_members_marked_unused(spec),
        *_registry_overlaps(spec),
        *_undefined_avps(index),
        *_section_references(spec, index),
    ]
    return _ordered(findings)


def _ordered(findings: list[Finding]) -> list[Finding]:
    order = list(Severity)
    return sorted(findings, key=lambda f: (order.index(f.severity), f.rule))


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


def _cited(index: _Index) -> list[str]:
    """Every document the file names as an origin, by a re-used row or a
    re-print."""
    return sorted({*index.reused.values(), *(r.origin for r in index.reprints)})


def _resolve_origins(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
) -> tuple[dict[str, _Origin], list[Finding]]:
    """The origins the corpus resolves, and a `cross-release-origin` note
    for each it resolved outside `spec`'s release."""
    origins = {}
    crossings = []
    for origin in _cited(index):
        entry, across = books.resolution(origin, like=spec)
        if entry is None:
            continue
        origins[origin] = _Origin.of(entry.spec)
        if across is not None:
            crossings.append(_cross_release(spec, entry, across))
    return origins, crossings


def _cross_release(
    spec: ast.Specification, entry: corpus.Entry, across: corpus.CrossRelease
) -> Finding:
    """A re-used origin resolved outside the citing document's release, by
    the drafting rule `corpus.resolution` applied, so a reader can audit it:
    TS 32.299 V19.0.0's TS 29.140 is V7.0.0, the document's final version,
    TS 29.212's 3GPP2 X.S0057-B is revision 0 V2.0, standing in, and TS
    32.299 V11.20.0's TS 29.061 is V19.1.0, standing in for V11.12.0. A
    note: the rule is the corpus's reading of the citing document's
    references, and only its editor knows whether it meant that."""
    citing = spec.specification + (f" V{spec.version}" if spec.version else "")
    if across.rule == corpus.STAND_IN and across.meant is not None:
        release = corpus.RELEASE_STAND_INS[
            across.citing, spec.version or "", across.cited
        ]
        how = "by version, naming" if across.specific else "non-specifically, meaning"
        rule = (
            f"it cites the document {how} V{across.meant},"
            f" which the corpus lacks, and V{across.version} stands in:"
            f" {release.evidence} (corpus.RELEASE_STAND_INS)"
        )
    elif across.rule == corpus.STAND_IN:
        stand_in = corpus.STAND_INS[across.citing, across.cited]
        rule = (
            f"its references name revision {across.cited_revision}, which the"
            f" corpus lacks, and revision {across.revision} V{across.version}"
            f" stands in: {stand_in.evidence} (corpus.STAND_INS)"
        )
    elif across.rule == corpus.SPECIFIC:
        rule = (
            f"its references name V{across.version} (a specific reference;"
            " corpus.CITED_VERSIONS)"
        )
    elif across.rule == corpus.LATEST_EDITION:
        evidence = corpus.LATEST_EDITIONS[across.citing, across.cited]
        rule = (
            f"it cites the document non-specifically, which reads as its latest"
            f" edition, V{across.version} of the corpus's copies: {evidence}"
            " (corpus.LATEST_EDITIONS)"
        )
    else:
        rule = (
            f"it cites the document non-specifically, which reads as its"
            f" final version, V{across.version} (corpus.FINAL_VERSIONS)"
        )
    return Finding(
        Severity.NOTE,
        "cross-release-origin",
        f"{across.cited} is resolved across releases to {entry.path.name}:"
        f" {citing} is the citing file, and {rule}",
    )


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

    One note per file rather than per origin. A Rel-19 corpus without an RFC
    extractor cannot resolve a single RFC, and 29.272 alone cites eighteen
    origins — reported individually they would bury every real finding, and
    they all say the same thing.

    An origin outside 3GPP and IETF (ETSI, 3GPP2, OMA, oneM2M) gets a note of
    its own, `external-origin-not-in-corpus`: no 3GPP or IETF download
    closes the gap, only a hand-written file or a catalogued document an
    extractor reads (oneM2M TS-0004).
    """
    cited = _cited(index)
    missing: list[str] = []
    external: list[str] = []
    for origin in cited:
        if origin in origins:
            continue
        if ast.is_external(origin):
            external.append(origin)
            continue
        held = books.versions(origin)
        missing.append(f"{origin} (corpus has {', '.join(held)})" if held else origin)
    findings = []
    if missing:
        findings.append(
            Finding(
                Severity.NOTE,
                "origin-not-in-corpus",
                f"{len(missing)} of {len(cited)} cited origins"
                f" could not be resolved for a {spec.version or 'version-less'}"
                f" document, and the rules"
                f" needing them were skipped: {', '.join(missing)}",
            )
        )
    if external:
        findings.append(
            Finding(
                Severity.NOTE,
                "external-origin-not-in-corpus",
                f"{len(external)} of {len(cited)} cited origins are documents"
                " outside 3GPP and IETF that the corpus holds no copy of, and"
                f" the rules needing them were skipped: {', '.join(external)}",
            )
        )
    return findings


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
                    paths=tuple(index.reused_paths[name]),
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
    flag rule on purpose, and evidence either way: the message says which
    side the model follows, for the disputed flag the first of the citing
    file's rows placing it (`_followed_for_flag`; RFC 6733 sections 4.1 and
    4.5 leave flag rules to the application), the origin for the type
    unless this file defines the AVP itself. A
    re-used table's M-bit column is not compared: it states this
    interface's setting, which is what the column is for, and the model
    reads it so (`model.Model._own_m_bit`), below the citing file's rows.
    Codes are `reused-code-conflict`'s.

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
            for label, flag, compared in _row_comparisons(
                table, row, theirs, definition
            ):
                if not compared or any(mine == other for mine, other, _ in compared):
                    continue
                spelled = "; ".join(
                    f"{other} in {where}" for _, other, where in compared
                )
                if flag is not None:
                    followed = _followed_for_flag(ours[name], row, flag)
                elif label == "encrypt":
                    followed = "neither, carrying no encrypt rule"
                elif any(each.name == name for each in index.definitions):
                    followed = "this file's definition"
                else:
                    followed = origin
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "reused-row-mismatch",
                        f"{name} is tabulated with {label} {compared[0][0]} in"
                        f" {_table_labels([table])}, but {origin}, which it is"
                        f" re-used from, reads {spelled}; the model follows"
                        f" {followed}",
                        paths=(index.path(row),),
                    )
                )
    return findings


def _followed_for_flag(
    ours: list[tuple[ast.AvpTable, ast.AvpTableRow]],
    row: ast.AvpTableRow,
    flag: ast.AvpFlag,
) -> str:
    """The row the model reads `flag` of a re-used AVP from, as a
    `reused-row-mismatch` message names it, `row` being the reported one:
    the first of this file's rows placing the flag
    (`model.Model._own_flags`). `row` places it, being compared on it, so
    that is `row` or an earlier row, never a re-used row's M-bit or the
    origin, which rank below. A first row placing V alone says nothing of
    M, so a second row's M is what the model follows."""
    for table, each in ours:
        if each is row:
            return f"this row for {flag.value}"
        if _placement(table, each, flag) is not None:
            return f"an earlier row for {flag.value}, in {_table_labels([table])}"
    raise AssertionError(f"{row.name}'s row is not among its rows")


def _reused_row_vendors_agree_with_origin(
    index: _Index, own_vendor: int, origins: dict[str, _Origin]
) -> list[Finding]:
    """A row this file tabulates for an AVP it re-uses places it in the
    origin's vendor space.

    The row's vendor is the model's reading (`ast.AvpTableRow.stated_vendor`):
    its Vendor-ID cell where its table prints one, else IETF space for V
    under Must-not and the file's `; Vendor-ID:` for V under Must; a row
    stating none agrees with any. The origin's is its definition's header,
    no vendor-id being IETF space, or what its own rows state the same way
    in its file. TS 29.229's rows for RFC 4590's `Digest-*` AVPs put V under
    Must-not and agree with RFC 4590's vendor 0. Agreeing with any one origin
    reading agrees, as for `reused-row-mismatch`. An error, unlike that
    rule's notes: two vendors are two identities, so the row and its origin
    name two AVPs, as two codes do (`reused-code-conflict`).
    """
    findings = []
    for name, origin in sorted(index.reused.items()):
        resolved = origins.get(origin)
        if resolved is None:
            continue
        readings: list[tuple[int, str]] = []
        definition = resolved.defined.get(name)
        if definition is not None:
            readings.append(
                (
                    ast.IETF_VENDOR
                    if definition.vendor_id is None
                    else definition.vendor_id,
                    f"its clause {definition.source.section}",
                )
            )
        for table in resolved.tables:
            for their_row in table.rows:
                if their_row.name != name:
                    continue
                stated = their_row.stated_vendor(resolved.spec.vendor_id)
                if stated is not None:
                    readings.append((stated, _table_labels([table])))
        if not readings:
            continue
        for table in index.tables:
            for row in table.rows:
                if row.name != name:
                    continue
                mine = row.stated_vendor(own_vendor)
                if mine is None or any(mine == other for other, _ in readings):
                    continue
                spelled = "; ".join(
                    f"vendor {other} in {where}" for other, where in readings
                )
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "reused-row-vendor-mismatch",
                        f"{name} is tabulated in vendor {mine} in"
                        f" {_table_labels([table])}, but {origin}, which it is"
                        f" re-used from, reads {spelled}",
                        paths=(index.path(row),),
                    )
                )
    return findings


def _reused_cells_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """A re-used table's own Code and Type cells read the origin's way.

    TS 29.172 table 7.4.1-2 and TS 32.299's tables 7.3.1-7.5.1 print the
    code, 29.172 the type too, of the AVPs they take from elsewhere. The
    origin states both, in its definition or its table rows; a code it does
    not give is `reused-code-conflict`, an error like any second code, and a
    type it does not give is `reused-row-mismatch`. Only what the origin
    states is compared, and agreeing with any of its readings agrees.
    """
    findings = []
    for block, row in index.reused_cells:
        resolved = origins.get(row.origin)
        if resolved is None:
            continue
        definition = resolved.defined.get(row.name)
        theirs = [
            their_row
            for table in resolved.tables
            for their_row in table.rows
            if their_row.name == row.name
        ]
        codes = {their.code for their in theirs if their.code is not None}
        types = {their.data_type for their in theirs if their.data_type is not None}
        if definition is not None:
            codes.add(definition.code)
            if not types:
                types.add(
                    ast.DataType.GROUPED
                    if isinstance(definition, ast.GroupedAvp)
                    else ast.DataType.ENUMERATED
                )
        where = f"re-used table {block.table}"
        if row.code is not None and codes and row.code not in codes:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reused-code-conflict",
                    f"{row.name} is code {row.code} in {where} and"
                    f" {', '.join(map(str, sorted(codes)))} in {row.origin},"
                    " which it is re-used from",
                    block.source.section,
                    row.origin,
                )
            )
        if row.data_type is not None and types and row.data_type not in types:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "reused-row-mismatch",
                    f"{row.name} is typed {row.data_type.value} in {where}, but"
                    f" {row.origin}, which it is re-used from, reads"
                    f" {', '.join(sorted(each.value for each in types))};"
                    f" the model follows {row.origin}",
                    block.source.section,
                    row.origin,
                    paths=(index.path(row),),
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
) -> list[tuple[str, ast.AvpFlag | None, list[tuple[str, str, str]]]]:
    """Per reading, the (this row, origin row, where) pairs that both state,
    with the flag a flag rule's reading compares."""
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
        out.append((label, None, compared))
    for flag in _CROSS_FILE_FLAGS:
        mine = _placement(table, row, flag)
        compared = [
            (f"{flag.value} in {mine}", f"{flag.value} in {other}", _table_labels([t]))
            for t, their_row in theirs
            if mine is not None
            and (other := _placement(t, their_row, flag)) is not None
        ]
        out.append(("flag rule", flag, compared))
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
        findings.append(
            Finding(
                Severity.NOTE, rule, message, where, paths=(index.path(definition),)
            )
        )
    return findings


def _reprints_agree_with_origin(
    index: _Index, origins: dict[str, _Origin]
) -> list[Finding]:
    """What a `Reprinted AVP` block says against the document it names.

    A re-print defines nothing, so it never meets the duplicate rules: TS 29.109
    prints RFC 6733's `Vendor-Specific-Application-Id` three times. Its claim is
    that it copies the origin, and that is what is checked. An origin that has
    never heard of the name, or two codes for one AVP, is an error, as for a
    re-used row. A body naming other members is a note: only the origin's editor
    knows which copy is current. Occurrence qualifiers are not compared, since TS
    29.109 prints `0*1 { Auth-Application-Id }`, the form RFC 3588 used, for what
    RFC 6733 writes `[ Auth-Application-Id ]`.
    """
    findings = []
    for reprint in index.reprints:
        origin = reprint.origin
        resolved = origins.get(origin)
        if resolved is None:
            continue
        where = reprint.source.section
        theirs = resolved.defined.get(reprint.name)
        row = resolved.tabled.get(reprint.name)
        if theirs is None and row is None:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reprint-not-in-origin",
                    f"{reprint.name} is printed as {origin}'s, which does not"
                    " define it",
                    where,
                    origin,
                )
            )
            continue
        code = theirs.code if theirs is not None else row.code if row else None
        if code is not None and code != reprint.code:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "reused-code-conflict",
                    f"{reprint.name} is code {reprint.code} here and {code} in"
                    f" {origin}",
                    where,
                    origin,
                )
            )
            continue
        if not isinstance(theirs, ast.GroupedAvp):
            continue
        ours = {rule.name for rule in reprint.avps}
        base = {rule.name for rule in theirs.avps}
        if ours != base:
            added = ", ".join(sorted(ours - base)) or "nothing"
            dropped = ", ".join(sorted(base - ours)) or "nothing"
            findings.append(
                Finding(
                    Severity.NOTE,
                    "reprint-differs",
                    f"{reprint.name}'s body, against {origin}'s definition: adds"
                    f" {added}, missing {dropped}",
                    where,
                    origin,
                    paths=(index.path(reprint),),
                )
            )
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

    A name an `Undefined AVP` block declares is no unresolved reference:
    `undefined-avp` reports it, and here `undefined-avp-defined` reports a
    block whose name a base document resolves after all, the stale claim's
    cross-file form.

    An error: the corrected corpus resolves every reference or declares it
    undefined, so one that does neither is a defect wanting a correction (a
    block, a renamed member, a row or a `; Bases:` entry).
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
    local = set(known)
    for base in bases.values():
        known |= base.defined.keys() | base.tabled.keys() | base.reused.keys()
    declared = {block.name: block for block in index.undefined}
    stale = [
        Finding(
            Severity.ERROR,
            "undefined-avp-defined",
            f"{name} is declared undefined, but a base document resolves it",
            block.source.section,
            paths=(index.path(block),),
        )
        for name, block in sorted(declared.items())
        if name in known and name not in local
    ]
    return stale + [
        Finding(
            Severity.ERROR,
            "unresolved-reference",
            f"{name} is referenced in {_clauses(where)} but resolves to no"
            " local definition, table row, re-used entry or base document,"
            " and no Undefined AVP block declares it",
        )
        for name, where in sorted(_references(index).items())
        if name not in known and name not in declared
    ]


# --- registry rules -----------------------------------------------------------
#
# TS 29.230 allocates the 3GPP vendor's AVP codes, the command codes and the
# application ids, each to the documents defining it. The registry is
# evidence, not a definer: where a document and the registry disagree, the
# document's clause is the primary source, so these are notes, and a
# disagreement is corrected only where the defining clause itself supports
# the registry.

REGISTRY = "TS29.230"


@dataclass(frozen=True)
class _Registered:
    """One registry document's tables, indexed by kind."""

    vendor_id: int
    tables: dict[ast.RegistryKind, list[ast.Registry]]

    @classmethod
    def of(cls, spec: ast.Specification) -> _Registered:
        tables: dict[ast.RegistryKind, list[ast.Registry]] = defaultdict(list)
        for section in spec.sections:
            if isinstance(section, ast.Registry):
                tables[section.registry].append(section)
        return cls(spec.vendor_id, tables)

    def allocations(
        self, kind: ast.RegistryKind, code: int
    ) -> list[tuple[ast.Registry, ast.RegistryRow]]:
        return [
            (table, row)
            for table in self.tables.get(kind, ())
            for row in table.allocations(code)
        ]

    def reservations(
        self, kind: ast.RegistryKind, code: int
    ) -> list[tuple[ast.Registry, ast.RegistryReservation]]:
        return [
            (table, row)
            for table in self.tables.get(kind, ())
            for row in table.reservations(code)
        ]


def _tables(found: Sequence[tuple[ast.Registry, object]]) -> str:
    labels = list(dict.fromkeys(table.table for table, _ in found))
    return f"table{'s' if len(labels) > 1 else ''} {', '.join(labels)}"


def _allocated_to(found: list[tuple[ast.Registry, ast.RegistryRow]]) -> str:
    return " and ".join(dict.fromkeys(row.name or "nothing" for _, row in found))


def _documents_of(found: list[tuple[ast.Registry, ast.RegistryRow]]) -> list[str]:
    return list(dict.fromkeys(doc for _, row in found for doc in row.defined_in))


def _own_avps(
    spec: ast.Specification, index: _Index
) -> dict[tuple[str, int], tuple[int, str]]:
    """The AVPs a file defines or tabulates as its own, by name and code,
    with their vendor and the clause first stating them. A name the file
    lists as re-used is its origin's to answer for."""
    own: dict[tuple[str, int], tuple[int, str]] = {}
    for definition in index.definitions:
        if definition.name not in index.reused:
            vendor = (
                ast.IETF_VENDOR
                if definition.vendor_id is None
                else definition.vendor_id
            )
            own.setdefault(
                (definition.name, definition.code), (vendor, definition.source.section)
            )
    for table in index.tables:
        for row in table.rows:
            if row.code is None or row.name in index.reused:
                continue
            vendor = row.stated_vendor(spec.vendor_id)
            own.setdefault(
                (row.name, row.code),
                (spec.vendor_id if vendor is None else vendor, table.source.section),
            )
    return own


def _registry_avps(
    spec: ast.Specification, index: _Index, registry: _Registered, own_reference: str
) -> list[Finding]:
    """Every AVP the file defines in the registry's vendor space against the
    registry's AVP codes: the name a row allocates its code to, the documents
    it cites, and, for a code no row allocates, the range reserving it.

    A name compared exactly, since a dictionary keys on it: TS 29.230 table
    7.1 allocates 829 to `Role-of-Node`, which TS 32.299 defines as
    `Role-Of-Node`. A row citing no document (table 7.1's 1530-1542 in TS
    29.273's block) claims none. A code inside a reservation is reported
    only where no reservation covering it names the file's document, so TS
    29.061's RADIUS-compatible 1-33 sit in "backwards compatibility with
    3GPP RADIUS Vendor Specific Attributes (See 3GPP TS 29.061 [13], ...)"
    silently.
    """
    kind = ast.RegistryKind.AVP_CODES
    findings = []
    for (name, code), (vendor, section) in sorted(_own_avps(spec, index).items()):
        if vendor != registry.vendor_id:
            continue
        found = registry.allocations(kind, code)
        if not found:
            covering = registry.reservations(kind, code)
            if covering and not any(
                own_reference in reservation.defined_in
                or own_reference.removeprefix("TS") in (reservation.purpose or "")
                for _, reservation in covering
            ):
                reserved = " and ".join(
                    _reservation_label(reservation) for _, reservation in covering
                )
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "registry-reserved-code",
                        f"{name} has code {code}, which {REGISTRY}"
                        f" {_tables(covering)} does not allocate but reserves:"
                        f" {reserved}",
                        section,
                        origin=REGISTRY,
                    )
                )
            continue
        names = [row.name for _, row in found if row.name is not None]
        if names and name not in names:
            case = (
                ", differing only in case"
                if name.lower() in (each.lower() for each in names)
                else ""
            )
            findings.append(
                Finding(
                    Severity.NOTE,
                    "registry-avp-name",
                    f"{name} has code {code}, which {REGISTRY} {_tables(found)}"
                    f" allocates to {_allocated_to(found)}{case}",
                    section,
                    origin=REGISTRY,
                )
            )
        documents = _documents_of(found)
        if documents and own_reference not in documents:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "registry-avp-document",
                    f"{name} (code {code}) is defined here, but {REGISTRY}"
                    f" {_tables(found)} allocates the code to"
                    f" {', '.join(documents)}",
                    section,
                    origin=REGISTRY,
                )
            )
    return findings


def _registry_result_codes(
    spec: ast.Specification, index: _Index, registry: _Registered, own_reference: str
) -> list[Finding]:
    """Every experimental result code the file lists in the registry's vendor
    space against the registry's rows: the name a row gives it and the documents
    it cites. A plain Result-Code is the IETF's, which table 8.1 does not hold,
    and a code no row allocates is left alone: TS 29.230 lists a document's code
    from whichever version allocated it, so its absence says little."""
    if spec.vendor_id != registry.vendor_id:
        return []
    kind = ast.RegistryKind.RESULT_CODES
    findings = []
    for table in index.value_tables:
        if (
            table.kind is not ast.ValueKind.RESULT_CODES
            or table.avp != "Experimental-Result-Code"
        ):
            continue
        for row in table.rows:
            found = registry.allocations(kind, row.value)
            clause = row.section or table.source.section
            names = [each.name for _, each in found if each.name is not None]
            if names and row.name not in names:
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "registry-result-code-name",
                        f"{row.name} has code {row.value}, which {REGISTRY}"
                        f" {_tables(found)} allocates to {_allocated_to(found)}",
                        clause,
                        origin=REGISTRY,
                        paths=(index.path(row),),
                    )
                )
            documents = _documents_of(found)
            if documents and own_reference not in documents:
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "registry-result-code-document",
                        f"{row.name} (code {row.value}) is listed here, but"
                        f" {REGISTRY} {_tables(found)} allocates the code to"
                        f" {', '.join(documents)}",
                        clause,
                        origin=REGISTRY,
                        paths=(index.path(row),),
                    )
                )
    return findings


def _command_names(name: str | None) -> set[str]:
    """The two names a registry's command row gives: table 5.1/1 writes
    `User-Authorization-Request/-Answer`, table 5.1/4
    `Provide-Location-Request/Answer`."""
    if name is None:
        return set()
    request, _, answer = name.partition("/")
    names = {request}
    if answer and request.endswith("Request"):
        names.add(request.removesuffix("Request") + answer.removeprefix("-"))
    return names


def _registry_commands(index: _Index, registry: _Registered) -> list[Finding]:
    """A command whose code the registry allocates under another name.

    The registry's row names the request and answer pair and both
    abbreviations; agreeing with either name or either abbreviation agrees.
    TS 29.215 names command 8388656 `TE-Request`, which table 5.1/4 calls
    `Trigger-Establishment-Request/Answer`, `TER/TEA`. The defining documents
    are not compared: a command code is the application's to re-use, and TS
    29.273's SWx commands are TS 29.229's Cx codes.
    """
    kind = ast.RegistryKind.COMMAND_CODES
    findings = []
    seen: set[tuple[str, int]] = set()
    for message in index.messages:
        key = (message.name, message.command_code)
        found = registry.allocations(kind, message.command_code)
        if not found or key in seen:
            continue
        seen.add(key)
        names = set().union(*(_command_names(row.name) for _, row in found))
        abbreviations = {
            each for _, row in found for each in (row.abbreviation or "").split("/")
        }
        if not names and not abbreviations - {""}:
            continue
        if message.name in names or message.abbreviation in abbreviations:
            continue
        registered = " and ".join(
            dict.fromkeys(
                f"{row.name} ({row.abbreviation})"
                if row.abbreviation
                else str(row.name)
                for _, row in found
            )
        )
        findings.append(
            Finding(
                Severity.NOTE,
                "registry-command-name",
                f"{message.name} ({message.abbreviation}) has command code"
                f" {message.command_code}, which {REGISTRY} {_tables(found)}"
                f" allocates to {registered}",
                message.source.section,
                origin=REGISTRY,
            )
        )
    return findings


def _registry_applications(
    index: _Index, registry: _Registered, own_reference: str
) -> list[Finding]:
    """An application id the file uses that the registry allocates to other
    documents, or, where an application scope names it, under another name.

    Table 4.1 names every application "3GPP" and its interface ("3GPP Gx"),
    so a scope's name is compared with the registry's less that prefix. An
    id the registry does not allocate is not reported: the IETF's are
    IANA's, and TS 29.230 lists only 3GPP's.
    """
    kind = ast.RegistryKind.APPLICATION_IDS
    # Per id, where the file uses it: each scope naming it, then the first
    # header printing it. Every scope's name is compared, since two scopes
    # may give one id two names.
    used: dict[int, dict[str | None, str]] = defaultdict(dict)
    for block in index.applications:
        used[block.application_id].setdefault(block.name, block.source.section)
    for message in index.messages:
        if message.application_id is not None:
            used[message.application_id].setdefault(None, message.source.section)
    findings = []
    for application_id, uses in sorted(used.items()):
        found = registry.allocations(kind, application_id)
        if not found:
            continue
        first, section = next(iter(uses.items()))
        subject = first or f"Application {application_id}"
        documents = _documents_of(found)
        if documents and own_reference not in documents:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "registry-application-document",
                    f"{subject} uses application {application_id}, which"
                    f" {REGISTRY} {_tables(found)} allocates to"
                    f" {_allocated_to(found)} in {', '.join(documents)}",
                    section,
                    origin=REGISTRY,
                )
            )
        names = [row.name.removeprefix("3GPP ") for _, row in found if row.name]
        for name, section in uses.items():
            if name is None or not names or name in names:
                continue
            findings.append(
                Finding(
                    Severity.NOTE,
                    "registry-application-name",
                    f"{name} has application {application_id}, which"
                    f" {REGISTRY} {_tables(found)} allocates to"
                    f" {_allocated_to(found)}",
                    section,
                    origin=REGISTRY,
                )
            )
    return findings


def _against_registry(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
) -> list[Finding]:
    """The registry rules, against the TS 29.230 the corpus resolves for
    `spec`; none when it holds no copy, or when `spec` is the registry."""
    try:
        own = ast.spec_ref(spec.specification)
    except ast.SpecRefError:
        return []
    entry = books.resolve(REGISTRY, like=spec)
    if entry is None or own == REGISTRY:
        return []
    registry = _Registered.of(entry.spec)
    return [
        *_registry_avps(spec, index, registry, own),
        *_registry_commands(index, registry),
        *_registry_applications(index, registry, own),
        *_registry_result_codes(spec, index, registry, own),
    ]


def lint_with_corpus(
    spec: ast.Specification,
    books: corpus.Corpus,
    acceptances: Sequence[corrections.Accept] = (),
) -> list[Finding]:
    """Every finding for `spec`, single-file and cross-file together, with
    the notes `acceptances` acknowledge reported as accepted (`accept`).

    The single-file rules that a second document supersedes are dropped rather
    than reported alongside their own answers: `local-and-reused` becomes
    `reused-reprint` or `reused-body-differs`, and `duplicate-identity` is
    re-run with re-used rows resolved into their origins' vendor spaces. A row
    whose origin is missing from the corpus keeps the single-file behaviour,
    which is why the superseded findings are filtered by what actually
    resolved.
    """
    index = _index(spec)
    origins, crossings = _resolve_origins(spec, index, books)
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
        *crossings,
        *_unresolved_origins(spec, index, origins, books),
        *_reused_avp_exists(index, origins),
        *_reprint_or_extension(index, origins),
        *_reprints_agree_with_origin(index, origins),
        *_reused_rows_agree_with_origin(index, origins),
        *_reused_row_vendors_agree_with_origin(index, spec.vendor_id, origins),
        *_reused_cells_agree_with_origin(index, origins),
        *_duplicate_identities(index, spec.vendor_id, reused_vendor),
        *_unresolved_references(index, bases, missing_bases),
        *_against_registry(spec, index, books),
    ]
    return accept(spec, _ordered(findings), acceptances)


def lint_record(books: corpus.Corpus) -> list[Finding]:
    """What the corpus's record of known holes says against the corpus, read as
    a default `model.Model.build` holds it to the record, policy aside: a hole
    no entry lists as it is, and an entry naming no hole. One finding per
    corpus, not per file. Silent for a corpus with no record, as the registry
    rules are for one with no registry; the model refuses that corpus's holes
    itself."""
    if books.record is None:
        return []
    built = model.Model.build(books, strict=False)
    known = {(entry.document, entry.name): entry for entry in books.record.holes}
    findings = []
    for hole in built.unrecorded_holes():
        entry = known.get((hole.document, hole.name))
        findings.append(
            Finding(
                Severity.ERROR,
                "unrecorded-hole",
                f"{hole}, which the record does not list"
                if entry is None
                else f"{hole}, which the record lists missing"
                f" {', '.join(entry.missing)}",
                section=hole.section,
            )
        )
    findings += [
        Finding(
            Severity.ERROR,
            "stale-hole-record",
            f"{entry.document} {entry.name} is recorded missing"
            f" {', '.join(entry.missing)}, but the corpus has no such hole: its"
            " entry belongs out of the record",
        )
        for entry in built.stale_record_entries()
    ]
    return findings


# --- acceptances ------------------------------------------------------------


def accept(
    spec: ast.Specification,
    findings: list[Finding],
    acceptances: Sequence[corrections.Accept],
) -> list[Finding]:
    """`findings` with each note an acceptance matches reported as accepted.

    An acceptance names a rule, the node the finding is about and the
    finding's message, exactly; it matches when its target selects one node
    in `spec` and one finding of that rule about that node, its tree path
    among the finding's `paths`, reads `expect`. Two definitions of one name
    are two nodes: accepting clause 6.3.1's body says nothing of 6.3.2's. A
    note so matched becomes `ACCEPTED`, citing the acceptance; a second
    acceptance of it finds it accepted. Anything else is a
    `stale-acceptance` error: the document has changed what it says,
    and the acknowledgement no longer describes it. An error is never
    accepted, since it is the file asserting two things that cannot both be
    true.
    """
    out = list(findings)
    for acceptance in acceptances:
        problem, at = _accepted_at(spec, out, acceptance)
        if problem is None:
            out[at] = dataclasses.replace(
                out[at], severity=Severity.ACCEPTED, accepted_by=acceptance.cited
            )
            continue
        out.append(
            Finding(
                Severity.ERROR,
                "stale-acceptance",
                f"{acceptance.cited} accepts [{acceptance.rule}] for"
                f" {acceptance.target.describe()}, but {problem}",
            )
        )
    return _ordered(out)


def _accepted_at(
    spec: ast.Specification, findings: list[Finding], acceptance: corrections.Accept
) -> tuple[str | None, int]:
    """The index of the finding `acceptance` matches, or why it matches none."""
    located = list(acceptance.target.locate(spec))
    if len(located) != 1:
        return f"its target matches {len(located)} nodes", -1
    path = located[0][0]
    about = [
        index
        for index, finding in enumerate(findings)
        if finding.rule == acceptance.rule and path in finding.paths
    ]
    matching = [
        index for index in about if findings[index].message == acceptance.expect
    ]
    if len(matching) > 1:
        return f"{len(matching)} findings read as expected", -1
    if not matching:
        now = "; ".join(repr(findings[index].message) for index in about)
        return "no finding about it reads as expected" + (
            f"; it now reads {now}" if now else ""
        ), -1
    if findings[matching[0]].severity is not Severity.NOTE:
        return f"the finding is {findings[matching[0]].severity.value}", -1
    return None, matching[0]
