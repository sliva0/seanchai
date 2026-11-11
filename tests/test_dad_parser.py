"""What the parser refuses, and the grammar no committed file exercises.
Every committed file parsing and round-tripping is `test_formatter.py`'s."""

import pytest

from seanchai.dad import ast, formatter, parser

_HEADER = "; Specification: 3GPP TS 29.999\n; Version: 19.0.0\n; Vendor-ID: 10415\n"


def _dad(*lines: str) -> str:
    """A file whose one section starts on line 5."""
    return _HEADER + "\n" + "\n".join(lines) + "\n"


_ROW_COLUMNS = "; Columns: Name Code Section Type Must May S.not M.not Encrypt"


def _table(*rows: str, columns: str = _ROW_COLUMNS) -> str:
    return _dad("; Type: AVP Table", "; Section: 6.3", "; Table: 6.3.1", columns, *rows)


def _enumerated(*values: str) -> str:
    return _dad(
        "; Type: Enumerated AVP",
        "; Name: Example",
        "; Section: 6.3.2",
        "Example ::= < Enumerated AVP header: 1 >",
        *values,
    )


def _grouped(*lines: str, name: str = "Example") -> str:
    return _dad("; Type: Grouped AVP", f"; Name: {name}", "; Section: 6.3.1", *lines)


_GX = ("; Type: Application Scope", "; Name: Gx", "; Section: 5.1")


@pytest.mark.parametrize(
    ("text", "lineno", "fact"),
    [
        pytest.param("", 1, "empty file", id="empty"),
        pytest.param(
            "; Specification: Test \n; Vendor-ID: 0\n",
            1,
            "trailing",
            id="trailing-space",
        ),
        pytest.param(
            "; Specification: A\n; Specification: B\n; Vendor-ID: 0\n",
            2,
            "duplicate directive 'Specification'",
            id="duplicate-directive",
        ),
        pytest.param(
            _HEADER + "; Bases: RFC 6733\n",
            4,
            "'RFC 6733'",
            id="bases-not-a-reference",
        ),
        pytest.param(
            _HEADER + "; Transcribed: https://www.etsi.org/deliver/es.pdf\n",
            4,
            "by hand from",
            id="transcribed-not-by-hand",
        ),
        pytest.param(
            _dad("; Type: Mystery", "; Section: 1"),
            5,
            "unknown section type 'Mystery'",
            id="unknown-section",
        ),
        pytest.param(
            _dad(*_GX, "; Application-ID: 16777238"),
            5,
            "missing directive 'Applies-To'",
            id="missing-directive",
        ),
        pytest.param(
            _dad("; Type: Undefined AVP", "; Name: X", "; Section: 1", "; Values: 1"),
            5,
            "unexpected directives",
            id="unexpected-directive",
        ),
        pytest.param(
            _dad("; Type: Undefined AVP", "; Name: X", "; Section: 1", "[ X ]"),
            8,
            "unexpected content in undefined AVP",
            id="unexpected-body",
        ),
        pytest.param(
            _dad(*_GX, "; Application-ID: 1", "; Applies-To: 5.*, 6"),
            9,
            "names no subclauses (write '6.*'",
            id="applies-to-a-bare-clause",
        ),
        pytest.param(
            _grouped("Other ::= < AVP header: 1 >"),
            8,
            "Name directive 'Example' != rule name 'Other'",
            id="name-not-the-rule",
        ),
        pytest.param(
            _dad(
                "; Type: Answer Message",
                "; Section: 7.2",
                "<answer-message> ::= < Diameter Header: code, ERR [PXY] >",
            ),
            7,
            "malformed answer-message rule",
            id="answer-message-as-printed",
        ),
        pytest.param(
            _dad(
                "; Type: Message",
                "; Name: Example, EX",
                "; Section: 1",
                "<Example> ::= < Diameter Header: 1, UNKNOWN >",
            ),
            8,
            "malformed Diameter flags",
            id="unknown-command-flag",
        ),
        pytest.param(
            _grouped("Example ::= < AVP header: 1 >", "[ Mismatched }"),
            9,
            "mismatched brackets",
            id="mismatched-brackets",
        ),
        pytest.param(
            _grouped(
                "Example ::= < AVP header: 1 >", "[ Both ] ; strikethrough ; bold"
            ),
            9,
            "malformed AVP rule",
            id="markers-out-of-order",
        ),
        pytest.param(_grouped(), 5, "no body", id="no-header-rule"),
        pytest.param(_enumerated("not = valid!"), 9, "malformed enum value", id="enum"),
        # Only `\"` and `\\` are escapes; a lone backslash is no name character.
        pytest.param(_enumerated('"a\\b" = 0'), 9, "malformed enum value", id="escape"),
        pytest.param(
            _table('Example "unclosed', columns="; Columns: Name Code"),
            9,
            "malformed table row",
            id="unclosed-quote",
        ),
        # TS 29.212's marks are comma-separated, with no empty mark between.
        pytest.param(
            _table("Example Both,,Rel8", columns="; Columns: Name Applicability"),
            9,
            "malformed Applicability cell",
            id="empty-mark",
        ),
        pytest.param(
            _table("too few columns"), 9, "expected 9 columns, got 3", id="cell-count"
        ),
        pytest.param(
            _table("Example 1 1 Unsigned32 - - - - Maybe"),
            9,
            "malformed Encrypt cell 'Maybe'",
            id="malformed-cell",
        ),
        pytest.param(
            _table("Example prose", columns="; Columns: Name Comments"),
            8,
            "unknown column 'Comments'",
            id="unknown-column",
        ),
        # TS 29.272 table 7.3.1/1 printed "Enumerate", a typo no free-text
        # field would have caught.
        pytest.param(
            _table("Example 10 6.2 Enumerate M,V - - - Yes"),
            9,
            "data_type",
            id="unknown-data-type",
        ),
        pytest.param(
            _table("Example twelve 1 Unsigned32 - - - - No"),
            9,
            "Code cell must be a number, got 'twelve'",
            id="not-a-number",
        ),
        pytest.param(
            _grouped("; Page: 99999999999", "Example ::= < AVP header: 1 >"),
            8,
            "page: Input should be less than",
            id="out-of-range",
        ),
        pytest.param(
            _table("Example 1 1.2.x Unsigned32 - - - - No"),
            9,
            "section: String should match pattern",
            id="not-a-clause",
        ),
        # A whole-section problem stays anchored on the block.
        pytest.param(_table(), 5, "at least 1 item", id="table-without-rows"),
        pytest.param(
            _dad(
                "; Type: Registry",
                "; Registry: AVP Codes",
                "; Section: 7",
                "; Table: 7.1",
                "; Columns: Code Name",
                "; RESERVED 1-9",
            ),
            10,
            "malformed reserved range",
            id="registry-reservation",
        ),
        pytest.param(
            _dad(
                "; Type: Value Table",
                "; AVP: ULR-Flags",
                "; Kind: bits",
                "; Section: 7.3.7",
                "Single-Registration-Indication = 0 ; M",
            ),
            9,
            "a bit takes no",
            id="value-row-tail",
        ),
    ],
)
def test_a_malformed_file_is_refused_at_its_line(text, lineno, fact):
    with pytest.raises(parser.DadParseError) as error:
        parser.parse(text)

    assert error.value.lineno == lineno
    assert fact in str(error.value)


# Constructs no committed file prints, in any spacing the grammar allows: the
# `ERR` flag and the widest numbers, a member both bold and struck, a quoted
# name or data type that is an identifier, the two escapes, and free text
# shaped like a directive.
_CORNERS = """\
; Specification: 3GPP TS 29.999
; Version: 19.0.0
; Vendor-ID: 4294967295


; Type: Message
; Name: Example-Answer, EXA
; Section: 6.1
; Page: 4294967295
<Example-Answer> ::= < Diameter Header: 16777215,  REQ, PXY, ERR,4294967295 >
  4294967295*4294967295  < Both >  ; bold   ; strikethrough


; Type: Enumerated AVP
; Name: Example-Mode
; Section: 6.3.1
Example-Mode ::= < Enumerated AVP header: 4294967295 4294967295 >
  "Yes" = 0
    "a \\"quoted\\" back\\\\slash"  = 1 ; ; Version: 9
  ; VENDOR-SPECIFIC   = 2-4294967295


; Type: AVP Table
; Section: 6.3
; Columns: Name Code Type
Example-Mode 4294967295 "Enumerated"


; Type: Registry
; Registry: AVP Codes
; Section: 7
; Table: 7.1
; Columns: Code Name Type
4294967295 Example-Mode "Enumerated"
"""

_CORNERS_CANONICAL = """\
; Specification: 3GPP TS 29.999
; Version: 19.0.0
; Vendor-ID: 4294967295


; Type: Message
; Name: Example-Answer, EXA
; Section: 6.1
; Page: 4294967295
<Example-Answer> ::= < Diameter Header: 16777215, REQ, PXY, ERR, 4294967295 >
4294967295*4294967295 < Both > ; bold ; strikethrough


; Type: Enumerated AVP
; Name: Example-Mode
; Section: 6.3.1
Example-Mode ::= < Enumerated AVP header: 4294967295 4294967295 >
        Yes                        = 0
        "a \\"quoted\\" back\\\\slash" = 1 ; ; Version: 9
      ; VENDOR-SPECIFIC            = 2-4294967295


; Type: AVP Table
; Section: 6.3
; Columns: Name   Code         Type
Example-Mode      4294967295   Enumerated


; Type: Registry
; Registry: AVP Codes
; Section: 7
; Table: 7.1
; Columns: Code   Name           Type
4294967295        Example-Mode   Enumerated
"""


def test_grammar_no_committed_file_uses_reads_back_canonical():
    spec = parser.parse(_CORNERS)

    message, enumerated, table, registry = spec.sections
    assert isinstance(message, ast.Message)
    assert ast.CommandFlag.ERROR in message.flags
    (rule,) = message.avps
    assert (rule.bold, rule.strikethrough) == (True, True)
    assert isinstance(enumerated, ast.EnumeratedAvp)
    names = [v.name for v in enumerated.values if isinstance(v, ast.EnumValue)]
    assert names == ["Yes", 'a "quoted" back\\slash']
    assert isinstance(table, ast.AvpTable) and isinstance(registry, ast.Registry)
    assert table.rows[0].data_type is ast.DataType.ENUMERATED
    (row,) = registry.rows
    assert isinstance(row, ast.RegistryRow)
    assert row.data_type is ast.DataType.ENUMERATED
    assert formatter.format_spec(spec) == _CORNERS_CANONICAL
    assert parser.parse(_CORNERS_CANONICAL) == spec


def test_a_file_may_be_its_header_alone():
    """An RFC can allocate command codes without defining an AVP."""
    text = "; Specification: RFC 9999\n; Vendor-ID: 0\n"

    assert formatter.format_spec(parser.parse(text)) == text


def test_the_layout_places_each_section_on_its_lines():
    """`parse_with_layout` ties the tree to the file: each section's lines,
    its directives as printed, each body line's item and each row's cells."""
    text = (
        "; Specification: 3GPP TS 29.900\n; Vendor-ID: 10415\n\n\n"
        "; Type: Message\n; Name: Thing-Request, TR ;; a note\n; Section: 6.1\n"
        "<Thing-Request> ::= < Diameter Header: 9, REQ >\n"
        "      1* { Thing }\n"
        ";;      [ Gone ] ; strikethrough\n\n\n"
        "; Type: Reused AVPs\n; Section: 6.3\n; Columns: Name   From   Applicability\n"
        'Thing   TS29.229   "All (NOTE 1)"\n'
    )

    spec, layout = parser.parse_with_layout(text)

    message, reused = layout.sections
    assert (message.first, message.last) == (5, 10)
    assert message.directives["Name"] == (6, "Thing-Request, TR")
    assert layout.paths[8] == ("sections", 0)
    assert layout.paths[9] == ("sections", 0, "avps", 0)
    assert 10 not in layout.paths
    assert (reused.first, reused.last) == (13, 16)
    line = text.splitlines()[15]
    assert [line[a:b] for a, b in layout.cells[16]] == [
        "Thing",
        "TS29.229",
        '"All (NOTE 1)"',
    ]
    assert parser.parse(text) == spec

    rule, qualifier = parser.avp_rule_line("      1* { Thing }") or (None, None)
    assert rule == ast.AvpRule(
        name="Thing", presence=ast.Presence.REQUIRED, max_occurs=None
    )
    assert qualifier == "1*"
    struck = parser.avp_rule_line("      [ Gone ] ; strikethrough")
    assert struck is not None and struck[0].strikethrough and struck[1] == ""
    assert parser.avp_rule_line("not a rule") is None
