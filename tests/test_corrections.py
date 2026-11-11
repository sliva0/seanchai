"""The committed corrections against the committed corpus, and how a
correction fails once the document moves on (docs/corrections.md)."""

import copy
import dataclasses
import itertools

import pytest
from conftest import _CORPUS_DIR, _ROOT, _corpus

from seanchai.dad import ast, corrections, formatter, parser
from seanchai.dad.corrections import (
    Correction,
    CorrectionError,
    Delete,
    Insert,
    Supply,
    avp_rule,
    avp_table,
    definition,
    enum_value,
    header,
    reused_avps,
    reused_row,
    table_row,
    undefined,
)

_CORRECTIONS = _ROOT / "edits" / "corrections"


def _declared(spec: ast.Specification) -> list[corrections.Declaration]:
    return corrections.in_release(
        corrections.load(_CORRECTIONS, spec.specification), spec.version
    )


# --- the committed corrections -----------------------------------------------


@pytest.mark.parametrize("raw", _corpus(raw=True), ids=lambda path: path.name)
def test_committed_corrections_reproduce_the_committed_corrected_file(raw):
    """The rot check that makes the layer worth having: if a re-extraction or a
    spec bump changes what a correction expects, this fails. Notes are keyed
    by tree path, so a deep copy of the corrected tree, or the tree parsed
    back from the corrected file, formats with them to the same file. The raw
    file's own comments, TS 32.299's struck members, move with their lines."""
    spec, comments = parser.parse_with_comments(raw.read_text(encoding="utf-8"))
    declared = _declared(spec)
    corrected, results, notes = corrections.apply_with_comments(
        spec, comments, declared
    )
    committed = (_CORPUS_DIR / raw.relative_to(_CORPUS_DIR / "raw")).with_name(
        raw.name.removesuffix(".raw.dad") + ".dad"
    )
    text = committed.read_text(encoding="utf-8")

    assert len(results) == len(corrections.edits(declared))
    assert formatter.format_spec(corrected, notes) == text
    assert formatter.format_spec(copy.deepcopy(corrected), notes) == text
    assert formatter.format_spec(parser.parse(text), notes) == text


@pytest.mark.parametrize("path", _corpus(raw=False), ids=lambda path: path.name)
def test_every_corrected_file_already_carries_its_corrections(path):
    """The committed pair has to agree: the corrected file is what the raw file
    plus the module produces, so every `replace` is already the value in it and
    correcting it again must fail."""
    spec = parser.parse(path.read_text(encoding="utf-8"))
    declared = corrections.edits(_declared(spec))

    # A name correction rewrites what every *sibling* correction's selector
    # matches on too: 29.338 fixes the name and the code of one misprinted
    # AVP-header line, and 32.299 the name and the origin of one re-used row;
    # in the corrected file both live under the new name.
    def named(selector: corrections.Selector) -> bool:
        # A registry row is selected by its code, which a rename leaves.
        return "name" in {field.name for field in dataclasses.fields(selector)}

    renamed = {
        c.target: c.replace
        for c in declared
        if isinstance(c, Correction) and c.field == "name" and named(c.target)
    }

    for correction in declared:
        if isinstance(correction, Insert):
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
        if isinstance(correction, Delete):
            # A deleted node's mark of success is its absence.
            assert list(target.find(spec)) == [], f"{target.describe()} in {path.name}"
            continue
        if isinstance(correction, Supply):
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
        if correction.field == "name" and named(target):
            # A correction that rewrites a name also rewrites what the selector
            # matches on, so in the corrected file the node answers to the
            # replacement. 29.172, 29.344 and 29.388 all fix a copied-in rule
            # name this way; a registry row is selected by its code instead.
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
        with pytest.raises(CorrectionError):
            corrections.apply(spec, declared)


@pytest.mark.parametrize(
    "path", sorted(_CORRECTIONS.glob("*.py")), ids=lambda path: path.name
)
def test_no_committed_reason_keeps_an_unformatted_placeholder(path):
    """A reason built from a shared fragment needs its `f` prefix; without it
    RFC 4590's forty flag-rule reasons cited a literal `{_WIRESHARK}`."""
    declared = corrections.load(path.parent, path.stem)

    assert declared
    assert [each.id for each in declared if "{" in each.reason] == []


# --- how a correction fails ----------------------------------------------------

# TS 29.229's shapes: RTA prints `< Session-Id >` twice (clause 6.1.10), table
# 6.3.1 lists what clause 6.3 defines, and the NOTE on it sends Load to RFC
# 8583. Clause 6.3.15's values stand in for an enumeration.
_TS29229 = parser.parse("""\
; Specification: 3GPP TS 29.229
; Version: 19.1.0
; Vendor-ID: 10415


; Type: Message
; Name: Registration-Termination-Answer, RTA
; Section: 6.1.10
<Registration-Termination-Answer> ::= < Diameter Header: 304, PXY, 16777216 >
        < Session-Id >
        { Origin-Host }
        < Session-Id >
        [ Identity-with-Emergency-Registration ]


; Type: AVP Table
; Section: 6.3
; Table: 6.3.1
; Columns: Name Code Section Type Must May S.not M.not Encrypt
Server-Assignment-Type 614 6.3.15 Enumerated M,V - - - No


; Type: Enumerated AVP
; Name: Server-Assignment-Type
; Section: 6.3.15
Server-Assignment-Type ::= < Enumerated AVP header: 614 10415 >
        NO_ASSIGNMENT = 0
        REGISTRATION  = 1


; Type: Reused AVPs
; Section: 6.3
; Table: 6.3.1
; Columns: Name From
Load RFC8583
""")

# TS 32.299 table 7.2.0.1 types an OMA row by reference only; TS 29.272
# clauses 7.3.67 and 7.3.137 cite TS 32.422 for values, printing none and one.
_CITED = parser.parse("""\
; Specification: 3GPP TS 32.299
; Version: 19.0.0
; Vendor-ID: 10415


; Type: AVP Table
; Section: 7.2
; Table: 7.2.0.1
; Columns: Name Code Type Must May S.not M.not
DCD-Information 2115 - - - - -


; Type: Reused AVPs
; Section: 7.2
; Table: 7.2.0.1
; Columns: Name From
DCD-Information OMA-DDS-Charging_Data


; Type: Enumerated AVP
; Name: Trace-Depth
; Section: 7.3.67
; Values: TS 32.422 [23] for Trace Depth
Trace-Depth ::= < Enumerated AVP header: 1462 10415 >


; Type: Enumerated AVP
; Name: Job-Type
; Section: 7.3.137
; Values: TS 32.422 [23] for Job-Type
Job-Type ::= < Enumerated AVP header: 1623 10415 >
        Immediate_MDT_only = 0
""")

_IDS = (f"edit-{n}" for n in itertools.count())
_RTA = "Registration-Termination-Answer"
_SAT = "Server-Assignment-Type"


def _found[T: ast.Node](selector: corrections.Selector, kind: type[T]) -> T:
    (node,) = selector.find(_TS29229)
    assert isinstance(node, kind)
    return node


_ROW = _found(table_row(_SAT), ast.AvpTableRow)
_LOAD = ast.ReusedAvpRow(name="Load", origin="RFC8583")
_SESSION_ID = ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED)
_MDT = (ast.EnumValue(name="Immediate_MDT_only", value=0),)
_FLAGS = ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR, ast.AvpFlag.MANDATORY}))
_BLANK = ast.AvpTableRow(name="DCD-Information", code=2115)


def _fix(target, field, expect, replace):
    return Correction(
        id=next(_IDS),
        target=target,
        field=field,
        expect=expect,
        replace=replace,
        reason="r",
    )


def _drop(target, expect):
    return Delete(id=next(_IDS), target=target, expect=expect, reason="r")


def _add(into, node, after=None):
    return Insert(id=next(_IDS), into=into, node=node, after=after, reason="r")


def _member(name):
    return ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL)


def _scope():
    return ast.ApplicationScope(
        name="Cx",
        source=ast.SourceRef(section="6"),
        application_id=16777216,
        applies_to=("6.*",),
    )


def _undefined(name, section="6.1.10"):
    return ast.UndefinedAvp(name=name, source=ast.SourceRef(section=section))


_CITATIONS = {
    "Trace-Depth": "TS 32.422 [23] for Trace Depth",
    "Job-Type": "TS 32.422 [23] for Job-Type",
}


def _values(name="Trace-Depth", expect=None, extend=False):
    return Supply(
        id=next(_IDS),
        target=definition(name),
        expect=expect or _CITATIONS[name],
        values=_MDT,
        extend=extend,
        reason="r",
    )


def _typed(expect=_BLANK):
    return Supply(
        id=next(_IDS),
        target=table_row("DCD-Information"),
        expect=expect,
        data_type=ast.DataType.GROUPED,
        flag_rules=_FLAGS,
        reason="r",
    )


_UNCITED = _CITED.model_copy(
    update={
        "sections": tuple(
            s for s in _CITED.sections if not isinstance(s, ast.ReusedAvps)
        )
    }
)
_SAT_CODE = _fix(table_row(_SAT), "code", 614, 615)
_LOAD_GONE = _drop(reused_row("Load"), _LOAD)


def _case(spec, edits, message, id):
    return pytest.param(spec, edits, message, id=id)


# What a declaration expects is gone: the document moved on.
_STALE = [
    _case(
        _TS29229,
        [_fix(table_row(_SAT), "code", 613, 615)],
        "expected code=613",
        "corrected-code-moved",
    ),
    _case(
        _TS29229,
        [_drop(reused_row("Load"), _LOAD.model_copy(update={"origin": "X"}))],
        "has changed",
        "deleted-row-changed",
    ),
    _case(
        _TS29229,
        [_add(avp_table("6.3.1"), _ROW)],
        "already present",
        "inserted-row-now-printed",
    ),
    _case(
        _TS29229,
        [_add(definition(_RTA), _member("X"), "Gone")],
        "is not present",
        "inserted-after-a-member-gone",
    ),
    _case(
        _TS29229,
        [_add(definition(_SAT), ast.EnumValue(name="X", value=1))],
        "value 1 is already present",
        "inserted-value-number-taken",
    ),
    _case(
        _TS29229,
        [_add(header(), _undefined(_SAT))],
        "defines it",
        "undefined-avp-now-defined",
    ),
    _case(
        _TS29229,
        [_add(header(), _undefined("Load"))],
        "the table of clause",
        "undefined-avp-now-re-used",
    ),
    _case(
        _TS29229,
        [_add(header(), _undefined("Absent"))],
        "no message or grouped",
        "undefined-avp-used-nowhere",
    ),
    _case(
        _CITED,
        [_values(expect="TS 32.422 [24]")],
        "expected values_source=",
        "supplied-values-citation-changed",
    ),
    _case(
        _CITED,
        [_values("Job-Type")],
        "already holds 1 values",
        "supplied-values-now-printed",
    ),
    _case(
        _CITED,
        [_values("Job-Type", extend=True)],
        "'Immediate_MDT_only' is already",
        "extending-value-now-printed",
    ),
    _case(_CITED, [_values(extend=True)], "prints no values", "extending-none-printed"),
    _case(
        _CITED,
        [_typed(_BLANK.model_copy(update={"code": 1}))],
        "expected AvpTable",
        "supplied-row-changed",
    ),
    _case(_UNCITED, [_typed()], "no re-used", "supplied-row-no-longer-re-used"),
]

# A selector matches nothing or more than one node. An occurrence fails once
# its name stops repeating, even the first.
_UNMATCHED = [
    _case(
        _TS29229,
        [_fix(table_row("Missing"), "code", 1, 2)],
        "no match",
        "row-of-no-such-name",
    ),
    _case(
        _TS29229,
        [_drop(avp_rule(_RTA, "Session-Id"), _SESSION_ID)],
        "2 matches",
        "rule-printed-twice",
    ),
    _case(
        _TS29229,
        [_drop(avp_rule(_RTA, "Origin-Host", occurrence=1), _SESSION_ID)],
        "no match",
        "occurrence-of-an-unrepeated-rule",
    ),
    _case(
        _TS29229,
        [_add(reused_avps("9.9"), _LOAD)],
        "no match",
        "table-of-no-such-clause",
    ),
]

# What a declaration asks for cannot be done.
_IMPOSSIBLE = [
    _case(
        _TS29229,
        [_fix(table_row(_SAT), "colour", None, "red")],
        "has no field",
        "no-such-field",
    ),
    _case(
        _TS29229,
        [_fix(table_row(_SAT), "code", 614, -1)],
        "is not valid",
        "invalid-value",
    ),
    _case(
        _TS29229,
        [_fix(definition(_RTA), "avps", None, ())],
        "holds child nodes",
        "field-of-child-nodes",
    ),
    _case(
        _TS29229,
        [
            _fix(avp_rule(_RTA, "Origin-Host"), "min_occurs", 1, 5),
            _fix(avp_rule(_RTA, "Origin-Host"), "max_occurs", 1, 2),
        ],
        "not valid",
        "inverted-occurrence-range",
    ),
    _case(
        _TS29229,
        [_drop(table_row(_SAT), _ROW)],
        "not valid",
        "table-left-with-no-rows",
    ),
    _case(
        _TS29229, [_drop(header(), _TS29229)], "can be deleted", "deleting-the-header"
    ),
    _case(
        _TS29229,
        [_add(definition(_SAT), _member("X"))],
        "message or grouped",
        "member-into-an-enumerated-avp",
    ),
    _case(
        _TS29229,
        [_add(definition(_RTA), _LOAD)],
        "must be a AvpRule",
        "re-used-row-into-a-message",
    ),
    _case(
        _TS29229,
        [_add(header(), _scope(), after="Cx")],
        "after must be None",
        "scope-after-another",
    ),
    _case(
        _TS29229,
        [_add(header(), _LOAD)],
        "only an ApplicationScope or an",
        "re-used-row-into-the-header",
    ),
    _case(
        _TS29229,
        [Supply(id="s", target=definition(_RTA), expect="x", values=_MDT, reason="r")],
        "matched a Message",
        "values-for-a-message",
    ),
]

# Two declarations that cannot both hold.
_CONFLICTING = [
    _case(
        _TS29229, [_SAT_CODE, _SAT_CODE], "corrected more than once", "corrected-twice"
    ),
    _case(
        _TS29229, [_LOAD_GONE, _LOAD_GONE], "deleted more than once", "deleted-twice"
    ),
    _case(
        _TS29229,
        [_fix(reused_row("Load"), "origin", "RFC8583", "RFC7683"), _LOAD_GONE],
        "both corrected and deleted",
        "corrected-and-deleted",
    ),
    _case(
        _TS29229,
        [
            _drop(definition(_SAT), _found(definition(_SAT), ast.EnumeratedAvp)),
            _fix(enum_value(_SAT, "NO_ASSIGNMENT"), "value", 0, 2),
        ],
        "another edit deleted",
        "corrected-inside-a-deleted-definition",
    ),
    _case(
        _TS29229,
        [
            _add(reused_avps("6.3.1"), _LOAD.model_copy(update={"name": "X"})),
            _drop(reused_avps("6.3.1"), _found(reused_avps("6.3.1"), ast.ReusedAvps)),
        ],
        "corrected and deleted",
        "inserted-into-a-deleted-table",
    ),
    _case(_CITED, [_values(), _values()], "supplied more than once", "supplied-twice"),
    _case(
        _CITED,
        [_typed(), _fix(table_row("DCD-Information"), "code", 2115, 2116)],
        "corrected and supplied",
        "corrected-and-supplied",
    ),
]


@pytest.mark.parametrize(("spec", "edits", "message"), _STALE)
def test_a_declaration_whose_expectation_is_gone_fails(spec, edits, message):
    with pytest.raises(CorrectionError, match=message):
        corrections.apply(spec, edits)


@pytest.mark.parametrize(("spec", "edits", "message"), _UNMATCHED)
def test_a_selector_matching_none_or_several_nodes_fails(spec, edits, message):
    with pytest.raises(CorrectionError, match=message):
        corrections.apply(spec, edits)


@pytest.mark.parametrize(("spec", "edits", "message"), _IMPOSSIBLE)
def test_a_declaration_asking_the_impossible_fails(spec, edits, message):
    with pytest.raises(CorrectionError, match=message):
        corrections.apply(spec, edits)


@pytest.mark.parametrize(("spec", "edits", "message"), _CONFLICTING)
def test_declarations_that_cannot_both_hold_fail(spec, edits, message):
    with pytest.raises(CorrectionError, match=message):
        corrections.apply(spec, edits)


# For the selectors no committed correction uses yet: TS 29.212's CC-Request
# printed per reference point, only Gx's header stating an id, and a value
# printed twice as TS 29.229's RTA prints `< Session-Id >` twice.
_AUTHORING = parser.parse("""\
; Specification: 3GPP TS 29.212
; Version: 19.3.0
; Vendor-ID: 10415


; Type: Message
; Name: CC-Request, CCR
; Section: 5.6.2
<CC-Request> ::= < Diameter Header: 272, REQ, PXY, 16777238 >
        < Session-Id >


; Type: Message
; Name: CC-Request, CCR
; Section: 4b.5.2
<CC-Request> ::= < Diameter Header: 272, REQ, PXY >
        < Session-Id >
        [ Event-Report-Indication ]


; Type: Enumerated AVP
; Name: Bearer-Control-Mode
; Section: 5.3.23
Bearer-Control-Mode ::= < Enumerated AVP header: 1023 10415 >
        UE_ONLY = 0
        UE_ONLY = 0


; Type: Undefined AVP
; Name: Event-Report-Indication
; Section: 4b.5.2
""")
_BCM = "Bearer-Control-Mode"
_ERI = "Event-Report-Indication"
_NOTE = "used in clause 4b.5.2 only"
_GXX = 16777266


_GX = 16777238
# Gx's CC-Request alone, by the id its header prints.
_GX_CCR = definition("CC-Request", application_id=_GX)


@pytest.mark.parametrize(
    ("edit", "corrected", "message"),
    [
        pytest.param(
            _fix(undefined(_ERI), "note", None, _NOTE),
            lambda spec: spec.sections[3].note == _NOTE,
            None,
            id="undefined",
        ),
        pytest.param(
            _fix(undefined("Session-Id"), "note", None, _NOTE),
            None,
            "no match",
            id="undefined-of-a-defined-name",
        ),
        pytest.param(
            _fix(enum_value(_BCM, "UE_ONLY", occurrence=2), "value", 0, 1),
            lambda spec: [value.value for value in spec.sections[2].values] == [0, 1],
            None,
            id="occurrence",
        ),
        pytest.param(
            _fix(enum_value(_BCM, "UE_ONLY", occurrence=3), "value", 0, 1),
            None,
            "no match",
            id="occurrence-past-the-last",
        ),
        pytest.param(
            _fix(
                definition("CC-Request", application_id=None),
                "application_id",
                None,
                _GXX,
            ),
            lambda spec: spec.sections[1].application_id == _GXX,
            None,
            id="no-application-id",
        ),
        pytest.param(
            _fix(definition("CC-Request"), "application_id", None, _GXX),
            None,
            "2 matches",
            id="omitted-application-id",
        ),
        pytest.param(
            _fix(_GX_CCR, "name", "CC-Request", "Credit-Control-Request"),
            lambda spec: (
                [s.name for s in spec.sections[:2]]
                == ["Credit-Control-Request", "CC-Request"]
            ),
            None,
            id="numeric-application-id",
        ),
        pytest.param(
            _fix(
                definition("CC-Request", application_id=_GXX),
                "name",
                "CC-Request",
                "Credit-Control-Request",
            ),
            None,
            "no match",
            id="numeric-application-id-no-header-prints",
        ),
        pytest.param(
            _fix(definition(_BCM, application_id=None), "name", _BCM, "X"),
            None,
            "no match",
            id="no-application-id-of-an-avp",
        ),
        pytest.param(
            _fix(avp_rule(_GX_CCR, "Session-Id"), "bold", False, True),
            lambda spec: [s.avps[0].bold for s in spec.sections[:2]] == [True, False],
            None,
            id="rule-of-the-numbered-application",
        ),
        pytest.param(
            _fix(
                avp_rule(definition("CC-Request", application_id=None), "Session-Id"),
                "bold",
                False,
                True,
            ),
            lambda spec: [s.avps[0].bold for s in spec.sections[:2]] == [False, True],
            None,
            id="rule-of-the-unnumbered-application",
        ),
        pytest.param(
            _fix(avp_rule("CC-Request", "Session-Id"), "bold", False, True),
            None,
            "2 matches",
            id="rule-of-either-application",
        ),
        pytest.param(
            _fix(avp_rule(_GX_CCR, _ERI), "bold", False, True),
            None,
            "no match",
            id="rule-only-the-other-application-prints",
        ),
    ],
)
def test_a_selector_no_committed_correction_uses_finds_its_one_node(
    edit, corrected, message
):
    if message is not None:
        with pytest.raises(CorrectionError, match=message):
            corrections.apply(_AUTHORING, [edit])
    else:
        assert corrected(corrections.apply(_AUTHORING, [edit])[0])


@pytest.mark.parametrize(
    ("declare", "message"),
    [
        (lambda: _fix(table_row(_SAT), "code", 614, 614), "with itself"),
        (lambda: avp_rule(_RTA, "Session-Id", occurrence=0), "counts from 1"),
        (
            lambda: Supply(
                id="s", target=definition("A"), expect="", values=(), reason="r"
            ),
            "supplies no values",
        ),
        (
            lambda: Supply(id="s", target=table_row("A"), expect=_BLANK, reason="r"),
            "supplies nothing",
        ),
        (
            lambda: Supply(
                id="s",
                target=table_row("A"),
                expect=_BLANK.model_copy(update={"data_type": ast.DataType.GROUPED}),
                data_type=ast.DataType.GROUPED,
                reason="r",
            ),
            "fills only a blank type",
        ),
        (
            lambda: Insert(
                id="row",
                into=avp_table("6.3.1"),
                node=_ROW,
                after=None,
                reason="r",
                drawn_from="clause\n4",
            ),
            "one line",
        ),
        (
            lambda: Supply(
                id="s",
                target=table_row("A"),
                expect=_BLANK,
                data_type=ast.DataType.GROUPED,
                extend=True,
                reason="r",
            ),
            "no list to extend",
        ),
    ],
    ids=[
        "replaces-itself",
        "occurrence-zero",
        "supplies-no-values",
        "supplies-nothing",
        "fills-a-typed-row",
        "two-line-provenance",
        "extending-a-row",
    ],
)
def test_a_declaration_that_cannot_mean_anything_is_refused(declare, message):
    with pytest.raises(CorrectionError, match=message):
        declare()


@pytest.mark.parametrize(
    ("module", "message"),
    [
        ("SOMETHING_ELSE = []", "no CORRECTIONS list"),
        ("CORRECTIONS = ['not a correction']", "must hold Correction"),
        # `all(...)` over a generator once left it exhausted, so the module
        # was silently corrected by nothing.
        ("CORRECTIONS = (c for c in [Correction(**_CODE)])", "must be a list"),
        ("import nonexistent_module_for_tests", "failed to import"),
        ("CORRECTIONS = [Correction(**_CODE), Correction(**_CODE)]", "declared twice"),
        ("CORRECTIONS = [Correction(**{**_CODE, 'id': 'Bad Id'})]", "kebab-case"),
    ],
    ids=[
        "no-list",
        "wrong-type",
        "generator",
        "import-error",
        "repeated-id",
        "malformed-id",
    ],
)
def test_a_module_that_declares_nothing_usable_is_refused(tmp_path, module, message):
    (tmp_path / "TS29.229.py").write_text(
        "from seanchai.dad.corrections import Correction, table_row\n"
        "_CODE = dict(id='code', target=table_row('A'), field='code', expect=1,"
        " replace=2, reason='r')\n" + module + "\n"
    )

    with pytest.raises(CorrectionError, match=message):
        corrections.load(tmp_path, "3GPP TS 29.229")


@pytest.mark.parametrize(
    "specification",
    ["3GPP TS ../outside", "/etc/passwd", r"..\outside", "OMA-../outside", ""],
)
def test_a_specification_header_cannot_name_a_module_outside_the_directory(
    tmp_path, specification
):
    # `; Specification:` comes from a parsed file, and loading its module runs
    # Python. Nothing but a canonical document reference may name that file.
    (tmp_path.parent / "outside.py").write_text("CORRECTIONS = []\n")
    directory = tmp_path / "corrections"
    directory.mkdir()

    with pytest.raises(CorrectionError, match="supported document"):
        corrections.load(directory, specification)


def test_a_required_load_needs_a_module_that_corrects_something(tmp_path):
    """`seanchai corpus correct` asked for these corrections: an uncorrected
    file passed off as a success is the failure mode. Acceptances change no
    data, so a module of them alone corrects nothing."""
    with pytest.raises(CorrectionError, match="no corrections module"):
        corrections.load(tmp_path, "3GPP TS 29.229", required=True)
    (tmp_path / "TS29.229.py").write_text(
        "from seanchai.dad.corrections import Accept, definition\n"
        "CORRECTIONS = [Accept(id='body', rule='reused-body-differs',"
        " target=definition('A'), expect='a message', reason='r')]\n"
    )

    with pytest.raises(CorrectionError, match="declares no corrections"):
        corrections.load(tmp_path, "3GPP TS 29.229", required=True)
    assert corrections.load(tmp_path, "3GPP TS 29.272") == []


def test_comments_on_a_directive_line_a_correction_removes_survive():
    """The note of a correction removing its field's line goes on the line
    naming the block, the file header's here, and the line's comments with
    it."""
    text = "\n".join(
        [
            "; Specification: 3GPP TS 29.109",
            "; Version: 19.0.0",
            "; Vendor-ID: 10415",
            ";; standing on the bases",
            "; Bases: RFC6733 ;; trailing on the bases",
            "",
        ]
    )
    spec, comments = parser.parse_with_comments(text)
    emptied = _fix(header(), "bases", ("RFC6733",), ())

    corrected, _, kept = corrections.apply_with_comments(spec, comments, [emptied])

    assert formatter.format_spec(corrected, kept).splitlines() == [
        ";; standing on the bases",
        "; Specification: 3GPP TS 29.109 ;; trailing on the bases"
        f" ;; corrected: ({emptied.id})",
        "; Version: 19.0.0",
        "; Vendor-ID: 10415",
    ]
