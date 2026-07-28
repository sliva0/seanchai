import pytest

from seanchai.dad import ast, parser


def _dad(*section_lines: str) -> str:
    header = "; Specification: Test Specification\n; Version: 1.2.3\n; Vendor-ID: 10415"
    body = "\n".join(section_lines)
    return f"{header}\n\n{body}\n"


def test_comments_are_ignored_without_changing_reported_line_numbers():
    text = "\n".join(
        [
            ";; file comment",
            "; Specification: Test Specification",
            ";; header comment",
            "; Version: 1.2.3",
            "; Vendor-ID: 10415",
            "",
            "; Type: Mystery",
        ]
    )

    with pytest.raises(parser.DadParseError, match="unknown section type") as exc_info:
        parser.parse(text)

    assert exc_info.value.lineno == 7


def test_trailing_comments_are_stripped_from_any_kind_of_line():
    plain = _dad(
        "; Type: Enumerated AVP",
        "; Name: Mode",
        "; Section: 6.3.2",
        "Mode ::= < Enumerated AVP header: 702 10415 >",
        "        Off = 0 ; stays off",
        "        On  = 1",
    )
    commented = _dad(
        "; Type: Enumerated AVP ;; even a directive line",
        "; Name: Mode",
        "; Section: 6.3.2",
        "Mode ::= < Enumerated AVP header: 702 10415 > ;; corrected: code",
        "        Off = 0 ; stays off ;; the description ends before the comment",
        "   ;; a comment-only line does not separate blocks",
        "        On  = 1 ;; note",
    )

    assert parser.parse(commented) == parser.parse(plain)


def test_parses_message_header_and_avp_rule_variants():
    spec = parser.parse(
        _dad(
            "; Type: Message",
            "; Name: Example-Request, EXR",
            "; Section: 4.2",
            "; Page: 17",
            "<Example-Request> ::= < Diameter Header: 321, REQ, ERR, 42 >",
            "        < Session-Id >",
            "      * [ Optional-AVP ]",
            "    2*5 { Bounded-AVP } ; bold",
            "     3* { At-Least-Three }",
        )
    )

    message = spec.sections[0]
    assert isinstance(message, ast.Message)
    assert message.name == "Example-Request"
    assert message.abbreviation == "EXR"
    assert message.source == ast.SourceRef(section="4.2", page=17)
    assert message.command_code == 321
    assert message.flags == {ast.CommandFlag.REQUEST, ast.CommandFlag.ERROR}
    assert message.application_id == 42
    assert [
        (
            rule.name,
            rule.presence,
            rule.min_occurs,
            rule.max_occurs,
            rule.bold,
        )
        for rule in message.avps
    ] == [
        ("Session-Id", ast.Presence.FIXED, 1, 1, False),
        ("Optional-AVP", ast.Presence.OPTIONAL, 0, None, False),
        ("Bounded-AVP", ast.Presence.REQUIRED, 2, 5, True),
        ("At-Least-Three", ast.Presence.REQUIRED, 3, None, False),
    ]


def test_parses_grouped_avp_without_vendor_or_page():
    spec = parser.parse(
        _dad(
            "; Type: Grouped AVP",
            "; Name: Example-Group",
            "; Section: 5.1",
            "Example-Group ::= < AVP header: 99 >",
            "      * [ Child-AVP ]",
        )
    )

    grouped = spec.sections[0]
    assert isinstance(grouped, ast.GroupedAvp)
    assert grouped.code == 99
    assert grouped.vendor_id is None
    assert grouped.source.page is None
    assert grouped.avps[0].name == "Child-AVP"


def test_avp_names_can_preserve_a_published_underscore():
    spec = parser.parse(
        _dad(
            "; Type: Enumerated AVP",
            "; Name: GBA_U-Awareness-Indicator",
            "; Section: 6.3.1.8",
            "GBA_U-Awareness-Indicator ::= < Enumerated AVP header: 407 10415 >",
            "        NO  = 0",
            "        YES = 1",
        )
    )

    avp = spec.sections[0]
    assert isinstance(avp, ast.EnumeratedAvp)
    assert avp.name == "GBA_U-Awareness-Indicator"


def test_parses_message_with_omitted_application_id_and_trailing_comma():
    spec = parser.parse(
        _dad(
            "; Type: Message",
            "; Name: Example-Request, EXR",
            "; Section: 4.2",
            "<Example-Request> ::= < Diameter Header: 321, REQ, PXY, >",
        )
    )

    message = spec.sections[0]
    assert isinstance(message, ast.Message)
    assert message.flags == {
        ast.CommandFlag.REQUEST,
        ast.CommandFlag.PROXIABLE,
    }
    assert message.application_id is None


def test_parses_enumerated_values_descriptions_and_reserved_ranges():
    spec = parser.parse(
        _dad(
            "; Type: Enumerated AVP",
            "; Name: Example-Mode",
            "; Section: 5.2",
            "Example-Mode ::= < Enumerated AVP header: 100 10415 >",
            "        First_Value = 0 ; used by default",
            "      ; RESERVED = 1",
            "      ; RESERVED = 2-4",
            "        Last-Value = 5",
        )
    )

    enumerated = spec.sections[0]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.vendor_id == 10415
    assert enumerated.values == (
        ast.EnumValue(name="First_Value", value=0, description="used by default"),
        ast.ReservedValues(first=1, last=1),
        ast.ReservedValues(first=2, last=4),
        ast.EnumValue(name="Last-Value", value=5),
    )


def test_parses_avp_table_nulls_flags_and_encryption():
    spec = parser.parse(
        _dad(
            "; Type: AVP Table",
            "; Section: 6.1",
            "; Table: 6.1/1",
            "; Columns: Name Code Section Type Must May S.not M.not Encrypt",
            "Local-AVP 10 6.2 Unsigned32 M,V - - - Yes",
            "Remote-AVP - - OctetString - M - V No",
        )
    )

    table = spec.sections[0]
    assert isinstance(table, ast.AvpTable)
    local, remote = table.rows
    assert local.code == 10
    assert local.section == "6.2"
    assert local.flag_rules.must == {ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}
    assert local.flag_rules.should_not == frozenset()
    assert local.may_encrypt is True
    assert remote.code is None
    assert remote.section is None
    assert remote.flag_rules.may == {ast.AvpFlag.MANDATORY}
    assert remote.flag_rules.must_not == {ast.AvpFlag.VENDOR}
    assert remote.may_encrypt is False


def test_parses_reused_avp_m_bit_overrides():
    spec = parser.parse(
        _dad(
            "; Type: Reused AVPs",
            "; Section: 6.3",
            "; Table: 6.3/2",
            "; Columns: Name From M-bit",
            "Default-AVP RFC7683 -",
            "Required-AVP TS29.336 MUST",
            "Forbidden-AVP RFC7944 MUST-NOT",
        )
    )

    reused = spec.sections[0]
    assert isinstance(reused, ast.ReusedAvps)
    assert [row.m_bit for row in reused.rows] == [
        None,
        ast.MBitOverride.MUST,
        ast.MBitOverride.MUST_NOT,
    ]


@pytest.mark.parametrize(
    ("text", "lineno", "message"),
    [
        (
            "; Specification: Test \n; Version: 1.0\n; Vendor-ID: 0\n",
            1,
            "trailing whitespace",
        ),
        ("", 1, "empty file"),
        (
            "; Specification: Test\n; Specification: Again\n"
            "; Version: 1.0\n; Vendor-ID: 0\n",
            2,
            "duplicate directive 'Specification'",
        ),
        (
            _dad("; Type: Unsupported", "; Section: 1"),
            5,
            "unknown section type 'Unsupported'",
        ),
        (
            _dad(
                "; Type: Grouped AVP",
                "; Name: Directive-Name",
                "; Section: 1",
                "Rule-Name ::= < AVP header: 1 >",
            ),
            8,
            "Name directive 'Directive-Name' != rule name 'Rule-Name'",
        ),
        (
            _dad(
                "; Type: Message",
                "; Name: Directive-Name, DN",
                "; Section: 1",
                "<Rule-Name> ::= < Diameter Header: 1, REQ >",
            ),
            8,
            "Name directive 'Directive-Name' != rule name 'Rule-Name'",
        ),
        (
            _dad(
                "; Type: Grouped AVP",
                "; Name: Example",
                "; Section: 1",
                "Example ::= < AVP header: 1 >",
                "        [ Mismatched-AVP }",
            ),
            9,
            "mismatched brackets",
        ),
        (
            _dad(
                "; Type: Message",
                "; Name: Example, EX",
                "; Section: 1",
                "<Example> ::= < Diameter Header: 1, UNKNOWN >",
            ),
            8,
            "malformed Diameter flags",
        ),
        (
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Code Section Type Must May S.not M.not Encrypt",
                "too few columns",
            ),
            9,
            "expected 9 columns, got 3",
        ),
        (
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Code Section Type Must May S.not M.not Encrypt",
                "Example 1 1 Unsigned32 - - - - Maybe",
            ),
            9,
            "malformed Encrypt cell 'Maybe'",
        ),
        (
            _dad(
                "; Type: Reused AVPs",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name From M-bit",
                "Example RFC7683 SOMETIMES",
            ),
            9,
            "malformed M-bit cell 'SOMETIMES'",
        ),
        (
            _dad(
                "; Type: Enumerated AVP",
                "; Name: Example",
                "; Section: 1",
                "Example ::= < Enumerated AVP header: 1 >",
                "not = valid!",
            ),
            9,
            "malformed enum value",
        ),
        # Values that reach an `int()` or a model field rather than a regex
        # still have to report as parse errors with a line, not as whatever
        # the last layer happened to raise — and at the line holding the value,
        # not at the start of the block it belongs to.
        (
            _dad(
                "; Type: Grouped AVP",
                "; Name: Example",
                "; Section: 1",
                "; Page: eleven",
                "Example ::= < AVP header: 1 >",
            ),
            8,
            "Page must be a number, got 'eleven'",
        ),
        (
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Code Section Type Must May S.not M.not Encrypt",
                "Example twelve 1 Unsigned32 - - - - No",
            ),
            9,
            "Code cell must be a number, got 'twelve'",
        ),
        (
            _dad(
                "; Type: Grouped AVP",
                "; Name: Example",
                "; Section: 1",
                "; Page: 99999999999",
                "Example ::= < AVP header: 1 >",
            ),
            8,
            "page: Input should be less than",
        ),
        (
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Code Section Type Must May S.not M.not Encrypt",
                "Example 1 1.2.not-a-section Unsigned32 - - - - No",
            ),
            9,
            "section: String should match pattern",
        ),
        # A whole-section problem, unlike the rows above, so it stays anchored
        # on the block rather than on any one directive.
        (
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Code Section Type Must May S.not M.not Encrypt",
            ),
            5,
            "rows: Tuple should have at least 1 item",
        ),
    ],
)
def test_parse_errors_include_the_source_line(text, lineno, message):
    with pytest.raises(parser.DadParseError, match=message) as exc_info:
        parser.parse(text)

    assert exc_info.value.lineno == lineno


_COLUMNS = "; Columns: Name Code Section Type Must May S.not M.not Encrypt"


def test_parses_a_table_whose_columns_are_a_subset_in_source_order():
    """TS 29.273's AVP table has no Encrypt column, and RFC 6733 §4.5 has
    neither MAY nor SHOULD NOT. An absent column is not an empty one."""
    spec = parser.parse(
        _dad(
            "; Type: AVP Table",
            "; Section: 6.1",
            "; Table: 6.1/1",
            "; Columns: Name Code Type Must M.not",
            "Local-AVP 10 Unsigned32 M,V -",
        )
    )

    table = spec.sections[0]
    assert isinstance(table, ast.AvpTable)
    assert table.columns == (
        ast.AvpColumn.NAME,
        ast.AvpColumn.CODE,
        ast.AvpColumn.TYPE,
        ast.AvpColumn.MUST,
        ast.AvpColumn.MUST_NOT,
    )
    (row,) = table.rows
    # Absent columns, not empty cells: the table never spoke about either.
    assert row.may_encrypt is None
    assert row.section is None
    assert row.flag_rules.may == frozenset()


def test_an_unknown_column_is_rejected_with_the_ones_that_exist():
    """A source column the format does not model is dropped by the extractor,
    not carried under its own label, so a `.dad` file can only name modelled
    ones."""
    with pytest.raises(
        parser.DadParseError, match=r"unknown column 'Applicability'.*expected one of"
    ):
        parser.parse(
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Applicability",
                "Local-AVP Both",
            )
        )


def test_a_table_row_must_have_one_cell_per_declared_column():
    with pytest.raises(parser.DadParseError, match="expected 5 columns, got 6"):
        parser.parse(
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Code Type Must M.not",
                "Local-AVP 10 Unsigned32 M,V - -",
            )
        )


def test_a_data_type_outside_the_closed_set_is_rejected():
    """TS 29.272 table 7.3.1/1 printed "Enumerate" and TS 29.212's prints
    "Enumarated"; both are typos no free-text field would have caught."""
    with pytest.raises(parser.DadParseError, match="data_type"):
        parser.parse(
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                _COLUMNS,
                "Local-AVP 10 6.2 Enumerate M,V - - - Yes",
            )
        )


def test_parses_a_reused_table_without_an_m_bit_column():
    """TS 29.128, 29.173 and 29.336 print no M-bit column at all."""
    spec = parser.parse(
        _dad(
            "; Type: Reused AVPs",
            "; Section: 6.3",
            "; Table: 6.3/2",
            "; Columns: Name From",
            "Default-AVP RFC7683",
        )
    )

    reused = spec.sections[0]
    assert isinstance(reused, ast.ReusedAvps)
    assert reused.columns == (ast.ReusedColumn.NAME, ast.ReusedColumn.FROM)
    assert reused.rows[0].m_bit is None


def test_parses_a_version_less_header_and_a_label_less_avp_table():
    """An RFC `.dad`: an RFC number names one immutable document, so there is
    no `; Version:` line, and RFC 6733 §4.5 prints no table caption, so its
    AVP table carries no `; Table:` either."""
    spec = parser.parse(
        "; Specification: RFC 6733\n"
        "; Vendor-ID: 0\n"
        "\n"
        "; Type: AVP Table\n"
        "; Section: 4.5\n"
        "; Columns: Name Code Section Type Must M.not\n"
        "Session-Id 263 8.8 UTF8String M V\n"
    )

    assert spec.version is None
    table = spec.sections[0]
    assert isinstance(table, ast.AvpTable)
    assert table.table is None
    assert table.rows[0].name == "Session-Id"


def test_parses_a_bases_line_into_spec_refs():
    spec = parser.parse(
        "; Specification: 3GPP TS 29.329\n"
        "; Version: 18.0.0\n"
        "; Vendor-ID: 10415\n"
        "; Bases: RFC6733, TS29.229\n"
        "\n"
        "; Type: Grouped AVP\n"
        "; Name: Example\n"
        "; Section: 6.3.1\n"
        "Example ::= < AVP header: 700 10415 >\n"
    )

    assert spec.bases == ("RFC6733", "TS29.229")


def test_a_missing_bases_line_means_no_bases():
    spec = parser.parse(
        _dad("; Type: AVP Table", "; Section: 6.3", "; Columns: Name", "Example")
    )

    assert spec.bases == ()


def test_a_bases_entry_that_names_no_document_is_rejected_with_its_line():
    text = (
        "; Specification: 3GPP TS 29.329\n"
        "; Version: 18.0.0\n"
        "; Vendor-ID: 10415\n"
        "; Bases: RFC 6733\n"
        "\n"
        "; Type: AVP Table\n"
        "; Section: 6.3\n"
        "; Columns: Name\n"
        "Example\n"
    )

    with pytest.raises(parser.DadParseError, match="'RFC 6733'") as exc_info:
        parser.parse(text)

    assert exc_info.value.lineno == 4
