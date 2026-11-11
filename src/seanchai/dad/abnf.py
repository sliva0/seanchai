"""ABNF meaning shared by the `.dad` parser and the source extractors.

Each side keeps its own regexes; this module holds what the syntax means:
bracket presence, `min*max` occurrences, Diameter header items and flag
cells. Both sides' rule regexes use the group names `min`, `max`, `open`,
`close` and `name`, so `avp_rule()` accepts either.

Errors are raised as `AbnfError`; the caller adds the line or section.
"""

import re

from ..errors import SeanchaiError
from . import ast

__all__ = [
    "ANSWER_MESSAGE_RE",
    "ANSWER_MESSAGE_RULE",
    "AbnfError",
    "avp_flags",
    "avp_flags_cell",
    "avp_rule",
    "brackets_for",
    "diameter_header",
    "diameter_header_items",
    "occurrences",
    "presence_of",
    "qualifier",
]

_PRESENCE_BY_BRACKETS = {
    ("<", ">"): ast.Presence.FIXED,
    ("{", "}"): ast.Presence.REQUIRED,
    ("[", "]"): ast.Presence.OPTIONAL,
}
_BRACKETS_BY_PRESENCE = {
    ast.Presence.FIXED: "<>",
    ast.Presence.REQUIRED: "{}",
    ast.Presence.OPTIONAL: "[]",
}
# Canonical order of the flags in a Diameter header line.
_COMMAND_FLAG_ORDER = [
    ast.CommandFlag.REQUEST,
    ast.CommandFlag.PROXIABLE,
    ast.CommandFlag.ERROR,
]


class AbnfError(SeanchaiError, ValueError):
    pass


def presence_of(open_bracket: str, close_bracket: str) -> ast.Presence:
    found = _PRESENCE_BY_BRACKETS.get((open_bracket, close_bracket))
    if found is None:
        raise AbnfError("mismatched brackets")
    return found


def brackets_for(presence: ast.Presence) -> tuple[str, str]:
    open_bracket, close_bracket = _BRACKETS_BY_PRESENCE[presence]
    return open_bracket, close_bracket


def occurrences(minimum: str | None, maximum: str | None) -> tuple[int, int | None]:
    """Return `(min_occurs, max_occurs)` for `min*max` groups. No qualifier
    means exactly once; a bare `*` is (0, None)."""
    if minimum is None and maximum is None:
        return 1, 1
    return int(minimum or 0), int(maximum) if maximum else None


def qualifier(min_occurs: int, max_occurs: int | None) -> str:
    """Return the qualifier `occurrences` reads; exactly once is empty."""
    if (min_occurs, max_occurs) == (1, 1):
        return ""
    minimum = str(min_occurs) if min_occurs else ""
    maximum = str(max_occurs) if max_occurs is not None else ""
    return f"{minimum}*{maximum}"


def avp_rule(
    match: re.Match, bold: bool = False, strikethrough: bool = False
) -> ast.AvpRule:
    """Build a body line of a message or grouped AVP from either side's match."""
    min_occurs, max_occurs = occurrences(match["min"], match["max"])
    return ast.AvpRule(
        name=match["name"],
        presence=presence_of(match["open"], match["close"]),
        min_occurs=min_occurs,
        max_occurs=max_occurs,
        bold=bold,
        strikethrough=strikethrough,
    )


def diameter_header(items: str) -> tuple[int, frozenset[ast.CommandFlag], int | None]:
    """Parse the inside of `< Diameter Header: 306, REQ, PXY, 16777217 >`.

    The application id is optional and recognised as a trailing number. One
    trailing empty item is tolerated (TS 29.272 prints `REQ, PXY, >`); any
    other empty item is an error.
    """
    parts = [item.strip() for item in items.split(",")]
    if parts and parts[-1] == "":
        parts.pop()
    if not parts or not parts[0].isdigit():
        raise AbnfError("Diameter header needs a command code")
    if "" in parts:
        raise AbnfError(f"empty item in Diameter header: {items!r}")
    application_id = int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else None
    names = parts[1:-1] if application_id is not None else parts[1:]
    try:
        parsed = [ast.CommandFlag(name) for name in names]
    except ValueError:
        raise AbnfError(f"malformed Diameter flags: {names!r}") from None
    _reject_repeats(parsed, f"Diameter header: {items!r}")
    return int(parts[0]), frozenset(parsed), application_id


# RFC 6733 section 7.2's rule line, which an `AnswerMessage` block prints as it
# stands: it names no command code, flag or application of its own.
ANSWER_MESSAGE_RULE = "<answer-message> ::= < Diameter Header: code, ERR [, PXY] >"
# The rule as documents print it, for the extractors: TS 29.229 clause 7.3.1
# writes `ERR [PXY]`, without RFC 6733's comma, and no space after `::=`.
# Nothing else in the line varies, so nothing else is read.
ANSWER_MESSAGE_RE = re.compile(
    r"^<\s*answer-message\s*>\s*::=\s*<\s*Diameter Header:\s*code\s*,\s*ERR\s*"
    r"\[\s*,?\s*PXY\s*\]\s*>$"
)


def diameter_header_items(
    command_code: int, flags: frozenset[ast.CommandFlag], application_id: int | None
) -> str:
    ordered = [flag.value for flag in _COMMAND_FLAG_ORDER if flag in flags]
    application = [] if application_id is None else [str(application_id)]
    return ", ".join([str(command_code), *ordered, *application])


def avp_flags(cell: str) -> frozenset[ast.AvpFlag]:
    """Parse an AVP-table flags cell: `M`, `M, V`, `M,V`. Callers handle the
    empty cell, which each side spells differently."""
    try:
        parsed = [ast.AvpFlag(flag.strip()) for flag in cell.split(",")]
    except ValueError:
        raise AbnfError(f"malformed flags cell {cell!r}") from None
    _reject_repeats(parsed, f"flags cell {cell!r}")
    return frozenset(parsed)


def _reject_repeats(flags: list, where: str) -> None:
    """Fail on a flag named twice, which a `frozenset` would hide. A source
    typo like this needs an explicit correction.
    """
    if len(set(flags)) != len(flags):
        repeated = sorted({flag.value for flag in flags if flags.count(flag) > 1})
        raise AbnfError(f"{where} repeats {', '.join(repeated)}")


def avp_flags_cell(flags: frozenset[ast.AvpFlag]) -> str:
    """Return the canonical `.dad` spelling, `-` for the empty set."""
    return ",".join(flag.value for flag in ast.AvpFlag if flag in flags) or "-"
