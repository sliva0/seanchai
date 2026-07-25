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
    assert enumerated.values == (
        ast.EnumValue(
            name="Disabled", value=0, description="first description continued"
        ),
        ast.ReservedValues(first=1, last=2),
        ast.EnumValue(name="Enabled", value=3),
    )
    assert warnings == []
    assert parser.parse(formatter.format(spec)) == spec


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
