import dataclasses
import difflib
import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .corpus import CITED_AS, Corpus, CorpusError, Entry
from .dad import ast, corrections, parser
from .downloader import load_catalog
from .linter import lint_with_corpus
from .model import Model

_LEXEME = re.compile(
    r';;[^\n]*?(?=;;|\n|$)|https?://[^\s]+|"(?:[^"\\]|\\.)*"|::='
    r"|[A-Za-z0-9_]+(?:[.\-/][A-Za-z0-9_*]+)*|[^\w\s]"
)
_CORRECTION = re.compile(r"\(([\w.-]+\.py#[\w-]+)\)")


def document_id(entry: Entry) -> str:
    return entry.path.stem


def _names(spec: ast.Specification) -> set[str]:
    names = set()
    for section in spec.sections:
        if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp | ast.UndefinedAvp):
            names.add(section.name)
        if isinstance(section, ast.AvpTable | ast.ReusedAvps):
            names.update(row.name for row in section.rows)
        if isinstance(section, ast.GroupedAvp | ast.Message):
            names.update(rule.name for rule in section.avps if rule.name != "AVP")
    return names


def _sections(spec: ast.Specification) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for section in spec.sections:
        source = section.source.model_dump()
        found.setdefault(source["section"], source)
    for section in spec.sections:
        source = section.source.model_dump()
        if isinstance(section, ast.AvpTable):
            for row in section.rows:
                if row.section:
                    found.setdefault(row.section, {**source, "section": row.section})
    return found


def _target(entry: Entry, section: str | None) -> dict:
    return {"document": document_id(entry), "section": section}


def _tokens(
    text: str,
    spec: ast.Specification,
    names: dict,
    references: dict,
    row_references: dict | None = None,
) -> list:
    lines = []
    block = -1
    anchored = set()
    defined_sections = {section.source.section for section in spec.sections}
    avp_names = _names(spec)
    for line in text.splitlines(keepends=True):
        if line.startswith("; Type:"):
            block += 1
        section = spec.sections[block] if block >= 0 else None
        source = section.source if section is not None else None
        directive = re.match(r"; ([\w-]+):", line)
        key = directive[1] if directive else None
        rule = re.match(r"\s*\d*\*?\d*\s*([<{\[]) ([\w-]+) ([>}\]])", line)
        enumeration = isinstance(section, ast.EnumeratedAvp) and " = " in line
        row = None
        if isinstance(section, ast.AvpTable | ast.ReusedAvps) and not line.startswith(
            (";", " ", "\n")
        ):
            row = next(
                (row for row in section.rows if line.startswith(row.name + " ")), None
            )
        anchor = None
        if source and line.startswith("; Type:"):
            anchor = source.section
        elif isinstance(section, ast.AvpTable) and isinstance(row, ast.AvpTableRow):
            anchor = (
                row.section if row and row.section not in defined_sections else None
            )
        if anchor in anchored:
            anchor = None
        if anchor:
            anchored.add(anchor)
        tokens = []
        end = 0
        for match in _LEXEME.finditer(line):
            if match.start() > end:
                tokens.append({"text": line[end : match.start()], "class": ""})
            value = match[0]
            token: dict[str, Any] = {"text": value, "class": ""}
            if value in avp_names and key in (None, "Name") and not enumeration:
                token["avp"] = value
            if value.startswith(";;"):
                token["class"] = "comment.line.double-semicolon.dad"
                if correction := _CORRECTION.search(value):
                    token["correction"] = correction[1]
            elif key and directive and match.start() < directive.end():
                if value == key:
                    token["class"] = "keyword.other.directive.dad"
            elif key in ("Section", "Page") and source:
                token["class"] = (
                    "constant.other.section.dad"
                    if key == "Section"
                    else "constant.numeric.dad"
                )
                token["source"] = source.model_dump()
            elif value in references and (key == "Bases" or key is None):
                token["class"] = "entity.name.tag.spec-ref.dad"
                token["target"] = references[value]
                if isinstance(section, ast.ReusedAvps) and key is None:
                    row_name = line.split(maxsplit=1)[0]
                    token["target"] = (row_references or {}).get(
                        (value, row_name), token["target"]
                    )
            elif value in names and key in (None, "Name") and not enumeration:
                if target := names[value]:
                    token["target"] = target
                if key == "Name":
                    token["class"] = "string.unquoted.directive-value.dad"
                elif rule and value == rule[2] and "::=" not in line:
                    token["class"] = {
                        "<": "support.class.avp.fixed.dad",
                        "{": "support.function.avp.required.dad",
                        "[": "variable.other.avp.optional.dad",
                    }[rule[1]]
                elif isinstance(section, ast.Message) and "::=" in line:
                    token["class"] = "entity.name.function.message.dad"
                elif (
                    isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp)
                    and "::=" in line
                ):
                    token["class"] = "entity.name.function.avp.dad"
            elif (
                enumeration
                and match.start() < line.index(" = ")
                and not value.startswith(";")
            ):
                token["class"] = "variable.other.enum.dad"
            elif value in ast.DataType:
                token["class"] = "storage.type.data-type.dad"
            elif key == "Type":
                token["class"] = "storage.type.section.dad"
            elif value in ("REQ", "PXY", "ERR"):
                token["class"] = "constant.language.command-flag.dad"
            elif value.isdigit():
                token["class"] = "constant.numeric.dad"
            elif value == "::=":
                token["class"] = "keyword.operator.definition.dad"
            elif value == "=":
                token["class"] = "keyword.operator.assignment.dad"
            elif value == "*":
                token["class"] = "keyword.operator.occurrences.dad"
            elif value in ("<", ">", "{", "}", "[", "]"):
                kind = {
                    "<": "fixed",
                    ">": "fixed",
                    "{": "required",
                    "}": "required",
                    "[": "optional",
                    "]": "optional",
                }[value]
                token["class"] = f"punctuation.definition.bracket.{kind}.dad"
            elif value.startswith('"') or key:
                token["class"] = "string.unquoted.directive-value.dad"
            if row and source and match.start() == 0 and value == row.name:
                token["source"] = {**source.model_dump(), "name": value, "row": True}
            elif isinstance(row, ast.AvpTableRow) and source and value == row.section:
                token["source"] = {**source.model_dump(), "section": row.section}
            tokens.append(token)
            end = match.end()
        if end < len(line):
            tokens.append({"text": line[end:], "class": ""})
        lines.append(
            {
                "tokens": tokens,
                "anchor": anchor,
                "section": source.section if source else None,
            }
        )
    return lines


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=lambda item: item.model_dump(mode="json"),
        )
        + "\n",
        encoding="utf-8",
    )


def export_corpus(
    books: Corpus,
    output: Path,
    *,
    dictionary: Path | None = None,
    corrections_directory: Path | None = None,
    specifications: Path | None = None,
    include_pdfs: bool = False,
) -> dict:
    entries = sorted(books, key=document_id)
    ids = [document_id(entry) for entry in entries]
    if len(set(ids)) != len(ids):
        raise CorpusError("export needs unique document file names")
    model = Model.build(books, strict=False, dictionary=dictionary)
    by_copy = {(entry.reference, entry.spec.version): entry for entry in entries}
    sections = {document_id(entry): _sections(entry.spec) for entry in entries}
    locations: dict[str, dict[str, str]] = {}
    for entry in entries:
        locations[document_id(entry)] = places = {}
        for section in entry.spec.sections:
            if isinstance(section, ast.GroupedAvp | ast.EnumeratedAvp):
                places[section.name] = section.source.section
        for section in entry.spec.sections:
            if isinstance(section, ast.AvpTable):
                for row in section.rows:
                    places.setdefault(row.name, row.section or section.source.section)
    catalog = load_catalog()
    titles = {f"{s.document_type}{s.number}": s.title for s in catalog.tgpp}
    titles.update({f"RFC{s.number}": s.title for s in catalog.rfc})
    titles.update({ast.spec_ref(s.identifier): s.title for s in catalog.onem2m})
    pinned = {(f"TS{s.number}", s.version): s.reason for s in catalog.pinned}
    pdfs: dict[str, list[Path]] = {}
    if include_pdfs:
        if specifications is None or not specifications.is_dir():
            raise CorpusError("including PDFs needs a specifications directory")
        for path in sorted(specifications.rglob("*.pdf")):
            pdfs.setdefault(path.name, []).append(path)
    documents = []
    search = []
    mentions = []
    for entry in entries:
        spec = entry.spec
        identifier = document_id(entry)
        names = {}
        holes = []
        references = {}
        for reference in sorted({e.reference for e in entries} | set(CITED_AS)):
            resolved = books.resolve(reference, like=spec)
            if resolved is not None:
                references[reference] = _target(resolved, None)
        row_references = {}
        for section in spec.sections:
            if isinstance(section, ast.ReusedAvps):
                for row in section.rows:
                    origin = books.resolve(row.origin, like=spec)
                    if origin is not None:
                        clause = locations[document_id(origin)].get(row.name)
                        row_references[row.origin, row.name] = {
                            **_target(origin, clause),
                            "name": row.name,
                        }
        for name in sorted(_names(spec)):
            avp = model.resolve(entry.reference, name, version=spec.version)
            hole = model.hole(entry.reference, name, version=spec.version)
            target = None
            if avp is not None:
                origin = (
                    entry
                    if avp.defined_in == entry.reference
                    else books.resolve(avp.defined_in, like=spec)
                )
                crossing = avp.across_releases
                if crossing and crossing.cited == avp.defined_in:
                    origin = by_copy.get((avp.defined_in, crossing.version), origin)
                if origin is not None:
                    clause = (
                        avp.section
                        if avp.section in sections[document_id(origin)]
                        else locations[document_id(origin)].get(avp.name)
                    )
                    target = _target(origin, clause)
            if hole is not None:
                holes.append(dataclasses.asdict(hole))
            names[name] = target
            search.append(
                {
                    "name": name,
                    "kind": "AVP",
                    "document": identifier,
                    "target": target,
                    "identity": list(avp.identity) if avp else None,
                    "defined_in": avp.defined_in if avp else None,
                    "alias": avp.wireshark_name
                    if avp
                    else (hole.wireshark_name if hole else None),
                    "data_type": avp.data_type if avp else None,
                    "across_releases": dataclasses.asdict(avp.across_releases)
                    if avp and avp.across_releases
                    else None,
                }
            )
        for section in spec.sections:
            if isinstance(section, ast.Message | ast.ApplicationScope):
                target = _target(entry, section.source.section)
                names[section.name] = target
                search.append(
                    {
                        "name": section.name,
                        "kind": "Command"
                        if isinstance(section, ast.Message)
                        else "Application",
                        "document": identifier,
                        "target": target,
                        "identity": [section.command_code, section.application_id]
                        if isinstance(section, ast.Message)
                        else [section.application_id],
                        "defined_in": entry.reference,
                        "alias": section.abbreviation
                        if isinstance(section, ast.Message)
                        else None,
                        "data_type": None,
                        "across_releases": None,
                    }
                )
            elif isinstance(section, ast.Registry):
                for row in section.rows:
                    if isinstance(row, ast.RegistryRow) and row.name:
                        search.append(
                            {
                                "name": row.name,
                                "kind": section.registry.value,
                                "document": identifier,
                                "target": _target(entry, section.source.section),
                                "identity": [row.code],
                                "defined_in": ", ".join(row.defined_in),
                                "alias": row.abbreviation,
                                "data_type": row.data_type,
                                "across_releases": None,
                            }
                        )
        declarations = corrections.in_release(
            corrections.load(corrections_directory, spec.specification),
            spec.version,
        )
        module = corrections.module_path(Path("."), spec.specification).name
        reasons = {f"{module}#{edit.id}": edit.reason for edit in declarations}
        raw_path = next(
            (
                parent / "raw" / entry.path.relative_to(parent).with_suffix(".raw.dad")
                for parent in entry.path.parents
                if (parent / "raw").is_dir()
            ),
            None,
        )
        raw = None
        if raw_path is not None and raw_path.is_file():
            raw_text = raw_path.read_text(encoding="utf-8")
            raw_names = names.copy()
            raw_references = row_references.copy()
            for edit in reversed(declarations):
                if (
                    isinstance(edit, corrections.Correction)
                    and edit.field == "name"
                    and isinstance(edit.expect, str)
                    and isinstance(edit.replace, str)
                    and not raw_names.get(edit.expect)
                    and edit.replace in raw_names
                ):
                    raw_names[edit.expect] = raw_names[edit.replace]
                    for (reference, name), target in list(raw_references.items()):
                        if name == edit.replace:
                            raw_references[reference, edit.expect] = target
            raw = _tokens(
                raw_text, parser.parse(raw_text), raw_names, references, raw_references
            )

            def normalized(text: str) -> str:
                return " ".join(text.split(";;", 1)[0].split())

            old = [normalized(line) for line in raw_text.splitlines()]
            new = [
                normalized(line)
                for line in entry.path.read_text(encoding="utf-8").splitlines()
            ]
            for tag, first, last, _, _ in difflib.SequenceMatcher(
                None, old, new, autojunk=False
            ).get_opcodes():
                if tag in ("replace", "delete"):
                    for index in range(first, last):
                        if old[index]:
                            raw[index]["warning"] = True
        link = str(spec.link or spec.transcribed or "")
        source: dict[str, Any] = {"url": link, "local": None}
        if entry.reference.startswith("RFC") and specifications is not None:
            text_source = specifications / "rfc" / f"{entry.reference.lower()}.txt"
            if text_source.is_file():
                source["text"] = f"sources/{identifier}.txt"
                destination = output / source["text"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(text_source, destination)
        if include_pdfs and urlparse(link).path.lower().endswith(".pdf"):
            candidates = pdfs.get(unquote(urlparse(link).path.rsplit("/", 1)[-1]), [])
            if not candidates:
                raise CorpusError(f"{identifier}: no downloaded PDF matches {link}")
            if len(candidates) > 1:
                import hashlib

                if (
                    len({hashlib.sha256(p.read_bytes()).digest() for p in candidates})
                    != 1
                ):
                    raise CorpusError(
                        f"{identifier}: conflicting PDF copies for {link}"
                    )
            source["local"] = f"sources/{identifier}.pdf"
            destination = output / source["local"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidates[0], destination)
        publisher = (
            "3GPP"
            if spec.specification.startswith("3GPP ")
            else (
                "IETF"
                if entry.reference.startswith("RFC")
                else spec.specification.split()[0]
            )
        )
        metadata = {
            "id": identifier,
            "reference": entry.reference,
            "specification": spec.specification,
            "version": spec.version,
            "publisher": publisher,
            "release": spec.version.split(".")[0]
            if publisher == "3GPP" and spec.version
            else None,
            "title": titles.get(entry.reference, spec.specification),
            "pinned": pinned.get((entry.reference, spec.version))
            if spec.version
            else None,
            "source": source,
        }
        document = {
            **metadata,
            "sections": list(sections[identifier].values()),
            "lines": _tokens(
                entry.path.read_text(encoding="utf-8"),
                spec,
                names,
                references,
                row_references,
            ),
            "raw": raw,
            "corrections": reasons,
            "holes": holes,
            "findings": [
                dataclasses.asdict(f)
                for f in lint_with_corpus(
                    spec, books, corrections.acceptances(declarations)
                )
            ],
        }
        _json(output / "documents" / f"{identifier}.json", document)
        for index, line in enumerate(document["lines"]):
            text = "".join(t["text"] for t in line["tokens"]).strip()
            if text:
                mentions.append(
                    {
                        "document": identifier,
                        "section": line["section"],
                        "line": index,
                        "text": text,
                        "avps": sorted(
                            {t["avp"] for t in line["tokens"] if "avp" in t}
                        ),
                    }
                )
        documents.append(metadata)
    result = {
        "schema_version": 1,
        "mode": "self-hosted" if include_pdfs else "public",
        "documents": documents,
        "search": search,
        "mentions": mentions,
    }
    _json(output / "index.json", result)
    return result
