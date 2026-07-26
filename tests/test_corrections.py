from pathlib import Path

import pytest

from seanchai.dad import ast, corrections, formatter, parser

_ROOT = Path(__file__).parent.parent


def _spec():
    return ast.Specification(
        specification="3GPP TS 29.999",
        version="1.2.3",
        sections=(
            ast.Message(
                name="Example-Request",
                abbreviation="EXR",
                source=ast.SourceRef(section="6.1"),
                command_code=321,
                flags=frozenset({ast.CommandFlag.REQUEST}),
                application_id=None,
                avps=(ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),),
            ),
            ast.AvpTable(
                table="6.3.1",
                source=ast.SourceRef(section="6.3"),
                rows=(
                    ast.AvpTableRow(
                        name="Example-Mode",
                        code=1600,
                        section="6.3.2",
                        data_type="Enumerated",
                        flag_rules=ast.AvpFlagRules(),
                        may_encrypt=False,
                    ),
                ),
            ),
            ast.EnumeratedAvp(
                name="Example-Mode",
                source=ast.SourceRef(section="6.3.2"),
                code=1600,
                values=(ast.EnumValue(name="Off", value=0),),
            ),
        ),
    )


def _message(spec: ast.Specification) -> ast.Message:
    section = spec.sections[0]
    assert isinstance(section, ast.Message)
    return section


def _table(spec: ast.Specification) -> ast.AvpTable:
    section = spec.sections[1]
    assert isinstance(section, ast.AvpTable)
    return section


def _correction(target, field, expect, replace):
    return corrections.Correction(
        target=target, field=field, expect=expect, replace=replace, reason="test"
    )


def test_applies_a_correction_and_leaves_the_rest_of_the_tree_alone():
    spec = _spec()

    corrected, results = corrections.apply(
        spec,
        [
            _correction(
                corrections.definition("Example-Request"),
                "application_id",
                None,
                16777308,
            )
        ],
    )

    assert _message(corrected).application_id == 16777308
    assert corrected.sections[1:] == spec.sections[1:]
    assert _message(spec).application_id is None  # the input is untouched
    assert [(r.node, r.old, r.new) for r in results] == [
        ("definition 'Example-Request'", None, 16777308)
    ]


@pytest.mark.parametrize(
    ("target", "field", "expect", "replace"),
    [
        (corrections.table_row("Example-Mode"), "code", 1600, 1602),
        (corrections.enum_value("Example-Mode", "Off"), "value", 0, 7),
        (
            corrections.avp_rule("Example-Request", "Session-Id"),
            "presence",
            ast.Presence.FIXED,
            ast.Presence.REQUIRED,
        ),
    ],
    ids=["table-row", "enum-value", "avp-rule"],
)
def test_every_selector_reaches_a_node_nested_in_the_tree(
    target, field, expect, replace
):
    corrected, results = corrections.apply(
        _spec(), [_correction(target, field, expect, replace)]
    )

    assert results[0].new == replace
    assert getattr(next(iter(target.find(corrected))), field) == replace


def test_applying_twice_fails_because_expect_no_longer_holds():
    # Deterministic, deliberately not idempotent: an already-applied correction
    # is indistinguishable from one the specification fixed upstream, and the
    # difference is the whole point of `expect`.
    correction = _correction(
        corrections.definition("Example-Request"), "application_id", None, 16777308
    )
    corrected, _ = corrections.apply(_spec(), [correction])

    assert corrections.apply(_spec(), [correction])[0] == corrected
    with pytest.raises(corrections.CorrectionError, match="expected application_id"):
        corrections.apply(corrected, [correction])


def test_a_correction_that_no_longer_matches_is_an_error():
    with pytest.raises(corrections.CorrectionError, match="expected code=99"):
        corrections.apply(
            _spec(), [_correction(corrections.table_row("Example-Mode"), "code", 99, 1)]
        )


def test_a_selector_matching_nothing_is_an_error():
    with pytest.raises(corrections.CorrectionError, match=r"Missing\-AVP.*no match"):
        corrections.apply(
            _spec(),
            [_correction(corrections.table_row("Missing-AVP"), "code", 1, 2)],
        )


def test_an_ambiguous_selector_is_an_error():
    # "Example-Mode" names both an AVP-table row and an enumerated definition;
    # within one selector kind, two matches must be narrowed rather than guessed.
    spec = _spec()
    doubled = spec.model_copy(update={"sections": (*spec.sections, spec.sections[2])})

    with pytest.raises(corrections.CorrectionError, match="2 matches, narrow"):
        corrections.apply(
            doubled,
            [_correction(corrections.definition("Example-Mode"), "code", 1600, 1602)],
        )


def test_an_unknown_field_is_an_error():
    with pytest.raises(corrections.CorrectionError, match="has no field 'colour'"):
        corrections.apply(
            _spec(),
            [_correction(corrections.table_row("Example-Mode"), "colour", None, "red")],
        )


def test_an_invalid_replacement_is_rejected_by_the_model():
    # The whole reason for rebuilding through validation instead of
    # `model_copy(update=...)`, which would accept this silently.
    with pytest.raises(corrections.CorrectionError, match="is not valid"):
        corrections.apply(
            _spec(),
            [_correction(corrections.table_row("Example-Mode"), "code", 1600, -1)],
        )


def test_a_failing_correction_leaves_no_partial_result():
    spec = _spec()
    good = _correction(
        corrections.definition("Example-Request"), "application_id", None, 16777308
    )
    bad = _correction(corrections.table_row("Example-Mode"), "code", 1, 2)

    with pytest.raises(corrections.CorrectionError):
        corrections.apply(spec, [good, bad])

    assert _message(spec).application_id is None


def test_two_corrections_to_the_same_field_are_rejected():
    correction = _correction(corrections.table_row("Example-Mode"), "code", 1600, 1602)

    with pytest.raises(corrections.CorrectionError, match="corrected more than once"):
        corrections.apply(_spec(), [correction, correction])


def test_two_fields_of_one_node_can_be_corrected_independently():
    corrected, results = corrections.apply(
        _spec(),
        [
            _correction(corrections.table_row("Example-Mode"), "code", 1600, 1602),
            _correction(
                corrections.table_row("Example-Mode"), "section", "6.3.2", "6.3.3"
            ),
        ],
    )

    row = _table(corrected).rows[0]
    assert (row.code, row.section) == (1602, "6.3.3")
    assert len(results) == 2


def test_a_correction_that_replaces_a_value_with_itself_is_rejected():
    with pytest.raises(corrections.CorrectionError, match="with itself"):
        _correction(corrections.table_row("Example-Mode"), "code", 1600, 1600)


def test_loading_finds_the_module_named_after_the_specification(tmp_path):
    (tmp_path / "TS29.999.py").write_text(
        "from seanchai.dad.corrections import Correction, table_row\n"
        "CORRECTIONS = [Correction(target=table_row('Example-Mode'), field='code',"
        " expect=1600, replace=1602, reason='typo')]\n"
    )

    declared = corrections.load(tmp_path, "3GPP TS 29.999")

    assert [c.replace for c in declared] == [1602]
    assert corrections.load(tmp_path, "3GPP TS 29.998") == []
    assert corrections.load(None, "3GPP TS 29.999") == []


@pytest.mark.parametrize(
    "raw",
    sorted((_ROOT / "examples").glob("*.raw.dad")),
    ids=lambda path: path.name,
)
def test_committed_corrections_still_apply_to_committed_raw_output(raw):
    """The rot check that makes the layer worth having: if a re-extraction or a
    spec bump changes what a correction expects, this fails."""
    spec = parser.parse(raw.read_text())
    declared = corrections.load(_ROOT / "corrections", spec.specification)

    corrected, results = corrections.apply(spec, declared)

    assert len(results) == len(declared)
    assert parser.parse(formatter.format_spec(corrected)) == corrected


def test_loading_rejects_a_module_without_corrections(tmp_path):
    (tmp_path / "TS29.999.py").write_text("SOMETHING_ELSE = []\n")

    with pytest.raises(corrections.CorrectionError, match="no CORRECTIONS list"):
        corrections.load(tmp_path, "3GPP TS 29.999")


def test_loading_rejects_corrections_of_the_wrong_type(tmp_path):
    (tmp_path / "TS29.999.py").write_text("CORRECTIONS = ['not a correction']\n")

    with pytest.raises(corrections.CorrectionError, match="must hold Correction"):
        corrections.load(tmp_path, "3GPP TS 29.999")
