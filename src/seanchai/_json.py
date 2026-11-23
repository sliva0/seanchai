"""The JSON shapes `seanchai dictionary` and `seanchai export` share, and how
the model's objects become them.

`dictionary` publishes these as part of its contract; `export_schema` builds
the export's shapes on them. Both serialise with `dumps`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pydantic

from .dad import ast

if TYPE_CHECKING:
    from . import corpus, model


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")


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


def flag_rules(rules: model.FlagRules) -> FlagRules:
    """`rules`, each column in a flags cell's order."""
    return FlagRules.model_validate(rules.to_dict())


def cross_release(crossing: corpus.CrossRelease | None) -> CrossRelease | None:
    """`crossing` as JSON, or None."""
    if crossing is None:
        return None
    return CrossRelease(
        citing=crossing.citing,
        cited=crossing.cited,
        version=crossing.version,
        rule=crossing.rule,
        cited_revision=crossing.cited_revision,
        revision=crossing.revision,
        meant=crossing.meant,
    )


def undefined_block(undefined: model.Undefined) -> UndefinedBlock:
    """The block declaring an undefined name, without its name and document."""
    return UndefinedBlock(
        section=undefined.section,
        page=undefined.page,
        note=undefined.note,
        cited_in=undefined.cited_in,
    )


def hole(found: model.Hole) -> Hole:
    """`found` as the export and the dictionary write it."""
    return Hole(
        name=found.name,
        reference=found.reference,
        version=found.version,
        missing=found.missing,
        vendor_id=found.vendor_id,
        code=found.code,
        data_type=found.data_type,
        flag_rules=None if found.flag_rules is None else flag_rules(found.flag_rules),
        section=found.section,
        origin=found.origin,
        conflict=found.conflict,
        wireshark_name=found.wireshark_name,
        across_releases=cross_release(found.across_releases),
        undefined=None if found.undefined is None else undefined_block(found.undefined),
        recorded=found.recorded,
    )


def dumps(value: pydantic.BaseModel, *, exclude_defaults: bool = True) -> str:
    """Serialise a model as the export and the dictionary write it: compact,
    keys sorted, one final newline. A field holding its default is left out
    unless `exclude_defaults` is false."""
    return (
        json.dumps(
            value.model_dump(mode="json", exclude_defaults=exclude_defaults),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
