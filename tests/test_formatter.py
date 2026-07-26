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
    assert formatter.format_spec(spec) == text
    assert parser.parse(formatter.format_spec(spec)) == spec


def _spec(*sections):
    return ast.Specification(specification="Test", version="1", sections=sections)


def _boundary_specs():
    """Shapes the committed examples don't happen to contain. The round-trip
    invariant has to hold for the whole format, not just for what 29.229,
    29.272 and 29.329 print."""
    source = ast.SourceRef(section="1")
    return {
        "empty-file": _spec(),
        "message-without-avps": _spec(
            ast.Message(
                name="Bare-Request",
                abbreviation="BR",
                source=source,
                command_code=0,
                flags=frozenset(),
                application_id=0,
                avps=(),
            )
        ),
        "every-command-flag": _spec(
            ast.Message(
                name="Full-Request",
                abbreviation="FULL",
                source=source,
                command_code=2**24 - 1,
                flags=frozenset(ast.CommandFlag),
                application_id=2**32 - 1,
                avps=(),
            )
        ),
        "occurrence-extremes": _spec(
            ast.GroupedAvp(
                name="Group",
                source=source,
                code=1,
                avps=(
                    ast.AvpRule(
                        name="Unbounded",
                        presence=ast.Presence.OPTIONAL,
                        min_occurs=0,
                        max_occurs=None,
                    ),
                    ast.AvpRule(
                        name="Wide",
                        presence=ast.Presence.FIXED,
                        min_occurs=2**32 - 1,
                        max_occurs=2**32 - 1,
                    ),
                    ast.AvpRule(name="Bold", presence=ast.Presence.REQUIRED, bold=True),
                ),
            )
        ),
        "enum-with-only-reserved": _spec(
            ast.EnumeratedAvp(
                name="Mode",
                source=source,
                code=1,
                values=(ast.ReservedValues(first=0, last=2**32 - 1),),
            )
        ),
        # Inline free text at the edge of what the constraint allows: one
        # character, an internal run of spaces the formatter must not collapse,
        # and text shaped like a directive, which is only safe because it never
        # starts a line.
        "awkward-inline-text": ast.Specification(
            specification="X",
            version="1",
            sections=(
                ast.EnumeratedAvp(
                    name="Mode",
                    source=source,
                    code=1,
                    values=(
                        ast.EnumValue(name="A", value=0, description="x"),
                        ast.EnumValue(name="B", value=1, description="two  spaces"),
                        ast.EnumValue(name="C", value=2, description="; Version: 9"),
                    ),
                ),
            ),
        ),
        "long-names": _spec(
            ast.AvpTable(
                table="1/1",
                columns=tuple(ast.AvpColumn),
                source=ast.SourceRef(section="1.2.3A", page=2**32 - 1),
                rows=(
                    ast.AvpTableRow(
                        name="A-Very-Long-Attribute-Name-3GPP-Style",
                        code=None,
                        section=None,
                        data_type=ast.DataType.OCTET_STRING,
                        # The widest flag cell the columns can hold; the four
                        # rules are disjoint, so every flag it names is in one.
                        flag_rules=ast.AvpFlagRules(must=frozenset(ast.AvpFlag)),
                        may_encrypt=True,
                    ),
                ),
            )
        ),
    }


@pytest.mark.parametrize("spec", _boundary_specs().values(), ids=_boundary_specs())
def test_formatting_is_idempotent_and_survives_a_round_trip(spec):
    once = formatter.format_spec(spec)

    assert parser.parse(once) == spec
    assert formatter.format_spec(parser.parse(once)) == once


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
                columns=tuple(ast.AvpColumn),
                source=ast.SourceRef(section="4"),
                rows=(
                    ast.AvpTableRow(
                        name="A",
                        code=None,
                        section=None,
                        data_type=ast.DataType.TIME,
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

    text = formatter.format_spec(spec)

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
        line
        for line in formatter.format_spec(spec).splitlines()
        if line.endswith("; bold")
    ]

    assert len({line.index("; bold") for line in bold_lines}) == 1
    assert bold_lines[1].index("; bold") == len(bold_lines[1].removesuffix("; bold"))


def test_an_unregistered_section_type_fails_loudly():
    # A new section kind without a formatter must not slip through as a
    # silently missing block.
    with pytest.raises(TypeError, match="no formatter for object"):
        formatter._format_section(object())  # type: ignore


def test_a_subclass_is_not_formatted_as_its_base():
    # Dispatch is by exact type: anything that matched by isinstance would
    # format this as a plain Message, dropping `extra` without a word.
    class ExtendedMessage(ast.Message):
        extra: str = "lost"

    section = ExtendedMessage(
        name="Example-Request",
        abbreviation="EXR",
        source=ast.SourceRef(section="1"),
        command_code=1,
        flags=frozenset(),
        application_id=None,
        avps=(),
    )

    with pytest.raises(TypeError, match="no formatter for ExtendedMessage"):
        formatter._format_section(section)


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
        return formatter.format_spec(spec).split("\n\n\n")[1].rstrip("\n")

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

    value_lines = formatter.format_spec(spec).splitlines()[-3:]

    assert len({line.index("=") for line in value_lines}) == 1
    assert value_lines[0].rstrip().endswith("1   ; one")
    assert value_lines[1].endswith("200")
    assert value_lines[2].endswith("3")
