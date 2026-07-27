"""Structural rules over one parsed `.dad` file.

The extractor records what a specification says, including where it
contradicts itself; this is the layer that reports those contradictions
instead of resolving them. Every rule here is decided inside a single file,
and every one of them has a real case in the committed corpus — they are not
hypothetical invariants, they are the inconsistencies three specifications
actually contain.

Findings carry a severity because not every one of them is a defect:

- `ERROR` — the file asserts two things that cannot both be true, whoever is
  at fault. Two AVPs with one identity; a table row disagreeing with the
  definition it points at.
- `NOTE` — something worth knowing that a single file cannot judge. An AVP
  both defined locally and listed as re-used is the case that forced the
  distinction: a specification may re-print another's AVP for convenience or
  *extend* it with new fields, and deciding which needs the origin document.

An AVP's identity is `(vendor-id, code)`, and the vendor half comes from the
file's own `; Vendor-ID:` directive. An AVP the file merely re-uses belongs to the
origin's vendor space, which only the origin document states, so those rows are
left to the cross-document rules rather than guessed at here.

Findings are anchored by clause and name rather than by line number. The AST
carries no line information, and a clause reference survives reformatting and
points at the same place in the specification as in the `.dad` file — which is
where the reader has to go anyway.
"""

from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass, field

from . import corpus
from .dad import ast


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

    def __str__(self) -> str:
        where = f" (clause {self.section})" if self.section else ""
        return f"{self.severity.value}: [{self.rule}] {self.message}{where}"


@dataclass
class _Index:
    """The one pass over the file that every rule reads from."""

    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp] = field(default_factory=list)
    messages: list[ast.Message] = field(default_factory=list)
    tables: list[ast.AvpTable] = field(default_factory=list)
    reused: dict[str, str] = field(default_factory=dict)  # AVP name -> origin

    @property
    def rows(self) -> list[ast.AvpTableRow]:
        return [row for table in self.tables for row in table.rows]


def _index(spec: ast.Specification) -> _Index:
    index = _Index()
    for section in spec.sections:
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
            index.definitions.append(section)
        elif isinstance(section, ast.Message):
            index.messages.append(section)
        elif isinstance(section, ast.AvpTable):
            index.tables.append(section)
        elif isinstance(section, ast.ReusedAvps):
            for row in section.rows:
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


def _repeats[T](items) -> list[T]:
    seen: dict[T, int] = defaultdict(int)
    for item in items:
        seen[item] += 1
    return [item for item, count in seen.items() if count > 1]


def _duplicate_identities(index: _Index, own_vendor: int) -> list[Finding]:
    """No two AVPs share a `(vendor-id, code)`.

    Not the same rule as "no duplicate names": TS 29.272's `Area-Scope` was
    printed with `Job-Type`'s code, so two differently-named AVPs had one
    identity while every name in the file stayed unique.
    """
    holders: dict[AvpIdentity, list[str]] = defaultdict(list)
    for definition in index.definitions:
        identity = _identity(definition.code, definition.vendor_id)
        holders[identity].append(
            f"{definition.name} (clause {definition.source.section})"
        )
    for row in index.rows:
        if row.code is None:
            continue
        if row.name in index.reused:
            # A re-used AVP belongs to the origin's vendor space, which is that
            # document's `; Vendor-ID:` to state — not this file's to guess. Two
            # AVPs numbered 621 in TS 29.229 are 3GPP's and RFC 7683's, and a
            # comparison that assumed one space would call them a collision.
            # Resolving these is the cross-document rules' job.
            continue
        identity = AvpIdentity(own_vendor, row.code)
        # A row whose own definition is in this file is the same AVP, not a
        # second claimant.
        if any(name.startswith(f"{row.name} (") for name in holders[identity]):
            continue
        holders[identity].append(f"{row.name} (AVP table)")

    findings = []
    for identity, names in sorted(holders.items(), key=lambda item: item[0].code):
        if len(names) > 1:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "duplicate-identity",
                    f"{identity} is claimed by {len(names)} AVPs: {', '.join(names)}",
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
        *_duplicate_identities(index, spec.vendor_id),
        *_table_agrees_with_definitions(index),
        *_vendor_id_agrees_with_header(index, spec.vendor_id),
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


def _defined_in(entry: corpus.Entry) -> dict[str, ast.GroupedAvp | ast.EnumeratedAvp]:
    index = _index(entry.spec)
    return {definition.name: definition for definition in index.definitions}


def _tabled_in(entry: corpus.Entry) -> dict[str, ast.AvpTableRow]:
    return {row.name: row for row in _index(entry.spec).rows}


def _unresolved_origins(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
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
        if books.resolve(origin, like=spec) is not None:
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
            f" could not be resolved for a {spec.version} document, and the rules"
            f" needing them were skipped: {', '.join(missing)}",
        )
    ]


def _reused_avp_exists(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
) -> list[Finding]:
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
        entry = books.resolve(origin, like=spec)
        if entry is None:
            continue
        if name in _defined_in(entry) or name in _tabled_in(entry):
            continue
        theirs = _index(entry.spec).reused.get(name)
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
        findings.append(
            Finding(
                Severity.ERROR,
                "reused-avp-not-in-origin",
                f"{name} is listed as re-used from {origin}, but"
                f" {entry.spec.specification} {entry.spec.version} neither"
                f" defines, tabulates nor re-uses it",
            )
        )
    return findings


def _reprint_or_extension(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
) -> list[Finding]:
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
        entry = books.resolve(origin, like=spec)
        if entry is None:
            continue
        theirs = _defined_in(entry).get(definition.name)
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


def _reused_identities(
    spec: ast.Specification, index: _Index, books: corpus.Corpus
) -> list[Finding]:
    """Two AVPs in one file claiming one `(vendor-id, code)`, re-used rows
    included.

    The single-file rule skips re-used rows on purpose: their vendor space is
    the origin's to state, and TS 29.229's two 621s are 3GPP's and RFC 7683's.
    Once the origins are readable that objection is gone, and the check can be
    made over every row in the file rather than the local ones only.
    """
    holders: dict[AvpIdentity, list[str]] = defaultdict(list)
    for definition in index.definitions:
        holders[_identity(definition.code, definition.vendor_id)].append(
            f"{definition.name} (clause {definition.source.section})"
        )
    for row in index.rows:
        if row.code is None:
            continue
        origin = index.reused.get(row.name)
        if origin is None:
            identity = AvpIdentity(spec.vendor_id, row.code)
        else:
            entry = books.resolve(origin, like=spec)
            if entry is None:
                continue
            identity = AvpIdentity(entry.spec.vendor_id, row.code)
        claim = f"{row.name} (AVP table"
        claim += f", re-used from {origin})" if origin else ")"
        if any(name.startswith(f"{row.name} (") for name in holders[identity]):
            continue
        holders[identity].append(claim)

    findings = []
    for identity, names in sorted(holders.items(), key=lambda item: item[0].code):
        if len(names) > 1:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "duplicate-identity",
                    f"{identity} is claimed by {len(names)} AVPs: {', '.join(names)}",
                )
            )
    return findings


def lint_with_corpus(spec: ast.Specification, books: corpus.Corpus) -> list[Finding]:
    """Every finding for `spec`, single-file and cross-file together.

    The single-file rules that a second document supersedes are dropped rather
    than reported alongside their own answers: `local-and-reused` becomes
    `reused-reprint` or `reused-definition-conflict`, and `duplicate-identity`
    is re-run over re-used rows too. A row whose origin is missing from the
    corpus keeps the single-file behaviour, which is why the superseded
    findings are filtered by what actually resolved.
    """
    index = _index(spec)
    resolved = {
        origin
        for origin in set(index.reused.values())
        if books.resolve(origin, like=spec) is not None
    }
    superseded = {"local-and-reused", "duplicate-identity"}
    findings = [
        finding
        for finding in lint(spec)
        if finding.rule not in superseded
        or (finding.rule == "local-and-reused" and _origin_of(finding) not in resolved)
    ]
    findings += [
        *_unresolved_origins(spec, index, books),
        *_reused_avp_exists(spec, index, books),
        *_reprint_or_extension(spec, index, books),
        *_reused_identities(spec, index, books),
    ]
    return _ordered(findings)


def _origin_of(finding: Finding) -> str:
    """The origin a `local-and-reused` note names, read back out of its own
    message — the notes are built one per origin, so this stays exact."""
    return finding.message.rsplit(" ", 1)[-1]
