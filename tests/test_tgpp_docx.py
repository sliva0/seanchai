"""The 3GPP Word extractor: its public contract and the shapes it refuses.

Every shape a corpus document prints is pinned by `test_real_sources.py`,
which needs the downloads; without them the whole raw output of the
`synthetic_spec_docx` fixture is pinned in `fixtures/tgpp_docx/`. The other
cases are the ones no committed document reaches: each starts from the
fixture, changes one thing the way a real document went wrong, and requires
the extraction to fail or to say what it left out.
"""

import copy
import re
from pathlib import Path

import docx
import pypdf
import pytest
from conftest import _declare

from seanchai.dad import ast, formatter, parser
from seanchai.extractor import tgpp_docx
from seanchai.extractor.errors import ExtractionError

_EXPECTED_RAW = Path(__file__).parent / "fixtures" / "tgpp_docx" / "synthetic.raw.dad"


class _H(str):
    """A heading paragraph, `number<TAB>title`."""


def _quirks(*names: str) -> str:
    return "".join(f'[[quirk]]\nname = "{name}"\nreason = "x"\n' for name in names)


def _paragraph(document, text):
    return next(p for p in document.paragraphs if p.text == text)


def _table(document, rows):
    """A table of `rows`; a row of one cell spans it, a shorter one is padded."""
    width = max(map(len, rows))
    table = document.add_table(rows=len(rows), cols=width)
    for row, values in zip(table.rows, rows, strict=True):
        if len(values) == 1:
            row.cells[0].merge(row.cells[-1]).text = values[0]
            continue
        for cell, value in zip(row.cells, values, strict=False):
            cell.text = value
    return table


def _appending(*items):
    """An edit appending headings, paragraphs and tables (tuples of rows)."""

    def edit(document):
        for item in items:
            match item:
                case _H():
                    document.add_paragraph(style="Heading 1").add_run(item)
                case str():
                    document.add_paragraph(item)
                case _:
                    _table(document, item)

    return edit


def _cell(table, row, column, text):
    def edit(document):
        document.tables[table].cell(row, column).text = text

    return edit


def _retext(old, new):
    def edit(document):
        _paragraph(document, old).text = new

    return edit


def _after_body(*texts, style=None):
    """An edit printing `texts` after the fixture command's last member."""

    def edit(document):
        previous = _paragraph(document, "* [ Local-AVP ]")
        for text in texts:
            paragraph = document.add_paragraph(text, style=style)
            previous._p.addnext(paragraph._p)
            previous = paragraph

    return edit


def _enum_values(*texts):
    """An edit printing `texts` as Example-Mode's value lines."""

    def edit(document):
        value = _paragraph(document, "Disabled (0)")
        value.text = texts[0]
        for text in reversed(texts[1:]):
            value._p.addnext(document.add_paragraph(text)._p)

    return edit


def _both(*edits):
    def edit(document):
        for each in edits:
            each(document)

    return edit


def _extract(tmp_path, base, edit, toml="", warnings=None):
    """Extract the fixture `base` with `edit` applied, its sources directory
    declaring `toml`."""
    document = docx.Document(str(base))
    edit(document)
    path = tmp_path / "edited.docx"
    document.save(path)
    sources = _declare(tmp_path, toml, "TS29.999")
    return tgpp_docx.extract(path, sources_dir=sources, warnings=warnings)


# --- the public contract -------------------------------------------------------


def test_extract_writes_a_tree_the_formatter_and_parser_keep(synthetic_spec_docx):
    spec = tgpp_docx.extract(synthetic_spec_docx)
    text = formatter.format_spec(spec)

    assert tgpp_docx.extract_with_comments(synthetic_spec_docx)[0] == spec
    assert parser.parse(text) == spec
    assert formatter.format_spec(parser.parse(text)) == text


def _list_numbered_role(document):
    """Example-Role, whose values' numbers exist only as Word's list numbering:
    TS 32.299 V11.20.0 clause 7.2.151, PoC-User-Role-info-Units, which the PDF
    prints "1. Moderator". Added here, not to the fixture, since it reads only
    behind `list-numbered-enum-values`."""
    _add_avp_row(
        document, "Example-Role", "12", "6.3.3", "Enumerated", "M, V", "", "", "",
        "No",
    )  # fmt: skip
    following = _paragraph(document, "6.4\tResult-Code AVP values")
    for text, style in (
        ("6.3.3\tExample-Role AVP", "Heading 2"),
        ("The Example-Role AVP (AVP code 12) is of type Enumerated.", None),
        ("Moderator", "List Number"),
        ("Participant", "List Number"),
    ):
        following._p.addprevious(document.add_paragraph(text, style=style)._p)


def test_the_synthetic_document_still_produces_the_committed_output(
    tmp_path, synthetic_spec_docx
):
    """The whole raw output, so a reader dropping any construct the fixture
    holds fails here without the downloads. After a deliberate change, write
    the new output over the expected file and review the diff."""
    document = docx.Document(str(synthetic_spec_docx))
    _list_numbered_role(document)
    path = tmp_path / "synthetic.docx"
    document.save(path)
    sources = _declare(tmp_path, _quirks("list-numbered-enum-values"), "TS29.999")
    warnings: list[str] = []

    spec, comments = tgpp_docx.extract_with_comments(
        path,
        link="https://example.com/spec.pdf",
        warnings=warnings,
        sources_dir=sources,
    )

    assert formatter.format_spec(spec, comments) == _EXPECTED_RAW.read_text(
        encoding="utf-8"
    )
    assert warnings == []


def test_a_document_without_a_cover_or_an_avp_table_is_refused(tmp_path):
    blank = tmp_path / "blank.docx"
    docx.Document().save(blank)
    with pytest.raises(ExtractionError, match="cover page"):
        tgpp_docx.extract(blank)

    covered = tmp_path / "covered.docx"
    document = docx.Document()
    document.add_table(rows=1, cols=1).cell(0, 0).text = "3GPP TS 29.999 V1.0"
    document.save(covered)
    with pytest.raises(ExtractionError, match="no AVP table found"):
        tgpp_docx.extract(covered)
    # A document declared to define messages alone still needs some.
    sources = _declare(tmp_path, _quirks("message-only"), "TS29.999")
    with pytest.raises(ExtractionError, match="no AVP table found"):
        tgpp_docx.extract(covered, sources_dir=sources)


# --- attaching PDF pages ---------------------------------------------------------


def _two_sections(page=None):
    """Matches the `outlined_pdf` fixture's cover; only 6.3.1 is bookmarked."""
    return ast.Specification(
        specification="3GPP TS 29.999",
        version="1.2.3",
        vendor_id=10415,
        sections=(
            ast.GroupedAvp(
                name="One", source=ast.SourceRef(section="6.3.1"), code=1, avps=()
            ),
            ast.GroupedAvp(
                name="Two",
                source=ast.SourceRef(section="2", page=page),
                code=2,
                avps=(),
            ),
        ),
    )


def test_attach_pages_sets_the_pages_its_pdf_bookmarks_and_clears_the_rest(
    outlined_pdf,
):
    # A page surviving from an earlier rendering would claim a page the PDF the
    # file names does not put the section on.
    warnings = []

    attached = tgpp_docx.attach_pages(_two_sections(page=99), outlined_pdf, warnings)

    assert [s.source.page for s in attached.sections] == [4, None]
    assert warnings == ["bookmark outline covered 1/2 sections"]
    assert tgpp_docx.attach_pages(attached, outlined_pdf) == attached


@pytest.mark.parametrize(
    ("specification", "version", "expected"),
    [
        ("TS 29.998", "1.2.3", "PDF renders 3GPP TS 29.998 V1.2.3"),
        ("TS 29.999", "1.2.4", "PDF renders 3GPP TS 29.999 V1.2.4"),
    ],
    ids=["other-specification", "other-version"],
)
def test_attach_pages_refuses_a_pdf_of_another_document(
    make_outlined_pdf, specification, version, expected
):
    # A neighbouring version renders the same sections at other pages, which
    # nothing downstream could detect.
    pdf = make_outlined_pdf("other.pdf", specification=specification, version=version)

    with pytest.raises(ExtractionError, match=re.escape(expected)):
        tgpp_docx.attach_pages(_two_sections(), pdf)


def test_attach_pages_refuses_a_pdf_without_an_outline_or_a_cover(make_bare_pdf):
    bare = make_bare_pdf("bare.pdf", "3GPP TS 29.999 version 1.2.3 Release 18")
    with pytest.raises(ExtractionError, match="no numbered sections"):
        tgpp_docx.attach_pages(_two_sections(), bare)

    with pytest.raises(ExtractionError, match="PDF cover page"):
        tgpp_docx.attach_pages(_two_sections(), make_bare_pdf("blank.pdf"))


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("3GPP TS 29.999 version 1.2.3 Release 18", "no numbered sections"),
        ("3GPP TS 29.999 version 1.2.4 Release 18", "PDF renders 3GPP TS 29.999"),
    ],
    ids=["same-version", "other-version"],
)
def test_attach_pages_checks_the_document_title_when_the_cover_is_unreadable(
    make_bare_pdf, title, expected
):
    """ETSI TS 129 214 V11.16.0's cover text extracts interleaved; its document
    information Title names the rendering instead."""
    pdf = make_bare_pdf("title.pdf")
    writer = pypdf.PdfWriter(clone_from=pdf)
    writer.add_metadata({"/Title": f"TS 129 999 - V1.2.3 - Test ({title})"})
    with pdf.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(ExtractionError, match=re.escape(expected)):
        tgpp_docx.attach_pages(_two_sections(), pdf)


# --- shapes it refuses -----------------------------------------------------------


def _mixed_bold(document):
    # 3GPP files carry bold on a member's brackets but not its name; runs
    # disagreeing within the name have no honest reading.
    rule = _paragraph(document, "* [ Local-AVP ]")
    rule.runs[0].text = "* [ Local-"
    rule.add_run("AVP ]").bold = False


def _partly_struck(document):
    rule = _paragraph(document, "* [ Local-AVP ]")
    rule.runs[0].text = "* [ Local-"
    rule.add_run("AVP ]").font.strike = True


def _add_avp_row(document, *values):
    for cell, value in zip(document.tables[1].add_row().cells, values, strict=True):
        cell.text = value


def _note_defined_in_rfc(document):
    _add_avp_row(
        document, "Noted-AVP", "NOTE 1", "", "Unsigned32", "M", "", "", "V", "No"
    )
    note = document.tables[1].add_row()
    note.cells[0].merge(
        note.cells[8]
    ).text = "NOTE 1: The value of this attribute is defined in IETF RFC 6733"


def _wildcard_row(document):
    # TS 32.299 table 7.1.0.1 tabulates the `* [ AVP ]` member.
    _add_avp_row(document, "AVP", "*", "", "Grouped", "M", "", "", "", "No")


def _rows_removed(table, keep):
    """An edit leaving table `table` only its first `keep` rows."""

    def edit(document):
        for row in list(document.tables[table].rows)[keep:]:
            row._tr.getparent().remove(row._tr)

    return edit


def _second_vendor_group(document):
    """A grouped AVP whose header gives another vendor than Example-Group's,
    which leaves the enumerated AVPs, whose clauses print none, without one."""
    _add_avp_row(
        document, "Other-Group", "12", "6.3.3", "Grouped", "M, V", "", "", "", "No"
    )
    _appending(
        _H("6.3.3\tOther-Group AVP"),
        "Other-Group ::= < AVP Header: 12 13019 >",
        "{ Example-Mode }",
    )(document)


def _drop_mode_row(document):
    row = document.tables[1].rows[3]._tr
    row.getparent().remove(row)


def _second_avp_table(*, reused, code="10"):
    """A second set of AVP tables in clause 7.3, as TS 29.272 prints one per
    interface: the AVP table, and with `reused` its re-used table."""

    def edit(document):
        avp, reused_table = document.tables[1], document.tables[2]
        _appending(_H("7.3\tMore AVP Definitions"))(document)
        copies = [("Table 7.3.1: AVP definitions", avp)]
        if reused:
            copies.append(("Table 7.3.2: Re-used AVPs", reused_table))
        for caption, table in copies:
            document.add_paragraph(caption)._p.addnext(copy.deepcopy(table._tbl))
        document.tables[3].cell(2, 1).text = code

    return edit


_TABLE_MESSAGE = (
    _H("6.4.5\tExample-Answer Message"),
    "Table 6.4.5: Example-Answer (EXA) Message Contents",
)


def _message_table(mark):
    """TS 32.299 V11.20.0 clause 6.4.5's command printed as a table."""

    def edit(document):
        _appending(*_TABLE_MESSAGE)(document)
        table = _table(
            document,
            (
                ("", ""),
                ("AVP", "Used in 3GPP"),
                ("<Diameter Header: 321, PXY>", "yes"),
                ("<Session-Id>", "yes"),
                ("* [Proxy-Info]", mark),
            ),
        )
        table.cell(0, 0).merge(table.cell(0, 1)).text = "Example Application AVPs"

    return edit


def _category_table(*rows):
    """TS 32.299 V11.20.0 clause 6.4.4's command printed by category."""
    return _appending(
        _H("6.4.4\tSample-Request Message"),
        "Table 6.4.4 illustrates the structure.",
        "Table 6.4.4: Sample-Request (SMR) Message Contents",
        (("AVP", "Category", "Description"), *rows),
    )


# The header the category table leaves out, supplied as its document's patch does.
_HEADER_PATCH = (
    '[[patch]]\nfind = "Table 6.4.4 illustrates the structure."\n'
    'replace = "<Diameter Header: 321, REQ, PXY>"\nexact = true\nreason = "x"\n'
)


_PROCEDURE = (
    _H("7\tProcedures"),
    "The NAF shall send an Other-Request message (OTR) to the BSF.",
    "<Other-Request> ::= < Diameter Header: 322, REQ >",
    "< Session-Id >",
)
_REPRINT = (
    "<Vendor-Specific-Application-Id>::=<AVP header: 260>",
    "1* [Vendor-Id] ; 3GPP is 10415",
)


def _vendor_column_table(reference="[A.5.16]", vendor="45687"):
    """oneM2M TS-0004 table A.4-1, its document's only AVP table: vendor and
    Reference columns."""
    names = ("AVP Name", "AVP Vendor Id", "AVP Code")
    commands = ("ACR", "ACA", "CCR", "CCA")
    flags = ("Must", "May", "Should not", "Must not", "May Encr.")
    banner = ("AVP Flag rules",) * len(flags)
    row = ("Occupancy", vendor, "1012", "O", "-", "-", "-")

    def drop_the_fixtures_tables(document):
        for table in document.tables[1:]:
            table._tbl.getparent().remove(table._tbl)

    return _both(
        drop_the_fixtures_tables,
        _appending(
            _H("A.4\tSummary of AVPs used"),
            "Table A.4-1: Summary",
            (
                (*names, *["Used in"] * 4, "Reference", "Value Type", *banner),
                (*names, *commands, "Reference", "Value Type", *flags),
                (*row, reference, "Unsigned32", "M", "P", "-", "V", "Y"),
            ),
        ),
    )


def _vendor_table(reference):
    """TS 32.299 table 7.3.1: other vendors' AVPs, cited by reference number."""
    return _appending(
        _H("7.3\tAVPs of other vendors"),
        "Table 7.3.1: Other vendors' AVPs",
        (
            ("AVP Name", "AVP Code", *["Used in"] * 4, "Reference"),
            ("AVP Name", "AVP Code", "ACR", "ACA", "CCR", "CCA", "Reference"),
            ("3GPP2-BSID", "9010", "X", "-", "X", "-", reference),
        ),
    )


_REFERENCES = (
    _H("2\tReferences"),
    '[37] ETSI TS 283 034 v2.2.0: "Diameter protocol for the e4 interface".',
    '[15] ETSI TS 183 017: "Diameter protocol for session based policy".',
    # TS 32.299's [209], which numbers no document.
    '[301] OMA "Multimedia Messaging Service; Encapsulation Protocol".',
)


def _registry(*rows, header=("AVP Code", "Attribute Name", "Specified in the TS")):
    """TS 29.230 table 7.1's allocation table."""
    return _appending(
        _H("2\tReferences"),
        '[2] 3GPP TS 29.229: "Cx and Dx interfaces".',
        _H("7\tAllocated AVP codes"),
        "Table 7.1: AVP codes",
        (header, *rows),
    )


def _origin_sentences(*texts):
    """An edit printing `texts` in Example-Mode's clause."""

    def edit(document):
        intro = _paragraph(document, "The Example-Mode AVP is of type Enumerated.")
        for text in reversed(texts):
            intro._p.addnext(document.add_paragraph(text)._p)

    return edit


_REFUSED = [
    # The AVP table.
    pytest.param(
        _cell(1, 2, 0, "Example Group"),
        "",
        "'Example Group' contains spaces",
        id="space-in-table-name",
    ),
    pytest.param(
        _cell(1, 2, 2, "6. 3.1"), "", "clause cell '6. 3.1'", id="clause-cell"
    ),
    pytest.param(_cell(1, 2, 3, "Integer"), "", "'Integer'", id="type-cell"),
    pytest.param(
        _cell(1, 3, 4, "M. V"), "", "malformed flags cell 'M. V'", id="flags-cell"
    ),
    pytest.param(_cell(1, 3, 4, "M.V"), "", "`dotted-flags`", id="dotted-flags"),
    pytest.param(
        _cell(1, 2, 2, "6.3.1 (see Note)"),
        "",
        "`clause-parenthetical`",
        id="clause-parenthetical",
    ),
    pytest.param(
        _note_defined_in_rfc, "", "`note-defined-in-rfc`", id="note-defined-in-rfc"
    ),
    pytest.param(_wildcard_row, "", "`wildcard-avp-row`", id="wildcard-row"),
    pytest.param(
        _both(_rows_removed(1, 2), _wildcard_row),
        _quirks("wildcard-avp-row"),
        "6.3: AVP table 6.3.1 has no row naming an AVP",
        id="wildcard-row-alone",
    ),
    pytest.param(
        _retext("Table 6.3.1: AVP definitions", "Table  : definitions"),
        "",
        "AVP table without a caption",
        id="uncaptioned",
    ),
    pytest.param(
        _cell(2, 1, 0, "Session- Id"),
        "",
        "'Session- Id' contains spaces",
        id="space-in-reused-name",
    ),
    pytest.param(
        _cell(2, 1, 1, "some other document"),
        "",
        "unrecognized origin",
        id="unknown-origin",
    ),
    # TS 29.212 prints ETSI TS 283 034 as "3GPP TS 283 034 [37]".
    pytest.param(
        _cell(2, 1, 1, "3GPP\xa0TS 283 034\xa0[37]"),
        "",
        "`origins-by-reference`",
        id="etsi-series-undeclared",
    ),
    pytest.param(
        _both(_appending(*_REFERENCES), _cell(2, 1, 1, "3GPP TS 283 034 [15]")),
        _quirks("origins-by-reference"),
        r"\[15\], which names",
        id="etsi-series-wrong-entry",
    ),
    # Across the tables.
    pytest.param(
        _drop_mode_row, "", "has no code in the AVP table", id="enum-without-row"
    ),
    pytest.param(
        _second_vendor_group,
        "",
        "cannot resolve the vendor id",
        id="two-grouped-vendors",
    ),
    # Adjacency is all that pairs a re-used table with its AVP table.
    pytest.param(
        _second_avp_table(reused=False), "", "cannot pair", id="unpaired-tables"
    ),
    pytest.param(
        _second_avp_table(reused=True, code="12"),
        "",
        "code conflict",
        id="one-name-two-codes",
    ),
    # The rules.
    pytest.param(
        _retext(
            "Example-Group ::= < AVP Header: 10 10415 >",
            "Example Group ::= < AVP Header: 10 10415 >",
        ),
        "",
        "rule name 'Example Group' contains spaces",
        id="space-in-rule-name",
    ),
    pytest.param(_mixed_bold, "", "mixed bold", id="mixed-bold"),
    pytest.param(_partly_struck, "", "partly struck", id="partly-struck"),
    pytest.param(
        _after_body("…", "* [ AVP ]"), "", "`elided-members`", id="elided-undeclared"
    ),
    pytest.param(
        _appending(
            _H("6.2\tOther-Request (OTR) Command"), "<Group> ::= < AVP header: 260 >"
        ),
        "",
        "malformed rule header",
        id="grouped-rule-as-command",
    ),
    # Enumerated values.
    pytest.param(
        _enum_values("(0) Off; see clause 2"),
        _quirks("label-after-enum-value"),
        "is no value name",
        id="label-after-value",
    ),
    # TS 32.299 writes "0 PS to CS Transfer"; prose after the number is no label.
    pytest.param(
        _enum_values("3 Off; see clause 2"),
        _quirks("value-first-enums"),
        "is not a value name",
        id="label-before-value",
    ),
    pytest.param(
        _enum_values(
            "The possible values are those defined in TS 32.422 [23] for Trace Depth.",
            "The values are taken from OMNA WSP Content Type Numbers [210].",
        ),
        _quirks("external-enum-values"),
        "names 2 sources",
        id="two-value-sources",
    ),
    # Commands printed as tables, behind `message-tables`.
    pytest.param(
        _message_table("maybe"),
        _quirks("message-tables"),
        "neither yes nor no",
        id="table-mark",
    ),
    pytest.param(
        _category_table(("Session-Id", "M")),
        _quirks("message-tables"),
        "no Diameter header",
        id="category-without-header",
    ),
    pytest.param(
        _category_table(("Odd", "X")),
        _quirks("message-tables") + _HEADER_PATCH,
        "category 'X'",
        id="category-unknown",
    ),
    pytest.param(
        _appending(*_TABLE_MESSAGE, (("", ""),)),
        _quirks("message-tables"),
        "over no table",
        id="caption-over-no-table",
    ),
    pytest.param(
        _appending(
            _H("6.5\tOther-Request (OTR) Command"),
            "Refer to clause 1.2.3.",
            "Additional definition text.",
        ),
        _quirks("command-reference-only"),
        "command section without ABNF",
        id="reference-only-with-more",
    ),
    # Commands printed in procedure clauses (TS 29.234 clause 4.4.2.2).
    pytest.param(
        _appending(
            _H("7\tProcedures"),
            "<ASR> ::= < Diameter Header: 274, REQ, PXY >",
            "< Session-Id >",
        ),
        _quirks("procedure-commands"),
        "without a named intro",
        id="procedure-command-unnamed",
    ),
    pytest.param(
        _appending(
            _H("7\tProcedures"),
            "<XYZ> ::= < Diameter Header: 999, REQ, PXY >",
            "< Session-Id >",
        ),
        _quirks("procedure-commands", "rfc-command-rules"),
        "none of the RFC commands",
        id="procedure-command-unknown",
    ),
    # TS 29.109 clause 5.2 re-prints a grouped rule from RFC 6733.
    pytest.param(
        _appending(
            *_PROCEDURE,
            "The content of Vendor-Specific-Application-ID according"
            " IETF RFC 6733 [33] is:",
            *_REPRINT,
        ),
        _quirks("procedure-commands", "abnf-comments"),
        "`reprinted-avps` quirk",
        id="reprint-undeclared",
    ),
    pytest.param(
        _appending(*_PROCEDURE, "Then:", *_REPRINT),
        _quirks("procedure-commands", "abnf-comments", "reprinted-avps"),
        "saying what it copies",
        id="reprint-without-origin",
    ),
    # Other tables, behind their quirks.
    pytest.param(
        _vendor_column_table(reference="see A.5.1"),
        _quirks("reference-cells", "command-columns"),
        "'see A.5.1', which names neither",
        id="reference-cell",
    ),
    pytest.param(
        _vendor_column_table(reference="[see A.5.1]"),
        _quirks("reference-cells", "command-columns"),
        "bracket holds no clause number",
        id="reference-bracket",
    ),
    pytest.param(
        _vendor_column_table(vendor="oneM2M"),
        _quirks("reference-cells", "command-columns"),
        "vendor cell 'oneM2M'",
        id="vendor-cell",
    ),
    pytest.param(
        _vendor_table("TS 29.212"),
        _quirks("vendor-avp-tables"),
        "no reference number",
        id="vendor-table-reference",
    ),
    pytest.param(
        _registry(("1", "A", "29.229")),
        _quirks("registry-tables"),
        r"unrecognized document cell '29\.229'",
        id="registry-document",
    ),
    pytest.param(
        _registry(("1", "A", "29.229 [2]"), header=("AVP Code", "Owner")),
        _quirks("registry-tables"),
        "unrecognized registry column 'Owner'",
        id="registry-column",
    ),
    pytest.param(
        _registry(("Note: The AVP codes from 1 to 9 are reserved for x",)),
        _quirks("registry-tables"),
        "`reserved-range-notes`",
        id="registry-note",
    ),
    pytest.param(
        _registry(
            ("314", "Charging-Characteristics", "Integer"),
            header=("AVP Code", "Attribute Name", "Data Type"),
        ),
        _quirks("registry-tables"),
        "'Integer' names no Diameter type",
        id="registry-type",
    ),
    pytest.param(
        _registry(("zz", "A", "29.229 [2]")),
        _quirks("registry-tables"),
        "code cell 'zz'",
        id="registry-placeholder",
    ),
    pytest.param(
        # Table 7.1's row naming a document alone, ahead of its range.
        _registry(("", "", "29.229 [2]")),
        _quirks("registry-tables"),
        "registry table 7.1 allocates no code and reserves no range",
        id="registry-without-codes",
    ),
    # TS 29.210 V6.7.0 states Gx's id in clause 6.1 and Gx over Gy's in 6.2; an
    # id stated at the interface clause itself could be for either's commands.
    pytest.param(
        _appending(
            _H("8\tGx"),
            "The Auth-Application-Id for the Gx Application is 16777224 as allocated"
            " by IANA.",
            _H("8.2\tGx over Gy"),
            "The Auth-Application-Id for the Gx over Gy Application is 16777225 as"
            " allocated by IANA.",
        ),
        _quirks("prose-application-ids"),
        "ambiguous",
        id="sibling-applications",
    ),
    # Where a definition is.
    # Both rows cite clause 6.3.2, so "this AVP" could be either.
    pytest.param(
        _both(
            _cell(1, 2, 2, "6.3.2"),
            _origin_sentences("This AVP is defined in TS 29.229 [6]."),
        ),
        _quirks("prose-avp-origins"),
        "could be Example-Group or Example-Mode",
        id="unnamed-citation",
    ),
    pytest.param(
        _origin_sentences(
            "The Example-Mode AVP is defined in TS 29.229 [6].",
            "This AVP is defined in TS 29.329 [7].",
        ),
        _quirks("prose-avp-origins"),
        "conflicting prose origins",
        id="conflicting-origins",
    ),
    pytest.param(
        _appending(
            _H("7.4\tExperimental-Result-Code AVP values"),
            "the following Experimental-Result-Code value defined in 3GPP TS 29.212 [3]"
            " is applicable:",
            "DIAMETER_PENDING_TRANSACTION (4144)",
            "This value is defined in TS 29.229 [6]",
        ),
        "",
        r"TS29\.212 and in TS29\.229",
        id="result-code-two-origins",
    ),
    pytest.param(
        _appending(
            _H("7.4\tExperimental-Result-Code AVP values"),
            _H("7.4.1\tDIAMETER_LOCAL (5002)"),
            "This value is defined in TS 29.999 [7].",
            "This value is defined in TS 29.229 [6].",
        ),
        "",
        r"TS29\.999 and in TS29\.229",
        id="result-code-defined-twice",
    ),
]


@pytest.mark.parametrize(("edit", "toml", "message"), _REFUSED)
def test_a_shape_it_cannot_read_faithfully_is_refused(
    tmp_path, synthetic_spec_docx, edit, toml, message
):
    with pytest.raises(ExtractionError, match=message):
        _extract(tmp_path, synthetic_spec_docx, edit, toml)


@pytest.mark.parametrize(
    "line",
    [
        # Each ended a real body, taking the members after it along: TS 29.128
        # clause 6.2.5, 29.172 7.3.3, 29.212 5.3.36, 29.272 7.3.35, 29.283
        # 7.2.4, 29.344 6.2.5 and 29.345 6.3.32 and 6.3.68.
        "**[ Proxy-Info ]",
        "[ 1xRTT-RCID ] ]",
        "2 [ Tunnel-Header-Filter ]",
        "[ IDR- Flags ]",
        "DRMP ]",
        "*AVP",
        "[ Ending\u2013Suffix ]",
    ],
)
def test_a_line_inside_a_body_that_is_no_member_fails(
    tmp_path, synthetic_spec_docx, line
):
    with pytest.raises(
        ExtractionError, match=rf"6\.1: line {re.escape(repr(line))} inside"
    ):
        _extract(tmp_path, synthetic_spec_docx, _after_body(line, "[ Later ]"))


def test_a_broken_member_fails_though_its_paragraph_style_changes(
    tmp_path, synthetic_spec_docx
):
    # TS 29.345 clause 6.3.54 changes style inside its body, at a broken line.
    edit = _after_body("[ ProSe-Validity Timer ]", "[ Later ]", style="Body Text")
    with pytest.raises(ExtractionError, match="ProSe-Validity Timer"):
        _extract(tmp_path, synthetic_spec_docx, edit)


@pytest.mark.parametrize(
    "lines",
    [
        ("NOTE: A note wedged in the rule.", "[ Later ]"),
        ("A sentence before an elided line.", "…"),
    ],
)
def test_a_member_printed_after_the_body_ended_fails(
    tmp_path, synthetic_spec_docx, lines
):
    with pytest.raises(ExtractionError, match="follows the end of Example-Request"):
        _extract(tmp_path, synthetic_spec_docx, _after_body(*lines))


def test_a_struck_member_without_a_legend_is_kept_and_warned_about(
    tmp_path, synthetic_spec_docx
):
    def strike(document):
        _paragraph(document, "* [ Local-AVP ]").runs[0].font.strike = True

    warnings: list[str] = []
    spec = _extract(tmp_path, synthetic_spec_docx, strike, warnings=warnings)

    message = next(s for s in spec.sections if isinstance(s, ast.Message))
    assert [(r.name, r.strikethrough) for r in message.avps][-1] == ("Local-AVP", True)
    assert any("member Local-AVP is struck through" in w for w in warnings)


@pytest.mark.parametrize(
    ("text", "declared", "read"),
    [
        ("OFF (0x0)", "", None),
        ("OFF (0) The mode is off", "", None),
        ("OFF (0),", "", None),
        ("[2] unknown", "", None),
        ("0. SUBMISSION", "", None),
        (
            "The following value is currently defined for the Example-Mode AVP:"
            " EVENT_RECORD (value 1) for an Event Based request.",
            "",
            None,
        ),
        # Every departure needs its own declaration: the one declared reads
        # its own line and no other.
        ("- Fully Off (0)", "dashed-enum-values", "- On (1)"),
        (
            "MM1 Message Submission, Profile based (0)",
            "worded-enum-values",
            "Fully On (1)",
        ),
        # TS 32.299 V11.20.0 prints "MONETARY<tabs>0"; without the tab the line
        # is a sentence ending in a number.
        ("MONETARY 0", "value-last-enums", "NON_MONETARY\t1"),
    ],
)
def test_a_value_line_in_an_undeclared_shape_is_not_read(
    tmp_path, synthetic_spec_docx, text, declared, read
):
    warnings: list[str] = []
    toml = _quirks(declared) if declared else ""
    lines = (text,) if read is None else (read, text)

    spec = _extract(tmp_path, synthetic_spec_docx, _enum_values(*lines), toml, warnings)

    mode = next(s for s in spec.sections if isinstance(s, ast.EnumeratedAvp))
    assert [
        value.value if isinstance(value, ast.EnumValue) else value
        for value in mode.values
    ] == ([] if read is None else [1])
    if read is None:
        assert "6.3.2: enumerated AVP Example-Mode lists no values" in warnings


def test_a_value_range_its_words_give_no_one_is_not_recorded(
    tmp_path, synthetic_spec_docx
):
    # TS 32.299 clause 7.2.213 prints ranges value first; a negation takes this
    # one away from vendors.
    edit = _enum_values("0 Off", "100 .. 199 Not for vendor-specific services")
    warnings: list[str] = []

    spec = _extract(
        tmp_path, synthetic_spec_docx, edit, _quirks("value-first-enums"), warnings
    )

    mode = next(s for s in spec.sections if isinstance(s, ast.EnumeratedAvp))
    assert mode.values == (ast.EnumValue(name="Off", value=0),)
    assert any("value range 100..199" in w and "not recorded" in w for w in warnings)


def test_a_vendor_table_row_citing_no_nameable_document_adds_no_row(
    tmp_path, synthetic_spec_docx
):
    edit = _both(_appending(*_REFERENCES), _vendor_table("[301]"))
    warnings: list[str] = []

    spec = _extract(
        tmp_path, synthetic_spec_docx, edit, _quirks("vendor-avp-tables"), warnings
    )

    assert not any(
        row.name == "3GPP2-BSID"
        for section in spec.sections
        if isinstance(section, ast.ReusedAvps)
        for row in section.rows
    )
    assert any("[301], which names no document" in w for w in warnings)


@pytest.mark.parametrize("toml", ["", _quirks("independent-avp-tables")])
def test_a_reused_table_with_no_rows_makes_no_block(
    tmp_path, synthetic_spec_docx, toml
):
    """Paired with the AVP table or, behind `independent-avp-tables`, not."""
    spec = _extract(tmp_path, synthetic_spec_docx, _rows_removed(2, 1), toml)

    assert not any(isinstance(section, ast.ReusedAvps) for section in spec.sections)


# --- declarations ------------------------------------------------------------------


_EXCLUSION = """
[[exclude]]
section = "8"
name = "Sh-ee"
reason = "the document leaves its application id to be allocated"
"""


def _unfinished_clause(document):
    """TS 29.329 V19.1.0's clause 8, which no reading could take."""
    _appending(
        _H("8\tSh-ee"),
        "The application id is xx1 (allocated by IANA).",
        _H("8.1\tGone-Request (GR) Command"),
        "< Gone-Request > ::= < Diameter Header: 310, REQ, xx1 >",
    )(document)


def test_a_patch_inside_an_excluded_clause_applies_nowhere(
    tmp_path, synthetic_spec_docx
):
    patch = (
        '[[patch]]\nfind = "xx1"\nreplace = "1"\ncount = 2\nsection = "8"\n'
        'reason = "a patch written for the clause goes with it"\n'
    )
    with pytest.raises(ExtractionError, match="applied 0 times"):
        _extract(tmp_path, synthetic_spec_docx, _unfinished_clause, _EXCLUSION + patch)


def test_an_exclusion_of_no_such_clause_fails(tmp_path, synthetic_spec_docx):
    with pytest.raises(ExtractionError, match="left nothing out"):
        _extract(tmp_path, synthetic_spec_docx, lambda document: None, _EXCLUSION)
