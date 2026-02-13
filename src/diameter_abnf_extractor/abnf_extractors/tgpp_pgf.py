from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

SECTION_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Za-z].+")
ABNF_START_RE = re.compile(r"::=")
RULE_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*\s*(=|/)\s*.+")
QUALIFIED_REP_RE = re.compile(r"^\d*\*\d*\s+[\[{<].+")
SPACED_LETTERS_RE = re.compile(r"\b(?:[A-Za-z]\s+){2,}[A-Za-z]\b")
BOLD_FONT_RE = re.compile(r"bold", re.IGNORECASE)
AVP_NAME_RE = re.compile(r"[\{\[]\s*([A-Za-z][A-Za-z0-9-]*)\s*[\}\]]")


@dataclass(frozen=True)
class AbnfDefinition:
    """ABNF definition text with source description metadata."""

    description: str
    definition: str


def normalize_line(line: str) -> str:
    """Normalize basic whitespace and control characters from one PDF line."""
    line = line.replace("\u00a0", " ").replace("\uf0b7", " ")
    line = line.replace("\t", " ").rstrip().strip("\x00")
    return line


def normalize_tokens(line: str) -> str:
    """Normalize spacing artifacts around common ABNF token patterns."""
    line = re.sub(r"\s*-\s*", "-", line)
    line = re.sub(r"::=\s*<", "::= <", line)
    line = re.sub(r"\*\s+\[", "*[", line)
    line = SPACED_LETTERS_RE.sub(lambda m: m.group(0).replace(" ", ""), line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def normalize_section_heading(line: str) -> str:
    """Normalize a section heading and fix split words caused by PDF layout."""
    line = normalize_tokens(line)
    line = re.sub(r"(?<=-)([A-Za-z]{1,4})\s+([a-z]{2,})\b", r"\1\2", line)
    return line


def is_section_heading(line: str) -> bool:
    """Return True when the line looks like a numbered section heading."""
    stripped = line.strip()
    return bool(stripped) and len(stripped) < 180 and bool(SECTION_RE.match(stripped))


def is_layout_noise(line: str) -> bool:
    """Return True for recurring page header/footer lines from ETSI PDFs."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped == "ETSI":
        return True
    if stripped.startswith("ETSI TS ") and "3GPP TS" in stripped:
        return True
    if "3GPP TS" in stripped and "ETSI TS" in stripped:
        return True
    if re.fullmatch(r"\d{1,3}", stripped):
        return True
    return False


def is_continuation_line(line: str) -> bool:
    """Return True when a line can belong to the current ABNF block."""
    stripped = line.strip()
    if not stripped:
        return True
    if is_section_heading(stripped):
        return False
    if stripped.startswith(";"):
        return True
    if QUALIFIED_REP_RE.match(stripped):
        return True
    if RULE_LINE_RE.match(stripped):
        return True
    if stripped[0] in "[]{}<>*/=|":
        return True
    return False


def extract_avp_names(line: str) -> list[str]:
    """Extract AVP names referenced in [] or {} from one ABNF line."""
    return AVP_NAME_RE.findall(line)


def extract_page_lines_with_bold(page: object) -> list[tuple[str, bool]]:
    """Extract page lines and whether the line contains bold AVP text."""
    page_lines: list[tuple[str, bool]] = []
    current_parts: list[str] = []
    current_has_bold_avp = False

    def flush_current_line() -> None:
        nonlocal current_has_bold_avp
        if not current_parts:
            page_lines.append(("", False))
            return

        joined = normalize_line(" ".join(part for part in current_parts if part))
        page_lines.append((joined, current_has_bold_avp))
        current_parts.clear()
        current_has_bold_avp = False

    def visitor_text(
        text: str, cm: object, tm: object, font_dict: dict | None, font_size: float
    ) -> None:
        nonlocal current_has_bold_avp
        del cm, tm, font_size
        base_font = str((font_dict or {}).get("/BaseFont", ""))
        is_bold_font = bool(BOLD_FONT_RE.search(base_font))

        chunks = text.split("\n")
        for index, chunk in enumerate(chunks):
            normalized_chunk = normalize_line(chunk)
            if normalized_chunk:
                current_parts.append(normalized_chunk)
                if is_bold_font and extract_avp_names(normalize_tokens(normalized_chunk)):
                    current_has_bold_avp = True

            if index < len(chunks) - 1:
                flush_current_line()

    page.extract_text(visitor_text=visitor_text)
    if current_parts:
        flush_current_line()

    return page_lines


def format_block(lines: list[tuple[str, bool]]) -> list[str]:
    """Format an ABNF block with normalized lines and stable indentation."""
    formatted: list[str] = []
    for index, (raw, has_bold_avp) in enumerate(lines):
        if not raw.strip():
            continue

        normalized = normalize_tokens(raw)
        if has_bold_avp:
            normalized = f"{normalized} ; bold"

        if index == 0:
            formatted.append(normalized)
        else:
            formatted.append(f"    {normalized}")

    return formatted


def extract_abnf_blocks(pdf_path: Path) -> list[AbnfDefinition]:
    """Extract ABNF definitions and description text from a 3GPP PDF."""
    reader = PdfReader(str(pdf_path))

    stream: list[tuple[int, str, bool]] = []
    for page_index, page in enumerate(reader.pages, start=1):
        page_lines = extract_page_lines_with_bold(page)
        stream.extend(
            (page_index, normalize_line(line_text), has_bold_avp)
            for line_text, has_bold_avp in page_lines
        )

    blocks: list[AbnfDefinition] = []
    seen: set[tuple[str, ...]] = set()
    current_section = "Unknown section"

    i = 0
    while i < len(stream):
        page_index, line, _ = stream[i]
        if is_section_heading(line):
            current_section = normalize_section_heading(line)

        if not ABNF_START_RE.search(line):
            i += 1
            continue

        block_lines: list[tuple[str, bool]] = [(line.strip(), False)]
        i += 1

        while i < len(stream):
            _, candidate, candidate_has_bold_avp = stream[i]
            if not candidate.strip():
                block_lines.append(("", False))
                i += 1
                continue

            if is_layout_noise(candidate):
                i += 1
                continue

            if not is_continuation_line(candidate):
                break

            block_lines.append((candidate, candidate_has_bold_avp))
            i += 1

        formatted = format_block(block_lines)
        if not formatted:
            continue

        key = tuple(formatted)
        if key in seen:
            breakpoint()
            continue
        seen.add(key)

        blocks.append(
            AbnfDefinition(
                description=f"Section: {current_section}; Page: {page_index}",
                definition="\n".join(formatted),
            )
        )

    return blocks
