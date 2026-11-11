"""What a build makes of holes and undefined names, and what it refuses.

The committed corpus shows each policy on its own seventeen holes and twelve
undefined names. A refusal needs a corpus that is wrong, so those cases build
the smallest fixture corpus that is.
"""

import functools
from pathlib import Path

import pytest
from conftest import _RULES

from seanchai import corpus, model
from seanchai.dad import ast
from seanchai.model import (
    Alias,
    AvpFlag,
    DataType,
    FlagRules,
    HolePolicy,
    Supplied,
    UndefinedPolicy,
)

_M = frozenset({AvpFlag.MANDATORY})
_V = frozenset({AvpFlag.VENDOR})

# The five holes no undefined policy answers for, and what each leaves out.
_FIELD_HOLES = {
    # Its row states only a code.
    ("TS29.061", "3GPP-Session-Stop-Indicator"): ("data_type", "flag_rules"),
    # Typed "Integer", which is no Diameter type.
    ("TS29.234", "Charging-Characteristics"): ("data_type",),
    # No code or flag rule; TS 29.329's reading is complete.
    ("TS29.229", "Wildcarded-IMPU"): ("code", "flag_rules"),
    # No flag rule.
    ("ETSI-TS183.020", "Privacy-Indicator"): ("flag_rules",),
    # Re-used from RFC 4675, a RADIUS document the corpus does not hold.
    ("RFC6736", "Egress-VLANID"): ("definition",),
}
_UNDEFINED = {
    ("RFC4004", "MIP-HA-to-MN-SPI"): ("9.4", ("9.4",)),
    ("RFC4004", "MIP-MN-to-FA-SPI"): ("9.5", ("9.5",)),
    ("RFC4004", "MIP-MN-to-HA-SPI"): ("9.6", ("9.6",)),
    ("RFC5866", "Authorization-Session-Volume"): ("5.3", ("5.3", "5.5")),
    ("TS29.061", "Delegated-IPv6-Prefix"): (
        "16a.4.1",
        ("16a.4.1", "16a.4.2", "16a.4.3"),
    ),
    ("TS29.561", "Delegated-IPv6-Prefix"): ("12.6.2", ("12.6.2", "12.6.3")),
    ("TS29.154", "External-Group-Identifier"): ("A.6.6.2", ("A.6.6.2",)),
    ("TS29.234", "Error-Cause"): ("4.4.2.1", ("4.4.2.1", "5.5.1")),
    ("TS29.345", "ProSe-Query-Code"): ("6.3.53", ("6.3.53", "6.3.54")),
    ("TS29.345", "ProSe-Response-Code"): ("6.3.53", ("6.3.53", "6.3.54")),
    ("TS32.299", "Network-Element"): ("7.2.66aA", ("7.2.66aA",)),
    ("TS32.299", "Submission-Timestamp"): ("7.2.112aA", ("7.2.112aA",)),
}


@functools.cache
def _installed(undefined: UndefinedPolicy = UndefinedPolicy.HOLE) -> model.Model:
    return model.Model.installed(undefined=undefined)


def _keys(holes) -> set[tuple[str, str]]:
    return {(hole.document, hole.name) for hole in holes}


# --- the committed corpus ----------------------------------------------------


def test_the_seventeen_known_holes_are_the_record_and_say_why():
    built = _installed()
    record = corpus.Corpus.installed().record
    assert record is not None

    holes = {(hole.document, hole.name): hole for hole in built.holes()}

    assert holes.keys() == _FIELD_HOLES.keys() | _UNDEFINED.keys()
    for key, missing in _FIELD_HOLES.items():
        assert holes[key].missing == missing, key
    for key in _UNDEFINED:
        assert holes[key].missing == (model.Missing.UNDEFINED,), key
    reasons = {(each.document, each.name): each.reason for each in record.holes}
    assert {key: hole.recorded for key, hole in holes.items()} == reasons
    assert built.unrecorded_holes() == built.stale_record_entries() == ()
    assert holes["RFC6736", "Egress-VLANID"].origin == "RFC4675"
    # A recorded hole is still a hole, wherever a body names it.
    stated = holes["TS29.234", "Charging-Characteristics"]
    assert '"Integer"' in (stated.recorded or "")
    assert built.resolve("TS29.234", "Charging-Characteristics") is None
    data = built.resolve("TS29.234", "Charging-Data")
    assert isinstance(data, model.Grouped)
    (member,) = [m for m in data.members if m.name == "Charging-Characteristics"]
    assert (member.avp, member.hole) == (None, stated)
    assert stated in {
        m.hole for app in built.applications("TS29.234") for m in app.walk()
    }


def test_the_twelve_undefined_names_are_declared_where_their_bodies_name_them():
    """By default each is a hole naming its block, and the members naming it
    hold the hole."""
    built = _installed()

    declared = {
        (each.reference, each.name): (each.section, each.cited_in)
        for each in built.undefined()
    }

    assert built.undefined_policy is UndefinedPolicy.HOLE
    assert declared == _UNDEFINED
    hole = built.hole("TS29.154", "External-Group-Identifier")
    assert hole is not None and hole.undefined == built.undefined("TS29.154")[0]
    assert str(hole) == "TS29.154 External-Group-Identifier: undefined (clause A.6.6.2)"
    assert built.resolve("TS29.154", "External-Group-Identifier") is None
    (ecr,) = [m for m in built.messages("TS29.154") if m.abbreviation == "ECR"]
    assert hole in {member.hole for member in ecr.avps}


@pytest.mark.parametrize(
    ("undefined", "refused"),
    [
        (UndefinedPolicy.HOLE, _FIELD_HOLES.keys() | _UNDEFINED.keys()),
        (UndefinedPolicy.DROP, _FIELD_HOLES.keys()),
        (UndefinedPolicy.PLACEHOLDER, _FIELD_HOLES.keys()),
    ],
    ids=str,
)
def test_allowing_no_hole_refuses_what_the_undefined_policy_leaves(undefined, refused):
    """The record lists twelve names `DROP` and `PLACEHOLDER` answer for; by
    default those entries going unused is no staleness."""
    with pytest.raises(model.IncompleteCorpusError) as raised:
        model.Model.installed(holes=HolePolicy.NONE, undefined=undefined)

    assert _keys(raised.value.holes) == refused
    assert _keys(_installed(undefined).holes()) == refused
    if undefined is UndefinedPolicy.HOLE:
        assert "undefined=... answers for the undefined names" in str(raised.value)


def test_drop_takes_the_members_out_and_keeps_them_beside():
    """RFC 4004 clause 9.4's SPI is a required member of MIP-HA-to-MN-MSA;
    TS 29.154's ECR names External-Group-Identifier."""
    built = _installed(UndefinedPolicy.DROP)

    msa = built.resolve("RFC4004", "MIP-HA-to-MN-MSA")
    (ecr,) = [m for m in built.messages("TS29.154") if m.abbreviation == "ECR"]

    assert isinstance(msa, model.Grouped)
    (spi,) = msa.dropped
    assert (spi.name, spi.min_occurs) == ("MIP-HA-to-MN-SPI", 1)
    assert spi.hole is not None and spi.hole.undefined is not None
    assert "MIP-HA-to-MN-SPI" not in {member.name for member in msa.members}
    assert [member.name for member in ecr.dropped] == ["External-Group-Identifier"]
    assert "External-Group-Identifier" not in {member.name for member in ecr.avps}
    assert built.hole("RFC4004", "MIP-HA-to-MN-SPI") is None
    assert built.resolve("RFC4004", "MIP-HA-to-MN-SPI") is None
    assert len(built.undefined()) == 12
    assert built.placeholders() == ()


def test_placeholder_keeps_the_members_in_place_untyped():
    built = _installed(UndefinedPolicy.PLACEHOLDER)

    msa = built.resolve("RFC4004", "MIP-HA-to-MN-MSA")

    assert isinstance(msa, model.Grouped)
    (member,) = [m for m in msa.members if m.name == "MIP-HA-to-MN-SPI"]
    assert (member.avp, member.hole) == (None, None)
    assert member.placeholder is not None
    assert member.placeholder.undefined.section == "9.4"
    assert "\n" not in repr(member)
    assert len(built.placeholders()) == 12
    assert [p.name for p in built.placeholders("RFC4004")] == [
        "MIP-HA-to-MN-SPI",
        "MIP-MN-to-FA-SPI",
        "MIP-MN-to-HA-SPI",
    ]
    assert built.hole("RFC4004", "MIP-HA-to-MN-SPI") is None


def _supplied(code: int, data_type=DataType.OCTET_STRING, **kw) -> Supplied:
    kw.setdefault("vendor_id", 10415)
    kw.setdefault("flag_rules", FlagRules(must=_M | _V))
    return Supplied(code=code, data_type=data_type, source="ACME dictionary", **kw)


def test_supply_reads_the_consumers_answers_in_the_declaring_document():
    """TS 29.336's External-Identifier carries an external group identifier
    on S6t and is most likely what TS 29.154 means; the rest are a
    dictionary's own numbers. A key naming a document wins over a name key."""
    alias = Alias("TS29.336", "External-Identifier", source="our reading")
    on = ast.EnumValue(name="ON", value=1)
    built = model.Model.installed(
        undefined=UndefinedPolicy.SUPPLY,
        supply={
            "External-Group-Identifier": alias,
            ("TS29.345", "ProSe-Query-Code"): _supplied(59990),
            "ProSe-Response-Code": _supplied(59991, DataType.ENUMERATED, values=(on,)),
            "Delegated-IPv6-Prefix": _supplied(
                59992, vendor_id=0, flag_rules=FlagRules(must=_M)
            ),
            ("TS29.561", "Delegated-IPv6-Prefix"): _supplied(59993),
            "Submission-Timestamp": _supplied(
                59994,
                DataType.GROUPED,
                members=(
                    ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),
                    ast.AvpRule(name="Network-Element", presence=ast.Presence.OPTIONAL),
                ),
            ),
        },
    )

    (ecr,) = [m for m in built.messages("TS29.154") if m.abbreviation == "ECR"]
    (member,) = [m for m in ecr.avps if m.name == "External-Group-Identifier"]
    assert member.avp == built.resolve("TS29.336", "External-Identifier")
    assert member.avp is not None and member.avp.identity == (10415, 3111)
    assert member.alias == alias
    assert built.resolve("TS29.154", "External-Group-Identifier") == member.avp

    query = built.resolve("TS29.345", "ProSe-Query-Code")
    assert query is not None
    assert (query.identity, query.defined_in, query.section, query.supplied) == (
        (10415, 59990),
        "TS29.345",
        "6.3.53",
        "ACME dictionary",
    )
    assert query in built.avps("TS29.345")
    response = built.resolve("TS29.345", "ProSe-Response-Code")
    assert isinstance(response, model.Enumerated) and response.values == (on,)
    # An IETF AVP takes RFC 6733's V rule.
    ietf = built.resolve("TS29.061", "Delegated-IPv6-Prefix")
    assert ietf is not None and ietf.flag_rules == FlagRules(must=_M, must_not=_V)
    other = built.resolve("TS29.561", "Delegated-IPv6-Prefix")
    assert other is not None and other.code == 59993
    # Members resolve in the block's document; one supplied nothing stays a hole.
    stamp = built.resolve("TS32.299", "Submission-Timestamp")
    assert isinstance(stamp, model.Grouped)
    session, element = stamp.members
    assert session.avp == built.resolve("TS32.299", "Session-Id")
    assert element.hole is not None and element.hole.recorded is not None
    # What the supply answers is no hole; what it does not stays recorded.
    assert _keys(built.holes()) == _FIELD_HOLES.keys() | {
        ("RFC4004", "MIP-HA-to-MN-SPI"),
        ("RFC4004", "MIP-MN-to-FA-SPI"),
        ("RFC4004", "MIP-MN-to-HA-SPI"),
        ("RFC5866", "Authorization-Session-Volume"),
        ("TS29.234", "Error-Cause"),
        ("TS32.299", "Network-Element"),
    }


# --- sidecars ----------------------------------------------------------------

_SIDECAR = """\
; Specification: ACME HSS dictionary
; Vendor-ID: 10415


; Type: AVP Table
; Section: 1
; Columns: Name                  Code   Type         Must  May  S.not  M.not
           Network-Element       59995  Grouped      M,V   -    -      -
           Submission-Timestamp  59996  Time         M     -    -      V
"""
_DEFINITION = """

; Type: Grouped AVP
; Name: Network-Element
; Section: 2
Network-Element ::= < AVP header: 59995 10415 >
        { Session-Id }
"""
_ROW = "Network-Element       59995  Grouped      M,V   -    -      -"


def test_a_sidecar_supplies_definitions_and_rows(tmp_path):
    """TS 32.299's two undefined names, as a vendor's dictionary might
    define them."""
    (tmp_path / "acme.dad").write_text(_SIDECAR + _DEFINITION)

    supplied = model.supplied_from(tmp_path / "acme.dad")

    source = "ACME HSS dictionary (acme.dad)"
    assert supplied["Network-Element"] == Supplied(
        vendor_id=10415,
        code=59995,
        data_type=DataType.GROUPED,
        flag_rules=ast.AvpFlagRules(must=_M | _V),
        source=source,
        members=(ast.AvpRule(name="Session-Id", presence=ast.Presence.REQUIRED),),
    )
    stamp = supplied["Submission-Timestamp"]
    assert (stamp.vendor_id, stamp.code, stamp.source) == (0, 59996, source)
    supply: dict[model.SupplyKey, Supplied | Alias] = {**supplied}
    built = model.Model.installed(undefined=UndefinedPolicy.SUPPLY, supply=supply)
    element = built.resolve("TS32.299", "Network-Element")
    assert isinstance(element, model.Grouped)
    assert element.members[0].avp == built.resolve("TS32.299", "Session-Id")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            _SIDECAR.replace(_ROW, _ROW.replace("M,V   -", "-     -")) + _DEFINITION,
            "Network-Element states no flag rules",
        ),
        (
            _SIDECAR.replace(_ROW, _ROW.replace("59995", "59999")) + _DEFINITION,
            "Network-Element: row gives code 59999, definition 59995",
        ),
        (
            # Every contradiction of one name is listed together.
            _SIDECAR.replace(
                _ROW, "Network-Element       59999  OctetString  M     -    -      V"
            )
            + _DEFINITION,
            "Network-Element: row gives code 59999, definition 59995;"
            " row gives type OctetString, definition Grouped;"
            " row gives vendor 0, definition 10415$",
        ),
        (
            _SIDECAR.replace("Name ", "Name Vendor-ID ").replace("  59", "  0  59")
            + _DEFINITION,
            "Network-Element: row gives vendor 0, definition 10415;"
            " row gives vendor 0 with V under Must$",
        ),
        (
            # A row alone, its V flag against the file's vendor.
            _SIDECAR.replace("; Vendor-ID: 10415", "; Vendor-ID: 0"),
            "Network-Element: row gives vendor 0 with V under Must",
        ),
        (
            _SIDECAR.replace(_ROW, f"{_ROW}\n           {_ROW}") + _DEFINITION,
            "Network-Element is tabled twice",
        ),
        (_SIDECAR + _DEFINITION * 2, "Network-Element is defined twice"),
        (
            _SIDECAR.replace("59996  Time", "-      Time"),
            "Submission-Timestamp states no code or no type",
        ),
    ],
    ids=[
        "no-flags",
        "code",
        "every-contradiction",
        "vendor-cell",
        "v-flag",
        "tabled-twice",
        "defined-twice",
        "row-without-a-code",
    ],
)
def test_a_sidecar_contradicting_itself_is_refused(tmp_path, text, message):
    (tmp_path / "acme.dad").write_text(text)

    with pytest.raises(model.ModelError, match=message):
        model.supplied_from(tmp_path / "acme.dad")


def test_a_name_two_sidecars_supply_is_refused(tmp_path):
    (tmp_path / "one.dad").write_text(_SIDECAR)
    (tmp_path / "two.dad").write_text(_SIDECAR + _DEFINITION)

    with pytest.raises(model.ModelError, match="Network-Element is supplied twice"):
        model.supplied_from(tmp_path / "one.dad", tmp_path / "two.dad")


# --- refusals over a fixture corpus ------------------------------------------


def _spec(sections, *, version: str | None = "18.1.0") -> ast.Specification:
    return ast.Specification(
        specification="3GPP TS 29.900",
        version=version,
        vendor_id=10415,
        sections=tuple(sections),
    )


def _rule(name, presence=ast.Presence.OPTIONAL):
    return ast.AvpRule(name=name, presence=presence)


def _message(*members: str) -> ast.Message:
    return ast.Message(
        name="Test-Request",
        abbreviation="TR",
        source=ast.SourceRef(section="6.1.1"),
        command_code=300,
        flags=frozenset({ast.CommandFlag.REQUEST}),
        application_id=16777216,
        avps=tuple(_rule(member) for member in members),
    )


def _table(*rows: ast.AvpTableRow) -> ast.AvpTable:
    return ast.AvpTable(
        source=ast.SourceRef(section="6.3.0"), columns=tuple(ast.AvpColumn), rows=rows
    )


def _row(name: str, code: int, data_type=DataType.UNSIGNED32) -> ast.AvpTableRow:
    return ast.AvpTableRow(
        name=name,
        code=code,
        data_type=data_type,
        flag_rules=ast.AvpFlagRules(must=_M | _V),
    )


def _declared(name: str, section="6.3.1") -> ast.UndefinedAvp:
    return ast.UndefinedAvp(name=name, source=ast.SourceRef(section=section))


def _undefined_corpus() -> corpus.Corpus:
    """RFC 4004 clause 9.4's shape: a grouped AVP whose required and optional
    members nothing defines, both declared, the optional one in a command
    too, and a second document re-using both."""
    own = _spec(
        [
            _message("Missing-Opt", "Holder"),
            ast.GroupedAvp(
                name="Holder",
                source=ast.SourceRef(section="6.3.1"),
                code=700,
                vendor_id=10415,
                avps=(
                    _rule("Known"),
                    _rule("Missing-Req", ast.Presence.REQUIRED),
                    _rule("Missing-Opt"),
                ),
            ),
            _table(_row("Holder", 700, DataType.GROUPED), _row("Known", 701)),
            _declared("Missing-Opt", "6.1.1"),
            _declared("Missing-Req"),
        ]
    )
    citing = ast.Specification(
        specification="3GPP TS 29.901",
        version="18.1.0",
        vendor_id=10415,
        sections=(
            ast.ReusedAvps(
                table="1",
                source=ast.SourceRef(section="6.3.0"),
                rows=(
                    ast.ReusedAvpRow(name="Holder", origin="TS29.900"),
                    ast.ReusedAvpRow(name="Missing-Opt", origin="TS29.900"),
                ),
            ),
        ),
    )
    return corpus.Corpus(
        corpus.Entry(Path(f"{n}.dad"), spec) for n, spec in enumerate((own, citing))
    )


def test_a_name_reached_through_an_origin_is_the_origins_hole():
    """No committed document re-uses an undefined name, so a fixture shows
    it: TS 29.901's reading names TS 29.900's block."""
    built = model.Model.build(_undefined_corpus(), holes=HolePolicy.ANY)

    hole = built.hole("TS29.901", "Missing-Opt")

    assert hole is not None
    assert (hole.reference, hole.missing) == ("TS29.900", (model.Missing.UNDEFINED,))
    assert hole == built.hole("TS29.900", "Missing-Opt")


@pytest.mark.parametrize(
    ("undefined", "supply", "message"),
    [
        (UndefinedPolicy.SUPPLY, None, "needs supply="),
        (UndefinedPolicy.DROP, {}, "read only with undefined=SUPPLY"),
        # A typo, or a name upstream has since defined.
        (UndefinedPolicy.SUPPLY, {"Missing-Optional": _supplied(710)}, "no Undefined"),
        (
            UndefinedPolicy.SUPPLY,
            {("TS29.901", "Missing-Opt"): _supplied(710)},
            "no Undefined AVP block declares",
        ),
        (
            UndefinedPolicy.SUPPLY,
            {"Missing-Opt": _supplied(701)},
            r"claims \(vendor 10415, code 701\), which is TS29.900's Known",
        ),
        (
            UndefinedPolicy.SUPPLY,
            {"Missing-Opt": _supplied(710), "Missing-Req": _supplied(710)},
            r"TS29.900 Missing-Opt and for TS29.900 Missing-Req both claim"
            r" \(vendor 10415, code 710\)",
        ),
        (
            UndefinedPolicy.SUPPLY,
            {"Missing-Opt": Alias("TS29.900", "Nowhere", "t")},
            "does not complete",
        ),
        (
            UndefinedPolicy.SUPPLY,
            {
                "Missing-Opt": Alias("TS29.900", "Missing-Req", "t"),
                "Missing-Req": Alias("TS29.900", "Missing-Opt", "t"),
            },
            r"supply aliases form a cycle: TS29\.900 Missing-Req -> TS29\.900"
            r" Missing-Opt -> TS29\.900 Missing-Req",
        ),
        (
            UndefinedPolicy.SUPPLY,
            {"Missing-Opt": _supplied(710, members=(_rule("Known"),))},
            "no Grouped",
        ),
        (
            UndefinedPolicy.SUPPLY,
            {
                "Missing-Opt": _supplied(
                    710, values=(ast.EnumValue(name="On", value=1),)
                )
            },
            "no Enumerated",
        ),
    ],
    ids=[
        "supply-without-a-mapping",
        "a-mapping-without-supply",
        "unknown-name",
        "unknown-document",
        "a-defined-identity",
        "two-names-one-identity",
        "alias-to-a-hole",
        "alias-cycle",
        "members-on-a-leaf",
        "values-on-a-leaf",
    ],
)
def test_a_build_refuses_a_supply_that_does_not_fit(undefined, supply, message):
    with pytest.raises(model.ModelError, match=message):
        model.Model.build(
            _undefined_corpus(),
            holes=HolePolicy.ANY,
            undefined=undefined,
            supply=supply,
        )


def test_a_name_key_every_document_key_overrides_claims_no_identity():
    built = model.Model.build(
        _undefined_corpus(),
        holes=HolePolicy.ANY,
        undefined=UndefinedPolicy.SUPPLY,
        supply={
            "Missing-Opt": _supplied(711),
            ("TS29.900", "Missing-Opt"): _supplied(710),
            "Missing-Req": _supplied(711),
        },
    )

    assert [avp.name for avp in built.readings((10415, 711))] == ["Missing-Req"]


def test_a_supplied_name_reached_across_releases_says_so():
    """No undefined name of the corpus is reached across releases. Here TS
    32.299 V18.1.0 re-uses a name TS 29.140 V7.0.0 declares undefined, and
    reads TS 29.140 as its final version: supplied, it still says by which
    citation it was reached."""
    origin = ast.Specification(
        specification="3GPP TS 29.140",
        version="7.0.0",
        vendor_id=10415,
        sections=(_declared("Missing-Opt"),),
    )
    citing = ast.Specification(
        specification="3GPP TS 32.299",
        version="18.1.0",
        vendor_id=10415,
        sections=(
            ast.ReusedAvps(
                table="1",
                source=ast.SourceRef(section="6.3.0"),
                rows=(ast.ReusedAvpRow(name="Missing-Opt", origin="TS29.140"),),
            ),
        ),
    )
    books = corpus.Corpus(
        (corpus.Entry(Path(f"{n}.dad"), s) for n, s in enumerate((origin, citing))),
        rules=_RULES,
    )

    built = model.Model.build(
        books,
        undefined=UndefinedPolicy.SUPPLY,
        supply={"Missing-Opt": _supplied(710)},
    )

    avp = built.resolve("TS32.299", "Missing-Opt")
    assert avp is not None and avp.supplied == "ACME dictionary"
    assert (avp.defined_in, avp.across_releases) == (
        "TS29.140",
        corpus.CrossRelease(
            "TS32.299", "TS29.140", "7.0.0", corpus.CitationRule.NON_SPECIFIC
        ),
    )
    assert built.across_releases("TS32.299") == (avp,)


# --- the record of known holes over a fixture corpus -------------------------


def _known(document: str, name: str, *missing: str) -> corpus.KnownHole:
    return corpus.KnownHole(document, name, tuple(map(model.Missing, missing)), "x")


_THING = corpus.KnownHole("TS29.900", "Thing", (model.Missing.FLAG_RULES,), "6.3.1")
_OPT = corpus.KnownHole("TS29.900", "Missing-Opt", (model.Missing.UNDEFINED,), "6.1")
_GONE = corpus.KnownHole("TS29.900", "Worked-Off", (model.Missing.DEFINITION,), "x")


def _recorded(*holes: corpus.KnownHole | None) -> corpus.Corpus:
    """One document holding a hole with a code (`Thing`, no flag rules), one
    undefined name (`Missing-Opt`), and a record of `holes`, or no record
    for a single None."""
    spec = _spec(
        [
            _message("Thing", "Missing-Opt"),
            _table(ast.AvpTableRow(name="Thing", code=1, data_type=DataType.TIME)),
            _declared("Missing-Opt", "6.1.1"),
        ]
    )
    record = (
        None
        if holes == (None,)
        else corpus.HoleRecord(Path("holes.toml"), tuple(h for h in holes if h))
    )
    return corpus.Corpus([corpus.Entry(Path("29900.dad"), spec)], record)


@pytest.mark.parametrize(
    ("holes", "build", "refused"),
    [
        # A hole the record does not list, alone and before a stale entry.
        ((_OPT,), {}, ("IncompleteCorpusError", {"Thing"})),
        ((_OPT, _GONE), {}, ("IncompleteCorpusError", {"Thing"})),
        # An entry is compared exactly, missing fields included.
        (
            (_OPT, _known("TS29.900", "Thing", "data_type")),
            {},
            ("IncompleteCorpusError", {"Thing"}),
        ),
        ((None,), {}, ("IncompleteCorpusError", {"Thing", "Missing-Opt"})),
        (
            (_THING, _OPT),
            {"holes": HolePolicy.NONE},
            ("IncompleteCorpusError", {"Thing", "Missing-Opt"}),
        ),
        # An entry naming no hole: by name, document, and older copy.
        ((_THING, _OPT, _GONE), {}, ("StaleHoleRecordError", {"Worked-Off"})),
        (
            (_THING, _OPT, _known("TS29.999", "Thing", "flag_rules")),
            {},
            ("StaleHoleRecordError", {"Thing"}),
        ),
        (
            (
                _THING,
                _OPT,
                _known("TS29.900 V1.0.0", "Thing", "flag_rules"),
            ),
            {},
            ("StaleHoleRecordError", {"Thing"}),
        ),
        # A policy excuses only an entry for a name a block declares, listed
        # as the hole it would be.
        (
            (
                _THING,
                _OPT,
                _known("TS29.900", "Worked-Off", "undefined"),
            ),
            {"undefined": UndefinedPolicy.DROP},
            ("StaleHoleRecordError", {"Worked-Off"}),
        ),
        (
            (
                _THING,
                _known("TS29.900", "Missing-Opt", "definition"),
            ),
            {"undefined": UndefinedPolicy.DROP},
            ("StaleHoleRecordError", {"Missing-Opt"}),
        ),
    ],
    ids=[
        "unrecorded",
        "unrecorded-before-stale",
        "other-missing-fields",
        "no-record",
        "none-allowed",
        "stale-name",
        "stale-document",
        "stale-version",
        "stale-under-drop",
        "answered-but-misdescribed",
    ],
)
def test_the_default_build_holds_the_corpus_to_its_record(holes, build, refused):
    error, names = refused

    with pytest.raises(getattr(model, error)) as raised:
        model.Model.build(_recorded(*holes), **build)

    if error == "IncompleteCorpusError":
        assert {hole.name for hole in raised.value.holes} == names
        for name in names:
            assert f"TS29.900 {name}" in str(raised.value)
    else:
        assert {entry.name for entry in raised.value.entries} == names
        for entry in raised.value.entries:
            assert f"{entry.document} {entry.name}" in str(raised.value)


@pytest.mark.parametrize(
    "undefined", [UndefinedPolicy.HOLE, UndefinedPolicy.DROP], ids=str
)
def test_a_recorded_hole_builds_and_carries_its_reason(undefined):
    built = model.Model.build(_recorded(_THING, _OPT), undefined=undefined)

    hole = built.hole("TS29.900", "Thing")
    assert hole is not None and hole.recorded == "6.3.1"
    assert built.resolve("TS29.900", "Thing") is None
    assert built.stale_record_entries() == ()
    assert (built.hole("TS29.900", "Missing-Opt") is None) == (
        undefined is UndefinedPolicy.DROP
    )


def test_allowing_any_hole_holds_the_corpus_to_nothing_but_reports_it():
    built = model.Model.build(_recorded(_GONE), holes=HolePolicy.ANY)

    assert built.stale_record_entries() == (_GONE,)
    assert {hole.name for hole in built.unrecorded_holes()} == {"Thing", "Missing-Opt"}


@pytest.mark.parametrize(
    ("undefined", "supply"),
    [
        (UndefinedPolicy.HOLE, None),
        (UndefinedPolicy.DROP, None),
        (UndefinedPolicy.SUPPLY, {}),
    ],
    ids=str,
)
@pytest.mark.parametrize("case", ["defined-upstream", "older-copy"])
def test_a_block_no_hole_comes_of_leaves_its_entry_stale(undefined, supply, case):
    """A definition wins over a block, so its entry names no hole whatever
    answers for the name; nor does an older copy's block no citation
    reaches."""
    if case == "defined-upstream":
        entries = [_spec([_table(_row("Known", 1)), _declared("Known")])]
        stale = _known("TS29.900", "Known", "undefined")
    else:
        entries = [
            _spec([_declared("Gone")], version="17.0.0"),
            _spec([_table(_row("Known", 1))]),
        ]
        stale = _known("TS29.900 V17.0.0", "Gone", "undefined")
    books = corpus.Corpus(
        [corpus.Entry(Path(f"{n}.dad"), spec) for n, spec in enumerate(entries)],
        corpus.HoleRecord(Path("holes.toml"), (stale,)),
    )

    with pytest.raises(model.StaleHoleRecordError) as raised:
        model.Model.build(books, undefined=undefined, supply=supply)

    assert raised.value.entries == (stale,)
