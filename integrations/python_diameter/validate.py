"""Validate the python-diameter library against specifications' `.dad` files.

[python-diameter](https://github.com/mensonen/diameter) has one class per
command, serving every specification that uses it, and global AVP
dictionaries keyed by code. A class is therefore checked against one
specification's claims at a time, not as a whole:

- Every command the specification defines has a library class with that
  command code, with a Request/Answer subclass for the message's direction.
- Every AVP in the command's ABNF body appears in that subclass's `avp_def`,
  matched by `(vendor-id, code)`, not by name. Library entries the body
  never mentions are reported too (they may belong to another
  specification). `is_required` is compared with the ABNF's `{ }` / `[ ]`
  brackets, and an explicit `is_mandatory` with the reading's M bit.
- Every AVP the specification defines is in the library's dictionary under
  the file's `; Vendor-ID:`, with the same name, a consistent value type and
  a mandatory default matching the AVP-table flag rules.
- With `--grouped`, every Grouped AVP a command reaches has a `type_class`
  whose `avp_def` matches the AVP's body, at any depth.

The library's AVP names follow Wireshark's dictionary, so a name that is
Wireshark's for the identity is counted, not reported, unless `--names` is
given.

uv supplies seanchai and a library from the inline script metadata;
`--library` names another. A reference is a SpecRef, or just its number:

    uv run integrations/python_diameter/validate.py TS29.229
    uv run integrations/python_diameter/validate.py 29.229 RFC7155
    uv run integrations/python_diameter/validate.py --all --summary-only
    uv run integrations/python_diameter/validate.py --claimed \
        --library ~/src/diameter --enumerated-as-integer --no-flags --grouped

Exits 1 when anything disagrees. A "missing" finding against a library that
follows an older release of the document may be correct for that release.
README.md beside this script describes the options.
"""

from __future__ import annotations

import argparse
import inspect
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from seanchai import corpus, model
from seanchai.dad import ast

_HERE = Path(__file__).parent
# What the library's README claims, for `--claimed` with no path.
CLAIMED = _HERE / "claimed.txt"
# Where the downloader puts Wireshark's dictionary, for `--wireshark` not given.
WIRESHARK = _HERE.parent.parent / "specifications" / "wireshark"

# The specification's value type against the library's Avp classes that can
# faithfully carry it. DiameterIdentity, DiameterURI and the filter rules are
# text on the wire and the library holds them as either string class;
# everything else maps one-to-one.
ACCEPTABLE = {
    ast.DataType.OCTET_STRING: {"AvpOctetString"},
    ast.DataType.UTF8_STRING: {"AvpUtf8String"},
    ast.DataType.INTEGER32: {"AvpInteger32"},
    ast.DataType.INTEGER64: {"AvpInteger64"},
    ast.DataType.UNSIGNED32: {"AvpUnsigned32"},
    ast.DataType.UNSIGNED64: {"AvpUnsigned64"},
    ast.DataType.FLOAT32: {"AvpFloat32"},
    ast.DataType.FLOAT64: {"AvpFloat64"},
    ast.DataType.GROUPED: {"AvpGrouped"},
    ast.DataType.ENUMERATED: {"AvpEnumerated"},
    ast.DataType.TIME: {"AvpTime"},
    ast.DataType.ADDRESS: {"AvpAddress"},
    ast.DataType.DIAMETER_IDENTITY: {"AvpUtf8String", "AvpOctetString"},
    ast.DataType.DIAMETER_URI: {"AvpUtf8String", "AvpOctetString"},
    ast.DataType.IP_FILTER_RULE: {"AvpUtf8String", "AvpOctetString"},
    ast.DataType.QOS_FILTER_RULE: {"AvpUtf8String", "AvpOctetString"},
}

Identity = tuple[int, int]
# What a set of documents says a command or a grouped AVP holds: a command by
# its code and direction, the way a library class serves it whichever document
# or application it is, and a grouped AVP by its identity.
Holder = tuple[str, int, int]
Mentions = dict[Holder, set[Identity]]


class Kind(StrEnum):
    """What a finding is about, for the summary's columns."""

    COMMAND = "command"  # no class, or no subclass for the direction
    MISSING = "missing"  # in the ABNF, not in avp_def
    REQUIRED = "required"  # is_required against the brackets
    EXTRA = "extra"  # in avp_def, not in the ABNF
    OVERRIDE = "override"  # an explicit is_mandatory against the M bit
    GROUPED = "grouped"  # a Grouped AVP with no type_class
    ABSENT = "absent"  # no dictionary entry
    NAME = "name"  # the dictionary spells it otherwise
    VENDOR = "vendor"  # the dictionary files it under another vendor
    TYPE = "type"  # the dictionary's value class
    FLAG = "flag"  # the dictionary's mandatory default against the M bit
    UNCHECKED = "unchecked"  # the corpus gives nothing to compare


@dataclass(frozen=True)
class Finding:
    kind: Kind
    text: str
    # A name finding where the library's name is Wireshark's for the identity.
    follows_wireshark: bool = False


@dataclass(frozen=True)
class Options:
    """What the command line asks to hold against the library."""

    # Extras any document here mentions in the same holder go unreported; None
    # reports every extra.
    mentions: Mentions | None = None
    enumerated_as_integer: bool = False
    flags: bool = True
    grouped: bool = False
    # Report a name that is Wireshark's as well.
    names: bool = False


def command_holder(code: int, request: bool) -> Holder:
    return ("command", code, int(request))


def grouped_holder(identity: Identity) -> Holder:
    return ("grouped", *identity)


class LibraryError(Exception):
    """`--library` names no checkout, or imports something else."""


def use_library(path: Path) -> None:
    """Import `diameter` from a checkout, or its `src/`, ahead of the installed
    package, and refuse to go on with any other. Bytecode stays out of a tree
    that is someone else's."""
    root = path.expanduser().resolve()
    found = next(
        (
            source
            for source in (root / "src", root)
            if (source / "diameter" / "__init__.py").is_file()
        ),
        None,
    )
    if found is None:
        raise LibraryError(f"{path} holds neither src/diameter/ nor diameter/")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(found))
    import diameter

    imported = Path(diameter.__file__).resolve()
    if not imported.is_relative_to(found):
        raise LibraryError(f"`diameter` came from {imported}, not from {found}")


def command_classes() -> dict[int, type]:
    """The library's base command classes, keyed by command code.

    A base class (`UserAuthorization`) carries the code; its Request/Answer
    subclasses carry the per-direction `avp_def`. The bases are found by
    scanning the commands module, so new library commands need no change
    here.
    """
    import diameter.message.commands as commands
    from diameter.message._base import DefinedMessage

    found = {}
    for name, obj in inspect.getmembers(commands, inspect.isclass):
        if (
            issubclass(obj, DefinedMessage)
            and obj is not DefinedMessage
            and not name.endswith(("Request", "Answer"))
        ):
            found[obj.code] = obj
    return found


def direction_class(base: type, request: bool) -> type | None:
    suffix = "Request" if request else "Answer"
    for subclass in base.__subclasses__():
        if subclass.__name__.endswith(suffix):
            return subclass
    return None


def identity_of(member: model.Member) -> Identity | None:
    """The member's `(vendor-id, code)`, read off a hole too: an AVP whose
    document states no flag rules (RFC 4072's EAP-Payload) still has an
    identity to look up in `avp_def`."""
    if member.avp is not None:
        return member.avp.identity
    hole = member.hole
    if hole is None or hole.vendor_id is None or hole.code is None:
        return None
    return (hole.vendor_id, hole.code)


def m_bit_conflict(flag_rules, mandatory: bool) -> str | None:
    """What the rules say against an M bit: `requires` or `forbids`, or None
    where they leave it open."""
    if flag_rules is None:
        return None
    if ast.AvpFlag.MANDATORY in flag_rules.must and not mandatory:
        return "requires"
    if ast.AvpFlag.MANDATORY in flag_rules.must_not and mandatory:
        return "forbids"
    return None


def check_members(
    who: str,
    body: Iterable[model.Member],
    holder: type,
    key: Holder,
    where: str,
    options: Options,
) -> list[Finding]:
    """One body, a command's or a grouped AVP's, against the class holding it."""
    name = holder.__name__
    findings = []
    by_identity = {(d.vendor_id, d.avp_code): d for d in holder.avp_def}
    matched = set()
    for member in body:
        if member.name == "AVP":
            continue
        identity = identity_of(member)
        if identity is None:
            findings.append(
                Finding(
                    Kind.UNCHECKED,
                    f"{who}: {member.name} resolves to no (vendor-id, code) in the"
                    f" corpus ({member.hole}), so it could not be checked",
                )
            )
            continue
        entry = by_identity.get(identity)
        if entry is None:
            vendor, code = identity
            findings.append(
                Finding(
                    Kind.MISSING,
                    f"{who}: {member.name} (vendor {vendor}, code {code},"
                    f" {member.rule.presence.value}) is in {where}'s ABNF but not"
                    f" in {name}.avp_def",
                )
            )
            continue
        matched.add(identity)
        required = member.rule.presence is not ast.Presence.OPTIONAL
        if entry.is_required != required:
            findings.append(
                Finding(
                    Kind.REQUIRED,
                    f"{who}: {member.name} is {member.rule.presence.value} in"
                    f" {where} but {name}.avp_def says"
                    f" is_required={entry.is_required}",
                )
            )
        if options.flags and member.avp is not None and entry.is_mandatory is not None:
            conflict = m_bit_conflict(member.avp.flag_rules, entry.is_mandatory)
            if conflict is not None:
                findings.append(
                    Finding(
                        Kind.OVERRIDE,
                        f"{who}: {member.name}'s reading {conflict} the M flag, but"
                        f" {name}.avp_def says is_mandatory={entry.is_mandatory}",
                    )
                )
    known = options.mentions.get(key, set()) if options.mentions is not None else set()
    for identity, entry in by_identity.items():
        if identity not in matched and identity not in known:
            vendor, code = identity
            findings.append(
                Finding(
                    Kind.EXTRA,
                    f"{who}: {name}.avp_def carries {entry.attr_name}"
                    f" (vendor {vendor}, code {code}), which {where}'s ABNF does"
                    " not mention",
                )
            )
    return findings


def grouped_reached(
    body: Iterable[model.Member], holder: type
) -> Iterator[tuple[model.Grouped, type | None]]:
    """Every Grouped AVP a body names, with the class `holder.avp_def` decodes
    it into. An entry `holder` lacks is the caller's finding already."""
    by_identity = {(d.vendor_id, d.avp_code): d for d in holder.avp_def}
    for member in body:
        if isinstance(member.avp, model.Grouped):
            entry = by_identity.get(member.avp.identity)
            if entry is not None:
                yield member.avp, entry.type_class


def check_grouped(
    who: str,
    body: Iterable[model.Member],
    holder: type,
    options: Options,
    seen: set[tuple],
) -> list[Finding]:
    """The grouped classes a body reaches, at any depth. Each class is held
    against each body once per document, whichever commands reach it."""
    findings = []
    for avp, type_class in grouped_reached(body, holder):
        checked = (type_class, avp.identity, avp.defined_in)
        if checked in seen:
            continue
        seen.add(checked)
        if type_class is None:
            findings.append(
                Finding(
                    Kind.GROUPED,
                    f"{who}: {avp.name} (vendor {avp.vendor_id}, code {avp.code})"
                    f" is Grouped but {holder.__name__}.avp_def gives no type_class,"
                    " so its members are not attributes",
                )
            )
            continue
        where = f"{avp.defined_in} clause {avp.section}"
        key = grouped_holder(avp.identity)
        findings += check_members(
            avp.name, avp.members, type_class, key, where, options
        )
        findings += check_grouped(avp.name, avp.members, type_class, options, seen)
    return findings


def check_message(
    message: model.Message,
    bases: dict[int, type],
    options: Options,
    seen: set[tuple],
) -> list[Finding]:
    """One spec command body against the library class serving its code."""
    base = bases.get(message.command_code)
    if base is None:
        return [
            Finding(
                Kind.COMMAND,
                f"{message.name}: the library has no command class for code"
                f" {message.command_code}",
            )
        ]
    request = ast.CommandFlag.REQUEST in message.flags
    cls = direction_class(base, request)
    if cls is None:
        return [
            Finding(
                Kind.COMMAND,
                f"{message.name}: {base.__name__} has no"
                f" {'Request' if request else 'Answer'} subclass",
            )
        ]
    findings = check_members(
        message.name,
        message.avps,
        cls,
        command_holder(message.command_code, request),
        f"clause {message.section}",
        options,
    )
    if options.grouped:
        findings += check_grouped(message.name, message.avps, cls, options, seen)
    return findings


def same_name(first: str, second: str) -> bool:
    """Whether two names differ in case and `-`/`_` at most, which the library
    may normalise."""

    def folded(name: str) -> str:
        return name.replace("-", "").replace("_", "").casefold()

    return folded(first) == folded(second)


def check_dictionary(
    avp: model.Avp | model.Hole, dictionary, where: str, options: Options
) -> list[Finding]:
    """One of the specification's own AVPs against the library's dictionary.

    A hole is checked on what its document does state.
    """
    if avp.code is None:
        # A code-less row has nothing to key the library's dictionary with;
        # the linter's `row-without-code` rule reports it on the corpus side.
        return []
    info = dictionary.get(avp.code)
    subject = f"{avp.name} (code {avp.code})"
    if info is None:
        return [Finding(Kind.ABSENT, f"{subject}: absent from {where}")]
    findings = []
    if info["name"] != avp.name:
        findings.append(
            Finding(
                Kind.NAME,
                f"{subject}: the library names it {info['name']!r},"
                f" {f'clause {avp.section}' if avp.section else 'its table'} spells"
                f" it {avp.name!r}",
                follows_wireshark=avp.wireshark_name is not None
                and same_name(info["name"], avp.wireshark_name),
            )
        )
    if info.get("vendor", 0) != avp.vendor_id:
        findings.append(
            Finding(
                Kind.VENDOR,
                f"{subject}: the library says vendor {info.get('vendor', 0)},"
                f" the specification says {avp.vendor_id}",
            )
        )
    type_name = info["type"].__name__
    acceptable = ACCEPTABLE.get(avp.data_type) if avp.data_type else None
    if options.enumerated_as_integer and avp.data_type is ast.DataType.ENUMERATED:
        acceptable = {"AvpEnumerated", "AvpInteger32"}
    if avp.data_type is None:
        pass
    elif acceptable is None:
        findings.append(
            Finding(
                Kind.UNCHECKED,
                f"{subject}: no mapping onto the library's classes for"
                f" {avp.data_type.value}, so the type was not checked",
            )
        )
    elif type_name not in acceptable:
        findings.append(
            Finding(
                Kind.TYPE,
                f"{subject}: the library holds it as {type_name}, the"
                f" specification says {avp.data_type.value}",
            )
        )
    if options.flags:
        conflict = m_bit_conflict(avp.flag_rules, info.get("mandatory", False))
        if conflict is not None:
            state = "off" if conflict == "requires" else "on"
            findings.append(
                Finding(
                    Kind.FLAG,
                    f"{subject}: the AVP table {conflict} the M flag, the library"
                    f" defaults it {state}",
                )
            )
    return findings


def mentions_in(built: model.Model, references: Iterable[str]) -> Mentions:
    """What the documents' bodies name, per command and direction, and per
    grouped AVP at any depth."""
    mentions: Mentions = {}

    def note(key: Holder, body: Iterable[model.Member]) -> None:
        holding = mentions.setdefault(key, set())
        for member in body:
            identity = identity_of(member)
            if identity is not None:
                holding.add(identity)

    for reference in references:
        pending: list[model.Avp | model.Hole] = list(built.avps(reference))
        for message in built.messages(reference):
            request = ast.CommandFlag.REQUEST in message.flags
            note(command_holder(message.command_code, request), message.avps)
            pending += [m.avp for m in message.avps if m.avp is not None]
        seen = set()
        while pending:
            avp = pending.pop()
            if isinstance(avp, model.Grouped) and id(avp) not in seen:
                seen.add(id(avp))
                note(grouped_holder(avp.identity), avp.members)
                pending += [m.avp for m in avp.members if m.avp is not None]
    return mentions


@dataclass(frozen=True)
class Report:
    reference: str
    commands: int
    avps: int
    findings: list[Finding]
    # Name findings left out for following Wireshark's dictionary.
    hidden_names: int = 0


def check_document(
    built: model.Model, reference: str, bases: dict[int, type], options: Options
) -> Report:
    from diameter.message.avp.dictionary import AVP_DICTIONARY, AVP_VENDOR_DICTIONARY

    messages = built.messages(reference)
    findings: list[Finding] = []
    seen: set[tuple] = set()
    for message in messages:
        findings += check_message(message, bases, options, seen)

    own: list[model.Avp | model.Hole] = [
        avp for avp in built.avps(reference) if avp.defined_in == reference
    ]
    own += [
        hole
        for hole in built.holes(reference)
        if hole.reference == reference and hole.vendor_id is not None
    ]
    for avp in own:
        # Per AVP, not per file: a document's own AVPs almost always share
        # its `; Vendor-ID:`, but a vendor-less definition is IETF-space and
        # lives in the library's base dictionary.
        assert avp.vendor_id is not None
        if avp.vendor_id == ast.IETF_VENDOR:
            dictionary, where = AVP_DICTIONARY, "AVP_DICTIONARY"
        else:
            dictionary = AVP_VENDOR_DICTIONARY.get(avp.vendor_id, {})
            where = f"AVP_VENDOR_DICTIONARY[{avp.vendor_id}]"
        findings += check_dictionary(avp, dictionary, where, options)
    kept = [f for f in findings if options.names or not f.follows_wireshark]
    return Report(reference, len(messages), len(own), kept, len(findings) - len(kept))


def summary(reports: list[Report]) -> list[str]:
    """One row per document and a total, with a column for every kind any
    document has."""
    counts = [Counter(finding.kind for finding in r.findings) for r in reports]
    kinds = [kind for kind in Kind if any(count[kind] for count in counts)]
    heading = ["reference", "commands", "avps", "findings", *kinds]
    rows = [
        [
            report.reference,
            report.commands,
            report.avps,
            len(report.findings),
            *(count[kind] for kind in kinds),
        ]
        for report, count in zip(reports, counts, strict=True)
    ]
    total = ["total", *(sum(row[i] for row in rows) for i in range(1, len(heading)))]
    table = [heading, *rows, total]
    widths = [max(len(str(row[i])) for row in table) for i in range(len(heading))]
    return [
        "  ".join(
            str(cell).ljust(width) if i == 0 else str(cell).rjust(width)
            for i, (cell, width) in enumerate(zip(row, widths, strict=True))
        ).rstrip()
        for row in table
    ]


def hidden_line(hidden: int) -> str:
    """What the reports left out, for a line after the summary."""
    names = "name" if hidden == 1 else "names"
    return f"hidden: {hidden} {names} following Wireshark's dictionary (--names shows)"


def reference_of(argument: str) -> str:
    """The corpus reference the argument names: `TS29.229`, `29.229`, or a
    full title like `3GPP TS 29.229`, all spelling the same document."""
    if re.fullmatch(r"\d{2}\.\d{3}", argument):
        return f"TS{argument}"
    try:
        return ast.spec_ref(argument)
    except ast.SpecRefError:
        return argument


def read_claimed(path: Path) -> list[str]:
    """The references a file lists, one per line, `#` starting a comment."""
    lines = path.read_text(encoding="utf-8").splitlines()
    named = (line.partition("#")[0].strip() for line in lines)
    return [reference_of(line) for line in named if line]


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate python-diameter against specifications' .dad files."
    )
    parser.add_argument(
        "specifications", nargs="*", help="references, e.g. TS29.229 or 29.229"
    )
    parser.add_argument(
        "--all", action="store_true", help="every specification the corpus holds"
    )
    parser.add_argument(
        "--claimed",
        type=Path,
        nargs="?",
        const=CLAIMED,
        metavar="FILE",
        help="the references a file lists, by default what the library's README"
        " claims; checks them, or just the named specifications, and implies"
        " --ignore-extras over exactly that set",
    )
    parser.add_argument(
        "--library",
        type=Path,
        metavar="PATH",
        help="a python-diameter checkout or its src/, imported ahead of the"
        " installed package",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        help="the corpus directory (default: the installed seanchai-corpus)",
    )
    parser.add_argument(
        "--ignore-extras",
        action="store_true",
        help="report an avp_def entry the ABNF does not mention only if no"
        " checked specification mentions it in that command",
    )
    parser.add_argument(
        "--enumerated-as-integer",
        action="store_true",
        help="accept AvpInteger32 for an Enumerated AVP",
    )
    parser.add_argument(
        "--no-flags", action="store_true", help="do not compare M bits at all"
    )
    parser.add_argument(
        "--grouped",
        action="store_true",
        help="also hold the grouped classes against the AVPs' bodies",
    )
    parser.add_argument(
        "--wireshark",
        type=Path,
        metavar="PATH",
        help="a Wireshark Diameter dictionary directory, for the names the library"
        " takes from it (default: this repository's specifications/wireshark,"
        " when there is one)",
    )
    parser.add_argument(
        "--names",
        action="store_true",
        help="also report a name that is Wireshark's for the identity",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="print the summary without the findings",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.all and (args.specifications or args.claimed):
        arguments.error("--all names every specification, so name none besides")
    if not (args.all or args.specifications or args.claimed):
        arguments.error("name specifications, or pass --all or --claimed")

    if args.library is not None:
        try:
            use_library(args.library)
        except LibraryError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    import diameter

    print(f"library: {diameter.__file__}")

    books = corpus.Corpus.load([args.corpus or corpus.installed_directory()])
    wireshark = args.wireshark
    if wireshark is None and (WIRESHARK / "dictionary.xml").is_file():
        wireshark = WIRESHARK
    try:
        built = model.Model.build(books, wireshark=wireshark)
        claimed = None
        if args.claimed:
            claimed = [built.canonical(name) for name in read_claimed(args.claimed)]
        if args.all:
            references = list(built.references())
        elif args.specifications:
            named = map(reference_of, args.specifications)
            references = list(dict.fromkeys(built.canonical(name) for name in named))
        else:
            references = list(dict.fromkeys(claimed or ()))
    except (model.ModelError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    mentions = None
    if claimed is not None:
        mentions = mentions_in(built, claimed)
    elif args.ignore_extras:
        if len(references) == 1:
            print(
                "note: --ignore-extras over one specification hides nothing;"
                " name the set, or pass --claimed",
                file=sys.stderr,
            )
        mentions = mentions_in(built, references)
    options = Options(
        mentions=mentions,
        enumerated_as_integer=args.enumerated_as_integer,
        flags=not args.no_flags,
        grouped=args.grouped,
        names=args.names,
    )
    bases = command_classes()
    reports = [check_document(built, r, bases, options) for r in references]

    several = len(reports) > 1
    for report in reports:
        if args.summary_only:
            continue
        if several:
            print(f"\n== {report.reference}")
        for finding in report.findings:
            print(finding.text)
    if several or args.summary_only:
        print()
        print("\n".join(summary(reports)))
    else:
        report = reports[0]
        count = len(report.findings)
        print(
            f"\n{count} disagreement{'s' if count != 1 else ''} across"
            f" {report.commands} commands and {report.avps}"
            f" {report.reference}-defined AVPs"
        )
    hidden = sum(report.hidden_names for report in reports)
    if hidden:
        print(hidden_line(hidden))
    return 1 if any(report.findings for report in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
