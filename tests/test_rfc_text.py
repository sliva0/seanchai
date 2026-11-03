"""RFC extraction smoke test, rejected shapes and quirk declarations."""

import pytest
from conftest import _CORPUS_DIR, _declare

from seanchai.dad import ast, formatter, parser
from seanchai.extractor import rfc_text, tgpp_docx
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
    """A header box and one AVP table for extraction and declaration checks."""
    return _rfc(
        "4.5.  Synthetic Base AVPs\n\n"
        + _HEADER_BOX
        + "   Class             25  8.20    OctetString| M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n"
    )


@pytest.fixture
def synthetic_rfc(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_synthetic(), encoding="utf-8")
    return path


def test_extracts_the_avp_table(synthetic_rfc):
    spec = rfc_text.extract(synthetic_rfc)
    assert parser.parse(formatter.format_spec(spec)) == spec


def test_the_extractors_never_mark_their_output_transcribed(
    synthetic_spec_docx, tmp_path
):
    """`; Transcribed:` is a person's statement about a file no extractor
    wrote; nothing either extractor produces, nor any raw file they
    committed, carries it."""
    rfc = tmp_path / "rfc9999.txt"
    rfc.write_text(_synthetic(), encoding="utf-8")
    extracted = [tgpp_docx.extract(synthetic_spec_docx), rfc_text.extract(rfc)]
    committed = [
        parser.parse(path.read_text(encoding="utf-8"))
        for tree in ("3gpp", "rfc")
        for path in sorted((_CORPUS_DIR / "raw" / tree).rglob("*.raw.dad"))
    ]

    assert committed
    assert all(spec.transcribed is None for spec in extracted + committed)
    assert all(
        "; Transcribed:" not in formatter.format_spec(spec) for spec in extracted
    )


def test_an_rfc_without_an_avp_table_can_still_be_a_corpus_node(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc("1.  Introduction\n\n   No tables here.\n"), encoding="utf-8")
    spec = rfc_text.extract(path)
    assert spec.sections == ()


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


_CODELESS_RFC = (
    "4.2.1.  Session AVPs\n"
    "\n"
    "                                            +-----------+\n"
    "                                            | AVP Flag |\n"
    "                                            |   Rules  |\n"
    "                                            |-----+-----+\n"
    "                                            |MUST | MUST|\n"
    "   Attribute Name          Section Defined  |     |  NOT|\n"
    "   -----------------------------------------|-----+-----|\n"
    "   NAS-Port                4.2.2            |  M  |  V  |\n"
    "   NAS-Port-Type           4.2.3            |  M  |  V  |\n"
    "   -----------------------------------------|-----+-----|\n"
    "\n"
    "4.2.2.  NAS-Port AVP\n"
    "\n"
    "   The NAS-Port AVP (AVP Code 5) is of type Unsigned32 and contains\n"
    "   the physical or virtual port number of the NAS.\n"
    "\n"
    "4.2.3.  NAS-Port-Type AVP\n"
    "\n"
    "   The NAS-Port-Type AVP (AVP Code 61) is of type Enumerated and\n"
    "   contains the type of the port.\n"
    "\n"
    "   The supported values are defined below:\n"
    "\n"
    "   ASYNC        0\n"
    "   SYNC         1\n"
)


def test_without_the_quirk_a_codeless_table_stays_codeless(tmp_path):
    """The rigid default: no declaration, no prose reading."""
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc(_CODELESS_RFC), encoding="utf-8")

    spec = rfc_text.extract(path)

    table = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    assert ast.AvpColumn.CODE not in table.columns
    assert all(row.code is None for row in table.rows)


def test_a_row_without_a_defining_sentence_is_a_warning(tmp_path):
    body = _CODELESS_RFC.replace(
        "   The NAS-Port AVP (AVP Code 5) is of type Unsigned32 and contains\n"
        "   the physical or virtual port number of the NAS.\n",
        "   Discussed elsewhere.\n",
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc(body), encoding="utf-8")
    sources = _declare(
        tmp_path,
        '[[quirk]]\nname = "prose-avp-codes"\nreason = "codes in prose"\n',
    )
    warnings: list[str] = []

    spec = rfc_text.extract(path, sources_dir=sources, warnings=warnings)

    table = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    by_name = {row.name: row for row in table.rows}
    assert by_name["NAS-Port"].code is None
    assert by_name["NAS-Port-Type"].code == 61
    assert any("no defining sentence" in warning for warning in warnings)


def test_a_declared_quirk_that_changes_nothing_fails_the_extraction(tmp_path):
    """The patch accounting contract, extended to quirks: a reading the
    source stopped needing must be loud, not silently ignored. This table
    prints its own Code column, so `prose-avp-codes` has nothing to do."""
    body = _rfc(
        "10.1.  AVP Codes\n\n"
        "   |Attribute Name      Code Defined     Data Type|\n"
        "   |QoS-Resources       508  3.1         Grouped  |\n"
    )
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")
    sources = _declare(
        tmp_path,
        '[[quirk]]\nname = "prose-avp-codes"\nreason = "codes in prose"\n',
    )

    with pytest.raises(ExtractionError, match="changed nothing"):
        rfc_text.extract(path, sources_dir=sources)


def test_an_unknown_quirk_name_fails_with_the_vocabulary(tmp_path, synthetic_rfc):
    sources = _declare(
        tmp_path,
        '[[quirk]]\nname = "prose-avp-codez"\nreason = "a typo"\n',
    )

    with pytest.raises(ExtractionError, match="clause-avp-table") as failure:
        rfc_text.extract(synthetic_rfc, sources_dir=sources)
    assert "prose-avp-codez" in str(failure.value)


def test_a_quirk_without_a_reason_cannot_be_declared(tmp_path, synthetic_rfc):
    sources = _declare(tmp_path, '[[quirk]]\nname = "prose-avp-codes"\n')

    with pytest.raises(ExtractionError, match="no `reason`"):
        rfc_text.extract(synthetic_rfc, sources_dir=sources)


_CATCHALL_ROW = "   Rest of the AVPs                          |    |     |\n"


@pytest.mark.parametrize(
    ("body", "quirk"),
    [
        (
            _rfc(
                "9.1.  Session AVPs\n\n"
                + _HEADER_BOX
                + "   Class             25  8.20    OctetString| M  |  V  |\n"
                + _CATCHALL_ROW
                + "   -----------------------------------------|----+-----|\n"
            ),
            "prose-catchall-row",
        ),
        (
            _rfc(
                "9.1.  Session AVPs\n\n"
                + _HEADER_BOX
                + "   MIP-Filter-      342  5.5     UTF8String | M  |  V  |\n"
                "   Rule\n"
                "   -----------------------------------------|----+-----|\n"
            ),
            "bare-name-continuation",
        ),
        (
            _rfc(
                "9.1.  Session AVPs\n\n"
                + _HEADER_BOX
                + "   Class             25  8.20    OctetString| M  |  V  |\n"
                "   ------------------------------------ ----|----+-----|\n"
            ),
            "ragged-separator",
        ),
        (_synthetic().replace("OctetString", "DiamIdent  "), "type-short-forms"),
    ],
    ids=[
        "prose-catchall-row",
        "bare-name-continuation",
        "ragged-separator",
        "type-short-forms",
    ],
)
def test_undeclared_rfc_shapes_are_rejected(tmp_path, body, quirk):
    path = tmp_path / "rfc9999.txt"
    path.write_text(body, encoding="utf-8")
    message = "flag cells" if quirk == "ragged-separator" else quirk
    with pytest.raises(ExtractionError, match=message):
        rfc_text.extract(path)


def _enumerated(clause: str) -> str:
    """The synthetic table typing `Prompt` Enumerated, and its clause."""
    return _rfc(
        "4.5.  Synthetic Base AVPs\n\n"
        + _HEADER_BOX
        + "   Prompt            76  5.3     Enumerated | M  |  V  |\n"
        "   -----------------------------------------|----+-----|\n\n"
        "5.3.  Prompt AVP\n\n"
        "   The Prompt AVP (AVP Code 76) is of type Enumerated.\n" + clause
    )


def test_a_clause_naming_two_value_sources_is_an_error(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(
        _enumerated(
            "   The supported values are listed in [RADIUSTypes].  The\n"
            "   complete list of defined values can be found in [RADIUS].\n"
        ),
        encoding="utf-8",
    )
    sources = _declare(
        tmp_path, '[[quirk]]\nname = "external-enum-values"\nreason = "x"\n'
    )

    with pytest.raises(ExtractionError, match="names 2 sources"):
        rfc_text.extract(path, sources_dir=sources)


def test_unread_value_lines_in_an_enumerated_clause_are_a_warning(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_enumerated("      0  No Echo\n      1  Echo\n"), encoding="utf-8")
    warnings: list[str] = []

    spec = rfc_text.extract(path, warnings=warnings)

    prompt = spec.sections[-1]
    assert isinstance(prompt, ast.EnumeratedAvp)
    assert prompt.values == (ast.EnumValue(name="Echo", value=1),)
    assert warnings == [
        "5.3: enumerated AVP 'Prompt': 1 value line(s) not read, first '0  No Echo'"
    ]


def test_a_mapping_table_row_that_does_not_read_is_an_error(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(
        _enumerated(
            "   Cause Value Name              |  RADIUS   | Diameter  |\n"
            "   ------------------------------|-----------+-----------+\n"
            "   User Request                  |     1     |   11      |\n"
            "   Lost Carrier                  |     2     |           |\n"
            "   ------------------------------|-----------+-----------+\n"
        ),
        encoding="utf-8",
    )
    sources = _declare(
        tmp_path, '[[quirk]]\nname = "cause-mapping-table"\nreason = "x"\n'
    )

    with pytest.raises(ExtractionError, match=r"5\.3: unreadable table row"):
        rfc_text.extract(path, sources_dir=sources)


def _registry(token: str) -> str:
    return (
        "9.5.  Namespaces\n\n"
        "   IANA has created a registry for use with the enumerated Prompt AVP.\n\n"
        "   Token                                        | Value    | Description\n"
        "   ---------------------------------------------+----------+------------\n"
        f"   {token:<45}| 1        | RFC 9999\n"
    )


def test_a_registry_value_its_clause_does_not_name_is_an_error(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(
        _enumerated("   This specification defines one value, ECHO.\n\n")
        + _registry("NO_ECHO"),
        encoding="utf-8",
    )
    sources = _declare(
        tmp_path, '[[quirk]]\nname = "registry-enum-values"\nreason = "x"\n'
    )

    with pytest.raises(ExtractionError, match="'NO_ECHO' is not named"):
        rfc_text.extract(path, sources_dir=sources)


# --- document shapes the corpus's later RFCs print ---------------------------


def _read(tmp_path, body: str, *quirks: str, warnings: list[str] | None = None):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc(body), encoding="utf-8")
    declarations = "".join(f'[[quirk]]\nname = "{q}"\nreason = "x"\n' for q in quirks)
    sources = _declare(tmp_path, declarations) if quirks else None
    return rfc_text.extract(path, sources_dir=sources, warnings=warnings)


def _of[T](spec: ast.Specification, kind: type[T]) -> list[T]:
    return [section for section in spec.sections if isinstance(section, kind)]


def test_a_six_letter_abbreviation_titles_a_command(tmp_path):
    """RFC 6738 clause 5.1's IKESKR."""
    spec = _read(
        tmp_path,
        "5.1.  IKEv2-SK-Request (IKESKR) Command\n\n"
        "      <IKEv2-SK-Request> ::= < Diameter Header: 329, REQ, PXY >\n"
        "                             < Session-Id >\n",
    )
    assert _of(spec, ast.Message)[0].abbreviation == "IKESKR"


def test_an_allocation_table_may_head_its_names_avp_name(tmp_path):
    """RFC 5624 clause 5.1."""
    spec = _read(
        tmp_path,
        "5.1.  AVP Codes\n\n"
        "   +-----------------------------------------------+\n"
        "   |                     AVP  Section              |\n"
        "   |AVP Name             Code Defined   Data Type  |\n"
        "   +-----------------------------------------------+\n"
        "   |Token-Rate           496  3.1.1     Float32    |\n"
        "   +-----------------------------------------------+\n",
    )
    row = _of(spec, ast.AvpTable)[0].rows[0]
    assert (row.name, row.code, row.section) == ("Token-Rate", 496, "3.1.1")


def test_a_defining_sentence_may_print_its_code_alone(tmp_path):
    """RFC 7075 clause 3.3: title "The Redirect-Realm AVP", sentence "(620)"."""
    spec = _read(
        tmp_path,
        "3.3.  The Redirect-Realm AVP\n\n"
        "   The Redirect-Realm AVP (620) is of type DiameterIdentity.  It says.\n",
        "clause-avp-table",
    )
    row = _of(spec, ast.AvpTable)[0].rows[0]
    assert (row.name, row.code) == ("Redirect-Realm", 620)
    assert row.data_type is ast.DataType.DIAMETER_IDENTITY


_FLUSH_TABLE = (
    "7.2.  Defined AVPs\n\n"
    "                                                  +-------------------+\n"
    "                                                  |    AVP Flag rules |\n"
    "   +----------------------------------------------|----+--------+-----+\n"
    "   |                       AVP  Section           |    |    SHLD| MUST|\n"
    "   | Attribute Name        Code Defined Data Type |MUST|     NOT|  NOT|\n"
    "   +----------------------------------------------+----+--------+-----+\n"
    "   |QoS-Authorization-Data 579    7.2  OctetString| M  |        |  V  |\n"
    "   |Bound-Auth-Session-    580    7.2  UTF8String | M  |        |  V  |\n"
    "   | Id                                           |    |        |     |\n"
    "   +----------------------------------------------+----+--------+-----+\n"
)
_LEGEND = (
    "   |M - Mandatory bit. An AVP with the M bit set and its value MUST   |\n"
    "   +------------------------------------------------------------------+\n"
)


def test_names_start_where_the_first_row_does_not_at_the_header_label(tmp_path):
    """RFC 5866 clause 7.2 and RFC 6736 print rows flush against the box, one
    column left of "Attribute Name", and a wrapped name at the label's column."""
    rows = _of(_read(tmp_path, _FLUSH_TABLE), ast.AvpTable)[0].rows
    assert [row.name for row in rows] == [
        "QoS-Authorization-Data",
        "Bound-Auth-Session-Id",
    ]


def test_a_boxed_legend_under_a_table_needs_its_quirk(tmp_path):
    with pytest.raises(ExtractionError, match="flag cells"):
        _read(tmp_path, _FLUSH_TABLE + _LEGEND)
    spec = _read(tmp_path, _FLUSH_TABLE + _LEGEND, "boxed-table-legend")
    assert len(_of(spec, ast.AvpTable)[0].rows) == 2


_CODES_TABLE = (
    "   +-----------------------+------+---------------+-------+\n"
    "   | Attribute Name        | AVP  | Reference     | Data- |\n"
    "   |                       | Code |               | Type  |\n"
    "   +-----------------------+------+---------------+-------+\n"
    "   | SIP-Server-URI        |  371 | Section 9.2   | UTF8S |\n"
    "   | SIP-Item-Number       |  378 | Section 9.5.2 | U32   |\n"
    "   +-----------------------+------+---------------+-------+\n"
    "\n"
    "                   Table 2: Defined AVPs\n"
    "\n"
)


def _flags_table(*names: str) -> str:
    return (
        "   +-----------------------+------+-----+-----+------+------+\n"
        "   | Attribute Name        | MUST | MAY | SHD | MUST | Encr |\n"
        "   |                       |      |     | NOT |  NOT |      |\n"
        "   +-----------------------+------+-----+-----+------+------+\n"
        + "".join(
            f"   | {name:<21} |   M  |  P  |     |   V  |   N  |\n" for name in names
        )
        + "   +-----------------------+------+-----+-----+------+------+\n"
    )


def test_a_flags_only_table_joins_the_table_before_it(tmp_path):
    """RFC 4740 tables 2 and 3, with table 2's abbreviated types."""
    body = (
        "9.  AVPs\n\n"
        + _CODES_TABLE
        + _flags_table("SIP-Item-Number", "SIP-Server-URI")
    )
    table = _of(
        _read(tmp_path, body, "split-avp-tables", "type-short-forms"), ast.AvpTable
    )
    assert len(table) == 1
    row = table[0].rows[1]
    assert (row.name, row.code, row.section) == ("SIP-Item-Number", 378, "9.5.2")
    assert row.data_type is ast.DataType.UNSIGNED32
    assert row.flag_rules.must == {ast.AvpFlag.MANDATORY}
    assert row.may_encrypt is False
    assert ast.AvpColumn.SHOULD_NOT in table[0].columns


def test_a_flags_only_table_needs_its_quirk(tmp_path):
    body = (
        "9.  AVPs\n\n"
        + _CODES_TABLE
        + _flags_table("SIP-Item-Number", "SIP-Server-URI")
    )
    with pytest.raises(ExtractionError, match="split-avp-tables"):
        _read(tmp_path, body, "type-short-forms")


def test_a_flags_only_table_must_name_what_the_table_before_it_does(tmp_path):
    body = "9.  AVPs\n\n" + _CODES_TABLE + _flags_table("SIP-Item-Number")
    with pytest.raises(ExtractionError, match="SIP-Server-URI"):
        _read(tmp_path, body, "split-avp-tables", "type-short-forms")


def test_type_abbreviations_need_their_quirk(tmp_path):
    body = "9.  AVPs\n\n" + _CODES_TABLE
    with pytest.raises(ExtractionError, match="type-short-forms"):
        _read(tmp_path, body)


def _reused_clause(table: str, origin: str = "[RFC4005]") -> str:
    return (
        "8.3.  Reused NASREQ AVPs\n\n"
        f"   The following table describes the AVPs reused from NASREQ {origin};\n"
        "   their AVP Code values and types.\n\n" + table
    )


_BOXED_TABLE = (
    "                                       +---------------------+\n"
    "                                       |    AVP Flag Rules   |\n"
    "   +------------------+------+---------|----+-----+----+-----|----+\n"
    "   |                  | AVP  |         |    |     |SHLD| MUST|    |\n"
    "   | Attribute Name   | Code |Value Type|MUST| MAY| NOT|  NOT|Encr|\n"
    "   |------------------|------|---------|----+-----+----+-----|----|\n"
    "   | Calling-Station- |  31  |UTF8String| M  |  P |    |  V  | Y  |\n"
    "   |   Id             |      |          |    |    |    |     |    |\n"
    "   +------------------+------+---------|----+-----+----+-----|----+\n"
)
_STACKED_TABLE = (
    "                                                  +---------+\n"
    "                                                  |  AVP    |\n"
    "                                                  |  Flag   |\n"
    "                                                  |  rules  |\n"
    "   +----------------------------------------------|-----+---+---------+\n"
    "   |                           AVP                |     |   |         |\n"
    "   | Attribute Name            Code     Data Type |MUST |MAY|   Encr  |\n"
    "   +----------------------------------------------+-----+---+---------+\n"
    "   |Logical-Access-ID          302     OctetString|   V | M |    Y    |\n"
    "   +----------------------------------------------+-----+---+---------+\n"
)


def test_a_table_boxing_every_column_reads_a_wrapped_name(tmp_path):
    """RFC 6736 table 2: the continuation is the line with its cells blank."""
    spec = _read(tmp_path, "8.3.  Some AVPs\n\n" + _BOXED_TABLE)
    row = _of(spec, ast.AvpTable)[0].rows[0]
    assert (row.name, row.code) == ("Calling-Station-Id", 31)
    assert row.data_type is ast.DataType.UTF8_STRING
    assert row.may_encrypt is True


def test_a_stacked_caption_opens_a_table_with_no_section_column(tmp_path):
    """RFC 6736 stacks "AVP", "Flag", "rules", so no line says "AVP Flag"."""
    spec = _read(tmp_path, "8.6.  Some AVPs\n\n" + _STACKED_TABLE)
    table = _of(spec, ast.AvpTable)[0]
    assert ast.AvpColumn.SECTION not in table.columns
    assert (table.rows[0].code, table.rows[0].section) == (302, None)


def test_an_occurrence_table_opens_no_avp_table(tmp_path):
    """RFC 6736's `| Attribute Name  NCR  NCA |`, and RFC 4005's bare one."""
    spec = _read(
        tmp_path,
        "9.  Occurrence\n\n"
        "   +---------------------------------------------+\n"
        "   | Attribute Name                  NCR    NCA  |\n"
        "   +---------------------------------------------+\n"
        "   | Session-Id                      1      1    |\n"
        "   +---------------------------------------------+\n",
    )
    assert not _of(spec, ast.AvpTable)


def test_a_table_under_a_reused_clause_is_a_reused_block(tmp_path):
    spec = _read(tmp_path, _reused_clause(_BOXED_TABLE), "reused-avp-tables")
    assert not _of(spec, ast.AvpTable)
    block = _of(spec, ast.ReusedAvps)[0]
    assert block.table == "8.3"
    row = block.rows[0]
    assert (row.name, row.origin, row.code) == ("Calling-Station-Id", "RFC4005", 31)
    assert row.data_type is ast.DataType.UTF8_STRING


def test_a_reused_clause_reads_a_publisher_tag_as_its_reference(tmp_path):
    body = _reused_clause(_STACKED_TABLE, "[ETSIES283034]")
    block = _of(_read(tmp_path, body, "reused-avp-tables"), ast.ReusedAvps)[0]
    assert block.rows[0].origin == "ETSI-ES283.034"


def test_a_reused_clause_naming_no_origin_is_an_error(tmp_path):
    body = "8.3.  Reused NASREQ AVPs\n\n   Nothing cited here.\n\n" + _BOXED_TABLE
    with pytest.raises(ExtractionError, match="names no origin"):
        _read(tmp_path, body, "reused-avp-tables")


_NOTED_TABLE = (
    "8.  AVP Flag Rules\n\n"
    "                                                 +---------+\n"
    "                                                 |AVP Flag |\n"
    "                                                 |  Rules  |\n"
    "                                                 +----+----+\n"
    "                       AVP  Section              |    |MUST|\n"
    "    Attribute Name     Code Defined   Value Type |MUST| NOT|\n"
    "   +---------------------------------------------+----+----+\n"
    "   |Key-Lifetime        584  Note 1   Integer64  |  M | V  |\n"
    "   +---------------------------------------------+----+----+\n"
    "   |Ni                  588  6.1.1    OctetString|  M | V  |\n"
    "   +---------------------------------------------+----+----+\n\n"
)


def test_a_row_citing_a_note_becomes_reused_under_its_quirk(tmp_path):
    """RFC 6738 clause 8. Without the quirk such a row is dropped, as RFC 5778's
    are: its AVP is not this document's."""
    note = "   Note 1: The Key and Key-Lifetime AVPs are defined in [RFC6734].\n"
    spec = _read(tmp_path, _NOTED_TABLE + note, "note-avp-origins")
    assert [row.name for row in _of(spec, ast.AvpTable)[0].rows] == ["Ni"]
    row = _of(spec, ast.ReusedAvps)[0].rows[0]
    assert (row.name, row.origin, row.code) == ("Key-Lifetime", "RFC6734", 584)
    assert row.data_type is ast.DataType.INTEGER64


def test_a_note_must_name_the_row_citing_it(tmp_path):
    note = "   Note 1: The Key AVP is defined in [RFC6734].\n"
    with pytest.raises(ExtractionError, match="does not name Key-Lifetime"):
        _read(tmp_path, _NOTED_TABLE + note, "note-avp-origins")


def _bulleted(*values: str) -> str:
    return (
        "9.  AVPs\n\n"
        + _CODES_TABLE.replace("SIP-Server-URI ", "Scheme         ")
        .replace("Section 9.2  ", "Section 9.1  ")
        .replace("UTF8S", "E    ")
        + "9.1.  Scheme AVP\n\n"
        + "".join(f"   {value}\n" for value in values)
    )


def test_bulleted_enum_values_keep_only_the_name_and_number(tmp_path):
    """RFC 4740 clause 9.5.1, whose description wraps onto "RFC 2617 [RFC2617]
    Section 3.2.1", which reads as a value but for the citation it is."""
    body = _bulleted(
        "o  DIGEST (0) to indicate HTTP Digest authentication as specified in",
        "   RFC 2617 [RFC2617] Section 3.2.1.  Derivative work is also",
        "o  NO_ASSIGNMENT (1)",
    )
    spec = _read(tmp_path, body, "type-short-forms", "bulleted-enum-values")
    values = _of(spec, ast.EnumeratedAvp)[0].values
    assert [(v.name, v.value) for v in values if isinstance(v, ast.EnumValue)] == [
        ("DIGEST", 0),
        ("NO_ASSIGNMENT", 1),
    ]


def test_bulleted_enum_values_need_their_quirk(tmp_path):
    spec = _read(tmp_path, _bulleted("o  DIGEST (0)"), "type-short-forms")
    assert not _of(spec, ast.EnumeratedAvp)


def test_prose_origins_read_every_wording_rfc_5779_uses(tmp_path):
    body = (
        "5.1.  MIP6-Agent-Info AVP\n\n"
        "   The MIP6-Agent-Info grouped AVP (AVP Code 486) is defined in\n"
        "   [RFC5447].\n\n"
        "5.3.  MIP6-Feature-Vector AVP\n\n"
        "   The MIP6-Feature-Vector AVP is originally defined in [RFC5447].\n\n"
        "5.8.  Service-Selection AVP\n\n"
        "   The Service-Selection AVP (AVP Code 493) is of type UTF8String and\n"
        "   carries an identifier.  This AVP is re-used from [RFC5778].\n"
    )
    spec = _read(tmp_path, body, "clause-avp-table", "prose-avp-origins")
    assert [(row.name, row.origin) for row in _of(spec, ast.ReusedAvps)[0].rows] == [
        ("MIP6-Agent-Info", "RFC5447"),
        ("MIP6-Feature-Vector", "RFC5447"),
        ("Service-Selection", "RFC5778"),
    ]


# --- where a rule's body ends ------------------------------------------------


def _ruled(*lines: str) -> str:
    return (
        "5.1.  Foo-Request (FOR) Command\n\n"
        "   <Foo-Request> ::= < Diameter Header: 268, REQ, PXY >\n"
        "                     < Session-Id >\n"
        + "".join(f"                     {line}\n" if line else "\n" for line in lines)
    )


@pytest.mark.parametrize("elided", ["…", "..."])
def test_an_elided_line_undeclared_fails_naming_its_quirk(tmp_path, elided):
    with pytest.raises(ExtractionError, match="`elided-members`"):
        _read(tmp_path, _ruled(elided, "* [ AVP ]"))


@pytest.mark.parametrize("elided", ["…", "..."])
def test_an_elided_line_declared_stays_a_comment_where_it_stood(tmp_path, elided):
    """RFC 5778 clause 5.1.1, where it took nine of DER's members out."""
    path = tmp_path / "rfc9999.txt"
    path.write_text(
        _rfc(_ruled(elided, "[ Later ]", elided, "* [ AVP ]", elided)), encoding="utf-8"
    )
    sources = _declare(tmp_path, '[[quirk]]\nname = "elided-members"\nreason = "x"\n')
    spec, comments = rfc_text.extract_with_comments(path, sources_dir=sources)
    message = _of(spec, ast.Message)[0]
    assert [rule.name for rule in message.avps] == ["Session-Id", "Later", "AVP"]
    assert formatter.format_spec(spec, comments).splitlines()[-6:] == [
        "        < Session-Id >",
        f";; {elided}",
        "        [ Later ]",
        f";; {elided}",
        "      * [ AVP ]",
        f";; {elided}",
    ]


def test_an_elided_line_declared_and_absent_fails_like_any_quirk(tmp_path):
    with pytest.raises(ExtractionError, match="elided-members"):
        _read(tmp_path, _ruled("* [ AVP ]"), "elided-members")


def test_a_line_that_is_no_member_fails_rather_than_ending_the_body(tmp_path):
    with pytest.raises(ExtractionError, match="is no ABNF member"):
        _read(tmp_path, _ruled("[ OC-OLR ] ]", "* [ AVP ]"))


def test_a_member_after_the_body_ended_fails(tmp_path):
    body = _ruled("[ First ]", "This sentence ends the body too soon.", "[ Later ]")
    with pytest.raises(ExtractionError, match="follows the end of"):
        _read(tmp_path, body)


def test_a_sentence_a_blank_line_or_the_next_rule_ends_a_body(tmp_path):
    for ending in (
        ("This sentence ends the body.",),
        ("", "Prose after a blank line ends it, as a word alone does:", "word"),
        ("<Bar> ::= < Diameter Header: 269, PXY >",),
    ):
        spec = _read(tmp_path, _ruled("* [ AVP ]", *ending))
        assert [r.name for r in _of(spec, ast.Message)[0].avps] == ["Session-Id", "AVP"]


def test_a_reference_tag_alone_on_a_line_is_no_member(tmp_path):
    spec = _read(
        tmp_path, _ruled("* [ AVP ]", "", "A wrapped citation of", "[RFC6733]")
    )
    assert len(_of(spec, ast.Message)[0].avps) == 2


def test_blank_lines_inside_a_body_are_page_break_residue(tmp_path):
    spec = _read(tmp_path, _ruled("[ First ]", "", "", "[ Later ]"))
    assert [r.name for r in _of(spec, ast.Message)[0].avps] == [
        "Session-Id",
        "First",
        "Later",
    ]


# --- a rule under a prose title ----------------------------------------------

_PROSE_TITLED = (
    "6.  QoS Capability Indication\n\n"
    "   QoS-Capability ::= < AVP Header: 578 >\n"
    "                    1*{ QoS-Profile-Template }\n"
    "                    * [ AVP ]\n\n"
)
_ALLOCATION = (
    "9.  IANA\n\n"
    "   +-----------------------------------------------+\n"
    "   | Attribute Name       Code Defined   Data Type |\n"
    "   +-----------------------------------------------+\n"
    "   | QoS-Capability       578  {}         Grouped   |\n"
    "   +-----------------------------------------------+\n"
)


def test_a_table_row_citing_its_clause_anchors_a_grouped_rule(tmp_path):
    """RFC 5777 clause 6; a prose title alone keeps illustrations out."""
    spec = _read(tmp_path, _PROSE_TITLED + _ALLOCATION.format("6"))
    grouped = _of(spec, ast.GroupedAvp)[0]
    assert (grouped.name, grouped.source.section) == ("QoS-Capability", "6")
    assert [rule.name for rule in grouped.avps] == ["QoS-Profile-Template", "AVP"]


def test_a_rule_under_a_prose_title_no_row_cites_is_an_illustration(tmp_path):
    spec = _read(tmp_path, _PROSE_TITLED + _ALLOCATION.format("7"))
    assert not _of(spec, ast.GroupedAvp)
