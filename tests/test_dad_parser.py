import pydantic
import pytest

from seanchai.dad import ast, formatter, parser


def _dad(*section_lines: str) -> str:
    header = "; Specification: Test Specification\n; Version: 1.2.3\n; Vendor-ID: 10415"
    body = "\n".join(section_lines)
    return f"{header}\n\n{body}\n"


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


def test_enum_value_names_may_hold_single_spaces():
    # TS 32.299 clause 7.2.1B labels its values in words.
    spec = parser.parse(
        _dad(
            "; Type: Enumerated AVP",
            "; Name: Access-Transfer-Type",
            "; Section: 7.2.1B",
            "Access-Transfer-Type ::= < Enumerated AVP header: 2710 10415 >",
            "        PS to CS Transfer = 0 ; a description",
            "        Yes               = 1",
        )
    )

    enumerated = spec.sections[0]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.values == (
        ast.EnumValue(name="PS to CS Transfer", value=0, description="a description"),
        ast.EnumValue(name="Yes", value=1),
    )


def test_enum_value_names_with_spaces_and_parentheses_round_trip():
    # TS 32.299 clauses 7.2.1B and 7.2.213.
    text = "\n".join(
        [
            "; Specification: 3GPP TS 32.299",
            "; Version: 18.0.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: Enumerated AVP",
            "; Name: SM-Service-Type",
            "; Section: 7.2.213",
            "SM-Service-Type ::= < Enumerated AVP header: 2029 10415 >",
            "        PS to CS Transfer                               = 0",
            "        VAS4SMS Short Message Virtual Private Network (VPN) = 7 ; note",
            "",
        ]
    )

    spec = parser.parse(text)

    enumerated = spec.sections[0]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert [
        value.name for value in enumerated.values if isinstance(value, ast.EnumValue)
    ] == [
        "PS to CS Transfer",
        "VAS4SMS Short Message Virtual Private Network (VPN)",
    ]
    assert formatter.format_spec(parser.parse(formatter.format_spec(spec))) == (
        formatter.format_spec(spec)
    )
    assert parser.parse(formatter.format_spec(spec)) == spec


def test_a_values_source_round_trips_after_the_page_with_or_without_values():
    # TS 29.272 clause 7.3.67 names TS 32.422 for Trace-Depth's values and
    # prints none; a `Supply` correction can add them under the citation.
    text = "\n".join(
        [
            "; Specification: 3GPP TS 29.272",
            "; Version: 18.7.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: Enumerated AVP",
            "; Name: Trace-Depth",
            "; Section: 7.3.67",
            "; Page: 130",
            "; Values: TS 32.422 [23] for Trace Depth",
            "Trace-Depth ::= < Enumerated AVP header: 1462 10415 >",
            "",
            "",
            "; Type: Enumerated AVP",
            "; Name: Job-Type",
            "; Section: 7.3.137",
            "; Values: TS 32.422 [23] for Job-Type",
            "Job-Type ::= < Enumerated AVP header: 1623 10415 >",
            "        Immediate_MDT_only = 0",
            "",
        ]
    )

    spec = parser.parse(text)

    trace_depth, job_type = spec.sections
    assert isinstance(trace_depth, ast.EnumeratedAvp)
    assert trace_depth.values_source == "TS 32.422 [23] for Trace Depth"
    assert trace_depth.values == ()
    assert isinstance(job_type, ast.EnumeratedAvp)
    assert job_type.values_source == "TS 32.422 [23] for Job-Type"
    assert formatter.format_spec(spec) == text


def test_a_values_source_is_free_text_and_reports_its_own_line():
    text = _dad(
        "; Type: Enumerated AVP",
        "; Name: Example-Mode",
        "; Section: 5.2",
        "; Values:  padded",
        "Example-Mode ::= < Enumerated AVP header: 100 10415 >",
    )

    with pytest.raises(parser.DadParseError, match="String should match") as error:
        parser.parse(text)

    assert error.value.lineno == 8


@pytest.mark.parametrize(
    "name", [" Leading", "Trailing ", "Doubled  space", "Tab\tinside", "(Leading"]
)
def test_enum_value_names_reject_other_whitespace(name):
    with pytest.raises(pydantic.ValidationError):
        ast.EnumValue(name=name, value=0)


@pytest.mark.parametrize(
    ("text", "lineno", "message"),
    [
        (
            "\n".join(
                [
                    ";; file comment",
                    "; Specification: Test Specification",
                    ";; header comment",
                    "; Version: 1.2.3",
                    "; Vendor-ID: 10415",
                    "",
                    "; Type: Mystery",
                ]
            ),
            7,
            "unknown section type",
        ),
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
