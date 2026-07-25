from pathlib import Path

import pytest

from seanchai.dad import ast, formatter, parser


@pytest.mark.parametrize(
    "path",
    sorted((Path(__file__).parent.parent / "examples").glob("*.dad")),
    ids=lambda path: path.name,
)
def test_committed_examples_round_trip_exactly(path):
    text = path.read_text()
    spec = parser.parse(text)
    assert formatter.format(spec) == text
    assert parser.parse(formatter.format(spec)) == spec


def test_formats_every_section_and_optional_field_canonically():
    spec = ast.Specification(
        specification="Test Specification",
        version="1.2.3",
        sections=(
            ast.Message(
                name="Example-Request",
                abbreviation="EXR",
                source=ast.SourceRef(section="1"),
                command_code=123,
                flags=frozenset({ast.CommandFlag.ERROR, ast.CommandFlag.REQUEST}),
                application_id=None,
                avps=(
                    ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),
                    ast.AvpRule(
                        name="Repeated",
                        presence=ast.Presence.OPTIONAL,
                        min_occurs=2,
                        max_occurs=4,
                        bold=True,
                    ),
                ),
            ),
            ast.GroupedAvp(
                name="Example-Group",
                source=ast.SourceRef(section="2", page=9),
                code=10,
                avps=(),
            ),
            ast.EnumeratedAvp(
                name="Example-Mode",
                source=ast.SourceRef(section="3"),
                code=11,
                vendor_id=10415,
                values=(
                    ast.EnumValue(name="Short", value=1, description="first"),
                    ast.ReservedValues(first=2, last=4),
                    ast.EnumValue(name="Long-Name", value=20),
                ),
            ),
            ast.AvpTable(
                table="4/1",
                source=ast.SourceRef(section="4"),
                rows=(
                    ast.AvpTableRow(
                        name="A",
                        code=None,
                        section=None,
                        data_type="Time",
                        flag_rules=ast.AvpFlagRules(
                            must=frozenset({ast.AvpFlag.VENDOR, ast.AvpFlag.MANDATORY})
                        ),
                        may_encrypt=True,
                    ),
                ),
            ),
            ast.ReusedAvps(
                table="4/2",
                source=ast.SourceRef(section="4"),
                rows=(
                    ast.ReusedAvpRow(
                        name="Other",
                        origin="RFC6733",
                        m_bit=ast.MBitOverride.MUST_NOT,
                    ),
                ),
            ),
        ),
    )

    text = formatter.format(spec)

    assert text.startswith(
        "; Specification: Test Specification\n; Version: 1.2.3\n\n\n"
    )
    assert "<Example-Request> ::= < Diameter Header: 123, REQ, ERR >" in text
    repeated_line = next(line for line in text.splitlines() if "Repeated" in line)
    assert repeated_line.lstrip().startswith("2*4 [ Repeated ]")
    assert repeated_line.endswith("; bold")
    assert "Example-Group ::= < AVP header: 10 >" in text
    assert "Example-Mode ::= < Enumerated AVP header: 11 10415 >" in text
    assert "      ; RESERVED  = 2-4" in text
    assert "A     -     -     Time   M,V" in text
    assert "Other   RFC6733   MUST-NOT" in text
    assert text.endswith("\n")
    assert parser.parse(text) == spec


def test_bold_markers_share_the_column_after_the_longest_rule():
    spec = ast.Specification(
        specification="Test",
        version="1",
        sections=(
            ast.GroupedAvp(
                name="Group",
                source=ast.SourceRef(section="1"),
                code=1,
                avps=(
                    ast.AvpRule(
                        name="Short",
                        presence=ast.Presence.OPTIONAL,
                        bold=True,
                    ),
                    ast.AvpRule(
                        name="A-Much-Longer-Name",
                        presence=ast.Presence.REQUIRED,
                        bold=True,
                    ),
                ),
            ),
        ),
    )

    bold_lines = [
        line for line in formatter.format(spec).splitlines() if line.endswith("; bold")
    ]

    assert len({line.index("; bold") for line in bold_lines}) == 1
    assert bold_lines[1].index("; bold") == len(bold_lines[1].removesuffix("; bold"))


def _group(name, section, avps):
    return ast.GroupedAvp(
        name=name, source=ast.SourceRef(section=section), code=1, avps=avps
    )


def test_a_long_rule_cannot_reflow_another_sections_bold_column():
    # The review workflow diffs re-extracted raw files against each other, so
    # adding one AVP must not rewrite every `; bold` line in the file.
    short = _group(
        "Group",
        "1",
        (ast.AvpRule(name="Short", presence=ast.Presence.OPTIONAL, bold=True),),
    )
    spec = ast.Specification(specification="Test", version="1", sections=(short,))
    grown = ast.Specification(
        specification="Test",
        version="1",
        sections=(
            short,
            _group(
                "Other",
                "2",
                (
                    ast.AvpRule(
                        name="A-Very-Much-Longer-Name",
                        presence=ast.Presence.REQUIRED,
                        bold=True,
                    ),
                ),
            ),
        ),
    )

    def first_section(spec):
        return formatter.format(spec).split("\n\n\n")[1].rstrip("\n")

    assert first_section(grown) == first_section(spec)


def test_enum_equals_signs_are_aligned_and_values_are_not_zero_padded():
    enum = ast.EnumeratedAvp(
        name="Mode",
        source=ast.SourceRef(section="1"),
        code=1,
        values=(
            ast.EnumValue(name="A", value=1, description="one"),
            ast.EnumValue(name="Long", value=200),
            ast.ReservedValues(first=3, last=3),
        ),
    )
    spec = ast.Specification(specification="Test", version="1", sections=(enum,))

    value_lines = formatter.format(spec).splitlines()[-3:]

    assert len({line.index("=") for line in value_lines}) == 1
    assert value_lines[0].rstrip().endswith("1   ; one")
    assert value_lines[1].endswith("200")
    assert value_lines[2].endswith("3")
