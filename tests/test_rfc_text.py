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
    """Two page-broken chunks of one table, exercising every collected wrap,
    preceded by the definition forms an RFC prints around it: a command, the
    grammar's own example (which must not extract), grouped AVPs bare and
    angle-bracketed, and both enumerated-value layouts."""
    definitions = (
        "3.2.  Command Code Format Specification\n"
        "\n"
        "   Every Command Code defined MUST include a corresponding CCF\n"
        "   specification.  For example:\n"
        "\n"
        "   Example-Request ::= < Diameter Header: 9999999, REQ, PXY >\n"
        "                       { Origin-Host }\n"
        "                     * [ AVP ]\n"
        "\n"
        "5.3.1.  Synthetic-Exchange-Request\n"
        "\n"
        "   The Synthetic-Exchange-Request (SER), indicated by the Command Code\n"
        "   set to 257, is sent to exchange local capabilities.\n"
        "\n"
        "      Message Format\n"
        "\n"
        "         <SER> ::= < Diameter Header: 257, REQ >\n"
        "                   { Origin-Host }\n"
        "                1* { Host-IP-Address }\n"
        "\n" + _FOOTER.format(53) + "\n"
        "\f\n" + _RUNNING + "\n"
        "\n"
        "                   [ Origin-State-Id ]\n"
        "                 * [ AVP ]\n"
        "\n"
        "4.4.3.  Proxy-Info AVP\n"
        "\n"
        "   The Proxy-Info AVP (AVP Code 284) is of type Grouped.\n"
        "\n"
        "         Proxy-Info ::= < AVP Header: 284 >\n"
        "                        { Proxy-Host }\n"
        "                      * [ AVP ]\n"
        "\n"
        "4.4.4.  Failed-AVP AVP\n"
        "\n"
        "   AVP Format\n"
        "\n"
        "         <Failed-AVP> ::= < AVP Header: 279 >\n"
        "                       1* {AVP}\n"
        "\n"
        "4.4.5.  Disconnect-Cause AVP\n"
        "\n"
        "   The Disconnect-Cause AVP (AVP Code 273) is of type Enumerated.  The\n"
        "   following values are supported:\n"
        "\n"
        "      REBOOTING                         0\n"
        "         A scheduled reboot is imminent.\n"
        "\n"
        "      BUSY                              1\n"
        "         The peer's internal resources are constrained.\n"
        "\n"
        "4.4.6.  Load-Type AVP\n"
        "\n"
        "   The Load-Type AVP (AVP code 651) is of type Enumerated.\n"
        "\n"
        "   HOST 0  The load report is for a host.\n"
        "\n"
        "   PEER 1:  The load report is for a peer.\n"
        "\n"
        "4.4.7.  Extension-Type AVP\n"
        "\n"
        "   The following new report type is defined for the Extension-Type AVP\n"
        "   of [RFC9998]:\n"
        "\n"
        "   PEER_REPORT 2  The overload treatment should apply to the peer.\n"
        "\n" + _FOOTER.format(54) + "\n"
        "\f\n" + _RUNNING + "\n"
        "\n"
    )
    page_one = (
        definitions + "4.5.  Synthetic Base AVPs\n"
        "\n"
        "   Due to space constraints, the short form DiamIdent is used to\n"
        "   represent DiameterIdentity.\n"
        "\n"
        + _HEADER_BOX
        + "   Acct-             85  9.8.2   Unsigned32 | M  |  V  |\n"
        "     Interim-Interval                       |    |     |\n"
        "   Disconnect-Cause 273  4.4.5   Enumerated | M  |  V  |\n"
        "   Load-Type        651  4.4.6   Enumerated | M  |  V  |\n"
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
    (table,) = [s for s in spec.sections if isinstance(s, ast.AvpTable)]
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
        "Disconnect-Cause",
        "Load-Type",
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


def test_extracts_later_rfc_fully_boxed_value_type_table(tmp_path):
    body = _rfc(
        "7.8.  AVP Flag Rules\n\n"
        "                                      +---------+\n"
        "                                      |AVP flag |\n"
        "                                      |rules    |\n"
        "                                      +----+----+\n"
        "           AVP   Section              |    |MUST|\n"
        "    Attribute Name Code Defined Value Type |MUST| NOT|\n"
        "   +----------------- -----------------+----+----+\n"
        "   |OC-Reduction                       |    |    |\n"
        "   |  -Percentage 627 7.7 Unsigned32   |    | V  |\n"
        "   +-----------------------------------+----+----+\n"
        "\n"
        "8.  After the Table\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")

    spec = rfc_text.extract(path)

    (table,) = spec.sections
    assert isinstance(table, ast.AvpTable)
    assert table.columns == (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
        ast.AvpColumn.MUST,
        ast.AvpColumn.MUST_NOT,
    )
    (row,) = table.rows
    assert row.name == "OC-Reduction-Percentage"
    assert row.code == 627
    assert row.section == "7.7"
    assert row.data_type == ast.DataType.UNSIGNED32
    assert row.flag_rules.must_not == {ast.AvpFlag.VENDOR}


def test_extracts_command_titles_and_clause_indexed_avps_without_a_table(tmp_path):
    body = _rfc(
        "3.1.  Diameter-EAP-Request (DER) Command\n\n"
        "   <Diameter-EAP-Request> ::= < Diameter Header: 268, REQ, PXY >\n"
        "                              < Session-Id >\n"
        "                            * [ AVP ]\n\n"
        "4.1.  EAP-Payload AVP\n\n"
        "   The EAP-Payload AVP (AVP Code 462) is of type OctetString.\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")

    spec = rfc_text.extract(path)

    message, table = spec.sections
    assert isinstance(message, ast.Message)
    assert (message.name, message.abbreviation) == ("Diameter-EAP-Request", "DER")
    assert isinstance(table, ast.AvpTable)
    assert table.columns == (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
        ast.AvpColumn.TYPE,
    )
    assert table.rows == (
        ast.AvpTableRow(
            name="EAP-Payload",
            code=462,
            section="4.1",
            data_type=ast.DataType.OCTET_STRING,
        ),
    )


def test_extracts_an_iana_avp_allocation_table_without_flag_columns(tmp_path):
    body = _rfc(
        "10.1.  AVP Codes\n\n"
        "   +---------------------------------------------------------+\n"
        "   |                    AVP  Section                         |\n"
        "   | Attribute Name     Code Defined     Data Type           |\n"
        "   +---------------------------------------------------------+\n"
        "   |QoS-Resources       508  3.1         Grouped             |\n"
        "   +---------------------------------------------------------+\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")

    spec = rfc_text.extract(path)

    (table,) = spec.sections
    assert isinstance(table, ast.AvpTable)
    assert table.rows[0].name == "QoS-Resources"
    assert table.rows[0].code == 508


def test_indexes_radius_attributes_with_diameter_compatible_codes(tmp_path):
    body = _rfc(
        "3.1.  Digest-Realm Attribute\n\n   Type\n         104 for Digest-Realm\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")

    spec = rfc_text.extract(path)

    (table,) = spec.sections
    assert isinstance(table, ast.AvpTable)
    assert table.columns == (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.SECTION,
    )
    assert table.rows[0].name == "Digest-Realm"
    assert table.rows[0].code == 104


def test_extracts_the_command(synthetic_rfc):
    """Name from the heading, abbreviation from the rule — the reverse of a
    3GPP heading — and a body read across a page break."""
    spec = rfc_text.extract(synthetic_rfc)

    (message,) = [s for s in spec.sections if isinstance(s, ast.Message)]
    assert message.name == "Synthetic-Exchange-Request"
    assert message.abbreviation == "SER"
    assert message.source.section == "5.3.1"
    assert message.source.page == 53
    assert message.command_code == 257
    assert message.flags == {ast.CommandFlag.REQUEST}
    assert message.application_id is None  # the base protocol prints none
    assert [(rule.name, rule.presence) for rule in message.avps] == [
        ("Origin-Host", ast.Presence.REQUIRED),
        ("Host-IP-Address", ast.Presence.REQUIRED),
        ("Origin-State-Id", ast.Presence.OPTIONAL),  # after the page break
        ("AVP", ast.Presence.OPTIONAL),
    ]
    assert message.avps[1].min_occurs == 1 and message.avps[1].max_occurs is None
    # The CCF grammar's own Example-Request must not become a command: its
    # section is titled with prose, which no definition heading is.
    assert spec.sections[0] is message


def test_extracts_grouped_avps(synthetic_rfc):
    spec = rfc_text.extract(synthetic_rfc)

    grouped = {s.name: s for s in spec.sections if isinstance(s, ast.GroupedAvp)}
    assert set(grouped) == {"Proxy-Info", "Failed-AVP"}
    proxy = grouped["Proxy-Info"]
    assert proxy.code == 284
    assert proxy.vendor_id is None
    assert proxy.source.section == "4.4.3"
    assert [rule.name for rule in proxy.avps] == ["Proxy-Host", "AVP"]
    # `<Failed-AVP> ::=` spells the rule name angle-bracketed, and its one
    # body line `1* {AVP}` without inner spaces.
    failed = grouped["Failed-AVP"]
    assert failed.code == 279
    (rule,) = failed.avps
    assert (rule.name, rule.min_occurs, rule.max_occurs) == ("AVP", 1, None)


def test_extracts_enumerated_avps_in_both_layouts(synthetic_rfc):
    warnings: list[str] = []
    spec = rfc_text.extract(synthetic_rfc, warnings=warnings)

    enums = {s.name: s for s in spec.sections if isinstance(s, ast.EnumeratedAvp)}
    assert set(enums) == {"Disconnect-Cause", "Load-Type"}
    # RFC 6733 layout: the value alone on its line, description indented below.
    disconnect = enums["Disconnect-Cause"]
    assert disconnect.code == 273  # from the AVP table, as in the docx extractor
    assert disconnect.vendor_id is None
    assert disconnect.values == (
        ast.EnumValue(name="REBOOTING", value=0),
        ast.EnumValue(name="BUSY", value=1),
    )
    # RFC 7944/8583 layout: the description starts on the value's own line.
    assert enums["Load-Type"].values == (
        ast.EnumValue(name="HOST", value=0),
        ast.EnumValue(name="PEER", value=1),
    )
    # A value list for an AVP the local table does not type as Enumerated —
    # an extension to another RFC's enum — is dropped with a warning.
    assert any("Extension-Type" in warning for warning in warnings)


def test_output_round_trips(synthetic_rfc):
    text = formatter.format_spec(rfc_text.extract(synthetic_rfc))
    assert formatter.format_spec(parser.parse(text)) == text


def test_an_rfc_without_an_avp_table_can_still_be_a_corpus_node(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc("1.  Introduction\n\n   No tables here.\n"), encoding="utf-8")
    spec = rfc_text.extract(path)
    assert spec.sections == ()


def test_extracts_multiple_avp_tables(tmp_path):
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
    spec = rfc_text.extract(path)
    tables = [section for section in spec.sections if isinstance(section, ast.AvpTable)]
    assert [table.source.section for table in tables] == ["4.5", "9.9"]


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

    (table,) = [s for s in spec.sections if isinstance(s, ast.AvpTable)]
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
