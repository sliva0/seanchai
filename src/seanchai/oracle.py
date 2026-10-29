"""Cross-check extracted values against Wireshark's Diameter dictionary.

The corpus's corrections so far are justified by internal consistency — a
clause checked against the same document's own table. Wireshark's dictionary
is maintained independently, from the same specifications, which makes it an
oracle for the facts both record: an AVP's code, its vendor space and its
type. Only 29.329 has been verified by hand; this is what lets the other
extracted values be checked at scale.

It is an oracle for *values*, not for the type vocabulary. Wireshark's
`typedefn`s include `IPAddress`, `VendorId`, `AppId`, `OctetStringOrUTF8` and
`MIPRegistrationRequest` — dissector conveniences, not Diameter types — so
the comparison maps each onto the RFC 6733 types it stands for before it may
call anything a disagreement. The mapping is a closed vocabulary like the
extractor's column labels: an unmapped dictionary type is reported, never
guessed at.

Disagreement is a report, not a verdict — Wireshark is a second independent
reading of the same specifications, not a primary source. It can lag a
release, carry its own typos, or deliberately disambiguate a name the
specifications share; each finding names both sides and leaves the judgement
to a reader with the primary specification open. The fix goes wherever the
mistake turns out to be: a corpus correction, or a merge request into
Wireshark.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path

from .dad import ast

_ENTITY_RE = re.compile(
    r'<!ENTITY\s+(?P<name>[A-Za-z0-9_]+)\s+SYSTEM\s+"(?P<file>[^"]+)"\s*>'
)
_PROLOG_RE = re.compile(r"<\?xml[^>]*\?>")
_DOCTYPE_RE = re.compile(r"<!DOCTYPE.*?\]>", re.DOTALL)
_PI_RE = re.compile(r"<\?[^>]*\?>")


class OracleError(ValueError):
    """The dictionary directory cannot be read as Wireshark's dictionary."""


@dataclass(frozen=True)
class DictionaryAvp:
    """One `<avp>` element, with its vendor symbol resolved to a number."""

    name: str
    code: int
    vendor: int
    type_name: str | None  # None for a grouped AVP with no <type>
    grouped: bool
    enumerated: bool


# What each Wireshark type may stand for, in RFC 6733's vocabulary. The
# fifteen real types map to themselves; the dissector conveniences map to the
# type the specifications print. `OctetStringOrUTF8` is Wireshark hedging
# where different specs disagree, so both readings are acceptable.
_ACCEPTABLE: dict[str, frozenset[ast.DataType]] = {
    **{data_type.value: frozenset({data_type}) for data_type in ast.DataType},
    # NASREQ and the 3GPP specs type their IPv4/IPv6-carrying AVPs
    # OctetString (RFC 4005's Framed-IP-Address, 29.061's 3GPP-CG-Address);
    # `IPAddress` is how the dissector displays them, not a claim the
    # specifications type them Address.
    "IPAddress": frozenset({ast.DataType.ADDRESS, ast.DataType.OCTET_STRING}),
    "VendorId": frozenset({ast.DataType.UNSIGNED32}),
    "AppId": frozenset({ast.DataType.UNSIGNED32}),
    "OctetStringOrUTF8": frozenset(
        {ast.DataType.OCTET_STRING, ast.DataType.UTF8_STRING}
    ),
    "MIPRegistrationRequest": frozenset({ast.DataType.OCTET_STRING}),
    # Wireshark types any AVP with a value table `Enumerated` so the
    # dissector shows labels — including RFC 6733's Result-Code, which the
    # RFC types Unsigned32. The display type therefore agrees with any of
    # the integer types a specification actually prints (Enumerated itself
    # derives from Integer32).
    "Enumerated": frozenset(
        {
            ast.DataType.ENUMERATED,
            ast.DataType.UNSIGNED32,
            ast.DataType.INTEGER32,
        }
    ),
}


@dataclass
class Oracle:
    """The parsed dictionary: every AVP by `(vendor, code)` identity.

    A list per identity rather than a single entry: Wireshark's own TGPP file
    warns that some 3GPP AVP codes collide across applications, and both
    claimants have to stay visible for the comparison to say which one the
    corpus agrees with.
    """

    avps: dict[tuple[int, int], list[DictionaryAvp]] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: Path) -> Oracle:
        """Parse `dictionary.xml` with its vendor entity files inlined.

        The dictionary splits itself across files with XML entities, which
        `ElementTree` does not resolve for security reasons — and these files
        are fetched pinned and validated, so inlining them textually keeps
        the stdlib parser and drops nothing.
        """
        try:
            text = (directory / "dictionary.xml").read_text(encoding="utf-8")
        except OSError as error:
            raise OracleError(
                f"cannot read the dictionary at {directory}: {error}"
            ) from error
        entities = {match["name"]: match["file"] for match in _ENTITY_RE.finditer(text)}
        # `dictionary.ent` is pulled in as a parameter entity and declares
        # `Custom` with a literal value — the empty string in a stock
        # checkout, entity references when a user extends the dictionary.
        # Its declarations sit outside comments; the commented examples
        # around them deliberately do not parse as declarations here because
        # comment stripping happens first.
        internal = {}
        try:
            ent = (directory / "dictionary.ent").read_text(encoding="utf-8")
        except OSError:
            ent = ""
        for source in (re.sub(r"<!--.*?-->", "", ent, flags=re.DOTALL), text):
            for match in re.finditer(
                r'<!ENTITY\s+(?P<name>[A-Za-z0-9_]+)\s+"(?P<value>[^"]*)"', source
            ):
                internal.setdefault(match["name"], match["value"])
        text = _DOCTYPE_RE.sub("", text)

        def _inlined(match: re.Match) -> str:
            if match["name"] in internal:
                return internal[match["name"]]
            file_name = entities.get(match["name"])
            if file_name is None:
                raise OracleError(f"undeclared entity &{match['name']};")
            try:
                included = (directory / file_name).read_text(encoding="utf-8")
            except OSError as error:
                raise OracleError(
                    f"entity file {file_name} is missing: {error}"
                ) from error
            return _PROLOG_RE.sub("", included)

        text = re.sub(r"&(?P<name>[A-Za-z0-9_]+);", _inlined, text)
        text = _PI_RE.sub("", text)
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as error:
            raise OracleError(f"dictionary.xml does not parse: {error}") from error

        vendors = {"None": 0}
        for vendor in root.iter("vendor"):
            vendors[vendor.attrib["vendor-id"]] = int(vendor.attrib["code"])

        oracle = cls()
        for avp in root.iter("avp"):
            symbol = avp.attrib.get("vendor-id", "None")
            if symbol not in vendors:
                raise OracleError(
                    f"AVP {avp.attrib.get('name')!r} names the"
                    f" undeclared vendor {symbol!r}"
                )
            type_element = avp.find("type")
            entry = DictionaryAvp(
                name=avp.attrib["name"],
                code=int(avp.attrib["code"]),
                vendor=vendors[symbol],
                type_name=(
                    type_element.attrib["type-name"]
                    if type_element is not None
                    else None
                ),
                grouped=avp.find("grouped") is not None,
                enumerated=avp.find("enum") is not None,
            )
            oracle.avps.setdefault((entry.vendor, entry.code), []).append(entry)
        if not oracle.avps:
            raise OracleError("dictionary.xml holds no AVPs")
        return oracle

    def name_for(
        self, vendor_id: int, code: int, name: str, data_type: ast.DataType | None
    ) -> str | None:
        """Wireshark's name for the AVP the corpus calls `name`, or None when
        the dictionary has no entry under `(vendor-id, code)` or cannot say
        which of several is meant.

        Where the identity collides (Wireshark's TGPP file warns some 3GPP
        codes do), an entry spelled like the corpus is the answer, then the
        one name among the entries whose type agrees with `data_type`.
        """
        entries = self.avps.get((vendor_id, code), [])
        if any(entry.name == name for entry in entries):
            return name
        names = {entry.name for entry in entries}
        if len(names) > 1 and data_type is not None:
            names = {
                entry.name
                for entry in entries
                if data_type in (_acceptable(entry) or frozenset())
            }
        return names.pop() if len(names) == 1 else None


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.message}"


def _acceptable(entry: DictionaryAvp) -> frozenset[ast.DataType] | None:
    """The corpus types this dictionary entry agrees with, or None when the
    dictionary type is outside the mapped vocabulary."""
    if entry.grouped:
        return frozenset({ast.DataType.GROUPED})
    if entry.enumerated:
        # Wireshark types enumerated AVPs as their wire type; the enum
        # children are what say a value list exists.
        return (
            _ACCEPTABLE.get(entry.type_name, frozenset())
            if entry.type_name
            else frozenset()
        ) | {ast.DataType.ENUMERATED}
    if entry.type_name is None:
        return None
    return _ACCEPTABLE.get(entry.type_name)


@dataclass(frozen=True)
class _Claim:
    """One (name, identity, type) fact the corpus asserts and the oracle can
    check. Definitions and table rows both reduce to this."""

    name: str
    vendor: int
    code: int
    data_type: ast.DataType | None
    where: str


def _claims(spec: ast.Specification) -> list[_Claim]:
    reused = {
        row.name
        for section in spec.sections
        if isinstance(section, ast.ReusedAvps)
        for row in section.rows
    }
    claims = []
    seen: set[tuple[str, int, int]] = set()
    for section in spec.sections:
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
            if section.name in reused:
                # The origin document's copy is the one to check; this file's
                # re-print is compared against the origin by the linter.
                continue
            claims.append(
                _Claim(
                    name=section.name,
                    vendor=section.vendor_id if section.vendor_id is not None else 0,
                    code=section.code,
                    data_type=ast.DataType.GROUPED
                    if isinstance(section, ast.GroupedAvp)
                    else ast.DataType.ENUMERATED,
                    where=f"clause {section.source.section}",
                )
            )
        elif isinstance(section, ast.AvpTable):
            for row in section.rows:
                if row.code is None or row.name in reused:
                    continue
                claims.append(
                    _Claim(
                        name=row.name,
                        vendor=spec.vendor_id,
                        code=row.code,
                        data_type=row.data_type,
                        where="AVP table",
                    )
                )
    unique = []
    for claim in claims:
        key = (claim.name, claim.vendor, claim.code)
        if key not in seen:
            seen.add(key)
            unique.append(claim)
    return unique


def crosscheck(spec: ast.Specification, oracle: Oracle) -> list[Finding]:
    """Every disagreement between one file and the dictionary.

    Absence is reported apart from disagreement: an AVP the dictionary lacks
    may simply postdate the pinned Wireshark release, while an AVP whose code
    resolves to a differently-named or differently-typed entry means one of
    the two projects read the specification wrong.
    """
    findings = []
    absent = []
    for claim in _claims(spec):
        entries = oracle.avps.get((claim.vendor, claim.code))
        if not entries:
            absent.append(claim.name)
            continue
        named = [entry for entry in entries if entry.name == claim.name]
        if not named:
            others = ", ".join(sorted({entry.name for entry in entries}))
            findings.append(
                Finding(
                    "name-disagrees",
                    f"{claim.name} ({claim.where}): the dictionary calls"
                    f" (vendor {claim.vendor}, code {claim.code}) {others}",
                )
            )
            continue
        if claim.data_type is None:
            continue
        acceptable = frozenset[ast.DataType]()
        unmapped = None
        for entry in named:
            mapped = _acceptable(entry)
            if mapped is None:
                unmapped = entry.type_name
                continue
            acceptable |= mapped
        if unmapped is not None and not acceptable:
            findings.append(
                Finding(
                    "type-unmapped",
                    f"{claim.name} ({claim.where}): dictionary type"
                    f" {unmapped!r} is outside the mapped vocabulary",
                )
            )
            continue
        if claim.data_type not in acceptable:
            spelled = ", ".join(sorted(entry.type_name or "Grouped" for entry in named))
            findings.append(
                Finding(
                    "type-disagrees",
                    f"{claim.name} ({claim.where}): corpus says"
                    f" {claim.data_type.value}, the dictionary says {spelled}",
                )
            )
    if absent:
        findings.append(
            Finding(
                "absent-from-dictionary",
                f"{len(absent)} AVPs are not in the dictionary:"
                f" {', '.join(sorted(absent))}",
            )
        )
    return findings
