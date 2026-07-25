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


def test_nodes_are_frozen_and_forbid_extra_fields():
    source = ast.SourceRef(section="1.2")

    with pytest.raises(pydantic.ValidationError, match="frozen"):
        source.section = "2.1"
    with pytest.raises(pydantic.ValidationError, match="Extra inputs"):
        ast.SourceRef(section="1.2", unknown=True)


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
