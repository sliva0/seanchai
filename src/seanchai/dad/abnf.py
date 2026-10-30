"""ABNF semantics shared by the `.dad` parser and the source extractors.

The parser reads canonical `.dad` text and the 3GPP extractor reads Word
paragraphs, so their *syntax* differs — the extractor tolerates spacing the
canonical form never emits, and neither dialect's regex belongs here. What they
must not disagree about is what that syntax *means*: which bracket pair is which
presence, how `min*max` maps to occurrence counts, how the items of a Diameter
header line split into command code, flags and application id, and how M/V flag
cells are spelled. Those live here, so a format change is one edit instead of
two that a test cannot catch drifting apart.

Both dialects' rule regexes use the same group names (`min`, `max`, `open`,
`close`, `name`), which is what lets `avp_rule()` accept either.

Errors are raised as `AbnfError` and translated by the caller, which is the
side that knows whether the context is a line number or a document section.
"""

import re

from . import ast

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


class AbnfError(ValueError):
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
    """`min*max` groups → `(min_occurs, max_occurs)`. Both groups absent means
    no qualifier at all, i.e. exactly once; a bare `*` is (0, None)."""
    if minimum is None and maximum is None:
        return 1, 1
    return int(minimum or 0), int(maximum) if maximum else None


def qualifier(min_occurs: int, max_occurs: int | None) -> str:
    """The inverse of `occurrences`: exactly-once prints nothing."""
    if (min_occurs, max_occurs) == (1, 1):
        return ""
    minimum = str(min_occurs) if min_occurs else ""
    maximum = str(max_occurs) if max_occurs is not None else ""
    return f"{minimum}*{maximum}"


def avp_rule(
    match: re.Match, bold: bool = False, strikethrough: bool = False
) -> ast.AvpRule:
    """One body line of a message or grouped AVP, from either dialect's match."""
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
    """The inside of `< Diameter Header: 306, REQ, PXY, 16777217 >`.

    The application id is optional because some source documents omit it (TS
    29.272 prints `< Diameter Header: 8388638, REQ, PXY, >`), so it is
    recognised by being a trailing number rather than by position. That one
    trailing comma is the only empty item tolerated: an interior `, ,` is a
    malformed header in either dialect, and letting it through here would mean
    canonical `.dad` accepting text the formatter can never produce.
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


def diameter_header_items(
    command_code: int, flags: frozenset[ast.CommandFlag], application_id: int | None
) -> str:
    ordered = [flag.value for flag in _COMMAND_FLAG_ORDER if flag in flags]
    application = [] if application_id is None else [str(application_id)]
    return ", ".join([str(command_code), *ordered, *application])


def avp_flags(cell: str) -> frozenset[ast.AvpFlag]:
    """An AVP-table flags cell: `M`, `M, V`, `M,V`. The empty spelling differs
    between dialects (`-` in `.dad`, an empty cell in a docx table), so callers
    handle that themselves."""
    try:
        parsed = [ast.AvpFlag(flag.strip()) for flag in cell.split(",")]
    except ValueError:
        raise AbnfError(f"malformed flags cell {cell!r}") from None
    _reject_repeats(parsed, f"flags cell {cell!r}")
    return frozenset(parsed)


def _reject_repeats(flags: list, where: str) -> None:
    """A flag named twice is a source typo, and a `frozenset` would swallow it.

    Swallowing it is the objectionable part: `REQ, REQ` would format back as
    `REQ`, so the file would silently disagree with the document instead of
    recording it. There is nothing a repeat could mean that the single flag
    does not already mean, so it cannot be recorded faithfully either — which
    leaves failing, and letting an input patch make the fix an explicit,
    reviewed edit.
    """
    if len(set(flags)) != len(flags):
        repeated = sorted({flag.value for flag in flags if flags.count(flag) > 1})
        raise AbnfError(f"{where} repeats {', '.join(repeated)}")


def avp_flags_cell(flags: frozenset[ast.AvpFlag]) -> str:
    """Canonical `.dad` spelling, with `-` for the empty set."""
    return ",".join(flag.value for flag in ast.AvpFlag if flag in flags) or "-"
