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


