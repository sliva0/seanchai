import pytest
from conftest import _corpus

from seanchai.dad import ast, formatter, parser


@pytest.mark.parametrize(
    "path", _corpus(raw=True) + _corpus(raw=False), ids=lambda path: path.name
)
def test_every_committed_dad_file_round_trips_exactly(path):
    """A corrected file is canonical output *plus* `;;` notes, which the parser
    discards — so the invariant is against the file with its notes stripped."""
    text = path.read_text()
    # A deleted section's note is a block of its own, so blocks left with
    # nothing but notes go entirely; a trailing note leaves its line.
    blocks = []
    for block in text.split("\n\n\n"):
        lines = [
            line.split(" ;; ")[0]
            for line in block.splitlines()
            if not line.lstrip().startswith(";;")
        ]
        if lines:
            blocks.append("\n".join(lines))
    canonical = "\n\n\n".join(blocks).rstrip("\n") + "\n"
    spec = parser.parse(text)

    assert formatter.format_spec(spec) == canonical
    assert parser.parse(formatter.format_spec(spec)) == spec


def _spec(*sections):
    return ast.Specification(
        specification="Test", version="1", vendor_id=10415, sections=sections
    )


def _boundary_specs():
    """Shapes absent from the committed corpus, pinned by the round-trip invariant."""
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
        "enum-description-and-range": _spec(
            ast.EnumeratedAvp(
                name="Mode",
                source=source,
                code=1,
                values=(
                    ast.EnumValue(name="Short", value=1, description="first"),
                    ast.ReservedValues(first=2, last=4),
                    ast.EnumValue(name="Long-Name", value=200),
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
            vendor_id=10415,
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


class ExtendedMessage(ast.Message):
    extra: str = "lost"


_EXTENDED_MESSAGE = ExtendedMessage(
    name="Example-Request",
    abbreviation="EXR",
    source=ast.SourceRef(section="1"),
    command_code=1,
    flags=frozenset(),
    application_id=None,
    avps=(),
)


@pytest.mark.parametrize("section", [object(), _EXTENDED_MESSAGE])
def test_an_unregistered_section_type_fails_loudly(section):
    with pytest.raises(TypeError, match=f"no formatter for {type(section).__name__}"):
        formatter._format_section(section, {}, {})


def test_a_standing_note_for_a_last_row_deletion_prints_after_the_rows():
    # With no sibling left to stand before, the note is keyed by the table
    # and prints at the end of its lines — where the deleted row stood.
    table = ast.ReusedAvps(
        table="6.4",
        source=ast.SourceRef(section="6.4"),
        rows=(ast.ReusedAvpRow(name="Load", origin="RFC8583"),),
    )
    spec = _spec(table)

    note = "deleted: re-used AVPs row 'Doomed' (f.py:9)"
    annotated = formatter.format_spec(spec, standing={id(table): [note]})
    lines = annotated.splitlines()

    marker = lines.index(f";; {note}")
    assert lines[marker - 1].startswith("Load")
    assert marker == len(lines) - 1
