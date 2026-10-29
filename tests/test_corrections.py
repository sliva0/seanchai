import copy
import dataclasses
import itertools
from pathlib import Path

import pytest
from conftest import _corpus

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


@pytest.mark.parametrize("raw", _corpus(raw=True), ids=lambda path: path.name)
def test_committed_corrections_still_apply_to_committed_raw_output(raw):
    """The rot check that makes the layer worth having: if a re-extraction or a
    spec bump changes what a correction expects, this fails. Committing the raw
    file is what lets it run without the source documents."""
    spec = parser.parse(raw.read_text(encoding="utf-8"))
    declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)

    corrected, results = corrections.apply(spec, declared)

    assert len(results) == len(declared)
    assert parser.parse(formatter.format_spec(corrected)) == corrected


@pytest.mark.parametrize("raw", _corpus(raw=True), ids=lambda path: path.name)
def test_correction_notes_mark_the_same_lines_in_a_copied_or_reparsed_tree(raw):
    """Notes are keyed by tree path, so they belong to a place rather than to
    the objects `apply` built: formatting a deep copy of the corrected tree,
    or the tree parsed back from the corrected file, with the same notes
    gives the committed corrected file."""
    spec = parser.parse(raw.read_text(encoding="utf-8"))
    declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)
    corrected, results = corrections.apply(spec, declared)
    notes = corrections.notes(results)
    committed = (_ROOT / "dad" / raw.relative_to(_ROOT / "dad" / "raw")).with_name(
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
    declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)

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
            assert isinstance(table, ast.AvpTable | ast.ReusedAvps)
            assert correction.node in table.rows
            continue
        target = correction.target
        if isinstance(correction, corrections.Delete):
            # A deleted node's mark of success is its absence.
            assert list(target.find(spec)) == [], f"{target.describe()} in {path.name}"
            continue
        if correction.field == "name":
            # A correction that rewrites a name also rewrites what the selector
            # matches on, so in the corrected file the node answers to the
            # replacement. 29.172, 29.344 and 29.388 all fix a copied-in rule
            # name this way.
            target = dataclasses.replace(target, name=correction.replace)
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
    This one names the outcome — four application ids, one AVP code, one
    missing vendor-id, two respelled names and TS 29.217's two eNodeB
    spellings (each in a re-used row and a body, one label here), nothing
    else — so changing what the corrections do has to be a deliberate edit
    here too.
    """
    raw = _ROOT / "dad" / "raw" / "3gpp" / "rel-18" / "29272-i70.raw.dad"
    spec = parser.parse(raw.read_text(encoding="utf-8"))
    declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)

    # Inserted rows shift every row index after them, which would drown the
    # field-level pin below in artifacts of renumbering; they are pinned
    # separately, by content, at the end.
    inserted = [c for c in declared if isinstance(c, corrections.Insert)]
    declared = [c for c in declared if not isinstance(c, corrections.Insert)]
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
        (name, "application_id", None, 16777308)
        for name in (
            "Update-VCSG-Location-Request",
            "Update-VCSG-Location-Answer",
            "Cancel-VCSG-Location-Request",
            "Cancel-VCSG-Location-Answer",
        )
    } | {
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
    }
    inserted_rows = set()
    for correction in inserted:
        assert isinstance(correction.node, ast.ReusedAvpRow)
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
