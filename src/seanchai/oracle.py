"""Cross-check extracted AVPs against Wireshark's Diameter dictionary.

Wireshark's dictionary is an independent reading of the same
specifications, so it can check each AVP's code, vendor and type. Its
dissector-specific types (`IPAddress`, `VendorId`, `AppId`, ...) are mapped
onto RFC 6733 types through a closed table; an unmapped type is reported.

A finding names both sides and decides nothing: Wireshark can lag a
release or carry its own errors. The fix goes into a corpus correction or
into Wireshark.
"""

from __future__ import annotations

import os
import re
import tomllib
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from ._prose import collapse_fields
from .dad import ast
from .errors import SeanchaiError

__all__ = [
    "Alias",
    "Claim",
    "DictionaryAvp",
    "Finding",
    "Oracle",
    "OracleError",
    "claims",
    "crosscheck",
    "load_aliases",
]

_ENTITY_RE = re.compile(
    r'<!ENTITY\s+(?P<name>[A-Za-z0-9_]+)\s+SYSTEM\s+"(?P<file>[^"]+)"\s*>'
)
_PROLOG_RE = re.compile(r"<\?xml[^>]*\?>")
_DOCTYPE_RE = re.compile(r"<!DOCTYPE.*?\]>", re.DOTALL)
_PI_RE = re.compile(r"<\?[^>]*\?>")


class OracleError(SeanchaiError, ValueError):
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
    # Its `<enum>` elements, by code: what the dictionary names the AVP's values.
    values: tuple[tuple[int, str], ...] = ()


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

    Each identity holds a list, since some 3GPP codes collide across
    applications.
    """

    avps: dict[tuple[int, int], list[DictionaryAvp]] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: str | os.PathLike[str]) -> Oracle:
        """Parse `dictionary.xml` with its entity files inlined as text.

        `ElementTree` does not resolve XML entities; the files are pinned
        downloads, so inlining them is safe.
        """
        try:
            directory = Path(directory)
            text = (directory / "dictionary.xml").read_text(encoding="utf-8")
        except (OSError, TypeError) as error:
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
                values=tuple(
                    (int(enum.attrib["code"]), enum.attrib["name"])
                    for enum in avp.findall("enum")
                ),
            )
            oracle.avps.setdefault((entry.vendor, entry.code), []).append(entry)
        if not oracle.avps:
            raise OracleError("dictionary.xml holds no AVPs")
        return oracle

    def name_for(
        self, vendor_id: int, code: int, name: str, data_type: ast.DataType | None
    ) -> str | None:
        """Wireshark's name for the AVP the corpus calls `name`, or None if
        no entry, or no single entry, matches `(vendor-id, code)`.

        On a colliding identity, an entry spelled like `name` wins, then the
        only name among entries whose type agrees with `data_type`.
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
    # The reason of the accepted alias acknowledging the finding, which
    # makes it agreement rather than a disagreement (`Alias`).
    accepted_by: str | None = None

    def __str__(self) -> str:
        if self.accepted_by is None:
            return f"[{self.rule}] {self.message}"
        return f"accepted[{self.rule}] {self.message} ({self.accepted_by})"


@dataclass(frozen=True)
class Alias:
    """A deliberate Wireshark rename accepted as agreement (TS 29.229's
    `User-Data` is `Cx-User-Data`). It holds only while vendor, code and type
    agree."""

    specification: str  # the `SpecRef` of the document, `TS29.229`
    name: str
    wireshark: str
    reason: str


_ALIAS_KEYS = frozenset({"specification", "name", "wireshark", "reason"})


def load_aliases(path: Path) -> tuple[Alias, ...]:
    """The `[[alias]]` entries of an aliases file
    (`integrations/wireshark/aliases.toml`). Each must have exactly the
    expected keys, at most one per document and name."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise OracleError(f"cannot read the aliases at {path}: {error}") from error
    if data.keys() - {"alias"}:
        raise OracleError(f"{path}: only [[alias]] tables belong here")
    aliases = []
    seen: set[tuple[str, str]] = set()
    for number, table in enumerate(data.get("alias", []), 1):
        if not isinstance(table, dict) or table.keys() != _ALIAS_KEYS:
            raise OracleError(
                f"{path}: alias {number} needs exactly the keys"
                f" {', '.join(sorted(_ALIAS_KEYS))}"
            )
        if not all(
            isinstance(value, str) and value.strip() for value in table.values()
        ):
            raise OracleError(f"{path}: alias {number} has an empty or non-text value")
        alias = Alias(**collapse_fields(table, {"reason"}))
        if (alias.specification, alias.name) in seen:
            raise OracleError(
                f"{path}: {alias.specification} {alias.name} is aliased twice"
            )
        seen.add((alias.specification, alias.name))
        aliases.append(alias)
    return tuple(aliases)


def _acceptable(entry: DictionaryAvp) -> frozenset[ast.DataType] | None:
    """The corpus types this entry agrees with, or None for an unmapped
    dictionary type."""
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
class Claim:
    """One (name, identity, type) fact a definition or table row asserts."""

    name: str
    vendor: int
    code: int
    data_type: ast.DataType | None
    where: str


def claims(spec: ast.Specification) -> list[Claim]:
    """One file's claims about its own AVPs, once per name and identity,
    excluding re-used names."""
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
                Claim(
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
                # A row's V flag says its vendor space where it says one: TS
                # 29.273 tabulates RFC 5778's MIP-Session-Key with V in Must
                # not, IETF space, in a vendor 10415 file.
                stated = row.stated_vendor(spec.vendor_id)
                claims.append(
                    Claim(
                        name=row.name,
                        vendor=spec.vendor_id if stated is None else stated,
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


def _value_findings(spec: ast.Specification, oracle: Oracle) -> list[Finding]:
    """Value-table names that differ from the dictionary's `<enum>`s for the
    same AVP, and, where the dictionary enumerates the AVP, values it
    lacks."""
    by_name: dict[str, dict[int, str]] = {}
    for entries in oracle.avps.values():
        for entry in entries:
            if entry.values:
                by_name.setdefault(entry.name, {}).update(entry.values)
    findings = []
    for table in spec.sections:
        if not isinstance(table, ast.ValueTable) or table.avp not in by_name:
            continue
        known = by_name[table.avp]
        absent = []
        for row in table.rows:
            number = (
                row.value
                if table.kind is ast.ValueKind.RESULT_CODES
                else 1 << row.value
            )
            found = known.get(number)
            if found is None:
                absent.append(row.name)
            elif found != row.name:
                clause = row.section or table.source.section
                findings.append(
                    Finding(
                        "value-disagrees",
                        f"{table.avp} {row.value} is {row.name} (clause {clause}):"
                        f" the dictionary calls it {found}",
                    )
                )
        if absent:
            findings.append(
                Finding(
                    "value-absent-from-dictionary",
                    f"{len(absent)} values of {table.avp} (clause"
                    f" {table.source.section}) are not in the dictionary:"
                    f" {', '.join(absent)}",
                )
            )
    return findings


def crosscheck(
    spec: ast.Specification, oracle: Oracle, aliases: Iterable[Alias] = ()
) -> list[Finding]:
    """Every disagreement between one file and the dictionary.

    Absence is reported separately from disagreement, since the pinned
    Wireshark release may predate an AVP.

    A name disagreement is accepted (`Finding.accepted_by`) when an alias in
    `aliases` names the dictionary entry and the claim's known type matches
    it. An alias that no longer holds is a `stale-alias` finding. A claim
    with no type neither confirms nor stales an alias; it stays a
    `name-disagrees` finding.
    """
    mine: dict[str, Alias] = {}
    for alias in aliases:
        if alias.specification == ast.spec_ref(spec.specification):
            mine[alias.name] = alias
    findings = []
    absent = []
    claimed: set[str] = set()
    for claim in claims(spec):
        alias = mine.get(claim.name)
        claimed.add(claim.name)
        entries = oracle.avps.get((claim.vendor, claim.code))
        identity = f"(vendor {claim.vendor}, code {claim.code})"
        if not entries:
            absent.append(claim.name)
            if alias is not None:
                findings.append(
                    _stale(claim, alias, f"the dictionary has nothing at {identity}")
                )
            continue
        calls = (
            f"the dictionary calls {identity}"
            f" {', '.join(sorted({entry.name for entry in entries}))}"
        )
        named = [entry for entry in entries if entry.name == claim.name]
        if named:
            if alias is not None:
                findings.append(_stale(claim, alias, calls))
            problem = _type_problem(claim, named)
            if problem is not None:
                where = f"{claim.name} ({claim.where})"
                findings.append(replace(problem, message=f"{where}: {problem.message}"))
            continue
        if alias is None:
            findings.append(
                Finding("name-disagrees", f"{claim.name} ({claim.where}): {calls}")
            )
            continue
        renamed = [entry for entry in entries if entry.name == alias.wireshark]
        problem = _type_problem(claim, renamed) if renamed else None
        if not renamed:
            findings.append(_stale(claim, alias, calls))
        elif problem is not None:
            findings.append(_stale(claim, alias, problem.message))
        elif claim.data_type is None:
            findings.append(
                Finding(
                    "name-disagrees",
                    f"{claim.name} ({claim.where}): {calls}; the accepted rename"
                    f" {alias.wireshark} is unconfirmed, the corpus stating no type",
                )
            )
        else:
            findings.append(
                Finding(
                    "name-disagrees",
                    f"{claim.name} ({claim.where}): {calls}",
                    accepted_by=alias.reason,
                )
            )
    for name in sorted(mine.keys() - claimed):
        findings.append(
            Finding(
                "stale-alias",
                f"{name}: the accepted rename {mine[name].wireshark} names no AVP"
                " the file defines or tabulates",
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
    findings.extend(_value_findings(spec, oracle))
    return findings


def _stale(claim: Claim, alias: Alias, why: str) -> Finding:
    return Finding(
        "stale-alias",
        f"{claim.name} ({claim.where}): the accepted rename {alias.wireshark}"
        f" does not hold: {why}",
    )


def _type_problem(claim: Claim, named: list[DictionaryAvp]) -> Finding | None:
    """A finding (message without the claim's name) if the entries `named`
    disagree with the claim's type, else None, also when the claim has no
    type."""
    if claim.data_type is None:
        return None
    acceptable = frozenset[ast.DataType]()
    unmapped = None
    for entry in named:
        mapped = _acceptable(entry)
        if mapped is None:
            unmapped = entry.type_name
            continue
        acceptable |= mapped
    if unmapped is not None and not acceptable:
        return Finding(
            "type-unmapped",
            f"dictionary type {unmapped!r} is outside the mapped vocabulary",
        )
    if claim.data_type in acceptable:
        return None
    spelled = ", ".join(sorted(entry.type_name or "Grouped" for entry in named))
    return Finding(
        "type-disagrees",
        f"corpus says {claim.data_type.value}, the dictionary says {spelled}",
    )
