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


def _with_specification(text):
    return ast.Specification(
        specification=text, version="1.0", vendor_id=10415, sections=()
    )


def _with_enum_description(text):
    return ast.EnumValue(name="Example", value=1, description=text)


def _with_table_label(text):
    return ast.AvpTable(
        table=text,
        columns=tuple(ast.AvpColumn),
        source=ast.SourceRef(section="1"),
        rows=(
            ast.AvpTableRow(
                name="Example",
                code=1,
                section=None,
                data_type=ast.DataType.UNSIGNED32,
                flag_rules=ast.AvpFlagRules(),
                may_encrypt=False,
            ),
        ),
    )


@pytest.mark.parametrize(
    "build",
    [_with_specification, _with_enum_description, _with_table_label],
    ids=["specification", "enum-description", "table-label"],
)
@pytest.mark.parametrize(
    "text",
    ["one\ntwo", "one\rtwo", "", " leading", "trailing ", "\tleading", "trailing\t"],
    ids=["newline", "carriage-return", "empty", *["padded"] * 4],
)
def test_inline_text_fields_reject_values_that_cannot_round_trip(build, text):
    # The format is line-oriented, and every one of these formats to text the
    # parser reads back as something else: a newline splits the value in two
    # and, in a header, injects a second directive; an empty or space-padded
    # value writes a line with trailing whitespace, which the parser rejects.
    with pytest.raises(pydantic.ValidationError):
        build(text)


@pytest.mark.parametrize(
    ("specification", "reference"),
    [
        ("3GPP TS 29.272", "TS29.272"),
        ("RFC 6733", "RFC6733"),
        ("ETSI TS 283 034", "ETSI-TS283.034"),
        ("ETSI ES 283 034", "ETSI-ES283.034"),
        ("3GPP2 X.S0057", "3GPP2-X.S0057"),
        ("OMA-DDS-Charging_Data", "OMA-DDS-Charging_Data"),
        ("oneM2M TS-0004", "oneM2M-TS-0004"),
    ],
)
def test_spec_ref_spells_each_publisher_one_way(specification, reference):
    assert ast.spec_ref(specification) == reference
    assert ast.is_external(reference) is not reference.startswith(("TS", "RFC"))


@pytest.mark.parametrize(
    "specification",
    [
        "3GPP TS ../outside",
        "/etc/passwd",
        r"..\outside",
        "TS 29.2721",
        "",
        "Test",
        # 3GPP numbers no three-digit series; ETSI's needs its publisher.
        "3GPP TS 283.034",
        "OMA-../outside",
        "3GPP2 ../X.S0057",
    ],
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


def _table(columns, rows):
    return ast.AvpTable(
        table="1/1", columns=columns, source=ast.SourceRef(section="1"), rows=rows
    )


def test_a_row_may_not_carry_a_value_for_a_column_the_table_lacks():
    """Unattributable data cannot be written out, so it cannot round-trip."""
    with pytest.raises(pydantic.ValidationError, match="table has no Encrypt column"):
        _table(
            (ast.AvpColumn.NAME,),
            (ast.AvpTableRow(name="Example", may_encrypt=False),),
        )
    with pytest.raises(pydantic.ValidationError, match="table has no Must column"):
        _table(
            (ast.AvpColumn.NAME,),
            (
                ast.AvpTableRow(
                    name="Example",
                    flag_rules=ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR})),
                ),
            ),
        )


def test_a_table_needs_a_name_column_and_no_duplicates():
    with pytest.raises(pydantic.ValidationError, match="no Name column"):
        _table((ast.AvpColumn.CODE,), (ast.AvpTableRow(name="Example", code=1),))
    with pytest.raises(pydantic.ValidationError, match="duplicate column"):
        _table(
            (ast.AvpColumn.NAME, ast.AvpColumn.NAME),
            (ast.AvpTableRow(name="Example"),),
        )


def test_marks_need_their_column_and_are_no_dash():
    """A mark may hold what a quoted enum value name may (TS 29.212's `All
    (NOTE 5)`), but not a lone `-`, which is the cell's printed dash: no
    marks, `()`, as a blank cell is no entry."""
    applicability = {ast.MarkColumn.APPLICABILITY: ("Both", "All (NOTE 5)")}
    with pytest.raises(pydantic.ValidationError, match="no Applicability column"):
        _table((ast.AvpColumn.NAME,), (ast.AvpTableRow(name="E", marks=applicability),))
    with pytest.raises(pydantic.ValidationError, match="no ACR column"):
        ast.ReusedAvps(
            table="7.3.1",
            source=ast.SourceRef(section="7.3"),
            rows=(
                ast.ReusedAvpRow(
                    name="E", origin="TS29.212", marks={ast.MarkColumn.ACR: ("X",)}
                ),
            ),
        )
    for marks in (("-",), ("",), (" padded",), ("a;;b",)):
        with pytest.raises(pydantic.ValidationError):
            ast.AvpTableRow(name="E", marks={ast.MarkColumn.APPLICABILITY: marks})
    columns = (ast.AvpColumn.NAME, ast.AvpColumn.APPLICABILITY)
    _table(columns, (ast.AvpTableRow(name="E", marks=applicability),))
    dash = {ast.MarkColumn.APPLICABILITY: ()}
    _table(columns, (ast.AvpTableRow(name="E", marks=dash),))
