import pydantic
import pytest

from seanchai.dad import ast


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (ast.AvpRule, {"name": "-bad", "presence": ast.Presence.OPTIONAL}),
        (ast.SourceRef, {"section": "section 1"}),
        (ast.ReusedAvpRow, {"name": "Example", "origin": "TS 29.336"}),
        (
            ast.Message,
            {
                "name": "Example",
                "abbreviation": "X",
                "source": ast.SourceRef(section="1"),
                "command_code": 1,
                "flags": frozenset(),
                "application_id": None,
                "avps": (),
            },
        ),
        (
            ast.Message,
            {
                "name": "Example",
                "abbreviation": "EX",
                "source": ast.SourceRef(section="1"),
                "command_code": 2**24,
                "flags": frozenset(),
                "application_id": None,
                "avps": (),
            },
        ),
        (ast.EnumValue, {"name": "Example", "value": -1}),
    ],
)
def test_field_constraints_reject_invalid_values(model, kwargs):
    with pytest.raises(pydantic.ValidationError):
        model(**kwargs)


def test_reserved_range_must_be_ordered():
    with pytest.raises(
        pydantic.ValidationError, match="reserved range 5-2 is inverted"
    ):
        ast.ReservedValues(first=5, last=2)


def test_occurrence_range_must_be_ordered():
    with pytest.raises(pydantic.ValidationError, match=r"5\*2 is inverted"):
        ast.AvpRule(
            name="Example", presence=ast.Presence.OPTIONAL, min_occurs=5, max_occurs=2
        )

    # An unbounded maximum is not "less than" anything.
    ast.AvpRule(
        name="Example", presence=ast.Presence.OPTIONAL, min_occurs=5, max_occurs=None
    )


def test_the_four_avp_flag_rule_columns_must_be_disjoint():
    # A table saying a flag is both required and forbidden is a source or
    # extraction error; nothing downstream can resolve it.
    with pytest.raises(pydantic.ValidationError, match="both must and must_not"):
        ast.AvpFlagRules(
            must=frozenset({ast.AvpFlag.VENDOR}),
            must_not=frozenset({ast.AvpFlag.VENDOR}),
        )

    ast.AvpFlagRules(
        must=frozenset({ast.AvpFlag.VENDOR}), may=frozenset({ast.AvpFlag.MANDATORY})
    )


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (
            ast.Specification,
            {
                "specification": "3GPP TS 29.272\n; Version: 0.0.0",
                "version": "1.0",
                "sections": (),
            },
        ),
        (ast.EnumValue, {"name": "Example", "value": 1, "description": "one\ntwo"}),
        (
            ast.AvpTable,
            {
                "table": "6.3\n; Section: 9",
                "source": ast.SourceRef(section="1"),
                "rows": (
                    ast.AvpTableRow(
                        name="Example",
                        code=1,
                        section=None,
                        data_type="Unsigned32",
                        flag_rules=ast.AvpFlagRules(),
                        may_encrypt=False,
                    ),
                ),
            },
        ),
    ],
    ids=["specification", "enum-description", "table-label"],
)
def test_fields_written_onto_one_line_reject_embedded_newlines(model, kwargs):
    # The format is line-oriented: such a value formats to text that does not
    # parse back, and in a header it injects a second directive.
    with pytest.raises(pydantic.ValidationError):
        model(**kwargs)


@pytest.mark.parametrize(
    ("specification", "reference"),
    [
        ("3GPP TS 29.272", "TS29.272"),
        ("TS 29.329", "TS29.329"),
        ("RFC 6733", "RFC6733"),
    ],
)
def test_spec_ref_accepts_the_canonical_document_references(specification, reference):
    assert ast.spec_ref(specification) == reference


@pytest.mark.parametrize(
    "specification",
    ["3GPP TS ../outside", "/etc/passwd", r"..\outside", "TS 29.2721", "", "Test"],
)
def test_spec_ref_rejects_anything_that_could_name_another_file(specification):
    # The result becomes a file name in a directory whose Python gets executed.
    with pytest.raises(ast.SpecRefError):
        ast.spec_ref(specification)


def test_nodes_are_frozen_and_forbid_extra_fields():
    source = ast.SourceRef(section="1.2")

    # Both statements are rejected statically as well as at runtime; the whole
    # point of the test is that the runtime rejects them too.
    with pytest.raises(pydantic.ValidationError, match="frozen"):
        source.section = "2.1"  # type: ignore
    with pytest.raises(pydantic.ValidationError, match="Extra inputs"):
        ast.SourceRef(section="1.2", unknown=True)  # type: ignore


def test_json_round_trip_preserves_discriminated_section_types():
    spec = ast.Specification(
        specification="Test",
        version="1.0",
        sections=(
            ast.Message(
                name="Example-Request",
                abbreviation="EXR",
                source=ast.SourceRef(section="1"),
                command_code=123,
                flags=frozenset({ast.CommandFlag.REQUEST}),
                application_id=42,
                avps=(
                    ast.AvpRule(
                        name="Session-Id", presence=ast.Presence.FIXED, bold=True
                    ),
                ),
            ),
            ast.EnumeratedAvp(
                name="Example-Mode",
                source=ast.SourceRef(section="2"),
                code=7,
                values=(ast.EnumValue(name="Enabled", value=1),),
            ),
        ),
    )

    restored = ast.Specification.model_validate_json(spec.model_dump_json())

    assert restored == spec
    assert isinstance(restored.sections[0], ast.Message)
    assert isinstance(restored.sections[1], ast.EnumeratedAvp)
