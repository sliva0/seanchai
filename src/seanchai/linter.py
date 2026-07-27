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
        *_duplicate_enum_values(index),
        *_duplicate_identities(index, spec.vendor_id),
        *_table_agrees_with_definitions(index),
        *_local_and_reused(index),
    ]
    return sorted(findings, key=lambda f: (f.severity != Severity.ERROR, f.rule))
