"""ABNF rules as a document prints them: the rule headers, a body's
members line by line with their bold and strikethrough, where a body ends,
the lines commented out of it, and the grouped AVPs whose clauses print an
`AVP header` rule."""

from __future__ import annotations

import dataclasses
import re

from ...dad import abnf, ast, formatter
from .. import sources
from ..errors import ExtractionError
from ._base import _Commented, _Line, _Section

_DIAMETER_HEADER_RE = re.compile(
    # The rule name is normalized separately: source docx sometimes carries
    # stray spaces inside it ("< User-Data -Request>").
    r"^<\s*(?P<name>[A-Za-z -]+?)\s*> ::=\s*<\s*Diameter Header:"
    r"\s*(?P<items>[0-9A-Z, ]+?)\s*>$"
)
_AVP_HEADER_RE = re.compile(
    # code/vendor separator varies between specs: "700 10415" and "632, 10415";
    # rule names can carry spaces for hyphens ("Monitoring Event Report::=");
    # TS 32.299 brackets some rule names ("<Event-Type>::=", "< Participant-Group >
    # ::="), as RFC 6733 does for `<Failed-AVP>`; TS 29.229 clause 6.3.13 writes
    # "AVP Header : 612".
    r"^(?P<open><\s*)?(?P<name>[A-Za-z0-9][A-Za-z0-9 _-]*?)\s*(?(open)>)"
    r"\s*::=\s*<\s*AVP [Hh]eader ?:\s*(?P<code>\d+)"
    r"(?:\s*,?\s+(?P<vendor>\d+))?\s*>$"
)
_ABNF_LINE_RE = re.compile(
    r"^(?:(?P<min>\d*)\*(?P<max>\d*))?\s*"
    r"(?P<open>[<{\[])\s*(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*)\s*(?P<close>[>}\]])$"
)
# One member anywhere in a line, for lines holding several.
_ABNF_MEMBER_RE = re.compile(
    r"\s*(?:\d*\*\d*)?\s*[<{\[]\s*[A-Za-z0-9][A-Za-z0-9_-]*\s*[>}\]]"
)


def _is_bold(line: _Line) -> bool:
    # Word applies bold erratically to brackets/whitespace runs; only the runs
    # spelling the AVP name itself are trusted (`*{ `=True, `Data-Reference`=None,
    # ` }`=True occurs in real documents for a non-bold AVP).
    if len(line.bold) > 1:
        raise ExtractionError(f"mixed bold in ABNF line: {line.text!r}")
    return next(iter(line.bold), False)


def _abnf_body(
    lines: list[_Line],
    start: int,
    rule: str,
    section: str,
    quirks: sources.Quirks,
    warnings: list[str],
) -> tuple[tuple[ast.AvpRule, ...], int, list[tuple[int, str]]]:
    """Parse `[qual] bracket Name bracket` lines starting at `start`.

    Also returns the lines commented out of the body, behind
    `struck-rules-unused` and `elided-members`, each as the note standing for
    it with the number of members before it.

    A body ends at a blank line, a sentence, another paragraph style or the
    next rule. Any other line is a member this reading cannot hold, and fails
    rather than taking the members after it out of the file (`_body_ends`)."""
    rules: list[ast.AvpRule] = []
    notes: list[tuple[int, ast.AvpRule | str]] = []
    style = None
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.text:
            # TS 32.299 leaves blank lines between a message header and its
            # first member (clauses 6.2.2-6.4.5) and inside CCA's body
            # (6.4.3); a blank line followed by anything else ends the body.
            following = next((later for later in lines[index:] if later.text), None)
            if following is None or not (
                _commented_members(following.text, quirks)
                or _ELIDED_LINE_RE.fullmatch(following.text)
            ):
                break
            index += 1
            continue
        if _ELIDED_LINE_RE.fullmatch(line.text):
            # TS 29.273's commands print "…" or "..." where a rule leaves out
            # what it does not change (clause 4.2.2.1.1, between members and
            # before `*[ AVP ]`). It is no member, and it is what the document
            # says of the rule, so it stays where it stood.
            if not quirks.enabled("elided-members"):
                raise ExtractionError(
                    f"{section}: {line.text!r} inside {rule}'s body, which this"
                    " document's source declaration does not read (the"
                    " `elided-members` quirk)"
                )
            quirks.fire("elided-members")
            notes.append((len(rules), line.text))
            style = line.style
            index += 1
            continue
        matches = _abnf_members(line.text)
        if not matches and (matches := _commented_members(line.text, quirks)):
            # TS 29.209 V6.8.0 clause 6.5.18: "{ Media-Component-Number } ;
            # Ordinal number of the media comp." The comment is RFC 5234's
            # (section 3.9) and prose, which a `.dad` body does not keep.
            quirks.fire("abnf-comments")
            line = dataclasses.replace(line, text=line.text.partition(";")[0].rstrip())
        if not matches:
            if not _body_ends(line, style):
                raise ExtractionError(
                    f"{section}: line {line.text!r} inside {rule}'s body is no ABNF"
                    " member; an input patch repairs a typo, a quirk declares a"
                    " reading"
                )
            break
        style = line.style
        index += 1
        if len(matches) > 1 and True in line.struck:
            raise ExtractionError(f"struck line with several members: {line.text!r}")
        for match in matches:
            member = _abnf_member(match, line, rule, quirks, warnings)
            if member.strikethrough and quirks.enabled("struck-rules-unused"):
                # TS 32.299 clauses 6.2.1.2 and 6.4.1.2 define the strike: "An
                # AVP in grey strikethrough in the message format ... is not
                # used by 3GPP". The document's own legend says the member is
                # not part of its rule, so it is no member; it stays in the
                # file as a comment, where the reader still sees it.
                quirks.fire("struck-rules-unused")
                notes.append((len(rules), member))
            else:
                rules.append(member)
    _no_member_after(lines[index:], rule, section)
    # Aligned over the struck members too, so a body's markers stay one
    # column whichever kind of line is longest.
    members = [
        *rules,
        *(note for _, note in notes if isinstance(note, ast.AvpRule)),
    ]
    commented = [
        (
            position,
            (
                note
                if isinstance(note, str)
                else formatter.commented_avp_rule(note, members)
            ),
        )
        for position, note in notes
    ]
    return tuple(rules), index, commented


# A line standing for members a rule leaves out, read behind `elided-members`.
_ELIDED_LINE_RE = re.compile(r"…|\.{3}")
# ABNF's own punctuation, which no line ending a body by its style holds.
_ABNF_PUNCTUATION_RE = re.compile(r"[\[\]{}<>*]")
# A sentence after a body: "NOTE: ...", "The following combinations are
# allowed:". It opens on a word and runs to several, or closes as sentences do;
# a closing bracket last is a member's ("DRMP ]", TS 29.283 clause 6.2.2).
_BODY_SENTENCE_RE = re.compile(r"[A-Za-z]\S*(?:\s+\S+){2,}(?<![>}\]])|[A-Za-z].*[.:]")
# What a member looks like when it cannot be read: qualifiers, then brackets.
_MEMBER_SHAPE_RE = re.compile(r"[\d\s*]*[<{\[].*[>}\]]")


def _body_ends(line: _Line, style: str | None) -> bool:
    """Whether a line no reading makes a member ends a body rather than
    breaking it. Prose follows a body directly and in its own style in dozens
    of clauses (TS 29.336's, 29.272's), so a boundary is a sentence, the next
    rule, or a change of paragraph style on a line with no ABNF in it."""
    return (
        "::=" in line.text
        or ":: =" in line.text
        or bool(_BODY_SENTENCE_RE.fullmatch(line.text))
        or (line.style != style and not _ABNF_PUNCTUATION_RE.search(line.text))
    )


def _no_member_after(lines: list[_Line], rule: str, section: str) -> None:
    """Fail on a member printed after its body ended and before the next rule,
    whichever line ended it: a note wedged between members reads as the
    sentence it is, and the members after it would be gone."""
    for line in lines:
        if "::=" in line.text or ":: =" in line.text:
            return
        if _MEMBER_SHAPE_RE.fullmatch(line.text) or _ELIDED_LINE_RE.fullmatch(
            line.text
        ):
            raise ExtractionError(
                f"{section}: line {line.text!r} follows the end of {rule}'s body"
                " and reads as one of its members"
            )


# An ABNF line with a trailing comment, read behind `abnf-comments`.
_ABNF_COMMENT_RE = re.compile(r"(?P<rule>[^;]*\S) ?;.*")


def _commented_members(text: str, quirks: sources.Quirks) -> list[re.Match]:
    """A line's members, its trailing comment set aside where the document
    declares `abnf-comments`."""
    if matches := _abnf_members(text):
        return matches
    if quirks.enabled("abnf-comments") and (
        commented := _ABNF_COMMENT_RE.fullmatch(text)
    ):
        return _abnf_members(commented["rule"])
    return []


def _abnf_members(text: str) -> list[re.Match]:
    """The members one ABNF line holds: normally one, but TS 32.299 clause
    7.2.154I prints "[ ProSe-Request-Timestamp ] [ PC3-Control-Protocol-Cause ]"
    on one line (the PDF too). A line counts only when members cover all of
    it."""
    if match := _ABNF_LINE_RE.match(text):
        return [match]
    pieces = _ABNF_MEMBER_RE.findall(text)
    if len(pieces) < 2 or "".join(pieces).replace(" ", "") != text.replace(" ", ""):
        return []
    found = [_ABNF_LINE_RE.match(piece.strip()) for piece in pieces]
    return [match for match in found if match is not None]


def _abnf_member(
    match: re.Match,
    line: _Line,
    rule: str,
    quirks: sources.Quirks,
    warnings: list[str],
) -> ast.AvpRule:
    """One member, struck through or not, which `; strikethrough` records as
    `; bold` records bold."""
    if False in line.struck and True in line.struck:
        raise ExtractionError(f"partly struck ABNF line: {line.text!r}")
    struck = True in line.struck
    if struck and not quirks.enabled("struck-rules-unused"):
        # A strike with no legend the extractor reads: the marker records
        # it, and the member stays, since nothing says what it means.
        warnings.append(f"{rule}: member {match['name']} is struck through")
    try:
        return abnf.avp_rule(match, bold=_is_bold(line), strikethrough=struck)
    except abnf.AbnfError as error:
        raise ExtractionError(f"{error} in {line.text!r}") from None


def _rule_text(text: str, quirks: sources.Quirks) -> str:
    """TS 32.299 spells the rule operator ":: =" in about ninety grouped
    rules (clause 7.2.0A onwards), TS 29.229 in four (6.3.13, 6.3.16, 6.3.19,
    6.3.64). It is a per-document convention, like `dotted-flags`, so the
    reading is declared; undeclared, it fails."""
    if ":: =" not in text:
        return text
    if not quirks.enabled("spaced-rule-operator"):
        raise ExtractionError(
            f"rule operator spelled ':: =' in {text!r}, which this document's"
            " source declaration does not read (the `spaced-rule-operator` quirk)"
        )
    quirks.fire("spaced-rule-operator")
    return text.replace(":: =", "::=")


def _find_rule_header(
    section: _Section, pattern: re.Pattern, quirks: sources.Quirks
) -> tuple[re.Match, int] | None:
    for index, line in enumerate(section.lines):
        text = _rule_text(line.text, quirks)
        if "::=" in text:
            match = pattern.match(text)
            if match is None:
                raise ExtractionError(
                    f"{section.number}: malformed rule header {line.text!r}"
                )
            return match, index + 1
    return None


def _extract_grouped(
    section: _Section,
    header: re.Match,
    body_start: int,
    name: str,
    quirks: sources.Quirks,
    warnings: list[str],
    commented: _Commented,
) -> ast.GroupedAvp:
    vendor = header["vendor"]
    avps, _, struck = _abnf_body(
        section.lines, body_start, name, section.number, quirks, warnings
    )
    grouped = ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=int(header["code"]),
        vendor_id=None if vendor is None else int(vendor),
        avps=avps,
    )
    if struck:
        commented.append((grouped, struck))
    return grouped
