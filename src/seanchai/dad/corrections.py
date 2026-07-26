"""Output corrections: typed find/replace on a parsed `.dad` tree.

The second of the two patch layers (see docs/proposal-corrections.md). Input
patches fix source typos that would break extraction; corrections fix data that
extracts and parses perfectly well but is *wrong* — an AVP code the spec's own
table misprints, a clause reference pointing at the wrong section, an
application id the header omits.

The two layers are the same operation at different altitudes: input patches are
find/replace on text, corrections are find/replace on typed fields. That is why
`expect` is mandatory here as well. A correction that no longer matches has
either been fixed upstream or been broken by a re-extraction, and both are
events worth failing on rather than silently skipping.

Corrections are declared per specification, as data:

    CORRECTIONS = [
        Correction(
            target=table_row("MME-Location-Information"),
            field="code",
            expect=1600,
            replace=1602,
            reason="table 7.3.1/1 prints the Trace-Data code by mistake",
            versions="18.6.0",
        ),
    ]

Applying is deterministic but deliberately not idempotent: feeding corrected
output back in makes every `expect` fail, because treating an already-applied
correction as a no-op would make "already corrected" indistinguishable from
"fixed upstream".
"""

import importlib.util
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydantic

from . import ast


class CorrectionError(ValueError):
    pass


@dataclass(frozen=True)
class Selector:
    """Base for the ways a correction names its target. Subclasses yield the
    nodes they match, in document order, from a whole specification.

    The subclasses are deliberately lower-case: a corrections file is data, and
    `table_row("MME-Location-Information")` reads as such where
    `TableRow(...)` would read as machinery.
    """

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class definition(Selector):
    """A message, grouped AVP or enumerated AVP, by name. `application_id`
    narrows the TS 29.272 case of one command defined for two applications."""

    name: str
    application_id: int | None = None

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if not isinstance(
                section, ast.Message | ast.GroupedAvp | ast.EnumeratedAvp
            ):
                continue
            if section.name != self.name:
                continue
            if self.application_id is not None and (
                not isinstance(section, ast.Message)
                or section.application_id != self.application_id
            ):
                continue
            yield section

    def describe(self) -> str:
        if self.application_id is None:
            return f"definition {self.name!r}"
        return f"definition {self.name!r} (application {self.application_id})"


@dataclass(frozen=True)
class table_row(Selector):
    """One row of an AVP table, by AVP name."""

    name: str

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if isinstance(section, ast.AvpTable):
                yield from (row for row in section.rows if row.name == self.name)

    def describe(self) -> str:
        return f"AVP table row {self.name!r}"


@dataclass(frozen=True)
class reused_row(Selector):
    """One row of the re-used AVPs table, by AVP name."""

    name: str

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if isinstance(section, ast.ReusedAvps):
                yield from (row for row in section.rows if row.name == self.name)

    def describe(self) -> str:
        return f"re-used AVPs row {self.name!r}"


@dataclass(frozen=True)
class enum_value(Selector):
    """One named value of an enumerated AVP."""

    avp: str
    name: str

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if isinstance(section, ast.EnumeratedAvp) and section.name == self.avp:
                yield from (
                    value
                    for value in section.values
                    if isinstance(value, ast.EnumValue) and value.name == self.name
                )

    def describe(self) -> str:
        return f"value {self.name!r} of {self.avp!r}"


@dataclass(frozen=True)
class avp_rule(Selector):
    """One AVP reference inside a message or grouped-AVP body."""

    parent: str
    name: str

    def find(self, spec: ast.Specification) -> Iterator[ast.Node]:
        for section in spec.sections:
            if not isinstance(section, ast.Message | ast.GroupedAvp):
                continue
            if section.name != self.parent:
                continue
            yield from (rule for rule in section.avps if rule.name == self.name)

    def describe(self) -> str:
        return f"AVP rule {self.name!r} in {self.parent!r}"


@dataclass(frozen=True)
class Correction:
    """One field of one node, with the value it is expected to hold.

    `versions` is advisory, exactly as for input patches: it records where the
    correction is known to be needed and sharpens the message, and never gates
    whether the correction is applied. Gating would silently ship an
    uncorrected file the first time a version moved.
    """

    target: Selector
    field: str
    expect: Any
    replace: Any
    reason: str
    versions: str | None = None

    def __post_init__(self) -> None:
        if self.expect == self.replace:
            raise CorrectionError(
                f"{self.target.describe()}: {self.field} correction replaces"
                " a value with itself"
            )


@dataclass
class Result:
    """What `apply()` did, one entry per correction, in declaration order."""

    correction: Correction
    node: str
    old: Any
    new: Any


def _corrected(node: ast.Node, correction: Correction) -> ast.Node:
    """Rebuild one node with the field replaced, through validation.

    `model_copy(update=...)` would not validate the new value, so a correction
    could write a code of `"oops"` into a tree that only fails much later.
    """
    if correction.field not in type(node).model_fields:
        raise CorrectionError(
            f"{correction.target.describe()}: {type(node).__name__} has no field"
            f" {correction.field!r}"
        )
    found = getattr(node, correction.field)
    if found != correction.expect:
        raise CorrectionError(
            f"{correction.target.describe()}: expected {correction.field}"
            f"={correction.expect!r}, found {found!r}"
        )
    values = {name: getattr(node, name) for name in type(node).model_fields}
    values[correction.field] = correction.replace
    try:
        return type(node)(**values)
    except pydantic.ValidationError as error:
        raise CorrectionError(
            f"{correction.target.describe()}: {correction.field}"
            f"={correction.replace!r} is not valid: {error.errors()[0]['msg']}"
        ) from None


def _resolve(spec: ast.Specification, correction: Correction) -> ast.Node:
    found = list(correction.target.find(spec))
    if not found:
        raise CorrectionError(f"{correction.target.describe()}: no match")
    if len(found) > 1:
        raise CorrectionError(
            f"{correction.target.describe()}: {len(found)} matches, narrow the selector"
        )
    return found[0]


def _replaced(node: Any, edits: dict[int, ast.Node]) -> Any:
    """Rebuild the tree, swapping in every corrected node by identity."""
    if isinstance(node, ast.Node):
        replacement = edits.get(id(node))
        if replacement is not None:
            return replacement
        values = {
            name: _replaced(getattr(node, name), edits)
            for name in type(node).model_fields
        }
        return type(node).model_construct(**values)
    if isinstance(node, tuple):
        return tuple(_replaced(item, edits) for item in node)
    return node


def apply(
    spec: ast.Specification, corrections: list[Correction]
) -> tuple[ast.Specification, list[Result]]:
    """Apply every correction, or none of them.

    Each correction is resolved and checked against the original tree before
    anything is rebuilt, so a failing correction cannot leave a half-corrected
    file behind.
    """
    edits: dict[int, ast.Node] = {}
    claimed: set[tuple[int, str]] = set()
    results = []
    for correction in corrections:
        node = _resolve(spec, correction)
        claim = (id(node), correction.field)
        if claim in claimed:
            raise CorrectionError(
                f"{correction.target.describe()}: {correction.field} is corrected"
                " more than once; combine the corrections"
            )
        claimed.add(claim)
        # Chain onto an earlier correction of the same node, so two fields of
        # one row can be corrected independently.
        corrected = _corrected(edits.get(id(node), node), correction)
        results.append(
            Result(
                correction=correction,
                node=correction.target.describe(),
                old=getattr(node, correction.field),
                new=correction.replace,
            )
        )
        edits[id(node)] = corrected
    return _replaced(spec, edits), results


def load(directory: Path | None, specification: str) -> list[Correction]:
    """Read `<directory>/<SpecRef>.py` and return its `CORRECTIONS` list.

    The file name is derived from the specification, so a corrections file
    cannot be applied to the wrong document. Importing it executes Python from
    `directory`, which is why the CLI requires the path to be given explicitly
    rather than discovering it.
    """
    if directory is None:
        return []
    path = directory / f"{ast.spec_ref(specification)}.py"
    if not path.is_file():
        return []
    module_spec = importlib.util.spec_from_file_location(path.stem, path)
    if module_spec is None or module_spec.loader is None:
        raise CorrectionError(f"cannot load corrections from {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    corrections = getattr(module, "CORRECTIONS", None)
    if corrections is None:
        raise CorrectionError(f"{path} defines no CORRECTIONS list")
    if not all(isinstance(item, Correction) for item in corrections):
        raise CorrectionError(f"{path}: CORRECTIONS must hold Correction objects")
    return list(corrections)
