"""`_Draft`: one reading of a name while resolution assembles it, how one
reading fills what it leaves unstated from the next (`_Draft.fill`), and how
a finished reading becomes an `Avp` or a `Hole` (`_Draft.final`)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property

from .. import corpus
from ..corpus import Missing
from ..dad import ast
from ._flags import FlagRules, _ietf_rules
from ._types import (
    Avp,
    Enumerated,
    Grouped,
    Hole,
    Member,
    Undefined,
    ValueTable,
)


@dataclass
class _Draft:
    """One reading of a name while resolution assembles it: `Avp`'s fields,
    any of them possibly unknown, until `final` turns it into an `Avp` or a
    `Hole`."""

    # Avp, Grouped or Enumerated; None when nothing defines the name, and the
    # draft carries only the unreadable `origin` that would have.
    kind: type[Avp] | None
    name: str
    reference: str
    # `reference`'s version when the reading is an older copy's, which a
    # hole names (`Hole.version`).
    version: str | None = None
    vendor_id: int | None = None
    # False for a table row whose V flag states no vendor space, so that the
    # vendor is the file's `; Vendor-ID:` rather than anything the row says.
    vendor_stated: bool = False
    code: int | None = None
    data_type: ast.DataType | None = None
    flag_rules: ast.AvpFlagRules | None = None
    section: str | None = None
    origin: str | None = None
    conflict: str | None = None
    wireshark_name: str | None = None
    across: corpus.CrossRelease | None = None
    members: tuple[Member, ...] = ()
    dropped: tuple[Member, ...] = ()
    values: tuple[ast.EnumEntry, ...] = ()
    values_source: str | None = None
    # The block declaring the name, on a draft of kind None that only
    # explains the failure.
    undefined: Undefined | None = None
    supplied: str | None = None
    completed_by: tuple[tuple[Missing, str], ...] = ()
    # `Avp.read_through`, where it is no longer `reference`.
    read_through: str | None = None
    value_tables: tuple[ValueTable, ...] = ()

    @property
    def document(self) -> str:
        """As `Hole.document`."""
        return self.reference + ("" if self.version is None else f" V{self.version}")

    def stating(self, name: Missing) -> str:
        """The document stating this reading's field `name`."""
        return dict(self.completed_by).get(name, self.reference)

    def fill(self, other: _Draft) -> _Draft:
        """This reading with what it leaves unstated taken from `other`, the
        next document along the resolution order, when the two are the same
        AVP saying the same thing.

        Every field both readings state must be equal: code, type, flag
        rules, and vendor where both state one. A table row states its
        vendor through its V flag (`AvpTableRow.stated_vendor`); one whose
        V flag says neither is inferred from its file, and agrees with any:
        TS 29.229's row for RFC 4590's `Digest-Realm` sits in vendor 10415's
        file, the origin's row in vendor 0's. A reading that disagrees fills
        nothing, and neither does any after it; the hole names it instead, since taking
        a `Time` row's missing flags from an `Unsigned32` reading would make
        one complete AVP out of two documents that disagree about it.
        """
        if self.kind is None:
            # Nothing here yet: any definition wins, and failing one, the
            # first unreadable origin stays the explanation, then the block
            # declaring the name undefined.
            return other if other.kind is not None or self.origin is None else self
        if other.kind is None or self.conflict is not None:
            return self
        pairs = [
            (self.code, other.code),
            (self.data_type, other.data_type),
            (self.flag_rules, other.flag_rules),
        ]
        if not any(mine is None and theirs is not None for mine, theirs in pairs):
            return self
        if self.vendor_stated and other.vendor_stated:
            pairs.append((self.vendor_id, other.vendor_id))
        if any(
            mine is not None and theirs is not None and mine != theirs
            for mine, theirs in pairs
        ):
            return replace(self, conflict=other.reference)
        kind, members, dropped = self.kind, self.members, self.dropped
        values, values_source = self.values, self.values_source
        if self.data_type is None and other.kind is not Avp:
            # A row printing no type, for an AVP another document defines
            # as grouped or enumerated, takes the definition's body too.
            kind, members, dropped = other.kind, other.members, other.dropped
            values, values_source = other.values, other.values_source
        completed = dict(self.completed_by)
        for each in (Missing.CODE, Missing.DATA_TYPE, Missing.FLAG_RULES):
            if getattr(self, each) is None and getattr(other, each) is not None:
                completed[each] = other.stating(each)
        vendor_id, vendor_stated = self.vendor_id, self.vendor_stated
        if not vendor_stated and other.vendor_stated:
            vendor_id, vendor_stated = other.vendor_id, True
            completed[Missing.VENDOR_ID] = other.stating(Missing.VENDOR_ID)
        return replace(
            self,
            across=self.across or other.across,
            completed_by=tuple(completed.items()),
            read_through=(
                other.read_through or other.document
                if self.flag_rules is None and other.flag_rules is not None
                else self.read_through
            ),
            kind=kind,
            members=members,
            dropped=dropped,
            values=values,
            values_source=values_source,
            vendor_id=vendor_id,
            vendor_stated=vendor_stated,
            code=other.code if self.code is None else self.code,
            data_type=other.data_type if self.data_type is None else self.data_type,
            flag_rules=(
                other.flag_rules if self.flag_rules is None else self.flag_rules
            ),
        )

    @property
    def complete(self) -> bool:
        """Whether this reading states every field itself, so that no later
        reading has anything to fill. RFC 6733's rule for an IETF AVP's
        unplaced bits is no statement: TS 29.273's row setting M for RFC
        5777's `QoS-Capability` still fills the origin's reading."""
        return self.kind is not None and None not in (
            self.vendor_id,
            self.code,
            self.data_type,
            self.flag_rules,
        )

    @cached_property
    def final(self) -> Avp | Hole:
        flag_rules = (
            None if self.flag_rules is None else FlagRules.printed(self.flag_rules)
        )
        if self.kind is not None and self.vendor_id == ast.IETF_VENDOR:
            flag_rules = _ietf_rules(self.flag_rules)
        if (
            self.kind is None
            or self.vendor_id is None
            or self.code is None
            or self.data_type is None
            or flag_rules is None
        ):
            missing = (
                (
                    (Missing.DEFINITION,)
                    if self.undefined is None
                    else (Missing.UNDEFINED,)
                )
                if self.kind is None
                else tuple(
                    name
                    for name, value in (
                        (Missing.CODE, self.code),
                        (Missing.DATA_TYPE, self.data_type),
                        (Missing.FLAG_RULES, flag_rules),
                    )
                    if value is None
                )
            )
            return Hole(
                reference=self.reference,
                name=self.name,
                missing=missing,
                vendor_id=self.vendor_id,
                code=self.code,
                data_type=self.data_type,
                flag_rules=flag_rules,
                section=self.section,
                origin=self.origin,
                conflict=self.conflict,
                wireshark_name=self.wireshark_name,
                across_releases=self.across,
                version=self.version,
                undefined=self.undefined if self.kind is None else None,
            )
        common = (
            self.name,
            self.vendor_id,
            self.code,
            self.data_type,
            flag_rules,
            self.reference,
            self.section,
            self.wireshark_name,
        )
        if self.kind is Grouped:
            return Grouped(
                *common,
                across_releases=self.across,
                supplied=self.supplied,
                completed_by=self.completed_by,
                read_through=self.read_through or self.document,
                members=self.members,
                dropped=self.dropped,
            )
        if self.kind is Enumerated:
            return Enumerated(
                *common,
                across_releases=self.across,
                supplied=self.supplied,
                completed_by=self.completed_by,
                read_through=self.read_through or self.document,
                values=self.values,
                values_source=self.values_source,
            )
        return Avp(
            *common,
            across_releases=self.across,
            supplied=self.supplied,
            completed_by=self.completed_by,
            read_through=self.read_through or self.document,
            value_tables=self.value_tables,
        )
