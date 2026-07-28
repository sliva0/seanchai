"""The RFC plain-text extractor, against a synthetic RFC abstracted from
RFC 6733's §4.5 layout: fixed-width table, boxed flag-rules header, page
furniture, wrapped names — including the reversed wrap where the data cells
arrive on the continuation line."""

import pytest

from seanchai.dad import ast, formatter, parser
from seanchai.extractor import rfc_text
from seanchai.extractor.errors import ExtractionError

_HEADER_BOX = """\
                                            +----------+
                                            | AVP Flag |
                                            |  rules   |
                                            |----+-----|
                   AVP  Section             |    |MUST |
   Attribute Name  Code Defined  Data Type  |MUST| NOT |
   -----------------------------------------|----+-----|
"""

_FOOTER = "Author, et al.               Standards Track                   [Page {}]"
_RUNNING = "RFC 9999                  Synthetic Protocol                 April 2013"


def _rfc(body: str) -> str:
    """A minimal RFC text: a cover header block, then `body` (already carrying
    its own page furniture where the test wants any)."""
    return (
        "Internet Engineering Task Force (IETF)                        A. Author\n"
        "Request for Comments: 9999                                     Somewhere\n"
        "Category: Standards Track\n"
        "\n"
        "                       A Synthetic Protocol\n"
        "\n" + body
    )


def _synthetic() -> str:
    """Two page-broken chunks of one table, exercising every collected wrap."""
    page_one = (
        "4.5.  Synthetic Base AVPs\n"
        "\n"
        "   Due to space constraints, the short form DiamIdent is used to\n"
        "   represent DiameterIdentity.\n"
        "\n"
        + _HEADER_BOX
        + "   Acct-             85  9.8.2   Unsigned32 | M  |  V  |\n"
        "     Interim-Interval                       |    |     |\n"
        "   Class             25  8.20    OctetString| M  |  V  |\n"
        "   Error-Message    281  7.3     UTF8String |    | V,M |\n"
        "   -----------------------------------------|----+-----|\n"
        "\n"
        "\n" + _FOOTER.format(55) + "\n"
        "\f\n" + _RUNNING + "\n"
        "\n"
    )
    page_two = (
        _HEADER_BOX + "   Inband-Security                          | M  |  V  |\n"
        "      -Id           299  6.10    Unsigned32 |    |     |\n"
        "   Origin-Host      264  6.3     DiamIdent  | M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n"
        "\n" + _FOOTER.format(56) + "\n"
        "\f\n" + _RUNNING + "\n"
        "\n"
        "5.  After the Table\n"
        "\n"
        "   Prose that must not be read as rows.\n"
    )
    return _rfc(page_one + page_two)


@pytest.fixture
def synthetic_rfc(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_synthetic(), encoding="utf-8")
    return path


def test_extracts_the_avp_table(synthetic_rfc):
    spec = rfc_text.extract(synthetic_rfc, link="https://example.com/rfc9999.txt")

    assert spec.specification == "RFC 9999"
    assert spec.version is None
    assert spec.vendor_id == 0
    (table,) = spec.sections
    assert isinstance(table, ast.AvpTable)
    assert table.table is None
    assert table.source.section == "4.5"
    assert table.source.page == 55
    assert table.columns == (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
        ast.AvpColumn.MUST,
        ast.AvpColumn.MUST_NOT,
    )
    assert [row.name for row in table.rows] == [
        "Acct-Interim-Interval",  # name wrapped onto a continuation line
        "Class",
        "Error-Message",
        "Inband-Security-Id",  # reversed wrap: data cells on the continuation
        "Origin-Host",
    ]
    by_name = {row.name: row for row in table.rows}
    assert by_name["Acct-Interim-Interval"].code == 85
    assert by_name["Inband-Security-Id"].code == 299
    assert by_name["Inband-Security-Id"].section == "6.10"
    # DiamIdent is the document's declared short form, not a typo.
    assert by_name["Origin-Host"].data_type == ast.DataType.DIAMETER_IDENTITY
    assert by_name["Class"].data_type == ast.DataType.OCTET_STRING
    assert by_name["Error-Message"].flag_rules.must == frozenset()
    assert by_name["Error-Message"].flag_rules.must_not == {
        ast.AvpFlag.MANDATORY,
        ast.AvpFlag.VENDOR,
    }


def test_output_round_trips(synthetic_rfc):
    text = formatter.format_spec(rfc_text.extract(synthetic_rfc))
    assert formatter.format_spec(parser.parse(text)) == text


def test_no_avp_table_is_an_error(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc("1.  Introduction\n\n   No tables here.\n"), encoding="utf-8")
    with pytest.raises(ExtractionError, match="no AVP table found"):
        rfc_text.extract(path)


def test_a_second_avp_table_is_an_error(tmp_path):
    chunk = (
        "4.5.  First\n\n"
        + _HEADER_BOX
        + "   Class             25  8.20    OctetString| M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n"
        "\n"
        "9.9.  Second\n\n"
        + _HEADER_BOX
        + "   Class             25  8.20    OctetString| M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc(chunk), encoding="utf-8")
    with pytest.raises(ExtractionError, match="more than one AVP table"):
        rfc_text.extract(path)


def test_an_unrecognized_header_spelling_is_an_error(tmp_path):
    body = _rfc(
        "4.5.  Odd Header\n\n"
        + _HEADER_BOX.replace("Data Type", "Val. Type")
        + "   Class             25  8.20    OctetString| M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ExtractionError, match="unrecognized AVP table header"):
        rfc_text.extract(path)


def test_a_wrapped_row_missing_its_data_cells_is_an_error(tmp_path):
    body = _rfc(
        "4.5.  Broken Row\n\n"
        + _HEADER_BOX
        + "   Acct-                                    | M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ExtractionError, match="incomplete AVP table row"):
        rfc_text.extract(path)


def test_an_unknown_data_type_is_an_error(tmp_path):
    body = _rfc(
        "4.5.  Typo\n\n"
        + _HEADER_BOX
        + "   Class             25  8.20    OctedString| M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ExtractionError, match="OctedString"):
        rfc_text.extract(path)


def test_input_patches_apply_to_content_lines(tmp_path, synthetic_rfc):
    """The typo above is the input-patch layer's job, scoped by section."""
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "RFC9999.toml").write_text(
        '[[patch]]\nfind = "OctetString"\nreplace = "UTF8String"\n'
        'section = "4.5"\nreason = "prove patches reach RFC lines"\n',
        encoding="utf-8",
    )

    spec = rfc_text.extract(synthetic_rfc, patches_dir=patches)

    (table,) = spec.sections
    assert isinstance(table, ast.AvpTable)
    by_name = {row.name: row for row in table.rows}
    assert by_name["Class"].data_type == ast.DataType.UTF8_STRING


def test_a_rotted_patch_fails_the_extraction(tmp_path, synthetic_rfc):
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "RFC9999.toml").write_text(
        '[[patch]]\nfind = "NoSuchText"\nreplace = "x"\nreason = "rotted"\n',
        encoding="utf-8",
    )
    with pytest.raises(ExtractionError, match="applied 0 times"):
        rfc_text.extract(synthetic_rfc, patches_dir=patches)
