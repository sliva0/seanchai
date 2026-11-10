"""Enumerated AVPs: the value lines of a clause in every shape a
document's quirks declare, reserved, void and vendor-specific ranges, and
where a clause says its values are defined."""

from __future__ import annotations

import contextlib
import re

import pydantic

from ...dad import ast
from .. import sources
from ..errors import ExtractionError
from ._base import _Section

_ENUM_VALUE_RE = re.compile(r"^(?P<name>[A-Za-z0-9_-]+)\s*\((?P<value>\d+)\)$")
# A value line in the shapes the quirks below read, each part optional so the
# reading can say which quirk a line needed. Prose can end in "(n)" too, so
# every departure from `NAME (n)` is declared per document:
# - `dashed-enum-values`: a list dash printed as text, "- AUDIO (0)" (TS 29.214
#   clause 5.3.19, 29.272 7.3.128, 29.338 5.3.3.2);
# - `worded-enum-values`: a label in words, "Device Trigger Request (1)" (TS
#   29.368 clause 6.4.6, 29.214 5.3.25);
# - `hex-enum-values`: "OTHER (0xFFFFFFFF)" (TS 29.214 clause 5.3.19);
# - `punctuated-enum-values`: a list's comma or full stop after the value,
#   "- ONLY_IMSI_REQUESTED (0)," (TS 29.338 clause 5.3.3.5);
# - `described-enum-values`: the value's gloss on its own line, "NO (0) The
#   sending node is not GBA_U aware" (TS 29.109 clause 6.3.1.8);
# - `label-after-enum-value`: no name before the value and the label after
#   it, "- (0) Private user identity." (TS 29.109 clause 6.3.1.13).
_LOOSE_ENUM_VALUE_RE = re.compile(
    r"(?P<dash>- )?"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9_-]*(?P<words>(?:,? [A-Za-z0-9_-]+)+)?)?"
    r"\s*\((?:(?P<value>\d+)|0x(?P<hex>[0-9A-Fa-f]+))\)"
    r"\s*(?P<rest>.*)"
)
# Several `NAME (n)` printed in one paragraph with nothing between, read behind
# `run-on-enum-values`: TS 29.229 clause 6.3.58's "NOT_PRIVILEDGED_SENDER
# (0)PRIVILEDGED_SENDER (1)", one run in the docx and one line in the PDF.
_RUN_ON_ENUM_VALUES_RE = re.compile(r"(?:[A-Za-z0-9_-]+\s*\(\d+\)\s*){2,}")
# The word a document prints where it withdrew a value's label, in lower case:
# TS 29.214 clause 5.3.13's "Void (0)". Whichever reading found the value, the
# word is no name.
_VOID_LABEL = "void"
_RUN_ON_ENUM_VALUE_RE = re.compile(r"(?P<name>[A-Za-z0-9_-]+)\s*\((?P<value>\d+)\)")
_RESERVED_NOTE_RE = re.compile(
    r"[Vv]alues? (?P<first>\d+)(?:\s*(?:-|to)\s*(?P<last>\d+))?\s+(?:is|are) reserved"
)


def _extract_enumerated(
    section: _Section,
    name: str,
    code: int,
    vendor_id: int | None,
    quirks: sources.Quirks,
    warnings: list[str],
) -> ast.EnumeratedAvp:
    values: list[ast.EnumValue] = []
    ranges: list[ast.ReservedValues | ast.VoidValues | ast.VendorSpecificValues] = []
    # A clause's explanatory prose is not captured as a value description; only
    # the value lines and the reserved-value notes are read.
    #
    # `EnumValue.description` is a one-line gloss, and a 3GPP clause does not
    # contain one. It contains paragraphs, with lead-ins ("This value is
    # used:"), nested bullet lists, NOTEs and caveats about the AVP rather than
    # about any one value. Any rule for flattening that onto a `;` comment
    # picks an arbitrary subset: the rule that used to live here took
    # paragraphs styled B1 or B2, which meant 29.272 §7.3.24 kept two bullets
    # while dropping the "This value is used:" that introduced them, and
    # 29.229 §6.3.15 kept "The request is generated in the following cases:"
    # and dropped the cases. `; Section:` points at the clause; a reader who
    # wants the prose reads it there, undamaged.
    #
    # The one exception is a description printed on the value's own line
    # after a colon (TS 32.299 clause 7.2.132, "2 High priority: Lower than
    # Pre-emptive priority"): that is the document's own one-line gloss.
    for paragraph in section.paragraphs:
        text = paragraph.text
        if not text:
            continue
        if (
            quirks.enabled("list-numbered-enum-values")
            and paragraph.label is not None
            and (number := _LIST_VALUE_RE.fullmatch(paragraph.label))
        ):
            # TS 32.299 V11.20.0 clauses 7.2.132-7.2.151: the value is the
            # number Word's list renders before the label ("0 Participating
            # PoC Server", "1. Moderator" in the ETSI PDF), which the text
            # does not carry.
            match = _VALUE_FIRST_RE.fullmatch(f"{number['value']} {text}")
            if match is None:
                raise ExtractionError(
                    f"{section.number}: list-numbered value {text!r} is no value"
                )
            quirks.fire("list-numbered-enum-values")
            values.append(_value_first(match, section.number))
        elif match := _ENUM_VALUE_RE.fullmatch(text):
            values.append(ast.EnumValue(name=match["name"], value=int(match["value"])))
        elif value := _loose_enum_value(text, section.number, quirks):
            values.append(value)
        elif quirks.enabled("run-on-enum-values") and _RUN_ON_ENUM_VALUES_RE.fullmatch(
            text
        ):
            quirks.fire("run-on-enum-values")
            values.extend(
                ast.EnumValue(name=match["name"], value=int(match["value"]))
                for match in _RUN_ON_ENUM_VALUE_RE.finditer(text)
            )
        elif paragraph.style == "NO" and (match := _RESERVED_NOTE_RE.search(text)):
            first = int(match["first"])
            ranges.append(
                ast.ReservedValues(first=first, last=int(match["last"] or first))
            )
        elif any(
            quirks.enabled(name)
            for name in (
                "value-first-enums",
                "value-last-enums",
                "bracketed-enum-values",
                "dotted-enum-values",
            )
        ):
            for line in paragraph.lines:
                if (
                    quirks.enabled("value-last-enums")
                    and line.tabbed_number
                    and (match := _VALUE_LAST_RE.fullmatch(line.text))
                ):
                    quirks.fire("value-last-enums")
                    values.append(_value_first(match, section.number))
                elif quirks.enabled("bracketed-enum-values") and (
                    match := _BRACKETED_VALUE_RE.fullmatch(line.text)
                ):
                    quirks.fire("bracketed-enum-values")
                    values.append(_value_first(match, section.number))
                elif quirks.enabled("dotted-enum-values") and (
                    match := _DOTTED_VALUE_RE.fullmatch(line.text)
                ):
                    quirks.fire("dotted-enum-values")
                    values.append(_value_first(match, section.number))
                elif not quirks.enabled("value-first-enums"):
                    continue
                elif match := _VALUE_RANGE_RE.fullmatch(line.text):
                    # SM-Service-Type (TS 32.299 clause 7.2.213) closes its
                    # list with "11 .. 99 Reserved for 3GPP defined SM
                    # services" and "100 .. 199 Vendor specific SM services",
                    # oneM2M TS-0004's Protocol-Type (A.5.17) with "100 ..
                    # 199 Operator and vendor specific protocol types". The
                    # first is a reserved range, the others vendor-specific
                    # ones, which keep the words. Vendor wording decides
                    # before "Reserved" does: values reserved for vendor use
                    # are allocated to vendors. Any negation in the words
                    # ("Not for vendor-specific services") leaves the range
                    # unread, as does a range allocated otherwise, which
                    # names no value `.dad` can hold and is reported instead.
                    quirks.fire("value-first-enums")
                    first, last = int(match["first"]), int(match["last"])
                    label = match["label"]
                    vendor = _VENDOR_SPECIFIC_LABEL_RE.search(label)
                    if vendor and not _NEGATION_RE.search(label):
                        ranges.append(
                            ast.VendorSpecificValues(
                                first=first, last=last, description=label
                            )
                        )
                    elif not vendor and label.startswith("Reserved"):
                        ranges.append(ast.ReservedValues(first=first, last=last))
                    elif label.lower() == _VOID_LABEL:
                        ranges.append(ast.VoidValues(first=first, last=last))
                    else:
                        warnings.append(
                            f"{section.number}: value range {first}..{last}"
                            f" {match['label']!r} names no value and was not"
                            " recorded"
                        )
                elif match := _VALUE_FIRST_RE.fullmatch(line.text):
                    quirks.fire("value-first-enums")
                    values.append(_value_first(match, section.number))
    if quirks.enabled("prose-enum-values"):
        for paragraph in section.paragraphs:
            for match in _PROSE_ENUM_VALUE_RE.finditer(paragraph.text):
                quirks.fire("prose-enum-values")
                values.append(
                    ast.EnumValue(name=match["name"], value=int(match["value"]))
                )
    values_source = _values_source(section, quirks)
    if not values and not ranges and values_source is None:
        # Kept empty rather than dropped: the clause still says the AVP is
        # enumerated, and a value line in a shape no declared reading takes
        # shows up here rather than as a silently shorter list.
        warnings.append(f"{section.number}: enumerated AVP {name} lists no values")
    # A label with a gloss after it says more than the word does, and stays
    # the value it was printed as.
    merged = sorted(
        [
            ast.VoidValues(first=value.value, last=value.value)
            if value.name.lower() == _VOID_LABEL and value.description is None
            else value
            for value in values
        ]
        + ranges,
        key=lambda item: item.value if isinstance(item, ast.EnumValue) else item.first,
    )
    return ast.EnumeratedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=code,
        vendor_id=vendor_id,
        values_source=values_source,
        values=tuple(merged),
    )


# A value named in a sentence, read behind `prose-enum-values`: oneM2M TS-0004
# clause A.5.3, "The following value is currently defined for the
# Accounting-Record-Type AVP: EVENT_RECORD (value 1) for an Event Based
# request."
_PROSE_ENUM_VALUE_RE = re.compile(
    r"\b(?P<name>[A-Z][A-Z0-9_]*) \(value (?P<value>\d+)\)"
)


# Behind `external-enum-values`: an enumerated clause naming the document or
# clause its values are defined in, one lead-in per document's wording. What
# follows the lead-in is the source as printed, reference number included.
_VALUES_SOURCE_RES = (
    # TS 29.272 clauses 7.3.67, 7.3.137 and ten more: "The possible values
    # are those defined in TS 32.422 [23] for Trace Depth."
    re.compile(r"The possible values are those defined in (?P<source>.+?)\.?$"),
    # TS 29.212 clause 5.3.120: "The values defined in the Default-Access AVP
    # are the same as the ones defined in IP-CAN-Type AVP."
    re.compile(
        r"The values defined in the \S+ AVP are the same as the ones defined in"
        r" (?P<source>.+?)\.?$"
    ),
    # TS 29.061 clause 17.7.25: "The enumeration values are defined in 3GPP
    # TS 25.413 [92]."
    re.compile(r"The enumeration values are defined in (?P<source>.+?)\.?$"),
    # TS 32.299 clause 7.2.238: "The values are taken from OMNA WSP Content
    # Type Numbers [210]."
    re.compile(r"The values are taken from (?P<source>.+?)\.?$"),
    # oneM2M TS-0004 clause A.5.22: "... the type of operation requested.
    # The values are defined in Table 6.3.4.2.5-6.", A.5.25 likewise.
    re.compile(r"(?:^|\. )The values are defined in (?P<source>.+?)\.?$"),
    # TS 32.299 clause 7.2.20eA: "... and holds the identifier of the network
    # element as defined in TS 23.682[243], that triggers the API
    # notification." TS 23.682 V19.3.0 names the network elements but
    # numbers none of them.
    re.compile(
        r"holds the identifier of the network element as defined in"
        r" (?P<source>[^,]+),"
    ),
)


def _values_source(section: _Section, quirks: sources.Quirks) -> str | None:
    """Where the clause says its values are defined, if it says so in one of
    the wordings `_VALUES_SOURCE_RES` reads."""
    if not quirks.enabled("external-enum-values"):
        return None
    found = [
        match["source"]
        for paragraph in section.paragraphs
        for pattern in _VALUES_SOURCE_RES
        if (match := pattern.search(paragraph.text))
    ]
    if len(found) > 1:
        raise ExtractionError(
            f"{section.number}: the clause names {len(found)} sources for its"
            f" values: {found}"
        )
    if not found:
        return None
    quirks.fire("external-enum-values")
    return found[0]


# TS 32.299 writes its value lists value first, and labels values in words:
# "0 PS to CS Transfer" (clause 7.2.1B). The label ends at the first colon;
# what follows is the line's description ("2 High priority: Lower than
# Pre-emptive priority", clause 7.2.132).
_VALUE_RANGE_RE = re.compile(r"(?P<first>\d+) ?\.\. ?(?P<last>\d+) (?P<label>.+)")
# A range's words allocating it to vendors or operators: "Vendor specific SM
# services" (TS 32.299 clause 7.2.213), "Operator and vendor specific
# protocol types" (oneM2M TS-0004 clause A.5.17).
_VENDOR_SPECIFIC_LABEL_RE = re.compile(r"\b(?:vendor|operator)[ -]specific\b", re.I)
# Words that turn the allocation around: "Not for vendor-specific services".
_NEGATION_RE = re.compile(r"\b(?:not|no|never|except)\b", re.I)
_VALUE_FIRST_RE = re.compile(
    r"(?P<value>\d+) (?P<label>[^:]+?)(?: ?:(?: (?P<description>.*))?)?"
)


# TS 32.299 V11.20.0 writes most value lists label first, the value set off
# by tabs: "MONETARY<tabs>0" (clause 7.2.14), "Calling Party<tab>0"
# (7.2.124). Read only where the printed line has that tab
# (`_Line.tabbed_number`).
_VALUE_LAST_RE = re.compile(r"(?P<label>.+?) (?P<value>\d+)(?P<description>)")


# TS 32.299 V11.20.0's other value-first shapes: the value bracketed, "[0]
# called party" (clause 7.2.101), or followed by a full stop, "0.
# SUBMISSION" (7.2.207, 7.2.218); each read behind its own quirk.
_BRACKETED_VALUE_RE = re.compile(r"\[(?P<value>\d+)\] (?P<label>.+?)(?P<description>)")
_DOTTED_VALUE_RE = re.compile(r"(?P<value>\d+)\. (?P<label>.+?)(?P<description>)")
# A list number Word renders before a value, behind `list-numbered-enum-values`:
# "0", or "1." (TS 32.299 V11.20.0 clause 7.2.151).
_LIST_VALUE_RE = re.compile(r"(?P<value>\d+)\.?")


# A label read out of prose is taken only in the shape a value name takes in
# the documents: words of letters, digits, `-`, `_` and parentheses, single
# spaces between (TS 32.299's "VAS4SMS Short Message Virtual Private Network
# (VPN)", 7.2.213). `.dad` can quote any label, but a line of prose that
# happens to follow a value is no label, and this is what turns it away.
_VALUE_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_()-]*(?: [A-Za-z0-9_()-]+)*")


def _loose_enum_value(
    text: str, section: str, quirks: sources.Quirks
) -> ast.EnumValue | None:
    """A value line departing from `NAME (n)` only in ways the document
    declares (`_LOOSE_ENUM_VALUE_RE`), else None, as for any other prose."""
    match = _LOOSE_ENUM_VALUE_RE.fullmatch(text)
    if match is None:
        return None
    needed = []
    if match["dash"]:
        needed.append("dashed-enum-values")
    if match["words"]:
        needed.append("worded-enum-values")
    if match["words"] and "," in match["words"]:
        # TS 29.140 V7.0.0 clause 6.3.5: "MM1 Message Submission, Profile
        # based (0)", a label `.dad` quotes (docs/grammar.md, quoted-name).
        needed.append("comma-enum-labels")
    if match["hex"]:
        needed.append("hex-enum-values")
    name, rest, description = match["name"], match["rest"], None
    if rest in {",", "."}:
        needed.append("punctuated-enum-values")
    elif rest and name:
        needed.append("described-enum-values")
        description = rest
    elif rest:
        # TS 29.109 clause 6.3.1.13 labels "- (0) Private user identity." after
        # the value; the full stop ends the sentence, not the label.
        needed.append("label-after-enum-value")
        name = rest.removesuffix(".")
    if name is None or not all(quirks.enabled(quirk) for quirk in needed):
        return None
    for quirk in needed:
        quirks.fire(quirk)
    value = int(match["value"]) if match["hex"] is None else int(match["hex"], 16)
    if _VALUE_LABEL_RE.fullmatch(name.replace(", ", " ")):
        with contextlib.suppress(pydantic.ValidationError):
            return ast.EnumValue(name=name, value=value, description=description)
    raise ExtractionError(f"{section}: enumerated value line {text!r} is no value name")


def _value_first(match: re.Match, section: str) -> ast.EnumValue:
    if _VALUE_LABEL_RE.fullmatch(match["label"]):
        with contextlib.suppress(pydantic.ValidationError):
            return ast.EnumValue(
                name=match["label"],
                value=int(match["value"]),
                description=match["description"] or None,
            )
    raise ExtractionError(
        f"{section}: enum value label {match['label']!r} is not a value name"
    )
