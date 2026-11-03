import re
from pathlib import Path

import docx
import docx.text.paragraph
import pypdf
import pytest
from conftest import _CORPUS_DIR
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from seanchai.dad import ast, formatter, parser
from seanchai.extractor import tgpp_docx


def _two_section_spec():
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
                name="Two", source=ast.SourceRef(section="2"), code=2, avps=()
            ),
        ),
    )


def test_extract_builds_all_supported_sections_from_a_docx(synthetic_spec_docx):
    spec = tgpp_docx.extract(synthetic_spec_docx)
    text = formatter.format_spec(spec)
    assert parser.parse(text) == spec
    assert formatter.format_spec(parser.parse(text)) == text


def test_extract_requires_cover_metadata_and_an_avp_table(tmp_path):
    missing_cover = tmp_path / "missing-cover.docx"
    docx.Document().save(missing_cover)

    with pytest.raises(tgpp_docx.ExtractionError, match="cover page"):
        tgpp_docx.extract(missing_cover)

    no_table = tmp_path / "no-table.docx"
    document = docx.Document()
    document.add_table(rows=1, cols=1).cell(0, 0).text = "3GPP TS 29.999 V1.0"
    document.save(no_table)

    with pytest.raises(tgpp_docx.ExtractionError, match="no AVP table found"):
        tgpp_docx.extract(no_table)


def test_origin_rejects_unknown_references():
    with pytest.raises(tgpp_docx.ExtractionError, match="unrecognized origin"):
        tgpp_docx._origin("some other document", "TS29.999")


@pytest.mark.parametrize("cell", ["M. V", "M, v", "v", "M.V"])
def test_flags_cell_rejects_known_source_typos(tmp_path, synthetic_spec_docx, cell):
    malformed = tmp_path / "flags.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[1].cell(3, 4).text = cell
    document.save(malformed)
    message = "dotted-flags" if cell == "M.V" else f"malformed flags cell {cell!r}"
    with pytest.raises(tgpp_docx.ExtractionError, match=re.escape(message)):
        tgpp_docx.extract(malformed, sources_dir=tmp_path)


def test_extract_rejects_spaces_in_avp_table_names(tmp_path, synthetic_spec_docx):
    malformed = tmp_path / "space-in-table-name.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[1].cell(2, 0).text = "Example Group"
    document.save(malformed)

    with pytest.raises(
        tgpp_docx.ExtractionError,
        match="AVP table name cell 'Example Group' contains spaces",
    ):
        tgpp_docx.extract(malformed)


def test_extract_rejects_an_avp_table_clause_cell_that_is_no_clause_number(
    tmp_path, synthetic_spec_docx
):
    malformed = tmp_path / "clause-cell.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[1].cell(2, 2).text = "6. 3.1"
    document.save(malformed)

    with pytest.raises(
        tgpp_docx.ExtractionError,
        match=re.escape(
            "6.3: AVP table row 'Example-Group' has clause cell '6. 3.1',"
            " which is not a clause number"
        ),
    ):
        tgpp_docx.extract(malformed)


def test_extract_rejects_spaces_in_reused_avp_names(tmp_path, synthetic_spec_docx):
    malformed = tmp_path / "space-in-reused-name.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[2].cell(1, 0).text = "Session- Id"
    document.save(malformed)

    with pytest.raises(
        tgpp_docx.ExtractionError,
        match="re-used AVPs name cell 'Session- Id' contains spaces",
    ):
        tgpp_docx.extract(malformed)


def test_extract_rejects_spaces_in_grouped_avp_rule_names(
    tmp_path, synthetic_spec_docx
):
    malformed = tmp_path / "space-in-rule-name.docx"
    document = docx.Document(synthetic_spec_docx)
    for paragraph in document.paragraphs:
        if paragraph.text.startswith("Example-Group ::="):
            paragraph.text = paragraph.text.replace("Example-Group", "Example Group")
            break
    document.save(malformed)

    with pytest.raises(
        tgpp_docx.ExtractionError,
        match=re.escape("6.3.1: rule name 'Example Group' contains spaces"),
    ):
        tgpp_docx.extract(malformed)


def test_attach_pages_reads_real_nested_pdf_outline_and_preserves_missing_sections(
    outlined_pdf,
):
    spec = _two_section_spec()
    warnings = []

    attached = tgpp_docx.attach_pages(spec, outlined_pdf, warnings=warnings)

    assert attached.sections[0].source.page == 4
    assert attached.sections[1].source.page is None
    assert spec.sections[0].source.page is None
    assert warnings == ["bookmark outline covered 1/2 sections"]


def test_attach_pages_clears_a_page_this_pdf_does_not_bookmark(outlined_pdf):
    # Attaching twice must leave the pages this PDF asserts and nothing else. A
    # section whose page survived from an earlier call would make the file
    # claim a page that the PDF it names does not put the section on — the same
    # wrong-rendering failure the version check rejects, through another door.
    stale = ast.Specification(
        specification="3GPP TS 29.999",
        version="1.2.3",
        vendor_id=10415,
        sections=(
            ast.GroupedAvp(
                name="Two",
                source=ast.SourceRef(section="2", page=99),
                code=2,
                avps=(),
            ),
        ),
    )

    attached = tgpp_docx.attach_pages(stale, outlined_pdf)

    assert attached.sections[0].source.page is None
    assert tgpp_docx.attach_pages(attached, outlined_pdf) == attached


@pytest.mark.parametrize(
    ("specification", "version", "expected"),
    [
        ("TS 29.998", "1.2.3", "PDF renders 3GPP TS 29.998 V1.2.3"),
        ("TS 29.999", "1.2.4", "PDF renders 3GPP TS 29.999 V1.2.4"),
    ],
    ids=["wrong-spec-right-version", "right-spec-wrong-version"],
)
def test_attach_pages_rejects_a_pdf_of_another_document(
    make_outlined_pdf, specification, version, expected
):
    # A neighbouring version renders the same sections at different pages, so
    # the result would be wrong in a way nothing downstream can detect.
    pdf = make_outlined_pdf("other.pdf", specification=specification, version=version)

    with pytest.raises(tgpp_docx.ExtractionError, match=re.escape(expected)):
        tgpp_docx.attach_pages(_two_section_spec(), pdf)


def test_attach_pages_rejects_a_pdf_without_a_usable_outline(make_bare_pdf):
    pdf = make_bare_pdf("no-outline.pdf", "3GPP TS 29.999 version 1.2.3 Release 18")

    with pytest.raises(tgpp_docx.ExtractionError, match="no numbered sections"):
        tgpp_docx.attach_pages(_two_section_spec(), pdf)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("3GPP TS 29.999 version 1.2.3 Release 18", "no numbered sections"),
        ("3GPP TS 29.999 version 1.2.4 Release 18", "PDF renders 3GPP TS 29.999"),
    ],
    ids=["same-version", "other-version"],
)
def test_attach_pages_reads_the_document_title_when_the_cover_is_unreadable(
    make_bare_pdf, title, expected
):
    """ETSI TS 129 214 V11.16.0's cover text extracts interleaved; its
    document information Title names the rendering instead, and is checked
    against the specification as the cover would be."""
    pdf = make_bare_pdf("title.pdf")
    writer = pypdf.PdfWriter(clone_from=pdf)
    writer.add_metadata({"/Title": f"TS 129 999 - V1.2.3 - Test ({title})"})
    with pdf.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(tgpp_docx.ExtractionError, match=re.escape(expected)):
        tgpp_docx.attach_pages(_two_section_spec(), pdf)


def test_attach_pages_rejects_a_pdf_without_cover_metadata(make_bare_pdf):
    with pytest.raises(tgpp_docx.ExtractionError, match="PDF cover page"):
        tgpp_docx.attach_pages(_two_section_spec(), make_bare_pdf("blank.pdf"))


def _avp_table_docx(tmp_path, labels, rows):
    """A minimal spec whose only content is an AVP table with `labels`."""
    document = docx.Document()
    cover = document.add_table(rows=1, cols=1)
    cover.cell(0, 0).text = "3GPP TS 29.999 V1.2.3"
    heading = document.add_paragraph(style="Heading 1")
    heading.add_run("6.3\tAVP Definitions")
    document.add_paragraph("Table 6.3.1: AVP definitions")
    table = document.add_table(rows=2, cols=len(labels))
    # The dispatch keys on this merged banner, as the real tables do.
    table.cell(0, 0).merge(table.cell(0, len(labels) - 1)).text = "AVP Flag rules"
    for cell, label in zip(table.rows[1].cells, labels, strict=True):
        cell.text = label
    for values in rows:
        for cell, value in zip(table.add_row().cells, values, strict=True):
            cell.text = value
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "table.docx"
    document.save(path)
    return path


def test_extract_distinguishes_an_absent_encrypt_column_from_an_empty_cell(tmp_path):
    """TS 29.273's AVP table has no Encrypt column at all, while TS 29.389's
    has one with an empty cell. Both used to be `False`."""
    labels = ["Attribute Name", "AVP Code", "Value Type"]
    absent = tgpp_docx.extract(
        _avp_table_docx(tmp_path / "a", labels, [["Local-AVP", "10", "Unsigned32"]]),
        warnings=[],
    )
    empty = tgpp_docx.extract(
        _avp_table_docx(
            tmp_path / "b",
            [*labels, "May Encr."],
            [["Local-AVP", "10", "Unsigned32", ""]],
        ),
        warnings=[],
    )

    absent_table, empty_table = (spec.sections[0] for spec in (absent, empty))
    assert isinstance(absent_table, ast.AvpTable)
    assert isinstance(empty_table, ast.AvpTable)
    assert absent_table.rows[0].may_encrypt is None
    assert empty_table.rows[0].may_encrypt is None
    assert ast.AvpColumn.ENCRYPT not in absent_table.columns
    assert ast.AvpColumn.ENCRYPT in empty_table.columns


# Resolve rejects.


def _avp_table(*rows, section="6.3", table="6.3.1", note_reused=()):
    return tgpp_docx._CollectedAvpTable(
        table=ast.AvpTable(
            table=table,
            columns=tuple(ast.AvpColumn),
            source=ast.SourceRef(section=section),
            rows=tuple(rows),
        ),
        section=section,
        note_reused=list(note_reused),
    )


def _reused_table(*rows, label="6.3.2", section="6.3"):
    return tgpp_docx._ReusedTable(
        rows=list(rows),
        columns=ast.REUSED_COLUMNS,
        label=label,
        section=section,
    )


def _grouped(vendor_id=10415, name="Group"):
    return ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section="6.3.1"),
        code=10,
        vendor_id=vendor_id,
        avps=(),
    )


def _row(name, code):
    return ast.AvpTableRow(
        name=name,
        code=code,
        section="6.3.1",
        data_type=ast.DataType.ENUMERATED,
        flag_rules=ast.AvpFlagRules(),
        may_encrypt=False,
    )


def _enum_section(number, name):
    """A section shaped like an enumerated-AVP clause."""
    paragraphs = [
        tgpp_docx._Para(
            text=text,
            style=style,
            lines=[
                tgpp_docx._Line(
                    text=text,
                    style=style,
                    bold=frozenset({False}),
                    struck=frozenset({False}),
                )
            ],
        )
        for text, style in [
            (f"The {name} AVP is of type Enumerated.", ""),
            ("Off (0)", "B1"),
        ]
    ]
    return tgpp_docx._Section(number=number, title=name, paragraphs=paragraphs)


def test_resolve_rejects_an_enum_with_no_code_in_the_avp_table():
    collected = tgpp_docx._Collected(
        grouped=[_grouped()],
        pending_enums=[(_enum_section("6.3.2", "Mode"), "Mode")],
        avp_tables=[_avp_table(_row("Other", 1))],
    )

    with pytest.raises(tgpp_docx.ExtractionError, match="has no code in the AVP table"):
        tgpp_docx._resolve(collected)


def test_resolve_rejects_avp_and_reused_table_counts_that_cannot_pair():
    # Adjacency in document order is the only thing that says which re-used
    # block belongs to which set, so unequal counts have no defensible pairing.
    two_avp_one_reused = tgpp_docx._Collected(
        avp_tables=[
            _avp_table(_row("One", 1), section="6.3"),
            _avp_table(_row("Two", 2), section="7.3"),
        ],
        reused_tables=[_reused_table(label="6.3.2")],
    )
    one_avp_two_reused = tgpp_docx._Collected(
        avp_tables=[_avp_table(_row("One", 1))],
        reused_tables=[_reused_table(label="6.3.2"), _reused_table(label="7.4.1")],
    )

    for collected in (two_avp_one_reused, one_avp_two_reused):
        with pytest.raises(tgpp_docx.ExtractionError, match="cannot pair"):
            tgpp_docx._resolve(collected)


def test_resolve_rejects_one_name_with_two_codes_across_avp_tables():
    collected = tgpp_docx._Collected(
        avp_tables=[
            _avp_table(_row("One", 1), section="6.3"),
            _avp_table(_row("One", 2), section="7.3"),
        ],
        reused_tables=[
            _reused_table(label="6.3.2"),
            _reused_table(label="7.3.2"),
        ],
    )

    with pytest.raises(tgpp_docx.ExtractionError, match="code conflict"):
        tgpp_docx._resolve(collected)


def test_resolve_refuses_conflicting_enumerated_vendor_ids():
    # Two different explicit vendor ids cannot both be this document's
    # implicit vendor for enumerated definitions.
    collected = tgpp_docx._Collected(
        grouped=[_grouped(10415), _grouped(vendor_id=13019)],
        pending_enums=[(_enum_section("6.3.2", "Mode"), "Mode")],
        avp_tables=[_avp_table(_row("Mode", 11))],
    )

    with pytest.raises(tgpp_docx.ExtractionError, match="cannot resolve the vendor id"):
        tgpp_docx._resolve(collected)


def _paragraph(document, text):
    return next(p for p in document.paragraphs if p.text == text)


def test_extract_rejects_an_abnf_line_with_mixed_bold(tmp_path, synthetic_spec_docx):
    # Word splits a line into runs at arbitrary points, and 3GPP files really
    # do carry bold on the brackets but not the name. When the *name* runs
    # disagree with each other there is no honest answer, so it fails.
    malformed = tmp_path / "mixed-bold.docx"
    document = docx.Document(synthetic_spec_docx)
    rule = _paragraph(document, "* [ Local-AVP ]")
    rule.runs[0].text = "* [ Local-"
    tail = rule.add_run("AVP ]")
    tail.bold = False
    document.save(malformed)

    with pytest.raises(tgpp_docx.ExtractionError, match="mixed bold in ABNF line"):
        tgpp_docx.extract(malformed)


def test_extract_reads_text_inside_smart_tags(tmp_path, synthetic_spec_docx):
    # TS 29.338 clause 5.3.2.6 tags the abbreviation in its heading, which
    # python-docx would read as "Alert-Service-Centre-Answer () Command", and
    # TS 29.214's clause cells are tagged whole.
    tagged = tmp_path / "tagged.docx"
    document = docx.Document(synthetic_spec_docx)

    def tag(run):
        element = OxmlElement("w:smartTag")
        element.set(qn("w:element"), "stockticker")
        element.append(OxmlElement("w:smartTagPr"))
        run._r.addprevious(element)
        element.append(run._r)

    heading = _paragraph(document, "6.1\tExample-Request (EXR) Command")
    heading.runs[0].text = "6.1\tExample-Request ("
    tag(heading.add_run("EXR"))
    heading.add_run(") Command")
    rule = _paragraph(document, "< Session-Id >")
    rule.runs[0].text = "< Session-"
    tag(rule.add_run("Id"))
    rule.add_run(" >")
    cell = document.tables[1].cell(2, 2).paragraphs[0]
    cell.runs[0].text = ""
    tag(cell.add_run("6.3.1"))
    document.save(tagged)

    spec = tgpp_docx.extract(tagged)

    message = next(s for s in spec.sections if isinstance(s, ast.Message))
    assert message.abbreviation == "EXR"
    assert message.avps[0].name == "Session-Id"
    table = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    assert table.rows[0].section == "6.3.1"


def test_a_spaced_command_heading_keeps_the_rule_s_name(tmp_path, synthetic_spec_docx):
    # TS 29.336 clause 8.2.7: "NIDD Information Request (NIR) Command".
    spaced = tmp_path / "spaced.docx"
    document = docx.Document(synthetic_spec_docx)
    heading = _paragraph(document, "6.1\tExample-Request (EXR) Command")
    heading.runs[0].text = "6.1\tExample Request (EXR) Command"
    document.save(spaced)

    warnings = []
    spec = tgpp_docx.extract(spaced, warnings=warnings)

    message = next(s for s in spec.sections if isinstance(s, ast.Message))
    assert (message.name, message.abbreviation) == ("Example-Request", "EXR")
    assert any("'Example Request' != rule name" in w for w in warnings)


def test_extract_rejects_an_avp_table_whose_caption_it_cannot_read(
    tmp_path, synthetic_spec_docx
):
    """The caption is where `; Table:` comes from, and a table with no label a
    reader can look up is worse than no extraction at all."""
    uncaptioned = tmp_path / "uncaptioned.docx"
    document = docx.Document(synthetic_spec_docx)
    _paragraph(document, "Table 6.3.1: AVP definitions").text = "Table  : definitions"
    document.save(uncaptioned)

    with pytest.raises(tgpp_docx.ExtractionError, match="AVP table without a caption"):
        tgpp_docx.extract(uncaptioned)


@pytest.mark.parametrize("quirk", ["note-defined-in-rfc", "clause-parenthetical"])
def test_undeclared_docx_shapes_are_rejected(tmp_path, synthetic_spec_docx, quirk):
    path = tmp_path / "undeclared.docx"
    document = docx.Document(synthetic_spec_docx)
    table = document.tables[1]
    if quirk == "note-defined-in-rfc":
        row = table.add_row()
        for cell, value in zip(
            row.cells,
            ["Noted-AVP", "NOTE 1", "", "Unsigned32", "M", "", "", "V", "No"],
            strict=True,
        ):
            cell.text = value
        note = table.add_row()
        note.cells[0].merge(
            note.cells[8]
        ).text = "NOTE 1: The value of this attribute is defined in IETF RFC 6733"
    else:
        table.cell(2, 2).text = "6.3.1 (see Note)"
    document.save(path)
    with pytest.raises(tgpp_docx.ExtractionError, match=quirk):
        tgpp_docx.extract(path)


@pytest.mark.parametrize(
    "body",
    ["Refer to clause 1.2.3.\nAdditional definition text.", "No definition supplied."],
)
def test_reference_only_quirk_rejects_other_command_text(tmp_path, body):
    document = docx.Document()
    document.add_paragraph("3GPP TS 29.999 V1.2.3")
    document.add_paragraph("6.1\tExample-Request (EXR) Command", style="Heading 1")
    for text in body.splitlines():
        document.add_paragraph(text)
    path = tmp_path / "bad.docx"
    document.save(path)
    (tmp_path / "TS29.999.toml").write_text(
        '[[quirk]]\nname = "command-reference-only"\nreason = "test rejection"\n'
    )
    with pytest.raises(tgpp_docx.ExtractionError, match="command section without ABNF"):
        tgpp_docx.extract(path, sources_dir=tmp_path)


def _message_table_docx(tmp_path, spec_docx, marks=("yes", "No")):
    """TS 32.299 V11.20.0 clause 6.4.5's shape."""
    document = docx.Document(spec_docx)
    document.add_paragraph("6.4.5\tExample-Answer Message", style="Heading 1")
    document.add_paragraph("Table 6.4.5: Example-Answer (EXA) Message Contents")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Example Application AVPs"
    table.cell(1, 0).text, table.cell(1, 1).text = "AVP", "Used in 3GPP"
    for member, mark in zip(
        ("<Diameter Header: 321, PXY>", "<Session-Id>", "* [Proxy-Info]"),
        ("yes", *marks),
        strict=True,
    ):
        row = table.add_row()
        row.cells[0].text, row.cells[1].text = member, mark
    path = tmp_path / "table.docx"
    document.save(path)
    (tmp_path / "TS29.999.toml").write_text(
        '[[quirk]]\nname = "message-tables"\nreason = "test"\n'
        '[[quirk]]\nname = "struck-rules-unused"\nreason = "test"\n'
    )
    return path


def test_a_command_printed_as_a_table_is_a_message(tmp_path, synthetic_spec_docx):
    path = _message_table_docx(tmp_path, synthetic_spec_docx)

    spec, comments = tgpp_docx.extract_with_comments(path, sources_dir=tmp_path)

    message = next(
        s
        for s in spec.sections
        if isinstance(s, ast.Message) and s.name == "Example-Answer"
    )
    assert message.abbreviation == "EXA"
    assert message.command_code == 321
    assert message.flags == frozenset({ast.CommandFlag.PROXIABLE})
    assert [rule.name for rule in message.avps] == ["Session-Id"]
    # "No" reads as the strike, commented out where it stood.
    assert re.search(
        r"^;;.*\[ Proxy-Info \] +; strikethrough$",
        formatter.format_spec(spec, comments),
        re.M,
    )


def test_a_command_table_with_another_mark_fails(tmp_path, synthetic_spec_docx):
    path = _message_table_docx(tmp_path, synthetic_spec_docx, ("yes", "maybe"))
    with pytest.raises(tgpp_docx.ExtractionError, match="neither yes nor no"):
        tgpp_docx.extract(path, sources_dir=tmp_path)


def _procedure_section(*lines):
    """A procedure clause printing the lines, as TS 29.234 clause 4.4.2.2 does."""
    para = [
        tgpp_docx._Para(
            text=text,
            style="",
            lines=[
                tgpp_docx._Line(
                    text=text,
                    style="",
                    bold=frozenset({False}),
                    struck=frozenset({False}),
                )
            ],
        )
        for text in lines
    ]
    return tgpp_docx._Section(number="4.4.2.2", title="Procedures", paragraphs=para)


def _procedure_messages(section, *quirk_names):
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks(
        [Quirk(name=name, reason="test") for name in quirk_names],
        None,
    )
    return tgpp_docx._extract_messages(section, None, [], quirks, [])


def test_rfc_command_rules_names_a_rule_from_its_command_code():
    asr, dea = _procedure_messages(
        _procedure_section(
            "<ASR> ::= < Diameter Header: 274, REQ, PXY >",
            "< Session-Id >",
            "<Diameter-EAP-Answer> ::= < Diameter Header: 268, PXY >",
            "< Session-Id >",
        ),
        "procedure-commands",
        "rfc-command-rules",
    )
    assert (asr.name, asr.abbreviation) == ("Abort-Session-Request", "ASR")
    assert (dea.name, dea.abbreviation) == ("Diameter-EAP-Answer", "DEA")


def test_a_bare_command_heading_is_read_through_the_rfc_command():
    # TS 29.061 clause 17.6.1, "AAR Command", over `<AA-Request> ::=`: the rule
    # keeps the document's spelling, the abbreviation comes from RFC 7155.
    aar, asr = _procedure_messages(
        _procedure_section(
            "The AAR command, defined in Diameter NASREQ, is indicated by code 265.",
            "<AA-Request> ::= < Diameter Header: 265, REQ, PXY >",
            "< Session-Id >",
            "The Abort-Session-Request (ASR) command, defined in IETF RFC 6733, ...",
            "<ASR> ::= < Diameter Header: 274, REQ, PXY >",
            "< Session-Id >",
        ),
        "procedure-commands",
        "rfc-command-rules",
    )
    assert (aar.name, aar.abbreviation) == ("AA-Request", "AAR")
    assert (asr.name, asr.abbreviation) == ("Abort-Session-Request", "ASR")


def test_a_procedure_step_names_the_command_printed_under_it():
    # TS 29.109 clauses 4.2 and 5.2, whose commands have no clause of their own:
    # the re-printed grouped rule between them is no command, and a body's
    # comments are read past a blank line.
    mar, bia = _procedure_messages(
        _procedure_section(
            "The BSF shall send the following request in the format of"
            " Multimedia-Auth-Request (MAR) message.",
            "<Multimedia-Auth-Request> ::=<Diameter Header: 303, REQ, PXY, 16777221 >",
            "< Session-Id >",
            "",
            "{ Origin-Host } ; Address of BSF",
            "The content of Vendor-Specific-Application-Id is:",
            "<Vendor-Specific-Application-Id>::=<AVP header: 260>",
            "1* [Vendor-Id] ; 3GPP is 10415",
            "After that the BSF shall send a Bootstrapping-Info-Answer message (BIA)"
            " back to the NAF.",
            "< Bootstrapping-Info-Answer> ::= < Diameter Header: 310, PXY, 16777220 >",
            "< Session-Id >",
        ),
        "procedure-commands",
        "abnf-comments",
    )
    assert (mar.name, mar.abbreviation) == ("Multimedia-Auth-Request", "MAR")
    assert [rule.name for rule in mar.avps] == ["Session-Id", "Origin-Host"]
    assert (bia.name, bia.abbreviation) == ("Bootstrapping-Info-Answer", "BIA")


def test_a_grouped_rule_in_a_command_clause_stays_malformed():
    section = _procedure_section("<Group> ::= < AVP header: 260 >")
    from seanchai.extractor.sources import Quirks

    with pytest.raises(tgpp_docx.ExtractionError, match="malformed rule header"):
        tgpp_docx._extract_messages(
            section,
            tgpp_docx._COMMAND_TITLE_RE.match("Example-Request (EXR) Command"),
            [],
            Quirks([], None),
            [],
        )


def test_application_id_stated_as_the_value_iana_assigned():
    # TS 29.061 clause 17.
    section = _procedure_section(
        "The Gmb application is defined as an IETF vendor specific Diameter"
        " application, where the vendor is 3GPP. The vendor identifier assigned by"
        " IANA to 3GPP is 10415. The Gmb application identifier value assigned by"
        " IANA is 16777223.",
    )
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="prose-application-ids", reason="test")], None)
    (scope,) = tgpp_docx._stated_applications(section, quirks)
    assert (scope.name, scope.application_id) == ("Gmb", 16777223)


@pytest.mark.parametrize(
    ("rule", "quirk_names", "message"),
    [
        (
            "<ASR> ::= < Diameter Header: 274, REQ, PXY >",
            ("procedure-commands",),
            "without a named intro",
        ),
        (
            "<XYZ> ::= < Diameter Header: 999, REQ, PXY >",
            ("procedure-commands", "rfc-command-rules"),
            "none of the RFC commands",
        ),
        (
            "<ASA> ::= < Diameter Header: 274, REQ, PXY >",
            ("procedure-commands", "rfc-command-rules"),
            "none of the RFC commands",
        ),
    ],
    ids=["undeclared", "unknown-code", "another-abbreviation"],
)
def test_rfc_command_rules_rejects_what_no_rfc_names(rule, quirk_names, message):
    with pytest.raises(tgpp_docx.ExtractionError, match=message):
        _procedure_messages(_procedure_section(rule), *quirk_names)


def test_an_avp_table_cell_naming_no_type_fails_undeclared(
    tmp_path, synthetic_spec_docx
):
    document = docx.Document(str(synthetic_spec_docx))
    cell = next(
        cell
        for table in document.tables
        for row in table.rows
        for cell in row.cells
        if cell.text == "Grouped"
    )
    cell.text = "Integer"
    path = tmp_path / "bad.docx"
    document.save(path)
    with pytest.raises(tgpp_docx.ExtractionError, match="Integer"):
        tgpp_docx.extract(path, sources_dir=tmp_path)


def test_message_only_quirk_cannot_accept_a_document_without_commands():
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="message-only", reason="rejection case")], None)
    with pytest.raises(tgpp_docx.ExtractionError, match="no AVP table found"):
        tgpp_docx._resolve(tgpp_docx._Collected(), quirks)


def test_an_enumerated_clause_naming_two_value_sources_is_rejected():
    from seanchai.extractor.sources import Quirk, Quirks

    section = _enum_section("7.3.67", "Trace-Depth")
    for text in (
        "The possible values are those defined in TS 32.422 [23] for Trace Depth.",
        "The values are taken from OMNA WSP Content Type Numbers [210].",
    ):
        section.paragraphs.append(
            tgpp_docx._Para(text=text, style="", lines=section.paragraphs[0].lines)
        )
    quirks = Quirks([Quirk(name="external-enum-values", reason="rejection")], None)

    with pytest.raises(tgpp_docx.ExtractionError, match="names 2 sources"):
        tgpp_docx._extract_enumerated(section, "Trace-Depth", 1462, 10415, quirks, [])


def _enum_with(text):
    section = _enum_section("6.3.1", "Example-Mode")
    del section.paragraphs[1:]
    section.paragraphs.append(
        tgpp_docx._Para(text=text, style="B1", lines=section.paragraphs[0].lines)
    )
    return section


@pytest.mark.parametrize(
    ("text", "declared"),
    [
        ("- OFF (0)", []),
        ("Fully Off (0)", []),
        ("OFF (0x0)", []),
        ("OFF (0),", []),
        ("OFF (0) The mode is off", []),
        ("- (0) Off.", []),
        ("OFF (0)ON (1)", []),
        # Every departure needs its own declaration.
        ("- Fully Off (0)", ["dashed-enum-values"]),
        ("- OFF (0),", ["punctuated-enum-values"]),
        ("Submission, Profile based (0)", ["worded-enum-values"]),
    ],
)
def test_an_undeclared_enum_value_shape_is_not_read(text, declared):
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name=name, reason="rejection") for name in declared], None)
    warnings = []

    enum = tgpp_docx._extract_enumerated(
        _enum_with(text), "Example-Mode", 1, 10415, quirks, warnings
    )

    assert enum.values == ()
    assert warnings == ["6.3.1: enumerated AVP Example-Mode lists no values"]


def test_a_label_after_the_value_must_be_a_value_name():
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="label-after-enum-value", reason="rejection")], None)

    with pytest.raises(tgpp_docx.ExtractionError, match="is no value name"):
        tgpp_docx._extract_enumerated(
            _enum_with("(0) Off; see clause 2"), "Example-Mode", 1, 10415, quirks, []
        )


def test_a_label_before_the_value_must_be_a_value_name():
    # TS 32.299 writes "0 PS to CS Transfer"; `.dad` could quote a label of
    # prose, but the line is still no value.
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="value-first-enums", reason="rejection")], None)
    section = _enum_with("3 Off; see clause 2")
    section.paragraphs[-1].lines = _abnf_lines("3 Off; see clause 2")

    with pytest.raises(tgpp_docx.ExtractionError, match="is not a value name"):
        tgpp_docx._extract_enumerated(section, "Example-Mode", 1, 10415, quirks, [])


@pytest.mark.parametrize(("tabbed", "values"), [(True, 1), (False, 0)])
def test_a_label_first_value_is_read_only_where_a_tab_sets_it_off(tabbed, values):
    """TS 32.299 V11.20.0 prints "MONETARY<tabs>0"; normalizing makes that
    "MONETARY 0", which a sentence ending in a number also reads as, so
    `value-last-enums` takes a line only where the printed one had the tab."""
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="value-last-enums", reason="rejection")], None)
    section = _enum_with("MONETARY 0")
    section.paragraphs[-1].lines = [
        tgpp_docx._Line(
            text="MONETARY 0",
            style="B1",
            bold=frozenset({False}),
            struck=frozenset({False}),
            tabbed_number=tabbed,
        )
    ]

    enum = tgpp_docx._extract_enumerated(section, "Example-Mode", 1, 10415, quirks, [])

    assert len(enum.values) == values


@pytest.mark.parametrize(
    ("text", "found", "warned"),
    [
        # TS 32.299 clause 7.2.213.
        (
            "11 .. 99 Reserved for 3GPP defined SM services",
            ast.ReservedValues(first=11, last=99),
            None,
        ),
        (
            "100 .. 199 Vendor specific SM services",
            ast.VendorSpecificValues(
                first=100, last=199, description="Vendor specific SM services"
            ),
            None,
        ),
        # oneM2M TS-0004 clause A.5.17.
        (
            "100 .. 199 Operator and vendor specific protocol types",
            ast.VendorSpecificValues(
                first=100,
                last=199,
                description="Operator and vendor specific protocol types",
            ),
            None,
        ),
        (
            "200 .. 299 Operator-specific services",
            ast.VendorSpecificValues(
                first=200, last=299, description="Operator-specific services"
            ),
            None,
        ),
        # Values reserved for vendor use are allocated to vendors.
        (
            "100 .. 199 Reserved for vendor specific services",
            ast.VendorSpecificValues(
                first=100,
                last=199,
                description="Reserved for vendor specific services",
            ),
            None,
        ),
        # A negation takes the range away from vendors.
        (
            "100 .. 199 Not for vendor-specific services",
            None,
            "6.3.1: value range 100..199 'Not for vendor-specific services'"
            " names no value and was not recorded",
        ),
        # Allocated to someone the words do not leave it to vendors.
        (
            "100 .. 199 Allocated to partner networks",
            None,
            "6.3.1: value range 100..199 'Allocated to partner networks' names"
            " no value and was not recorded",
        ),
    ],
)
def test_a_value_first_range_is_read_by_its_words(text, found, warned):
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="value-first-enums", reason="rejection")], None)
    section = _enum_with("0 Off")
    section.paragraphs[-1] = tgpp_docx._Para(
        text=f"0 Off\n{text}", style="B1", lines=_abnf_lines("0 Off", text)
    )
    warnings = []

    enum = tgpp_docx._extract_enumerated(
        section, "Example-Mode", 1, 10415, quirks, warnings
    )

    off = ast.EnumValue(name="Off", value=0)
    assert enum.values == ((off,) if found is None else (off, found))
    assert warnings == ([] if warned is None else [warned])


def _enum_lines(text, *, label=None):
    section = _enum_with(text)
    section.paragraphs[-1] = tgpp_docx._Para(
        text=text, style="B1", lines=_abnf_lines(text), label=label
    )
    return section


@pytest.mark.parametrize(
    ("text", "quirk", "label", "value"),
    [
        # TS 29.140 V7.0.0 clause 6.3.5, a quoted name with a comma.
        (
            "MM1 Message Submission, Profile based (0)",
            "comma-enum-labels",
            None,
            ast.EnumValue(name="MM1 Message Submission, Profile based", value=0),
        ),
        # TS 32.299 V11.20.0 clauses 7.2.101 and 7.2.207.
        (
            "[2] unknown",
            "bracketed-enum-values",
            None,
            ast.EnumValue(name="unknown", value=2),
        ),
        (
            "0. SUBMISSION",
            "dotted-enum-values",
            None,
            ast.EnumValue(name="SUBMISSION", value=0),
        ),
        # Clause 7.2.151: the number is the list's, "1." in the PDF.
        (
            "Moderator",
            "list-numbered-enum-values",
            "1.",
            ast.EnumValue(name="Moderator", value=1),
        ),
    ],
)
def test_a_declared_enum_value_shape_is_read_and_only_then(text, quirk, label, value):
    from seanchai.extractor.sources import Quirk, Quirks

    needed = [quirk] + (["worded-enum-values"] if "," in text else [])
    declared = Quirks([Quirk(name=name, reason="test") for name in needed], None)
    undeclared = Quirks(
        [Quirk(name=name, reason="test") for name in needed if name != quirk], None
    )

    read = tgpp_docx._extract_enumerated(
        _enum_lines(text, label=label), "Example-Mode", 1, 10415, declared, []
    )
    warnings = []
    unread = tgpp_docx._extract_enumerated(
        _enum_lines(text, label=label), "Example-Mode", 1, 10415, undeclared, warnings
    )

    assert read.values == (value,)
    assert unread.values == ()
    assert warnings == ["6.3.1: enumerated AVP Example-Mode lists no values"]


def test_a_list_level_without_a_start_counts_from_zero():
    """ECMA-376 part 1, 17.9.25: TS 32.299 V11.20.0's PoC-Server-Role list
    (clause 7.2.145) gives no `w:start`, and its PDF prints 0 and 1."""
    numbering = _numbering(
        '<w:abstractNum w:abstractNumId="1">'
        '<w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1"/>'
        "</w:lvl></w:abstractNum>"
        '<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>'
    )
    replay = tgpp_docx._ListNumbering(numbering, None)

    assert [replay.advance(_numbered(1, 0)) for _ in range(2)] == ["0", "1"]


def _abnf_lines(*texts):
    return [
        tgpp_docx._Line(
            text=text,
            style="PL",
            bold=frozenset({False}) if text else frozenset(),
            struck=frozenset({False}) if text else frozenset(),
        )
        for text in texts
    ]


def test_a_blank_line_before_a_line_of_several_members_does_not_end_the_body():
    # The corpus has blank lines inside bodies (TS 32.299's CCA) and lines of
    # several members (its 7.2.154I), but never one right after the other.
    lines = _abnf_lines("[ First ]", "", "[ Second ] [ Third ]", "[ Fourth ]", "Prose")

    rules, end, _ = tgpp_docx._abnf_body(
        lines, 0, "Example", tgpp_docx.sources.Quirks([], None), []
    )

    assert [rule.name for rule in rules] == ["First", "Second", "Third", "Fourth"]
    assert end == 4


def _struck_lines():
    lines = _abnf_lines("[ First ]", "[ Struck ]", "[ Last ]")
    lines[1].struck = frozenset({True})
    return lines


def test_a_struck_member_without_a_legend_stays_a_member_with_its_marker():
    warnings: list[str] = []

    rules, _, commented = tgpp_docx._abnf_body(
        _struck_lines(), 0, "Example", tgpp_docx.sources.Quirks([], None), warnings
    )

    assert [(rule.name, rule.strikethrough) for rule in rules] == [
        ("First", False),
        ("Struck", True),
        ("Last", False),
    ]
    assert commented == []
    assert warnings == ["Example: member Struck is struck through"]


def test_behind_its_legend_a_struck_member_is_commented_out_in_place():
    # TS 32.299 clauses 6.2.1.2 and 6.4.1.2: struck "is not used by 3GPP".
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="struck-rules-unused", reason="legend")], None)
    warnings: list[str] = []

    rules, _, commented = tgpp_docx._abnf_body(
        _struck_lines(), 0, "Example", quirks, warnings
    )

    assert [rule.name for rule in rules] == ["First", "Last"]
    assert commented == [(1, "     [ Struck ] ; strikethrough")]
    assert warnings == []


def test_a_partly_struck_line_still_fails():
    lines = _struck_lines()
    lines[1].struck = frozenset({True, False})

    with pytest.raises(tgpp_docx.ExtractionError, match="partly struck"):
        tgpp_docx._abnf_body(
            lines, 0, "Example", tgpp_docx.sources.Quirks([], None), []
        )


def _vendor_table(reference):
    """TS 32.299 table 7.3.1's two-row header and one row."""
    rows = [
        [
            "AVP Name",
            "AVP Code",
            "Used in",
            "Used in",
            "Used in",
            "Used in",
            "Reference",
        ],
        ["AVP Name", "AVP Code", "ACR", "ACA", "CCR", "CCA", "Reference"],
        ["3GPP2-BSID", "9010", "X", "-", "X", "-", reference],
    ]
    return tgpp_docx._Table(
        caption="7.3.1",
        rows=[
            tgpp_docx._Row(cells=cells, first_cell_lines=cells[:1]) for cells in rows
        ],
    )


def test_a_vendor_table_reference_cell_must_be_a_reference_number():
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="vendor-avp-tables", reason="rejection")], None)
    with pytest.raises(tgpp_docx.ExtractionError, match="no reference number"):
        tgpp_docx._extract_vendor_table(
            _vendor_table("TS 29.212"), "7.3", [], quirks, {}
        )


def test_a_vendor_table_row_citing_an_unnameable_reference_adds_no_row():
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="vendor-avp-tables", reason="rejection")], None)
    warnings: list[str] = []
    table = tgpp_docx._extract_vendor_table(
        _vendor_table("[301]"),
        "7.5",
        warnings,
        quirks,
        # TS 32.299's [209], which numbers no document.
        {"301": 'OMA "Multimedia Messaging Service; Encapsulation Protocol".'},
    )

    assert table.rows == []
    assert warnings[-1] == (
        "re-used AVPs row '3GPP2-BSID' refers to [301], which names no"
        " document a From cell can cite; no row added"
    )


@pytest.mark.parametrize(
    ("entry", "origin"),
    [
        ('oneM2M TS-0004: "Service Layer Core Protocol ...".', "oneM2M-TS-0004"),
        ('OMA-DDS-Charging_Data: "Charging Data".', "OMA-DDS-Charging_Data"),
        ('ETSI TS 283 034 v2.2.0: "... (TISPAN); ..."', "ETSI-TS283.034"),
        ('3GPP2 X.S0057-B: "E-UTRAN - eHRPD ..."', "3GPP2-X.S0057"),
        # The document is what precedes the title.
        ('3GPP TS 29.212: "... (ETSI TS 283 034)".', "TS29.212"),
    ],
)
def test_a_clause_2_entry_names_its_document_with_its_publisher(entry, origin):
    assert tgpp_docx._entry_document(entry) == origin


def test_a_from_cell_printing_an_etsi_series_reads_clause_2():
    from seanchai.extractor.sources import Quirk, Quirks

    references = {"37": 'ETSI TS 283 034 v2.2.0: "..."', "15": 'ETSI TS 183 017: "..."'}
    cell = "3GPP\xa0TS 283 034\xa0[37]"
    with pytest.raises(tgpp_docx.ExtractionError, match="origins-by-reference"):
        tgpp_docx._origin(cell, "TS29.212", references, Quirks([], None))

    quirks = Quirks([Quirk(name="origins-by-reference", reason="test")], None)
    assert tgpp_docx._origin(cell, "TS29.212", references, quirks) == "ETSI-TS283.034"
    with pytest.raises(tgpp_docx.ExtractionError, match=r"\[15\], which names"):
        tgpp_docx._origin("3GPP TS 283 034 [15]", "TS29.212", references, quirks)


_REGISTRY_HEADER = ("AVP Code", "Attribute Name", "Specified in the TS")


def _registry_table(*rows, header=_REGISTRY_HEADER):
    """TS 29.230 table 7.1's shape: a header, then rows of physical cells."""
    return tgpp_docx._Table(
        caption="7.1",
        rows=[
            tgpp_docx._Row(cells=list(cells), first_cell_lines=list(cells[:1]))
            for cells in (header, *rows)
        ],
    )


def _registry_quirks(*names):
    from seanchai.extractor.sources import Quirk, Quirks

    return Quirks([Quirk(name=name, reason="rejection") for name in names], None)


@pytest.mark.parametrize(
    ("table", "message"),
    [
        (
            _registry_table(("1", "A", "29.229")),
            r"unrecognized document cell '29\.229'",
        ),
        (
            _registry_table(("1", "A", "29.229 [2]"), header=("AVP Code", "Owner")),
            "unrecognized registry column 'Owner'",
        ),
        (
            _registry_table(("Note: The AVP codes from 1 to 9 are reserved for x",)),
            "does not read \\(the `reserved-range-notes` quirk\\)",
        ),
        (
            _registry_table(
                ("314", "Charging-Characteristics", "Integer"),
                header=("AVP Code", "Attribute Name", "Data Type"),
            ),
            "'Integer' names no Diameter type",
        ),
    ],
    ids=["bare-number", "unknown-column", "undeclared-notes", "undeclared-type"],
)
def test_a_registry_table_rejects_what_it_cannot_read(table, message):
    with pytest.raises(tgpp_docx.ExtractionError, match=message):
        tgpp_docx._extract_registry(
            table, "7.1", [], _registry_quirks("registry-tables"), {"2": "TS 29.229"}
        )


# --- list-numbered headings (oneM2M TS-0004) --------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _numbering(xml: str):
    from docx.oxml import parse_xml

    return parse_xml(f'<w:numbering xmlns:w="{_W}">{xml}</w:numbering>')


def _level(ilvl, text, fmt="decimal", start=1, extra=""):
    return (
        f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="{start}"/>'
        f'<w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>{extra}</w:lvl>'
    )


def _numbered(num_id=None, ilvl=0, style=None):
    from docx.oxml import parse_xml

    num_pr = (
        ""
        if num_id is None
        else f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/></w:numPr>'
    )
    p_style = "" if style is None else f'<w:pStyle w:val="{style}"/>'
    return parse_xml(f'<w:p xmlns:w="{_W}"><w:pPr>{p_style}{num_pr}</w:pPr></w:p>')


def test_list_numbering_replays_counters_with_restarts_and_overrides():
    """oneM2M TS-0004's annex: level text `A.%1`, `A.%1.%2`, deeper levels
    restarting under a new parent; a style's own list prints nothing."""
    numbering = _numbering(
        '<w:abstractNum w:abstractNumId="1">'
        + _level(0, "A.%1", extra="<w:isLgl/>")
        + _level(1, "A.%1.%2", extra="<w:isLgl/>")
        + _level(2, "(%3)", fmt="lowerLetter", extra='<w:lvlRestart w:val="0"/>')
        + "</w:abstractNum>"
        '<w:abstractNum w:abstractNumId="2">'
        + _level(0, "", fmt="none")
        + "</w:abstractNum>"
        '<w:abstractNum w:abstractNumId="3">'
        + _level(0, "%1.", fmt="upperRoman")
        + "</w:abstractNum>"
        '<w:num w:numId="7"><w:abstractNumId w:val="1"/></w:num>'
        '<w:num w:numId="8"><w:abstractNumId w:val="2"/></w:num>'
        '<w:num w:numId="9"><w:abstractNumId w:val="3"/></w:num>'
        '<w:num w:numId="10"><w:abstractNumId w:val="3"/>'
        '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="4"/></w:lvlOverride>'
        "</w:num>"
    )
    styles = _numbering(
        '<w:style w:styleId="Heading1"><w:pPr><w:numPr><w:ilvl w:val="0"/>'
        '<w:numId w:val="8"/></w:numPr></w:pPr></w:style>'
        '<w:style w:styleId="Heading2"><w:basedOn w:val="Heading1"/></w:style>'
    )
    replay = tgpp_docx._ListNumbering(numbering, styles)

    labels = [
        replay.advance(paragraph)
        for paragraph in (
            _numbered(7, 0, style="Heading1"),  # A.1, its own list over its style's
            _numbered(style="Heading2"),  # the style's list, which prints nothing
            _numbered(7, 0),  # A.2
            _numbered(7, 1),  # A.2.1
            _numbered(7, 2),  # (a)
            _numbered(7, 1),  # A.2.2
            _numbered(7, 2),  # (b): level 3 never restarts
            _numbered(),
            _numbered(7, 0),  # A.3
            _numbered(7, 1),  # A.3.1: level 2 restarts under A.3
            _numbered(9, 0),  # I.
            _numbered(10, 0),  # IV., the override restarting the shared list
            _numbered(9, 0),  # V.
            _numbered(0, 0),  # numId 0 is no numbering
        )
    ]

    assert labels == [
        "A.1",
        None,
        "A.2",
        "A.2.1",
        "(a)",
        "A.2.2",
        "(b)",
        None,
        "A.3",
        "A.3.1",
        "I.",
        "IV.",
        "V.",
        None,
    ]


def _with_num_pr(num_pr: str, style: str | None = None):
    """A paragraph whose `w:numPr` holds exactly `num_pr`."""
    from docx.oxml import parse_xml

    p_style = "" if style is None else f'<w:pStyle w:val="{style}"/>'
    return parse_xml(
        f'<w:p xmlns:w="{_W}"><w:pPr>{p_style}<w:numPr>{num_pr}</w:numPr></w:pPr></w:p>'
    )


_TWO_LEVELS = (
    '<w:abstractNum w:abstractNumId="1">'
    + _level(0, "A.%1")
    + _level(1, "A.%1.%2")
    + "</w:abstractNum>"
)


@pytest.mark.parametrize(
    "override",
    [
        _level(0, "B.%1", start=4),
        # The level's start overridden apart from its text.
        '<w:startOverride w:val="4"/>' + _level(0, "B.%1"),
    ],
    ids=["lvl", "lvl-and-start-override"],
)
def test_an_override_level_renders_with_its_own_text_format_and_start(override):
    """A `w:lvlOverride/w:lvl` redefines the level for its `w:num`: start 4
    and level text `B.%1` number the first paragraph B.4, not A.1."""
    numbering = _numbering(
        _TWO_LEVELS
        + '<w:abstractNum w:abstractNumId="2">'
        + _level(0, "(%1)", fmt="lowerLetter")
        + "</w:abstractNum>"
        '<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>'
        '<w:num w:numId="2"><w:abstractNumId w:val="1"/>'
        f'<w:lvlOverride w:ilvl="0">{override}</w:lvlOverride></w:num>'
        '<w:num w:numId="3"><w:abstractNumId w:val="2"/>'
        '<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0"><w:numFmt w:val="upperRoman"/>'
        "</w:lvl></w:lvlOverride></w:num>"
    )
    replay = tgpp_docx._ListNumbering(numbering, None)

    labels = [
        replay.advance(_numbered(num_id, ilvl))
        for num_id, ilvl in ((2, 0), (2, 1), (2, 0), (1, 0), (3, 0))
    ]

    # The abstract's text and its other levels stay for the num without the
    # override; a `w:lvl` giving only a format keeps the abstract's text.
    assert labels == ["B.4", "A.4.1", "B.5", "A.6", "(I)"]


def test_a_restarted_level_restarts_at_its_overridden_start():
    """Level 1 overridden to start at 4 restarts at 4 under each new
    level-0 paragraph, the first included."""
    numbering = _numbering(
        _TWO_LEVELS + '<w:num w:numId="1"><w:abstractNumId w:val="1"/>'
        '<w:lvlOverride w:ilvl="1"><w:startOverride w:val="4"/></w:lvlOverride>'
        "</w:num>"
    )
    replay = tgpp_docx._ListNumbering(numbering, None)

    labels = [replay.advance(_numbered(1, ilvl)) for ilvl in (0, 1, 1, 0, 1)]

    assert labels == ["A.1", "A.1.4", "A.1.5", "A.2", "A.2.4"]


def test_a_paragraph_numpr_inherits_what_it_leaves_out_from_its_style():
    """Word merges `w:numId` and `w:ilvl` separately: a heading printing
    only its level numbers in its style's list, one printing only its list
    takes its style's level."""
    numbering = _numbering(
        _TWO_LEVELS + '<w:num w:numId="5"><w:abstractNumId w:val="1"/></w:num>'
        '<w:num w:numId="6"><w:abstractNumId w:val="1"/></w:num>'
    )
    styles = _numbering(
        '<w:style w:styleId="Heading1"><w:pPr><w:numPr><w:ilvl w:val="0"/>'
        '<w:numId w:val="5"/></w:numPr></w:pPr></w:style>'
        '<w:style w:styleId="Heading2"><w:basedOn w:val="Heading1"/><w:pPr>'
        '<w:numPr><w:ilvl w:val="1"/></w:numPr></w:pPr></w:style>'
    )
    replay = tgpp_docx._ListNumbering(numbering, styles)

    labels = [
        replay.advance(paragraph)
        for paragraph in (
            _with_num_pr('<w:ilvl w:val="0"/>', style="Heading2"),  # list 5
            _with_num_pr('<w:numId w:val="6"/>', style="Heading2"),  # level 1
            _with_num_pr("", style="Heading2"),  # level 1, Heading1's list
            _with_num_pr('<w:numId w:val="0"/>', style="Heading1"),  # unnumbered
        )
    ]

    assert labels == ["A.1", "A.1.1", "A.1.2", None]


def test_a_list_format_the_replay_cannot_render_fails():
    numbering = _numbering(
        '<w:abstractNum w:abstractNumId="1">'
        + _level(0, "%1", fmt="chineseCounting")
        + '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>'
    )
    replay = tgpp_docx._ListNumbering(numbering, None)

    with pytest.raises(tgpp_docx.ExtractionError, match="'chineseCounting'"):
        replay.advance(_numbered(1, 0))


_ONEM2M_SOURCE = (
    Path(__file__).parent.parent
    / "specifications/converted/onem2m/Release-2/TS-0004"
    / "TS-0004-Service_Layer_Core_Protocol-V2_35_0(cl).docx"
)


@pytest.mark.sources
def test_onem2m_ts_0004s_annex_a_headings_number_as_its_pdf_prints_them():
    """ETSI TS 118 104 V2.7.1 (the same Release 2 line, PDF only) and
    TS-0004 V5.2.0's Word file print annex A's numbers as text; V2.35.0's
    exist only in its list numbering."""
    assert _ONEM2M_SOURCE.is_file(), "run `seanchai download`"
    document = docx.Document(str(_ONEM2M_SOURCE))
    replay = tgpp_docx._ListNumbering(
        document.part.numbering_part.element, document.styles.element
    )
    annex = []
    inside = False
    for item in document.iter_inner_content():
        if not isinstance(item, docx.text.paragraph.Paragraph):
            continue
        label = replay.advance(item._p)
        style = (item.style.name if item.style is not None else None) or ""
        if item.text.startswith("Annex "):
            inside = item.text.startswith("Annex A ")
        elif inside and style.startswith("Heading"):
            annex.append((label, item.text))

    assert annex[:7] == [
        ("A.1", "Introduction"),
        ("A.2", "Diameter Commands on Mch"),
        ("A.2.1", "Accounting Request Command"),
        ("A.2.2", "Accounting Answer Command"),
        ("A.3", "Mapping of M2M Recorded Information Elements to AVPs"),
        ("A.4", "Summary of AVPs used"),
        ("A.5", "oneM2M Specific AVP Usage"),
    ]
    assert [label for label, _ in annex[7:]] == [f"A.5.{n}" for n in range(1, 33)]
    assert annex[20] == ("A.5.14", "M2M-Information AVP")


# --- oneM2M TS-0004 table A.4-1 ---------------------------------------------


def _vendor_column_table(*data):
    upper = [
        "AVP Name",
        "AVP Vendor Id",
        "AVP Code",
        *["Used in"] * 4,
        "Reference",
        "Value Type",
        *["AVP Flag rules"] * 5,
    ]
    lower = [
        "AVP Name",
        "AVP Vendor Id",
        "AVP Code",
        "ACR",
        "ACA",
        "CCR",
        "CCA",
        "Reference",
        "Value Type",
        "Must",
        "May",
        "Should not",
        "Must not",
        "May Encr.",
    ]
    return tgpp_docx._Table(
        caption="A.4-1",
        rows=[
            tgpp_docx._Row(cells=cells, first_cell_lines=cells[:1])
            for cells in (upper, lower, *data)
        ],
    )


def _a4_row(name, vendor, code, reference):
    marks = ["O", "-", "-", "-"]
    flags = ["M", "P", "-", "V", "Y"]
    return [name, vendor, code, *marks, reference, "Unsigned32", *flags]


def _a4_quirks(*names):
    from seanchai.extractor.sources import Quirk, Quirks

    return Quirks([Quirk(name=name, reason="test") for name in names], None)


def test_a_reference_column_names_a_clause_or_the_document_re_used_from():
    table, reused = tgpp_docx._extract_avp_table(
        _vendor_column_table(
            _a4_row("Occupancy", "45687", "1012", "[A.5.16]"),
            _a4_row("Origin-State-Id", "0", "278", "IETF RFC 6733 [14]"),
            _a4_row("Node-Id", "10415", "2064", "3GPP TS 32.299 [31]"),
        ),
        "A.4",
        [],
        _a4_quirks("reference-cells", "command-columns"),
    )

    assert ast.AvpColumn.VENDOR in table.columns
    assert [(row.vendor_id, row.code, row.section) for row in table.rows] == [
        (45687, 1012, "A.5.16"),
        (0, 278, None),
        (10415, 2064, None),
    ]
    assert [(row.name, row.origin) for row in reused] == [
        ("Origin-State-Id", "RFC6733"),
        ("Node-Id", "TS32.299"),
    ]


@pytest.mark.parametrize(
    ("cell", "column", "message"),
    [
        ("see A.5.1", 7, "names neither a clause nor a document"),
        ("[see A.5.1]", 7, "bracket holds no clause number"),
        ("oneM2M", 1, "vendor cell 'oneM2M'"),
    ],
)
def test_a_table_a4_cell_it_cannot_read_fails(cell, column, message):
    row = _a4_row("Occupancy", "45687", "1012", "[A.5.16]")
    row[column] = cell
    with pytest.raises(tgpp_docx.ExtractionError, match=message):
        tgpp_docx._extract_avp_table(
            _vendor_column_table(row),
            "A.4",
            [],
            _a4_quirks("reference-cells", "command-columns"),
        )


def test_a_reference_column_is_unmodelled_without_its_quirk():
    warnings: list[str] = []
    table, reused = tgpp_docx._extract_avp_table(
        _vendor_column_table(_a4_row("Occupancy", "45687", "1012", "[A.5.16]")),
        "A.4",
        warnings,
        _a4_quirks("command-columns"),
    )

    assert ast.AvpColumn.SECTION not in table.columns
    assert reused == []
    assert "AVP table column 'Reference' is not modelled and was dropped" in warnings


def test_a_onem2m_cover_names_the_document_and_its_publishers_vendor(tmp_path):
    document = docx.Document()
    cover = document.add_table(rows=1, cols=2)
    cover.cell(0, 0).text = "Document Number"
    cover.cell(0, 1).text = "oneM2M-TS-0004-V2.35.0"

    assert tgpp_docx._spec_and_version(document) == ("oneM2M TS-0004", "2.35.0")
    assert tgpp_docx._publisher_vendor("oneM2M TS-0004") == 45687
    assert tgpp_docx._publisher_vendor("3GPP TS 29.272") == 10415


def test_a_value_named_in_a_sentence_is_read_behind_its_quirk():
    text = (
        "The following value is currently defined for the Accounting-Record-Type"
        " AVP: EVENT_RECORD (value 1) for an Event Based request."
    )
    read = tgpp_docx._extract_enumerated(
        _enum_with(text), "Accounting-Record-Type", 480, None,
        _a4_quirks("prose-enum-values"), [],
    )  # fmt: skip
    unread = tgpp_docx._extract_enumerated(
        _enum_with(text), "Accounting-Record-Type", 480, None, _a4_quirks(), []
    )

    assert read.values == (ast.EnumValue(name="EVENT_RECORD", value=1),)
    assert unread.values == ()


# --- documents the corpus holds at an older release -------------------------

_RELEASE_11_TS_32_299 = _CORPUS_DIR / "raw/3gpp/rel-11/32299-bk0.raw.dad"


def test_ts_32_299_release_11_reads_its_own_template():
    """V11.20.0, which oneM2M TS-0004 cites, heads its commands "Message",
    writes value lists label first after tabs and dashes the Encrypt cells
    of its unused table 7.1 rows; its Release 11 declarations read all
    three, and none of Release 18's apply to it."""
    from seanchai.dad import parser

    spec = parser.parse(_RELEASE_11_TS_32_299.read_text(encoding="utf-8"))
    sections = {getattr(section, "name", None): section for section in spec.sections}

    assert spec.version == "11.20.0"
    assert [
        message.abbreviation
        for message in spec.sections
        if isinstance(message, ast.Message)
    ] == ["ACR", "ACA", "CCR", "CCA", "RAA"]
    aoc_format = sections["AoC-Format"]
    assert isinstance(aoc_format, ast.EnumeratedAvp)
    assert aoc_format.values == (
        ast.EnumValue(name="MONETARY", value=0),
        ast.EnumValue(name="NON_MONETARY", value=1),
        ast.EnumValue(name="CAI", value=2),
    )
    (unused,) = [
        row
        for table in spec.sections
        if isinstance(table, ast.AvpTable)
        for row in table.rows
        if row.name == "CC-Sub-Session-Id"
    ]
    assert unused.may_encrypt is None
    # Value lists printed in four more shapes, each its own declaration.
    enumerated = {
        section.name: section
        for section in spec.sections
        if isinstance(section, ast.EnumeratedAvp)
    }
    assert [
        (value.name, value.value)
        for name in ("Media-Initiator-Flag", "PoC-Server-Role", "SM-Message-Type")
        for value in enumerated[name].values
        if isinstance(value, ast.EnumValue)
    ] == [
        ("called party", 0),
        ("calling party", 1),
        ("unknown", 2),
        ("Participating PoC Server", 0),
        ("Controlling PoC Server", 1),
        ("SUBMISSION", 0),
        ("DELIVERY_REPORT", 1),
        ("SM Service Request", 2),
    ]
