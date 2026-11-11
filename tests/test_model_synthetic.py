"""Model rules no committed document shows, over the smallest fixture corpus
that does.

Each case says why the corpus cannot show it: no pair of documents
disagrees that way, or a defective file would be needed. Everything the
corpus does show is in `test_model.py`.
"""

from pathlib import Path

import pytest
from conftest import _RULES

from seanchai import corpus, model
from seanchai.dad import ast
from seanchai.model import AvpFlag, DataType, FlagRules

_M = frozenset({AvpFlag.MANDATORY})
_V = frozenset({AvpFlag.VENDOR})
_MUST = ast.MBitOverride.MUST
_MUST_NOT = ast.MBitOverride.MUST_NOT


def _spec(specification, *sections, vendor_id=10415, bases=()) -> ast.Specification:
    ietf = specification.startswith("RFC")
    return ast.Specification(
        specification=specification,
        version=None if ietf else "18.1.0",
        vendor_id=0 if ietf else vendor_id,
        bases=tuple(bases),
        sections=sections,
    )


def _model(*specs: ast.Specification) -> model.Model:
    return model.Model.build(
        corpus.Corpus(
            (corpus.Entry(Path(f"{n}.dad"), spec) for n, spec in enumerate(specs)),
            rules=_RULES,
        ),
        holes=model.HolePolicy.ANY,
    )


def _rule(name: str) -> ast.AvpRule:
    return ast.AvpRule(name=name, presence=ast.Presence.OPTIONAL)


def _grouped(name, code, *members, vendor_id=10415) -> ast.GroupedAvp:
    return ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section="6.3.1"),
        code=code,
        vendor_id=vendor_id,
        avps=tuple(map(_rule, members)),
    )


def _table(*rows: ast.AvpTableRow, flagless=False) -> ast.AvpTable:
    columns = tuple(ast.AvpColumn)
    if flagless:
        # RFC 5777's shape: Name, Code, Section and Type.
        columns = (
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
        )
    return ast.AvpTable(
        source=ast.SourceRef(section="6.3.0"), columns=columns, rows=rows
    )


def _row(
    name, code, data_type: DataType | None = DataType.UNSIGNED32, **flags
) -> ast.AvpTableRow:
    """A row placing `flags`; without any, its flag cells are dashes."""
    return ast.AvpTableRow(
        name=name,
        code=code,
        data_type=data_type,
        flag_rules=ast.AvpFlagRules(**flags),
    )


def _reused(origin: str, *rows: tuple[str, ast.MBitOverride | None]) -> ast.ReusedAvps:
    return ast.ReusedAvps(
        table="1",
        source=ast.SourceRef(section="6.3.0"),
        rows=tuple(
            ast.ReusedAvpRow(name=name, origin=origin, m_bit=m_bit)
            for name, m_bit in rows
        ),
    )


def _message(*members: str, application_id: int | None = 16777216) -> ast.Message:
    return ast.Message(
        name="Test-Request",
        abbreviation="TR",
        source=ast.SourceRef(section="5.6.2"),
        command_code=300,
        flags=frozenset({ast.CommandFlag.REQUEST}),
        application_id=application_id,
        avps=tuple(map(_rule, members)),
    )


# TS 29.800's `Bundle` holds `Feature`; both put V in Must and M in Must not.
_ORIGIN = _spec(
    "3GPP TS 29.800",
    _grouped("Bundle", 1, "Feature"),
    _table(
        _row("Bundle", 1, DataType.GROUPED, must=_V, must_not=_M),
        _row("Feature", 2, must=_V, must_not=_M),
    ),
)


@pytest.mark.parametrize(
    ("citing", "expected"),
    [
        # A citing table's cell outranks the re-used row's M-bit.
        (
            [_table(_row("Feature", 2, must=_V, may=_M)), ("Feature", _MUST)],
            FlagRules(must=_V, may=_M),
        ),
        # The M-bit fills the M a citing row leaves, ahead of the origin.
        (
            [_table(_row("Feature", 2, must=_V)), ("Feature", _MUST)],
            FlagRules(must=_M | _V),
        ),
        # Each flag is the first citing row's placing it; the M-bit ranks
        # below both rows.
        (
            [
                _table(_row("Feature", 2, must=_V)),
                _table(_row("Feature", 2, must=_M, may=_V)),
                ("Feature", _MUST_NOT),
            ],
            FlagRules(must=_M | _V),
        ),
        # A flag nothing of the citing document places is the origin's.
        (
            [_table(_row("Feature", 2, must=_V)), ("Feature", None)],
            FlagRules(must=_V, must_not=_M),
        ),
    ],
    ids=["cell-over-m-bit", "m-bit-over-origin", "first-row-each", "origin-last"],
)
def test_a_citing_documents_flags_rank_cells_then_m_bit_then_origin(citing, expected):
    """No committed document both tabulates a re-used AVP and marks its
    M-bit otherwise; TS 29.272's RAT-Type shows the M-bit over the origin."""
    sections = [
        each if isinstance(each, ast.AvpTable) else _reused("TS29.800", each)
        for each in citing
    ]

    found = _model(_ORIGIN, _spec("3GPP TS 29.900", *sections)).resolve(
        "TS29.900", "Feature"
    )

    assert found is not None and found.flag_rules == expected


def test_a_file_citing_itself_reads_its_own_rules():
    """TS 29.212's Gxx tables re-use TS 29.212's own AVPs; none marks an
    M-bit against its own table."""
    spec = _spec(
        "3GPP TS 29.900",
        _table(_row("Feature", 2, must=_M | _V)),
        _reused("TS29.900", ("Feature", _MUST_NOT)),
    )

    found = _model(spec).resolve("TS29.900", "Feature")

    assert found is not None and found.flag_rules == FlagRules(must=_M | _V)


def test_an_m_bit_alone_completes_no_vendor_avp():
    """Over an IETF reading RFC 6733's V rule completes it (TS 29.273's Key);
    a vendor reading stating no flags stays a hole."""
    origin = _spec("3GPP TS 29.800", _table(_row("Feature", 2), flagless=True))
    citing = _spec("3GPP TS 29.900", _reused("TS29.800", ("Feature", _MUST)))

    hole = _model(origin, citing).hole("TS29.900", "Feature")

    assert hole is not None and hole.missing == (model.Missing.FLAG_RULES,)


def test_an_untyped_origin_takes_the_citing_tables_type_and_stays_a_hole():
    """RFC 4590 types none of its attributes; its corrections now type the
    Digest AVPs TS 29.229 re-uses. Uncorrected, TS 29.229's table typed them,
    and its flags differing from the origin's are no conflict."""
    origin = _spec(
        "RFC4590", _table(_row("Digest-Qop", 110, None, may=_M, must_not=_V))
    )
    citing = _spec(
        "3GPP TS 29.900",
        _table(_row("Digest-Qop", 110, DataType.UTF8_STRING, must=_M, must_not=_V)),
        _reused("RFC4590", ("Digest-Qop", None)),
    )
    built = _model(origin, citing)

    found = built.resolve("TS29.900", "Digest-Qop")

    assert found is not None
    assert (found.defined_in, found.data_type) == ("RFC4590", DataType.UTF8_STRING)
    assert found.flag_rules == FlagRules(must=_M, must_not=_V)
    hole = built.hole("RFC4590", "Digest-Qop")
    assert hole is not None and hole.missing == (model.Missing.DATA_TYPE,)


@pytest.mark.parametrize(
    ("theirs", "ours", "expected"),
    [
        # Two codes for one name.
        (
            _spec("3GPP TS 29.901", _table(_row("Thing", 2, must=_V))),
            _spec("3GPP TS 29.900", _table(_row("Thing", 1, None), flagless=True)),
            ("data_type", "flag_rules"),
        ),
        # (10415, 1) and (999, 1) are two AVPs, whatever the name says.
        (
            _spec(
                "3GPP TS 29.901",
                _grouped("Thing", 1, "A", vendor_id=999),
                _table(_row("Thing", 1, DataType.GROUPED, must=_V)),
                vendor_id=999,
            ),
            _spec(
                "3GPP TS 29.900",
                _grouped("Thing", 1, "A"),
                _reused("TS29.901", ("Thing", None)),
            ),
            ("flag_rules",),
        ),
        # A Time row with blank flag cells takes no flags from an Unsigned32
        # reading of its code.
        (
            _spec("3GPP TS 29.901", _table(_row("Thing", 1, must=_V))),
            _spec("3GPP TS 29.900", _table(_row("Thing", 1, DataType.TIME))),
            ("flag_rules",),
        ),
    ],
    ids=["code", "vendor", "type"],
)
def test_readings_that_disagree_fill_nothing_and_leave_a_hole_naming_both(
    theirs, ours, expected
):
    """The committed corpus holds no such pair: the linter reports them,
    and the corrections settle each."""
    if not any(isinstance(each, ast.ReusedAvps) for each in ours.sections):
        ours = ours.model_copy(update={"bases": ("TS29.901",)})

    hole = _model(theirs, ours).hole("TS29.900", "Thing")

    assert hole is not None
    assert (hole.missing, hole.conflict) == (expected, "TS29.901")
    assert str(hole).endswith("TS29.901's reading, which states it, disagrees")


@pytest.mark.parametrize(
    ("theirs", "vendor_id"),
    [
        # The same type and code: the blank row takes the flags.
        (_row("Thing", 1, DataType.TIME, must=_V), 10415),
        # A row placing V nowhere fixed claims no vendor, so its file's
        # `; Vendor-ID:` is no claim against the citing file's.
        (_row("Thing", 1, DataType.TIME, may=_V), 999),
    ],
    ids=["same-type", "vendor-unstated"],
)
def test_readings_that_agree_fill_each_other(theirs, vendor_id):
    base = _spec("3GPP TS 29.901", _table(theirs), vendor_id=vendor_id)
    ours = _spec(
        "3GPP TS 29.900", _table(_row("Thing", 1, DataType.TIME)), bases=["TS29.901"]
    )

    found = _model(base, ours).resolve("TS29.900", "Thing")

    assert found is not None and found.identity == (10415, 1)
    assert found.flag_rules == FlagRules.printed(theirs.flag_rules)


def test_a_row_printing_no_type_takes_the_body_another_document_defines():
    """No committed row lacks a type its name's definition states."""
    base = _spec("3GPP TS 29.901", _grouped("Thing", 1, "A"))
    ours = _spec(
        "3GPP TS 29.900",
        _table(_row("Thing", 1, None, must=_V)),
        bases=["TS29.901"],
    )

    found = _model(base, ours).resolve("TS29.900", "Thing")

    assert isinstance(found, model.Grouped)
    assert [member.name for member in found.members] == ["A"]


def test_a_citing_row_stating_no_code_does_not_replace_the_origins_member():
    """Through TS 32.299, M2M-Information keeps oneM2M's Originator because
    the two codes differ; a citing row with no code is no evidence either
    way, so the origin's member stays."""
    citing = _spec(
        "3GPP TS 29.900",
        _table(_row("Feature", None, must=_M | _V)),
        _reused("TS29.800", ("Bundle", None)),
    )
    built = _model(_ORIGIN, citing)

    bundle = built.resolve("TS29.900", "Bundle")

    assert isinstance(bundle, model.Grouped)
    assert bundle.members[0].avp is built.resolve("TS29.800", "Feature")


# --- a body among its own descendants ----------------------------------------
# No specification does this; resolution cuts the recursion so a defective
# file cannot loop.


def test_a_grouped_avp_holding_itself_is_cut_and_walked_past():
    spec = _spec(
        "3GPP TS 29.900",
        _grouped("Loop", 1, "Loop", "AVP", "Missing"),
        _table(_row("Loop", 1, DataType.GROUPED, must=_V)),
        _message("Loop", "AVP"),
    )
    built = _model(spec)

    loop = built.resolve("TS29.900", "Loop")
    (message,) = built.messages("TS29.900")

    assert isinstance(loop, model.Grouped)
    assert (loop.members[0].avp, loop.members[0].hole) == (None, None)
    walked = message.walk()
    assert [member.name for member in walked] == ["Loop", "AVP", "Missing"]
    assert walked[2].hole is not None


@pytest.mark.parametrize("own_ping", [False, True], ids=["both-reused", "own-ping"])
def test_a_body_read_through_a_citing_document_is_cut_where_it_recurs(own_ping):
    """`Ping` holds `Pong` and `Pong` holds `Ping`. Read through the citing
    document, the inner `Ping` is the one being resolved, so it is cut,
    whether the citing document re-uses `Ping` too or defines its own."""
    ping = _grouped("Ping", 1, "Pong")
    origin = _spec(
        "3GPP TS 29.800",
        *([] if own_ping else [ping]),
        _grouped("Pong", 2, "Ping"),
        _table(
            _row("Ping", 1, DataType.GROUPED, must=_V, must_not=_M),
            _row("Pong", 2, DataType.GROUPED, must=_V, must_not=_M),
        ),
    )
    if own_ping:
        citing = _spec(
            "3GPP TS 29.900",
            ping,
            _table(_row("Ping", 1, DataType.GROUPED, must=_V, must_not=_M)),
            _reused("TS29.800", ("Pong", _MUST)),
        )
    else:
        citing = _spec(
            "3GPP TS 29.900", _reused("TS29.800", ("Ping", _MUST), ("Pong", _MUST))
        )

    found = _model(origin, citing).resolve("TS29.900", "Ping")

    assert isinstance(found, model.Grouped)
    pong = found.members[0].avp
    assert isinstance(pong, model.Grouped)
    assert pong.flag_rules == FlagRules(must=_M | _V)
    assert (pong.members[0].avp, pong.members[0].hole) == (None, None)


def test_a_cut_does_not_replace_another_avp_of_the_name():
    """The citing document's own `Feature` (10415, 3) holds the re-used
    `Bundle`, whose `Feature` is oneM2M's (45687, 2): the name recurs, the
    AVP does not, so the body keeps oneM2M's member."""
    origin = _spec(
        "oneM2M TS-0004",
        _grouped("Bundle", 1, "Feature", vendor_id=45687),
        _table(
            _row("Bundle", 1, DataType.GROUPED, must=_M | _V),
            _row("Feature", 2, must=_M | _V),
        ),
        vendor_id=45687,
    )
    citing = _spec(
        "3GPP TS 29.900",
        _grouped("Feature", 3, "Bundle"),
        _table(_row("Feature", 3, DataType.GROUPED, must=_V, must_not=_M)),
        _reused("oneM2M-TS-0004", ("Bundle", None)),
    )
    built = _model(origin, citing)

    feature = built.resolve("TS29.900", "Feature")

    assert isinstance(feature, model.Grouped)
    bundle = feature.members[0].avp
    assert isinstance(bundle, model.Grouped)
    assert bundle.members[0].avp is built.resolve("oneM2M-TS-0004", "Feature")


# --- commands ----------------------------------------------------------------


def test_a_header_keeps_its_own_id_against_an_application_scope():
    """No committed header disagrees with its block; the linter's
    application-header-mismatch reports one that does."""
    spec = _spec(
        "3GPP TS 29.900",
        ast.ApplicationScope(
            name="Gx",
            source=ast.SourceRef(section="1.1"),
            application_id=16777238,
            applies_to=("5.*",),
        ),
        _message(application_id=16777266),
    )

    (application,) = _model(spec).applications("TS29.900")

    assert (application.application_id, application.name) == (16777266, None)


def test_no_answer_message_where_neither_a_document_nor_its_bases_print_one():
    """Every committed document reaches RFC 6733's."""
    assert _model(_spec("3GPP TS 29.900")).answer_message("TS29.900") is None
