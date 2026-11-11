"""The entry points: `extract` and `extract_with_comments` run the
stages over a docx, and `attach_pages` adds page numbers from the ETSI PDF's
bookmark outline."""

from __future__ import annotations

import re
from pathlib import Path

import pydantic

from ...dad import ast, formatter
from ...errors import MissingExtraError
from .. import sources
from ..errors import ExtractionError, boundary
from ._base import (
    _Commented,
    _Glosses,
    _normalize,
    _publisher_vendor,
    _ValueNotes,
)
from ._collect import _assemble, _collect, _resolve
from ._docx import _sections, _spec_and_version, _unwrap_smart_tags
from ._quirks import QUIRKS
from ._values import _value_tables

try:
    import docx
    import pypdf
except ImportError as error:
    raise MissingExtraError(
        "reading source documents needs python-docx and pypdf"
    ) from error


_PDF_COVER_RE = re.compile(
    r"3GPP (?P<spec>TS \d{2}\.\d{3}) version (?P<version>\d+(?:\.\d+)*)"
)


def _pdf_spec_and_version(reader: pypdf.PdfReader) -> tuple[str, str]:
    """An ETSI rendering prints its own title on the cover, with the 3GPP
    original in parentheses: "(3GPP TS 29.272 version 18.6.0 Release 18)".

    Failing the cover, the document information Title ETSI writes with the
    same parenthesis: TS 129 214 V11.16.0 (2015-10) draws its cover title as
    overlapping text runs pypdf reads interleaved, "(3GPP TS 29.21" and
    ".214 version 11.16.0 Release 1", where its Title reads "... (3GPP TS
    29.214 version 11.16.0 Release 11)". Either names the rendering, so a
    neighbouring version is refused all the same."""
    if not reader.pages:
        raise ExtractionError("PDF has no pages")
    cover = _normalize(reader.pages[0].extract_text())
    match = _PDF_COVER_RE.search(cover)
    if match is None and reader.metadata is not None and reader.metadata.title:
        match = _PDF_COVER_RE.search(_normalize(reader.metadata.title))
    if match is None:
        raise ExtractionError("cannot find spec number/version on the PDF cover page")
    return f"3GPP {match['spec']}", match["version"]


def sources_file_name(specification: str) -> str:
    """Source-declaration file name for a cover-page spec title:
    "3GPP TS 29.272" → "TS29.272.toml"."""
    return f"{ast.spec_ref(specification)}.toml"


def extract(
    docx_path: Path | str,
    link: str | None = None,
    warnings: list[str] | None = None,
    sources_dir: Path | None = None,
) -> ast.Specification:
    """Extract a `Specification` from a 3GPP docx. Non-fatal source-document
    inconsistencies are appended to `warnings` when a list is given. When
    `sources_dir` is given, source declarations from
    `<sources_dir>/<SpecRef>.toml` (if present) apply: input patches to the
    normalized source text before parsing, and quirks to the readings the
    extractor uses.

    Lines commented out behind `struck-rules-unused` and `elided-members` are
    not in the tree; `extract_with_comments` returns them too."""
    return extract_with_comments(docx_path, link, warnings, sources_dir)[0]


def extract_with_comments(
    docx_path: Path | str,
    link: str | None = None,
    warnings: list[str] | None = None,
    sources_dir: Path | None = None,
) -> tuple[ast.Specification, formatter.Comments]:
    """`extract`, plus the `;;` lines the file prints beside the tree, as the
    `formatter.Comments` `format_spec` takes: each line commented out behind
    `struck-rules-unused` or `elided-members`, standing before the member that
    followed it, or at its body's end."""
    warnings = warnings if warnings is not None else []
    with boundary(f"extracting {docx_path}"):
        document = docx.Document(str(docx_path))
        _unwrap_smart_tags(document)
        specification, version = _spec_and_version(document)
        declarations_path = (
            sources_dir / sources_file_name(specification)
            if sources_dir is not None
            else None
        )
        patcher, quirks = sources.load(declarations_path, version, QUIRKS, warnings)

        read = _sections(document, patcher, quirks)
        collected = _collect(
            read,
            warnings,
            ast.spec_ref(specification),
            quirks,
            _publisher_vendor(specification),
        )
        value_tables, value_notes = _value_tables(
            read, warnings, quirks, ast.spec_ref(specification)
        )
        patcher.finish()
        sections = _assemble(
            _resolve(collected, quirks, warnings),
            collected.reprints,
            value_tables,
            collected.answers,
        )
        quirks.finish()
        spec = ast.Specification(
            specification=specification,
            version=version,
            vendor_id=_publisher_vendor(specification),
            bases=(ast.BASE_PROTOCOL,),
            link=None if link is None else pydantic.HttpUrl(link),
            sections=sections,
        )
        return spec, _comments(
            sections,
            collected.commented,
            collected.glosses,
            [*value_notes, *collected.table_notes],
            []
            if declarations_path is None
            else patcher.exclusion_notes(declarations_path.name),
        )


def _comments(
    sections: tuple[ast.Section, ...],
    commented: _Commented,
    glosses: _Glosses,
    value_notes: _ValueNotes | None = None,
    excluded: list[str] | None = None,
) -> formatter.Comments:
    """The commented-out lines, keyed by the path of what follows each:
    the member after it in its body, or the body's end, and each gloss on its
    member. A body is found by identity, since it is the very object the file
    holds. A value table's notes stand among its rows the same way. What the
    file leaves out is a block of its own after the header."""

    def position_of(
        body: ast.Message
        | ast.GroupedAvp
        | ast.ReprintedAvp
        | ast.ValueTable
        | ast.AvpTable,
    ) -> int:
        for index, section in enumerate(sections):
            if section is body:
                return index
        raise ExtractionError(
            f"{getattr(body, 'name', body.type)}: the body its comments belong to"
            " is not in the file"
        )

    standing: dict[ast.TreePath, list[str]] = {}
    for body, notes in commented:
        index = position_of(body)
        for position, note in notes:
            standing.setdefault(("sections", index, "avps", position), []).append(note)
    for table, notes in value_notes or ():
        for position, note in notes:
            standing.setdefault(
                ("sections", position_of(table), "rows", position), []
            ).append(note)
    trailing: dict[ast.TreePath, list[str]] = {
        ("sections", position_of(body), "avps", position): [gloss]
        for body, position, gloss in glosses
    }
    return formatter.Comments(
        standing=standing,
        trailing=trailing,
        detached={("sections", 0): excluded} if excluded else {},
    )


def attach_pages(
    spec: ast.Specification,
    pdf_path: Path | str,
    warnings: list[str] | None = None,
) -> ast.Specification:
    """Attach PDF page numbers to every section, from the ETSI PDF bookmark
    outline (section number → 1-based page of the first outline entry that
    starts with it).

    The PDF must render the same specification and version as `spec`, since
    the downloader may fetch an earlier ETSI rendering when the exact one is
    not published, and its page numbers would be silently wrong.
    """
    warnings = warnings if warnings is not None else []
    with boundary(f"attaching pages from {pdf_path}"):
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
                match = re.match(r"^(\d+[A-Za-z]*(?:\.\d+[A-Za-z]*)*)\s", entry.title)
                if match is None:
                    continue
                # pypdf types `get_page_number` as optional; it resolves for a real
                # outline.
                destination = entry.page or reader.pages[0]
                number = reader.get_page_number(destination)
                if number is not None:
                    # `setdefault`, not assignment: a section number bookmarked
                    # twice (a "6.3.1" continued after a page break) should keep
                    # the first entry, as documented, not the last.
                    pages.setdefault(match.group(1), number + 1)

        walk(reader.outline)
        if not pages:
            raise ExtractionError(
                "PDF bookmark outline has no numbered sections — wrong file, or a"
                " rendering without an outline"
            )

        def with_page(section):
            # Unconditionally, including when this PDF has no bookmark for the
            # section: returning it untouched would leave a page number from an
            # earlier `attach_pages` call in place, and the file would then
            # assert a page that the PDF it names does not put the section on.
            # That is the same wrong-rendering failure the version check above
            # exists to prevent, arriving through a second call instead of a
            # mismatched file.
            return section.model_copy(
                update={
                    "source": ast.SourceRef(
                        section=section.source.section,
                        page=pages.get(section.source.section),
                    )
                }
            )

        attached = tuple(with_page(section) for section in spec.sections)
        covered = sum(1 for section in attached if section.source.page is not None)
        if covered < len(attached):
            # Not fatal on its own — some sections legitimately have no bookmark —
            # but a low count means the outline and the docx disagree about section
            # numbering, which is worth seeing before the file gets committed.
            warnings.append(
                f"bookmark outline covered {covered}/{len(attached)} sections"
            )
        return spec.model_copy(update={"sections": attached})
