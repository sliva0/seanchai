import copy
import dataclasses
import itertools
from pathlib import Path

import pytest
from conftest import _CORPUS_DIR, _corpus

from seanchai.dad import ast, corrections, formatter, parser

_ROOT = Path(__file__).parent.parent


def _spec():
    return ast.Specification(
        specification="3GPP TS 29.999",
        version="1.2.3",
        vendor_id=10415,
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
                columns=tuple(ast.AvpColumn),
                source=ast.SourceRef(section="6.3"),
                rows=(
                    ast.AvpTableRow(
                        name="Example-Mode",
                        code=1600,
                        section="6.3.2",
                        data_type=ast.DataType.ENUMERATED,
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


_IDS = (f"test-{n}" for n in itertools.count())


def _correction(target, field, expect, replace):
    return corrections.Correction(
        id=next(_IDS),
        target=target,
        field=field,
        expect=expect,
        replace=replace,
        reason="test",
    )


@pytest.mark.parametrize(
    ("target", "field", "expect", "replace", "cited"),
    [
        (corrections.header(), "bases", (), ("RFC6733",), "; Bases: RFC6733"),
        (corrections.avp_table("6.3.1"), "table", "6.3.1", "6.3.9", "; Table: 6.3.9"),
        # A correction that removes its field's line is cited on the line
        # that names the block.
        (corrections.avp_table("6.3.1"), "table", "6.3.1", None, "; Type: AVP Table"),
    ],
    ids=["bases", "table-label", "table-label-removed"],
)
def test_a_header_or_table_field_correction_is_cited_on_its_directive_line(
    target, field, expect, replace, cited
):
    # These have no header rule to carry the note, and every line the
    # correction changed has to cite it.
    correction = _correction(target, field, expect, replace)
    corrected, results = corrections.apply(_spec(), [correction])

    text = formatter.format_spec(corrected, corrections.notes(results))

    (noted,) = [line for line in text.splitlines() if ";;" in line]
    assert noted == f"{cited} ;; corrected: ({correction.id})"


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


def test_a_registry_reservation_is_corrected_by_its_range():
    """TS 29.230 table 7.1 reserves 1324-1399 "for TS 32.229", TS 32.299."""
    spec = parser.parse(
        "; Specification: 3GPP TS 29.230\n; Version: 19.3.0\n; Vendor-ID: 10415\n"
        "; Bases: RFC6733\n\n\n"
        "; Type: Registry\n; Registry: AVP Codes\n; Section: 7\n; Table: 7.1\n"
        "; Columns: Code Name Defined-In\n"
        '1323 VoLTE-Information TS32.299\n; RESERVED 1324..1399 TS32.229 "TS 32.229"\n'
    )
    edits = [
        corrections.Correction(
            id="reserved-document",
            target=corrections.registry_reservation(1324, 1399),
            field="defined_in",
            expect=("TS32.229",),
            replace=("TS32.299",),
            reason="r",
        ),
    ]

    corrected, _ = corrections.apply(spec, edits)

    (registry,) = corrected.sections
    assert isinstance(registry, ast.Registry)
    assert registry.rows[1] == ast.RegistryReservation(
        first=1324, last=1399, defined_in=("TS32.299",), purpose="TS 32.229"
    )
    with pytest.raises(corrections.CorrectionError, match=r"1324\.\.1400"):
        corrections.apply(
            spec,
            [
                dataclasses.replace(
                    edits[0], target=corrections.registry_reservation(1324, 1400)
                )
            ],
        )


def test_a_correction_that_replaces_a_value_with_itself_is_rejected():
    with pytest.raises(corrections.CorrectionError, match="with itself"):
        _correction(corrections.table_row("Example-Mode"), "code", 1600, 1600)


@pytest.mark.parametrize(
    "reversed_order", [False, True], ids=["parent-first", "child-first"]
)
@pytest.mark.parametrize(
    (
        "parent",
        "field",
        "before",
        "after",
        "child",
        "child_field",
        "child_before",
        "child_after",
    ),
    [
        (
            "Example-Request",
            "application_id",
            None,
            16777308,
            corrections.avp_rule("Example-Request", "Session-Id"),
            "presence",
            ast.Presence.FIXED,
            ast.Presence.REQUIRED,
        ),
        (
            "Example-Mode",
            "code",
            1600,
            1602,
            corrections.enum_value("Example-Mode", "Off"),
            "value",
            0,
            7,
        ),
    ],
    ids=["message-rule", "enum-value"],
)
def test_a_definition_and_one_of_its_avp_rules_are_both_applied(
    reversed_order,
    parent,
    field,
    before,
    after,
    child,
    child_field,
    child_before,
    child_after,
):
    # Rebuilding the ancestor must preserve the child's edit in either order.
    target = corrections.definition(parent)
    declared = [
        _correction(target, field, before, after),
        _correction(child, child_field, child_before, child_after),
    ]
    corrected, results = corrections.apply(
        _spec(), list(reversed(declared)) if reversed_order else declared
    )
    assert len(results) == 2
    (definition,) = target.find(corrected)
    (nested,) = child.find(corrected)
    assert getattr(definition, field) == after
    assert getattr(nested, child_field) == child_after


def test_replacing_a_structural_field_is_rejected_rather_than_given_semantics():
    # A whole-subtree replacement would have to say what happens to a
    # correction aimed at one of the children it discards; correcting the child
    # is the operation that exists.
    with pytest.raises(corrections.CorrectionError, match="holds child nodes"):
        corrections.apply(
            _spec(),
            [_correction(corrections.definition("Example-Request"), "avps", None, ())],
        )


def test_the_rebuilt_tree_is_validated_as_a_whole():
    # `min_occurs`/`max_occurs` are each valid on their own; only the rule
    # they belong to knows the range is now inverted.
    with pytest.raises(corrections.CorrectionError, match="not valid"):
        corrections.apply(
            _spec(),
            [
                _correction(
                    corrections.avp_rule("Example-Request", "Session-Id"),
                    "min_occurs",
                    1,
                    5,
                ),
                _correction(
                    corrections.avp_rule("Example-Request", "Session-Id"),
                    "max_occurs",
                    1,
                    2,
                ),
            ],
        )


def _two_applications() -> ast.Specification:
    """One command name defined for two applications, as TS 29.272 does for
    IDR/DSR/RSR across S6a and S7a."""
    spec = _spec()
    message = _message(spec)
    # Spelled out rather than `model_copy`d: a copy would share the one
    # `AvpRule` object between both messages, which is not what parsing a file
    # produces and not what the identity-keyed rebuild is meant to handle.
    s7a = ast.Message(
        name=message.name,
        abbreviation=message.abbreviation,
        source=message.source,
        command_code=message.command_code,
        flags=message.flags,
        application_id=16777308,
        avps=(ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),),
    )
    return spec.model_copy(update={"sections": (message, s7a, *spec.sections[1:])})


def test_an_explicit_none_application_id_selects_the_definition_that_omits_it():
    corrected, _ = corrections.apply(
        _two_applications(),
        [
            _correction(
                corrections.definition("Example-Request", application_id=None),
                "application_id",
                None,
                16777251,
            )
        ],
    )

    assert [
        section.application_id
        for section in corrected.sections
        if isinstance(section, ast.Message)
    ] == [16777251, 16777308]


def test_an_unspecified_application_id_does_not_filter_and_stays_ambiguous():
    with pytest.raises(corrections.CorrectionError, match="2 matches, narrow"):
        corrections.apply(
            _two_applications(),
            [
                _correction(
                    corrections.definition("Example-Request"), "command_code", 321, 322
                )
            ],
        )


def test_an_avp_rule_can_be_narrowed_by_its_parents_application():
    target = corrections.avp_rule(
        parent=corrections.definition("Example-Request", application_id=16777308),
        name="Session-Id",
    )

    corrected, results = corrections.apply(
        _two_applications(),
        [_correction(target, "presence", ast.Presence.FIXED, ast.Presence.REQUIRED)],
    )

    messages = [s for s in corrected.sections if isinstance(s, ast.Message)]
    assert results[0].node == (
        "AVP rule 'Session-Id' in definition 'Example-Request' (application 16777308)"
    )
    assert messages[0].avps[0].presence is ast.Presence.FIXED
    assert messages[1].avps[0].presence is ast.Presence.REQUIRED


def test_a_node_object_shared_by_two_places_is_corrected_only_where_selected():
    # Edits are keyed by where the selector found a node, not by the object:
    # a caller that hands the same object to two parents gets the one
    # correction it was told about.
    spec = _spec()
    message = _message(spec)
    shared = message.model_copy(update={"application_id": 16777308})

    corrected, results = corrections.apply(
        spec.model_copy(update={"sections": (message, shared, *spec.sections[1:])}),
        [
            _correction(
                corrections.avp_rule(
                    parent=corrections.definition(
                        "Example-Request", application_id=16777308
                    ),
                    name="Session-Id",
                ),
                "bold",
                False,
                True,
            )
        ],
    )

    first, second = corrected.sections[:2]
    assert isinstance(first, ast.Message)
    assert isinstance(second, ast.Message)
    assert not first.avps[0].bold
    assert second.avps[0].bold
    assert results[0].path == ("sections", 1, "avps", 0)


def _with_reused(spec: ast.Specification) -> ast.Specification:
    reused = ast.ReusedAvps(
        table="6.4",
        source=ast.SourceRef(section="6.4"),
        rows=(
            ast.ReusedAvpRow(name="Load", origin="RFC8583"),
            ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229"),
        ),
    )
    return spec.model_copy(update={"sections": (*spec.sections, reused)})


def _delete(target, expect):
    return corrections.Delete(
        id=next(_IDS), target=target, expect=expect, reason="test"
    )


def _insert(node, after=None):
    return corrections.Insert(
        id=next(_IDS),
        into=corrections.avp_table("6.3.1"),
        node=node,
        after=after,
        reason="test",
    )


def test_an_insert_with_no_after_appends():
    inserted = ast.AvpTableRow(
        name="Inserted-AVP",
        code=1601,
        section="6.3.3",
        data_type=ast.DataType.UNSIGNED32,
        may_encrypt=False,
    )

    corrected, _ = corrections.apply(_spec(), [_insert(inserted)])

    assert _table(corrected).rows[-1].name == "Inserted-AVP"


def test_an_insert_fails_when_upstream_already_has_the_row():
    with pytest.raises(corrections.CorrectionError, match="already present"):
        corrections.apply(_spec(), [_insert(_table(_spec()).rows[0])])


def test_an_insert_fails_when_its_after_row_is_missing():
    inserted = ast.AvpTableRow(
        name="Inserted-AVP",
        code=1601,
        section="6.3.3",
        data_type=ast.DataType.UNSIGNED32,
        may_encrypt=False,
    )

    with pytest.raises(corrections.CorrectionError, match="is not present"):
        corrections.apply(_spec(), [_insert(inserted, after="Missing-AVP")])


def _reused_insert(label, name):
    return corrections.Insert(
        id=next(_IDS),
        into=corrections.reused_avps(label),
        node=ast.ReusedAvpRow(name=name, origin="RFC6733"),
        after=None,
        reason="test",
    )


def test_a_reused_insert_without_its_block_or_table_matches_nothing():
    # Only an AVP table of the same label can give a new block its place.
    with pytest.raises(corrections.CorrectionError, match="no match"):
        corrections.apply(_spec(), [_reused_insert("9.9.9", "Session-Id")])


def test_a_created_reused_block_rejects_a_row_inserted_twice():
    twice = [_reused_insert("6.3.1", "Session-Id")] * 2

    with pytest.raises(corrections.CorrectionError, match="already present"):
        corrections.apply(_spec(), twice)


def test_a_created_reused_block_follows_its_table_and_carries_the_rows():
    corrected, results = corrections.apply(
        _spec(), [_reused_insert("6.3.1", "Session-Id")]
    )

    block = corrected.sections[2]
    assert isinstance(block, ast.ReusedAvps)
    assert block.table == "6.3.1"
    assert block.source == _table(_spec()).source
    assert [row.name for row in block.rows] == ["Session-Id"]
    assert results[0].path == ("sections", 2, "rows", 0)


def test_a_delete_cannot_reach_a_block_only_an_insert_creates():
    # Selectors see the input: a block that exists only once the corrections
    # run cannot be deleted by them, before or after the insert that makes it.
    block = ast.ReusedAvps(
        table="6.3.1",
        source=ast.SourceRef(section="6.3"),
        columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
        rows=(ast.ReusedAvpRow(name="Session-Id", origin="RFC6733"),),
    )
    delete = _delete(corrections.reused_avps("6.3.1"), block)

    for order in (
        [delete, _reused_insert("6.3.1", "Session-Id")],
        [_reused_insert("6.3.1", "Session-Id"), delete],
    ):
        with pytest.raises(corrections.CorrectionError, match="no match"):
            corrections.apply(_spec(), order)


def test_an_inserted_row_cannot_be_deleted_afterwards():
    inserted = _reused_insert("6.3.1", "Session-Id")
    delete = _delete(
        corrections.reused_row("Session-Id"),
        ast.ReusedAvpRow(name="Session-Id", origin="RFC6733"),
    )

    with pytest.raises(corrections.CorrectionError, match="no match"):
        corrections.apply(_spec(), [inserted, delete])


def test_an_insert_into_a_table_another_edit_deletes_fails():
    reused = _with_reused(_spec())
    (block,) = corrections.reused_avps("6.4").find(reused)
    edits = [
        corrections.Insert(
            id=next(_IDS),
            into=corrections.reused_avps("6.4"),
            node=ast.ReusedAvpRow(name="Inserted-AVP", origin="RFC6733"),
            after=None,
            reason="test",
        ),
        _delete(corrections.reused_avps("6.4"), block),
    ]

    with pytest.raises(corrections.CorrectionError, match="corrected and deleted"):
        corrections.apply(reused, edits)


def _member_insert(
    name, after: str | None = "Session-Id", into="Example-Request", node=None
):
    return corrections.Insert(
        id=next(_IDS),
        into=corrections.definition(into),
        node=node or ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL),
        after=after,
        reason="test",
    )


def test_a_member_insert_lands_after_its_member_and_is_noted():
    edits = [_member_insert("Late-AVP"), _member_insert("Early-AVP")]

    corrected, results = corrections.apply(_spec(), edits)

    assert [rule.name for rule in _message(corrected).avps] == [
        "Session-Id",
        "Early-AVP",
        "Late-AVP",
    ]
    assert [result.path for result in results] == [
        ("sections", 0, "avps", 2),
        ("sections", 0, "avps", 1),
    ]
    assert corrections.notes(results).trailing[("sections", 0, "avps", 1)] == [
        f"inserted: ({edits[1].id})"
    ]


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (_member_insert("Session-Id", after=None), "already present"),
        (_member_insert("Other", after="Missing-AVP"), "is not present"),
        (_member_insert("Other", into="Example-Mode"), "message or grouped AVP"),
        (
            _member_insert(
                "Other",
                node=ast.ReusedAvpRow(name="Other", origin="RFC6733"),
            ),
            "must be a AvpRule",
        ),
    ],
)
def test_a_member_insert_fails_where_its_body_cannot_take_it(edit, problem):
    with pytest.raises(corrections.CorrectionError, match=problem):
        corrections.apply(_spec(), [edit])


def _value_insert(name, value, after: str | None = "Off"):
    return _member_insert(
        name,
        after=after,
        into="Example-Mode",
        node=ast.EnumValue(name=name, value=value),
    )


def test_a_value_insert_extends_an_enumeration_and_is_noted():
    """RFC 8581 clause 7.2.1 adds PEER_REPORT to RFC 7683's OC-Report-Type."""
    edit = _value_insert("On", 1)

    corrected, results = corrections.apply(_spec(), [edit])

    enum = corrected.sections[2]
    assert isinstance(enum, ast.EnumeratedAvp)
    assert enum.values == (
        ast.EnumValue(name="Off", value=0),
        ast.EnumValue(name="On", value=1),
    )
    assert results[0].path == ("sections", 2, "values", 1)
    assert corrections.notes(results).trailing[("sections", 2, "values", 1)] == [
        f"inserted: ({edit.id})"
    ]


@pytest.mark.parametrize(
    ("edit", "problem"),
    [
        (_value_insert("Off", 1), "'Off' is already present"),
        (_value_insert("On", 0), "value 0 is already present"),
        (_value_insert("On", 1, after="Missing"), "is not present"),
        (
            _member_insert("Other", node=ast.EnumValue(name="Other", value=1)),
            "must be a AvpRule",
        ),
    ],
)
def test_a_value_insert_fails_where_its_enumeration_cannot_take_it(edit, problem):
    with pytest.raises(corrections.CorrectionError, match=problem):
        corrections.apply(_spec(), [edit])


def test_a_delete_whose_expect_differs_reports_the_changed_fields():
    with pytest.raises(corrections.CorrectionError, match=r"has changed.*origin"):
        corrections.apply(
            _with_reused(_spec()),
            [
                _delete(
                    corrections.reused_row("Feature-Id"),
                    ast.ReusedAvpRow(name="Feature-Id", origin="TS29.999"),
                )
            ],
        )


def test_a_delete_whose_expect_is_the_wrong_kind_of_node_is_an_error():
    with pytest.raises(corrections.CorrectionError, match="expected a AvpTableRow"):
        corrections.apply(
            _with_reused(_spec()),
            [
                _delete(
                    corrections.reused_row("Feature-Id"),
                    ast.AvpTableRow(name="Feature-Id"),
                )
            ],
        )


def test_deleting_and_correcting_the_same_node_is_refused():
    spec = _with_reused(_spec())
    doomed = ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229")
    edits = [
        _correction(
            corrections.reused_row("Feature-Id"), "origin", "TS29.229", "TS29.999"
        ),
        _delete(corrections.reused_row("Feature-Id"), doomed),
    ]

    for ordering in (edits, list(reversed(edits))):
        with pytest.raises(
            corrections.CorrectionError, match="both corrected and deleted"
        ):
            corrections.apply(spec, ordering)


_SUPPLIED = (
    ast.EnumValue(name="Any", value=0),
    ast.ReservedValues(first=1, last=3),
    ast.EnumValue(name="Text", value=4),
)


def _externally_defined(
    spec: ast.Specification, values: tuple = ()
) -> ast.Specification:
    """TS 32.299 clause 7.2.238's shape: an enumerated AVP whose clause
    names another document for its values and prints none."""
    enumerated = spec.sections[2]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    cited = enumerated.model_copy(
        update={
            "values_source": "OMNA WSP Content Type Numbers [210]",
            "values": values,
        }
    )
    return spec.model_copy(update={"sections": (*spec.sections[:2], cited)})


def _supply(expect="OMNA WSP Content Type Numbers [210]", values=_SUPPLIED):
    return corrections.Supply(
        id=next(_IDS),
        target=corrections.definition("Example-Mode"),
        expect=expect,
        values=values,
        reason="test",
    )


def test_a_supply_fills_the_values_and_marks_every_supplied_line():
    supply = _supply()

    corrected, results = corrections.apply(_externally_defined(_spec()), [supply])

    enumerated = corrected.sections[2]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.values == _SUPPLIED
    # The document still says where the values are defined.
    assert enumerated.values_source == "OMNA WSP Content Type Numbers [210]"
    text = formatter.format_spec(corrected, corrections.notes(results))
    noted = [line for line in text.splitlines() if ";;" in line]
    assert noted == [
        f"        Any      = 0 ;; supplied: ({supply.id})",
        f"      ; RESERVED = 1-3 ;; supplied: ({supply.id})",
        f"        Text     = 4 ;; supplied: ({supply.id})",
    ]
    assert parser.parse_with_comments(text) == (
        corrected,
        corrections.notes(results),
    )


@pytest.mark.parametrize(
    ("spec", "expect", "message"),
    [
        # Upstream re-worded the citation.
        (
            _externally_defined(_spec()),
            "OMNA WSP Content Type Codes [210]",
            "expected values_source='OMNA WSP Content Type Codes",
        ),
        # Upstream prints the list itself.
        (
            _externally_defined(_spec(), values=_SUPPLIED[:1]),
            "OMNA WSP Content Type Numbers [210]",
            "already holds 1 values",
        ),
        # No citation at all: a clause saying nothing is not a Supply case.
        (_spec(), "OMNA WSP Content Type Numbers [210]", "found None"),
    ],
    ids=["citation-changed", "values-printed", "no-citation"],
)
def test_a_supply_expects_the_citation_and_no_values(spec, expect, message):
    with pytest.raises(corrections.CorrectionError, match=message):
        corrections.apply(spec, [_supply(expect=expect)])


_PRINTED = (
    ast.EnumValue(name="Plain", value=0),
    ast.ReservedValues(first=5, last=6),
)


def _extend(values):
    return corrections.Supply(
        id=next(_IDS),
        target=corrections.definition("Example-Mode"),
        expect="OMNA WSP Content Type Numbers [210]",
        values=values,
        extend=True,
        reason="test",
    )


def test_an_extending_supply_follows_the_printed_values_and_marks_its_own():
    # RFC 4005 clause 4.4's shape: an informational list the registry it
    # cites has grown past.
    spec = _externally_defined(_spec(), values=_PRINTED)
    added = (ast.EnumValue(name="Fancy", value=7), ast.ReservedValues(first=8, last=9))
    supply = _extend(added)

    corrected, results = corrections.apply(spec, [supply])

    enumerated = corrected.sections[2]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.values == (*_PRINTED, *added)
    text = formatter.format_spec(corrected, corrections.notes(results))
    noted = [line for line in text.splitlines() if ";;" in line]
    assert noted == [
        f"        Fancy    = 7 ;; supplied: ({supply.id})",
        f"      ; RESERVED = 8-9 ;; supplied: ({supply.id})",
    ]
    assert parser.parse_with_comments(text) == (
        corrected,
        corrections.notes(results),
    )


@pytest.mark.parametrize(
    ("printed", "values", "message"),
    [
        (_PRINTED, (ast.EnumValue(name="Plain", value=7),), "'Plain' is already"),
        (_PRINTED, (ast.EnumValue(name="Fancy", value=0),), "value 0 is already"),
        # A number inside a printed reserved range is no new number.
        (_PRINTED, (ast.EnumValue(name="Fancy", value=6),), "value 6 is already"),
        (_PRINTED, (ast.ReservedValues(first=4, last=5),), "value 4-5 is already"),
        # Nothing printed to extend: the plain form is the one that applies.
        ((), (ast.EnumValue(name="Fancy", value=7),), "prints no values"),
    ],
    ids=["name", "number", "reserved-number", "reserved-range", "empty-list"],
)
def test_an_extending_supply_adds_only_new_names_and_numbers(printed, values, message):
    spec = _externally_defined(_spec(), values=printed)

    with pytest.raises(corrections.CorrectionError, match=message):
        corrections.apply(spec, [_extend(values)])


def test_a_supply_requires_an_enumerated_avp():
    supply = corrections.Supply(
        id=next(_IDS),
        target=corrections.definition("Example-Request"),
        expect="anything",
        values=_SUPPLIED,
        reason="test",
    )

    with pytest.raises(corrections.CorrectionError, match="matched a Message"):
        corrections.apply(_spec(), [supply])


def test_a_supply_of_no_values_is_rejected_when_declared():
    with pytest.raises(corrections.CorrectionError, match="supplies no values"):
        _supply(values=())


def test_supplying_one_section_twice_or_deleting_it_is_refused():
    spec = _externally_defined(_spec())
    enumerated = spec.sections[2]

    with pytest.raises(corrections.CorrectionError, match="supplied more than once"):
        corrections.apply(spec, [_supply(), _supply()])
    edits = [_supply(), _delete(corrections.definition("Example-Mode"), enumerated)]
    for ordering in (edits, list(reversed(edits))):
        with pytest.raises(
            corrections.CorrectionError, match="both corrected and deleted"
        ):
            corrections.apply(spec, ordering)


def test_a_supply_and_a_correction_of_the_same_section_both_apply():
    spec = _externally_defined(_spec())
    edits = [
        _correction(corrections.definition("Example-Mode"), "code", 1600, 1601),
        _supply(),
    ]

    corrected, _ = corrections.apply(spec, edits)

    enumerated = corrected.sections[2]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert (enumerated.code, enumerated.values) == (1601, _SUPPLIED)


_REFERRED = ast.AvpTableRow(name="Borrowed", code=2101)
_OMA_FLAGS = ast.AvpFlagRules(
    must=frozenset({ast.AvpFlag.VENDOR, ast.AvpFlag.MANDATORY}),
    may=frozenset({ast.AvpFlag.PROTECTED}),
)


def _typed_by_reference(spec, reused=True):
    """`_spec` with a row typed only by a reference to another document, as
    TS 32.299 table 7.2.0.1 types OMA's rows, and the re-used row citing it."""
    table = _table(spec)
    table = table.model_copy(update={"rows": (*table.rows, _REFERRED)})
    cited = ast.ReusedAvps(
        table="6.3.1",
        source=ast.SourceRef(section="6.3"),
        rows=(ast.ReusedAvpRow(name="Borrowed", origin="OMA-DDS-Charging_Data"),),
    )
    sections = (spec.sections[0], table, *((cited,) if reused else ()))
    return spec.model_copy(update={"sections": (*sections, *spec.sections[2:])})


def _supply_row(expect=_REFERRED, data_type=ast.DataType.UTF8_STRING, flags=_OMA_FLAGS):
    return corrections.Supply(
        id=next(_IDS),
        target=corrections.table_row("Borrowed"),
        expect=expect,
        data_type=data_type,
        flag_rules=flags,
        reason="test",
    )


def test_a_supply_fills_a_row_typed_by_reference_and_marks_it():
    supply = _supply_row()

    corrected, results = corrections.apply(_typed_by_reference(_spec()), [supply])

    row = _table(corrected).rows[-1]
    assert (row.data_type, row.flag_rules) == (ast.DataType.UTF8_STRING, _OMA_FLAGS)
    # The citation stays: the document still says where the AVP is defined.
    assert isinstance(corrected.sections[2], ast.ReusedAvps)
    text = formatter.format_spec(corrected, corrections.notes(results))
    (noted,) = [line for line in text.splitlines() if ";;" in line]
    assert noted.split()[:7] == ["Borrowed", "-", "2101", "-", "UTF8String", "M,V", "P"]
    assert noted.endswith(f" ;; supplied: ({supply.id})")
    assert parser.parse_with_comments(text) == (
        corrected,
        corrections.notes(results),
    )


@pytest.mark.parametrize(
    ("spec", "supply", "message"),
    [
        # Upstream types the row itself.
        (
            _typed_by_reference(_spec()),
            _supply_row(expect=_REFERRED.model_copy(update={"code": 2102})),
            "expected AvpTableRow",
        ),
        # Nothing says the AVP is defined elsewhere.
        (_typed_by_reference(_spec(), reused=False), _supply_row(), "no re-used"),
    ],
    ids=["row-changed", "not-reused"],
)
def test_a_row_supply_expects_the_blank_row_of_a_reused_avp(spec, supply, message):
    with pytest.raises(corrections.CorrectionError, match=message):
        corrections.apply(spec, [supply])


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"expect": _REFERRED.model_copy(update={"data_type": "Unsigned32"})},
            "fills only a blank type",
        ),
        ({"flags": ast.AvpFlagRules()}, "blank flag rules with stated ones"),
        ({"data_type": None, "flags": None}, "supplies nothing"),
    ],
    ids=["typed", "no-flags", "nothing"],
)
def test_a_row_supply_is_checked_when_declared(arguments, message):
    with pytest.raises(corrections.CorrectionError, match=message):
        _supply_row(**arguments)


def test_a_row_supply_does_not_extend():
    with pytest.raises(corrections.CorrectionError, match="no list to extend"):
        corrections.Supply(
            id=next(_IDS),
            target=corrections.table_row("Borrowed"),
            expect=_REFERRED,
            data_type=ast.DataType.UTF8_STRING,
            extend=True,
            reason="test",
        )


def test_a_row_is_not_both_supplied_and_corrected():
    spec = _typed_by_reference(_spec())
    correction = _correction(corrections.table_row("Borrowed"), "code", 2101, 2102)
    for ordering in ([_supply_row(), correction], [correction, _supply_row()]):
        with pytest.raises(corrections.CorrectionError, match="corrected and supplied"):
            corrections.apply(spec, ordering)


def _application(name, application_id, applies_to=("6.*",), section="2.4"):
    return ast.ApplicationScope(
        name=name,
        source=ast.SourceRef(section=section),
        application_id=application_id,
        applies_to=applies_to,
    )


def _insert_application(node, after=None):
    return corrections.Insert(
        id=next(_IDS), into=corrections.header(), node=node, after=after, reason="t"
    )


def test_applications_inserted_into_the_file_lead_it_in_declaration_order():
    first = _insert_application(_application("First", 1, ("6.1.*",)))
    second = _insert_application(_application("Second", 2, ("6.2.*",)))

    corrected, results = corrections.apply(_spec(), [first, second])

    assert [type(s).__name__ for s in corrected.sections[:3]] == [
        "ApplicationScope",
        "ApplicationScope",
        "Message",
    ]
    assert [
        s.name for s in corrected.sections[:2] if isinstance(s, ast.ApplicationScope)
    ] == ["First", "Second"]
    text = formatter.format_spec(corrected, corrections.notes(results))
    noted = [line for line in text.splitlines() if ";;" in line]
    assert noted == [
        f"; Type: Application Scope ;; inserted: ({first.id})",
        f"; Type: Application Scope ;; inserted: ({second.id})",
    ]
    assert parser.parse_with_comments(text) == (corrected, corrections.notes(results))


def test_an_application_insert_follows_the_files_own_and_fails_on_its_name():
    spec = _spec()
    spec = spec.model_copy(
        update={"sections": (_application("Own", 1), *spec.sections)}
    )

    corrected, _ = corrections.apply(
        spec, [_insert_application(_application("Inserted", 2))]
    )

    assert [
        s.name for s in corrected.sections[:2] if isinstance(s, ast.ApplicationScope)
    ] == ["Own", "Inserted"]
    with pytest.raises(corrections.CorrectionError, match="'Own' is already present"):
        corrections.apply(spec, [_insert_application(_application("Own", 3))])


@pytest.mark.parametrize(
    ("node", "after", "message"),
    [
        (_application("Placed", 1), "Own", "after must be None"),
        (
            ast.ReusedAvpRow(name="X", origin="RFC6733"),
            None,
            "only an ApplicationScope or an UndefinedAvp",
        ),
    ],
    ids=["after", "not-an-application"],
)
def test_an_insert_into_the_file_takes_an_application_and_no_after(
    node, after, message
):
    with pytest.raises(corrections.CorrectionError, match=message):
        corrections.apply(_spec(), [_insert_application(node, after)])


def test_an_application_field_correction_is_cited_on_its_directive_line():
    spec = _spec()
    spec = spec.model_copy(
        update={"sections": (_application("Own", 1), *spec.sections)}
    )
    correction = _correction(
        corrections.application_scope("Own"), "application_id", 1, 16777238
    )

    corrected, results = corrections.apply(spec, [correction])

    text = formatter.format_spec(corrected, corrections.notes(results))
    (noted,) = [line for line in text.splitlines() if ";;" in line]
    assert noted == f"; Application-ID: 16777238 ;; corrected: ({correction.id})"


def _with_mystery(spec: ast.Specification) -> ast.Specification:
    """`_spec()` with a member its file defines nowhere: TS 29.345's
    ProSe-Query-Code shape."""
    message = _message(spec)
    mystery = ast.AvpRule(name="Mystery", presence=ast.Presence.OPTIONAL)
    sections = (
        message.model_copy(update={"avps": (*message.avps, mystery)}),
        *spec.sections[1:],
    )
    return spec.model_copy(update={"sections": sections})


def _undefined(name="Mystery", section="6.1", note: str | None = '"a mystery"'):
    return ast.UndefinedAvp(
        name=name, source=ast.SourceRef(section=section, page=7), note=note
    )


def test_an_undefined_avp_inserted_into_the_file_ends_it():
    spec = _with_mystery(_spec())
    scope = _insert_application(_application("Own", 1))
    undefined = _insert_application(_undefined())

    corrected, results = corrections.apply(spec, [undefined, scope])

    assert [type(s).__name__ for s in corrected.sections] == [
        "ApplicationScope",
        "Message",
        "AvpTable",
        "EnumeratedAvp",
        "UndefinedAvp",
    ]
    assert results[0].node == "undefined AVP 'Mystery'"
    text = formatter.format_spec(corrected, corrections.notes(results))
    assert text.endswith(
        f"; Type: Undefined AVP ;; inserted: ({undefined.id})\n"
        "; Name: Mystery\n"
        "; Section: 6.1\n"
        "; Page: 7\n"
        '; Note: "a mystery"\n'
    )
    assert parser.parse_with_comments(text) == (corrected, corrections.notes(results))
    # Correcting corrected output fails, as every other expectation does.
    with pytest.raises(corrections.CorrectionError, match="declared 2 times"):
        corrections.apply(corrected, [undefined])


def test_an_undefined_avp_names_the_member_a_correction_renames():
    """RFC 4004 clause 9.5's shape: the block declares the member's
    corrected name, which only the corrected tree holds."""
    rename = _correction(
        corrections.avp_rule("Example-Request", "Mystery"),
        "name",
        "Mystery",
        "Mystery-Renamed",
    )

    corrected, _ = corrections.apply(
        _with_mystery(_spec()),
        [_insert_application(_undefined("Mystery-Renamed")), rename],
    )

    assert corrected.sections[-1] == _undefined("Mystery-Renamed")


def _tabulating_mystery(spec: ast.Specification) -> ast.Specification:
    table = _table(spec)
    row = ast.AvpTableRow(name="Mystery", code=1601)
    sections = list(spec.sections)
    sections[1] = table.model_copy(update={"rows": (*table.rows, row)})
    return spec.model_copy(update={"sections": tuple(sections)})


@pytest.mark.parametrize(
    ("node", "after", "tabulated", "message"),
    [
        (_undefined(), "Own", False, "ends the file; after must be None"),
        (_undefined("Example-Mode"), None, False, "clause 6.3.2 defines it"),
        (_undefined(), None, True, "the table of clause 6.3 lists it"),
        (_undefined(section="6.3"), None, False, "no message or grouped body"),
        (_undefined("Absent"), None, False, "no message or grouped body in clause 6.1"),
    ],
    ids=["after", "defined", "tabulated", "other-clause", "unreferenced"],
)
def test_an_undefined_avp_insert_fails_where_the_file_says_otherwise(
    node, after, tabulated, message
):
    spec = _with_mystery(_spec())
    if tabulated:
        spec = _tabulating_mystery(spec)

    with pytest.raises(corrections.CorrectionError, match=message):
        corrections.apply(spec, [_insert_application(node, after)])


def test_an_undefined_avp_is_selected_by_name_for_correction_and_deletion():
    spec = _with_mystery(_spec())
    spec = spec.model_copy(update={"sections": (*spec.sections, _undefined())})
    correction = _correction(
        corrections.undefined("Mystery"), "note", '"a mystery"', '"clause 6.1 says"'
    )

    corrected, results = corrections.apply(spec, [correction])

    text = formatter.format_spec(corrected, corrections.notes(results))
    (noted,) = [line for line in text.splitlines() if ";;" in line]
    assert noted == f'; Note: "clause 6.1 says" ;; corrected: ({correction.id})'

    removed, results = corrections.apply(
        spec,
        [_correction(corrections.undefined("Mystery"), "note", '"a mystery"', None)],
    )
    text = formatter.format_spec(removed, corrections.notes(results))
    (noted,) = [line for line in text.splitlines() if ";;" in line]
    assert noted.startswith("; Type: Undefined AVP ;; corrected:")

    deleted, results = corrections.apply(
        spec,
        [_delete(corrections.undefined("Mystery"), _undefined())],
    )
    assert not any(isinstance(s, ast.UndefinedAvp) for s in deleted.sections)
    text = formatter.format_spec(deleted, corrections.notes(results))
    assert text.endswith(
        f";; deleted: undefined AVP 'Mystery' ({results[0].correction.cited})\n"
    )


def _repeated_session_id(spec: ast.Specification) -> ast.Specification:
    """TS 29.229 clause 6.1.10's RTA shape: one rule printed twice."""
    message = _message(spec)
    repeated = message.model_copy(
        update={
            "avps": (
                *message.avps,
                ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),
            )
        }
    )
    return spec.model_copy(update={"sections": (repeated, *spec.sections[1:])})


_SESSION_ID = ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED)


def test_an_occurrence_deletes_one_copy_of_a_repeated_rule():
    target = corrections.avp_rule("Example-Request", "Session-Id", occurrence=2)

    corrected, results = corrections.apply(
        _repeated_session_id(_spec()), [_delete(target, _SESSION_ID)]
    )

    assert _message(corrected).avps == (_SESSION_ID,)
    assert results[0].node == (
        "AVP rule 'Session-Id' (occurrence 2) in definition 'Example-Request'"
    )


def test_without_an_occurrence_a_repeated_rule_is_ambiguous():
    with pytest.raises(corrections.CorrectionError, match="2 matches, narrow"):
        corrections.apply(
            _repeated_session_id(_spec()),
            [
                _delete(
                    corrections.avp_rule("Example-Request", "Session-Id"), _SESSION_ID
                )
            ],
        )


@pytest.mark.parametrize("occurrence", [1, 2], ids=["first", "second"])
def test_an_occurrence_fails_once_the_rule_is_no_longer_repeated(occurrence):
    """Upstream dropping the copy is the event the declaration exists to
    report, so even the first occurrence stops matching."""
    target = corrections.avp_rule(
        "Example-Request", "Session-Id", occurrence=occurrence
    )

    with pytest.raises(corrections.CorrectionError, match="no match"):
        corrections.apply(_spec(), [_delete(target, _SESSION_ID)])


def test_an_occurrence_counts_from_one():
    with pytest.raises(corrections.CorrectionError, match="counts from 1"):
        corrections.avp_rule("Example-Request", "Session-Id", occurrence=0)


_OFF = ast.EnumValue(name="Off", value=0)


def _repeated_off(spec: ast.Specification) -> ast.Specification:
    """RFC 4005 clause 6.1's shape: a value listed, then listed again."""
    enumerated = spec.sections[2]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    repeated = enumerated.model_copy(update={"values": (_OFF, _OFF)})
    return spec.model_copy(update={"sections": (*spec.sections[:2], repeated)})


def test_an_occurrence_deletes_one_copy_of_a_repeated_value():
    target = corrections.enum_value("Example-Mode", "Off", value=0, occurrence=2)

    corrected, results = corrections.apply(
        _repeated_off(_spec()), [_delete(target, _OFF)]
    )

    enumerated = corrected.sections[2]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.values == (_OFF,)
    assert results[0].node == ("value 'Off' of 'Example-Mode' (= 0) (occurrence 2)")


def test_a_value_occurrence_fails_once_the_value_is_no_longer_repeated():
    target = corrections.enum_value("Example-Mode", "Off", occurrence=1)

    with pytest.raises(corrections.CorrectionError, match="no match"):
        corrections.apply(_spec(), [_delete(target, _OFF)])


def test_a_value_occurrence_counts_from_one():
    with pytest.raises(corrections.CorrectionError, match="counts from 1"):
        corrections.enum_value("Example-Mode", "Off", occurrence=0)


def test_the_file_header_cannot_be_deleted():
    # The root stands in no tuple, so there is no place for the deletion's
    # note and nothing the corrected tree could leave out.
    spec = _spec()

    with pytest.raises(corrections.CorrectionError, match="can be deleted"):
        corrections.apply(spec, [_delete(corrections.header(), spec)])


def test_deleting_the_same_node_twice_is_refused():
    doomed = ast.ReusedAvpRow(name="Feature-Id", origin="TS29.229")
    delete = _delete(corrections.reused_row("Feature-Id"), doomed)

    with pytest.raises(corrections.CorrectionError, match="deleted more than once"):
        corrections.apply(_with_reused(_spec()), [delete, delete])


def test_deleting_a_tables_last_row_fails_its_own_invariant():
    # An empty table means the extractor found a caption and lost the
    # contents; a deletion may not manufacture that state.
    with pytest.raises(corrections.CorrectionError, match="not valid"):
        corrections.apply(
            _spec(),
            [
                _delete(
                    corrections.table_row("Example-Mode"),
                    ast.AvpTableRow(
                        name="Example-Mode",
                        code=1600,
                        section="6.3.2",
                        data_type=ast.DataType.ENUMERATED,
                        may_encrypt=False,
                    ),
                )
            ],
        )


def test_correcting_a_node_inside_a_deleted_subtree_is_refused():
    spec = _spec()
    message = _message(spec)

    with pytest.raises(corrections.CorrectionError, match="another edit deleted"):
        corrections.apply(
            spec,
            [
                _delete(corrections.definition("Example-Request"), message),
                _correction(
                    corrections.avp_rule("Example-Request", "Session-Id"),
                    "bold",
                    False,
                    True,
                ),
            ],
        )


_MODULES = sorted((_ROOT / "edits" / "corrections").glob("*.py"))


@pytest.mark.parametrize("path", _MODULES, ids=lambda path: path.name)
def test_no_committed_reason_keeps_an_unformatted_placeholder(path):
    """A reason built from a shared fragment needs its `f` prefix; without it
    RFC 4590's forty flag-rule reasons cited a literal `{_WIRESHARK}`."""
    declared = corrections.load(path.parent, path.stem)

    unformatted = [each.id for each in declared if "{" in each.reason]

    assert declared
    assert unformatted == []


@pytest.mark.parametrize("raw", _corpus(raw=True), ids=lambda path: path.name)
def test_committed_corrections_still_apply_to_committed_raw_output(raw):
    """The rot check that makes the layer worth having: if a re-extraction or a
    spec bump changes what a correction expects, this fails. Committing the raw
    file is what lets it run without the source documents."""
    spec = parser.parse(raw.read_text(encoding="utf-8"))
    declared = corrections.in_release(
        corrections.load(_ROOT / "edits" / "corrections", spec.specification),
        spec.version,
    )

    corrected, results = corrections.apply(spec, declared)

    assert len(results) == len(corrections.edits(declared))
    assert parser.parse(formatter.format_spec(corrected)) == corrected


@pytest.mark.parametrize("raw", _corpus(raw=True), ids=lambda path: path.name)
def test_correction_notes_mark_the_same_lines_in_a_copied_or_reparsed_tree(raw):
    """Notes are keyed by tree path, so they belong to a place rather than to
    the objects `apply` built: formatting a deep copy of the corrected tree,
    or the tree parsed back from the corrected file, with the same notes
    gives the committed corrected file. The raw file's own comments, TS
    32.299's commented-out struck members, move with their lines."""
    spec, comments = parser.parse_with_comments(raw.read_text(encoding="utf-8"))
    declared = corrections.in_release(
        corrections.load(_ROOT / "edits" / "corrections", spec.specification),
        spec.version,
    )
    corrected, _, notes = corrections.apply_with_comments(spec, comments, declared)
    committed = (_CORPUS_DIR / raw.relative_to(_CORPUS_DIR / "raw")).with_name(
        raw.name.removesuffix(".raw.dad") + ".dad"
    )
    text = committed.read_text(encoding="utf-8")

    assert formatter.format_spec(corrected, notes) == text
    assert formatter.format_spec(copy.deepcopy(corrected), notes) == text
    assert formatter.format_spec(parser.parse(text), notes) == text


@pytest.mark.parametrize("path", _corpus(raw=False), ids=lambda path: path.name)
def test_every_corrected_file_already_carries_its_corrections(path):
    """The committed pair has to agree: the corrected file is what the raw file
    plus the module produces, so every `replace` is already the value in it and
    correcting it again must fail."""
    spec = parser.parse(path.read_text(encoding="utf-8"))
    declared = corrections.edits(
        corrections.in_release(
            corrections.load(_ROOT / "edits" / "corrections", spec.specification),
            spec.version,
        )
    )

    # A name correction rewrites what every *sibling* correction's selector
    # matches on too: 29.338 fixes the name and the code of one misprinted
    # AVP-header line, and 32.299 the name and the origin of one re-used row;
    # in the corrected file both live under the new name.
    renamed = {
        c.target: c.replace
        for c in declared
        if isinstance(c, corrections.Correction) and c.field == "name"
    }

    for correction in declared:
        if isinstance(correction, corrections.Insert):
            (table,) = correction.into.find(spec)
            if isinstance(table, ast.Specification):
                assert correction.node in table.sections
                continue
            if isinstance(table, ast.Message | ast.GroupedAvp):
                assert correction.node in table.avps
                continue
            if isinstance(table, ast.EnumeratedAvp):
                assert correction.node in table.values
                continue
            assert isinstance(table, ast.AvpTable | ast.ReusedAvps | ast.ValueTable)
            assert correction.node in table.rows
            continue
        target = correction.target
        if isinstance(correction, corrections.Delete):
            # A deleted node's mark of success is its absence.
            assert list(target.find(spec)) == [], f"{target.describe()} in {path.name}"
            continue
        if isinstance(correction, corrections.Supply):
            (supplied,) = target.find(spec)
            if isinstance(supplied, ast.AvpTableRow):
                # Each supplies what the row leaves blank: TS 32.299's clause
                # 7.2.50 types DCD-Information itself, and OMA only flags it.
                for field in ("data_type", "flag_rules"):
                    if (value := getattr(correction, field)) is not None:
                        assert getattr(supplied, field) == value
                continue
            assert isinstance(supplied, ast.EnumeratedAvp)
            # Extending, the supplied values follow the printed ones.
            tail = supplied.values[len(supplied.values) - len(correction.values) :]
            assert tail == correction.values
            continue
        if correction.field == "name":
            # A correction that rewrites a name also rewrites what the selector
            # matches on, so in the corrected file the node answers to the
            # replacement. 29.172, 29.344 and 29.388 all fix a copied-in rule
            # name this way.
            target = dataclasses.replace(target, name=correction.replace)
        elif correction.field == "avp":
            # The same for the AVP a value table's selector matches on: TS
            # 29.337 corrects the "Supported-Feature-List" its clause heads.
            target = dataclasses.replace(target, avp=correction.replace)
        elif target in renamed:
            target = dataclasses.replace(target, name=renamed[target])
        matches = list(target.find(spec))
        assert len(matches) == 1, f"{target.describe()} in {path.name}"
        assert getattr(matches[0], correction.field) == correction.replace

    if declared:
        with pytest.raises(corrections.CorrectionError):
            corrections.apply(spec, declared)


def _fields(spec: ast.Specification) -> tuple[dict[tuple, object], dict[tuple, object]]:
    """Every leaf field of every node, keyed by its structural path — indices
    and field names only, so a corrected `name` moves a value rather than the
    key — plus each node's human label for reporting."""
    flat: dict[tuple, object] = {}
    labels: dict[tuple, object] = {}

    def walk(node, path):
        if isinstance(node, ast.Node):
            labels[path] = getattr(node, "name", None) or getattr(node, "table", None)
            for field in type(node).model_fields:
                walk(getattr(node, field), (*path, field))
        elif isinstance(node, tuple):
            for index, item in enumerate(node):
                walk(item, (*path, index))
        else:
            flat[path] = node

    walk(spec, ())
    return flat, labels


def test_the_ts29272_corrections_change_exactly_the_declared_fields():
    """The intended semantic diff, pinned independently of the correction file.

    The rot check above reads its expectation out of the correction it is
    testing, so a wrong `expect`/`replace`/reason changed together stays green.
    This one names the outcome — one AVP code, one missing vendor-id, two
    respelled names and TS 29.217's two eNodeB spellings (each in a re-used
    row and a body, one label here), the feature and bit names a wrapped cell
    spaces, nothing else, plus the inserted rows and the VCSG application scope
    — so changing what the corrections do has to be a deliberate edit here too.
    """
    raw = _CORPUS_DIR / "raw" / "3gpp" / "rel-19" / "29272-j60.raw.dad"
    spec = parser.parse(raw.read_text(encoding="utf-8"))
    declared = corrections.in_release(
        corrections.load(_ROOT / "edits" / "corrections", spec.specification),
        spec.version,
    )

    # Inserted rows shift every row index after them, which would drown the
    # field-level pin below in artifacts of renumbering; they are pinned
    # separately, by content, at the end.
    inserted = [c for c in declared if isinstance(c, corrections.Insert)]
    # Supplied values add nodes too, and are pinned by count at the end.
    supplied = [c for c in declared if isinstance(c, corrections.Supply)]
    edits = (corrections.Insert, corrections.Supply)
    declared = [c for c in declared if not isinstance(c, edits)]
    corrected, _ = corrections.apply(spec, declared)

    before, labels = _fields(spec)
    after, _ = _fields(corrected)
    changed = {
        path: (before[path], after[path])
        for path in before
        if before[path] != after[path]
    }
    assert set(before) == set(after)  # no node added or removed
    # path[:-1] is the node's own path, path[-1] the field; labels come from
    # the raw tree, so a renamed node reports under its misprinted name.
    assert {
        (labels[path[:-1]], path[-1], *value) for path, value in changed.items()
    } == {
        # Alert-Reason's misspelled type is an input patch, not a correction:
        # a closed `data_type` means the raw file cannot carry "Enumerate" as
        # far as this layer.
        ("Area-Scope", "code", 1623, 1624),
        ("WLAN-offloadability", "vendor_id", None, 10415),
        (
            "Additional-Context-ID",
            "name",
            "Additional-Context-ID",
            "Additional-Context-Identifier",
        ),
        (
            "Re-synchronization-Info",
            "name",
            "Re-synchronization-Info",
            "Re-Synchronization-Info",
        ),
        ("eNodeB-ID", "name", "eNodeB-ID", "eNodeB-Id"),
        ("Extended-eNodeB-ID", "name", "Extended-eNodeB-ID", "Extended-eNodeB-Id"),
        *(
            (spaced, "name", spaced, spaced.replace("- ", "-").replace(" -", "-"))
            for spaced in (
                "ODB-all- InternationalOG",
                "LCS- BasicSelfLocation",
                "LCS- AutonomousSelfLocation",
                "LCS- TransferToThirdParty",
                "Dia-LCS- BasicSelfLocation",
                "Dia-LCS- AutonomousSelfLocation",
                "Dia-LCS- TransferToThirdParty",
                "eDRX-Cycle-Length -Withdrawal",
            )
        ),
    }
    (block,) = [c.node for c in inserted if isinstance(c.into, corrections.header)]
    assert block == ast.ApplicationScope(
        name="S7a/S7d",
        source=ast.SourceRef(section="7.2.2", page=73),
        application_id=16777308,
        applies_to=("7.2.21.*", "7.2.22.*", "7.2.23.*", "7.2.24.*"),
    )
    inserted_rows = set()
    for correction in inserted:
        if isinstance(correction.into, corrections.header):
            continue
        assert isinstance(correction.node, ast.ReusedAvpRow)
        assert isinstance(correction.into, corrections.reused_avps)
        inserted_rows.add(
            (correction.into.label, correction.node.name, correction.node.origin)
        )
    assert inserted_rows == {
        ("7.3.1/2", "MIP6-Home-Link-Prefix", "RFC5447"),
        ("7.3.1/2", "ProSe-Permission", "TS29.344"),
        ("7.3.1/2", "Periodic-Communication-Indicator", "TS29.336"),
        ("7.3.1/2", "Communication-Duration-Time", "TS29.336"),
        ("7.3.1/2", "Periodic-Time", "TS29.336"),
        ("7.3.1/2", "Scheduled-Communication-Time", "TS29.336"),
        ("7.3.1/2", "Stationary-Indication", "TS29.336"),
    }
    # TS 32.422's trace parameters, all but Report-Interval.
    assert {
        correction.target.name: len(correction.values)
        for correction in supplied
        if isinstance(correction.target, corrections.definition)
    } == {
        "Trace-Depth": 9,
        "Job-Type": 13,
        "Report-Amount": 8,
        "Logging-Interval": 11,
        "Logging-Duration": 6,
        "Measurement-Period-LTE": 5,
        "Measurement-Period-UMTS": 13,
        "Collection-Period-RRM-LTE": 10,
        "Collection-Period-RRM-UMTS": 8,
        "Collection-Period-RRM-NR": 5,
        "Collection-Period-M6-NR": 14,
    }


def test_loading_rejects_a_module_without_corrections(tmp_path):
    (tmp_path / "TS29.999.py").write_text("SOMETHING_ELSE = []\n")

    with pytest.raises(corrections.CorrectionError, match="no CORRECTIONS list"):
        corrections.load(tmp_path, "3GPP TS 29.999")


def test_loading_rejects_corrections_of_the_wrong_type(tmp_path):
    (tmp_path / "TS29.999.py").write_text("CORRECTIONS = ['not a correction']\n")

    with pytest.raises(corrections.CorrectionError, match="must hold Correction"):
        corrections.load(tmp_path, "3GPP TS 29.999")


def test_loading_rejects_a_generator_rather_than_silently_consuming_it(tmp_path):
    # `all(...)` over a generator leaves it exhausted, so the list built after
    # it used to come out empty — a spec silently corrected by nothing.
    (tmp_path / "TS29.999.py").write_text(
        "from seanchai.dad.corrections import Correction, table_row\n"
        "CORRECTIONS = (c for c in [Correction(id='x',"
        " target=table_row('Example-Mode'),"
        " field='code', expect=1600, replace=1602, reason='typo')])\n"
    )

    with pytest.raises(corrections.CorrectionError, match="must be a list"):
        corrections.load(tmp_path, "3GPP TS 29.999")


def test_loading_reports_a_module_that_fails_to_import(tmp_path):
    (tmp_path / "TS29.999.py").write_text("import nonexistent_module_for_tests\n")

    with pytest.raises(corrections.CorrectionError, match="failed to import"):
        corrections.load(tmp_path, "3GPP TS 29.999")


@pytest.mark.parametrize(
    "specification",
    [
        "3GPP TS ../outside",
        "/etc/passwd",
        r"..\outside",
        "3GPP TS 29.9999",
        "",
    ],
    ids=["relative", "absolute", "windows-separator", "malformed", "empty"],
)
def test_a_specification_header_cannot_name_a_module_outside_the_directory(
    tmp_path, specification
):
    # `; Specification:` comes from a parsed file, and loading its module runs
    # Python. Nothing but a canonical document reference may name that file.
    (tmp_path.parent / "outside.py").write_text("CORRECTIONS = []\n")
    directory = tmp_path / "corrections"
    directory.mkdir()

    with pytest.raises(corrections.CorrectionError, match="supported document"):
        corrections.load(directory, specification)


def test_a_required_load_fails_when_the_module_is_missing_or_empty(tmp_path):
    # `seanchai correct` asked for this specification's corrections; producing
    # an uncorrected file and calling it a success is the failure mode.
    with pytest.raises(corrections.CorrectionError, match="no corrections module"):
        corrections.load(tmp_path, "3GPP TS 29.999", required=True)

    (tmp_path / "TS29.999.py").write_text("CORRECTIONS = []\n")

    with pytest.raises(corrections.CorrectionError, match="declares no corrections"):
        corrections.load(tmp_path, "3GPP TS 29.999", required=True)

    # The same two states are ordinary results for a corpus-wide extraction.
    assert corrections.load(tmp_path, "3GPP TS 29.999") == []
    assert corrections.load(tmp_path, "3GPP TS 29.998") == []


def test_a_module_may_declare_a_supply(tmp_path):
    (tmp_path / "TS29.999.py").write_text(
        "from seanchai.dad import ast\n"
        "from seanchai.dad.corrections import Supply, definition\n"
        "CORRECTIONS = [Supply(id='mode-values', target=definition('Example-Mode'),"
        " expect='TS 29.998 [1]', values=[ast.EnumValue(name='Off', value=0)],"
        " reason='r')]\n"
    )

    (supply,) = corrections.load(tmp_path, "3GPP TS 29.999")

    assert isinstance(supply, corrections.Supply)
    assert supply.cited == "TS29.999.py#mode-values"
    assert supply.values == (ast.EnumValue(name="Off", value=0),)


def test_an_acceptance_is_declared_beside_corrections_and_changes_nothing(
    tmp_path,
):
    (tmp_path / "TS29.999.py").write_text(
        "from seanchai.dad.corrections import Accept, definition\n"
        "CORRECTIONS = [Accept(id='mode-body', rule='reused-body-differs',"
        " target=definition('Example-Mode'), expect='a message',"
        " reason='clause 6.3.2 prints its own body')]\n"
    )

    (accept,) = corrections.load(tmp_path, "3GPP TS 29.999")
    spec = ast.Specification(
        specification="3GPP TS 29.999", vendor_id=10415, sections=()
    )

    assert isinstance(accept, corrections.Accept)
    assert accept.cited == "TS29.999.py#mode-body"
    assert corrections.apply(spec, [accept]) == (spec, [])
    # Nothing to correct is what `seanchai correct` refuses.
    with pytest.raises(corrections.CorrectionError, match="declares no corrections"):
        corrections.load(tmp_path, "3GPP TS 29.999", required=True)


def test_loaded_corrections_cite_their_module_and_a_unique_id():
    declared = corrections.load(_ROOT / "edits" / "corrections", "3GPP TS 29.272")

    assert all(c.cited == f"TS29.272.py#{c.id}" for c in declared)
    assert len({c.id for c in declared}) == len(declared)


@pytest.mark.parametrize(
    ("module", "message"),
    [
        (
            "CORRECTIONS = [Correction(id='Bad Id', target=table_row('A'),"
            " field='code', expect=1, replace=2, reason='r')]\n",
            "not a lowercase kebab-case name",
        ),
        (
            "CORRECTIONS = [Correction(id='same', target=table_row('A'),"
            " field='code', expect=1, replace=2, reason='r'),"
            " Correction(id='same', target=table_row('B'),"
            " field='code', expect=1, replace=2, reason='r')]\n",
            "declared twice",
        ),
    ],
    ids=["malformed", "duplicate"],
)
def test_a_malformed_or_repeated_id_is_rejected(tmp_path, module, message):
    (tmp_path / "TS29.999.py").write_text(
        "from seanchai.dad.corrections import Correction, table_row\n" + module
    )

    with pytest.raises(corrections.CorrectionError, match=message):
        corrections.load(tmp_path, "3GPP TS 29.999")


_COMMENTED = """\
; Specification: 3GPP TS 29.999
; Version: 1.2.3
; Vendor-ID: 10415


; Type: Message
; Name: Example-Request, EXR
; Section: 6.1
<Example-Request> ::= < Diameter Header: 321, REQ > ;; printed without an id
        < Session-Id >
;;      [ Struck-Before ] ; strikethrough
        { Origin-Host }
;;      [ Struck-After ]  ; strikethrough
        { Origin-Realm }
        [ Last ]
;;      [ Struck-End ]    ; strikethrough


; Type: Enumerated AVP ;; from clause 6.3.2
; Name: Example-Mode
; Section: 6.3.2
Example-Mode ::= < Enumerated AVP header: 1600 10415 >
        ;; one value
        Off = 0 ;; the only value
"""


def test_a_files_comments_move_with_their_lines_through_the_edits():
    """TS 32.299's struck members are commented out of their bodies; a
    correction inserting or deleting around them must leave each where it
    stood."""
    spec, comments = parser.parse_with_comments(_COMMENTED)
    message, enumerated = spec.sections
    assert isinstance(message, ast.Message)
    scope = ast.ApplicationScope(
        name="Example",
        source=ast.SourceRef(section="6"),
        application_id=7,
        applies_to=("6.*",),
    )
    edits = [
        corrections.Insert(
            id="scope", into=corrections.header(), node=scope, after=None, reason="t"
        ),
        _correction(
            corrections.definition("Example-Request"), "application_id", None, 7
        ),
        corrections.Delete(
            id="host",
            target=corrections.avp_rule("Example-Request", "Origin-Host"),
            expect=message.avps[1],
            reason="t",
        ),
        corrections.Delete(
            id="last",
            target=corrections.avp_rule("Example-Request", "Last"),
            expect=message.avps[3],
            reason="t",
        ),
        corrections.Delete(
            id="mode",
            target=corrections.definition("Example-Mode"),
            expect=enumerated,
            reason="t",
        ),
    ]

    corrected, _, merged = corrections.apply_with_comments(spec, comments, edits)

    text = formatter.format_spec(corrected, merged)
    corrected_id = edits[1].id
    assert text.split("\n\n\n")[2:] == [
        "\n".join(
            [
                "; Type: Message",
                "; Name: Example-Request, EXR",
                "; Section: 6.1",
                "<Example-Request> ::= < Diameter Header: 321, REQ, 7 >"
                f" ;; printed without an id ;; corrected: ({corrected_id})",
                "        < Session-Id >",
                # Before the deleted line, then the deletion, then after it.
                ";;      [ Struck-Before ] ; strikethrough",
                ";; deleted: AVP rule 'Origin-Host' (host)",
                ";;      [ Struck-After ]  ; strikethrough",
                "        { Origin-Realm }",
                ";; deleted: AVP rule 'Last' (last)",
                ";;      [ Struck-End ]    ; strikethrough",
            ]
        ),
        # A deleted section's comments are a block where it stood, in the
        # order they printed.
        "\n".join(
            [
                ";; from clause 6.3.2",
                ";; one value",
                ";; the only value",
                ";; deleted: definition 'Example-Mode' (mode)",
                "",
            ]
        ),
    ]
    assert parser.parse(text) == corrected
    assert formatter.format_spec(*parser.parse_with_comments(text)) == text


def test_without_comments_apply_with_comments_gives_the_notes():
    spec = _spec()
    edits = [
        corrections.Delete(
            id="session-id",
            target=corrections.avp_rule("Example-Request", "Session-Id"),
            expect=_message(spec).avps[0],
            reason="t",
        )
    ]

    corrected, results, merged = corrections.apply_with_comments(
        spec, formatter.Comments(), edits
    )

    assert (corrected, results) == corrections.apply(spec, edits)
    assert merged == corrections.notes(results)


def test_a_comment_block_ending_the_file_stays_at_its_end():
    text = _COMMENTED + "\n\n;; end of file\n"
    spec, comments = parser.parse_with_comments(text)

    unchanged, _, kept = corrections.apply_with_comments(spec, comments, [])

    assert formatter.format_spec(unchanged, kept) == text
    # After the note of a deleted last section, which stood before it.
    enumerated = spec.sections[1]
    deleted, _, kept = corrections.apply_with_comments(
        spec,
        comments,
        [
            corrections.Delete(
                id="mode",
                target=corrections.definition("Example-Mode"),
                expect=enumerated,
                reason="t",
            )
        ],
    )
    assert formatter.format_spec(deleted, kept).endswith(
        ";; deleted: definition 'Example-Mode' (mode)\n;; end of file\n"
    )


def test_comments_on_a_directive_line_a_correction_removes_survive():
    text = "\n".join(
        [
            "; Specification: 3GPP TS 29.999",
            "; Version: 1.2.3",
            "; Vendor-ID: 10415",
            ";; standing on the bases",
            "; Bases: RFC6733 ;; trailing on the bases",
            "",
        ]
    )
    spec, comments = parser.parse_with_comments(text)
    emptied = _correction(corrections.header(), "bases", ("RFC6733",), ())

    corrected, _, kept = corrections.apply_with_comments(spec, comments, [emptied])

    assert formatter.format_spec(corrected, kept).splitlines() == [
        ";; standing on the bases",
        "; Specification: 3GPP TS 29.999 ;; trailing on the bases"
        f" ;; corrected: ({emptied.id})",
        "; Version: 1.2.3",
        "; Vendor-ID: 10415",
    ]


def _value_tables_spec():
    return ast.Specification(
        specification="3GPP TS 29.999",
        version="1.2.3",
        vendor_id=10415,
        sections=(
            ast.ValueTable(
                avp="Supported-Feature-List",
                kind=ast.ValueKind.FEATURES,
                feature_list_id=1,
                application="T4",
                table="6.3.5",
                source=ast.SourceRef(section="6.3.5"),
                rows=(ast.ValueRow(name="LCS- Basic", value=0, mark="O"),),
            ),
            ast.ValueTable(
                avp="Experimental-Result-Code",
                kind=ast.ValueKind.RESULT_CODES,
                source=ast.SourceRef(section="7"),
                rows=(
                    ast.ValueRow(name="DIAMETER_ERROR_ X", value=5001, section="7.1"),
                ),
            ),
        ),
    )


def test_a_value_table_and_its_rows_are_corrected_and_cited_on_their_lines():
    edits = [
        corrections.Correction(
            id="avp",
            target=corrections.value_table("Supported-Feature-List", feature_list_id=1),
            field="avp",
            expect="Supported-Feature-List",
            replace="Feature-List",
            reason="r",
        ),
        corrections.Correction(
            id="spelling",
            target=corrections.value_row(
                corrections.value_table("Experimental-Result-Code", section="7"),
                "DIAMETER_ERROR_ X",
                5001,
            ),
            field="name",
            expect="DIAMETER_ERROR_ X",
            replace="DIAMETER_ERROR_X",
            reason="r",
        ),
        corrections.Insert(
            id="row",
            into=corrections.value_table("Experimental-Result-Code"),
            node=ast.ValueRow(name="DIAMETER_ERROR_Y", value=5002),
            after="DIAMETER_ERROR_ X",
            reason="r",
        ),
    ]

    corrected, results = corrections.apply(_value_tables_spec(), edits)

    features, codes = [
        section for section in corrected.sections if isinstance(section, ast.ValueTable)
    ]
    assert features.avp == "Feature-List"
    assert [row.name for row in codes.rows] == [
        "DIAMETER_ERROR_X",
        "DIAMETER_ERROR_Y",
    ]
    text = formatter.format_spec(corrected, corrections.notes(results))
    assert "; AVP: Feature-List ;; corrected: (avp)" in text
    assert "DIAMETER_ERROR_X = 5001 ; 7.1 ;; corrected: (spelling)" in text
    assert "DIAMETER_ERROR_Y = 5002 ;; inserted: (row)" in text
    assert parser.parse(text) == corrected


def test_a_value_row_correction_expects_what_the_row_holds():
    wrong = corrections.Correction(
        id="spelling",
        target=corrections.value_row("Experimental-Result-Code", "DIAMETER_ERROR_ X"),
        field="value",
        expect=9,
        replace=5001,
        reason="r",
    )

    with pytest.raises(corrections.CorrectionError, match="expect"):
        corrections.apply(_value_tables_spec(), [wrong])
