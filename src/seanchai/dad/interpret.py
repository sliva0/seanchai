"""Interpreted constraints: what a clause's prose says of an AVP's value or
presence, declared by a person who read it, pinned to the sentences read.

A corrections module declares them beside its corrections:

    from seanchai.dad.interpret import Interpret, encoding, reading

    CORRECTIONS += [
        Interpret(
            id="visited-plmn-id",
            avp="Visited-PLMN-Id",
            section="7.3.9",
            page=41,
            readings=(
                reading(
                    "The content of this AVP shall be encoded as an octet"
                    " string according to table 7.3.9-1.",
                    encoding(ast.Codec.PLMN_ID),
                ),
            ),
            versions="19.6.0",
        ),
    ]

`corrections.apply` places each as an `Interpreted Constraints` block in
the corrected file, in clause order beside the clause it reads, and the
regenerate step checks every quote against the source document's clause
(`check_quotes`). docs/constraints.md describes the kinds and codecs.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pydantic

from .._versions import VersionRange
from . import ast
from ._errors import CorrectionError

__all__ = [
    "Interpret",
    "absent_if",
    "bit",
    "bits_at_least_one",
    "bits_at_most_one",
    "bits_clear",
    "bits_only",
    "bits_set",
    "characters",
    "check_quotes",
    "default",
    "digits",
    "element",
    "encoding",
    "equals",
    "exclude",
    "excludes",
    "members_at_least_one",
    "members_only",
    "octets",
    "paged",
    "present",
    "present_if",
    "range_of",
    "reading",
    "requires",
    "text_only",
    "unique",
    "values_if",
    "with_origin",
]


# --- the rules, as a module writes them -------------------------------------


class _Same:
    """A length's upper bound left out: the same as its lower."""


_SAME = _Same()


def _length(
    unit: ast.LengthUnit, low: int | None, high: int | _Same | None
) -> ast.LengthRule:
    return ast.LengthRule(
        unit=unit, low=low, high=low if isinstance(high, _Same) else high
    )


def octets(low: int | None, high: int | _Same | None = _SAME) -> ast.LengthRule:
    """`length LOW..HIGH octets`; one argument is an exact length, None an
    open bound."""
    return _length(ast.LengthUnit.OCTETS, low, high)


def digits(low: int | None, high: int | _Same | None = _SAME) -> ast.LengthRule:
    """`length LOW..HIGH digits`, as `octets`."""
    return _length(ast.LengthUnit.DIGITS, low, high)


def characters(low: int | None, high: int | _Same | None = _SAME) -> ast.LengthRule:
    """`length LOW..HIGH characters`, as `octets`."""
    return _length(ast.LengthUnit.CHARACTERS, low, high)


def range_of(low: int | None, high: int | None) -> ast.RangeRule:
    """`range LOW..HIGH`, None for an open bound."""
    return ast.RangeRule(low=low, high=high)


def exclude(*values: int) -> ast.ExcludeRule:
    """`exclude V, ...`."""
    return ast.ExcludeRule(values=values)


def encoding(codec: ast.Codec) -> ast.EncodingRule:
    """`encoding CODEC`, for every codec but `element`."""
    return ast.EncodingRule(codec=codec)


def element(
    document: str, clause: str | None = None, name: str | None = None
) -> ast.EncodingRule:
    """`encoding element DOCUMENT [CLAUSE] ["NAME"]`: an information element
    `document` defines, carried whole."""
    return ast.EncodingRule(
        codec=ast.Codec.ELEMENT, document=document, clause=clause, element=name
    )


def present(avp: str) -> ast.Condition:
    """A condition: `avp` is present."""
    return ast.Condition(avp=avp)


def equals(avp: str, value: int | str) -> ast.Condition:
    """A condition: `avp` holds `value`, a number or a value's name."""
    return ast.Condition(avp=avp, value=value)


def bit(avp: str, which: int | str) -> ast.Condition:
    """A condition: `avp` has a bit set, by number or by its bit table's
    name."""
    return ast.Condition(avp=avp, bit=which)


def _predicate(
    kind: ast.PredicateKind, conditions: Sequence[ast.Condition | str]
) -> ast.PredicateRule:
    return ast.PredicateRule(
        kind=kind,
        conditions=tuple(
            present(each) if isinstance(each, str) else each for each in conditions
        ),
    )


def present_if(*conditions: ast.Condition | str) -> ast.PredicateRule:
    """`present-if C [or C ...]`; a bare name is `present(name)`."""
    return _predicate(ast.PredicateKind.PRESENT_IF, conditions)


def absent_if(*conditions: ast.Condition | str) -> ast.PredicateRule:
    """`absent-if C [or C ...]`."""
    return _predicate(ast.PredicateKind.ABSENT_IF, conditions)


def requires(*conditions: ast.Condition | str) -> ast.PredicateRule:
    """`requires C [or C ...]`."""
    return _predicate(ast.PredicateKind.REQUIRES, conditions)


def excludes(*conditions: ast.Condition | str) -> ast.PredicateRule:
    """`excludes C [or C ...]`."""
    return _predicate(ast.PredicateKind.EXCLUDES, conditions)


def default(value: int | str) -> ast.DefaultRule:
    """`default VALUE`: what the AVP is read as when absent, a number or a
    value's name."""
    return ast.DefaultRule(value=value)


def bits_at_most_one(*bits: int) -> ast.BitsRule:
    """`bits at-most-one B B ...`: of these bits of the AVP's own value, at
    most one is set."""
    return ast.BitsRule(relation=ast.BitsRelation.AT_MOST_ONE, bits=bits)


def bits_at_least_one(*bits: int) -> ast.BitsRule:
    """`bits at-least-one B B ...`: of these bits, at least one is set."""
    return ast.BitsRule(relation=ast.BitsRelation.AT_LEAST_ONE, bits=bits)


def bits_set(*bits: int) -> ast.BitsRule:
    """`bits set B ...`: each of these bits is set."""
    return ast.BitsRule(relation=ast.BitsRelation.SET, bits=bits)


def bits_clear(*bits: int) -> ast.BitsRule:
    """`bits clear B ...`: each of these bits is clear."""
    return ast.BitsRule(relation=ast.BitsRelation.CLEAR, bits=bits)


def bits_only(*bits: int) -> ast.BitsRule:
    """`bits only B ...`: no bit but these is set."""
    return ast.BitsRule(relation=ast.BitsRelation.ONLY, bits=bits)


def members_at_least_one(*members: str) -> ast.MembersRule:
    """`members at-least-one M ...`: of these members of the grouped AVP, at
    least one is present; one name alone is a member that must be."""
    return ast.MembersRule(relation=ast.BitsRelation.AT_LEAST_ONE, members=members)


def members_only(*members: str) -> ast.MembersRule:
    """`members only M ...`: the grouped AVP holds no member but these."""
    return ast.MembersRule(relation=ast.BitsRelation.ONLY, members=members)


def unique() -> ast.UniqueRule:
    """`unique`: no two of the `within` grouped AVPs beside each other hold
    the AVP with the same value."""
    return ast.UniqueRule()


def values_if(
    values: int | Sequence[int], *conditions: ast.Condition | str
) -> ast.ValuesRule:
    """`values V, ... if C [or C ...]`: when a condition holds, the AVP's
    value is one of `values`; a bare name is `present(name)`."""
    return ast.ValuesRule(
        values=(values,) if isinstance(values, int) else tuple(values),
        conditions=tuple(
            present(each) if isinstance(each, str) else each for each in conditions
        ),
    )


def text_only() -> ast.TextOnly:
    """`text-only`: the quote states a rule no kind expresses."""
    return ast.TextOnly()


def reading(quotes: str | Sequence[str], *rules: ast.ConstraintRule) -> ast.Reading:
    """Quotes, verbatim, and the rules read from them: one sentence, or
    several where the rule takes them together."""
    return ast.Reading(
        quotes=(quotes,) if isinstance(quotes, str) else tuple(quotes),
        rules=rules,
    )


# --- the declaration --------------------------------------------------------

_ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


@dataclass(frozen=True, kw_only=True)
class Interpret:
    """Constraints read from one clause about one AVP, inserted into the
    corrected file as an `Interpreted Constraints` block.

    `command` (with `application_id`) or `within` scopes the rules to where
    the AVP appears in that command or grouped AVP. `table` names the table
    printing the quotes, an information element's description.

    `page` is not declared: it is the clause's page in the copy being
    corrected, which one declaration serves in several releases, and
    regenerating reads it from the source, the PDF's outline or the RFC's
    page (`paged`). A declaration applied without the source carries none.

    Applying it expects the corrected file to hold the AVP and the scope,
    and no other block for the same AVP, scope and clause. Regenerating
    from the source documents checks every quote against the clause
    (`check_quotes`).
    """

    id: str
    avp: str
    section: str
    readings: tuple[ast.Reading, ...]
    page: int | None = None
    command: str | None = None
    application_id: int | None = None
    within: str | None = None
    table: str | None = None
    versions: str | VersionRange = "*..*"
    origin: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_RE.fullmatch(self.id):
            raise CorrectionError(
                f"correction id {self.id!r} is not a lowercase kebab-case name"
            )
        object.__setattr__(self, "versions", VersionRange.parse(self.versions))
        object.__setattr__(self, "readings", tuple(self.readings))
        if not self.readings:
            raise CorrectionError(f"{self.id}: an interpretation reads something")
        try:
            self.node  # noqa: B018 -- validated once, here
        except pydantic.ValidationError as error:
            raise CorrectionError(f"{self.id}: {error.errors()[0]['msg']}") from None

    @property
    def node(self) -> ast.InterpretedConstraints:
        """The block the declaration inserts."""
        body: list[ast.Quote | ast.ConstraintRule] = []
        for each in self.readings:
            body.extend(ast.Quote(text=quote) for quote in each.quotes)
            body.extend(each.rules)
        return ast.InterpretedConstraints(
            avp=self.avp,
            command=self.command,
            application_id=self.application_id,
            within=self.within,
            table=self.table,
            source=ast.SourceRef(section=self.section, page=self.page),
            versions=str(self.versions),
            body=tuple(body),
        )

    @property
    def reason(self) -> str:
        """What the record says of it: the clause and the quotes read."""
        quotes = "; ".join(
            f"'{quote}'" for each in self.readings for quote in each.quotes
        )
        where = f"table {self.table}" if self.table else f"clause {self.section}"
        return f"interpreted from {where}: {quotes}"

    @property
    def cited(self) -> str:
        return f"{self.origin}#{self.id}" if self.origin else self.id

    def scope(self) -> str:
        """The AVP and where it is constrained, for messages."""
        if self.command is not None:
            return f"{self.avp} in {self.command}"
        if self.within is not None:
            return f"{self.avp} in {self.within}"
        return self.avp


def _normalize(text: str) -> str:
    """Whitespace collapsed as the extractors collapse it, so a quote spans
    a line break or a double space as the clause prints it."""
    return " ".join(text.replace("\xa0", " ").split())


def check_quotes(
    declared: Sequence[Interpret], clauses: Mapping[str, Sequence[str]]
) -> None:
    """Check every quote of `declared` against the text of its clause:
    `clauses` maps a clause number to its paragraphs and table cells, as the
    extractor read and normalized them. A quote must be within one of them.

    Raises `CorrectionError` naming every miss, as a correction's `expect`
    fails once upstream changes.
    """
    misses = []
    for each in declared:
        texts = clauses.get(each.section)
        if texts is None:
            misses.append(f"{each.cited}: the document has no clause {each.section}")
            continue
        for item in each.readings:
            for quote in item.quotes:
                if not any(_normalize(quote) in text for text in texts):
                    misses.append(
                        f"{each.cited}: clause {each.section} does not print {quote!r}"
                    )
    if misses:
        raise CorrectionError("; ".join(misses))


def paged(item: Interpret, pages: Mapping[str, int] | None) -> Interpret:
    """`item` placed on its clause's page in `pages`, a clause number's page
    in the copy corrected; unchanged without `pages`."""
    if pages is None:
        return item
    return dataclasses.replace(item, page=pages.get(item.section))


def with_origin(item: Interpret, origin: str) -> Interpret:
    """`item` as loaded from the module `origin`."""
    return dataclasses.replace(item, origin=origin)
