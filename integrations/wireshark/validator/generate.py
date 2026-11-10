#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["seanchai", "seanchai-corpus"]
#
# [tool.uv.sources]
# seanchai = { path = "../../..", editable = true }
# seanchai-corpus = { path = "../../../packages/seanchai-corpus", editable = true }
# ///
"""Write the Wireshark plugin that validates Diameter traffic against the corpus.

The rules are `seanchai dictionary`'s, as a Lua table: every reading of every
AVP the selected commands reach, with its type, flag rules, members and values,
the commands keyed by application id, command code and direction, the
`<answer-message>` each answer takes with the E bit set, and the result codes
and bits the documents name. `core.lua` checks a PDU against them and
`plugin.lua` draws the result; the output is one file holding all three, for
Wireshark's plugin directory.

    uv run integrations/wireshark/validator/generate.py \\
        -o ~/.local/lib/wireshark/plugins/seanchai_diameter.lua
    uv run integrations/wireshark/validator/generate.py --application 16777216 \\
        --application 16777251 -o seanchai_diameter.lua
    uv run integrations/wireshark/validator/generate.py --rules-only -o rules.lua

Where several documents define one command under one application id, every one
is a candidate and the plugin reports against the best match, except a document
a newer one in the corpus obsoletes (`OBSOLETED_BY`), which the corpus holds
only because others cite it. README.md beside this script says what is checked.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from seanchai import __version__, corpus, dictionary, model
from seanchai.dad import ast

HERE = Path(__file__).parent

# A document the corpus holds because others cite it, which a newer RFC in the
# corpus obsoletes: its header says so. RFC 7155: "Obsoletes: 4005"; RFC 8506:
# "Obsoletes: 4006". Their commands are no candidates where the newer
# document's are.
OBSOLETED_BY = {"RFC4005": "RFC7155", "RFC4006": "RFC8506"}

# RFC 6733 section 7.2's rule, for an E-bit answer to a command no document
# defines.
BASE_ANSWER = "RFC6733/RFC6733:7.2"


def lua_string(text: str) -> str:
    """`text` as a Lua string literal that every Lua from 5.1 reads alike."""
    out = ['"']
    for char in text:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif code < 32 or code == 127:
            out.append(f"\\{code:03d}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _flag_letters(values: Iterable[str]) -> str:
    return lua_string("".join(sorted(values)))


def _body(members: Iterable[dictionary.Member]) -> str:
    """A body as `b(wildcard, m(...), ...)`: members by reading id, with the
    holes and placeholders the corpus cannot complete named for what they are.
    `wildcard` is the `* [ AVP ]` line's `{min, max}`, or `false` where the body
    has none: RFC 6733's `Failed-AVP` is `1* { AVP }`, which admits any AVP and
    requires one."""
    wildcard = "false"
    entries = []
    for member in members:
        maximum = -1 if member.max_occurs is None else member.max_occurs
        if member.kind == "wildcard":
            wildcard = f"{{min={member.min_occurs},max={maximum}}}"
            continue
        if member.kind == "avp":
            assert member.avp is not None
            entries.append(
                f"m({lua_string(member.avp)},{lua_string(member.name)},"
                f"{lua_string(member.presence.value)},{member.min_occurs},{maximum})"
            )
        else:
            reason = member.hole if member.kind == "hole" else "undefined"
            entries.append(
                f"u({lua_string(member.name)},{lua_string(reason or member.kind)},"
                f"{lua_string(member.presence.value)},{member.min_occurs},{maximum})"
            )
    return f"b({wildcard},{{{','.join(entries)}}})"


def _avp(avp: dictionary.Avp) -> str:
    rules = avp.flag_rules
    parts = [
        f"name={lua_string(avp.name)}",
        f"type={lua_string(avp.data_type.value)}",
        f"defined_in={lua_string(avp.defined_in)}",
        f"read_through={lua_string(avp.read_through)}",
        "flags={"
        f"must={_flag_letters(rules.must)},"
        f"may={_flag_letters(rules.may)},"
        f"should_not={_flag_letters(rules.should_not)},"
        f"must_not={_flag_letters(rules.must_not)},"
        f"application={_flag_letters(rules.application_defined)}"
        "}",
    ]
    if avp.kind == "grouped":
        parts.append(f"members={_body(avp.members)}")
    if avp.kind == "enumerated":
        values = [each.value for each in avp.values if each.kind == "value"]
        ranges = [
            f"{{{lua_string(each.kind)},{each.first},{each.last}}}"
            for each in avp.values
            if each.kind != "value"
        ]
        parts.append("values={" + ",".join(f"[{value}]=true" for value in values) + "}")
        parts.append("ranges={" + ",".join(ranges) + "}")
        if not values:
            # A clause citing its values elsewhere, which no correction
            # supplied (TS 29.272's Report-Interval): any number may be one.
            parts.append("values_open=true")
    return "{" + ",".join(parts) + "}"


def _allocated(built: model.Model, application_id: int | None) -> set[str]:
    """The documents TS 29.230's registry allocates an application id to."""
    if application_id is None:
        return set()
    return {
        reference
        for allocation in built.registry(
            model.RegistryKind.APPLICATION_IDS, application_id
        )
        if isinstance(allocation.entry, ast.RegistryRow)
        for reference in allocation.entry.defined_in
    }


def _candidates(applications: Iterable[dictionary.Application], built: model.Model):
    """The commands per `app:code:R` key, without an obsoleted document's where
    the document obsoleting it defines commands of its own. Those of a document
    the registry allocates the id to come first, which the plugin keeps where
    candidates fit a message equally: 3GPP2 X.S0013-006 prints Cx's commands as
    TS 29.229 does, and the registry gives 16777216 to TS 29.229."""
    defining = {application.reference for application in applications}
    keyed: dict[str, list[tuple[dictionary.Application, dictionary.Command]]] = (
        defaultdict(list)
    )
    for application in applications:
        newer = OBSOLETED_BY.get(application.reference)
        if newer is not None and newer in defining:
            continue
        for command in application.commands:
            app = "*" if command.application_id is None else str(command.application_id)
            key = f"{app}:{command.command_code}:{1 if command.is_request else 0}"
            keyed[key].append((application, command))
    for entries in keyed.values():
        allocated = _allocated(built, entries[0][1].application_id)
        entries.sort(key=lambda entry: entry[0].reference not in allocated)
    return keyed


def rules_chunk(built: dictionary.Dictionary, resolved: model.Model) -> str:
    """The rules as a Lua chunk returning the table `core.validate` reads."""
    lines = [
        "local function m(id, name, presence, min, max)",
        "  return {id=id, name=name, presence=presence, min=min, max=max}",
        "end",
        "local function u(name, hole, presence, min, max)",
        "  return {name=name, hole=hole, presence=presence, min=min, max=max}",
        "end",
        "local function b(wildcard, members)",
        "  members.wildcard = wildcard",
        "  return members",
        "end",
        "local avps, commands, answers = {}, {}, {}",
        "local result_codes, bits = {}, {}",
    ]
    for avp in built.avps:
        lines.append(f"avps[{lua_string(avp.id)}]={_avp(avp)}")
    for key, entries in sorted(_candidates(built.applications, resolved).items()):
        candidates = []
        for application, command in entries:
            fields = [
                f"name={lua_string(command.name)}",
                f"abbreviation={lua_string(command.abbreviation)}",
                f"document={lua_string(command.defined_in)}",
                f"section={lua_string(command.section)}",
                f"interface={lua_string(application.name or application.clause)}",
                f"proxiable={'true' if 'PXY' in command.flags else 'false'}",
                f"members={_body(command.members)}",
            ]
            if command.answer_message is not None:
                fields.append(f"answer={lua_string(command.answer_message)}")
            candidates.append("{" + ",".join(fields) + "}")
        lines.append(f"commands[{lua_string(key)}]={{{','.join(candidates)}}}")
    for answer in built.answer_messages:
        lines.append(
            f"answers[{lua_string(answer.id)}]={{"
            f"defined_in={lua_string(answer.defined_in)},"
            f"section={lua_string(answer.section)},"
            f"read_through={lua_string(answer.read_through)},"
            f"members={_body(answer.members)}}}"
        )
    codes: dict[int, dict[int, str]] = defaultdict(dict)
    masks: dict[str, set[int]] = defaultdict(set)
    for table in built.value_tables:
        if table.kind.value == "result-codes":
            for row in table.rows:
                codes[table.vendor_id].setdefault(row.value, row.name)
        elif table.kind.value == "bits" and table.avp_id is not None:
            identity = table.avp_id.partition("#")[0]
            masks[identity].update(row.value for row in table.rows)
    for vendor, names in sorted(codes.items()):
        entries = ",".join(
            f"[{value}]={lua_string(name)}" for value, name in sorted(names.items())
        )
        lines.append(f"result_codes[{vendor}]={{{entries}}}")
    for identity, numbers in sorted(masks.items()):
        entries = ",".join(f"[{number}]=true" for number in sorted(numbers))
        lines.append(f"bits[{lua_string(identity)}]={{{entries}}}")
    corpus_version = built.corpus_version or "unversioned"
    corpus_line = f"seanchai {built.seanchai_version}, corpus {corpus_version}"
    lines.append(
        "return {avps=avps, commands=commands, answers=answers,"
        f" result_codes=result_codes, bits=bits, base_answer={lua_string(BASE_ANSWER)},"
        f" corpus={lua_string(corpus_line)}}}"
    )
    return "\n".join(lines) + "\n"


def plugin(rules: str, version_line: str) -> str:
    """One file for Wireshark's plugin directory: the rules, the core and the
    glue, each in its own function scope."""
    core = (HERE / "core.lua").read_text("utf-8")
    glue = (HERE / "plugin.lua").read_text("utf-8")
    return (
        "-- Seanchaí Diameter validation, generated by"
        " integrations/wireshark/validator/generate.py: do not edit.\n"
        f"-- {version_line}\n\n"
        "local RULES = (function()\n"
        f"{rules}"
        "end)()\n\n"
        "local core = (function()\n"
        f"{core}"
        "end)()\n\n"
        f"{glue}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--corpus", type=Path, help="a corpus directory; the installed one by default"
    )
    parser.add_argument(
        "--document", action="append", default=[], help="only this document's commands"
    )
    parser.add_argument(
        "--application",
        action="append",
        type=int,
        default=[],
        help="only this application id's commands",
    )
    parser.add_argument(
        "--rules-only",
        action="store_true",
        help="write the rules alone, as a Lua chunk returning them",
    )
    arguments = parser.parse_args(argv)

    if arguments.corpus is None:
        books = corpus.Corpus.installed()
        built_model = model.Model.build(books)
        corpus_version = books.version
    else:
        built_model = model.Model.build(corpus.Corpus.load([arguments.corpus]))
        corpus_version = None
    try:
        built = dictionary.build(
            built_model,
            corpus_version=corpus_version,
            documents=arguments.document,
            application_ids=arguments.application,
        )
    except model.ModelError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    rules = rules_chunk(built, built_model)
    version_line = (
        f"seanchai {__version__}, corpus {corpus_version or 'unversioned'},"
        f" {len(built.applications)} applications, {len(built.avps)} AVPs"
    )
    text = rules if arguments.rules_only else plugin(rules, version_line)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(text, "utf-8")
    print(f"wrote {arguments.output} ({version_line})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
