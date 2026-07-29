#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["python-diameter", "seanchai"]
#
# [tool.uv.sources]
# seanchai = { path = "../..", editable = true }
# ///
"""Validate the python-diameter library against one specification's `.dad`.

This is the *validate* consumer direction over the model: the
[python-diameter](https://github.com/mensonen/diameter) library holds one
class per command that tries to serve every specification using that command
at once, plus global AVP dictionaries keyed by code. Validating the whole of
such a class against any one document would mis-report every AVP the class
carries for the *other* documents — but each specification's claims are still
checkable one at a time: its commands must exist under the right codes with
the right members, and its own AVPs must be right in the global dictionary.

What is checked, against the named specification:

- Every command the specification defines has a library class with that
  command code, with a Request/Answer subclass for the message's direction.
- Every AVP in the command's ABNF body appears in that subclass's `avp_def`,
  identified by `(vendor-id, code)` — names differ freely between the
  library's attribute spelling and the specification's. The reverse
  direction reports library entries the body never mentions (which may be
  another specification's use of the command — read them against the scope),
  and `is_required` is compared against the ABNF's `{ }` / `[ ]` brackets.
- Every AVP the specification itself defines is looked up in the library's
  dictionary for the file's own `; Vendor-ID:` — present, same name, a value
  type consistent with the specification's, and a mandatory default matching
  the AVP-table flag rules.

Self-contained via inline script metadata — uv supplies the library and
seanchai. The argument is the reference re-used rows cite, with the bare
number accepted as shorthand:

    uv run integrations/python_diameter/validate.py TS29.229
    uv run integrations/python_diameter/validate.py 29.229
    uv run integrations/python_diameter/validate.py RFC7155

Exits 1 when anything disagrees. The report is a statement about two
artifacts: a "missing" finding against a library pinned to an older release
of the document may simply be that release's truth, and reading the findings
against their clauses is the reader's part of the job.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

from seanchai import corpus, model
from seanchai.dad import ast

# The specification's value type against the library's Avp classes that can
# faithfully carry it. DiameterIdentity and DiameterURI are UTF-8 text on the
# wire and the library holds them as either string class; everything else
# maps one-to-one.
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
}


def command_classes() -> dict[int, type]:
    """The library's base command classes, keyed by command code.

    A base class (`UserAuthorization`) carries the code; its Request/Answer
    subclasses carry the per-direction `avp_def`. The bases are found by
    scanning the commands module rather than by naming them, so a command the
    library adds is picked up without touching this script.
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


def check_message(message: model.Message, bases: dict[int, type]) -> list[str]:
    """One spec command body against the library class serving its code."""
    base = bases.get(message.command_code)
    if base is None:
        return [
            f"{message.name}: the library has no command class for code"
            f" {message.command_code}"
        ]
    findings = []
    request = ast.CommandFlag.REQUEST in message.flags
    cls = direction_class(base, request)
    if cls is None:
        return [
            f"{message.name}: {base.__name__} has no"
            f" {'Request' if request else 'Answer'} subclass"
        ]
    cls_name = cls.__name__

    by_identity = {(d.vendor_id, d.avp_code): d for d in cls.avp_def}
    matched = set()
    for member in message.avps:
        if member.name == "AVP":
            continue
        identity = None if member.avp is None else member.avp.identity
        if identity is None:
            findings.append(
                f"{message.name}: {member.name} resolves to no"
                " (vendor-id, code) in the corpus, so it could not be checked"
            )
            continue
        entry = by_identity.get(identity)
        if entry is None:
            vendor, code = identity
            findings.append(
                f"{message.name}: {member.name} (vendor {vendor}, code {code},"
                f" {member.rule.presence.value}) is in clause {message.section}'s"
                f" ABNF but not in {cls_name}.avp_def"
            )
            continue
        matched.add(identity)
        required = member.rule.presence is not ast.Presence.OPTIONAL
        if entry.is_required != required:
            findings.append(
                f"{message.name}: {member.name} is"
                f" {member.rule.presence.value} in clause {message.section} but"
                f" {cls_name}.avp_def says"
                f" is_required={entry.is_required}"
            )
    for identity, entry in by_identity.items():
        if identity not in matched:
            vendor, code = identity
            findings.append(
                f"{message.name}: {cls_name}.avp_def carries {entry.attr_name}"
                f" (vendor {vendor}, code {code}), which clause"
                f" {message.section}'s ABNF does not mention"
            )
    return findings


def check_dictionary(avp: model.Avp, dictionary, where: str) -> list[str]:
    """One of the specification's own AVPs against the library's dictionary."""
    if avp.code is None:
        # A code-less row has nothing to key the library's dictionary with;
        # the linter's `row-without-code` rule reports it on the corpus side.
        return []
    info = dictionary.get(avp.code)
    subject = f"{avp.name} (code {avp.code})"
    if info is None:
        return [f"{subject}: absent from {where}"]
    findings = []
    if info["name"] != avp.name:
        findings.append(
            f"{subject}: the library names it {info['name']!r}, clause"
            f" {avp.section} spells it {avp.name!r}"
        )
    if info.get("vendor", 0) != avp.vendor_id:
        findings.append(
            f"{subject}: the library says vendor {info.get('vendor', 0)},"
            f" the specification says {avp.vendor_id}"
        )
    type_name = info["type"].__name__
    if avp.data_type is None:
        pass
    elif avp.data_type not in ACCEPTABLE:
        findings.append(
            f"{subject}: no mapping onto the library's classes for"
            f" {avp.data_type.value}, so the type was not checked"
        )
    elif type_name not in ACCEPTABLE[avp.data_type]:
        findings.append(
            f"{subject}: the library holds it as {type_name}, the"
            f" specification says {avp.data_type.value}"
        )
    if avp.flag_rules is not None:
        mandatory = info.get("mandatory", False)
        if ast.AvpFlag.MANDATORY in avp.flag_rules.must and not mandatory:
            findings.append(
                f"{subject}: the AVP table requires the M flag, the library"
                " defaults it off"
            )
        if ast.AvpFlag.MANDATORY in avp.flag_rules.must_not and mandatory:
            findings.append(
                f"{subject}: the AVP table forbids the M flag, the library"
                " defaults it on"
            )
    return findings


def reference_of(argument: str) -> str:
    """The corpus reference the argument names: `TS29.229`, `29.229`, or a
    full title like `3GPP TS 29.229`, all spelling the same document."""
    if re.fullmatch(r"\d{2}\.\d{3}", argument):
        return f"TS{argument}"
    try:
        return ast.spec_ref(argument)
    except ast.SpecRefError:
        return argument


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate.py <specification>   (e.g. TS29.229)", file=sys.stderr)
        return 2
    reference = reference_of(sys.argv[1])

    from diameter.message.avp.dictionary import AVP_DICTIONARY, AVP_VENDOR_DICTIONARY

    built = model.Model.build(corpus.Corpus.load([Path(__file__).parents[2] / "dad"]))
    try:
        messages = built.messages(reference)
    except model.ModelError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    findings: list[str] = []
    bases = command_classes()
    for message in messages:
        findings += check_message(message, bases)

    own = [avp for avp in built.avps(reference) if avp.defined_in == reference]
    for avp in own:
        # Per AVP, not per file: a document's own AVPs almost always share
        # its `; Vendor-ID:`, but a vendor-less definition is IETF-space and
        # lives in the library's base dictionary.
        if avp.vendor_id == ast.IETF_VENDOR:
            dictionary, where = AVP_DICTIONARY, "AVP_DICTIONARY"
        else:
            dictionary = AVP_VENDOR_DICTIONARY.get(avp.vendor_id, {})
            where = f"AVP_VENDOR_DICTIONARY[{avp.vendor_id}]"
        findings += check_dictionary(avp, dictionary, where)

    for finding in findings:
        print(finding)
    print(
        f"\n{len(findings)} disagreement{'s' if len(findings) != 1 else ''} across"
        f" {len(messages)} commands and {len(own)} {reference}-defined AVPs"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
