"""`FlagRules`, RFC 6733's default for an IETF-space AVP's unplaced M and V
bits, and helpers for reading a table row's flag cells."""

from __future__ import annotations

from dataclasses import dataclass

from ..dad import ast

_COLUMNS = ("must", "may", "should_not", "must_not", "application_defined")


@dataclass(frozen=True)
class FlagRules:
    """An AVP's flag rules: the four columns of a specification's AVP table,
    plus `application_defined`, the bits RFC 6733 leaves to the application
    that uses the AVP.

    RFC 6733 section 4.1 has the using application set the M bit, so an IETF
    AVP whose RFC states no M rule has none of its own. Section 4.1.1 makes
    an IETF-space AVP's V bit Must-not.

    Every `Avp.flag_rules` and `Hole.flag_rules` is one of these.
    `application_defined` is set only for vendor 0 (`_ietf_rules`); elsewhere
    it is empty and the columns are as the document prints them. Each flag
    sits in at most one column.
    """

    must: frozenset[ast.AvpFlag] = frozenset()
    may: frozenset[ast.AvpFlag] = frozenset()
    should_not: frozenset[ast.AvpFlag] = frozenset()
    must_not: frozenset[ast.AvpFlag] = frozenset()
    application_defined: frozenset[ast.AvpFlag] = frozenset()

    def __post_init__(self) -> None:
        seen: dict[ast.AvpFlag, str] = {}
        for column in _COLUMNS:
            flags = frozenset(ast.AvpFlag(flag) for flag in getattr(self, column))
            # Accepts any iterable of flags or their letters, held as a frozenset.
            object.__setattr__(self, column, flags)
            for flag in flags:
                if flag in seen:
                    raise ValueError(
                        f"AVP flag {flag.value!r} is in both {seen[flag]} and {column}"
                    )
                seen[flag] = column

    @classmethod
    def printed(cls, rules: ast.AvpFlagRules | FlagRules) -> FlagRules:
        """A table row's printed rules (`ast.AvpFlagRules`) as a `FlagRules`,
        or `rules` unchanged if it already is one."""
        if isinstance(rules, cls):
            return rules
        return cls(
            must=rules.must,
            may=rules.may,
            should_not=rules.should_not,
            must_not=rules.must_not,
        )

    def columns(self) -> ast.AvpFlagRules:
        """The four printed columns, as a table row holds them; the
        application-defined bits are in none of them."""
        return ast.AvpFlagRules(
            must=self.must,
            may=self.may,
            should_not=self.should_not,
            must_not=self.must_not,
        )

    def to_dict(self) -> dict[str, list[str]]:
        """The five columns, each a list of flags in a flags cell's order
        (M, V, P)."""
        return {
            name: [flag.value for flag in ast.AvpFlag if flag in getattr(self, name)]
            for name in _COLUMNS
        }

    def __repr__(self) -> str:
        placed = ", ".join(
            f"{name}={''.join(self.to_dict()[name])}"
            for name in _COLUMNS
            if getattr(self, name)
        )
        return f"<FlagRules {placed or 'none'}>"


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
