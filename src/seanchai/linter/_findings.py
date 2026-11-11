"""Findings, their report order, and acceptances."""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Sequence
from dataclasses import dataclass

from ..dad import ast, corrections


@dataclass(frozen=True)
class AvpIdentity:
    """The `(vendor-id, code)` pair that identifies an AVP."""

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
    # The origin document the finding is about, if any. `lint_with_corpus`
    # reads it to decide what a resolved origin supersedes.
    origin: str | None = None
    # The acceptance a note was accepted by, as a corrected file cites it
    # (`TS29.336.py#serving-node-t4-body`).
    accepted_by: str | None = None
    # Tree paths of the nodes the finding is about, as correction selectors
    # locate them. An acceptance's target must select one of them; a finding
    # with none cannot be accepted.
    paths: tuple[ast.TreePath, ...] = ()

    def __str__(self) -> str:
        where = f" (clause {self.section})" if self.section else ""
        by = f" ({self.accepted_by})" if self.accepted_by else ""
        return f"{self.severity.value}: [{self.rule}] {self.message}{where}{by}"


def _ordered(findings: list[Finding]) -> list[Finding]:
    order = list(Severity)
    return sorted(findings, key=lambda f: (order.index(f.severity), f.rule))


# --- acceptances ------------------------------------------------------------


def accept(
    spec: ast.Specification,
    findings: list[Finding],
    acceptances: Sequence[corrections.Accept],
) -> list[Finding]:
    """Return `findings` with each note an acceptance matches marked accepted.

    An acceptance matches when its target selects exactly one node in `spec`
    and exactly one finding of its rule, with that node's path in the
    finding's `paths`, has the message `expect`. Two definitions of one name
    are two nodes. Any acceptance that does not match a note adds a
    `stale-acceptance` error.
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
