"""Extractor: 3GPP .docx specification → `.dad` AST.

Pipeline stage one of two: this module walks the docx body (paragraphs and
tables in document order, grouped under numbered headings) and produces a
`Specification`. Pages are attached afterwards by `attach_pages`, which reads
only the bookmark outline of the matching ETSI PDF rendering.

All source text is normalized exactly once, while building the section model,
and input patches (see `patches.py`) are applied at that same point — so
patch application counting is exact, and every later parsing step sees
patched text.

What maps to what in a 3GPP Diameter spec docx:

- `x.y.z Name (ABBR) Command` headings with a `::= < Diameter Header: ... >`
  paragraph run → `Message`; per-run bold marks this-spec AVPs.
- `x.y.z Name AVP` headings with an `::= < AVP header: ... >` run → `GroupedAvp`.
- `x.y.z Name AVP` headings whose intro says "is of type Enumerated" with
  `B1`-style `ValueName (n)` items → `EnumeratedAvp`; `B2` items are value
  descriptions, `NO`-style "Value n is reserved" notes → reserved values,
  inserted in numeric order.
- The AVP-flags table (header "AVP Flag rules") → `AvpTable`; rows whose code
  cell is a NOTE reference get `code=None`, and note texts naming a defining
  RFC additionally produce `ReusedAvps` rows.
- The "re-used Diameter AVPs" table → `ReusedAvps` rows with M-bit overrides.

The vendor-id for locally defined AVPs is not printed by enumerated-AVP
sections, so it is taken from the spec's grouped-AVP headers (3GPP: 10415).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import docx
import docx.document
import docx.table
import docx.text.paragraph
import pydantic
import pypdf

from ..dad import abnf, ast
from .errors import ExtractionError
from .patches import Patcher

_HEADING_RE = re.compile(r"^(?P<number>\d+(?:\.\d+[A-Z]*)*)\t(?P<title>.+)$")
_COMMAND_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) Command$"
)
# The " AVP" suffix is spec-dependent: 29.329 titles are "MSISDN AVP",
# 29.272 mostly bare "Subscription-Data". Bare titles like "General" also
# match — harmless, since a section only becomes a definition when its body
# holds an AVP-header rule or an Enumerated intro with a known code.
_AVP_TITLE_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)( AVP)?$")
_DIAMETER_HEADER_RE = re.compile(
    # The rule name is normalized separately: source docx sometimes carries
    # stray spaces inside it ("< User-Data -Request>").
    r"^<\s*(?P<name>[A-Za-z -]+?)\s*> ::=\s*<\s*Diameter Header:"
    r"\s*(?P<items>[0-9A-Z, ]+?)\s*>$"
)
_AVP_HEADER_RE = re.compile(
    # code/vendor separator varies between specs: "700 10415" and "632, 10415";
    # rule names can carry spaces for hyphens ("Monitoring Event Report::=")
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9 -]*?)\s*::=\s*<\s*AVP [Hh]eader:\s*(?P<code>\d+)"
    r"(?:\s*,?\s+(?P<vendor>\d+))?\s*>$"
)
_ABNF_LINE_RE = re.compile(
    r"^(?:(?P<min>\d*)\*(?P<max>\d*))?\s*"
    r"(?P<open>[<{\[])\s*(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)\s*(?P<close>[>}\]])$"
)
_ENUM_VALUE_RE = re.compile(r"^(?P<name>[A-Za-z0-9_-]+)\s*\((?P<value>\d+)\)$")
_RESERVED_NOTE_RE = re.compile(
    r"[Vv]alues? (?P<first>\d+)(?:\s*(?:-|to)\s*(?P<last>\d+))?\s+(?:is|are) reserved"
)
_TABLE_CAPTION_RE = re.compile(r"^Table (?P<label>[\d.]+(?:/\d+)?[A-Z]?):")
_NOTE_REF_RE = re.compile(r"\s*NOTE\s*(?P<number>\d+)\s*")
_NOTE_RFC_RE = re.compile(
    r"^NOTE\s*(?P<number>\d+):\s*The values? of th(?:is|ese) attributes? "
    r"is defined in IETF\s+RFC\s+(?P<rfc>\d+)"
)
_DOCX_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) V(?P<version>\d+(?:\.\d+)*)"
)
_PDF_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) version (?P<version>\d+(?:\.\d+)*)"
)
_ORIGIN_TS_RE = re.compile(r"3GPP\s+TS\s+(?P<number>\d{2}\.\d{3})")
_ORIGIN_RFC_RE = re.compile(r"IETF\s+RFC\s+(?P<number>\d+)")

_M_BIT_OVERRIDES = {
    "": None,
    "Must set": ast.MBitOverride.MUST,
    "Must not set": ast.MBitOverride.MUST_NOT,
}


def _normalize(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


@dataclass
class _Para:
    """A body paragraph: normalized+patched text, style name, and the docx
    paragraph (kept for run-level bold inspection)."""

    text: str
    style: str
    source: docx.text.paragraph.Paragraph


@dataclass
class _Row:
    cells: list[str]
    # The first cell's individual lines (normalized+patched) — merged
    # full-width NOTE rows hold one note per line.
    first_cell_lines: list[str]


@dataclass
class _Table:
    caption: str | None
    rows: list[_Row]


@dataclass
class _Section:
    """One numbered heading with the body content up to the next heading."""

    number: str
    title: str
    paragraphs: list[_Para] = field(default_factory=list)
    tables: list[_Table] = field(default_factory=list)


def _is_bold(paragraph: docx.text.paragraph.Paragraph) -> bool:
    # Word applies bold erratically to brackets/whitespace runs; only the runs
    # spelling the AVP name itself are trusted (`*{ `=True, `Data-Reference`=None,
    # ` }`=True occurs in real documents for a non-bold AVP).
    flags = {
        bool(run.bold)
        for run in paragraph.runs
        if any(char.isalnum() for char in run.text)
    }
    if len(flags) > 1:
        raise ExtractionError(f"mixed bold in ABNF line: {paragraph.text!r}")
    return flags.pop() if flags else False


def _sections(document: docx.document.Document, patcher: Patcher) -> list[_Section]:
    sections: list[_Section] = []
    current: _Section | None = None
    caption: str | None = None
    for item in document.iter_inner_content():
        number = current.number if current is not None else None
        if isinstance(item, docx.table.Table):
            if current is not None:
                rows = []
                for row in item.rows:
                    # Merged cells appear repeatedly in row.cells (a full-width
                    # note row repeats one cell nine times); count each physical cell
                    # once. Per-line views of the first cell are duplicates of
                    # already-counted text, so they don't record either.
                    seen: dict[int, str] = {}
                    cells = []
                    for cell in row.cells:
                        key = id(cell._tc)
                        if key not in seen:
                            seen[key] = patcher.apply(_normalize(cell.text), number)
                        cells.append(seen[key])
                    rows.append(
                        _Row(
                            cells=cells,
                            first_cell_lines=[
                                patcher.apply(_normalize(line), number, record=False)
                                for line in row.cells[0].text.splitlines()
                            ],
                        )
                    )
                current.tables.append(_Table(caption=caption, rows=rows))
            caption = None
            continue
        style = (item.style.name or "") if item.style else ""
        if style.startswith("Heading"):
            match = _HEADING_RE.match(item.text.strip())
            if match:
                current = _Section(
                    number=match["number"],
                    title=patcher.apply(_normalize(match["title"]), match["number"]),
                )
                sections.append(current)
                continue
        text = patcher.apply(_normalize(item.text), number)
        if match := _TABLE_CAPTION_RE.match(text):
            caption = match["label"]
        if current is not None:
            current.paragraphs.append(_Para(text=text, style=style, source=item))
    return sections


def _abnf_body(
    paragraphs: list[_Para], start: int
) -> tuple[tuple[ast.AvpRule, ...], int]:
    """Parse `[qual] bracket Name bracket` lines starting at `start`."""
    rules = []
    index = start
    while index < len(paragraphs):
        paragraph = paragraphs[index]
        match = _ABNF_LINE_RE.match(paragraph.text)
        if match is None:
            break
        try:
            rules.append(abnf.avp_rule(match, bold=_is_bold(paragraph.source)))
        except abnf.AbnfError as error:
            raise ExtractionError(f"{error} in {paragraph.text!r}") from None
        index += 1
    return tuple(rules), index


def _find_rule_header(
    section: _Section, pattern: re.Pattern
) -> tuple[re.Match, int] | None:
    for index, paragraph in enumerate(section.paragraphs):
        if "::=" in paragraph.text:
            match = pattern.match(paragraph.text)
            if match is None:
                raise ExtractionError(
                    f"{section.number}: malformed rule header {paragraph.text!r}"
                )
            return match, index + 1
    return None


def _extract_messages(
    section: _Section, title: re.Match, warnings: list[str]
) -> list[ast.Message]:
    """A command section usually holds one ABNF, but can hold several — the
    same command under different application ids (TS 29.272 defines IDR/DSR/RSR
    once for S6a and once for S7a in one section)."""
    messages = []
    index = 0
    while index < len(section.paragraphs):
        text = section.paragraphs[index].text
        index += 1
        if "::=" not in text:
            continue
        header = _DIAMETER_HEADER_RE.match(text)
        if header is None:
            raise ExtractionError(f"{section.number}: malformed rule header {text!r}")
        rule_name = header["name"].replace(" ", "")
        if rule_name != title["name"]:
            # A real occurrence: TS 29.329 §6.1.8 heading says
            # "Push-Notifications-Answer", the rule "Push-Notification-Answer".
            # The rule name wins; the discrepancy is reported, not fatal.
            warnings.append(
                f"{section.number}: heading name {title['name']!r}"
                f" != rule name {rule_name!r}, using the rule name"
            )
        try:
            command_code, flags, application_id = abnf.diameter_header(header["items"])
        except abnf.AbnfError as error:
            raise ExtractionError(f"{section.number}: {error}") from None
        if application_id is None:
            warnings.append(
                f"{section.number}: {rule_name} header omits the application id"
            )
        avps, index = _abnf_body(section.paragraphs, index)
        messages.append(
            ast.Message(
                name=rule_name,
                abbreviation=title["abbr"],
                source=ast.SourceRef(section=section.number),
                command_code=command_code,
                flags=flags,
                application_id=application_id,
                avps=avps,
            )
        )
    if not messages:
        raise ExtractionError(f"{section.number}: command section without ABNF")
    return messages


def _extract_grouped(
    section: _Section, header: re.Match, body_start: int, name: str
) -> ast.GroupedAvp:
    vendor = header["vendor"]
    avps, _ = _abnf_body(section.paragraphs, body_start)
    return ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=int(header["code"]),
        vendor_id=None if vendor is None else int(vendor),
        avps=avps,
    )


def _extract_enumerated(
    section: _Section, name: str, code: int, vendor_id: int | None
) -> ast.EnumeratedAvp:
    values: list[ast.EnumValue] = []
    reserved: list[ast.ReservedValues] = []
    # Classified by content, not paragraph style: the usual convention is
    # value=B1/description=B2, but human-written specs invert it (29.229
    # §6.3.34 has the value in Normal and the description in B1).
    for paragraph in section.paragraphs:
        text = paragraph.text
        if not text:
            continue
        if match := _ENUM_VALUE_RE.fullmatch(text):
            values.append(ast.EnumValue(name=match["name"], value=int(match["value"])))
        elif paragraph.style == "NO":
            if match := _RESERVED_NOTE_RE.search(text):
                first = int(match["first"])
                reserved.append(
                    ast.ReservedValues(first=first, last=int(match["last"] or first))
                )
        elif paragraph.style in ("B1", "B2") and values:
            previous = values[-1].description
            values[-1] = values[-1].model_copy(
                update={"description": f"{previous} {text}" if previous else text}
            )
    merged = sorted(
        [*values, *reserved],
        key=lambda item: item.value if isinstance(item, ast.EnumValue) else item.first,
    )
    return ast.EnumeratedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        code=code,
        vendor_id=vendor_id,
        values=tuple(merged),
    )


def _strip_note_ref(text: str) -> tuple[str, str | None]:
    match = _NOTE_REF_RE.search(text)
    if match is None:
        return text, None
    return (text[: match.start()] + text[match.end() :]).strip(), match["number"]


def _flags_cell(text: str) -> frozenset[ast.AvpFlag]:
    # Strict: typos like "M. V" or lowercase "v" are fixed by input patches,
    # not tolerated here.
    if not text:  # an empty table cell
        return frozenset()
    try:
        return abnf.avp_flags(text)
    except abnf.AbnfError as error:
        raise ExtractionError(str(error)) from None


def _extract_avp_table(
    table: _Table, section_number: str
) -> tuple[ast.AvpTable, list[ast.ReusedAvpRow]]:
    rows: list[ast.AvpTableRow] = []
    note_refs: list[tuple[str, str]] = []  # (avp name, note number)
    note_rfcs: dict[str, str] = {}  # note number -> RFC number
    for row in table.rows:
        cells = row.cells
        if cells[0].startswith("NOTE"):  # merged full-width row, one note per line
            for line in row.first_cell_lines:
                if match := _NOTE_RFC_RE.match(line):
                    note_rfcs[match["number"]] = match["rfc"]
            continue
        if cells[0] in ("", "Attribute Name") or cells[0] == cells[1]:
            continue  # header rows (merged cells repeat the same text)
        if len(cells) != 9:
            raise ExtractionError(f"AVP table row with {len(cells)} cells: {cells!r}")
        name, name_note = _strip_note_ref(cells[0])
        if " " in name:
            # AVP names never contain spaces; line-wrap artifacts eating a
            # hyphen (29.272 "MME-Location Information") are input-patched.
            raise ExtractionError(f"AVP table name cell {name!r} contains spaces")
        code, code_note = _strip_note_ref(cells[1])
        if note := name_note or code_note:
            note_refs.append((name, note))
        rows.append(
            ast.AvpTableRow(
                name=name,
                code=int(code) if code else None,
                section=cells[2] or None,
                data_type=cells[3],
                flag_rules=ast.AvpFlagRules(
                    must=_flags_cell(cells[4]),
                    may=_flags_cell(cells[5]),
                    should_not=_flags_cell(cells[6]),
                    must_not=_flags_cell(cells[7]),
                ),
                may_encrypt={"Yes": True, "No": False}[cells[8]],
            )
        )
    if table.caption is None:
        raise ExtractionError("AVP table without a caption")
    reused = [
        ast.ReusedAvpRow(name=name, origin=f"RFC{note_rfcs[note]}")
        for name, note in note_refs
        if note in note_rfcs
    ]
    avp_table = ast.AvpTable(
        table=table.caption,
        rows=tuple(rows),
        source=ast.SourceRef(section=section_number),
    )
    return avp_table, reused


def _origin(reference: str) -> str:
    if match := _ORIGIN_TS_RE.search(reference):
        return f"TS{match['number']}"
    if match := _ORIGIN_RFC_RE.search(reference):
        return f"RFC{match['number']}"
    raise ExtractionError(f"unrecognized origin reference {reference!r}")


def _extract_reused_table(table: _Table, warnings: list[str]) -> list[ast.ReusedAvpRow]:
    rows = []
    for row in table.rows:
        cells = row.cells
        if cells[0] in ("", "Attribute Name") or cells[0].startswith("NOTE"):
            continue
        name, _ = _strip_note_ref(cells[0])
        m_bit_cell = cells[3]
        if m_bit_cell == cells[0]:
            # Horizontally merged row: python-docx repeats the first cell's
            # text in the missing position (TS 29.272 Battery-Indicator row).
            warnings.append(
                f"re-used AVPs row {name!r} has a merged M-bit cell, treating as empty"
            )
            m_bit_cell = ""
        rows.append(
            ast.ReusedAvpRow(
                name=name, origin=_origin(cells[1]), m_bit=_M_BIT_OVERRIDES[m_bit_cell]
            )
        )
    return rows


def _spec_and_version(document: docx.document.Document) -> tuple[str, str]:
    for item in document.iter_inner_content():
        if isinstance(item, docx.table.Table):
            for row in item.rows:
                for cell in row.cells:
                    if match := _DOCX_COVER_RE.search(_normalize(cell.text)):
                        return f"3GPP {match['spec']}", match["version"]
    raise ExtractionError("cannot find spec number/version on the cover page")


def _pdf_spec_and_version(reader: pypdf.PdfReader) -> tuple[str, str]:
    """An ETSI rendering prints its own title on the cover, with the 3GPP
    original in parentheses: "(3GPP TS 29.272 version 18.6.0 Release 18)"."""
    if not reader.pages:
        raise ExtractionError("PDF has no pages")
    cover = _normalize(reader.pages[0].extract_text())
    match = _PDF_COVER_RE.search(cover)
    if match is None:
        raise ExtractionError("cannot find spec number/version on the PDF cover page")
    return f"3GPP {match['spec']}", match["version"]


@dataclass
class _Collected:
    """What one pass over the document found, before anything is cross-checked.

    Tables are kept as lists rather than as a single winner: a document with two
    AVP tables is not something any collected spec does, and quietly keeping the
    last one would hide it.
    """

    messages: list[ast.Message] = field(default_factory=list)
    grouped: list[ast.GroupedAvp] = field(default_factory=list)
    # Sections that read like an enumerated AVP, with the name from the
    # heading. They cannot become definitions until the AVP table is known —
    # that is where their code comes from.
    pending_enums: list[tuple[_Section, str]] = field(default_factory=list)
    # Each table is paired with what identifies it: the section it was found
    # in for AVP tables, the caption label for re-used tables.
    avp_tables: list[tuple[ast.AvpTable, str]] = field(default_factory=list)
    reused_tables: list[tuple[list[ast.ReusedAvpRow], str]] = field(
        default_factory=list
    )
    # Reused rows derived from AVP-table NOTEs rather than from a reused table.
    note_reused: list[ast.ReusedAvpRow] = field(default_factory=list)


@dataclass
class _Resolved:
    """Definitions after cross-section resolution: every enumerated AVP has a
    code and a vendor-id, and external AVPs have been dropped."""

    messages: list[ast.Message]
    avp_table: ast.AvpTable
    tables_section: str
    reused: list[ast.ReusedAvpRow]
    reused_label: str
    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp]


def _collect(sections: list[_Section], warnings: list[str]) -> _Collected:
    """Walk the document once, classifying sections. Source-shaped work only:
    nothing here needs to know about another section."""
    collected = _Collected()
    for section in sections:
        if title := _COMMAND_TITLE_RE.match(section.title):
            collected.messages.extend(_extract_messages(section, title, warnings))
            continue
        for table in section.tables:
            header = table.rows[0].cells
            if "AVP Flag rules" in header:
                avp_table, note_reused = _extract_avp_table(table, section.number)
                collected.avp_tables.append((avp_table, section.number))
                collected.note_reused.extend(note_reused)
            elif "Reference" in header and "M-bit" in header:
                if table.caption is None:
                    raise ExtractionError("re-used AVPs table without a caption")
                collected.reused_tables.append(
                    (_extract_reused_table(table, warnings), table.caption)
                )
        if title := _AVP_TITLE_RE.match(section.title):
            found = _find_rule_header(section, _AVP_HEADER_RE)
            if found is not None:
                header, body_start = found
                rule_name = header["name"]
                if " " in rule_name:
                    # Spaces-for-hyphens rule names (29.272 §7.3.196
                    # "Monitoring Event Report") are input-patched.
                    raise ExtractionError(
                        f"{section.number}: rule name {rule_name!r} contains spaces"
                    )
                if rule_name != title["name"]:
                    warnings.append(
                        f"{section.number}: heading name"
                        f" {title['name']!r} != rule name {rule_name!r},"
                        " using the rule name"
                    )
                collected.grouped.append(
                    _extract_grouped(section, header, body_start, name=rule_name)
                )
            elif section.paragraphs and "type Enumerated" in section.paragraphs[0].text:
                collected.pending_enums.append((section, title["name"]))
    return collected


def _resolve(collected: _Collected) -> _Resolved:
    """Cross-section work: pick the tables, then turn pending enumerated
    sections into definitions using codes from the AVP table."""
    if not collected.avp_tables:
        raise ExtractionError("no AVP table found")
    if len(collected.avp_tables) > 1:
        found = ", ".join(number for _, number in collected.avp_tables)
        raise ExtractionError(f"more than one AVP table found, in sections {found}")
    if len(collected.reused_tables) > 1:
        found = ", ".join(label for _, label in collected.reused_tables)
        raise ExtractionError(f"more than one re-used AVPs table found: {found}")
    avp_table, tables_section = collected.avp_tables[0]
    reused_rows, reused_label = (
        collected.reused_tables[0] if collected.reused_tables else ([], avp_table.table)
    )

    codes = {row.name: row.code for row in avp_table.rows}
    # Enumerated sections never print the vendor-id, so it comes from the
    # spec's grouped-AVP headers — one value per 3GPP spec (10415).
    vendors = {avp.vendor_id for avp in collected.grouped if avp.vendor_id is not None}
    vendor_id = vendors.pop() if len(vendors) == 1 else None
    # AVPs originating in other specs get no local definition, even when their
    # section is worded like one (e.g. DRMP: "is of type Enumerated" but the
    # values are defined in RFC 7944).
    external = {row.name for row in [*reused_rows, *collected.note_reused]}

    enumerated = []
    for section, name in collected.pending_enums:
        if name in external:
            continue
        code = codes.get(name)
        if code is None:
            raise ExtractionError(
                f"{section.number}: enumerated AVP {name!r}"
                " has no code in the AVP table"
            )
        enumerated.append(_extract_enumerated(section, name, code, vendor_id))

    return _Resolved(
        messages=collected.messages,
        avp_table=avp_table,
        tables_section=tables_section,
        reused=[*reused_rows, *collected.note_reused],
        reused_label=reused_label,
        definitions=[*collected.grouped, *enumerated],
    )


def _assemble(resolved: _Resolved) -> tuple[ast.Section, ...]:
    """File order: messages, the AVP table, the reused table, then every
    definition in document order."""
    sections: list[ast.Section] = [*resolved.messages, resolved.avp_table]
    if resolved.reused:
        sections.append(
            ast.ReusedAvps(
                table=resolved.reused_label,
                source=ast.SourceRef(section=resolved.tables_section),
                rows=tuple(resolved.reused),
            )
        )
    sections.extend(
        sorted(
            resolved.definitions,
            key=lambda definition: _section_sort_key(definition.source.section),
        )
    )
    return tuple(sections)


def _section_sort_key(section: str) -> list[tuple[int, str]]:
    """Document order for section numbers: "6.3.10" sorts after "6.3.4", and
    "6.3.7A" after "6.3.7"."""
    key = []
    for part in section.split("."):
        digits = re.match(r"\d+", part)
        # `SectionNumber` guarantees every part starts with digits.
        assert digits is not None, f"malformed section number {section!r}"
        key.append((int(digits[0]), part))
    return key


def patch_file_name(specification: str) -> str:
    """Patch file name for a cover-page spec title: "3GPP TS 29.272" →
    "TS29.272.toml"."""
    return f"{ast.spec_ref(specification)}.toml"


def extract(
    docx_path: Path | str,
    link: str | None = None,
    warnings: list[str] | None = None,
    patches_dir: Path | None = None,
) -> ast.Specification:
    """Extract a `Specification` from a 3GPP docx. Non-fatal source-document
    inconsistencies are appended to `warnings` when a list is given. When
    `patches_dir` is given, input patches from `<patches_dir>/<SpecRef>.toml`
    (if present) are applied to the normalized source text before parsing."""
    warnings = warnings if warnings is not None else []
    document = docx.Document(str(docx_path))
    specification, version = _spec_and_version(document)
    patch_path = (
        patches_dir / patch_file_name(specification)
        if patches_dir is not None
        else None
    )
    patcher = Patcher.load(patch_path, version)

    collected = _collect(_sections(document, patcher), warnings)
    patcher.finish()
    sections = _assemble(_resolve(collected))
    return ast.Specification(
        specification=specification,
        version=version,
        link=None if link is None else pydantic.HttpUrl(link),
        sections=sections,
    )


def attach_pages(
    spec: ast.Specification,
    pdf_path: Path | str,
    warnings: list[str] | None = None,
) -> ast.Specification:
    """Attach PDF page numbers to every section, from the ETSI PDF bookmark
    outline (section number → 1-based page of the first outline entry that
    starts with it).

    The PDF must render the same specification and version as `spec`: page
    numbers from a neighbouring version are wrong in a way nothing downstream
    can detect, and the downloader will happily fetch an earlier ETSI rendering
    when the exact one is not published yet.
    """
    warnings = warnings if warnings is not None else []
    reader = pypdf.PdfReader(str(pdf_path))
    specification, version = _pdf_spec_and_version(reader)
    if (specification, version) != (spec.specification, spec.version):
        raise ExtractionError(
            f"PDF renders {specification} V{version}, but the extracted"
            f" specification is {spec.specification} V{spec.version}"
            " — its page numbers do not apply"
        )
    pages: dict[str, int] = {}

    def walk(entries) -> None:
        for entry in entries:
            if isinstance(entry, list):
                walk(entry)
                continue
            match = re.match(r"^(\d+(?:\.\d+[A-Z]*)*)\s", entry.title)
            if match is None:
                continue
            # pypdf types an outline destination as `IndirectObject` and
            # `get_page_number` as optional; both resolve for a real outline.
            destination = entry.page or reader.pages[0]
            number = reader.get_page_number(destination)  # pyright: ignore[reportArgumentType]
            if number is not None:
                pages[match.group(1)] = number + 1

    walk(reader.outline)
    if not pages:
        raise ExtractionError(
            "PDF bookmark outline has no numbered sections — wrong file, or a"
            " rendering without an outline"
        )

    def with_page(section):
        page = pages.get(section.source.section)
        if page is None:
            return section
        return section.model_copy(
            update={"source": ast.SourceRef(section=section.source.section, page=page)}
        )

    attached = tuple(with_page(section) for section in spec.sections)
    covered = sum(1 for section in attached if section.source.page is not None)
    if covered < len(attached):
        # Not fatal on its own — some sections legitimately have no bookmark —
        # but a low count means the outline and the docx disagree about section
        # numbering, which is worth seeing before the file gets committed.
        warnings.append(f"bookmark outline covered {covered}/{len(attached)} sections")
    return spec.model_copy(update={"sections": attached})
