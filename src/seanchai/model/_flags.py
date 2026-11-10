"""Flag rules as the model reads them: `FlagRules`, RFC 6733's rule for an
IETF-space AVP's unplaced M and V bits, and the two helpers resolution reads
a table row's flag cells with."""

from __future__ import annotations

import pydantic

from ..dad import ast


class FlagRules(ast.AvpFlagRules):
    """Flag rules holding the one setting no table cell prints: a bit RFC
    6733 leaves to whichever application uses the AVP.

    RFC 6733 section 4.1: "The 'M' bit MUST be set according to the rules
    defined in the application specification that introduces or reuses this
    AVP", and RFC 7423 section 4.4.1 has a re-using application "specify
    the setting of the M-bit". An IETF AVP whose defining RFC states no M
    rule (RFC 4072, 5447, 5777 and 6734 print no flag columns) therefore has
    none of its own, by rule rather than by omission, and Must or May would
    each be a guess. Its V bit is no guess: section 4.1.1 forbids a Vendor-ID
    of zero, so an IETF-space AVP carries none and its V bit is Must-not.

    Every `Avp.flag_rules` and `Hole.flag_rules` is one of these, so a consumer
    reads one type. `application_defined` is set only on vendor 0's
    (`_ietf_rules`); everywhere else it is empty and the columns are the
    document's as printed.
    """

    application_defined: frozenset[ast.AvpFlag] = frozenset()

    @classmethod
    def printed(cls, rules: ast.AvpFlagRules) -> FlagRules:
        """A table's four columns as the model's type; rules already of it are
        returned as they are."""
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
    """An IETF-space AVP's flag rules with RFC 6733's rule for each of M and
    V that no reading places: V under Must-not (section 4.1.1), M
    application-defined (section 4.1). Rules placing both are returned as
    they are; so are a document's own rules for the P bit, which RFC 6733
    reserves. RFC 7683 and 8583 place V only, and say in prose that "the
    M-bit usage for a given AVP in a given command may be defined by the
    application"."""
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
    """Whether a row's flag cells say anything. A table with no flag columns
    (RFC 4072, 5447, 5777 and 6734 print none) and a row with every
    flag cell blank (TS 32.299 table 7.2.0.1 for most re-printed rows) both
    parse to empty rules, and neither is a claim that no flag applies."""
    return bool(
        flag_rules.must
        or flag_rules.may
        or flag_rules.should_not
        or flag_rules.must_not
    )


def _overlay(
    own: ast.AvpFlagRules, theirs: ast.AvpFlagRules | None
) -> ast.AvpFlagRules:
    """`own`'s placements, with each flag `own` places in no column placed
    where `theirs` places it: TS 29.229's `Digest-Qop` row puts M in Must
    and V in Must not, and RFC 4590's stand-in rules add P under May."""
    if theirs is None:
        return own
    placed = own.must | own.may | own.should_not | own.must_not
    return ast.AvpFlagRules(
        must=own.must | (theirs.must - placed),
        may=own.may | (theirs.may - placed),
        should_not=own.should_not | (theirs.should_not - placed),
        must_not=own.must_not | (theirs.must_not - placed),
    )
