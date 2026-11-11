"""`seanchai export`: the site's JSON over the committed corpus, and how an export
replaces the directory it writes.

The committed corpus is exported as a site's build runs it: a command in a
directory holding nothing of the repository, reading the corrections from the
installed corpus's record, under two hash seeds. `tests/export.sha256` pins
every file; the tests on its content state the contract docs/website.md
describes, one file kind at a time.
"""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import seanchai_corpus
from click.testing import CliRunner
from conftest import _CORPUS_DIR

from seanchai import export_schema
from seanchai.cli import main
from seanchai.corpus import Corpus, CorpusError
from seanchai.dad import ast
from seanchai.dad.ast import section_sort_key
from seanchai.downloader.catalog import load_catalog
from seanchai.export import SYNTAX_FILE, export_corpus

ROOT = Path(__file__).resolve().parent.parent
_ETSI = _CORPUS_DIR / "etsi"
_PIN = ROOT / "tests" / "export.sha256"
_GRAMMAR = ROOT / "src" / "seanchai" / "dad" / "syntax" / "dad.tmLanguage.json"


def _tree(path: Path) -> dict[str, bytes]:
    return {
        file.relative_to(path).as_posix(): file.read_bytes()
        for file in path.rglob("*")
        if file.is_file()
    }


@pytest.fixture(scope="module")
def exports(tmp_path_factory) -> list[Path]:
    """The committed corpus exported twice at once, under hash seeds 1 and 2."""
    cwd = tmp_path_factory.mktemp("elsewhere")
    runs = []
    errors = []
    try:
        for seed in ("1", "2"):
            output = tmp_path_factory.mktemp(f"seed-{seed}") / "out"
            command = [sys.executable, "-c", "from seanchai.cli import main; main()"]
            process = subprocess.Popen(
                [*command, "export", "-o", str(output)],
                cwd=cwd,
                env={**os.environ, "PYTHONHASHSEED": seed},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            runs.append((output, process))
        for _, process in runs:
            _, stderr = process.communicate()
            errors.append((process.returncode, stderr.decode()))
    finally:
        # A failure or an interrupt above leaves no child running.
        for _, process in runs:
            if process.returncode is None:
                process.kill()
                process.communicate()
    for returncode, stderr in errors:
        assert returncode == 0, stderr
    return [output for output, _ in runs]


@dataclass(frozen=True)
class Exported:
    path: Path
    index: dict
    search: dict
    docs: dict[str, dict]
    raws: dict[str, dict]

    def entry(self, document: str, name: str) -> dict:
        return next(
            e
            for e in self.search["entries"]
            if e["document"] == document and e["name"] == name
        )

    def title(self, document: str, clause: str) -> str:
        (found,) = [
            s for s in self.docs[document]["sections"] if s["section"] == clause
        ]
        return found["title"]


@pytest.fixture(scope="module")
def exported(exports) -> Exported:
    path = exports[0]
    files = {
        file.name.removesuffix(".json"): json.loads(file.read_text("utf-8"))
        for file in (path / "documents").glob("*.json")
    }
    return Exported(
        path,
        json.loads((path / "index.json").read_text("utf-8")),
        json.loads((path / "search.json").read_text("utf-8")),
        {key: value for key, value in files.items() if not key.endswith(".raw")},
        {
            key.removesuffix(".raw"): value
            for key, value in files.items()
            if key.endswith(".raw")
        },
    )


def _text(lines) -> str:
    return "".join(t["text"] for line in lines for t in line["tokens"])


def _tokens(lines, text: str) -> list[dict]:
    return [t for line in lines for t in line["tokens"] if t["text"] == text]


# --- the whole export -------------------------------------------------------------


def _pinned_bytes(name: str, data: bytes) -> bytes:
    """A file as the pin reads it. A release changes the versions and nothing
    else, so they are left out, and the pin need not move with one."""
    if name != "index.json":
        return data
    index = export_schema.Index.model_validate_json(data)
    return export_schema.dumps(
        index.model_copy(update={"seanchai_version": None, "corpus_version": None})
    ).encode()


def test_the_export_is_what_the_pin_says(exports, request):
    """Regenerate with `uv run pytest --update-export-pin` (docs/development.md)."""
    first, second = (_tree(path) for path in exports)
    assert first.keys() == second.keys()
    assert [name for name in first if first[name] != second[name]] == [], (
        "the export depends on the hash seed"
    )
    actual = {
        name: hashlib.sha256(_pinned_bytes(name, data)).hexdigest()
        for name, data in first.items()
    }
    if request.config.getoption("--update-export-pin"):
        _PIN.write_text(
            "".join(f"{actual[name]}  {name}\n" for name in sorted(actual)), "utf-8"
        )
    pinned = {
        name: digest
        for digest, name in (
            line.split("  ", 1) for line in _PIN.read_text("utf-8").splitlines()
        )
    }
    changed = sorted(
        name for name in actual.keys() & pinned if actual[name] != pinned[name]
    )
    added = sorted(actual.keys() - pinned.keys())
    removed = sorted(pinned.keys() - actual.keys())
    assert not (changed or added or removed), (
        f"changed: {changed}\nnew: {added}\ngone: {removed}\n"
        "review the export, then run `uv run pytest --update-export-pin`"
    )


def test_every_file_is_compact_json_its_schema_describes(exported):
    schema = json.loads((exported.path / "schema.json").read_text("utf-8"))
    assert schema == export_schema.json_schema()
    definitions = schema["$defs"]
    for root in ("Index", "Search", "Document", "RawDocument"):
        assert {"$ref": f"#/$defs/{root}"} in schema["oneOf"]
        version = definitions[root]["properties"]["schema_version"]
        assert version["minimum"] == version["maximum"] == export_schema.SCHEMA_VERSION
    references = [
        part.removeprefix('"#/$defs/')
        for part in json.dumps(schema).split('"$ref": ')[1:]
    ]
    assert all(part.split('"')[0] in definitions for part in references)

    models = {"index.json": export_schema.Index, "search.json": export_schema.Search}
    for name, data in _tree(exported.path).items():
        assert str(ROOT).encode() not in data, name
        if name == SYNTAX_FILE:
            # The editors' grammar as it stands, the copy under editors/ too.
            assert data == _GRAMMAR.read_bytes()
            vscode = ROOT / "editors" / "vscode" / "syntaxes" / "dad.tmLanguage.json"
            assert vscode.read_bytes() == data
            continue
        value = json.loads(data)
        compact = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        assert data.decode("utf-8") == compact + "\n", name
        if name == "schema.json":
            continue
        model = models.get(name) or (
            export_schema.RawDocument
            if name.endswith(".raw.json")
            else export_schema.Document
        )
        assert export_schema.dumps(model.model_validate_json(data)).encode() == data


def test_the_tokens_of_each_document_join_to_its_files_bytes(exported):
    for entry in Corpus.load([_CORPUS_DIR]):
        identifier = entry.path.stem
        raw = _CORPUS_DIR / "raw" / entry.path.relative_to(_CORPUS_DIR)
        assert _text(exported.docs[identifier]["lines"]) == entry.path.read_text()
        assert _text(exported.raws[identifier]["lines"]) == raw.with_suffix(
            ".raw.dad"
        ).read_text("utf-8")


def test_every_link_resolves_and_every_cited_correction_has_its_reason(exported):
    """The fixture ran with no `edits/` in reach, as an installed package
    does: the reasons come from the corpus's record."""
    anchors = {}
    for key, doc in exported.docs.items():
        values = [line["anchor"] for line in doc["lines"] if line.get("anchor")]
        assert len(values) == len(set(values)), key
        anchors[key] = set(values)
    targets = [e["target"] for e in exported.search["entries"] if e["target"]]
    cited = 0
    for key, doc in exported.docs.items():
        for lines in (doc["lines"], exported.raws[key]["lines"]):
            for token in (t for line in lines for t in line["tokens"]):
                if "target" in token:
                    targets.append(token["target"])
                if "correction" in token:
                    cited += 1
                    assert doc["corrections"][token["correction"]]["reason"]
        for finding in doc["findings"]:
            assert finding["rule"] != "stale-acceptance"
            if finding["severity"] == "accepted":
                assert doc["corrections"][finding["accepted_by"]]["kind"] == "accept"
    assert cited > 500
    for target in targets:
        assert target["document"] in exported.docs
        if target.get("section"):
            assert target["section"] in anchors[target["document"]]


# --- one file kind at a time ---------------------------------------------------------


def test_index_json_summarises_each_document(exported):
    index = exported.index
    assert index["generator"] == "seanchai"
    assert index["corpus_version"] == seanchai_corpus.__version__
    assert index["seanchai_version"]
    assert index["mode"] == "public"
    assert {d["id"] for d in index["documents"]} == exported.docs.keys()
    assert exported.raws.keys() == exported.docs.keys()
    summaries = {d["id"]: d for d in index["documents"]}
    for summary in summaries.values():
        assert (exported.path / summary["path"]).is_file()
        assert (exported.path / summary["raw"]).is_file()
        # Public mode copies no PDF; the site opens ETSI's own URL.
        assert summary["source"]["local"] is None
    assert {
        name: summaries[name]["source"]["kind"]
        for name in ("29212-j10", "es283034-020200", "rfc6733", "xs0057-0_v2.0")
    } == {
        "29212-j10": "etsi-pdf",
        "es283034-020200": "etsi-pdf",
        "rfc6733": "rfc-text",
        "xs0057-0_v2.0": "other",
    }
    # The catalog's title, a transcription's from its cover.
    assert summaries["29209-680"]["title"] == "Policy control over Gq interface"
    assert "e4 interface" in summaries["es283034-020200"]["title"]
    assert not [d for d in index["documents"] if d["title"] == d["specification"]]


def test_search_json_names_each_entry_as_its_document_means_it(exported):
    fields = {
        "avp": {"vendor_id", "code"},
        "command": {
            "command_code",
            "application_id",
            "header_application_id",
            "application",
        },
        "application": {"application_id"},
        "registry": {"registry", "code"},
        "value": {"value_kind", "avp", "value", "application", "feature_list_id"},
    }
    for entry in exported.search["entries"]:
        if entry["identity"] is not None:
            assert entry["identity"]["kind"] == entry["kind"]
            assert set(entry["identity"]) - {"kind"} == fields[entry["kind"]]
        if entry["kind"] == "avp" and entry["identity"]:
            assert entry["target"]["section"]
    assert {e["kind"] for e in exported.search["entries"]} == fields.keys()

    # A command's application is the effective one: Gx's headers print none,
    # and its Application Scope block states it.
    gx = next(
        e
        for e in exported.search["entries"]
        if e["document"] == "29212-j10"
        and e["name"] == "CC-Request"
        and e["target"]["section"] == "5.6.2"
    )
    assert gx["abbreviation"] == "CCR"
    assert gx["wireshark_name"] is None
    assert gx["identity"] == {
        "kind": "command",
        "command_code": 272,
        "application_id": 16777238,
        "header_application_id": None,
        "application": "Gx",
    }
    # TS 29.272 clause 7.2.9 prints Insert-Subscriber-Data-Request twice.
    printed = [
        e["identity"]
        for e in exported.search["entries"]
        if e["document"] == "29272-j60"
        and e["name"] == "Insert-Subscriber-Data-Request"
    ]
    assert sorted(i["application_id"] for i in printed) == [16777251, 16777308]
    assert all(i["application_id"] == i["header_application_id"] for i in printed)

    # A citation of another release resolves into that release's copy.
    cited = exported.entry("ts-0004-v2_35_0", "Service-Information")
    assert cited["target"]["document"] == "32299-bk0"
    assert cited["across_releases"]["version"] == "11.20.0"
    # A table row the corpus re-uses is the origin's definition.
    reused = exported.entry("29329-j10", "Session-Priority")
    assert reused["target"] == {"document": "29229-j10", "section": "6.3.56"}

    code = exported.entry("29229-j10", "DIAMETER_ERROR_USER_UNKNOWN")
    assert code["target"] == {"document": "29229-j10", "section": "6.2.2.1"}
    assert code["identity"] == {
        "kind": "value",
        "value_kind": "result-codes",
        "avp": "Experimental-Result-Code",
        "value": 5001,
        "application": None,
        "feature_list_id": None,
    }
    feature = exported.entry("29272-j60", "ODB-all-APN")
    assert feature["identity"]["application"] == "S6a/S6d"
    assert feature["identity"]["feature_list_id"] == 1


def test_a_document_carries_its_sections_targets_and_corrections(exported):
    assert exported.title("29229-j10", "6.1.1") == "Message User-Authorization-Request"
    assert exported.title("29229-j10", "6.3.0") == "AVP Table, Reused AVPs"
    assert exported.title("29229-j10", "6.3.4") == "Grouped AVP Server-Capabilities"
    assert exported.title("29229-j10", "6.3.75") == "AVP PCSCF-FQDN"
    assert exported.title("29061-j10", "16.4.7") == "AVP 3GPP-IMSI and 37 more"
    assert exported.title("29229-j10", "6.2.2.1") == (
        "Value DIAMETER_ERROR_USER_UNKNOWN"
    )
    assert "Value Table ULR-Flags" in exported.title("29272-j60", "7.3.7")
    for doc in exported.docs.values():
        clauses = [each["section"] for each in doc["sections"]]
        assert clauses == sorted(clauses, key=section_sort_key), doc["id"]
        assert all(each["title"] for each in doc["sections"]), doc["id"]

    kinds = set()
    for doc in exported.docs.values():
        for token in (t for line in doc["lines"] for t in line["tokens"]):
            if "kind" in token:
                kinds.add(token["kind"])
                assert token["text"].startswith(";;")
                assert (token["kind"] == "correction-note") == ("correction" in token)
    assert kinds == {"comment", "correction-note"}
    assert "TS29.272.py#area-scope-code" in exported.docs["29272-j60"]["corrections"]

    # A re-used row's origin cell targets the AVP by name.
    ts29214 = next(
        d
        for d in exported.docs.values()
        if (d["reference"], d["version"]) == ("TS29.214", "19.3.0")
    )
    line = next(
        line
        for line in ts29214["lines"]
        if {"3GPP-MS-TimeZone", "TS29.061"} <= {t["text"] for t in line["tokens"]}
    )
    (origin,) = [t for t in line["tokens"] if t["text"] == "TS29.061"]
    assert origin["target"]["name"] == "3GPP-MS-TimeZone"
    assert exported.docs[origin["target"]["document"]]["reference"] == "TS29.061"

    # A table row's name keeps where the source prints it, and targets the
    # definition: here TS 29.229's, which TS 29.329 re-uses.
    sh = exported.docs["29329-j10"]["lines"]
    row = next(
        t for t in _tokens(sh, "Supported-Features") if "row" in t.get("source", {})
    )
    assert row["source"] == {
        "section": "6.3",
        "page": 18,
        "name": "Supported-Features",
        "row": True,
    }
    assert row["target"] == {"document": "29229-j10", "section": "6.3.29"}

    # TS 29.212 prints CC-Request once per interface, with one spelling.
    gx = exported.docs["29212-j10"]["lines"]
    for line in gx:
        for token in _tokens([line], "CC-Request"):
            assert token["target"] == {
                "document": "29212-j10",
                "section": line["section"],
            }
    assert {"5.6.2", "5a.6.2", "5b.6.4", "E.6.6.2"} <= {
        line["section"] for line in gx if _tokens([line], "CC-Request")
    }

    s6a = exported.docs["29272-j60"]["lines"]
    (avp_line,) = [line for line in s6a if _text([line]).startswith("; AVP: ULR-Flags")]
    (avp,) = _tokens([avp_line], "ULR-Flags")
    assert avp["target"] == {"document": "29272-j60", "section": "7.3.7"}
    cx = exported.docs["29229-j10"]["lines"]
    row = next(
        line
        for line in cx
        if line["tokens"][0]["text"] == "DIAMETER_ERROR_USER_UNKNOWN"
    )
    assert row["anchor"] == "6.2.2.1"


def test_a_raw_document_marks_what_the_corrected_file_changes(exported):
    raw = exported.raws["29229-j10"]["lines"]
    renamed = [
        line
        for line in raw
        if any(t.get("avp") == "Digest-QoP" for t in line["tokens"])
    ]
    assert renamed and all(line.get("warning") for line in renamed)
    session = [
        line
        for line in raw
        if line.get("section") == "6.1.10"
        and any(t.get("avp") == "Session-Id" for t in line["tokens"])
    ]
    assert [bool(line.get("warning")) for line in session].count(True) == 1
    # The raw spelling links through the correction declaring the name.
    tokens = _tokens(raw, "Digest-QoP")
    assert len(tokens) == 3
    assert all(t["target"] == {"document": "rfc4590", "section": "3.8"} for t in tokens)


def test_sections_sort_in_document_order():
    clauses = ["E.6.3.6", "6.3.10", "6.3.7A", "6.3.4", "6.3.7", "A.1", "5a", "5.1"]

    assert sorted(clauses, key=section_sort_key) == [
        "5.1",
        "5a",
        "6.3.4",
        "6.3.7",
        "6.3.7A",
        "6.3.10",
        "A.1",
        "E.6.3.6",
    ]


# --- the blocks ---------------------------------------------------------------------


def _block(doc: dict, kind: str, section: str, name: str | None = None) -> dict:
    (found,) = [
        b
        for b in doc["blocks"]
        if b["type"] == kind
        and b["section"] == section
        and (name is None or b.get("name") == name)
    ]
    return found


def _span_text(doc: dict, span: dict) -> str:
    return _text([doc["lines"][span["line"]]])[span["start"] : span["end"]]


def test_each_file_s_blocks_place_its_sections_on_its_own_lines(exported):
    for key, doc in exported.docs.items():
        for file in (doc, exported.raws[key]):
            texts = [_text([line]) for line in file["lines"]]
            starts = [i for i, text in enumerate(texts) if text.startswith("; Type:")]
            assert [b["line"] for b in file["blocks"]] == starts, key
            for block, after in zip(
                file["blocks"], [*starts[1:], len(texts)], strict=True
            ):
                assert texts[block["line"]].startswith(f"; Type: {block['type']}")
                assert block["line"] < block["last"] < after
                assert texts[block["last"]].strip()
                # A blank line ends a block, comments and all.
                assert not "".join(texts[block["last"] + 1 : block["last"] + 2]).strip()
                inside = range(block["line"], block["last"] + 1)
                rule = block.get("rule")
                for member in rule["members"] if rule else ():
                    assert member["line"] in inside
                    assert f" {member['name']} " in texts[member["line"]]
                for row in [
                    *block.get("rows", ()),
                    *block.get("allocations", ()),
                    *block.get("value_rows", ()),
                    *block.get("values", ()),
                ]:
                    assert row["line"] in inside
                for row in [*block.get("rows", ()), *block.get("allocations", ())]:
                    assert len(row["cells"]) == len(block["columns"])
                    printed = texts[row["line"]].split(";;")[0]
                    assert all(cell in printed for cell in row["cells"])
                for span in block.get("commands", ()):
                    assert span["line"] in inside
                    text = texts[span["line"]][span["start"] : span["end"]]
                    assert text in (span["name"], span.get("abbreviation")) or (
                        span["name"].endswith(text)
                    )


def test_a_message_block_holds_its_rule_and_command(exported):
    """TS 29.329 clause 6.1.1 prints the User-Data-Request."""
    sh = exported.docs["29329-j10"]
    udr = _block(sh, "Message", "6.1.1", "User-Data-Request")
    assert udr["abbreviation"] == "UDR"
    assert udr["fields"] == {
        "Name": "User-Data-Request, UDR",
        "Section": "6.1.1",
        "Page": "11",
    }
    assert udr["command"] == {
        "code": 306,
        "request": True,
        "flags": ["REQ", "PXY"],
        "header_application_id": 16777217,
        "application_id": 16777217,
    }
    rule = udr["rule"]
    assert rule["name"] == "User-Data-Request"
    assert _text([sh["lines"][rule["line"]]]).startswith("<User-Data-Request> ::=")
    members = {m["name"]: m for m in rule["members"]}
    assert len(members) == len(rule["members"]) == 31
    # RFC 6733 clause 3.2: no qualifier is exactly once, or at most once of
    # an optional member; `*` on a required member still means at least one.
    assert members["Session-Id"] == {
        "name": "Session-Id",
        "presence": "fixed",
        "min": 1,
        "max": 1,
        "line": rule["line"] + 1,
    }
    assert {k: members["DRMP"][k] for k in ("presence", "min", "max")} == {
        "presence": "optional",
        "min": 0,
        "max": 1,
    }
    assert members["Data-Reference"] | {"line": 0} == {
        "name": "Data-Reference",
        "presence": "required",
        "qualifier": "*",
        "min": 1,
        "max": None,
        "bold": True,
        "line": 0,
    }
    assert members["Supported-Features"]["qualifier"] == "*"
    assert members["Supported-Features"]["min"] == 0
    assert "bold" not in members["User-Name"]
    assert [_span_text(sh, span) for span in udr["commands"]] == [
        "User-Data-Request",
        "UDR",
        "User-Data-Request",
    ]
    assert {span["block"] for span in udr["commands"]} == {sh["blocks"].index(udr)}


def test_a_message_block_names_its_application_as_the_search_entry_does(exported):
    # The header's id is part of the key: TS 29.272 clause 7.2.9 prints
    # Insert-Subscriber-Data-Request once per application.
    commands = {
        (
            e["document"],
            e["name"],
            e["target"]["section"],
            e["identity"]["header_application_id"],
        ): e["identity"]
        for e in exported.search["entries"]
        if e["kind"] == "command"
    }
    blocks = [
        (key, block)
        for key, doc in exported.docs.items()
        for block in doc["blocks"]
        if block["type"] == "Message"
    ]
    assert len(blocks) > 500
    for key, block in blocks:
        command = block["command"]
        identity = commands[
            key, block["name"], block["section"], command["header_application_id"]
        ]
        assert identity["command_code"] == command["code"]
        assert (command["application_id"], command.get("application")) == (
            identity["application_id"],
            identity["application"],
        )


def test_a_struck_member_is_kept_and_flagged(exported):
    """TS 32.299 V11.20.0 clause 6.2.2 strikes Vendor-Specific-Application-Id
    through in the Accounting-Request, and the extractor comments it out."""
    doc = exported.docs["32299-bk0"]
    acr = _block(doc, "Message", "6.2.2", "Accounting-Request")
    struck = [m for m in acr["rule"]["members"] if m.get("struck")]
    assert [m["name"] for m in struck] == [
        "Vendor-Specific-Application-Id",
        "Accounting-Sub-Session-Id",
        "Acct-Session-Id",
        "Acct-Multi-Session-Id",
        "Accounting-Realtime-Required",
    ]
    line = _text([doc["lines"][struck[0]["line"]]])
    assert line.startswith(";;") and line.rstrip().endswith("; strikethrough")
    assert struck[0]["presence"] == "optional"
    (entry,) = [e for e in Corpus.installed() if e.path.stem == "32299-bk0"]
    (message,) = [
        s
        for s in entry.spec.sections
        if isinstance(s, ast.Message) and s.name == "Accounting-Request"
    ]
    effective = [m["name"] for m in acr["rule"]["members"] if not m.get("struck")]
    assert effective == [rule.name for rule in message.avps]
    # TS 32.299's "Used in" columns are its commands.
    table = _block(doc, "AVP Table", "7.1")
    assert [_span_text(doc, s) for s in table["commands"]] == [
        "ACR",
        "ACA",
        "CCR",
        "CCA",
    ]
    assert doc["blocks"][table["commands"][0]["block"]]["name"] == (
        "Accounting-Request"
    )


def test_a_table_row_holds_its_cells_as_printed(exported):
    """TS 29.212 table 5.4.0.1 re-uses 3GPP-GGSN-Address with a quoted mark,
    and table 5a.4.0.1 prints a blank Applicability cell."""
    gx = exported.docs["29212-j10"]
    reused = _block(gx, "Reused AVPs", "5.4.0")
    assert reused["columns"] == ["Name", "From", "Acc-Type", "Applicability"]
    assert reused["fields"]["Table"] == "5.4.0.1"
    rows = {row["name"]: row for row in reused["rows"]}
    assert rows["3GPP-GGSN-Address"]["cells"] == [
        "3GPP-GGSN-Address",
        "TS29.061",
        '"All (NOTE 8)"',
        "Both,EPC-routed,ABC",
    ]
    assert rows["3GPP-GGSN-Address"]["marks"] == {
        "Acc-Type": ["All (NOTE 8)"],
        "Applicability": ["Both", "EPC-routed", "ABC"],
    }
    # A corrected row's note is no cell.
    assert rows["3GPP-GGSN-IPv6-Address"]["cells"][-1] == "Both,EPC-routed,ABC"
    blank = _block(gx, "Reused AVPs", "5a.4.0")
    (timezone,) = [r for r in blank["rows"] if r["name"] == "3GPP-MS-TimeZone"]
    assert timezone["cells"][-1] == '""'
    assert timezone["marks"] == {"Acc-Type": ["All"]}
    # An AVP table's row places its AVP: V under Must is the file's vendor.
    table = _block(exported.docs["29329-j10"], "AVP Table", "6.3")
    (user_data,) = [r for r in table["rows"] if r["name"] == "User-Data"]
    assert user_data["vendor"] == 10415
    assert user_data["cells"][:5] == ["User-Data", "702", "6.3.3", "OctetString", "M,V"]


def test_a_command_codes_row_names_its_request_and_answer(exported):
    """TS 29.230 table 5.1/1 allocates 300 to User-Authorization-Request/-Answer,
    UAR/UAA, defined in TS 29.229."""
    doc = exported.docs["29230-j30"]
    registry = next(
        b
        for b in doc["blocks"]
        if b["type"] == "Registry" and b["fields"]["Table"] == "5.1/1"
    )
    assert registry["columns"] == ["Code", "Name", "Abbreviation", "Defined-In"]
    (row,) = [a for a in registry["allocations"] if a["code"] == 300]
    assert row == {
        "line": row["line"],
        "cells": ["300", "User-Authorization-Request/-Answer", "UAR/UAA", "TS29.229"],
        "code": 300,
        "name": "User-Authorization-Request/-Answer",
        "abbreviation": "UAR/UAA",
        "documents": ["29229-j10"],
    }
    spans = [s for s in registry["commands"] if s["line"] == row["line"]]
    assert [
        (_span_text(doc, s), s["name"], s["request"], s["abbreviation"]) for s in spans
    ] == [
        ("User-Authorization-Request", "User-Authorization-Request", True, "UAR"),
        ("UAR", "User-Authorization-Request", True, "UAR"),
        ("Answer", "User-Authorization-Answer", False, "UAA"),
        ("UAA", "User-Authorization-Answer", False, "UAA"),
    ]
    assert all(s["code"] == 300 and "block" not in s for s in spans)
    avp_codes = next(
        b
        for b in doc["blocks"]
        if b["type"] == "Registry" and b["fields"]["Registry"] == "AVP Codes"
    )
    assert {a.get("vendor") for a in avp_codes["allocations"]} == {10415}


def test_a_result_code_row_names_its_origin(exported):
    """TS 29.283 clause 7.4.3.2 lists DIAMETER_ERROR_USER_UNKNOWN "defined in
    3GPP TS 29.229", whose clause 6.2.2.1 defines it."""
    doc = exported.docs["29283-j00"]
    (table,) = [
        b
        for b in doc["blocks"]
        if b["type"] == "Value Table"
        and any(r["name"] == "DIAMETER_ERROR_USER_UNKNOWN" for r in b["value_rows"])
    ]
    assert table["name"] == "Experimental-Result-Code"
    assert table["fields"]["Kind"] == "result-codes"
    (row,) = [r for r in table["value_rows"] if r["value"] == 5001]
    assert row == {
        "line": row["line"],
        "name": "DIAMETER_ERROR_USER_UNKNOWN",
        "value": 5001,
        "section": "7.4.3.2",
        "origin": "TS29.229",
        "origin_target": {
            "document": "29229-j10",
            "section": "6.2.2.1",
            "name": "DIAMETER_ERROR_USER_UNKNOWN",
        },
    }
    # The origin's token links where the row does.
    (token,) = _tokens([doc["lines"][row["line"]]], "TS29.229")
    assert token["target"] == row["origin_target"]


def test_a_raw_file_s_blocks_describe_its_own_lines(exported):
    """TS 29.061 V6.15.0 clause 17.6.6 prints `Redirected-Host` in the
    Re-Auth-Answer, which the corrected file reads as Redirect-Host."""
    names = {}
    for kind, file in (
        ("raw", exported.raws["29061-6f0"]),
        ("corrected", exported.docs["29061-6f0"]),
    ):
        raa = _block(file, "Message", "17.6.6", "Re-Auth-Answer")
        names[kind] = [m["name"] for m in raa["rule"]["members"]]
        for member in raa["rule"]["members"]:
            assert f" {member['name']} " in _text([file["lines"][member["line"]]])
    assert "Redirected-Host" in names["raw"]
    assert "Redirected-Host" not in names["corrected"]
    assert "Redirect-Host" in names["corrected"]


def test_the_index_names_each_document_s_interfaces(exported):
    summaries = {d["id"]: d for d in exported.index["documents"]}
    assert all(d["interfaces"] is not None for d in summaries.values())
    assert summaries["29329-j10"]["interfaces"] == ["Sh"]
    # One edition differs: TS 29.212's Release 11 has no St.
    assert "St" in summaries["29212-j10"]["interfaces"]
    assert "St" not in summaries["29212-bj0"]["interfaces"]
    # The registry specifies none, and says so.
    assert summaries["29230-j30"]["interfaces"] == []
    assert summaries["rfc6733"]["interfaces"] == ["Base"]


# --- where the corrections and the sources come from ------------------------------


def test_corrections_directory_reads_the_modules_which_agree_with_the_record(
    tmp_path,
):
    books = Corpus.load([_ETSI])
    export_corpus(books, tmp_path / "default")
    export_corpus(
        books, tmp_path / "named", corrections_directory=ROOT / "edits" / "corrections"
    )
    assert _tree(tmp_path / "default") == _tree(tmp_path / "named")

    modules = tmp_path / "modules"
    modules.mkdir()
    with pytest.raises(CorpusError, match="corrections record does not hold"):
        export_corpus(books, tmp_path / "other", corrections_directory=modules)


def test_a_corpus_of_its_own_has_no_version_and_a_stale_record_is_refused(tmp_path):
    corpus = tmp_path / "dad"
    corpus.mkdir()
    source = _CORPUS_DIR / "rfc" / "rfc4004.dad"
    (corpus / source.name).write_bytes(source.read_bytes())

    index = export_corpus(Corpus.load([corpus]), tmp_path / "out")

    assert index.corpus_version is None
    doc = json.loads((tmp_path / "out/documents/rfc4004.json").read_text("utf-8"))
    assert (doc["corrections"], doc["raw"]) == ({}, None)
    assert not (tmp_path / "out/documents/rfc4004.raw.json").exists()

    (corpus / "corrections.json").write_text('{"documents": {}}', "utf-8")
    with pytest.raises(CorpusError, match="seanchai corpus regenerate"):
        export_corpus(Corpus.load([corpus]), tmp_path / "again")


def test_a_self_hosted_export_copies_each_pdf_from_where_the_download_puts_it(
    tmp_path,
):
    """The ETSI directory holds transcriptions, whose PDFs a download puts in
    `transcriptions/`; one missing names the download that fetches it."""
    books = Corpus.load([_ETSI])
    specifications = tmp_path / "specifications"
    fetched = specifications / "transcriptions"
    fetched.mkdir(parents=True)

    with pytest.raises(
        CorpusError, match="seanchai corpus download --only transcribed"
    ):
        export_corpus(
            books, tmp_path / "out", include_pdfs=True, specifications=specifications
        )
    for document in load_catalog().transcribed:
        (fetched / document.file_name).write_bytes(b"%PDF-test")
    index = export_corpus(
        books, tmp_path / "out", include_pdfs=True, specifications=specifications
    )

    assert index.mode == "self-hosted"
    for doc in index.documents:
        assert doc.source.local is not None
        assert (tmp_path / "out" / doc.source.local).read_bytes() == b"%PDF-test"

    (specifications / "copy").mkdir()
    for document in load_catalog().transcribed:
        (specifications / "copy" / document.file_name).write_bytes(b"other")
    with pytest.raises(CorpusError, match="conflicting PDF copies"):
        export_corpus(
            books, tmp_path / "again", include_pdfs=True, specifications=specifications
        )


def test_a_public_export_copies_the_rfc_texts_a_download_holds(tmp_path):
    books = Corpus.load([_CORPUS_DIR / "rfc"])
    sources = tmp_path / "specifications"
    (sources / "rfc").mkdir(parents=True)
    text = b"RFC 6733\n\f6.7.2.  Proxy-Info AVP\n"
    (sources / "rfc/rfc6733.txt").write_bytes(text)

    index = export_corpus(books, tmp_path / "export", specifications=sources)

    (doc,) = [d for d in index.documents if d.source.text is not None]
    assert doc.reference == "RFC6733"
    assert doc.source.local is None
    assert (tmp_path / "export" / doc.source.text).read_bytes() == text


# --- the output directory -------------------------------------------------------------


def _with_pdfs(tmp_path: Path) -> Path:
    specifications = tmp_path / "specifications"
    (specifications / "transcriptions").mkdir(parents=True)
    for document in load_catalog().transcribed:
        (specifications / "transcriptions" / document.file_name).write_bytes(b"%PDF")
    return specifications


def test_an_export_replaces_the_previous_one_whole_keeping_its_mode(tmp_path):
    output = tmp_path / "out"
    self_hosted = ["--include-pdfs", "--specifications", str(_with_pdfs(tmp_path))]

    def export(*options: str):
        result = CliRunner().invoke(
            main, ["export", "--corpus", str(_ETSI), "-o", str(output), *options]
        )
        assert result.exit_code == 0, result.output

    export(*self_hosted)
    assert list((output / "sources").glob("*.pdf"))
    assert output.stat().st_mode & 0o777 != 0o700
    output.chmod(0o750)
    (output / "documents" / "removed.json").write_text("{}", "utf-8")

    export()

    assert json.loads((output / "index.json").read_text("utf-8"))["mode"] == "public"
    assert output.stat().st_mode & 0o777 == 0o750
    export_corpus(Corpus.load([_ETSI]), tmp_path / "fresh")
    assert _tree(output) == _tree(tmp_path / "fresh")
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "fresh",
        "out",
        "specifications",
    ]


def test_an_export_follows_a_symlinked_output(tmp_path):
    real = tmp_path / "real"
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    export_corpus(Corpus.load([_ETSI]), link)

    assert link.is_symlink()
    assert (real / "index.json").is_file()


@pytest.mark.parametrize(
    ("index", "replaced"),
    [
        ("empty", True),
        (None, False),
        ({"schema_version": 1}, False),
        ({"name": "my-package", "version": "1.0.0"}, False),
        (["generator"], False),
        ({"generator": "someone-else", "schema_version": 1}, False),
        # Shaped as an export's but not saying so.
        (
            {
                "schema_version": 1,
                "seanchai_version": None,
                "corpus_version": None,
                "mode": "public",
                "documents": [],
            },
            False,
        ),
        ({"generator": "seanchai"}, True),
        ({"schema_version": 99, "generator": "seanchai"}, True),
    ],
)
def test_only_an_earlier_export_s_directory_is_replaced(tmp_path, index, replaced):
    output = tmp_path / "out"
    output.mkdir()
    if index not in (None, "empty"):
        (output / "index.json").write_text(json.dumps(index), "utf-8")
    if index != "empty":
        (output / "mine.txt").write_text("mine", "utf-8")
    before = _tree(output)

    if replaced:
        export_corpus(Corpus.load([_ETSI]), output)
        assert not (output / "mine.txt").exists()
        assert (output / "index.json").is_file()
        return
    with pytest.raises(CorpusError, match="not empty and holds no Seanchaí export"):
        export_corpus(Corpus.load([_ETSI]), output)
    assert _tree(output) == before


def test_a_file_as_output_is_refused(tmp_path):
    output = tmp_path / "out"
    output.write_text("mine", "utf-8")

    with pytest.raises(CorpusError, match="not a directory"):
        export_corpus(Corpus.load([_ETSI]), output)

    assert output.read_text("utf-8") == "mine"


def _exported_before(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    output = tmp_path / "out"
    export_corpus(Corpus.load([_ETSI]), output)
    return output, _tree(output)


def test_a_failed_export_leaves_the_previous_one_as_it_was(tmp_path):
    output, before = _exported_before(tmp_path)
    empty = tmp_path / "specifications"
    empty.mkdir()

    with pytest.raises(CorpusError, match="no downloaded PDF"):
        export_corpus(
            Corpus.load([_ETSI]), output, include_pdfs=True, specifications=empty
        )

    assert _tree(output) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out", "specifications"]


def _rename_failing(monkeypatch, *, staged=None, backup=None, after=None):
    """Make renaming the staged export or the backup back raise, or `after`
    raise once the rename of that path is done."""
    rename = Path.rename

    def failing(self, target):
        if staged and self.name == "new":
            raise staged
        if backup and ".previous-" in self.name:
            raise backup
        moved = rename(self, target)
        if after is not None and self == after:
            raise KeyboardInterrupt
        return moved

    monkeypatch.setattr(Path, "rename", failing)


@pytest.mark.parametrize(
    "failure",
    ["no-room", "interrupted", "interrupted-after-the-backup"],
)
def test_a_failed_swap_restores_the_previous_export(tmp_path, monkeypatch, failure):
    output, before = _exported_before(tmp_path)
    if failure == "interrupted-after-the-backup":
        # Nothing but the backup holds the previous export when it arrives.
        _rename_failing(monkeypatch, after=output)
    else:
        error = OSError("no room") if failure == "no-room" else KeyboardInterrupt()
        _rename_failing(monkeypatch, staged=error)

    with pytest.raises((OSError, KeyboardInterrupt)):
        export_corpus(Corpus.load([_ETSI]), output)

    assert _tree(output) == before
    assert [p.name for p in tmp_path.iterdir()] == ["out"]


def test_a_failed_restoration_keeps_the_backup_and_names_it(tmp_path, monkeypatch):
    output, before = _exported_before(tmp_path)
    backup = tmp_path / f"out.previous-{os.getpid()}"
    _rename_failing(monkeypatch, staged=OSError("no room"), backup=OSError("read-only"))

    with pytest.raises(CorpusError) as refused:
        export_corpus(Corpus.load([_ETSI]), output)

    assert str(backup) in str(refused.value)
    assert "read-only" in str(refused.value)
    assert not output.exists()
    assert _tree(backup) == before


def test_a_backup_already_there_is_not_overwritten(tmp_path):
    """The name holds a pid, which comes round again: what an earlier run could
    not restore stops this one rather than being replaced."""
    output, before = _exported_before(tmp_path)
    backup = tmp_path / f"out.previous-{os.getpid()}"
    backup.mkdir()
    (backup / "index.json").write_text("earlier", "utf-8")

    with pytest.raises(OSError):
        export_corpus(Corpus.load([_ETSI]), output)

    assert _tree(output) == before
    assert (backup / "index.json").read_text("utf-8") == "earlier"


def test_a_name_set_off_by_spaces_is_spanned_and_a_kept_struck_member_is_said(
    tmp_path,
):
    """A hand-written corpus may space a directive's value out, and print a
    member struck through without commenting it out."""
    corpus = tmp_path / "dad"
    corpus.mkdir()
    text = (_CORPUS_DIR / "rfc" / "rfc4004.dad").read_text("utf-8")
    name = "; Name: AA-Mobile-Node-Request, AMR"
    member = (
        "    { Session-Id }" if "    { Session-Id }" in text else "    < Session-Id >"
    )
    assert name in text and member in text
    text = text.replace(name, name.replace("Name: ", "Name:    "), 1)
    text = text.replace(member, f"{member} ; strikethrough", 1)
    (corpus / "rfc4004.dad").write_text(text, "utf-8")

    export_corpus(Corpus.load([corpus]), tmp_path / "out")

    doc = json.loads((tmp_path / "out/documents/rfc4004.json").read_text("utf-8"))
    lines = [
        "".join(token["text"] for token in line["tokens"]) for line in doc["lines"]
    ]
    block = next(b for b in doc["blocks"] if b.get("abbreviation") == "AMR")
    assert sorted(
        lines[span["line"]][span["start"] : span["end"]] for span in block["commands"]
    ) == ["AA-Mobile-Node-Request", "AA-Mobile-Node-Request", "AMR"]
    first = block["rule"]["members"][0]
    assert (first["name"], first.get("strikethrough"), first.get("struck")) == (
        "Session-Id",
        True,
        None,
    )
