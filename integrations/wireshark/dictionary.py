#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["seanchai", "seanchai-corpus"]
#
# [tool.uv.sources]
# seanchai = { path = "../..", editable = true }
# seanchai-corpus = { path = "../../packages/seanchai-corpus", editable = true }
# ///
"""Write a Wireshark Diameter dictionary from the corpus.

The reverse of `seanchai corpus crosscheck`: the AVPs and commands a selection
of documents or applications reaches, as `seanchai dictionary` selects them,
in the XML Wireshark reads from `resources/protocols/diameter/`, for testing
a dissector or a tool reading that format.

    uv run integrations/wireshark/dictionary.py --application 16777251 -o out/
    uv run integrations/wireshark/dictionary.py --document TS29.229 -o out/

`dictionary.xml` holds the base types, every IETF AVP and the vendors, and
includes one file per document with its applications, their commands and
the vendor AVPs it defines. An AVP is written once, from its defining reading
where the selection holds it; a name another identity already takes is the
one `aliases.toml` gives it, or else is suffixed with its vendor and code.
What the format cannot hold is listed in each file's header comment and in
`--report`: see README.md.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from seanchai import dictionary, model, oracle
from seanchai.corpus import Corpus
from seanchai.dad import ast

_ROOT = Path(__file__).resolve().parent.parent.parent
_ALIASES = Path(__file__).resolve().parent / "aliases.toml"

# Wireshark's typedefn per corpus type, and each derived type's parent, as
# its own dictionary.xml declares them.
_TYPES = {
    ast.DataType.OCTET_STRING: None,
    ast.DataType.UTF8_STRING: "OctetString",
    ast.DataType.ADDRESS: "OctetString",
    ast.DataType.DIAMETER_IDENTITY: "OctetString",
    ast.DataType.IP_FILTER_RULE: "OctetString",
    ast.DataType.QOS_FILTER_RULE: "OctetString",
    ast.DataType.INTEGER32: None,
    ast.DataType.INTEGER64: None,
    ast.DataType.UNSIGNED32: None,
    ast.DataType.UNSIGNED64: None,
    ast.DataType.FLOAT32: None,
    ast.DataType.FLOAT64: None,
    ast.DataType.TIME: None,
    ast.DataType.ENUMERATED: "Integer32",
    ast.DataType.DIAMETER_URI: "UTF8String",
}
# The symbols Wireshark's dictionary names vendors by, where the corpus uses
# them; another vendor is `Vendor<id>`.
_SYMBOLS = {0: "None", 10415: "TGPP", 5535: "3GPP2", 13019: "ETSI", 45687: "oneM2M"}
_FLAGS = (
    ("must", "must"),
    ("may", "may"),
    ("should_not", "shouldnot"),
    ("must_not", "mustnot"),
)
# A name as Wireshark's own entries spell them, which its reader takes: no
# space or punctuation but `.`, `-` and `_`. The DTD calls `name` an ID, which
# may not start with a digit; the dictionary holds fifty that do
# (`3GPP-IMSI`), so this does not hold it to that.
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")


@dataclass
class Written:
    """The files, by name, and what the format could not hold, by document."""

    files: dict[str, str]
    left_out: dict[str, list[str]] = field(default_factory=dict)

    def note(self, reference: str, what: str) -> None:
        self.left_out.setdefault(reference, []).append(what)


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _flag(rules: dictionary.FlagRules, flag: ast.AvpFlag) -> str | None:
    for column, value in _FLAGS:
        if flag in getattr(rules, column):
            return value
    return None


def _symbol(vendor: int) -> str:
    return _SYMBOLS.get(vendor, f"Vendor{vendor}")


def _file_name(reference: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", reference) + ".xml"


class _Writer:
    def __init__(
        self, built: dictionary.Dictionary, aliases: Sequence[oracle.Alias]
    ) -> None:
        self.built = built
        self.written = Written({})
        renamed = {
            (alias.specification, alias.name): alias.wireshark for alias in aliases
        }
        # One reading per identity: the defining one where the output holds
        # it, else the first by id.
        chosen: dict[tuple[int, int], dictionary.Avp] = {}
        for avp in sorted(built.avps, key=lambda each: (not each.defining, each.id)):
            chosen.setdefault((avp.vendor_id, avp.code), avp)
        self.avps = dict(sorted(chosen.items()))
        for identity, avp in self.avps.items():
            others = [
                each.id
                for each in built.avps
                if (each.vendor_id, each.code) == identity and each.id != avp.id
            ]
            if others:
                self.written.note(
                    avp.defined_in,
                    f"{avp.name} ({identity[0]}:{identity[1]}): one reading of"
                    f" {len(others) + 1}, the defining one",
                )
        self.names: dict[tuple[int, int], str] = {}
        taken: set[str] = set()
        for identity, avp in self.avps.items():
            name = renamed.get((avp.defined_in, avp.name), avp.name)
            if name in taken or not _NAME_RE.match(name):
                spelled = re.sub(r"[^A-Za-z0-9_-]", "-", name)
                name = f"{spelled}-{identity[0]}-{identity[1]}"
                if not _NAME_RE.match(name):
                    name = f"AVP-{name}"
                self.written.note(
                    avp.defined_in,
                    f"{avp.name} ({identity[0]}:{identity[1]}): named {name},"
                    " the name being taken or no XML name",
                )
            taken.add(name)
            self.names[identity] = name
        self.ids = {avp.id: (avp.vendor_id, avp.code) for avp in built.avps}
        self.enums = self._values()
        self.session = self.names.get((0, 263))

    def _values(self) -> dict[tuple[int, int], dict[int, str]]:
        """Each identity's `<enum>`s: an Enumerated reading's values, the
        result codes the value tables name, and each bit table's masks."""
        found: dict[tuple[int, int], dict[int, str]] = {}
        for identity, avp in self.avps.items():
            for value in avp.values:
                if value.kind == "value" and value.name and value.value is not None:
                    found.setdefault(identity, {}).setdefault(value.value, value.name)
                elif value.kind != "value":
                    self.written.note(
                        avp.defined_in,
                        f"{avp.name}: the {value.kind} range"
                        f" {value.first}..{value.last}",
                    )
        for table in sorted(
            self.built.value_tables, key=lambda t: (t.reference, t.section)
        ):
            if table.kind is ast.ValueKind.FEATURES:
                self.written.note(
                    table.reference,
                    f"the features of {table.avp} in {table.application}, table"
                    f" {table.table}",
                )
                continue
            if table.kind is ast.ValueKind.RESULT_CODES:
                identity = (0, 298) if table.vendor_id else (0, 268)
            else:
                identities = {
                    self.ids[each] for each in table.avp_ids if each in self.ids
                }
                if len(identities) != 1:
                    continue
                (identity,) = identities
            if identity not in self.avps:
                continue
            for row in table.rows:
                code = (
                    row.value
                    if table.kind is ast.ValueKind.RESULT_CODES
                    else 1 << row.value
                )
                held = found.setdefault(identity, {})
                if code in held and held[code] != row.name:
                    self.written.note(
                        table.reference,
                        f"{table.avp} {code}: {row.name}, which"
                        f" {held[code]} already names",
                    )
                held.setdefault(code, row.name)
        return found

    def avp(self, identity: tuple[int, int], indent: str) -> list[str]:
        avp = self.avps[identity]
        rules = avp.flag_rules
        attributes = [f'name="{_xml(self.names[identity])}"', f'code="{avp.code}"']
        for key, flag in (
            ("mandatory", ast.AvpFlag.MANDATORY),
            ("protected", ast.AvpFlag.PROTECTED),
            ("vendor-bit", ast.AvpFlag.VENDOR),
        ):
            if (value := _flag(rules, flag)) is not None:
                attributes.append(f'{key}="{value}"')
        if avp.may_encrypt is not None:
            attributes.append(f'may-encrypt="{"yes" if avp.may_encrypt else "no"}"')
        if avp.vendor_id:
            attributes.append(f'vendor-id="{_symbol(avp.vendor_id)}"')
        lines = [f"{indent}<avp {' '.join(attributes)}>"]
        members = [
            self.names[self.ids[member.avp]]
            for member in avp.members
            if member.avp is not None and self.ids[member.avp] in self.names
        ]
        anything = any(member.kind == "wildcard" for member in avp.members)
        substituted = avp.kind == "grouped" and not members and anything
        if substituted and self.session:
            # Only `* { AVP }`, Failed-AVP's: `<grouped>` holds one `<gavp>` at
            # least, and Wireshark's own entry names Session-Id under a
            # comment saying it holds any AVP.
            members = [self.session]
            self.written.note(
                avp.defined_in, f"{avp.name}: holds any AVP, written as Session-Id"
            )
        if avp.kind == "grouped" and members:
            lines.append(f"{indent}\t<grouped>")
            if substituted:
                lines.append(f"{indent}\t\t<!-- This grouped AVP holds any AVP -->")
            lines.extend(f'{indent}\t\t<gavp name="{_xml(name)}"/>' for name in members)
            lines.append(f"{indent}\t</grouped>")
            for member in avp.members:
                if member.kind != "avp":
                    self.written.note(
                        avp.defined_in,
                        f"{avp.name}: its member {member.name} ({member.kind})",
                    )
        else:
            if avp.data_type is ast.DataType.GROUPED:
                self.written.note(
                    avp.defined_in,
                    f"{avp.name}: Grouped with no member to list, written OctetString",
                )
            data_type = (
                ast.DataType.OCTET_STRING
                if avp.data_type is ast.DataType.GROUPED
                else avp.data_type
            )
            lines.append(f'{indent}\t<type type-name="{data_type.value}"/>')
            lines.extend(
                f'{indent}\t<enum name="{_xml(name)}" code="{code}"/>'
                for code, name in sorted(self.enums.get(identity, {}).items())
            )
        lines.append(f"{indent}</avp>")
        return lines

    def run(self) -> Written:
        documents: dict[str, list[dictionary.Application]] = {}
        for application in self.built.applications:
            documents.setdefault(application.reference, []).append(application)
        # Where each vendor AVP is written: its defining document's file, where
        # one is written, else dictionary.xml's base.
        homes: dict[str, list[tuple[int, int]]] = {}
        base: list[tuple[int, int]] = []
        for identity, avp in self.avps.items():
            if identity[0] and avp.defined_in in documents:
                homes.setdefault(avp.defined_in, []).append(identity)
            else:
                base.append(identity)
        for reference, applications in sorted(documents.items()):
            lines = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                f"<!-- Written by Seanchaí from {reference}"
                " (integrations/wireshark/dictionary.py). -->",
            ]
            seen: set[int | None] = set()
            for application in applications:
                if (
                    application.application_id in seen
                    or application.application_id is None
                ):
                    continue
                seen.add(application.application_id)
                identifier = application.application_id
                name = application.name or f"{reference} {identifier}"
                lines.append(f'<application id="{identifier}" name="{_xml(name)}">')
                lines.extend(self.commands(application.commands, "\t"))
                if len(seen) == 1:
                    for identity in homes.pop(reference, []):
                        lines.extend(self.avp(identity, "\t"))
                lines.append("</application>")
            for identity in homes.pop(reference, []):
                # A document whose commands print no application id.
                base.append(identity)
            self.written.files[_file_name(reference)] = "\n".join(lines) + "\n"
        for identities in homes.values():
            base.extend(identities)
        self.written.files["dictionary.xml"] = self.dictionary(
            sorted(documents), sorted(base)
        )
        return self.written

    def commands(
        self, commands: Iterable[dictionary.Command], indent: str
    ) -> list[str]:
        named: dict[int, str] = {}
        for command in commands:
            named.setdefault(
                command.command_code,
                re.sub(r"-(Request|Answer)$", "", command.name),
            )
        return [
            f'{indent}<command name="{_xml(name)}" code="{code}" vendor-id="None"/>'
            for code, name in sorted(named.items())
        ]

    def dictionary(
        self, documents: Sequence[str], base: Sequence[tuple[int, int]]
    ) -> str:
        entities = {
            reference: f"doc{index}" for index, reference in enumerate(documents)
        }
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<!-- Written by Seanchaí (integrations/wireshark/dictionary.py)"
            f" from {', '.join(documents) or 'the corpus'}. -->",
            '<!DOCTYPE dictionary SYSTEM "dictionary.dtd" [',
            *(
                f'\t<!ENTITY {entity} SYSTEM "{_file_name(reference)}">'
                for reference, entity in entities.items()
            ),
            "]>",
            "<dictionary>",
            '\t<base uri="https://www.rfc-editor.org/rfc/rfc6733">',
        ]
        unscoped = [
            command
            for application in self.built.applications
            if application.application_id is None
            for command in application.commands
        ]
        lines.extend(self.commands(unscoped, "\t\t"))
        for data_type, parent in _TYPES.items():
            parented = f' type-parent="{parent}"' if parent else ""
            lines.append(f'\t\t<typedefn type-name="{data_type.value}"{parented}/>')
        for identity in base:
            lines.extend(self.avp(identity, "\t\t"))
        lines.append("\t</base>")
        lines.extend(f"\t&{entity};" for entity in entities.values())
        for vendor in sorted({identity[0] for identity in self.avps} | {0}):
            names = {each.vendor_id: each.name for each in self.built.vendors}
            lines.append(
                f'\t<vendor vendor-id="{_symbol(vendor)}" code="{vendor}"'
                f' name="{_xml(names.get(vendor) or _symbol(vendor))}"/>'
            )
        lines.append("</dictionary>")
        return "\n".join(lines) + "\n"


def generate(
    built: dictionary.Dictionary, aliases: Sequence[oracle.Alias] = ()
) -> Written:
    """The dictionary's files for `built`, and what they leave out."""
    return _Writer(built, aliases).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--document", action="append", default=[], metavar="REF")
    parser.add_argument(
        "--application", action="append", default=[], type=int, metavar="ID"
    )
    parser.add_argument(
        "--corpus", type=Path, help="another corpus than the installed one"
    )
    parser.add_argument("--aliases", type=Path, default=_ALIASES)
    parser.add_argument(
        "--report", action="store_true", help="print what the format left out"
    )
    arguments = parser.parse_args(argv)
    books = Corpus.load([arguments.corpus]) if arguments.corpus else Corpus.installed()
    built = model.Model.build(
        books,
        holes=model.HolePolicy.ANY if arguments.corpus else model.HolePolicy.RECORDED,
    )
    written = generate(
        dictionary.build(
            built,
            corpus_version=books.version,
            documents=arguments.document,
            application_ids=arguments.application,
        ),
        oracle.load_aliases(arguments.aliases),
    )
    output: Path = arguments.output
    output.mkdir(parents=True, exist_ok=True)
    for name, text in written.files.items():
        (output / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(written.files)} files to {output}", file=sys.stderr)
    if arguments.report:
        for reference, notes in sorted(written.left_out.items()):
            print(f"{reference}:")
            for note in notes:
                print(f"  {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
