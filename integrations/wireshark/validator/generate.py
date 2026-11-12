#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["seanchai", "seanchai-corpus"]
#
# [tool.uv.sources]
# seanchai = { path = "../../..", editable = true }
# seanchai-corpus = { path = "../../../packages/seanchai-corpus", editable = true }
# ///
"""Write the Wireshark plugin that validates Diameter traffic against the corpus.

The rules are `seanchai dictionary`'s output as a Lua table: every reading of
every AVP the selected commands reach (type, flag rules, members, values), the
commands keyed by application id, command code and direction, the
`<answer-message>` used with the E bit, and the result codes the documents
name. Beside them, read from the corpus files (`Places`), is where each rule
is written: every document cited, with its source URL and explorer id, once,
and each clause, page and table a reading, command or answer-message cites.
`core.lua` checks a PDU against the rules and `plugin.lua` shows the result.
The output is one file holding all three, for Wireshark's plugin directory.

    uv run integrations/wireshark/validator/generate.py \\
        -o ~/.local/lib/wireshark/plugins/seanchai_diameter.lua
    uv run integrations/wireshark/validator/generate.py --application 16777216 \\
        --application 16777251 -o seanchai_diameter.lua
    uv run integrations/wireshark/validator/generate.py --rules-only -o rules.lua

Where several documents define one command under one application id, each is
a candidate and the plugin reports against the best match. A document that a
newer one in the corpus obsoletes (`OBSOLETED_BY`) is not a candidate. README.md
beside this script says what is checked.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

from seanchai import __version__, corpus, dictionary, model
from seanchai.dad import ast

HERE = Path(__file__).parent

# The explorer site, which shows each document's corrected text at a clause.
EXPLORER = "https://sliva0.github.io/seanchai-explorer/"

# The RFC 6733 sections the checks of the header, the AVP framing and the
# data formats cite, with their pages as RFC 6733's table of contents prints
# them: 3 Diameter Header, 4.1 AVP Header, 4.2 Basic AVP Data Formats, 4.3.1
# Common Derived AVP Data Formats, 7.1.3 Protocol Errors, 7.2 Error Bit.
BASE_SECTIONS = {
    "header": ("3", 34),
    "avp": ("4.1", 41),
    "basic": ("4.2", 43),
    "derived": ("4.3.1", 44),
    "protocol_errors": ("7.1.3", 90),
    "error_bit": ("7.2", 95),
}

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


def _link_kind(entry: corpus.Entry, link: str) -> str:
    """How a place in `entry`'s source is linked to: `rfc` by its section's
    anchor in rfc-editor.org's HTML rendering, `pdf` by `#page=N`, `printed`
    for a PDF whose pages the corpus counts as printed, which a fragment cannot
    reach (a 3GPP2 document numbers its front matter apart: X.S0013-006's
    printed page 8 is the PDF's 14th), and `other` by the document alone."""
    url = urlparse(link)
    path = url.path.lower()
    if entry.reference.startswith("RFC") and path.endswith(".txt"):
        return "rfc"
    if not path.endswith(".pdf"):
        return "other"
    return "printed" if entry.spec.specification.startswith("3GPP2 ") else "pdf"


def _label(entry: corpus.Entry, newest: bool) -> str:
    """`entry`'s name as its cover prints it, "3GPP " left off a TS or TR, and
    the version for an older copy: "TS 29.061", "TS 29.214 V7.12.0"."""
    name = entry.spec.specification.removeprefix("3GPP ")
    if not newest and entry.spec.version is not None:
        name += f" V{entry.spec.version}"
    return name


class Places:
    """Where the corpus prints what the rules hold: each document's source and
    explorer id, and each clause and page a finding cites.

    Documents and citations are numbered in the order first cited, so that
    each is written once into the rules and a rule names it by number."""

    def __init__(self, books: corpus.Corpus) -> None:
        self._copies: dict[str, list[corpus.Entry]] = {}
        for entry in books:  # each reference's copies, newest first
            self._copies.setdefault(entry.reference, []).append(entry)
        self._pages: dict[Path, dict[str, int | None]] = {}
        self.documents: dict[Path, tuple[corpus.Entry, int]] = {}
        self.citations: dict[tuple[int, str, int | None, str | None, bool], int] = {}

    def entry(self, document: str) -> corpus.Entry | None:
        """The copy a spelling names: "TS29.061" its newest, "TS32.299
        V11.20.0" that version."""
        reference, _, version = document.partition(" V")
        copies = self._copies.get(reference, [])
        if version:
            copies = [each for each in copies if each.spec.version == version]
        return copies[0] if copies else None

    def _copies_of(self, document: str) -> list[corpus.Entry]:
        found = self.entry(document)
        if found is None:
            return []
        rest = self._copies[found.reference]
        return [found, *(each for each in rest if each is not found)]

    def _placed(self, entry: corpus.Entry) -> dict[str, int | None]:
        """Every clause `entry` places something in, with its page: its first
        block there, else the table of its first row there, as the export's
        sections have it."""
        pages = self._pages.get(entry.path)
        if pages is None:
            pages = {}
            for section in entry.spec.sections:
                pages.setdefault(section.source.section, section.source.page)
            for section in entry.spec.sections:
                if isinstance(section, ast.AvpTable | ast.ValueTable):
                    for row in section.rows:
                        if row.section:
                            pages.setdefault(row.section, section.source.page)
            self._pages[entry.path] = pages
        return pages

    def _cite(
        self,
        entry: corpus.Entry,
        clause: str,
        page: int | None,
        table: str | None = None,
    ) -> int:
        if entry.path not in self.documents:
            self.documents[entry.path] = (entry, len(self.documents) + 1)
        shown = clause in self._placed(entry)
        key = (self.documents[entry.path][1], clause, page, table, shown)
        return self.citations.setdefault(key, len(self.citations) + 1)

    def clause(
        self, document: str, clause: str | None, name: str | None = None
    ) -> int | None:
        """The citation of `clause` in `document`, or None where the corpus
        holds no copy placing it. A block named `name` there gives its page."""
        if clause is None:
            return None
        for entry in self._copies_of(document):
            for section in entry.spec.sections:
                if (
                    name is not None
                    and section.source.section == clause
                    and getattr(section, "name", None) == name
                ):
                    return self._cite(entry, clause, section.source.page)
            placed = self._placed(entry)
            if clause in placed:
                return self._cite(entry, clause, placed[clause])
        return None

    def table_row(self, document: str, name: str) -> int | None:
        """The AVP-table row `document` prints for `name`, as its table's
        clause, page and label, or failing one, its re-used row stating an M
        bit: the cells the flag rules come from. None where it prints
        neither."""
        for entry in self._copies_of(document):
            reused = None
            for section in entry.spec.sections:
                if isinstance(section, ast.AvpTable) and any(
                    row.name == name for row in section.rows
                ):
                    source = section.source
                    return self._cite(entry, source.section, source.page, section.table)
                if (
                    reused is None
                    and isinstance(section, ast.ReusedAvps)
                    and any(
                        row.name == name and row.m_bit is not None
                        for row in section.rows
                    )
                ):
                    reused = section
            if reused is not None:
                source = reused.source
                return self._cite(entry, source.section, source.page, reused.table)
        return None

    def table(self, table: dictionary.ValueTable) -> int | None:
        """A value table, as its block's clause, page and label."""
        document = table.reference
        if table.version is not None:
            document += f" V{table.version}"
        entry = self.entry(document)
        if entry is None:
            return None
        return self._cite(entry, table.section, table.page, table.table)

    def base(self, clause: str, page: int) -> int | None:
        """A section of RFC 6733, the base protocol."""
        entry = self.entry(ast.BASE_PROTOCOL)
        return None if entry is None else self._cite(entry, clause, page)

    def lua(self) -> list[str]:
        """The documents and citations as Lua lines: `docs[n]` is reference,
        label, explorer id, source URL and link kind (`_link_kind`);
        `cites[n]` is document number, clause, page or false, table or
        false, and `true` for a clause the corpus places nothing in, where
        the explorer has nothing to go to."""
        lines = []
        for entry, number in self.documents.values():
            newest = self._copies[entry.reference][0] is entry
            link = str(entry.spec.link or entry.spec.transcribed or "")
            kind = _link_kind(entry, link)
            if kind == "rfc":
                # rfc-editor.org's HTML rendering anchors every section as
                # `#section-7.2`; the plain text has no anchors.
                link = link.removesuffix(".txt") + ".html"
            fields = [
                entry.reference,
                _label(entry, newest),
                entry.path.stem,  # the explorer's id: seanchai.export.document_id
                link,
                kind,
            ]
            lines.append(f"docs[{number}]={{{','.join(map(lua_string, fields))}}}")
        for (document, clause, page, table, shown), number in self.citations.items():
            fields = [str(document), lua_string(clause), str(page or "false")]
            if table is not None or not shown:
                fields.append("false" if table is None else lua_string(table))
            if not shown:
                fields.append("true")
            lines.append(f"cites[{number}]={{{','.join(fields)}}}")
        return lines


def _cited(field: str, number: int | None) -> list[str]:
    return [] if number is None else [f"{field}={number}"]


def _flag_document(avp: dictionary.Avp) -> str:
    """The document whose table states `avp`'s flag rules: the one that
    completed them, else the one the reading is read through."""
    for missing, document in avp.completed_by:
        if missing == corpus.Missing.FLAG_RULES:
            return document
    return avp.read_through or avp.defined_in


def _flag_letters(values: Iterable[str]) -> str:
    return lua_string("".join(sorted(values)))


def _body(members: Iterable[dictionary.Member]) -> str:
    """A body as `b(wildcard, m(...), ...)`, with members by reading id and
    holes and placeholders marked as such.

    `wildcard` is the `* [ AVP ]` line's `{min, max}`, or `false` where the body
    has none. RFC 6733's `Failed-AVP` is `1* { AVP }`: any AVP, at least one."""
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


def _avp_citations(avp: dictionary.Avp, places: Places) -> list[str]:
    """`at`, the clause defining the reading (its Grouped AVP rule, its
    Enumerated values, or the clause its table row names), and `flags_at`,
    the AVP-table row its flag rules are read from."""
    document = avp.defined_in
    if avp.read_through.partition(" V")[0] == avp.defined_in:
        document = avp.read_through  # the copy, where an older one is read
    row = places.table_row(document, avp.name)
    # A table printing no clause column (TS 32.299's) is all that places it.
    at = places.clause(document, avp.section, avp.name) or row
    flags_at = places.table_row(_flag_document(avp), avp.name) or row or at
    return [*_cited("at", at), *_cited("flags_at", flags_at)]


def _avp(avp: dictionary.Avp, places: Places) -> str:
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
        *_avp_citations(avp, places),
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
    """The candidate commands per `app:code:R` key.

    An obsoleted document's commands are dropped where the obsoleting document
    defines commands of its own. Commands of the document the registry gives
    the id to come first; the plugin prefers them when candidates fit equally
    (3GPP2 X.S0013-006 prints Cx's commands as TS 29.229 does, and 16777216 is
    TS 29.229's)."""
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


def rules_chunk(
    built: dictionary.Dictionary,
    resolved: model.Model,
    places: Places,
    explorer: str = EXPLORER,
) -> str:
    """The rules as a Lua chunk returning the table `core.validate` reads.

    `explorer` is the explorer site's address, which each reference links to
    at its clause; empty for no such links."""
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
        "local result_codes, bits, bits_at = {}, {}, {}",
        "local docs, cites, base = {}, {}, {}",
    ]
    for avp in built.avps:
        lines.append(f"avps[{lua_string(avp.id)}]={_avp(avp, places)}")
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
                *_cited(
                    "at",
                    places.clause(command.defined_in, command.section, command.name),
                ),
            ]
            if command.answer_message is not None:
                fields.append(f"answer={lua_string(command.answer_message)}")
            candidates.append("{" + ",".join(fields) + "}")
        lines.append(f"commands[{lua_string(key)}]={{{','.join(candidates)}}}")
    for answer in built.answer_messages:
        fields = [
            f"defined_in={lua_string(answer.defined_in)}",
            f"section={lua_string(answer.section)}",
            f"read_through={lua_string(answer.read_through)}",
            f"members={_body(answer.members)}",
            *_cited("at", places.clause(answer.defined_in, answer.section)),
        ]
        lines.append(f"answers[{lua_string(answer.id)}]={{{','.join(fields)}}}")
    codes: dict[int, dict[int, str]] = defaultdict(dict)
    masks: dict[str, set[int]] = defaultdict(set)
    masks_at: dict[str, int] = {}
    for table in built.value_tables:
        if table.kind.value == "result-codes":
            for row in table.rows:
                codes[table.vendor_id].setdefault(row.value, row.name)
        elif table.kind.value == "bits" and table.avp_id is not None:
            identity = table.avp_id.partition("#")[0]
            masks[identity].update(row.value for row in table.rows)
            if (at := places.table(table)) is not None:
                masks_at.setdefault(identity, at)
    for vendor, names in sorted(codes.items()):
        entries = ",".join(
            f"[{value}]={lua_string(name)}" for value, name in sorted(names.items())
        )
        lines.append(f"result_codes[{vendor}]={{{entries}}}")
    for identity, numbers in sorted(masks.items()):
        entries = ",".join(f"[{number}]=true" for number in sorted(numbers))
        lines.append(f"bits[{lua_string(identity)}]={{{entries}}}")
    for identity, at in sorted(masks_at.items()):
        lines.append(f"bits_at[{lua_string(identity)}]={at}")
    for kind, (clause, page) in BASE_SECTIONS.items():
        if (at := places.base(clause, page)) is not None:
            lines.append(f"base.{kind}={at}")
    lines.extend(places.lua())
    corpus_version = built.corpus_version or "unversioned"
    corpus_line = f"seanchai {built.seanchai_version}, corpus {corpus_version}"
    lines.append(
        "return {avps=avps, commands=commands, answers=answers,"
        " result_codes=result_codes, bits=bits, bits_at=bits_at, docs=docs,"
        f" cites=cites, base=base, base_answer={lua_string(BASE_ANSWER)},"
        f" explorer={lua_string(explorer) if explorer else 'nil'},"
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
    parser.add_argument(
        "--explorer",
        default=EXPLORER,
        metavar="URL",
        help="the explorer site each reference links to; empty for no such links",
    )
    arguments = parser.parse_args(argv)

    if arguments.corpus is None:
        books = corpus.Corpus.installed()
        corpus_version = books.version
    else:
        books = corpus.Corpus.load([arguments.corpus])
        corpus_version = None
    built_model = model.Model.build(books)
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
    rules = rules_chunk(built, built_model, Places(books), arguments.explorer)
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
