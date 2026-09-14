import pytest

from seanchai.dad import ast, parser


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
