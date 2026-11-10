"""The registry rules, single-file and against the corpus's TS 29.230.

TS 29.230 allocates the 3GPP vendor's AVP codes, the command codes and the
application ids, each to the documents defining it. The registry is
evidence, not a definer: where a document and the registry disagree, the
document's clause is the primary source, so these are notes, and a
disagreement is corrected only where the defining clause itself supports
the registry.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .. import corpus
from ..dad import ast
from ._findings import Finding, Severity
from ._index import _Index, _repeats

REGISTRY = "TS29.230"


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
    from whichever version allocated it, so its absence says little. A code
    whose text names the document defining it claims no allocation: its origin
    answers for it (`_result_codes_agree_with_origin`)."""
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
            if documents and own_reference not in documents and row.origin is None:
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
