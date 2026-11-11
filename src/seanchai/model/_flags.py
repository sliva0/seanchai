"""`FlagRules`, RFC 6733's default for an IETF-space AVP's unplaced M and V
bits, and helpers for reading a table row's flag cells."""

from __future__ import annotations

import pydantic

from ..dad import ast


class FlagRules(ast.AvpFlagRules):
    """AVP flag rules plus `application_defined`: the bits RFC 6733 leaves
    to the application that uses the AVP.

    RFC 6733 section 4.1 has the using application set the M bit, so an IETF
    AVP whose RFC states no M rule has none of its own. Section 4.1.1 makes
    an IETF-space AVP's V bit Must-not.

    Every `Avp.flag_rules` and `Hole.flag_rules` is one of these.
    `application_defined` is set only for vendor 0 (`_ietf_rules`); elsewhere
    it is empty and the columns are as the document prints them.
    """

    application_defined: frozenset[ast.AvpFlag] = frozenset()

    @classmethod
    def printed(cls, rules: ast.AvpFlagRules) -> FlagRules:
        """`rules` as a `FlagRules`, returned unchanged if it already is one."""
        if isinstance(rules, cls):
            return rules
        return cls(
            must=rules.must,
            may=rules.may,
            should_not=rules.should_not,
            must_not=rules.must_not,
        )

    def to_dict(self) -> dict[str, list[str]]:
        """The five columns, each a sorted list of flags."""
        return {
            name: sorted(flag.value for flag in getattr(self, name))
            for name in type(self).model_fields
        }

    @pydantic.field_serializer("application_defined", when_used="json")
    def _application_defined_in_cell_order(
        self, flags: frozenset[ast.AvpFlag]
    ) -> list[ast.AvpFlag]:
        """As `AvpFlagRules`' columns."""
        return [flag for flag in ast.AvpFlag if flag in flags]

    @pydantic.model_validator(mode="after")
    def _defined_once(self) -> FlagRules:
        placed = self.must | self.may | self.should_not | self.must_not
        if overlap := placed & self.application_defined:
            raise ValueError(
                f"AVP flag {min(overlap).value!r} is both placed and"
                " application-defined"
            )
        return self


def _ietf_rules(flag_rules: ast.AvpFlagRules | None) -> FlagRules:
    """An IETF-space AVP's flag rules, with an unplaced V put under Must-not
    (RFC 6733 section 4.1.1) and an unplaced M made application-defined
    (section 4.1). Other placements, the P bit included, are kept."""
    rules = ast.AvpFlagRules() if flag_rules is None else flag_rules
    placed = rules.must | rules.may | rules.should_not | rules.must_not
    if {ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR} <= placed:
        return FlagRules.printed(rules)
    return FlagRules(
        must=rules.must,
        may=rules.may,
        should_not=rules.should_not,
        must_not=rules.must_not | ({ast.AvpFlag.VENDOR} - placed),
        application_defined=frozenset({ast.AvpFlag.MANDATORY}) - placed,
    )


def _stated(flag_rules: ast.AvpFlagRules) -> bool:
    """Whether a row's flag cells state anything. Empty rules come from a
    table with no flag columns or a row with blank cells, and do not mean
    that no flag applies."""
    return bool(
        flag_rules.must
        or flag_rules.may
        or flag_rules.should_not
        or flag_rules.must_not
    )


def _overlay(
    own: ast.AvpFlagRules, theirs: ast.AvpFlagRules | None
) -> ast.AvpFlagRules:
    """`own`'s placements, plus `theirs` for each flag `own` leaves
    unplaced."""
    if theirs is None:
        return own
    placed = own.must | own.may | own.should_not | own.must_not
    return ast.AvpFlagRules(
        must=own.must | (theirs.must - placed),
        may=own.may | (theirs.may - placed),
        should_not=own.should_not | (theirs.should_not - placed),
        must_not=own.must_not | (theirs.must_not - placed),
    )
