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
    warnings = []

    spec = tgpp_docx.extract(
        synthetic_spec_docx,
        link="https://example.com/spec.pdf",
        warnings=warnings,
    )

    assert spec.specification == "3GPP TS 29.999"
    assert spec.version == "1.2.3"
    assert str(spec.link) == "https://example.com/spec.pdf"
    message, table, reused, grouped, enumerated = spec.sections
    assert isinstance(message, ast.Message)
    assert isinstance(table, ast.AvpTable)
    assert isinstance(reused, ast.ReusedAvps)
    assert isinstance(grouped, ast.GroupedAvp)
    assert isinstance(enumerated, ast.EnumeratedAvp)

    assert message.command_code == 321
    assert message.application_id == 42
    assert message.avps[1].bold is True

    source_table = docx.Document(synthetic_spec_docx).tables[1]
    merged_header = [cell.text for cell in source_table.rows[0].cells]
    assert merged_header[0] == merged_header[1] == "AVP"
    assert merged_header[4] == merged_header[5] == "AVP Flag rules"
    assert len(table.rows) == 2
    assert table.rows[1].may_encrypt is True
    assert table.rows[1].flag_rules.must == {ast.AvpFlag.VENDOR}

    # The fixture's re-used table has a Comments column, which the format does
    # not model and does not want to: it holds prose.
    assert reused.columns == (
        ast.ReusedColumn.NAME,
        ast.ReusedColumn.FROM,
        ast.ReusedColumn.M_BIT,
    )
    assert reused.rows == (
        ast.ReusedAvpRow(
            name="Other-AVP",
            origin="RFC6733",
            m_bit=ast.MBitOverride.MUST_NOT,
        ),
    )

    assert grouped.vendor_id == 10415
    assert grouped.avps[0].presence is ast.Presence.REQUIRED

    assert enumerated.vendor_id == 10415
    # The clause prose between the two values is not captured: a `.dad`
    # description is a one-line gloss, and a 3GPP clause has paragraphs.
    # `; Section:` is what points a reader at the prose.
    assert enumerated.values == (
        ast.EnumValue(name="Disabled", value=0),
        ast.ReservedValues(first=1, last=2),
        ast.EnumValue(name="Enabled", value=3),
    )
    assert warnings == []
    assert parser.parse(formatter.format_spec(spec)) == spec


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


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("Defined by 3GPP TS 29.336 clause 6", "TS29.336"),
        ("See IETF RFC 6733", "RFC6733"),
        # The publisher prefix is conventional, not reliable: 29.344 and 29.388
        # write their From cells with the bibliography number instead.
        ("TS 29.272 [10]", "TS29.272"),
        ("RFC 6733 [5]", "RFC6733"),
    ],
)
def test_origin_normalizes_supported_references(reference, expected):
    assert tgpp_docx._origin(reference) == expected


def test_origin_rejects_unknown_references():
    with pytest.raises(tgpp_docx.ExtractionError, match="unrecognized origin"):
        tgpp_docx._origin("some other document")


def test_flags_cell_accepts_only_comma_separated_uppercase_flags():
    assert tgpp_docx._flags_cell("M, V") == {
        ast.AvpFlag.MANDATORY,
        ast.AvpFlag.VENDOR,
    }


@pytest.mark.parametrize("cell", ["M. V", "M, v", "v"])
def test_flags_cell_rejects_known_source_typos(cell):
    with pytest.raises(
        tgpp_docx.ExtractionError,
        match=f"malformed flags cell {cell!r}",
    ):
        tgpp_docx._flags_cell(cell)


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


def test_attach_pages_is_idempotent(outlined_pdf):
    once = tgpp_docx.attach_pages(_two_section_spec(), outlined_pdf)

    assert tgpp_docx.attach_pages(once, outlined_pdf) == once


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


def test_extract_reads_the_columns_off_the_label_row(tmp_path):
    """TS 29.212's table has two columns beyond the shared nine. They are
    dropped, and warned about, because a column with machine-readable values
    is a reason to model it rather than to carry it anonymously."""
    warnings = []
    path = _avp_table_docx(
        tmp_path,
        [
            "Attribute Name",
            "AVP Code",
            "Clause defined",
            "Value Type (NOTE 2)",
            "Must",
            "May Encr.",
            "Acc. Type",
            "Applicability (notes 3, 9)",
        ],
        [["Local-AVP", "10", "6.3.1", "Unsigned32", "M, V", "Yes", "All", "Both Rel8"]],
    )

    spec = tgpp_docx.extract(path, warnings=warnings)

    (table,) = spec.sections
    assert isinstance(table, ast.AvpTable)
    assert table.columns == (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        # The note reference points at prose the format does not carry, so it
        # is not part of the label — and "Value Type (NOTE 2)" is still Type.
        ast.AvpColumn.TYPE,
        ast.AvpColumn.MUST,
        ast.AvpColumn.ENCRYPT,
    )
    assert warnings == [
        "AVP table column 'Acc. Type' is not modelled and was dropped",
        "AVP table column 'Applicability' is not modelled and was dropped",
    ]
    # Cells are still read positionally against the source table, so dropping
    # a column in the middle must not shift the ones after it.
    (row,) = table.rows
    assert (row.code, row.data_type) == (10, ast.DataType.UNSIGNED32)
    assert row.may_encrypt is True
    # An undeclared column is absent, not empty: this table had no May column.
    assert row.flag_rules.may == frozenset()

    text = formatter.format_spec(spec)
    assert formatter.format_spec(parser.parse(text)) == text
    assert parser.parse(text) == spec


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


def _reused_docx(tmp_path, labels, rows):
    """A spec with a minimal AVP table plus a re-used table with `labels`."""
    document = docx.Document()
    document.add_table(rows=1, cols=1).cell(0, 0).text = "3GPP TS 29.999 V1.2.3"
    document.add_paragraph(style="Heading 1").add_run("6.3\tAVP Definitions")
    document.add_paragraph("Table 6.3.1: AVP definitions")
    avp = document.add_table(rows=2, cols=3)
    avp.cell(0, 0).merge(avp.cell(0, 2)).text = "AVP Flag rules"
    for cell, label in zip(
        avp.rows[1].cells, ["Attribute Name", "AVP Code", "Value Type"], strict=True
    ):
        cell.text = label
    for cell, value in zip(
        avp.add_row().cells, ["Local-AVP", "10", "Unsigned32"], strict=True
    ):
        cell.text = value

    document.add_paragraph("Table 6.3.2: Re-used AVPs")
    reused = document.add_table(rows=1, cols=len(labels))
    for cell, label in zip(reused.rows[0].cells, labels, strict=True):
        cell.text = label
    for values in rows:
        for cell, value in zip(reused.add_row().cells, values, strict=True):
            cell.text = value
    path = tmp_path / "reused.docx"
    document.save(path)
    return path


def test_extract_reads_a_reused_table_with_no_m_bit_column(tmp_path):
    """TS 29.128, 29.173 and 29.336 print no M-bit column. The Comments column
    they do print is prose, so it is dropped without a warning."""
    warnings = []
    path = _reused_docx(
        tmp_path,
        ["Attribute Name", "Reference", "Comments"],
        [["Other-AVP", "IETF RFC 6733", "See clause 6.4.2"]],
    )

    spec = tgpp_docx.extract(path, warnings=warnings)

    reused = next(s for s in spec.sections if isinstance(s, ast.ReusedAvps))
    assert reused.columns == (ast.ReusedColumn.NAME, ast.ReusedColumn.FROM)
    assert reused.rows[0].m_bit is None
    assert warnings == []

    text = formatter.format_spec(spec)
    assert parser.parse(text) == spec
    assert formatter.format_spec(parser.parse(text)) == text


def test_a_prose_column_is_dropped_without_a_warning(tmp_path):
    """Comments, Description and Comment are known to hold narrative — up to
    1657 characters of it — which `.dad` does not carry. Dropping them is the
    intent, so they are not warned about; anything else unmodelled is."""
    warnings = []
    path = _reused_docx(
        tmp_path,
        ["Attribute Name", "Reference", "Description", "Acc. Type"],
        [["Other-AVP", "IETF RFC 6733", "a paragraph " * 40, "3GPP-EPS"]],
    )

    spec = tgpp_docx.extract(path, warnings=warnings)

    reused = next(s for s in spec.sections if isinstance(s, ast.ReusedAvps))
    assert reused.columns == (ast.ReusedColumn.NAME, ast.ReusedColumn.FROM)
    assert warnings == [
        "re-used table column 'Acc. Type' is not modelled and was dropped"
    ]
