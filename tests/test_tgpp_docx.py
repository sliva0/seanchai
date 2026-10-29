import re

import docx
import pytest

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


def test_message_only_quirk_cannot_accept_a_document_without_commands():
    from seanchai.extractor.sources import Quirk, Quirks

    quirks = Quirks([Quirk(name="message-only", reason="rejection case")], None)
    with pytest.raises(tgpp_docx.ExtractionError, match="no AVP table found"):
        tgpp_docx._resolve(tgpp_docx._Collected(), quirks)


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

    rules, end = tgpp_docx._abnf_body(
        lines, 0, "Example", tgpp_docx.sources.Quirks([], None), []
    )

    assert [rule.name for rule in rules] == ["First", "Second", "Third", "Fourth"]
    assert end == 4
