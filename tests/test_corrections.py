from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "reversed_order", [False, True], ids=["parent-first", "child-first"]
)
def test_a_definition_and_one_of_its_avp_rules_are_both_applied(reversed_order):
    # Rebuilding used to stop at the first replaced node it met, so whichever
    # of these was the ancestor swallowed the other without a word — two
    # successful results, one of them absent from the returned tree.
    declared = [
        _correction(
            corrections.definition("Example-Request"), "application_id", None, 16777308
        ),
        _correction(
            corrections.avp_rule("Example-Request", "Session-Id"),
            "presence",
            ast.Presence.FIXED,
            ast.Presence.REQUIRED,
        ),
    ]

    corrected, results = corrections.apply(
        _spec(), list(reversed(declared)) if reversed_order else declared
    )

    message = _message(corrected)
    assert len(results) == 2
    assert message.application_id == 16777308
    assert message.avps[0].presence is ast.Presence.REQUIRED


def test_an_enumerated_avp_and_one_of_its_values_are_both_applied():
    corrected, results = corrections.apply(
        _spec(),
        [
            _correction(corrections.definition("Example-Mode"), "code", 1600, 1602),
            _correction(corrections.enum_value("Example-Mode", "Off"), "value", 0, 7),
        ],
    )

    enumerated = corrected.sections[2]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert len(results) == 2
    assert enumerated.code == 1602
    assert enumerated.values == (ast.EnumValue(name="Off", value=7),)


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


def test_a_node_shared_by_two_places_is_refused_rather_than_corrected_twice():
    # Identity is what maps a resolved node back into the tree, so a caller
    # that hands the same object to two parents would otherwise get one
    # reported correction and two applied ones.
    spec = _spec()
    message = _message(spec)
    shared = message.model_copy(update={"application_id": 16777308})

    with pytest.raises(corrections.CorrectionError, match="more than once in the tree"):
        corrections.apply(
            spec.model_copy(update={"sections": (message, shared, *spec.sections[1:])}),
            [
                _correction(
                    # Narrowed, so the selector reports exactly one match — the
                    # object it found is nevertheless in both messages.
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


def test_the_reused_row_selector_reaches_a_reused_avps_row():
    spec = _spec()
    reused = ast.ReusedAvps(
        table="6.4",
        source=ast.SourceRef(section="6.4"),
        rows=(ast.ReusedAvpRow(name="Load", origin="RFC7683"),),
    )
    with_reused = spec.model_copy(update={"sections": (*spec.sections, reused)})

    corrected, results = corrections.apply(
        with_reused,
        [_correction(corrections.reused_row("Load"), "origin", "RFC7683", "RFC8583")],
    )

    row = corrected.sections[3]
    assert isinstance(row, ast.ReusedAvps)
    assert row.rows[0].origin == "RFC8583"
    assert results[0].node == "re-used AVPs row 'Load'"


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


def _corpus(*, raw: bool):
    """Committed files of one kind. `rglob("*.dad")` matches `.raw.dad` too,
    so the two are told apart by suffix rather than by glob."""
    paths = [
        path
        for path in sorted((_ROOT / "dad").rglob("*.dad"))
        if path.name.endswith(".raw.dad") == raw
    ]
    assert paths, "no committed .dad files found — these tests would pass vacuously"
    return paths


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


@pytest.mark.parametrize("path", _corpus(raw=False), ids=lambda path: path.name)
def test_every_corrected_file_already_carries_its_corrections(path):
    """The committed pair has to agree: the corrected file is what the raw file
    plus the module produces, so every `replace` is already the value in it and
    correcting it again must fail."""
    spec = parser.parse(path.read_text(encoding="utf-8"))
    declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)

    for correction in declared:
        matches = list(correction.target.find(spec))
        assert len(matches) == 1, f"{correction.target.describe()} in {path.name}"
        assert getattr(matches[0], correction.field) == correction.replace

    if declared:
        with pytest.raises(corrections.CorrectionError):
            corrections.apply(spec, declared)


def _fields(spec: ast.Specification) -> dict[tuple, object]:
    """Every leaf field of every node, keyed by its path through the tree."""
    flat: dict[tuple, object] = {}

    def walk(node, path):
        if isinstance(node, ast.Node):
            key = getattr(node, "name", None) or getattr(node, "table", None)
            for field in type(node).model_fields:
                walk(getattr(node, field), (*path, key, field))
        elif isinstance(node, tuple):
            for index, item in enumerate(node):
                walk(item, (*path, index))
        else:
            flat[path] = node

    walk(spec, ())
    return flat


def test_the_ts29272_corrections_change_exactly_the_declared_fields():
    """The intended semantic diff, pinned independently of the correction file.

    The rot check above reads its expectation out of the correction it is
    testing, so a wrong `expect`/`replace`/reason changed together stays green.
    This one names the outcome — four application ids, one misspelled table
    type and one AVP code, nothing else — so changing what the corrections do
    has to be a deliberate edit here too.
    """
    raw = _ROOT / "dad" / "3gpp" / "rel-18" / "29272-i60.raw.dad"
    spec = parser.parse(raw.read_text(encoding="utf-8"))
    declared = corrections.load(_ROOT / "edits" / "corrections", spec.specification)

    corrected, _ = corrections.apply(spec, declared)

    before, after = _fields(spec), _fields(corrected)
    changed = {
        path: (before[path], after[path])
        for path in before
        if before[path] != after[path]
    }
    assert set(before) == set(after)  # no node added, removed or renamed
    # path[-2] is the node's own name, path[-1] the field.
    assert {(*path[-2:], *value) for path, value in changed.items()} == {
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
        "CORRECTIONS = (c for c in [Correction(target=table_row('Example-Mode'),"
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


def test_a_valid_reference_still_resolves_inside_the_directory(tmp_path):
    (tmp_path / "TS29.272.py").write_text("CORRECTIONS = []\n")

    assert corrections.load(tmp_path, "3GPP TS 29.272") == []


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


def test_a_correction_records_where_it_was_declared():
    """So a corrected file can cite the declaration rather than making a reader
    grep the corpus for the value they do not believe."""
    correction = _correction(corrections.table_row("Example-Mode"), "code", 1600, 1602)

    path, _, line = correction.origin.rpartition(":")

    assert path.endswith("test_corrections.py")
    assert line.isdigit()


def test_origin_is_the_declaration_site_not_this_module():
    """A `Correction` built inside a helper or a comprehension must still cite
    the corrections file, which is why the frame is walked rather than taken at
    a fixed depth."""
    declared = corrections.load(_ROOT / "edits" / "corrections", "3GPP TS 29.272")

    assert all(c.origin.startswith("edits/corrections/TS29.272.py:") for c in declared)


def test_apply_reports_the_corrected_node_in_the_returned_tree():
    """`node_id` has to name a node of the *rebuilt* tree: rebuilding
    constructs new objects, so the identity a correction was resolved by is
    gone by the time a formatter could use it."""
    spec = _spec()
    corrected, (result,) = corrections.apply(
        spec, [_correction(corrections.table_row("Example-Mode"), "code", 1600, 1602)]
    )

    assert result.node_id == id(_table(corrected).rows[0])
    assert result.node_id != id(_table(spec).rows[0])
