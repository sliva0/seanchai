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


def test_void_values_parse_and_round_trip_in_one_spelling():
    # TS 29.214 clause 5.3.13 prints `Void (0)` and `Void (5)`.
    text = _dad(
        "; Type: Enumerated AVP",
        "; Name: Example-Mode",
        "; Section: 5.2",
        "Example-Mode ::= < Enumerated AVP header: 100 10415 >",
        "      ; VOID = 0",
        "        On   = 1",
        "      ; VOID = 5-7",
    )

    spec = parser.parse(text)

    (enumerated,) = spec.sections
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.values == (
        ast.VoidValues(first=0, last=0),
        ast.EnumValue(name="On", value=1),
        ast.VoidValues(first=5, last=7),
    )
    canonical = formatter.format_spec(spec)
    assert canonical.endswith(
        "      ; VOID = 0\n        On   = 1\n      ; VOID = 5-7\n"
    )
    assert parser.parse(canonical) == spec
    loose = text.replace("      ; VOID = 5-7", "  ; VOID   = 5-7")
    assert parser.parse(loose) == spec
    assert formatter.format_spec(parser.parse(loose)) == canonical


@pytest.mark.parametrize(
    "line",
    [
        "      ; VOID = 5..7",
        "      ; VOID = 5-7 ; withdrawn",
        "      ; VOID = 7-5",
        "      ; VOID",
    ],
)
def test_a_malformed_void_line_is_a_parse_error(line):
    with pytest.raises(parser.DadParseError, match="line 9:"):
        parser.parse(
            _dad(
                "; Type: Enumerated AVP",
                "; Name: Example",
                "; Section: 1",
                "Example ::= < Enumerated AVP header: 1 >",
                line,
            )
        )


def test_vendor_specific_ranges_parse_and_round_trip_in_one_spelling():
    # TS 32.299 clause 7.2.213 and oneM2M TS-0004 clause A.5.17 leave
    # 100-199 to vendors.
    text = _dad(
        "; Type: Enumerated AVP",
        "; Name: Example-Mode",
        "; Section: 5.2",
        "Example-Mode ::= < Enumerated AVP header: 100 10415 >",
        "        First           = 0",
        "      ; RESERVED        = 1-99",
        "      ; VENDOR-SPECIFIC = 100-199 ; Vendor specific SM services",
        "      ; VENDOR-SPECIFIC = 300",
    )

    spec = parser.parse(text)

    enumerated = spec.sections[0]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.values == (
        ast.EnumValue(name="First", value=0),
        ast.ReservedValues(first=1, last=99),
        ast.VendorSpecificValues(
            first=100, last=199, description="Vendor specific SM services"
        ),
        ast.VendorSpecificValues(first=300, last=300),
    )
    canonical = formatter.format_spec(spec)
    assert canonical.splitlines()[-4:] == text.splitlines()[-4:]
    assert parser.parse(canonical) == spec
    # Any spacing the grammar allows comes back in the formatter's one.
    loose = text.replace(
        "      ; VENDOR-SPECIFIC = 100-199 ;", "  ; VENDOR-SPECIFIC   = 100-199    ;"
    )
    assert parser.parse(loose) == spec
    assert formatter.format_spec(parser.parse(loose)) == canonical


@pytest.mark.parametrize(
    "line",
    [
        "      ; VENDOR-SPECIFIC = 100..199",
        "      ; VENDOR-SPECIFIC = 100-199 Vendor specific",
        "      ; VENDOR-SPECIFIC = 100-199 ; ",
        "      ; VENDOR SPECIFIC = 100-199",
        "      ; VENDOR-SPECIFIC = 199-100",
    ],
)
def test_a_malformed_vendor_specific_line_is_a_parse_error(line):
    with pytest.raises(parser.DadParseError, match="line 9:"):
        parser.parse(
            _dad(
                "; Type: Enumerated AVP",
                "; Name: Example",
                "; Section: 1",
                "Example ::= < Enumerated AVP header: 1 >",
                line,
            )
        )


def test_enum_value_names_that_are_no_identifier_are_quoted():
    # TS 32.299 clause 7.2.1B labels its values in words.
    spec = parser.parse(
        _dad(
            "; Type: Enumerated AVP",
            "; Name: Access-Transfer-Type",
            "; Section: 7.2.1B",
            "Access-Transfer-Type ::= < Enumerated AVP header: 2710 10415 >",
            '        "PS to CS Transfer" = 0 ; a description',
            "        Yes                 = 1",
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
            '        "PS to CS Transfer"                                   = 0',
            '        "VAS4SMS Short Message Virtual Private Network (VPN)" = 7 ; note',
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
    assert formatter.format_spec(spec) == text
    assert parser.parse(formatter.format_spec(spec)) == spec


def test_a_quoted_identifier_formats_bare():
    text = _dad(
        "; Type: Enumerated AVP",
        "; Name: Example",
        "; Section: 1",
        "Example ::= < Enumerated AVP header: 1 >",
        '        "Yes"     = 0',
        '        "Two  (2)" = 1',
    )

    spec = parser.parse(text)

    assert formatter.format_spec(spec).splitlines()[-2:] == [
        "        Yes        = 0",
        '        "Two  (2)" = 1',
    ]


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ('        "a\\"b" = 0', 'a"b'),
        ('        "a\\\\" = 0', "a\\"),
        ('        "\\"\\\\\\"" = 0', '"\\"'),
        # RFC 4005 clause 7.3, Tunnel-Medium-Type.
        (
            '        "802 (includes all 802 media plus Ethernet \\"canonical'
            ' format\\")" = 6',
            '802 (includes all 802 media plus Ethernet "canonical format")',
        ),
    ],
)
def test_a_quoted_name_escapes_a_double_quote_and_a_backslash(line, name):
    text = _dad(
        "; Type: Enumerated AVP",
        "; Name: Example",
        "; Section: 1",
        "Example ::= < Enumerated AVP header: 1 >",
        line,
    )

    spec = parser.parse(text)

    enumerated = spec.sections[0]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.values == (ast.EnumValue(name=name, value=int(line[-1])),)
    formatted = formatter.format_spec(spec)
    assert formatted.splitlines()[-1] == line
    assert parser.parse(formatted) == spec


@pytest.mark.parametrize(
    "line",
    [
        # Unquoted, a name of words is no value line: the quotes are what
        # say where it ends.
        "        PS to CS Transfer = 0",
        '        "Unclosed = 0',
        '        "" = 0',
        '        "Two "quotes"" = 0',
        # Only `\"` and `\\` are escapes: a lone backslash is no name
        # character, and a trailing one escapes the closing quote.
        '        "a\\b" = 0',
        '        "a\\" = 0',
        '        "\\" = 0',
    ],
)
def test_enum_value_names_that_are_no_identifier_must_be_quoted(line):
    text = _dad(
        "; Type: Enumerated AVP",
        "; Name: Example",
        "; Section: 1",
        "Example ::= < Enumerated AVP header: 1 >",
        line,
    )

    with pytest.raises(parser.DadParseError) as error:
        parser.parse(text)

    assert error.value.lineno == 9


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


def test_an_application_scope_round_trips_with_its_comments():
    # TS 29.212 clause 5.1 states Gx's id for the commands of clause 5.
    text = "\n".join(
        [
            "; Specification: 3GPP TS 29.212",
            "; Version: 18.2.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: Application Scope ;; read from the prose",
            "; Name: Gx",
            "; Section: 5.1",
            "; Page: 120",
            "; Application-ID: 16777238",
            "; Applies-To: 5.*, E.6.*",
            ";; after the block",
            "",
        ]
    )

    spec, comments = parser.parse_with_comments(text)

    (application,) = spec.sections
    assert isinstance(application, ast.ApplicationScope)
    assert application == ast.ApplicationScope(
        name="Gx",
        source=ast.SourceRef(section="5.1", page=120),
        application_id=16777238,
        applies_to=("5.*", "E.6.*"),
    )
    assert application.covers("5") and application.covers("5.6.2")
    assert application.covers("E.6")
    assert not application.covers("5a.6.2") and not application.covers("E.61")
    assert comments.trailing == {("sections", 0, "type"): ["read from the prose"]}
    assert comments.standing == {("sections", 0): ["after the block"]}
    assert formatter.format_spec(spec, comments) == text


@pytest.mark.parametrize(
    ("lines", "lineno", "message"),
    [
        (["; Application-ID: 16777238"], 5, "missing directive 'Applies-To'"),
        (
            ["; Application-ID: 99999999999", "; Applies-To: 5.*"],
            8,
            "Input should be less than",
        ),
        (["; Application-ID: 1", "; Applies-To: 5.*, 5.*"], 9, "names a clause twice"),
        # A bare clause is reserved for that clause alone.
        (
            ["; Application-ID: 1", "; Applies-To: 5.*, 6"],
            9,
            r"Applies-To entry '6' names no subclauses \(write '6\.\*'",
        ),
        (["; Application-ID: 1", "; Applies-To: 5-1.*"], 9, "should match pattern"),
        (["; Application-ID: 1", "; Scope: 5"], 5, "missing directive 'Applies-To'"),
        (
            [
                "; Application-ID: 1",
                "; Applies-To: 5.*",
                "<Gx> ::= < Diameter Header: 1 >",
            ],
            10,
            "unexpected content in application scope",
        ),
    ],
    ids=[
        "no-applies-to",
        "id-too-large",
        "repeated-clause",
        "bare-clause",
        "not-a-clause",
        "old-scope",
        "a-body",
    ],
)
def test_an_application_scope_rejects_with_the_line(lines, lineno, message):
    text = _dad("; Type: Application Scope", "; Name: Gx", "; Section: 5.1", *lines)

    with pytest.raises(parser.DadParseError, match=message) as error:
        parser.parse(text)

    assert error.value.lineno == lineno


def test_a_reprinted_avp_round_trips_with_its_glosses():
    # TS 29.109 clause 4.2 prints RFC 6733's rule, glossing what each member holds.
    text = "\n".join(
        [
            "; Specification: 3GPP TS 29.109",
            "; Version: 18.1.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: Reprinted AVP",
            "; Name: Vendor-Specific-Application-Id",
            "; Section: 4.2",
            "; Page: 15",
            "; From: RFC6733",
            "Vendor-Specific-Application-Id ::= < AVP header: 260 >",
            "     1* [ Vendor-Id ] ;; 3GPP is 10415",
            "     *1 { Auth-Application-Id } ;; 16777221",
            "",
        ]
    )

    spec, comments = parser.parse_with_comments(text)

    (reprint,) = spec.sections
    assert isinstance(reprint, ast.ReprintedAvp)
    assert (reprint.origin, reprint.code, reprint.vendor_id) == ("RFC6733", 260, None)
    assert [rule.name for rule in reprint.avps] == ["Vendor-Id", "Auth-Application-Id"]
    assert comments.trailing[("sections", 0, "avps", 0)] == ["3GPP is 10415"]
    assert formatter.format_spec(spec, comments) == text


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["; Section: 4.2", "X ::= < AVP header: 1 >"], "From"),
        (["; Section: 4.2", "; From: RFC 6733", "X ::= < AVP header: 1 >"], "origin"),
        (["; Section: 4.2", "; From: RFC6733", "Y ::= < AVP header: 1 >"], "!= rule"),
        (["; Section: 4.2", "; From: RFC6733"], "no body"),
    ],
    ids=["no-origin", "origin-no-reference", "another-rule", "no-rule"],
)
def test_a_reprinted_avp_rejects_with_the_line(lines, message):
    text = _dad("; Type: Reprinted AVP", "; Name: X", *lines)
    with pytest.raises(parser.DadParseError, match=message):
        parser.parse(text)


@pytest.mark.parametrize(
    ("page", "note"),
    [("53", '"a ProSe Query Code"'), (None, None)],
    ids=["page-and-note", "bare"],
)
def test_an_undefined_avp_round_trips_with_its_comments(page, note):
    # TS 29.345 clause 6.3.53 names ProSe-Query-Code, which nothing defines.
    text = "\n".join(
        [
            "; Specification: 3GPP TS 29.345",
            "; Version: 18.0.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: Undefined AVP ;; inserted",
            "; Name: ProSe-Query-Code",
            "; Section: 6.3.53",
            *([] if page is None else [f"; Page: {page}"]),
            *([] if note is None else [f"; Note: {note}"]),
            ";; after the block",
            "",
        ]
    )

    spec, comments = parser.parse_with_comments(text)

    (undefined,) = spec.sections
    assert undefined == ast.UndefinedAvp(
        name="ProSe-Query-Code",
        source=ast.SourceRef(section="6.3.53", page=None if page is None else 53),
        note=note,
    )
    assert comments.trailing == {("sections", 0, "type"): ["inserted"]}
    assert comments.standing == {("sections", 0): ["after the block"]}
    assert formatter.format_spec(spec, comments) == text


@pytest.mark.parametrize(
    ("lines", "lineno", "message"),
    [
        (
            ["; Name: X", "; Section: 1", "        [ X ]"],
            8,
            "unexpected content in undefined AVP",
        ),
        (["; Section: 1"], 5, "missing directive 'Name'"),
        (["; Name: AVP", "; Section: 1"], 6, "wildcard"),
        (["; Name: X", "; Section: 1", "; Values: 1"], 5, "unexpected directives"),
        (["; Name: X", "; Note: said"], 5, "missing directive 'Section'"),
    ],
    ids=["a-body", "no-name", "the-wildcard", "unknown-directive", "no-section"],
)
def test_an_undefined_avp_rejects_with_the_line(lines, lineno, message):
    text = _dad("; Type: Undefined AVP", *lines)

    with pytest.raises(parser.DadParseError, match=message) as error:
        parser.parse(text)

    assert error.value.lineno == lineno


def test_an_undefined_avp_note_cannot_hold_a_comment_start():
    with pytest.raises(pydantic.ValidationError, match="starts a comment"):
        ast.UndefinedAvp(name="X", source=ast.SourceRef(section="1"), note='"a ;; b"')


def test_a_registry_round_trips_rows_and_reservations_with_its_comments():
    # TS 29.230 table 7.1: a row citing three documents, a blank type and
    # document, and reservations with and without the documents they name.
    text = "\n".join(
        [
            "; Specification: 3GPP TS 29.230",
            "; Version: 18.6.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: Registry",
            "; Registry: AVP Codes",
            "; Section: 7.1",
            "; Table: 7.1",
            "; Page: 12",
            "; Columns: Code   Name                      Type          Defined-In",
            "100               3GPP-WLAN-APN-Id          OctetString   TS29.234",
            '; RESERVED 1..255 TS29.061,TS29.234 "compatibility (See \\"x\\")"',
            '; RESERVED 256..299 "future use" ;; a note',
            "308               APN-Id                    -             -",
            ";; standing",
            '519               "Media-Sub-Component AVP" Grouped       '
            "TS29.209,TS29.211,TS29.214",
            "; RESERVED 320..399",
            # A type outside the closed set, kept quoted as printed.
            '314               Charging-Characteristics  "Integer"     TS29.234',
            # A placeholder printed where the code goes, kept quoted.
            '"zz"              Sh-ee                     -             TS29.329',
            "",
        ]
    )

    spec, comments = parser.parse_with_comments(text)

    (registry,) = spec.sections
    assert isinstance(registry, ast.Registry)
    assert registry.registry is ast.RegistryKind.AVP_CODES
    assert registry.rows[1] == ast.RegistryReservation(
        first=1,
        last=255,
        defined_in=("TS29.061", "TS29.234"),
        purpose='compatibility (See "x")',
    )
    assert registry.rows[3] == ast.RegistryRow(code=308, name="APN-Id")
    assert registry.rows[4].defined_in == ("TS29.209", "TS29.211", "TS29.214")
    assert registry.rows[5] == ast.RegistryReservation(first=320, last=399)
    assert registry.rows[7] == ast.RegistryRow(
        printed_code="zz", name="Sh-ee", defined_in=("TS29.329",)
    )
    assert registry.rows[6] == ast.RegistryRow(
        code=314,
        name="Charging-Characteristics",
        printed_type="Integer",
        defined_in=("TS29.234",),
    )
    assert registry.allocations(519) == [registry.rows[4]]
    assert registry.reservations(299) == [registry.rows[2]]
    assert comments.trailing == {("sections", 0, "rows", 2): ["a note"]}
    assert comments.standing == {("sections", 0, "rows", 4): ["standing"]}
    formatted = formatter.format_spec(spec, comments)
    assert parser.parse_with_comments(formatted) == (spec, comments)
    assert formatter.format_spec(*parser.parse_with_comments(formatted)) == formatted


def test_a_registry_type_cell_is_a_data_type_bare_and_a_printed_token_quoted():
    text = _dad(
        "; Type: Registry",
        "; Registry: AVP Codes",
        "; Section: 7.1",
        "; Table: 7.1",
        "; Columns: Code Type",
        '1 "Grouped"',
        '2 "Integer"',
    )

    (registry,) = parser.parse(text).sections
    assert isinstance(registry, ast.Registry)
    grouped, integer = registry.rows
    assert isinstance(grouped, ast.RegistryRow)
    assert (grouped.data_type, grouped.printed_type) == (ast.DataType.GROUPED, None)
    assert integer == ast.RegistryRow(code=2, printed_type="Integer")
    formatted = formatter.format_spec(parser.parse(text)).splitlines()
    assert [line.split() for line in formatted[-2:]] == [
        ["1", "Grouped"],
        ["2", '"Integer"'],
    ]
    with pytest.raises(parser.DadParseError, match="unknown Diameter data type"):
        parser.parse(text.replace('"Integer"', "Integer"))


def test_an_avp_table_type_cell_is_a_data_type_bare_and_a_printed_token_quoted():
    """TS 29.234 table 10.1.1 types Charging-Characteristics "Integer"."""
    text = "\n".join(
        (
            "; Specification: 3GPP TS 29.234",
            "; Version: 11.2.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: AVP Table",
            "; Section: 10.1",
            "; Columns: Name Code Type",
            'Charging-Characteristics 314 "Integer"',
            'Charging-Data 304 "Grouped"',
            "",
        )
    )

    (table,) = parser.parse(text).sections
    assert isinstance(table, ast.AvpTable)
    integer, grouped = table.rows
    assert (integer.data_type, integer.printed_type) == (None, "Integer")
    assert (grouped.data_type, grouped.printed_type) == (ast.DataType.GROUPED, None)
    formatted = formatter.format_spec(parser.parse(text))
    assert [line.split() for line in formatted.splitlines()[-2:]] == [
        ["Charging-Characteristics", "314", '"Integer"'],
        ["Charging-Data", "304", "Grouped"],
    ]
    assert parser.parse(formatted) == parser.parse(text)
    with pytest.raises(parser.DadParseError, match="unknown Diameter data type"):
        parser.parse(text.replace('"Integer"', "Integer"))


def test_a_printed_type_needs_a_type_column_and_no_type_beside_it():
    row = ast.AvpTableRow(name="Charging-Characteristics", printed_type="Integer")
    with pytest.raises(pydantic.ValidationError, match="no Type column"):
        ast.AvpTable(
            columns=(ast.AvpColumn.NAME,),
            rows=(row,),
            source=ast.SourceRef(section="10.1"),
        )
    with pytest.raises(pydantic.ValidationError, match="naming no Diameter type"):
        ast.AvpTableRow(name="X", printed_type="Grouped")


@pytest.mark.parametrize(
    ("lines", "lineno", "message"),
    [
        (["; Columns: Code Name", "1 A"], 5, "missing directive 'Registry'"),
        (
            ["; Registry: Vendor IDs", "; Columns: Code Name", "1 A"],
            8,
            "unknown registry 'Vendor IDs'",
        ),
        (["; Registry: AVP Codes", "; Columns: Name", "A"], 9, "no Code column"),
        (
            ["; Registry: AVP Codes", "; Columns: Code Defined-In", "1 29.229"],
            10,
            "Defined-In entry '29.229' does not name a supported document",
        ),
        (
            ["; Registry: AVP Codes", "; Columns: Code Name", "1 Bad,Name"],
            10,
            "malformed Name cell",
        ),
        (
            ["; Registry: AVP Codes", "; Columns: Code Name", "; RESERVED 9..1"],
            10,
            "inverted",
        ),
        (
            ["; Registry: AVP Codes", "; Columns: Code Name", "; RESERVED 1-9"],
            10,
            "malformed reserved range",
        ),
        (
            ["; Registry: AVP Codes", "; Columns: Code Name", '; RESERVED 1..9 "a" b'],
            10,
            "malformed reserved range",
        ),
    ],
    ids=[
        "no-kind",
        "unknown-kind",
        "no-code",
        "bare-number",
        "comma-in-plain-name",
        "inverted",
        "enum-spelling",
        "purpose-first",
    ],
)
def test_a_registry_rejects_with_the_line(lines, lineno, message):
    text = _dad("; Type: Registry", "; Section: 7.1", "; Table: 7.1", *lines)

    with pytest.raises(parser.DadParseError, match=message) as error:
        parser.parse(text)

    assert error.value.lineno == lineno


@pytest.mark.parametrize(
    "name",
    [" Leading", "Trailing ", "Tab\tinside", "New\nline", "a ;; b"],
)
def test_enum_value_names_reject_what_quotes_cannot_hold(name):
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
            # `int()` would take `+1`; the grammar's `1*DIGIT` does not.
            _dad(
                "; Type: Application Scope",
                "; Name: Example",
                "; Section: 1",
                "; Application-ID: +1",
                "; Applies-To: 5.*",
            ),
            8,
            r"Application-ID must be a number, got '\+1'",
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
        parser.DadParseError, match=r"unknown column 'Comments'.*expected one of"
    ):
        parser.parse(
            _dad(
                "; Type: AVP Table",
                "; Section: 1",
                "; Table: 1",
                "; Columns: Name Comments",
                "Local-AVP prose",
            )
        )


def test_mark_cells_read_as_comma_separated_marks():
    """Marks are plain or quoted, as enum value names are; `-` is a printed
    dash and `""` a blank cell."""
    spec = parser.parse(
        _dad(
            "; Type: AVP Table",
            "; Section: 5.3.0",
            "; Table: 5.3.0.1",
            "; Columns: Name Code Acc-Type Applicability",
            'Local-AVP 1000 3GPP-EPS,"Non-3GPP-EPS (NOTE 11)" Both,Rel8',
            'Other-AVP 1001 "All (NOTE 5)" ""',
            'Odd-AVP 1002 "say \\"so\\"" -',
            "",
            "",
            "; Type: Reused AVPs",
            "; Section: 7.3",
            "; Table: 7.3.1",
            "; Columns: Name Code ACR ACA From",
            "3GPP2-BSID 9010 X - TS29.212",
        )
    )

    table, reused = spec.sections
    assert isinstance(table, ast.AvpTable)
    assert [row.marks for row in table.rows] == [
        {
            ast.MarkColumn.ACCESS_TYPES: ("3GPP-EPS", "Non-3GPP-EPS (NOTE 11)"),
            ast.MarkColumn.APPLICABILITY: ("Both", "Rel8"),
        },
        {ast.MarkColumn.ACCESS_TYPES: ("All (NOTE 5)",)},
        {
            ast.MarkColumn.ACCESS_TYPES: ('say "so"',),
            ast.MarkColumn.APPLICABILITY: (),
        },
    ]
    assert isinstance(reused, ast.ReusedAvps)
    assert reused.rows[0].code == 9010
    assert reused.rows[0].marks == {ast.MarkColumn.ACR: ("X",), ast.MarkColumn.ACA: ()}
    assert parser.parse(formatter.format_spec(spec)) == spec


@pytest.mark.parametrize(
    ("cell", "message"),
    [
        ("Both,,Rel8", "malformed Applicability cell"),
        ('Both,""', r"marks\.Applicability"),
        ("Both,-", r"marks\.Applicability"),
        ('"unclosed', "malformed table row"),
    ],
)
def test_a_malformed_mark_cell_is_rejected(cell, message):
    with pytest.raises(parser.DadParseError, match=f"line 9: {message}"):
        parser.parse(
            _dad(
                "; Type: AVP Table",
                "; Section: 5.3.0",
                "; Table: 5.3.0.1",
                "; Columns: Name Applicability",
                f"Local-AVP {cell}",
            )
        )


def test_a_vendor_id_column_states_each_rows_vendor():
    """oneM2M TS-0004 table A.4-1 prints each row's vendor, IETF, 3GPP and
    oneM2M rows in one table; `-` is a blank cell."""
    text = _dad(
        "; Type: AVP Table",
        "; Section: A.4",
        "; Table: A.4-1",
        "; Columns: Name                Vendor-ID   Code   Must   M.not",
        "Session-Id                    0           263    M      V",
        "Node-Id                       10415       2064   M,V    -",
        "Access-Network-Identifier     45687       1000   M      V",
        "Unstated                      -           1999   -      -",
    )
    spec = parser.parse(text)

    (table,) = spec.sections
    assert isinstance(table, ast.AvpTable)
    assert [row.vendor_id for row in table.rows] == [0, 10415, 45687, None]
    assert [row.stated_vendor(10415) for row in table.rows] == [0, 10415, 45687, None]
    canonical = formatter.format_spec(spec)
    assert parser.parse(canonical) == spec
    assert "\nAccess-Network-Identifier   45687       1000   M      V\n" in canonical
    with pytest.raises(parser.DadParseError, match="line 11: Vendor-ID cell must"):
        parser.parse(text.replace("45687", "oneM2M"))
    with pytest.raises(parser.DadParseError, match=r"line 11: .*vendor_id"):
        parser.parse(text.replace("45687", "4294967296"))


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


_TRANSCRIBED = (
    "; Specification: ETSI ES 283 034\n"
    "; Version: 2.2.0\n"
    "; Vendor-ID: 13019\n"
    "; Bases: RFC6733\n"
    "; Link: https://www.etsi.org/deliver/es.pdf\n"
    "; Transcribed: by hand from https://www.etsi.org/deliver/es.pdf\n"
)


def test_a_transcription_names_the_rendering_it_was_copied_from():
    spec = parser.parse(_TRANSCRIBED)

    assert str(spec.transcribed) == "https://www.etsi.org/deliver/es.pdf"
    assert formatter.format_spec(spec) == _TRANSCRIBED


def test_the_transcribed_directive_formats_after_the_link():
    lines = _TRANSCRIBED.splitlines()
    swapped = "\n".join([*lines[:4], lines[5], lines[4]]) + "\n"

    assert formatter.format_spec(parser.parse(swapped)) == _TRANSCRIBED


@pytest.mark.parametrize(
    "value",
    ["https://www.etsi.org/deliver/es.pdf", "by hand from es.pdf", "by hand from"],
)
def test_a_transcribed_directive_must_say_by_hand_from_a_url(value):
    text = _TRANSCRIBED.replace(
        "by hand from https://www.etsi.org/deliver/es.pdf", value
    )

    with pytest.raises(parser.DadParseError) as exc_info:
        parser.parse(text)

    assert exc_info.value.lineno == 6


def test_avp_rules_carry_bold_and_strikethrough_markers_in_that_order():
    spec = parser.parse(
        _dad(
            "; Type: Grouped AVP",
            "; Name: Group",
            "; Section: 1",
            "Group ::= < AVP header: 1 >",
            "        [ Struck ] ; strikethrough",
            "        [ Both ]   ; bold ; strikethrough",
        )
    )

    (grouped,) = spec.sections
    assert isinstance(grouped, ast.GroupedAvp)
    assert [(rule.bold, rule.strikethrough) for rule in grouped.avps] == [
        (False, True),
        (True, True),
    ]
    with pytest.raises(parser.DadParseError, match="malformed AVP rule"):
        parser.parse(
            _dad(
                "; Type: Grouped AVP",
                "; Name: Group",
                "; Section: 1",
                "Group ::= < AVP header: 1 >",
                "        [ Both ] ; strikethrough ; bold",
            )
        )


def test_a_commented_out_member_is_no_member_and_keeps_its_place():
    # TS 32.299 clause 6.2.2's ACR, behind `struck-rules-unused`.
    text = "\n".join(
        [
            "; Specification: 3GPP TS 32.299",
            "; Version: 18.0.0",
            "; Vendor-ID: 10415",
            "",
            "",
            "; Type: Message",
            "; Name: Accounting-Request, ACR",
            "; Section: 6.2.2",
            "<Accounting-Request> ::= < Diameter Header: 271, REQ, PXY >",
            "        < Session-Id >",
            ";;      [ Vendor-Specific-Application-Id ] ; strikethrough",
            "        [ User-Name ]",
            ";;      [ Accounting-Realtime-Required ]   ; strikethrough",
            "",
        ]
    )

    spec, comments = parser.parse_with_comments(text)

    (message,) = spec.sections
    assert isinstance(message, ast.Message)
    assert [rule.name for rule in message.avps] == ["Session-Id", "User-Name"]
    assert comments.standing == {
        ("sections", 0, "avps", 1): [
            "     [ Vendor-Specific-Application-Id ] ; strikethrough"
        ],
        ("sections", 0, "avps", 2): [
            "     [ Accounting-Realtime-Required ]   ; strikethrough"
        ],
    }
    assert formatter.format_spec(spec, comments) == text


_VALUE_TABLES = """\
; Specification: 3GPP TS 29.999
; Version: 1.2.3
; Vendor-ID: 10415


; Type: Value Table
; AVP: Experimental-Result-Code
; Kind: result-codes
; Section: 6.2
; Page: 17
DIAMETER_FIRST_REGISTRATION = 2001 ; 6.2.1.1
"DIAMETER_ERROR_DATA SYNC"  = 5105 ; 6.2.2.1
DIAMETER_LISTED             = 5999


; Type: Value Table
; AVP: ULR-Flags
; Kind: bits
; Section: 7.3.7
; Table: 7.3.7/1
; Page: 40
Single-Registration-Indication = 0
"S6a/S6d-Indicator"            = 1


; Type: Value Table
; AVP: Feature-List
; Kind: features
; Feature-List-ID: 1
; Application: S6a/S6d
; Section: 7.3.10.1
; Table: 7.3.10/1
SiFC          = 0  ; M
"SMS in MME"  = 10 ; "O (NOTE 1)"
Blank-Mark    = 11
"""


def test_value_tables_parse_with_their_directives_and_rows():
    spec = parser.parse(_VALUE_TABLES)
    codes, bits, features = [
        section for section in spec.sections if isinstance(section, ast.ValueTable)
    ]

    assert (codes.avp, codes.kind) == (
        "Experimental-Result-Code",
        ast.ValueKind.RESULT_CODES,
    )
    assert codes.table is None
    assert codes.source == ast.SourceRef(section="6.2", page=17)
    assert codes.rows[0] == ast.ValueRow(
        name="DIAMETER_FIRST_REGISTRATION", value=2001, section="6.2.1.1"
    )
    assert codes.rows[1].name == "DIAMETER_ERROR_DATA SYNC"
    assert codes.rows[2].section is None
    assert (bits.table, bits.kind) == ("7.3.7/1", ast.ValueKind.BITS)
    assert bits.rows[1] == ast.ValueRow(name="S6a/S6d-Indicator", value=1)
    assert (features.feature_list_id, features.application) == (1, "S6a/S6d")
    assert [row.mark for row in features.rows] == ["M", "O (NOTE 1)", None]


def test_a_re_used_block_a_clause_s_prose_states_has_no_table():
    text = """\
; Specification: 3GPP TS 29.999
; Version: 18.0.0
; Vendor-ID: 10415


; Type: Reused AVPs
; Section: 6.3.9
; Page: 21
; Columns: Name   From
Server-Name       TS29.229
"""
    spec = parser.parse(text)
    (block,) = spec.sections

    assert isinstance(block, ast.ReusedAvps)
    assert block.table is None
    assert block.source == ast.SourceRef(section="6.3.9", page=21)
    assert formatter.format_spec(spec) == text


def test_a_result_code_names_the_document_defining_it():
    text = """\
; Specification: 3GPP TS 29.999
; Version: 18.0.0
; Vendor-ID: 10415


; Type: Value Table
; AVP: Experimental-Result-Code
; Kind: result-codes
; Section: 7.4
DIAMETER_ERROR_USER_UNKNOWN = 5001 ; 7.4.3.2  from TS29.229
DIAMETER_ERROR_LOCAL        = 5002 ; 7.4.3.10
DIAMETER_USER_UNKNOWN       = 5030 ; from RFC8506
"""
    (codes,) = parser.parse(text).sections

    assert isinstance(codes, ast.ValueTable)
    assert [(row.section, row.origin) for row in codes.rows] == [
        ("7.4.3.2", "TS29.229"),
        ("7.4.3.10", None),
        (None, "RFC8506"),
    ]
    assert formatter.format_spec(parser.parse(text)) == text


def test_only_a_result_code_has_an_origin():
    with pytest.raises(pydantic.ValidationError, match="origin"):
        ast.ValueTable(
            avp="Some-Flags",
            kind=ast.ValueKind.BITS,
            source=ast.SourceRef(section="6.3.1"),
            rows=(ast.ValueRow(name="A", value=0, origin="TS29.229"),),
        )


@pytest.mark.parametrize(
    ("rows", "directives", "message"),
    [
        ("Name = x", "; AVP: A\n; Kind: bits", "malformed value row"),
        ("Name = 1 ; M", "; AVP: A\n; Kind: bits", "a bit takes no"),
        ("Name = 1 ; not a clause", "; AVP: A\n; Kind: result-codes", "section"),
        ("Name = 1 ; from", "; AVP: A\n; Kind: result-codes", "section"),
        ("Name = 1 ; 6.2 from TS 29.229", "; AVP: A\n; Kind: result-codes", "section"),
        ("Name = 1 ; 6.2 from Nowhere", "; AVP: A\n; Kind: result-codes", "pattern"),
        ("Name = 1 ; -", "; AVP: A\n; Kind: features", "no mark"),
        ("Name = 1", "; AVP: A\n; Kind: enum", "unknown kind"),
        ("Name = 1", "; Kind: bits", "missing directive 'AVP'"),
        ("Name = 1", "; AVP: A", "missing directive 'Kind'"),
        ("", "; AVP: A\n; Kind: bits", "rows"),
        (
            "Name = 1",
            "; AVP: A\n; Kind: bits\n; Application: Gx",
            "features table's",
        ),
        (
            "Name = 1",
            "; AVP: A\n; Kind: features\n; Feature-List-ID: x",
            "must be a number",
        ),
    ],
)
def test_malformed_value_tables_are_refused(rows, directives, message):
    text = (
        "; Specification: RFC 9999\n; Vendor-ID: 0\n\n\n; Type: Value Table\n"
        f"{directives}\n; Section: 1\n{rows}\n"
    )

    with pytest.raises(parser.DadParseError, match=message):
        parser.parse(text)
