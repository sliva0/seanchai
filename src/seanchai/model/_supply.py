"""`supplied_from`: the definitions a consumer's hand-authored `.dad`
sidecars supply for undefined names (`UndefinedPolicy.SUPPLY`)."""

from __future__ import annotations

from pathlib import Path

from ..dad import ast, parser
from ._errors import ModelError
from ._flags import _stated
from ._types import Supplied


def supplied_from(*paths: Path) -> dict[str, Supplied]:
    """The definitions hand-authored `.dad` sidecars supply, by name, for
    `Model.build(..., undefined=UndefinedPolicy.SUPPLY, supply=...)`.

    A sidecar is an ordinary `.dad` file, the format's hand-authored
    input, but no corpus document: nothing cites it, and only its own
    statements count, so each entry must be complete in its file. Every
    `Grouped AVP` and `Enumerated AVP` section and every AVP-table row is
    one `Supplied`: a definition's code and vendor from its header rule (no
    vendor-id is IETF space), its flag rules from the table row of its
    name; a row alone gives code, type and flag rules, its vendor read as
    `AvpTableRow.stated_vendor` reads it. The source is the file's `;
    Specification:` and name. A missing field, a row contradicting its
    definition or its own V flag, and a name given twice, defined or tabled
    twice in one sidecar or supplied by two, raise `ModelError`.
    """
    found: dict[str, Supplied] = {}
    for path in paths:
        spec = parser.parse(path.read_text(encoding="utf-8"))
        source = f"{spec.specification} ({path.name})"
        defined: dict[str, ast.GroupedAvp | ast.EnumeratedAvp] = {}
        rows: dict[str, ast.AvpTableRow] = {}
        for section in spec.sections:
            if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
                if section.name in defined:
                    raise ModelError(f"{path}: {section.name} is defined twice")
                defined[section.name] = section
            elif isinstance(section, ast.AvpTable):
                for row in section.rows:
                    if row.name in rows:
                        raise ModelError(f"{path}: {row.name} is tabled twice")
                    rows[row.name] = row
        for name in dict.fromkeys((*defined, *rows)):
            if name in found:
                raise ModelError(f"{path}: {name} is supplied twice")
            found[name] = _supplied(
                spec, source, name, defined.get(name), rows.get(name)
            )
    return found


def _supplied(
    spec: ast.Specification,
    source: str,
    name: str,
    definition: ast.GroupedAvp | ast.EnumeratedAvp | None,
    row: ast.AvpTableRow | None,
) -> Supplied:
    if row is None or not _stated(row.flag_rules):
        raise ModelError(f"{source}: {name} states no flag rules")
    stated = row.stated_vendor(spec.vendor_id)
    if definition is None:
        if row.code is None or row.data_type is None:
            raise ModelError(f"{source}: {name} states no code or no type")
        vendor_id = spec.vendor_id if stated is None else stated
        _refuse_conflicts(source, name, _flag_conflict(row, vendor_id))
        return Supplied(
            vendor_id=vendor_id,
            code=row.code,
            data_type=row.data_type,
            flag_rules=row.flag_rules,
            source=source,
        )
    grouped = isinstance(definition, ast.GroupedAvp)
    data_type = ast.DataType.GROUPED if grouped else ast.DataType.ENUMERATED
    vendor_id = (
        ast.IETF_VENDOR if definition.vendor_id is None else definition.vendor_id
    )
    printed_type = row.data_type or row.printed_type
    conflicts = []
    if row.code is not None and row.code != definition.code:
        conflicts.append(f"row gives code {row.code}, definition {definition.code}")
    if printed_type is not None and printed_type != data_type:
        conflicts.append(f"row gives type {printed_type}, definition {data_type}")
    if stated is not None and stated != vendor_id:
        conflicts.append(f"row gives vendor {stated}, definition {vendor_id}")
    conflicts += _flag_conflict(row, vendor_id if stated is None else stated)
    _refuse_conflicts(source, name, conflicts)
    return Supplied(
        vendor_id=vendor_id,
        code=definition.code,
        data_type=data_type,
        flag_rules=row.flag_rules,
        source=source,
        members=definition.avps if isinstance(definition, ast.GroupedAvp) else (),
        values=definition.values if isinstance(definition, ast.EnumeratedAvp) else (),
    )


def _flag_conflict(row: ast.AvpTableRow, vendor_id: int) -> list[str]:
    """How `row`'s V flag contradicts the vendor it is read in: RFC 6733
    section 4.1.1, as `AvpTableRow.vendor_flag_conflict` reads it."""
    conflict = row.model_copy(update={"vendor_id": vendor_id}).vendor_flag_conflict()
    return [] if conflict is None else [f"row gives {conflict}"]


def _refuse_conflicts(source: str, name: str, conflicts: list[str]) -> None:
    if conflicts:
        raise ModelError(f"{source}: {name}: {'; '.join(conflicts)}")
