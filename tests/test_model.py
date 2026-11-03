"""The consumer model resolves names into objects by a stated policy.

The synthetic cases pin the resolution order — local definition, re-used
origin, table row, base document — and the corpus-level cases pin what the
committed files actually resolve to, so a policy change shows up as a
concrete AVP moving between documents rather than as a green run.
"""

import dataclasses
import json
from pathlib import Path

import pytest
from conftest import _CORPUS_DIR

from seanchai import corpus, model
from seanchai.dad import ast

_ROOT = Path(__file__).parent.parent


def _spec(
    specification: str,
    sections,
    *,
    vendor_id: int = 10415,
    bases=(),
    version: str | None = "18.1.0",
):
    return ast.Specification(
        specification=specification,
        version=version,
        vendor_id=vendor_id,
        bases=tuple(bases),
        sections=tuple(sections),
    )


def _entry(spec: ast.Specification) -> corpus.Entry:
    return corpus.Entry(path=Path(f"{spec.specification}.dad"), spec=spec)


def _model(*specs: ast.Specification) -> model.Model:
    """A fixture's model; these corpora have no record, and many hold a hole on
    purpose."""
    return model.Model.build(
        corpus.Corpus(_entry(spec) for spec in specs), strict=False
    )


def _rule(name, presence=ast.Presence.OPTIONAL):
    return ast.AvpRule(name=name, presence=presence)


def _grouped(name, code, *members, vendor_id: int | None = 10415):
    return ast.GroupedAvp(
        type="Grouped AVP",
        name=name,
        source=ast.SourceRef(section="6.3.1"),
        code=code,
        vendor_id=vendor_id,
        avps=tuple(_rule(member) for member in members),
    )


def _table(*rows):
    return ast.AvpTable(
        type="AVP Table",
        source=ast.SourceRef(section="6.3.0"),
        columns=tuple(ast.AvpColumn),
        rows=tuple(rows),
    )


def _row(name, code, data_type=ast.DataType.UNSIGNED32, *, vendor="must"):
    """A row flagging V under `vendor`: "must" for the file's space,
    "must_not" for IETF space, "may" for a row that states neither."""
    return ast.AvpTableRow(
        name=name,
        code=code,
        data_type=data_type,
        flag_rules=ast.AvpFlagRules(**{vendor: frozenset({ast.AvpFlag.VENDOR})}),
    )


def _reused(name, origin):
    return ast.ReusedAvps(
        type="Reused AVPs",
        table="1",
        source=ast.SourceRef(section="6.3.0"),
        rows=(ast.ReusedAvpRow(name=name, origin=origin),),
    )


def _message(name, *members):
    return ast.Message(
        type="Message",
        name=name,
        abbreviation="TR",
        source=ast.SourceRef(section="6.1.1"),
        command_code=300,
        flags=frozenset({ast.CommandFlag.REQUEST}),
        application_id=16777216,
        avps=tuple(_rule(member) for member in members),
    )


def test_an_enumeration_exposes_the_ranges_it_leaves_to_vendors():
    """TS 32.299 clause 7.2.213: values 0-10 named, 11-99 reserved, 100-199
    left to vendors; only the last are `vendor_specific`."""
    vendor = ast.VendorSpecificValues(
        first=100, last=199, description="Vendor specific SM services"
    )
    values = (
        ast.EnumValue(name="Off", value=0),
        ast.ReservedValues(first=11, last=99),
        vendor,
    )
    built = _model(
        _spec(
            "3GPP TS 29.999",
            [
                ast.EnumeratedAvp(
                    name="Mode",
                    source=ast.SourceRef(section="6.3.2"),
                    code=700,
                    vendor_id=10415,
                    values=values,
                ),
                _table(_row("Mode", 700, ast.DataType.ENUMERATED)),
            ],
        )
    )

    mode = built.resolve("TS29.999", "Mode")

    assert isinstance(mode, model.Enumerated)
    assert mode.values == values
    assert mode.vendor_specific == (vendor,)
    assert vendor.covers(100) and vendor.covers(199) and not vendor.covers(99)


class TestApplications:
    def _document(self, *sections):
        return _spec("3GPP TS 29.999", sections)

    def _command(self, section, application_id):
        message = _message("Test-Request")
        return message.model_copy(
            update={
                "source": ast.SourceRef(section=section),
                "application_id": application_id,
            }
        )

    def _block(self, name, application_id, *applies_to):
        return ast.ApplicationScope(
            name=name,
            source=ast.SourceRef(section="1.1"),
            application_id=application_id,
            applies_to=applies_to,
        )

    def test_a_block_gives_its_id_to_the_commands_whose_headers_print_none(self):
        built = _model(
            self._document(
                self._block("Gx", 16777238, "5.*"),
                self._command("5.6.2", None),
                self._command("5a.6.2", None),
            )
        )

        stated, unstated = built.applications("TS29.999")

        assert (stated.application_id, stated.name, stated.stated_in) == (
            16777238,
            "Gx",
            "1.1",
        )
        assert (unstated.application_id, unstated.name) == (None, None)

    def test_a_header_keeps_its_own_id_against_a_block(self):
        # The linter's application-header-mismatch reports this.
        built = _model(
            self._document(
                self._block("Gx", 16777238, "5.*"),
                self._command("5.6.2", 16777266),
            )
        )

        (application,) = built.applications("TS29.999")

        assert (application.application_id, application.name) == (16777266, None)


class TestResolutionOrder:
    def test_a_local_definition_wins_over_the_reused_listing(self):
        """An extension means what the extending document says (TS 29.272
        re-defines nine of RFC 6733's AVPs with extra members)."""
        origin = _spec(
            "RFC6733",
            [
                _grouped("Thing", 1, "A", vendor_id=None),
                _table(_row("Thing", 1, ast.DataType.GROUPED)),
            ],
            vendor_id=0,
            version=None,
        )
        extender = _spec(
            "3GPP TS 29.900",
            [
                _grouped("Thing", 1, "A", "B", vendor_id=None),
                _reused("Thing", "RFC6733"),
            ],
        )
        resolved = _model(origin, extender).resolve("TS29.900", "Thing")
        assert isinstance(resolved, model.Grouped)
        assert resolved.defined_in == "TS29.900"
        assert [member.name for member in resolved.members] == ["A", "B"]

    def test_a_reused_row_resolves_to_the_origins_definition(self):
        """Even when the citing file also tabulates the AVP, the way TS
        29.229 re-prints RFC 4590's Digest rows in its own table."""
        origin = _spec(
            "RFC4590",
            [_grouped("Digest-Thing", 7, "A", vendor_id=None)],
            vendor_id=0,
            version=None,
        )
        citing = _spec(
            "3GPP TS 29.900",
            [
                _table(
                    _row("Digest-Thing", 7, ast.DataType.GROUPED, vendor="must_not")
                ),
                _reused("Digest-Thing", "RFC4590"),
            ],
        )
        resolved = _model(origin, citing).resolve("TS29.900", "Digest-Thing")
        assert resolved is not None
        assert resolved.defined_in == "RFC4590"
        assert resolved.vendor_id == 0

    def test_a_base_document_supplies_what_nothing_local_does(self):
        base = _spec(
            "RFC6733",
            [_table(_row("Session-Id", 263, ast.DataType.UTF8_STRING))],
            vendor_id=0,
            version=None,
        )
        citing = _spec(
            "3GPP TS 29.900",
            [_message("Test-Request", "Session-Id")],
            bases=["RFC6733"],
        )
        (message,) = _model(base, citing).messages("TS29.900")
        (member,) = message.avps
        assert member.avp is not None
        assert member.avp.defined_in == "RFC6733"
        assert member.avp.identity == (0, 263)

    def test_an_indirect_citation_lands_on_the_real_definition(self):
        """TS 29.172 cites Service-Selection from TS 29.272, which itself
        re-uses it from RFC 5778 — the chain is followed to the end."""
        real = _spec(
            "RFC5778",
            [
                _grouped("Thing", 1, "A", vendor_id=None),
                _table(_row("Thing", 1, ast.DataType.GROUPED)),
            ],
            vendor_id=0,
            version=None,
        )
        middleman = _spec("3GPP TS 29.901", [_reused("Thing", "RFC5778")])
        citing = _spec("3GPP TS 29.900", [_reused("Thing", "TS29.901")])
        resolved = _model(real, middleman, citing).resolve("TS29.900", "Thing")
        assert resolved is not None
        assert resolved.defined_in == "RFC5778"

    def test_the_avp_wildcard_is_grammar_not_a_reference(self):
        """`* [ AVP ]` must not resolve even when some document defines an
        AVP that happens to be named `AVP`."""
        citing = _spec("3GPP TS 29.900", [_message("Test-Request", "AVP")])
        (message,) = _model(citing).messages("TS29.900")
        assert message.avps[0].avp is None
        assert message.avps[0].hole is None

    def test_a_definition_among_its_own_descendants_stops_resolving(self):
        looped = _spec(
            "3GPP TS 29.900",
            [
                _grouped("Loop", 1, "Loop"),
                _table(_row("Loop", 1, ast.DataType.GROUPED)),
            ],
        )
        resolved = _model(looped).resolve("TS29.900", "Loop")
        assert isinstance(resolved, model.Grouped)
        assert resolved.members[0].avp is None
        assert resolved.members[0].hole is None


_I32 = ast.DataType.INTEGER32
_M = frozenset({ast.AvpFlag.MANDATORY})
_V = frozenset({ast.AvpFlag.VENDOR})
# RFC 6733's rule for an IETF AVP no document flags.
_IETF_RULES = model.FlagRules(must_not=_V, application_defined=_M)


def _flagless_table(*rows):
    """RFC 5777's shape: Name, Code, Section and Type, no flag columns."""
    return ast.AvpTable(
        type="AVP Table",
        source=ast.SourceRef(section="10.1"),
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
        ),
        rows=tuple(rows),
    )


_P = frozenset({ast.AvpFlag.PROTECTED})
_UTF8 = ast.DataType.UTF8_STRING


def _flagged(name, code, data_type: ast.DataType | None = _UTF8, **columns):
    return ast.AvpTableRow(
        name=name,
        code=code,
        data_type=data_type,
        flag_rules=ast.AvpFlagRules(**columns),
    )


def _stand_in(*rows: ast.AvpTableRow) -> ast.Specification:
    """RFC 4590's shape once corrected: IETF rows, M and P under May."""
    rows = rows or (_flagged("Digest-Qop", 110, may=_M | _P, must_not=_V),)
    return _spec("RFC4590", [_table(*rows)], vendor_id=0, version=None)


class TestCitingFlagRules:
    """RFC 6733 sections 4.1 and 4.5 leave flag rules to the application, so
    a citing table's flag cells outrank the origin's through the citing
    document; the origin supplies the rest."""

    def test_a_citing_tables_must_m_outranks_the_origins_may_m(self):
        """TS 29.229 table 6.3.0.1 puts M in Must for `Digest-Qop`, RFC
        4590's stand-in rows in May; the citing row places no P, which the
        origin's May supplies."""
        citing = _spec(
            "3GPP TS 29.900",
            [
                _table(_flagged("Digest-Qop", 110, must=_M, must_not=_V)),
                _reused("Digest-Qop", "RFC4590"),
            ],
        )
        built = _model(_stand_in(), citing)
        resolved = built.resolve("TS29.900", "Digest-Qop")
        assert resolved is not None
        assert (resolved.defined_in, resolved.identity) == ("RFC4590", (0, 110))
        assert resolved.flag_rules == model.FlagRules(must=_M, may=_P, must_not=_V)
        assert built.holes() == ()

    def test_a_citing_row_of_dashes_falls_back_to_the_origin(self):
        """A row whose flag cells are all `-` states no flag rule."""
        citing = _spec(
            "3GPP TS 29.900",
            [_table(_flagged("Digest-Qop", 110)), _reused("Digest-Qop", "RFC4590")],
        )
        resolved = _model(_stand_in(), citing).resolve("TS29.900", "Digest-Qop")
        assert resolved is not None
        assert resolved.flag_rules == model.FlagRules(may=_M | _P, must_not=_V)

    def test_the_origins_own_reading_keeps_its_flag_rules(self):
        """Read after the citing document's, so a shared memo would show."""
        citing = _spec(
            "3GPP TS 29.900",
            [
                _table(_flagged("Digest-Qop", 110, must=_M, must_not=_V)),
                _reused("Digest-Qop", "RFC4590"),
            ],
        )
        built = _model(_stand_in(), citing)
        assert built.resolve("TS29.900", "Digest-Qop") is not None
        origins = built.resolve("RFC4590", "Digest-Qop")
        assert origins is not None
        assert origins.flag_rules == model.FlagRules(may=_M | _P, must_not=_V)
        assert len(built.identified(0, 110)) == 2

    def test_citing_flags_fill_an_untyped_origin_without_disagreeing(self):
        """An origin stating flags but no type takes the citing table's type;
        the citing flags differ from the origin's, which is no conflict."""
        origin = _stand_in(_flagged("Digest-Qop", 110, None, may=_M, must_not=_V))
        citing = _spec(
            "3GPP TS 29.900",
            [
                _table(_flagged("Digest-Qop", 110, must=_M, must_not=_V)),
                _reused("Digest-Qop", "RFC4590"),
            ],
        )
        built = _model(origin, citing)
        resolved = built.resolve("TS29.900", "Digest-Qop")
        assert resolved is not None
        assert resolved.data_type is _UTF8
        assert resolved.flag_rules == model.FlagRules(must=_M, must_not=_V)
        assert built.resolve("RFC4590", "Digest-Qop") is None

    def test_an_extensions_table_flags_take_the_origins_unplaced_ones(self):
        """TS 32.299 re-defines RFC 4006's Multiple-Services-Credit-Control,
        its row placing no P, which RFC 4006's May supplies."""
        origin = _spec(
            "RFC4006",
            [
                _grouped("Thing", 1, "A", vendor_id=None),
                _table(_flagged("Thing", 1, ast.DataType.GROUPED, must=_M, may=_P)),
            ],
            vendor_id=0,
            version=None,
        )
        extender = _spec(
            "3GPP TS 29.900",
            [
                _grouped("Thing", 1, "A", "B", vendor_id=None),
                _table(
                    _flagged("Thing", 1, ast.DataType.GROUPED, must=_M, must_not=_V)
                ),
                _reused("Thing", "RFC4006"),
            ],
        )
        resolved = _model(origin, extender).resolve("TS29.900", "Thing")
        assert isinstance(resolved, model.Grouped)
        assert resolved.defined_in == "TS29.900"
        assert [member.name for member in resolved.members] == ["A", "B"]
        assert resolved.flag_rules == model.FlagRules(must=_M, may=_P, must_not=_V)


_MUST = ast.MBitOverride.MUST
_MUST_NOT = ast.MBitOverride.MUST_NOT


def _vendor_rules(m: str) -> model.FlagRules:
    """A vendor AVP's rules: V in Must, M under `m`."""
    if m == "must":
        return model.FlagRules(must=_M | _V)
    return model.FlagRules(must=_V, **{m: _M})


def _origin(*sections) -> ast.Specification:
    """TS 29.800: `Bundle` holding `Feature` and `Other`, all three with M
    in Must not, and whatever else a test adds."""
    return _spec(
        "3GPP TS 29.800",
        [
            _grouped("Bundle", 1, "Feature", "Other"),
            _table(
                _flagged("Bundle", 1, ast.DataType.GROUPED, must=_V, must_not=_M),
                _flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_V, must_not=_M),
                _flagged("Other", 3, ast.DataType.UNSIGNED32, must=_V, must_not=_M),
            ),
            *sections,
        ],
    )


def _citing(*sections) -> ast.Specification:
    return _spec("3GPP TS 29.900", sections)


def _reused_from(origin: str, *rows: tuple[str, ast.MBitOverride | None]):
    return ast.ReusedAvps(
        type="Reused AVPs",
        table="2",
        source=ast.SourceRef(section="6.3.0"),
        rows=tuple(
            ast.ReusedAvpRow(name=name, origin=origin, m_bit=m_bit)
            for name, m_bit in rows
        ),
    )


class TestCitingMembers:
    """A grouped AVP read through a citing document keeps the defining
    document's body, each member the citing document says anything of read
    through it, the rest the origin's."""

    def test_a_member_the_citing_document_tabulates_is_read_through_it(self):
        """TS 32.299's `Supported-Features`, TS 29.229's body, holds TS
        32.299's `Feature-List`, M in Must."""
        citing = _citing(
            _table(
                _flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_M | _V),
            ),
            _reused_from("TS29.800", ("Bundle", None), ("Feature", None)),
        )
        built = _model(_origin(), citing)
        bundle = built.resolve("TS29.900", "Bundle")
        assert isinstance(bundle, model.Grouped)
        assert bundle.defined_in == "TS29.800"
        assert bundle.flag_rules == _vendor_rules("must_not")
        feature = bundle.members[0].avp
        assert feature is not None and feature.defined_in == "TS29.800"
        assert feature.flag_rules == _vendor_rules("must")
        assert feature == built.resolve("TS29.900", "Feature")
        # The body and its qualifiers are the defining document's.
        theirs = built.resolve("TS29.800", "Bundle")
        assert isinstance(theirs, model.Grouped)
        assert [m.rule for m in bundle.members] == [m.rule for m in theirs.members]
        member = theirs.members[0].avp
        assert member is not None and member.flag_rules == _vendor_rules("must_not")

    def test_a_member_the_citing_document_says_nothing_of_is_the_origins(self):
        citing = _citing(
            _table(
                _flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_M | _V),
            ),
            _reused_from("TS29.800", ("Bundle", None), ("Feature", None)),
        )
        built = _model(_origin(), citing)
        bundle = built.resolve("TS29.900", "Bundle")
        assert isinstance(bundle, model.Grouped)
        assert bundle.members[1].avp is built.resolve("TS29.800", "Other")
        assert built.hole("TS29.900", "Other") is not None

    def test_a_member_the_citing_document_reads_as_another_avp_is_the_origins(
        self,
    ):
        """TS 32.299 defines its own `Originator`, (10415, 864) Enumerated,
        and re-uses oneM2M's `M2M-Information`, whose `Originator` is
        (45687, 1008) UTF8String: a name is no identity, so the body keeps
        oneM2M's member. A member the citing document reads as the same AVP
        is still read through it."""
        origin = _spec(
            "oneM2M TS-0004",
            [
                _grouped("Bundle", 1, "Originator", "Feature", vendor_id=45687),
                _table(
                    _flagged("Bundle", 1, ast.DataType.GROUPED, must=_M | _V),
                    _flagged("Originator", 1008, must=_M | _V),
                    _flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_M | _V),
                ),
            ],
            vendor_id=45687,
        )
        citing = _citing(
            _table(
                _flagged("Originator", 864, ast.DataType.ENUMERATED, must=_M | _V),
                _flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_V, must_not=_M),
            ),
            _reused_from("oneM2M-TS-0004", ("Bundle", None), ("Feature", None)),
        )
        built = _model(origin, citing)
        bundle = built.resolve("TS29.900", "Bundle")
        theirs = built.resolve("oneM2M-TS-0004", "Bundle")
        assert isinstance(bundle, model.Grouped) and isinstance(theirs, model.Grouped)
        originator, feature = (member.avp for member in bundle.members)
        assert originator is theirs.members[0].avp
        assert originator is not None
        assert (originator.identity, originator.data_type) == ((45687, 1008), _UTF8)
        mine = built.resolve("TS29.900", "Originator")
        assert mine is not None and mine.identity == (10415, 864)
        assert feature is not None and feature.identity == (45687, 2)
        assert feature.flag_rules == model.FlagRules(must=_V, must_not=_M)
        assert feature == built.resolve("TS29.900", "Feature")

    def test_a_member_the_citing_document_cannot_identify_is_the_origins(self):
        """A citing row stating no code reads as a hole with no identity,
        which is no evidence it is the origin's member: the origin's stays."""
        citing = _citing(
            _table(_flagged("Feature", None, ast.DataType.UNSIGNED32, must=_M | _V)),
            _reused_from("TS29.800", ("Bundle", None)),
        )
        built = _model(_origin(), citing)
        bundle = built.resolve("TS29.900", "Bundle")
        assert isinstance(bundle, model.Grouped)
        assert bundle.members[0].avp is built.resolve("TS29.800", "Feature")

    def test_two_holes_without_codes_are_not_one_avp(self):
        """The origin's `Gap` is a hole in vendor 45687 with no code, the
        citing document's a hole in 10415 with no code: two unknown
        identities are no evidence of one AVP, so the origin's hole stays."""
        origin = _spec(
            "oneM2M TS-0004",
            [
                _grouped("Bundle", 1, "Gap", vendor_id=45687),
                _table(
                    _flagged("Bundle", 1, ast.DataType.GROUPED, must=_M | _V),
                    _flagged("Gap", None, must=_M | _V),
                ),
            ],
            vendor_id=45687,
        )
        citing = _citing(
            _table(_flagged("Gap", None, must=_V, must_not=_M)),
            _reused_from("oneM2M-TS-0004", ("Bundle", None)),
        )
        built = _model(origin, citing)
        bundle = built.resolve("TS29.900", "Bundle")
        assert isinstance(bundle, model.Grouped)
        gap = bundle.members[0].hole
        assert gap is not None and gap == built.hole("oneM2M-TS-0004", "Gap")
        assert gap.vendor_id == 45687
        mine = built.hole("TS29.900", "Gap")
        assert mine is not None and mine.vendor_id == 10415

    def test_a_grouped_members_own_members_are_read_through_it_too(self):
        """`Outer` holds `Bundle`, both re-used: `Bundle`'s `Feature` is the
        citing document's at depth two."""
        origin = _origin(
            _grouped("Outer", 4, "Bundle"),
            _table(_flagged("Outer", 4, ast.DataType.GROUPED, must=_V, must_not=_M)),
        )
        citing = _citing(
            _reused_from(
                "TS29.800",
                ("Outer", None),
                ("Bundle", None),
                ("Feature", _MUST),
            ),
        )
        outer = _model(origin, citing).resolve("TS29.900", "Outer")
        assert isinstance(outer, model.Grouped)
        bundle = outer.members[0].avp
        assert isinstance(bundle, model.Grouped)
        feature = bundle.members[0].avp
        assert feature is not None
        assert feature.flag_rules == _vendor_rules("must")

    def test_a_body_among_its_own_descendants_stops_through_the_citing_one(self):
        """`Ping` holds `Pong` and `Pong` holds `Ping`, both re-used: read
        through the citing document, the inner `Ping` is cut as `_body`
        cuts it."""
        origin = _spec(
            "3GPP TS 29.800",
            [
                _grouped("Ping", 1, "Pong"),
                _grouped("Pong", 2, "Ping"),
                _table(
                    _flagged("Ping", 1, ast.DataType.GROUPED, must=_V, must_not=_M),
                    _flagged("Pong", 2, ast.DataType.GROUPED, must=_V, must_not=_M),
                ),
            ],
        )
        citing = _citing(
            _reused_from("TS29.800", ("Ping", _MUST), ("Pong", _MUST)),
        )
        built = _model(origin, citing)
        ping = built.resolve("TS29.900", "Ping")
        assert isinstance(ping, model.Grouped)
        pong = ping.members[0].avp
        assert isinstance(pong, model.Grouped)
        assert pong.flag_rules == _vendor_rules("must")
        assert pong.members[0].avp is None and pong.members[0].hole is None
        assert isinstance(built.resolve("TS29.900", "Pong"), model.Grouped)

    def test_a_cut_is_the_citing_documents_own_body_only_when_one_identity(self):
        """The citing document's own `Ping` (10415, 1) holds the re-used
        `Pong`, whose `Ping` is the same AVP: read through the citing
        document, that member is `Ping` among its own descendants and is
        cut."""
        origin = _spec(
            "3GPP TS 29.800",
            [
                _grouped("Pong", 2, "Ping"),
                _table(
                    _flagged("Ping", 1, ast.DataType.UNSIGNED32, must=_V, must_not=_M),
                    _flagged("Pong", 2, ast.DataType.GROUPED, must=_V, must_not=_M),
                ),
            ],
        )
        citing = _citing(
            _grouped("Ping", 1, "Pong"),
            _table(_flagged("Ping", 1, ast.DataType.GROUPED, must=_V, must_not=_M)),
            _reused_from("TS29.800", ("Pong", None)),
        )
        ping = _model(origin, citing).resolve("TS29.900", "Ping")
        assert isinstance(ping, model.Grouped)
        pong = ping.members[0].avp
        assert isinstance(pong, model.Grouped)
        assert pong.members[0].avp is None and pong.members[0].hole is None

    def test_a_cut_does_not_replace_another_avp_of_the_name(self):
        """The citing document's own `Feature` (10415, 3) holds the re-used
        `Bundle`, whose `Feature` is oneM2M's (45687, 2): the citing
        document's `Feature` is being resolved when the member is read
        through it, but that is another AVP, so the body keeps oneM2M's
        member rather than a cut."""
        origin = _spec(
            "oneM2M TS-0004",
            [
                _grouped("Bundle", 1, "Feature", vendor_id=45687),
                _table(
                    _flagged("Bundle", 1, ast.DataType.GROUPED, must=_M | _V),
                    _flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_M | _V),
                ),
            ],
            vendor_id=45687,
        )
        citing = _citing(
            _grouped("Feature", 3, "Bundle"),
            _table(_flagged("Feature", 3, ast.DataType.GROUPED, must=_V, must_not=_M)),
            _reused_from("oneM2M-TS-0004", ("Bundle", None)),
        )
        built = _model(origin, citing)
        feature = built.resolve("TS29.900", "Feature")
        assert isinstance(feature, model.Grouped)
        assert feature.identity == (10415, 3)
        bundle = feature.members[0].avp
        assert isinstance(bundle, model.Grouped)
        member = bundle.members[0].avp
        assert member is not None and member.identity == (45687, 2)
        assert member is built.resolve("oneM2M-TS-0004", "Feature")


class TestReusedMBit:
    """A re-used row's M-bit cell is the citing interface's M rule: it
    outranks the origin's, and the citing AVP table's cells outrank it."""

    def test_an_m_bit_outranks_the_origins_m_rule(self):
        """TS 29.272 table 7.3.1/2 marks TS 29.212's `RAT-Type` `MUST`."""
        citing = _citing(_reused_from("TS29.800", ("Feature", _MUST)))
        built = _model(_origin(), citing)
        ours = built.resolve("TS29.900", "Feature")
        assert ours is not None and ours.defined_in == "TS29.800"
        assert ours.flag_rules == _vendor_rules("must")
        theirs = built.resolve("TS29.800", "Feature")
        assert theirs is not None
        assert theirs.flag_rules == _vendor_rules("must_not")

    def test_must_not_clears_an_origins_must(self):
        origin = _spec(
            "3GPP TS 29.800",
            [_table(_flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_M | _V))],
        )
        citing = _citing(_reused_from("TS29.800", ("Feature", _MUST_NOT)))
        ours = _model(origin, citing).resolve("TS29.900", "Feature")
        assert ours is not None
        assert ours.flag_rules == _vendor_rules("must_not")

    def test_the_citing_tables_cell_outranks_the_m_bit(self):
        citing = _citing(
            _table(
                _flagged("Feature", 2, ast.DataType.UNSIGNED32, may=_M, must=_V),
            ),
            _reused_from("TS29.800", ("Feature", _MUST)),
        )
        ours = _model(_origin(), citing).resolve("TS29.900", "Feature")
        assert ours is not None
        assert ours.flag_rules == _vendor_rules("may")

    def test_the_m_bit_outranks_the_origin_where_the_citing_row_leaves_m(self):
        """A citing row placing V alone: M comes from the M-bit, ahead of
        the origin's."""
        citing = _citing(
            _table(_flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_V)),
            _reused_from("TS29.800", ("Feature", _MUST)),
        )
        ours = _model(_origin(), citing).resolve("TS29.900", "Feature")
        assert ours is not None
        assert ours.flag_rules == _vendor_rules("must")

    def test_the_first_re_used_row_stating_m_is_read(self):
        """TS 29.336's `DRMP`: `-` for its first interface, Must not for its
        second; the first states nothing of M, so the second's rule stands,
        and a third's is not read."""
        citing = _citing(
            _reused_from("TS29.800", ("Feature", None)),
            _reused_from("TS29.800", ("Feature", _MUST)),
            _reused_from("TS29.800", ("Feature", _MUST_NOT)),
        )
        ours = _model(_origin(), citing).resolve("TS29.900", "Feature")
        assert ours is not None
        assert ours.flag_rules == _vendor_rules("must")

    def test_each_flag_is_the_first_citing_row_placing_it(self):
        """A first row placing V alone and a later one placing M in Must and
        V in May: V is the first row's, M the later one's, and the re-used
        row's M-bit, ranked below both, is not read."""
        citing = _citing(
            _table(_flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_V)),
            _table(_flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_M, may=_V)),
            _reused_from("TS29.800", ("Feature", _MUST_NOT)),
        )
        ours = _model(_origin(), citing).resolve("TS29.900", "Feature")
        assert ours is not None
        assert ours.flag_rules == _vendor_rules("must")

    def test_a_flag_no_citing_row_places_falls_to_the_m_bit_then_the_origin(self):
        """Two rows placing V alone: M is the re-used row's M-bit where it
        states one, and the origin's where none does."""
        rows = (
            _table(_flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_V)),
            _table(_flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_V)),
        )
        stated = _citing(*rows, _reused_from("TS29.800", ("Feature", _MUST)))
        ours = _model(_origin(), stated).resolve("TS29.900", "Feature")
        assert ours is not None and ours.flag_rules == _vendor_rules("must")
        silent = _citing(*rows, _reused_from("TS29.800", ("Feature", None)))
        ours = _model(_origin(), silent).resolve("TS29.900", "Feature")
        assert ours is not None and ours.flag_rules == _vendor_rules("must_not")

    def test_an_m_bit_over_an_unflagged_ietf_avp_takes_rfc_6733s_v(self):
        """TS 29.273's `Key`, from RFC 6734, which prints no flag columns."""
        origin = _spec(
            "RFC6734",
            [_flagless_table(_flagged("Key", 581, ast.DataType.GROUPED))],
            vendor_id=0,
            version=None,
        )
        citing = _citing(_reused_from("RFC6734", ("Key", _MUST_NOT)))
        built = _model(origin, citing)
        ours = built.resolve("TS29.900", "Key")
        assert ours is not None
        assert ours.flag_rules == model.FlagRules(must_not=_M | _V)
        theirs = dataclasses.replace(ours, flag_rules=_IETF_RULES)
        assert built.resolve("RFC6734", "Key") == theirs

    def test_an_m_bit_alone_completes_no_vendor_avp(self):
        origin = _spec(
            "3GPP TS 29.800",
            [_flagless_table(_flagged("Feature", 2, ast.DataType.UNSIGNED32))],
        )
        citing = _citing(_reused_from("TS29.800", ("Feature", _MUST)))
        hole = _model(origin, citing).hole("TS29.900", "Feature")
        assert hole is not None and hole.missing == (model.FLAG_RULES,)

    def test_a_file_citing_itself_reads_its_own_rules(self):
        """TS 29.212's Gxx tables re-use TS 29.212's AVPs from TS 29.212."""
        spec = _spec(
            "3GPP TS 29.900",
            [
                _table(_flagged("Feature", 2, ast.DataType.UNSIGNED32, must=_M | _V)),
                _reused_from("TS29.900", ("Feature", _MUST_NOT)),
            ],
        )
        ours = _model(spec).resolve("TS29.900", "Feature")
        assert ours is not None
        assert ours.flag_rules == _vendor_rules("must")


class TestHoles:
    def test_a_reprint_without_a_table_row_takes_the_origins_flag_rules(self):
        """TS 29.272 re-prints TS 29.212's Allocation-Retention-Priority and
        tabulates it nowhere; the flag rules are the origin's."""
        origin = _spec(
            "3GPP TS 29.901",
            [_grouped("Thing", 1, "A"), _table(_row("Thing", 1, ast.DataType.GROUPED))],
        )
        reprint = _spec(
            "3GPP TS 29.900",
            [_grouped("Thing", 1, "A"), _reused("Thing", "TS29.901")],
        )
        resolved = _model(origin, reprint).resolve("TS29.900", "Thing")
        assert isinstance(resolved, model.Grouped)
        assert resolved.defined_in == "TS29.900"
        assert ast.AvpFlag.VENDOR in resolved.flag_rules.must

    def test_completed_by_names_who_states_what_the_origin_does_not(self):
        origin = _spec(
            "3GPP TS 29.901",
            [_table(ast.AvpTableRow(name="Thing", data_type=ast.DataType.UTF8_STRING))],
        )
        citing = _spec(
            "3GPP TS 29.900",
            [
                _table(_row("Thing", 7, ast.DataType.UTF8_STRING)),
                _reused("Thing", "TS29.901"),
            ],
        )
        built = _model(origin, citing)

        resolved = built.resolve("TS29.900", "Thing")

        assert resolved is not None and resolved.defined_in == "TS29.901"
        assert dict(resolved.completed_by) == {
            "code": "TS29.900",
            "vendor_id": "TS29.900",
            "flag_rules": "TS29.900",
        }
        hole = built.hole("TS29.901", "Thing")
        assert hole is not None and hole.missing == ("code", "flag_rules")

    def test_completed_by_follows_a_field_to_the_document_stating_it(self):
        """A reprint takes its flags through its origin's reading, and the
        origin's complete reading has nothing to name."""
        origin = _spec(
            "3GPP TS 29.901",
            [_grouped("Thing", 1, "A"), _table(_row("Thing", 1, ast.DataType.GROUPED))],
        )
        reprint = _spec(
            "3GPP TS 29.900",
            [_grouped("Thing", 1, "A"), _reused("Thing", "TS29.901")],
        )
        built = _model(origin, reprint)

        resolved = built.resolve("TS29.900", "Thing")
        assert resolved is not None
        assert dict(resolved.completed_by) == {"flag_rules": "TS29.901"}
        theirs = built.resolve("TS29.901", "Thing")
        assert theirs is not None and theirs.completed_by == ()

    def test_an_origin_without_a_type_takes_the_citing_tables(self):
        """RFC 4590 is a RADIUS document and types none of its attributes;
        TS 29.229's own table types the Digest AVPs it re-uses. The origin's
        own reading keeps the hole."""
        origin = _spec(
            "RFC4590",
            [_flagless_table(ast.AvpTableRow(name="Digest-Realm", code=104))],
            vendor_id=0,
            version=None,
        )
        citing = _spec(
            "3GPP TS 29.900",
            [
                _table(
                    _row(
                        "Digest-Realm", 104, ast.DataType.UTF8_STRING, vendor="must_not"
                    )
                ),
                _reused("Digest-Realm", "RFC4590"),
            ],
        )
        built = _model(origin, citing)
        resolved = built.resolve("TS29.900", "Digest-Realm")
        assert resolved is not None
        assert (resolved.defined_in, resolved.identity) == ("RFC4590", (0, 104))
        assert resolved.data_type is ast.DataType.UTF8_STRING
        assert built.resolve("RFC4590", "Digest-Realm") is None
        assert built.holes() == (
            model.Hole(
                "RFC4590",
                "Digest-Realm",
                (model.DATA_TYPE,),
                vendor_id=0,
                code=104,
                flag_rules=_IETF_RULES,
            ),
        )

    def test_an_ietf_avp_no_reading_flags_takes_rfc_6733s_rule(self):
        """RFC 5777 prints no flag columns. RFC 6733 section 4.1 leaves the M
        bit to the application using the AVP, and section 4.1.1 forbids a
        zero Vendor-ID, so V is Must-not: complete, by rule."""
        spec = _spec(
            "RFC5777",
            [_flagless_table(ast.AvpTableRow(name="Port", code=530, data_type=_I32))],
            vendor_id=0,
            version=None,
        )
        built = model.Model.build(corpus.Corpus([_entry(spec)]), strict=True)
        resolved = built.resolve("RFC5777", "Port")
        assert resolved is not None
        assert resolved.flag_rules == _IETF_RULES
        assert resolved.flag_rules != model.FlagRules(must_not=_V)

    def test_a_citing_tables_m_bit_comes_before_rfc_6733s_rule(self):
        """TS 29.273 sets M for RFC 5777's `QoS-Capability` in its own table;
        its reading takes that, and RFC 5777's own reading keeps the rule."""
        origin = _spec(
            "RFC5777",
            [_flagless_table(ast.AvpTableRow(name="Port", code=530, data_type=_I32))],
            vendor_id=0,
            version=None,
        )
        rules = model.FlagRules(must=_M, must_not=_V)
        row = ast.AvpTableRow(name="Port", code=530, data_type=_I32, flag_rules=rules)
        citing = _spec("3GPP TS 29.900", [_table(row), _reused("Port", "RFC5777")])
        built = _model(origin, citing)
        resolved = built.resolve("TS29.900", "Port")
        assert resolved is not None
        assert (resolved.defined_in, resolved.flag_rules) == ("RFC5777", rules)
        origins = built.resolve("RFC5777", "Port")
        assert origins is not None and origins.flag_rules == _IETF_RULES

    def test_an_ietf_row_placing_v_only_has_m_application_defined(self):
        """RFC 7683's table places V under Must-not and M nowhere, and says
        the M-bit usage "may be defined by the application"."""
        rules = ast.AvpFlagRules(must_not=_V)
        row = ast.AvpTableRow(name="OC-OLR", code=623, data_type=_I32, flag_rules=rules)
        spec = _spec("RFC7683", [_table(row)], vendor_id=0, version=None)
        resolved = _model(spec).resolve("RFC7683", "OC-OLR")
        assert resolved is not None
        assert resolved.flag_rules == _IETF_RULES

    def test_a_vendor_row_placing_v_only_states_no_m(self):
        """TS 29.389 table 6.3.1-1, V read from clause 6.3.1: no rule
        completes a vendor AVP's M bit."""
        row = ast.AvpTableRow(
            name="Thing", code=1, data_type=_I32, flag_rules=ast.AvpFlagRules(must=_V)
        )
        resolved = _model(_spec("3GPP TS 29.900", [_table(row)])).resolve(
            "TS29.900", "Thing"
        )
        assert resolved is not None
        assert not resolved.flag_rules.application_defined

    def test_a_bit_cannot_be_both_placed_and_application_defined(self):
        with pytest.raises(ValueError, match="both placed and application-defined"):
            model.FlagRules(may=_M, application_defined=_M)

    def test_readings_giving_two_codes_are_not_merged(self):
        origin = _spec("3GPP TS 29.901", [_table(_row("Thing", 2))])
        citing = _spec(
            "3GPP TS 29.900",
            [_flagless_table(ast.AvpTableRow(name="Thing", code=1))],
            bases=["TS29.901"],
        )
        hole = _model(origin, citing).hole("TS29.900", "Thing")
        assert hole is not None
        assert hole.missing == (model.DATA_TYPE, model.FLAG_RULES)
        assert hole.conflict == "TS29.901"

    def test_a_definition_in_another_vendors_space_fills_nothing(self):
        """(10415, 1) and (999, 1) are two AVPs, whatever the name says."""
        origin = _spec(
            "3GPP TS 29.901",
            [
                _grouped("Thing", 1, "A", vendor_id=999),
                _table(_row("Thing", 1, ast.DataType.GROUPED)),
            ],
            vendor_id=999,
        )
        reprint = _spec(
            "3GPP TS 29.900",
            [_grouped("Thing", 1, "A"), _reused("Thing", "TS29.901")],
        )
        built = _model(origin, reprint)
        assert built.resolve("TS29.900", "Thing") is None
        assert str(built.hole("TS29.900", "Thing")) == (
            "TS29.900 Thing: no flag_rules; TS29.901's reading, which states it,"
            " disagrees"
        )

    def test_a_table_rows_vendor_is_inferred_and_agrees_with_any(self):
        """The origin only tabulates the AVP, with V under May, so its vendor
        is its file's `; Vendor-ID:`, which is no claim against the
        definition's."""
        origin = _spec(
            "3GPP TS 29.901",
            [_table(_row("Thing", 1, ast.DataType.GROUPED, vendor="may"))],
            vendor_id=999,
        )
        reprint = _spec(
            "3GPP TS 29.900",
            [_grouped("Thing", 1, "A"), _reused("Thing", "TS29.901")],
        )
        resolved = _model(origin, reprint).resolve("TS29.900", "Thing")
        assert resolved is not None
        assert resolved.identity == (10415, 1)
        assert ast.AvpFlag.VENDOR in resolved.flag_rules.may

    def test_a_row_forbidding_v_is_ietf_space(self):
        """TS 29.229's `Digest-QoP` row prints V under Must-not in vendor
        10415's table; the AVP is RFC 4590's code 110 in vendor 0."""
        spec = _spec(
            "3GPP TS 29.900",
            [
                _table(
                    _row("Digest-QoP", 110, ast.DataType.UTF8_STRING, vendor="must_not")
                )
            ],
        )
        resolved = _model(spec).resolve("TS29.900", "Digest-QoP")
        assert resolved is not None
        assert resolved.identity == (0, 110)

    def test_a_rows_vendor_id_cell_is_its_vendor(self):
        """oneM2M TS-0004 table A.4-1 mixes vendors: each row's identity is
        its own Vendor-ID cell and code, whatever its V flag says."""
        rows = (
            ast.AvpTableRow(name="Occupancy", vendor_id=45687, code=1012),
            ast.AvpTableRow(name="Node-Id", vendor_id=10415, code=2064),
            _row("Session-Id", 263, vendor="must_not").model_copy(
                update={"vendor_id": 0}
            ),
        )
        spec = _spec("oneM2M TS-0004", [_table(*rows)], vendor_id=45687, version=None)
        built = _model(spec)
        identities = {}
        for row in rows:
            resolved = built.resolve("oneM2M-TS-0004", row.name)
            identities[row.name] = None if resolved is None else resolved.identity
        hole = built.hole("oneM2M-TS-0004", "Occupancy")
        assert hole is not None
        assert (hole.vendor_id, hole.code) == (45687, 1012)
        assert identities["Session-Id"] == (0, 263)

    def test_a_row_requiring_v_states_the_files_vendor(self):
        """A row requiring V states its file's vendor, so a definition in
        another vendor's space does not fill it."""
        origin = _spec(
            "3GPP TS 29.901",
            [_table(_row("Thing", 1, ast.DataType.GROUPED))],
            vendor_id=999,
        )
        reprint = _spec(
            "3GPP TS 29.900",
            [_grouped("Thing", 1, "A"), _reused("Thing", "TS29.901")],
        )
        built = _model(origin, reprint)
        assert built.resolve("TS29.900", "Thing") is None
        hole = built.hole("TS29.900", "Thing")
        assert hole is not None
        assert hole.conflict == "TS29.901"

    @pytest.mark.parametrize(
        ("theirs", "complete"),
        [(ast.DataType.TIME, True), (ast.DataType.UNSIGNED32, False)],
    )
    def test_readings_fill_each_other_only_where_they_agree(self, theirs, complete):
        """A `Time` row with blank flag cells takes the flags of a `Time`
        reading of the same code, never of an `Unsigned32` one: that would
        be a complete AVP assembled from a disagreement."""
        blank = ast.AvpTableRow(name="Thing", code=1, data_type=ast.DataType.TIME)
        base = _spec("3GPP TS 29.901", [_table(_row("Thing", 1, theirs))])
        citing = _spec("3GPP TS 29.900", [_table(blank)], bases=["TS29.901"])
        built = _model(base, citing)
        resolved = built.resolve("TS29.900", "Thing")
        hole = built.hole("TS29.900", "Thing")
        if complete:
            assert resolved is not None
            assert resolved.data_type is ast.DataType.TIME
            assert hole is None
        else:
            assert resolved is None
            assert hole is not None
            assert (hole.missing, hole.conflict) == ((model.FLAG_RULES,), "TS29.901")

    def test_empty_flag_cells_are_a_hole_not_an_absence_of_flags(self):
        """TS 32.299 table 7.2.0.1 prints `-` in every flag cell of most
        re-printed rows; that states nothing about the M bit."""
        blank = ast.AvpTableRow(name="Thing", code=1, data_type=ast.DataType.UNSIGNED32)
        spec = _spec("3GPP TS 29.900", [_table(blank)])
        hole = _model(spec).hole("TS29.900", "Thing")
        assert hole is not None
        assert hole.missing == (model.FLAG_RULES,)
        assert hole.data_type is ast.DataType.UNSIGNED32

    def test_a_struck_member_still_in_its_body_is_a_member(self):
        # Behind `struck-rules-unused` a struck member is a comment, no
        # member; without it the strike is only a marker on the rule.
        message = _message("Test-Request", "Thing")
        struck = message.avps[0].model_copy(update={"strikethrough": True})
        spec = _spec(
            "3GPP TS 29.900",
            [message.model_copy(update={"avps": (struck,)}), _table(_row("Thing", 1))],
        )

        (resolved,) = _model(spec).messages("TS29.900")

        (member,) = resolved.avps
        assert member.rule.strikethrough and member.avp is not None

    def test_a_member_with_a_hole_says_why_it_has_no_avp(self):
        absent = _spec(
            "3GPP TS 29.900",
            [
                _message("Test-Request", "Nowhere", "Elsewhere"),
                _reused("Elsewhere", "3GPP2-X.S0057"),
            ],
        )
        (message,) = _model(absent).messages("TS29.900")
        assert [member.avp for member in message.avps] == [None, None]
        assert [str(member.hole) for member in message.avps] == [
            "TS29.900 Nowhere: resolves nowhere",
            "TS29.900 Elsewhere: resolves nowhere"
            " (re-used from 3GPP2-X.S0057, which the corpus lacks)",
        ]

    def test_a_strict_build_names_every_hole(self):
        spec = _spec(
            "3GPP TS 29.900",
            [
                _message("Test-Request", "Nowhere"),
                _flagless_table(
                    ast.AvpTableRow(name="Thing", code=1, data_type=ast.DataType.TIME)
                ),
            ],
        )
        books = corpus.Corpus([_entry(spec)])
        with pytest.raises(model.IncompleteCorpusError) as raised:
            model.Model.build(books, strict=True)
        assert str(raised.value) == (
            "the corpus has 2 holes (Model.build(..., strict=False) builds the"
            " rest):\n  TS29.900 Nowhere: resolves nowhere"
            "\n  TS29.900 Thing: no flag_rules"
        )
        assert raised.value.holes == model.Model.build(books, strict=False).holes()

    def test_a_complete_corpus_builds_strictly(self):
        spec = _spec(
            "3GPP TS 29.900",
            [_message("Test-Request", "Thing"), _table(_row("Thing", 1))],
        )
        built = model.Model.build(corpus.Corpus([_entry(spec)]), strict=True)
        assert built.holes() == ()


class TestQueries:
    def test_an_unknown_reference_is_an_error_not_an_empty_answer(self):
        with pytest.raises(model.ModelError):
            _model().messages("TS29.999")

    def test_a_definitions_flag_rules_come_from_its_table_row(self):
        spec = _spec(
            "3GPP TS 29.900",
            [_grouped("Thing", 1, "A"), _table(_row("Thing", 1, ast.DataType.GROUPED))],
        )
        resolved = _model(spec).resolve("TS29.900", "Thing")
        assert resolved is not None
        assert resolved.flag_rules is not None
        assert ast.AvpFlag.VENDOR in resolved.flag_rules.must


class TestCommandShape:
    @pytest.mark.parametrize(
        ("presence", "spelled", "bounds"),
        [
            (ast.Presence.FIXED, (1, 1), (1, 1)),
            (ast.Presence.REQUIRED, (1, 1), (1, 1)),
            (ast.Presence.REQUIRED, (0, None), (1, None)),
            (ast.Presence.REQUIRED, (2, 4), (2, 4)),
            (ast.Presence.OPTIONAL, (1, 1), (0, 1)),
            (ast.Presence.OPTIONAL, (1, 2), (0, 2)),
            (ast.Presence.OPTIONAL, (0, None), (0, None)),
            (ast.Presence.OPTIONAL, (0, 3), (0, 3)),
        ],
    )
    def test_occurrence_bounds_follow_rfc_6733s_qualifier_defaults(
        self, presence, spelled, bounds
    ):
        """`[ X ]` may be absent and `* { X }` must appear at least once,
        though the AST records the qualifier as spelled."""
        minimum, maximum = spelled
        rule = ast.AvpRule(
            name="X", presence=presence, min_occurs=minimum, max_occurs=maximum
        )
        member = model.Member(rule=rule, avp=None)
        assert (member.min_occurs, member.max_occurs) == bounds

    def test_applications_split_by_application_id_and_interface_clause(self):
        def message(name, section, application_id):
            return ast.Message(
                type="Message",
                name=name,
                abbreviation="TR",
                source=ast.SourceRef(section=section),
                command_code=300,
                flags=frozenset({ast.CommandFlag.REQUEST}),
                application_id=application_id,
                avps=(),
            )

        spec = _spec(
            "3GPP TS 29.900",
            [
                message("A-Request", "5.6.2", None),
                message("B-Request", "5a.6.2", None),
                message("C-Request", "5a.6.3", None),
                message("D-Request", "7.2.9", 1),
                message("E-Request", "7.2.9", 2),
                message("F-Request", "A.7.6.2", None),
                message("G-Request", "A.8.6.2", None),
            ],
        )
        found = [
            (app.application_id, app.clause, [m.name for m in app.messages])
            for app in _model(spec).applications("TS29.900")
        ]
        assert found == [
            (None, "5", ["A-Request"]),
            (None, "5a", ["B-Request", "C-Request"]),
            (1, "7", ["D-Request"]),
            (2, "7", ["E-Request"]),
            (None, "A.7", ["F-Request"]),
            (None, "A.8", ["G-Request"]),
        ]


def test_a_dictionary_adds_wireshark_names_beside_the_documents(tmp_path):
    """With a Wireshark dictionary every AVP and hole with an identity
    carries its name there; the document's spelling stays the AVP's name."""
    (tmp_path / "dictionary.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<dictionary>
  <base>
    <avp name="Wireshark-Thing" code="1" vendor-id="TGPP">
      <type type-name="Unsigned32"/>
    </avp>
  </base>
  <vendor vendor-id="TGPP" code="10415" name="3GPP"/>
</dictionary>
""",
        encoding="utf-8",
    )
    spec = _spec("3GPP TS 29.900", [_table(_row("Thing", 1), _row("Other", 2))])
    books = corpus.Corpus([_entry(spec)])

    plain = model.Model.build(books).resolve("TS29.900", "Thing")
    named = model.Model.build(books, dictionary=tmp_path).resolve("TS29.900", "Thing")
    other = model.Model.build(books, dictionary=tmp_path).resolve("TS29.900", "Other")

    assert plain is not None and plain.wireshark_name is None
    assert named is not None
    assert (named.name, named.wireshark_name) == ("Thing", "Wireshark-Thing")
    assert other is not None and other.wireshark_name is None


@pytest.fixture(scope="module")
def built() -> model.Model:
    return model.Model.build(corpus.Corpus.load([_CORPUS_DIR]))


class TestOverTheCommittedCorpus:
    def test_a_reprint_defines_nothing(self, built):
        # TS 29.109 prints RFC 6733's rule three times, and RFC 6733 answers.
        definition = built.definition((0, 260))
        assert definition is not None
        assert definition.defined_in == "RFC6733"
        assert 260 not in {avp.code for avp in built.avps("TS29.109")}

    def test_29229s_commands_resolve_completely(self, built):
        """Every name in every Cx command body resolves; the only bare
        member is the any-AVP wildcard."""
        messages = built.messages("TS29.229")
        assert sorted({m.command_code for m in messages}) == list(range(300, 306))
        for message in messages:
            unresolved = [m.name for m in message.avps if m.avp is None]
            assert unresolved in ([], ["AVP"]), (message.name, unresolved)

        (uar,) = [m for m in built.messages("TS29.229") if m.abbreviation == "UAR"]
        by_name = {member.name: member.avp for member in uar.avps}
        session_id = by_name["Session-Id"]
        assert session_id is not None
        assert (session_id.defined_in, session_id.identity) == ("RFC6733", (0, 263))

    def test_applications_follow_each_documents_interfaces(self, built):
        """TS 29.272 splits S6a/S6d, S13 and S7a by application id within
        clause 7, its VCSG commands joining S7a through clause 7.2.2's
        block; TS 29.212's headers print no ids, so Gx, Gxx, Sd, St and
        annex E take theirs from the clauses stating them and split by
        clause; TS 29.273 shares 16777250 between SWa, STa and SWd."""

        def keys(reference):
            return [
                (app.application_id, app.clause, app.name, app.stated_in)
                for app in built.applications(reference)
            ]

        assert keys("TS29.272") == [
            (16777251, "7", None, None),
            (16777308, "7", "S7a/S7d", "7.2.2"),
            (16777252, "7", None, None),
        ]
        assert keys("TS29.212") == [
            (16777238, "5", "Gx", "5.1"),
            (16777266, "5a", "Gxx", "5a.1"),
            (16777303, "5b", "Sd", "5b.1"),
            (16777349, "5c", "St", "5c.1"),
            (16777318, "E.6", "S15", "E.6.1"),
        ]
        assert [key[:2] for key in keys("TS29.273")] == [
            (16777250, "4"),
            (16777250, "5"),
            (16777250, "6"),
            (16777264, "7"),
            (16777265, "8"),
            (16777272, "9"),
        ]

    def test_application_blocks_split_a_clause_and_leave_the_rest(self, built):
        """TS 32.299 clause 6 defines Rf (6.2, 3) and Ro (6.4, 4), RFC 5778's
        clause 5 MIP6I (5.1, 7) and MIP6A (5.2, 8); RFC 6733's clause 8
        commands carry the using application's id, which no block states."""

        def keys(reference):
            return [
                (app.application_id, app.clause, [m.abbreviation for m in app.messages])
                for app in built.applications(reference)
            ]

        assert keys("TS32.299") == [
            (3, "6", ["ACR", "ACA"]),
            (4, "6", ["CCR", "CCA", "RAR", "RAA"]),
        ]
        assert keys("RFC5778") == [(7, "5", ["DER", "DEA"]), (8, "5", ["MIR", "MIA"])]
        assert [key[:2] for key in keys("RFC6733")] == [(0, "5"), (None, "8"), (3, "9")]

    def test_the_two_code_621_spaces_stay_separate(self, built):
        """TS 29.229's own 621 and RFC 7683's 621 are different AVPs, which
        is the case that forced identity to be a (vendor, code) pair."""
        assert {a.name for a in built.identified(10415, 621)} == {
            "Primary-Charging-Collection-Function-Name"
        }
        assert {a.name for a in built.identified(0, 621)} == {"OC-Supported-Features"}

    def test_the_first_table_row_wins_and_the_others_stay_reachable(self, built):
        """TS 29.061 tabulates 3GPP-IMSI in tables 9a (Gi/SGi, M in M.not)
        and 10 (Gmb, M in Must); resolution reads table 9a's."""
        imsi = built.resolve("TS29.061", "3GPP-IMSI")
        assert imsi is not None
        assert imsi.flag_rules is not None
        assert ast.AvpFlag.MANDATORY in imsi.flag_rules.must_not
        first, second = built.table_rows("TS29.061", "3GPP-IMSI")
        assert model.FlagRules.printed(first.flag_rules) == imsi.flag_rules
        assert ast.AvpFlag.MANDATORY in second.flag_rules.must
        assert built.table_rows("TS29.061", "No-Such-AVP") == ()

    def test_marks_come_from_every_table_row_in_file_order(self, built):
        """TS 29.212 marks AN-GW-Address in Gx's AVP table and again in
        Gxx's re-used table, a note reference kept with its mark; TS 32.299
        marks Error-Message per command, `()` for each printed dash, and
        leaves Termination-Cause blank, None, under ACR."""
        gx, gxx = built.marks("TS29.212", "AN-GW-Address")
        assert (gx.table, gx.section) == ("5.3.0.1", "5.3.0")
        assert gx.marks == {
            ast.MarkColumn.ACCESS_TYPES: ("All",),
            ast.MarkColumn.APPLICABILITY: ("Both", "Rel8", "EPC-routed"),
        }
        assert gxx.table == "5a.4.0.1"
        assert gxx.marks[ast.MarkColumn.APPLICABILITY] == ("EPC-routed (See NOTE 8)",)
        (charging,) = built.marks("TS32.299", "Error-Message")
        commands = [ast.MarkColumn(each) for each in ("ACR", "ACA", "CCR", "CCA")]
        assert charging.marks == dict.fromkeys(commands, ())
        (termination,) = built.marks("TS32.299", "Termination-Cause")
        assert list(termination.marks.values()) == [None, (), ("OC",), ()]
        assert built.marks("TS29.229", "User-Data") == ()

    def test_a_reused_chain_is_followed_across_files(self, built):
        drmp = built.resolve("TS29.229", "DRMP")
        assert drmp is not None
        assert drmp.defined_in == "RFC7944"
        assert isinstance(drmp, model.Enumerated)

    def test_a_reprint_takes_its_flag_rules_through_the_origin(self, built):
        """TS 29.272 clause 7.3.40 re-prints Allocation-Retention-Priority,
        re-used from TS 29.212, and tabulates it nowhere."""
        arp = built.resolve("TS29.272", "Allocation-Retention-Priority")
        assert isinstance(arp, model.Grouped)
        assert arp.defined_in == "TS29.272"
        assert built.table_rows("TS29.272", "Allocation-Retention-Priority") == ()
        (row, *_) = built.table_rows("TS29.212", "Allocation-Retention-Priority")
        assert arp.flag_rules == model.FlagRules.printed(row.flag_rules)

    def test_an_externally_defined_enumeration_is_complete(self, built):
        """TS 29.272 clause 7.3.141 defines Report-Interval and points at TS
        32.422 for its values, which no flat list holds: an AVP with no
        values and their source, not a hole. Clause 7.3.67's Trace-Depth
        points there too, and its supplied values keep the citation."""
        report_interval = built.resolve("TS29.272", "Report-Interval")
        assert isinstance(report_interval, model.Enumerated)
        assert report_interval.values == ()
        assert report_interval.values_source == "TS 32.422 [23] for Report Interval"
        assert built.hole("TS29.272", "Report-Interval") is None
        trace_depth = built.resolve("TS29.272", "Trace-Depth")
        assert isinstance(trace_depth, model.Enumerated)
        assert trace_depth.values[0] == ast.EnumValue(name="Minimum", value=0)
        assert trace_depth.values_source == "TS 32.422 [23] for Trace Depth"
        alert_reason = built.resolve("TS29.272", "Alert-Reason")
        assert isinstance(alert_reason, model.Enumerated)
        assert alert_reason.values_source is None

    def test_sm_service_type_leaves_100_to_199_to_vendors(self, built):
        sm_service_type = built.resolve("TS32.299", "SM-Service-Type")
        assert isinstance(sm_service_type, model.Enumerated)
        assert sm_service_type.vendor_specific == (
            ast.VendorSpecificValues(
                first=100, last=199, description="Vendor specific SM services"
            ),
        )

    def test_oc_report_type_holds_the_value_rfc_8581_adds(self, built):
        """RFC 8581 clause 7.2.1 adds PEER_REPORT to RFC 7683's list."""
        report_type = built.resolve("RFC7683", "OC-Report-Type")
        assert isinstance(report_type, model.Enumerated)
        assert report_type.values == (
            ast.EnumValue(name="HOST_REPORT", value=0),
            ast.EnumValue(name="REALM_REPORT", value=1),
            ast.EnumValue(name="PEER_REPORT", value=2),
        )

    def test_32299s_supported_features_holds_its_own_feature_list(self, built):
        """TS 32.299 table 7.2.0.1 sets M on Supported-Features and on its
        Feature-List-ID and Feature-List members, all TS 29.229's, whose table
        6.3.0.1 forbids M on the two members: through TS 32.299 the body is
        TS 29.229's and the members TS 32.299's."""
        ours = built.resolve("TS32.299", "Supported-Features")
        theirs = built.resolve("TS29.229", "Supported-Features")
        assert isinstance(ours, model.Grouped) and isinstance(theirs, model.Grouped)
        assert ours.defined_in == "TS29.229"
        assert [m.rule for m in ours.members] == [m.rule for m in theirs.members]
        for name in ("Feature-List-ID", "Feature-List"):
            (mine,) = [m.avp for m in ours.members if m.name == name]
            (other,) = [m.avp for m in theirs.members if m.name == name]
            assert mine is not None and other is not None
            assert mine.flag_rules == model.FlagRules(must=_M | _V)
            assert other.flag_rules == model.FlagRules(must=_V, must_not=_M)
            assert mine == built.resolve("TS32.299", name)
        # Vendor-Id, which TS 32.299 tabulates with dashes, is RFC 6733's.
        assert ours.members[0].name == "Vendor-Id"
        assert ours.members[0].avp == built.resolve("TS32.299", "Vendor-Id")
        assert ours.members[0].avp == theirs.members[0].avp

    def test_32299s_m2m_information_keeps_onem2ms_originator(self, built):
        """TS 32.299 defines its own Originator, (10415, 864) Enumerated; the
        M2M-Information it re-uses from oneM2M TS-0004 holds oneM2M's, which
        a name read through TS 32.299 must not replace."""
        ours = built.resolve("TS32.299", "M2M-Information")
        theirs = built.resolve("oneM2M-TS-0004", "M2M-Information")
        assert isinstance(ours, model.Grouped) and isinstance(theirs, model.Grouped)
        (mine,) = [m.avp for m in ours.members if m.name == "Originator"]
        (other,) = [m.avp for m in theirs.members if m.name == "Originator"]
        assert mine is other
        assert mine is not None
        assert (mine.identity, mine.data_type) == ((45687, 1008), _UTF8)
        own = built.resolve("TS32.299", "Originator")
        assert own is not None
        assert (own.identity, own.data_type) == (
            (10415, 864),
            ast.DataType.ENUMERATED,
        )

    def test_29061s_local_m1_information_keeps_29468s_addresses(self, built):
        """TS 29.061's own MBMS-GW-SSM-IP-Address and -IPv6-Address are 924
        and 925 OctetString; the Local-M1-Information it re-uses from TS
        29.468 holds TS 29.468's, 3522 and 3523 Address."""
        ours = built.resolve("TS29.061", "Local-M1-Information")
        assert isinstance(ours, model.Grouped)
        found = {
            m.name: (m.avp.identity, m.avp.data_type)
            for m in ours.members
            if m.avp is not None and m.name.startswith("MBMS-GW-SSM-")
        }
        assert found == {
            "MBMS-GW-SSM-IP-Address": ((10415, 3522), ast.DataType.ADDRESS),
            "MBMS-GW-SSM-IPv6-Address": ((10415, 3523), ast.DataType.ADDRESS),
        }
        own = built.resolve("TS29.061", "MBMS-GW-SSM-IP-Address")
        assert own is not None and own.identity == (10415, 924)

    @pytest.mark.parametrize(
        ("reference", "name"),
        [
            ("TS29.336", "DRMP"),
            ("TS29.336", "OC-OLR"),
            ("TS29.273", "OC-Supported-Features"),
            ("TS29.338", "SGSN-Number"),
        ],
    )
    def test_a_later_re_used_rows_m_bit_counts_where_earlier_ones_say_nothing(
        self, built, reference, name
    ):
        """TS 29.336 prints `-` for DRMP in table 6.4.1/2 and MUST-NOT in
        8.4.1-2; TS 29.273 prints MUST-NOT for OC-Supported-Features in
        8.2.3.0/2 alone of four tables, TS 29.338 for SGSN-Number in 6.3.3.1/2
        alone of two: through each, M is in Must not."""
        ours = built.resolve(reference, name)
        assert ours is not None
        assert ast.AvpFlag.MANDATORY in ours.flag_rules.must_not

    def test_29272s_m_bit_sets_m_on_29212s_rat_type(self, built):
        """TS 29.272 table 7.3.1/2 marks RAT-Type "Must" in its M-bit column
        where TS 29.212 table 5.3.1 puts M in Must not: through TS 29.272 M
        is in Must, at top level and inside TS 29.272's eDRX-Cycle-Length."""
        ours = built.resolve("TS29.272", "RAT-Type")
        theirs = built.resolve("TS29.212", "RAT-Type")
        assert ours is not None and theirs is not None
        assert (ours.defined_in, ours.identity) == ("TS29.212", theirs.identity)
        assert ours.flag_rules == model.FlagRules(must=_M | _V, may=_P)
        assert theirs.flag_rules == model.FlagRules(must=_V, may=_P, must_not=_M)
        cycle = built.resolve("TS29.272", "eDRX-Cycle-Length")
        assert isinstance(cycle, model.Grouped)
        (member,) = [m.avp for m in cycle.members if m.name == "RAT-Type"]
        assert member == ours

    @pytest.mark.parametrize(
        "name", ["Digest-Realm", "Digest-Algorithm", "Digest-Qop", "Digest-HA1"]
    )
    def test_the_digest_avps_take_rfc_4590s_stand_in_types(self, built, name):
        """RFC 4590 types nothing; its corrections type all twenty
        UTF8String with Wireshark's flag rules, M in May. TS 29.229's re-used
        Digest AVPs take RFC 4590's type and identity and their own table's
        M in Must, RFC 4590's P in May filling the bit the table leaves."""
        ours = built.resolve("TS29.229", name)
        theirs = built.resolve("RFC4590", name)
        assert ours is not None and theirs is not None
        assert (ours.defined_in, ours.data_type) == ("RFC4590", _UTF8)
        assert (ours.identity, ours.data_type) == (theirs.identity, theirs.data_type)
        assert ours.flag_rules == model.FlagRules(must=_M, may=_P, must_not=_V)
        assert theirs.flag_rules == model.FlagRules(may=_M | _P, must_not=_V)
        assert built.holes("RFC4590") == ()

    def test_the_registry_answers_by_code_beside_the_model(self, built):
        (cx,) = built.registry(ast.RegistryKind.APPLICATION_IDS, 16777216)
        assert (cx.reference, cx.table, cx.section) == ("TS29.230", "4.1", "4.1")
        assert cx.entry == ast.RegistryRow(
            code=16777216, name="3GPP Cx/Px", defined_in=("TS29.228", "TS29.229")
        )
        # Table 7.1 prints 318 in TS 29.234's block and again in TS 29.273's.
        twice = built.registry(ast.RegistryKind.AVP_CODES, 318)
        assert [allocation.entry.defined_in for allocation in twice] == [
            ("TS29.234",),
            (),
        ]
        (radius,) = built.registry(ast.RegistryKind.AVP_CODES, 1)
        assert isinstance(radius.entry, ast.RegistryReservation)
        assert (radius.entry.first, radius.entry.last) == (1, 255)
        # Every row and range of TS 29.230's application id tables, no others.
        spec = next(
            entry.spec
            for entry in corpus.Corpus.load(_CORPUS_DIR).newest()
            if entry.reference == "TS29.230"
        )
        printed = [
            row
            for section in spec.sections
            if isinstance(section, ast.Registry)
            and section.registry is ast.RegistryKind.APPLICATION_IDS
            for row in section.rows
        ]
        allocations = built.registry(ast.RegistryKind.APPLICATION_IDS)
        assert printed
        assert [allocation.entry for allocation in allocations] == printed


def test_every_row_citing_an_etsi_tispan_origin_resolves_to_its_transcription():
    """3GPP cites ES 283 034 as "ETSI TS 283 034" and TS 183 017 under its
    own number; each row resolves to the transcribed document's AVP, in
    ETSI's vendor space, and the transcriptions cite each other too."""
    books = corpus.Corpus.load([_CORPUS_DIR])
    built = model.Model.build(books)
    cited = [
        (entry.reference, row.name, row.origin)
        for entry in books
        for section in entry.spec.sections
        if isinstance(section, ast.ReusedAvps)
        for row in section.rows
        if row.origin in {"ETSI-TS283.034", "ETSI-ES283.034", "ETSI-TS183.017"}
    ]

    assert {origin for _, _, origin in cited} == {
        "ETSI-TS283.034",
        "ETSI-ES283.034",
        "ETSI-TS183.017",
    }
    for reference, name, origin in cited:
        avp = built.resolve(reference, name)
        assert avp is not None, (reference, name)
        assert avp.vendor_id == 13019, (reference, name)
        # A transcription that re-prints what it imports reads its own copy
        # first (ES 283 034's Reservation-Priority, TS 183 017's
        # Globally-Unique-Address).
        assert avp.defined_in in {reference, corpus.CITED_AS.get(origin, origin)}


def test_3gpp2_bsid_resolves_to_the_3gpp2_transcription():
    """TS 29.212 re-uses 3GPP2-BSID from 3GPP2 X.S0057 and TS 32.299 from TS
    29.212; both reach table 1 of the transcription, in 3GPP2's vendor
    space, with the flag rules it prints, and say that revision 0 stands
    in for the revision B TS 29.212 [24] cites."""
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]))

    for reference in ("TS29.212", "TS32.299"):
        avp = built.resolve(reference, "3GPP2-BSID")
        assert avp is not None, reference
        assert (avp.defined_in, avp.identity, avp.data_type) == (
            "3GPP2-X.S0057",
            (5535, 9010),
            ast.DataType.UTF8_STRING,
        )
        flags = avp.flag_rules
        assert flags.must == {ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}
        assert flags.may == {ast.AvpFlag.PROTECTED}
        assert avp.across_releases == corpus.CrossRelease(
            "TS29.212",
            "3GPP2-X.S0057",
            "2.0",
            corpus.STAND_IN,
            cited_revision="B",
            revision="0",
        )


def test_without_its_stand_in_entry_3gpp2_bsid_is_a_hole(monkeypatch):
    """TS 29.212 [24] names revision B, which the corpus lacks; with no
    `corpus.STAND_INS` entry letting revision 0 answer, the AVP resolves
    nowhere, as it did before the transcription."""
    monkeypatch.delitem(corpus.STAND_INS, ("TS29.212", "3GPP2-X.S0057"))
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]), strict=False)

    assert built.resolve("TS29.212", "3GPP2-BSID") is None
    assert (
        "TS29.212 3GPP2-BSID: resolves nowhere (re-used from 3GPP2-X.S0057,"
        " which the corpus lacks)"
    ) in {str(hole) for hole in built.holes()}


def test_citations_across_releases_resolve_and_say_by_which_rule():
    """The drafting rules on references (docs/consumers.md): TS 32.299's
    non-specific TS 29.140 [213] is its final version, V7.0.0; TS 183
    017's "TS 29.214 Release 7" [19] and oneM2M TS-0004's "TS 32.299
    (Release 11)" [31] are the versions they name; TS 29.212's "3GPP2
    X.S0057-B" [24] is revision 0, standing in; and TS 32.299 V11.20.0's
    six non-specific Release 11 citations the corpus holds no Release 11
    copy of, TS 29.210 V6.7.0's and TS 29.234 V11.2.0's TS 29.229, and TS 183
    033's "TS 29.229 (V6.6.0)" [2], are Release 18's, standing in; ES 283 035's
    TS 29.329 [7] is the latest edition, as its clause 2.1 says. Each AVP so
    reached says so, and nothing else in the corpus resolves across releases."""
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]))

    vas = built.resolve("TS32.299", "VAS-ID")
    codec = built.resolve("ETSI-TS183.017", "Codec-Data")
    node = built.resolve("oneM2M-TS-0004", "Node-Id")

    assert vas is not None and codec is not None and node is not None
    assert (vas.identity, vas.data_type, vas.defined_in) == (
        (10415, 1102),
        ast.DataType.UTF8_STRING,
        "TS29.140",
    )
    assert vas.across_releases == corpus.CrossRelease(
        "TS32.299", "TS29.140", "7.0.0", corpus.NON_SPECIFIC
    )
    assert codec.across_releases == corpus.CrossRelease(
        "ETSI-TS183.017", "TS29.214", "7.12.0", corpus.SPECIFIC
    )
    assert node.across_releases == corpus.CrossRelease(
        "oneM2M-TS-0004", "TS32.299", "11.20.0", corpus.SPECIFIC
    )
    # The Release 18 reading of TS 32.299 is untouched by its older copy.
    current = built.resolve("TS32.299", "Node-Id")
    assert current is not None and current.across_releases is None
    crossings = {
        (found.across_releases.citing, found.across_releases.cited)
        for found in built.across_releases()
        if found.across_releases is not None
    }
    assert crossings == {
        ("ETSI-ES283.026", "TS29.209"),
        ("ETSI-ES283.034", "TS29.209"),
        ("ETSI-ES283.035", "TS29.209"),
        ("ETSI-ES283.035", "TS29.329"),
        ("ETSI-TS183.033", "TS29.229"),
        ("ETSI-TS183.017", "TS29.209"),
        ("ETSI-TS183.017", "TS29.214"),
        ("TS29.140", "TS29.061"),
        ("TS29.140", "TS29.329"),
        ("TS29.210", "TS29.229"),
        ("TS29.212", "3GPP2-X.S0057"),
        ("TS29.234", "TS29.229"),
        ("TS32.299", "TS29.061"),
        ("TS32.299", "TS29.140"),
        ("TS32.299", "TS29.173"),
        ("TS32.299", "TS29.229"),
        ("TS32.299", "TS29.272"),
        ("TS32.299", "TS29.273"),
        ("TS32.299", "TS29.329"),
        ("oneM2M-TS-0004", "TS32.299"),
    }
    # TS 29.212's and 32.299's 3GPP2-BSID are one Avp, revision 0 standing
    # in for TS 29.212's revision B. The audit list is sorted, and holds what
    # each reference's own list does.
    everything = built.across_releases()
    order = [
        (found.across_releases.citing, found.name)
        for found in everything
        if found.across_releases is not None
    ]
    assert len(order) == len(everything)
    assert order == sorted(order)
    # oneM2M's own two, the thirty-five its Service-Information reaches through
    # TS 32.299 V11.20.0's six release stand-ins, TS 29.061's
    # 3GPP-Session-Stop-Indicator a hole among them, V11.20.0's VAS-ID and
    # VASP-ID from TS 29.140 V7.0.0, and 3GPP2-BSID through TS 29.212 V11.19.0.
    reached = built.across_releases("oneM2M-TS-0004")
    assert len(reached) == 40
    assert set(reached) <= set(everything)
    rules = {
        (found.across_releases.cited, found.across_releases.rule)
        for found in reached
        if found.across_releases is not None
        and found.across_releases.citing == "TS32.299"
    }
    assert rules == {
        ("TS29.140", corpus.NON_SPECIFIC),
        *((cited, corpus.STAND_IN) for cited in ("TS29.061", "TS29.173")),
        *((cited, corpus.STAND_IN) for cited in ("TS29.229", "TS29.272")),
        *((cited, corpus.STAND_IN) for cited in ("TS29.273", "TS29.329")),
    }


def test_the_retired_documents_read_their_releases_re_uses():
    """TS 29.210 V6.7.0's TS 29.061 is the pinned V6.15.0, whose table 10 puts
    M in Must where Release 18's table 9a puts it in Must not; its TS 29.229,
    and TS 29.234 V11.2.0's, are V18.1.0, standing in for the V6.11.0 and
    V11.5.0 that define alike what each re-uses. TS 29.234 keeps its own
    SIP-Auth-Data-Item body, flag rules from TS 29.229."""
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]))

    rat = built.resolve("TS29.210", "3GPP-RAT-Type")
    assert rat is not None
    assert (rat.identity, rat.across_releases) == ((10415, 21), None)
    assert ast.AvpFlag.MANDATORY in rat.flag_rules.must
    current = built.resolve("TS29.061", "3GPP-RAT-Type")
    assert current is not None and ast.AvpFlag.MANDATORY in current.flag_rules.must_not
    charging = built.resolve("TS29.210", "Charging-Information")
    assert charging is not None
    assert charging.across_releases == corpus.CrossRelease(
        "TS29.210", "TS29.229", "18.1.0", corpus.STAND_IN, meant="6.11.0"
    )
    item = built.resolve("TS29.234", "SIP-Auth-Data-Item")
    assert isinstance(item, model.Grouped)
    assert ast.AvpFlag.MANDATORY in item.flag_rules.must
    assert item.defined_in == "TS29.234"
    assert "SIP-Digest-Authenticate" not in {m.name for m in item.members}
    assert item.across_releases == corpus.CrossRelease(
        "TS29.234", "TS29.229", "18.1.0", corpus.STAND_IN, meant="11.5.0"
    )


def test_ts_32_299s_m2m_information_resolves_to_onem2m_ts_0004():
    """TS 32.299 table 7.5.1 tabulates M2M-Information from oneM2M TS-0004
    ([301]), which the corpus extracts from oneM2M's Word file: vendor
    45687 per clause A.4, every member resolving, oneM2M's own in 45687
    and the rest in the space table A.4-1 gives each."""
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]))

    avp = built.resolve("TS32.299", "M2M-Information")

    assert isinstance(avp, model.Grouped)
    assert (avp.identity, avp.defined_in, avp.section) == (
        (45687, 1011),
        "oneM2M-TS-0004",
        "A.5.14",
    )
    members = {m.rule.name: m.avp.identity for m in avp.members if m.avp is not None}
    assert len(members) == 24
    assert members["Rating-Group"] == (0, 432)
    assert members["Node-Id"] == (10415, 2064)
    assert {identity[0] for identity in members.values()} == {0, 10415, 45687}
    # Its own reading is complete, and so is what it reaches in TS 32.299
    # V11.20.0 through Service-Information, but for TS 29.061's
    # 3GPP-Session-Stop-Indicator, which TS 29.061's reading reports.
    assert built.holes("oneM2M-TS-0004") == ()


def test_onem2m_reaches_release_11s_bodies_through_ts_32_299_v11_20_0():
    """oneM2M TS-0004's Service-Information is TS 32.299 V11.20.0's, whose
    non-specific references mean Release 11's last versions: the pinned TS
    29.212 V11.19.0's QoS-Information, nine members and the wildcard where
    Release 18's has sixteen, and TS 29.214 V11.16.0's Flows, closed where
    Release 18's adds three members, `*[ AVP ]` among them. TS 29.229's
    Server-Capabilities is V18.1.0's, standing in for V11.5.0, which defines
    it alike; IM-Information takes OMA's flags as Release 18's does. Flows
    sits in PS-Information's Service-Data-Container's
    AF-Correlation-Information."""
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]))

    def member(avp, name):
        assert isinstance(avp, model.Grouped)
        (found,) = [m.avp for m in avp.members if m.name == name]
        assert found is not None, name
        return found

    service = built.resolve("oneM2M-TS-0004", "Service-Information")
    qos = member(member(service, "PS-Information"), "QoS-Information")
    current = built.resolve("TS29.212", "QoS-Information")
    assert isinstance(qos, model.Grouped) and isinstance(current, model.Grouped)
    assert qos.identity == current.identity == (10415, 1016)
    assert (len(qos.members), len(current.members)) == (10, 17)
    assert qos.across_releases is None
    container = member(member(service, "PS-Information"), "Service-Data-Container")
    flows = member(member(container, "AF-Correlation-Information"), "Flows")
    assert isinstance(flows, model.Grouped)
    assert [m.name for m in flows.members] == [
        "Media-Component-Number",
        "Flow-Number",
        "Final-Unit-Action",
    ]
    capabilities = member(member(service, "IMS-Information"), "Server-Capabilities")
    assert capabilities.across_releases == corpus.CrossRelease(
        "TS32.299", "TS29.229", "18.1.0", corpus.STAND_IN, meant="11.5.0"
    )
    im = member(service, "IM-Information")
    assert (im.identity, im.data_type) == ((10415, 2110), ast.DataType.GROUPED)
    assert im.flag_rules == model.FlagRules(
        must=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}),
        may=frozenset({ast.AvpFlag.PROTECTED}),
    )


def test_only_three_cited_enumerations_stay_without_values():
    """Every `; Values:` citation in the committed corpus has its values
    supplied but three, which no flat list from the cited source can fill:
    TS 32.422 numbers each RAT's report intervals from 0, the ICMP registry
    numbers codes per type, and TS 23.682 numbers no network element."""
    unfilled = {
        (entry.reference, entry.spec.version, section.name, section.values_source)
        for entry in corpus.Corpus.load([_CORPUS_DIR])
        for section in entry.spec.sections
        if isinstance(section, ast.EnumeratedAvp)
        and section.values_source is not None
        and not section.values
    }
    assert unfilled == {
        ("TS29.272", "18.7.0", "Report-Interval", "TS 32.422 [23] for Report Interval"),
        (
            "RFC5777",
            None,
            "ICMP-Code",
            "IANA under the ICMP Type Numbers registry as defined in [RFC2780]",
        ),
        ("TS32.299", "18.0.0", "API-Network-Service-Node", "TS 23.682[243]"),
    }


def _committed() -> corpus.Corpus:
    return corpus.Corpus.load([_CORPUS_DIR])


# The field holes of the record: the ones no undefined policy answers for.
_FIELD_HOLES = {
    ("3GPP2-X.S0013-014", "Charging-Information"),
    ("ETSI-TS183.066", "CNGCF-Address"),
    ("ETSI-TS183.066", "Privacy-Indicator"),
    ("ETSI-TS183.066", "SIP-Outbound-Proxy"),
    ("RFC6736", "Egress-VLANID"),
    ("TS29.061", "3GPP-Session-Stop-Indicator"),
    ("TS29.061 V6.15.0", "3GPP-GPRS-Negotiated-QoS-Profile"),
    ("TS29.061 V6.15.0", "3GPP-SGSN-MCC-MNC"),
    ("TS29.229", "Wildcarded-IMPU"),
    ("TS29.234", "Charging-Characteristics"),
}


def test_the_committed_corpus_builds_against_its_record():
    books = _committed()
    built = model.Model.build(books)

    assert books.record is not None and books.record.path == _CORPUS_DIR / "holes.toml"
    known = {(each.document, each.name): each for each in books.record.holes}
    assert {(hole.document, hole.name): hole for hole in built.holes()}.keys() == (
        known.keys()
    )
    for hole in built.holes():
        entry = known[(hole.document, hole.name)]
        assert hole.missing == entry.missing
        assert hole.recorded == entry.reason
    assert built.unrecorded_holes() == built.stale_record_entries() == ()
    # A recorded hole stays one, and a member reached carries the reason too.
    assert built.resolve("TS29.234", "Charging-Characteristics") is None
    hole = built.hole("TS29.234", "Charging-Characteristics")
    assert hole is not None and hole.recorded is not None
    assert '"Integer"' in hole.recorded
    (member,) = [
        member
        for avp in built.avps("TS29.234")
        if avp.name == "Charging-Data" and isinstance(avp, model.Grouped)
        for member in avp.members
        if member.name == "Charging-Characteristics"
    ]
    assert member.avp is None and member.hole == hole


def test_a_strict_build_refuses_exactly_the_recorded_holes():
    books = _committed()
    assert books.record is not None

    with pytest.raises(model.IncompleteCorpusError) as raised:
        model.Model.build(books, strict=True)

    assert {(hole.document, hole.name) for hole in raised.value.holes} == {
        (each.document, each.name) for each in books.record.holes
    }
    assert "undefined=... answers for the undefined names" in str(raised.value)


@pytest.mark.parametrize(
    "policy",
    [model.UndefinedPolicy.DROP, model.UndefinedPolicy.PLACEHOLDER],
    ids=str,
)
def test_an_answer_for_the_undefined_names_leaves_the_field_holes(policy):
    """With the eleven undefined names answered for, `strict=True` still refuses
    what states no type, under every policy, and the default build takes the
    nine entries' going unused as no staleness."""
    books = _committed()

    with pytest.raises(model.IncompleteCorpusError) as raised:
        model.Model.build(books, strict=True, undefined=policy)
    assert {(hole.document, hole.name) for hole in raised.value.holes} == (_FIELD_HOLES)

    built = model.Model.build(books, undefined=policy)
    assert {(hole.document, hole.name) for hole in built.holes()} == _FIELD_HOLES


def test_a_supply_answering_part_of_the_record_builds_by_default():
    """A name `SUPPLY` answers is no hole and its entry goes unused; a name it
    says nothing of stays a recorded hole."""
    alias = model.Alias("TS29.336", "External-Identifier", "test")
    built = model.Model.build(
        _committed(),
        undefined=model.UndefinedPolicy.SUPPLY,
        supply={("TS29.154", "External-Group-Identifier"): alias},
    )

    assert built.hole("TS29.154", "External-Group-Identifier") is None
    assert built.resolve("TS29.154", "External-Group-Identifier") is not None
    hole = built.hole("RFC4004", "MIP-HA-to-MN-SPI")
    assert hole is not None and hole.recorded is not None


def _recorded_corpus(*holes: corpus.KnownHole) -> corpus.Corpus:
    """A document with one hole with a code (`Thing`), one undefined name
    (`Missing-Opt`) and otherwise complete, and a record of `holes`."""
    spec = _spec(
        "3GPP TS 29.900",
        [
            _message("Test-Request", "Thing", "Missing-Opt"),
            _flagless_table(
                ast.AvpTableRow(name="Thing", code=1, data_type=ast.DataType.TIME)
            ),
            ast.UndefinedAvp(name="Missing-Opt", source=ast.SourceRef(section="6.1.1")),
        ],
    )
    return corpus.Corpus([_entry(spec)], corpus.HoleRecord(Path("holes.toml"), holes))


_THING = corpus.KnownHole("TS29.900", "Thing", ("flag_rules",), "clause 6.3.1 says so")
_MISSING = corpus.KnownHole(
    "TS29.900", "Missing-Opt", ("undefined",), "no clause defines it"
)


class TestTheRecord:
    def test_a_recorded_hole_builds_and_carries_its_reason(self):
        built = model.Model.build(_recorded_corpus(_THING, _MISSING))

        hole = built.hole("TS29.900", "Thing")
        assert hole is not None and hole.recorded == "clause 6.3.1 says so"
        assert built.resolve("TS29.900", "Thing") is None

    def test_an_unrecorded_hole_fails_naming_only_it(self):
        books = _recorded_corpus(_MISSING)

        with pytest.raises(model.IncompleteCorpusError) as raised:
            model.Model.build(books)

        assert [hole.name for hole in raised.value.holes] == ["Thing"]
        assert str(raised.value) == (
            "the corpus has 1 hole its record does not list"
            " (Model.build(..., strict=False) builds the rest):"
            "\n  TS29.900 Thing: no flag_rules"
        )

    def test_an_entry_naming_other_missing_fields_lists_no_such_hole(self):
        wrong = corpus.KnownHole("TS29.900", "Thing", ("data_type",), "wrong")

        with pytest.raises(model.IncompleteCorpusError) as raised:
            model.Model.build(_recorded_corpus(wrong, _MISSING))

        assert [hole.name for hole in raised.value.holes] == ["Thing"]
        assert raised.value.holes[0].recorded is None

    @pytest.mark.parametrize(
        "entry",
        [
            corpus.KnownHole("TS29.900", "Worked-Off", ("definition",), "gone"),
            corpus.KnownHole("TS29.999", "Thing", ("flag_rules",), "document gone"),
            corpus.KnownHole("TS29.900 V1.0.0", "Thing", ("flag_rules",), "old copy"),
        ],
        ids=["name", "document", "version"],
    )
    def test_a_stale_entry_fails_naming_it(self, entry):
        books = _recorded_corpus(_THING, _MISSING, entry)

        with pytest.raises(model.StaleHoleRecordError) as raised:
            model.Model.build(books)

        assert raised.value.entries == (entry,)
        assert f"{entry.document} {entry.name}" in str(raised.value)

    def test_an_unrecorded_hole_is_reported_before_a_stale_entry(self):
        stale = corpus.KnownHole("TS29.900", "Worked-Off", ("definition",), "gone")

        with pytest.raises(model.IncompleteCorpusError):
            model.Model.build(_recorded_corpus(_MISSING, stale))

    @pytest.mark.parametrize(
        "policy",
        [model.UndefinedPolicy.DROP, model.UndefinedPolicy.PLACEHOLDER],
        ids=str,
    )
    def test_an_entry_the_policy_answered_is_not_stale(self, policy):
        built = model.Model.build(_recorded_corpus(_THING, _MISSING), undefined=policy)

        assert built.hole("TS29.900", "Missing-Opt") is None
        assert built.stale_record_entries() == ()

    def test_a_policy_excuses_only_a_name_a_block_declares(self):
        """`Worked-Off` is defined nowhere and declared by no block, so no
        policy explains its entry going unused; nor does one explain an entry
        for `Thing` under a document that does not hold it."""
        stale = corpus.KnownHole("TS29.900", "Worked-Off", ("undefined",), "gone")

        with pytest.raises(model.StaleHoleRecordError) as raised:
            model.Model.build(
                _recorded_corpus(_THING, _MISSING, stale),
                undefined=model.UndefinedPolicy.DROP,
            )

        assert raised.value.entries == (stale,)

    def test_a_supply_answering_nothing_excuses_no_entry(self):
        """An older copy's block no reading reaches is no hole of the corpus's,
        so its entry is stale, and an empty supply answered nothing for it."""
        older = _spec(
            "3GPP TS 29.900",
            [ast.UndefinedAvp(name="Gone", source=ast.SourceRef(section="6.1.1"))],
            version="17.0.0",
        )
        newer = _spec("3GPP TS 29.900", [_table(_row("Known", 1))])
        entry = corpus.KnownHole("TS29.900 V17.0.0", "Gone", ("undefined",), "old")
        books = corpus.Corpus(
            [
                corpus.Entry(Path("older.dad"), older),
                corpus.Entry(Path("newer.dad"), newer),
            ],
            corpus.HoleRecord(Path("holes.toml"), (entry,)),
        )

        for policy, supply in (
            (model.UndefinedPolicy.HOLE, None),
            (model.UndefinedPolicy.DROP, None),
            (model.UndefinedPolicy.SUPPLY, {}),
        ):
            with pytest.raises(model.StaleHoleRecordError):
                model.Model.build(books, undefined=policy, supply=supply)

    def test_an_answered_entry_must_still_list_the_hole_as_it_is(self):
        wrong = corpus.KnownHole("TS29.900", "Missing-Opt", ("definition",), "wrong")

        with pytest.raises(model.StaleHoleRecordError) as raised:
            model.Model.build(
                _recorded_corpus(_THING, wrong), undefined=model.UndefinedPolicy.DROP
            )

        assert raised.value.entries == (wrong,)

    def test_a_name_defined_upstream_goes_stale_under_every_policy(self):
        """The block stands, but a definition wins over it, so the entry is
        stale and no policy answered for anything."""
        spec = _spec(
            "3GPP TS 29.900",
            [
                _table(_row("Known", 1)),
                ast.UndefinedAvp(name="Known", source=ast.SourceRef(section="6.1.1")),
            ],
        )
        entry = corpus.KnownHole("TS29.900", "Known", ("undefined",), "was undefined")
        books = corpus.Corpus(
            [_entry(spec)], corpus.HoleRecord(Path("holes.toml"), (entry,))
        )

        for policy in (model.UndefinedPolicy.HOLE, model.UndefinedPolicy.DROP):
            with pytest.raises(model.StaleHoleRecordError):
                model.Model.build(books, undefined=policy)

    def test_strict_true_refuses_a_recorded_hole(self):
        with pytest.raises(model.IncompleteCorpusError) as raised:
            model.Model.build(_recorded_corpus(_THING, _MISSING), strict=True)
        assert {hole.name for hole in raised.value.holes} == {"Thing", "Missing-Opt"}

    def test_strict_false_holds_the_corpus_to_nothing(self):
        stale = corpus.KnownHole("TS29.900", "Worked-Off", ("definition",), "gone")

        built = model.Model.build(_recorded_corpus(stale), strict=False)

        assert built.stale_record_entries() == (stale,)
        assert {hole.name for hole in built.unrecorded_holes()} == {
            "Thing",
            "Missing-Opt",
        }

    def test_a_corpus_with_no_record_has_no_known_holes(self):
        spec = _spec(
            "3GPP TS 29.900",
            [
                _message("Test-Request", "Nowhere"),
            ],
        )
        with pytest.raises(model.IncompleteCorpusError, match="its record does not"):
            model.Model.build(corpus.Corpus([_entry(spec)]))


def test_the_committed_corpus_declares_its_eleven_undefined_names():
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]))
    declared = {
        (each.reference, each.name, each.section, each.cited_in)
        for each in built.undefined()
    }
    assert declared == {
        ("RFC4004", "MIP-HA-to-MN-SPI", "9.4", ("9.4",)),
        ("RFC4004", "MIP-MN-to-FA-SPI", "9.5", ("9.5",)),
        ("RFC4004", "MIP-MN-to-HA-SPI", "9.6", ("9.6",)),
        ("RFC5866", "Authorization-Session-Volume", "5.3", ("5.3", "5.5")),
        (
            "TS29.061",
            "Delegated-IPv6-Prefix",
            "16a.4.1",
            ("16a.4.1", "16a.4.2", "16a.4.3"),
        ),
        ("TS29.154", "External-Group-Identifier", "A.6.6.2", ("A.6.6.2",)),
        ("TS29.234", "Error-Cause", "4.4.2.1", ("4.4.2.1", "5.5.1")),
        ("TS29.345", "ProSe-Query-Code", "6.3.53", ("6.3.53", "6.3.54")),
        ("TS29.345", "ProSe-Response-Code", "6.3.53", ("6.3.53", "6.3.54")),
        ("TS32.299", "Network-Element", "7.2.66aA", ("7.2.66aA",)),
        ("TS32.299", "Submission-Timestamp", "7.2.112aA", ("7.2.112aA",)),
    }


def test_ts_29_154s_group_identifier_reads_as_ts_29_336s_by_alias():
    books = corpus.Corpus.load([_CORPUS_DIR])
    alias = model.Alias("TS29.336", "External-Identifier", "test")
    built = model.Model.build(
        books,
        undefined=model.UndefinedPolicy.SUPPLY,
        supply={("TS29.154", "External-Group-Identifier"): alias},
    )

    (ecr,) = [m for m in built.messages("TS29.154") if m.abbreviation == "ECR"]
    (member,) = [m for m in ecr.avps if m.name == "External-Group-Identifier"]
    assert member.avp == built.resolve("TS29.336", "External-Identifier")
    assert member.avp is not None and member.avp.identity == (10415, 3111)
    assert member.alias == alias


@pytest.mark.sources
def test_the_pinned_dictionary_names_the_avps_it_spells_differently():
    """Wireshark's deliberate disambiguations and its own defects both
    arrive as `wireshark_name`, beside the specifications' spelling."""
    named = model.Model.build(
        corpus.Corpus.load([_CORPUS_DIR]),
        dictionary=_ROOT / "specifications" / "wireshark",
    )
    for reference, name, wireshark_name in [
        ("TS29.229", "User-Data", "Cx-User-Data"),
        ("TS29.329", "User-Data", "Sh-User-Data"),
        ("TS29.272", "Call-Barring-Info", "Call-Barring-Infor-List"),
        ("RFC6733", "Session-Id", "Session-Id"),
    ]:
        avp = named.resolve(reference, name)
        assert avp is not None
        assert (avp.name, avp.wireshark_name) == (name, wireshark_name)
    hole = named.hole("TS29.061", "3GPP-Session-Stop-Indicator")
    assert hole is not None
    assert hole.wireshark_name == "3GPP-Session-Stop-Indicator"


# --- undefined names ---------------------------------------------------------

_REQUIRED = ast.Presence.REQUIRED
_MV = ast.AvpFlagRules(must=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}))


def _declared(name, section, note=None):
    return ast.UndefinedAvp(
        name=name, source=ast.SourceRef(section=section, page=9), note=note
    )


def _undefined_corpus(*, defects=True) -> corpus.Corpus:
    """RFC 4004 clause 9.4's shape and TS 29.345 clause 6.3.53's in one
    document: a grouped AVP with a required and an optional member nothing
    defines, both declared, the optional one in a command too; and a second
    document re-using both. With `defects`, also a name resolving nowhere
    and a row stating no type, which no policy touches."""
    holder = ast.GroupedAvp(
        name="Holder",
        source=ast.SourceRef(section="6.3.1"),
        code=700,
        vendor_id=10415,
        avps=(_rule("Known"), _rule("Missing-Req", _REQUIRED), _rule("Missing-Opt")),
    )
    defective = ("Nowhere", "Stop") if defects else ()
    own = _spec(
        "3GPP TS 29.900",
        [
            _message("Test-Request", "Missing-Opt", "Holder", *defective),
            holder,
            _table(
                _row("Holder", 700, ast.DataType.GROUPED),
                _row("Known", 701),
                *([ast.AvpTableRow(name="Stop", code=702)] if defects else []),
            ),
            _declared("Missing-Opt", "6.1.1", '"the request may carry it"'),
            _declared("Missing-Req", "6.3.1"),
        ],
    )
    citing = _spec(
        "3GPP TS 29.901",
        [
            _message("Other-Request", "Holder", "Missing-Opt"),
            ast.ReusedAvps(
                table="1",
                source=ast.SourceRef(section="6.3.0"),
                rows=(
                    ast.ReusedAvpRow(name="Holder", origin="TS29.900"),
                    ast.ReusedAvpRow(name="Missing-Opt", origin="TS29.900"),
                ),
            ),
        ],
    )
    return corpus.Corpus(_entry(spec) for spec in (own, citing))


def _build(policy=model.UndefinedPolicy.HOLE, supply=None, *, defects=True, **kw):
    kw.setdefault("strict", False)
    return model.Model.build(
        _undefined_corpus(defects=defects), undefined=policy, supply=supply, **kw
    )


def _holder(built: model.Model) -> model.Grouped:
    holder = built.resolve("TS29.900", "Holder")
    assert isinstance(holder, model.Grouped)
    return holder


def _test_request(built: model.Model) -> model.Message:
    (message,) = built.messages("TS29.900")
    return message


_TEXT = ast.AvpFlagRules(must=frozenset({ast.AvpFlag.MANDATORY}))


def _supplied(code=710, data_type=ast.DataType.UTF8_STRING, vendor_id=10415, **kw):
    return model.Supplied(
        vendor_id=vendor_id,
        code=code,
        data_type=data_type,
        flag_rules=_MV if vendor_id else _TEXT,
        source="ACME dictionary",
        **kw,
    )


class TestUndefinedNames:
    def test_by_default_a_declared_name_is_an_undefined_hole(self):
        built = _build()

        assert built.undefined_policy is model.UndefinedPolicy.HOLE
        assert built.resolve("TS29.900", "Missing-Opt") is None
        hole = built.hole("TS29.900", "Missing-Opt")
        assert hole is not None
        assert hole.missing == (model.UNDEFINED,)
        assert hole.undefined == model.Undefined(
            reference="TS29.900",
            name="Missing-Opt",
            section="6.1.1",
            page=9,
            note='"the request may carry it"',
            cited_in=("6.1.1", "6.3.1"),
        )
        assert str(hole) == "TS29.900 Missing-Opt: undefined (clause 6.1.1)"
        assert hole in built.holes("TS29.900")
        member = _holder(built).members[1]
        assert member.hole is not None and member.hole.missing == (model.UNDEFINED,)
        with pytest.raises(model.IncompleteCorpusError, match="undefined="):
            _build(defects=False, strict=True)

    def test_a_name_reached_through_an_origin_names_the_origins_block(self):
        built = _build()

        (message,) = built.messages("TS29.901")
        hole = message.avps[1].hole
        assert hole is not None
        assert (hole.reference, hole.missing) == ("TS29.900", (model.UNDEFINED,))
        assert built.hole("TS29.901", "Missing-Opt") == hole

    def test_drop_takes_the_members_out_and_keeps_them_beside(self):
        built = _build(model.UndefinedPolicy.DROP)

        holder = _holder(built)
        assert [member.name for member in holder.members] == ["Known"]
        assert [member.name for member in holder.dropped] == [
            "Missing-Req",
            "Missing-Opt",
        ]
        required = holder.dropped[0]
        assert required.min_occurs == 1
        assert required.hole is not None and required.hole.undefined is not None
        message = _test_request(built)
        assert [member.name for member in message.avps] == ["Holder", "Nowhere", "Stop"]
        assert [member.name for member in message.dropped] == ["Missing-Opt"]
        assert built.hole("TS29.900", "Missing-Opt") is None
        assert built.resolve("TS29.900", "Missing-Opt") is None
        assert [each.name for each in built.undefined("TS29.900")] == [
            "Missing-Opt",
            "Missing-Req",
        ]
        assert built.placeholders() == ()
        _build(model.UndefinedPolicy.DROP, defects=False, strict=True)

    def test_placeholder_keeps_the_members_in_place_untyped(self):
        built = _build(model.UndefinedPolicy.PLACEHOLDER)

        member = _holder(built).members[1]
        assert member.name == "Missing-Req"
        assert (member.avp, member.hole) == (None, None)
        assert member.placeholder is not None
        assert member.placeholder.undefined.section == "6.3.1"
        assert [each.name for each in built.placeholders("TS29.900")] == [
            "Missing-Opt",
            "Missing-Req",
        ]
        assert built.hole("TS29.900", "Missing-Req") is None
        assert not any(hole.undefined for hole in built.holes())
        _build(model.UndefinedPolicy.PLACEHOLDER, defects=False, strict=True)

    @pytest.mark.parametrize("policy", list(model.UndefinedPolicy), ids=str)
    def test_no_policy_touches_a_name_without_a_block_or_a_field_hole(self, policy):
        """TS 29.061's `3GPP-Session-Stop-Indicator`, a row stating only a
        code, stays a hole whatever the consumer answers for the declared
        names, and so does a name resolving nowhere without a block."""
        supply = {} if policy is model.UndefinedPolicy.SUPPLY else None
        built = _build(policy, supply)

        nowhere = built.hole("TS29.900", "Nowhere")
        stop = built.hole("TS29.900", "Stop")
        assert nowhere is not None and nowhere.missing == (model.DEFINITION,)
        assert stop is not None and stop.missing == ("data_type", "flag_rules")
        names = [member.name for member in _test_request(built).avps]
        assert names[-2:] == ["Nowhere", "Stop"]
        with pytest.raises(model.IncompleteCorpusError):
            _build(policy, supply, strict=True)

    def test_supply_reads_the_consumers_definition_in_the_declaring_document(self):
        built = _build(
            model.UndefinedPolicy.SUPPLY,
            {"Missing-Opt": _supplied(), "Missing-Req": _supplied(711)},
            defects=False,
            strict=True,
        )

        avp = built.resolve("TS29.900", "Missing-Opt")
        assert avp == model.Avp(
            name="Missing-Opt",
            vendor_id=10415,
            code=710,
            data_type=ast.DataType.UTF8_STRING,
            flag_rules=model.FlagRules.printed(_MV),
            defined_in="TS29.900",
            section="6.1.1",
            wireshark_name=None,
            supplied="ACME dictionary",
        )
        assert avp in built.avps("TS29.900")
        assert _holder(built).members[2].avp == avp
        (message,) = built.messages("TS29.901")
        assert message.avps[1].avp == avp
        assert built.hole("TS29.900", "Missing-Opt") is None

    def test_a_supplied_ietf_avp_takes_rfc_6733s_rules(self):
        built = _build(
            model.UndefinedPolicy.SUPPLY, {"Missing-Opt": _supplied(vendor_id=0)}
        )

        avp = built.resolve("TS29.900", "Missing-Opt")
        assert avp is not None
        assert avp.flag_rules == model.FlagRules(
            must=frozenset({ast.AvpFlag.MANDATORY}),
            must_not=frozenset({ast.AvpFlag.VENDOR}),
        )

    def test_a_supplied_grouped_reads_its_members_by_the_policy(self):
        grouped = _supplied(
            711,
            ast.DataType.GROUPED,
            members=(_rule("Known"), _rule("Missing-Opt")),
        )
        built = _build(model.UndefinedPolicy.SUPPLY, {"Missing-Req": grouped})

        avp = built.resolve("TS29.900", "Missing-Req")
        assert isinstance(avp, model.Grouped) and avp.supplied == "ACME dictionary"
        known, missing = avp.members
        assert known.avp == built.resolve("TS29.900", "Known")
        # Supplied nothing for, the nested name stays a hole.
        assert missing.hole is not None and missing.hole.undefined is not None
        assert built.hole("TS29.900", "Missing-Opt") is not None
        with pytest.raises(model.IncompleteCorpusError, match="Missing-Opt"):
            _build(
                model.UndefinedPolicy.SUPPLY,
                {"Missing-Req": grouped},
                defects=False,
                strict=True,
            )

    def test_a_supplied_enumeration_carries_its_values(self):
        values = (ast.EnumValue(name="On", value=1),)
        built = _build(
            model.UndefinedPolicy.SUPPLY,
            {
                "Missing-Opt": _supplied(
                    data_type=ast.DataType.ENUMERATED, values=values
                )
            },
        )

        avp = built.resolve("TS29.900", "Missing-Opt")
        assert isinstance(avp, model.Enumerated) and avp.values == values

    def test_an_alias_reads_the_member_as_an_avp_the_corpus_defines(self):
        alias = model.Alias("TS29.900", "Known", "the editors meant Known")
        built = _build(model.UndefinedPolicy.SUPPLY, {"Missing-Opt": alias})

        member = _holder(built).members[2]
        assert member.rule.name == "Missing-Opt"
        assert member.avp == built.resolve("TS29.900", "Known")
        assert member.alias == alias
        assert _holder(built).members[0].alias is None
        assert built.resolve("TS29.900", "Missing-Opt") == member.avp

    def test_a_document_key_wins_over_a_name_key(self):
        built = _build(
            model.UndefinedPolicy.SUPPLY,
            {"Missing-Opt": _supplied(), ("TS29.900", "Missing-Opt"): _supplied(712)},
        )

        avp = built.resolve("TS29.900", "Missing-Opt")
        assert avp is not None and avp.code == 712

    @pytest.mark.parametrize(
        ("policy", "supply", "message"),
        [
            (model.UndefinedPolicy.SUPPLY, None, "needs supply="),
            (model.UndefinedPolicy.DROP, {}, "read only with undefined=SUPPLY"),
            (
                model.UndefinedPolicy.SUPPLY,
                {"Missing-Optional": _supplied()},
                "no Undefined AVP block declares",
            ),
            (
                model.UndefinedPolicy.SUPPLY,
                {("TS29.901", "Missing-Opt"): _supplied()},
                "no Undefined AVP block declares",
            ),
            (
                model.UndefinedPolicy.SUPPLY,
                {"Missing-Opt": _supplied(701)},
                r"claims \(vendor 10415, code 701\), which is TS29.900's Known",
            ),
            (
                model.UndefinedPolicy.SUPPLY,
                {"Missing-Opt": model.Alias("TS29.900", "Nowhere", "t")},
                "does not complete",
            ),
            (
                model.UndefinedPolicy.SUPPLY,
                {"Missing-Opt": _supplied(members=(_rule("Known"),))},
                "no Grouped",
            ),
        ],
        ids=[
            "supply-without-a-mapping",
            "a-mapping-without-supply",
            "unknown-name",
            "unknown-document",
            "identity-collision",
            "alias-to-a-hole",
            "members-on-a-leaf",
        ],
    )
    def test_a_build_refuses_a_supply_that_does_not_fit(self, policy, supply, message):
        with pytest.raises(model.ModelError, match=message):
            _build(policy, supply)

    def test_a_build_refuses_two_supplied_names_on_one_identity(self):
        supply = {"Missing-Opt": _supplied(), "Missing-Req": _supplied()}

        with pytest.raises(
            model.ModelError,
            match=(
                r"TS29.900 Missing-Opt and for TS29.900 Missing-Req both claim"
                r" \(vendor 10415, code 710\)"
            ),
        ):
            _build(model.UndefinedPolicy.SUPPLY, supply, defects=False, strict=True)

    def test_a_shadowed_name_key_claims_no_identity(self):
        """A name key every document key overrides supplies nothing, so it
        collides with nothing either."""
        supply = {
            "Missing-Opt": _supplied(711),
            ("TS29.900", "Missing-Opt"): _supplied(710),
            "Missing-Req": _supplied(711),
        }

        built = _build(model.UndefinedPolicy.SUPPLY, supply, defects=False)

        assert [avp.name for avp in built.identified(10415, 711)] == ["Missing-Req"]

    def test_a_cycle_of_aliases_is_refused(self):
        supply = {
            "Missing-Opt": model.Alias("TS29.900", "Missing-Req", "t"),
            "Missing-Req": model.Alias("TS29.900", "Missing-Opt", "t"),
        }

        with pytest.raises(
            model.ModelError,
            match=(
                r"supply aliases form a cycle: TS29\.900 Missing-Req -> TS29\.900"
                r" Missing-Opt -> TS29\.900 Missing-Req"
            ),
        ):
            _build(model.UndefinedPolicy.SUPPLY, supply)

    def test_a_supplied_name_reached_across_releases_says_so(self):
        """A name TS 29.140 V7.0.0 declares undefined, re-used by TS 32.299
        V18.1.0, which reads TS 29.140 non-specifically as its final
        version: supplied, it still says by which citation it was reached."""
        origin = _spec(
            "3GPP TS 29.140", [_declared("Missing-Opt", "6.1.1")], version="7.0.0"
        )
        citing = _spec("3GPP TS 32.299", [_reused("Missing-Opt", "TS29.140")])
        books = corpus.Corpus(_entry(spec) for spec in (origin, citing))
        across = corpus.CrossRelease(
            "TS32.299", "TS29.140", "7.0.0", corpus.NON_SPECIFIC
        )
        hole = model.Model.build(books, strict=False).hole("TS32.299", "Missing-Opt")
        assert hole is not None and hole.across_releases == across

        built = model.Model.build(
            books,
            undefined=model.UndefinedPolicy.SUPPLY,
            supply={"Missing-Opt": _supplied()},
        )

        avp = built.resolve("TS32.299", "Missing-Opt")
        assert avp is not None and avp.supplied == "ACME dictionary"
        assert (avp.defined_in, avp.across_releases) == ("TS29.140", across)
        assert built.across_releases("TS32.299") == (avp,)
        origins = built.resolve("TS29.140", "Missing-Opt")
        assert origins is not None and origins.across_releases is None


_SIDECAR = """\
; Specification: ACME HSS dictionary
; Vendor-ID: 10415


; Type: AVP Table
; Section: 1
; Columns: Name         Code  Type        Must  May  S.not  M.not
           Missing-Req  711   Grouped     M,V   -    -      -
           Missing-Opt  710   UTF8String  M     -    -      V


; Type: Grouped AVP
; Name: Missing-Req
; Section: 2
Missing-Req ::= < AVP header: 711 10415 >
        { Known }
"""


class TestSuppliedFrom:
    def test_a_sidecar_supplies_definitions_and_rows(self, tmp_path):
        (tmp_path / "acme.dad").write_text(_SIDECAR)

        supplied = model.supplied_from(tmp_path / "acme.dad")

        source = "ACME HSS dictionary (acme.dad)"
        assert supplied["Missing-Req"] == model.Supplied(
            vendor_id=10415,
            code=711,
            data_type=ast.DataType.GROUPED,
            flag_rules=_MV,
            source=source,
            members=(_rule("Known", _REQUIRED),),
        )
        opt = supplied["Missing-Opt"]
        assert (opt.vendor_id, opt.code, opt.source) == (0, 710, source)
        built = _build(model.UndefinedPolicy.SUPPLY, supplied, defects=False)
        avp = built.resolve("TS29.900", "Missing-Req")
        assert isinstance(avp, model.Grouped) and avp.members[0].avp is not None

    def test_an_incomplete_sidecar_is_refused(self, tmp_path):
        # Missing-Req's row places no flag.
        (tmp_path / "bare.dad").write_text(_SIDECAR.replace("M,V   -", "-     -"))

        with pytest.raises(model.ModelError, match="Missing-Req states no flag rules"):
            model.supplied_from(tmp_path / "bare.dad")

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            (
                "Missing-Req  999   Grouped     M,V   -    -      -",
                "row gives code 999, definition 711",
            ),
            (
                "Missing-Req  711   OctetString M,V   -    -      -",
                "row gives type OctetString, definition Grouped",
            ),
            (
                "Missing-Req  711   Grouped     M     -    -      V",
                "row gives vendor 0, definition 10415",
            ),
        ],
    )
    def test_a_row_contradicting_its_definition_is_refused(
        self, tmp_path, row, message
    ):
        printed = "Missing-Req  711   Grouped     M,V   -    -      -"
        assert printed in _SIDECAR
        (tmp_path / "acme.dad").write_text(_SIDECAR.replace(printed, row))

        with pytest.raises(model.ModelError, match=f"Missing-Req: {message}"):
            model.supplied_from(tmp_path / "acme.dad")

    def test_every_contradiction_is_listed_together(self, tmp_path):
        printed = "Missing-Req  711   Grouped     M,V   -    -      -"
        row = "Missing-Req  999   OctetString M     -    -      V"
        (tmp_path / "acme.dad").write_text(_SIDECAR.replace(printed, row))

        with pytest.raises(model.ModelError) as raised:
            model.supplied_from(tmp_path / "acme.dad")

        assert str(raised.value).endswith(
            "Missing-Req: row gives code 999, definition 711;"
            " row gives type OctetString, definition Grouped;"
            " row gives vendor 0, definition 10415"
        )

    def test_a_vendor_cell_contradicting_definition_and_flag_is_refused(self, tmp_path):
        columns = "Name         Code  Type        Must  May  S.not  M.not"
        text = _SIDECAR.replace(columns, columns.replace("Code", "Vendor-ID  Code"))
        for row in ("Missing-Req  711", "Missing-Opt  710"):
            text = text.replace(row, row.replace(" 7", " 0          7"))
        (tmp_path / "acme.dad").write_text(text)

        with pytest.raises(model.ModelError) as raised:
            model.supplied_from(tmp_path / "acme.dad")

        assert str(raised.value).endswith(
            "Missing-Req: row gives vendor 0, definition 10415;"
            " row gives vendor 0 with V under Must"
        )

    def test_a_row_alone_contradicting_its_v_flag_is_refused(self, tmp_path):
        text = _SIDECAR.replace("; Vendor-ID: 10415", "; Vendor-ID: 0")
        definition = text.index("; Type: Grouped")
        (tmp_path / "acme.dad").write_text(text[:definition].rstrip() + "\n")

        with pytest.raises(
            model.ModelError, match="Missing-Req: row gives vendor 0 with V under Must"
        ):
            model.supplied_from(tmp_path / "acme.dad")

    def test_a_name_two_sidecars_supply_is_refused(self, tmp_path):
        (tmp_path / "one.dad").write_text(_SIDECAR)
        (tmp_path / "two.dad").write_text(_SIDECAR)

        with pytest.raises(model.ModelError, match="Missing-Req is supplied twice"):
            model.supplied_from(tmp_path / "one.dad", tmp_path / "two.dad")

    def test_a_name_one_sidecar_tables_twice_is_refused(self, tmp_path):
        last = "Missing-Opt  710   UTF8String  M     -    -      V\n"
        again = last.replace("710", "999")
        twice = _SIDECAR.replace(last, f"{last}           {again}")
        assert twice.count("Missing-Opt") == 2
        (tmp_path / "twice.dad").write_text(twice)

        with pytest.raises(model.ModelError, match="Missing-Opt is tabled twice"):
            model.supplied_from(tmp_path / "twice.dad")

    def test_a_name_one_sidecar_defines_twice_is_refused(self, tmp_path):
        definition = _SIDECAR[_SIDECAR.index("; Type: Grouped") :]
        (tmp_path / "twice.dad").write_text(f"{_SIDECAR}\n\n{definition}")

        with pytest.raises(model.ModelError, match="Missing-Req is defined twice"):
            model.supplied_from(tmp_path / "twice.dad")


def test_every_reading_has_one_flag_rules_type():
    """A consumer reads `application_defined` off any AVP or hole, so an M-bit
    check cannot silently differ by which document states the rules."""
    built = model.Model.build(corpus.Corpus.load(_CORPUS_DIR))

    avps = [avp for each in built.references() for avp in built.avps(each)]
    readings = [*avps, *built.holes()]

    assert all(
        isinstance(found.flag_rules, model.FlagRules)
        for found in readings
        if found.flag_rules is not None
    )
    assert any(avp.flag_rules.application_defined for avp in avps)


class TestWhatCommandsUse:
    def test_an_application_holds_what_its_commands_use_at_any_depth(self, built):
        """Cx's tables list 77 AVPs, its commands use 103: the base protocol's
        Destination-Host and Failed-AVP are in no table of TS 29.229's."""
        (cx,) = built.applications("TS29.229", application_id=16777216)

        members = cx.avps()
        identities = {member.avp.identity for member in members if member.avp}

        assert len(identities) == 103
        assert {"Destination-Host", "Auth-Session-State", "Failed-AVP"} <= {
            member.name for member in members
        }
        assert not {"Destination-Host", "Failed-AVP"} & {
            avp.name for avp in built.avps("TS29.229")
        }

    def test_a_walk_is_in_definition_order_and_holds_each_reading_once(self, built):
        (uar, *_) = built.messages("TS29.229")

        names = [member.name for member in uar.walk()]

        assert names[0] == "Session-Id"
        assert len(names) == len(set(names))
        # A grouped member comes right before its own members.
        place = names.index("Supported-Features")
        assert names[place + 1 : place + 3] == ["Feature-List-ID", "Feature-List"]

    def test_a_walk_keeps_the_wildcard_once_and_passes_over_a_cut(self):
        spec = _spec(
            "3GPP TS 29.900",
            [
                ast.GroupedAvp(
                    name="Loop",
                    source=ast.SourceRef(section="6.1"),
                    code=1,
                    vendor_id=10415,
                    avps=(_rule("Loop"), _rule("AVP"), _rule("Missing")),
                ),
                _table(_flagged("Loop", 1, ast.DataType.GROUPED, must=_V)),
                ast.Message(
                    name="Thing-Request",
                    abbreviation="THR",
                    source=ast.SourceRef(section="6.2"),
                    command_code=300,
                    flags=frozenset({ast.CommandFlag.REQUEST}),
                    application_id=7,
                    avps=(_rule("Loop"), _rule("AVP")),
                ),
            ],
        )
        (message,) = _model(spec).messages("TS29.900")

        walked = message.walk()

        assert [member.name for member in walked] == ["Loop", "AVP", "Missing"]
        assert walked[1].avp is None and walked[1].hole is None
        assert walked[2].hole is not None

    def test_a_hole_is_a_member_of_the_closure(self, built):
        holes = [
            member.hole
            for application in built.applications("TS29.234")
            for member in application.avps()
            if member.hole is not None
        ]

        assert "Charging-Characteristics" in {hole.name for hole in holes}


class TestCorpusWideQueries:
    def test_messages_cover_every_document(self, built):
        everything = built.messages()

        assert len(everything) == sum(
            len(built.messages(each)) for each in built.references()
        )
        assert {"TS29.229", "RFC6733"} <= {each.defined_in for each in everything}

    def test_applications_filter_by_id_across_documents(self, built):
        everything = built.applications()
        gx = built.applications(application_id=16777238)

        assert {each.reference for each in gx} >= {"TS29.212"}
        assert all(each.application_id == 16777238 for each in gx)
        assert set(gx) < set(everything)
        assert built.applications("TS29.229", application_id=1) == ()

    def test_avps_list_every_distinct_reading(self, built):
        everything = built.avps()

        assert len(everything) == len(set(everything))
        assert set(built.avps("TS29.229")) <= set(everything)
        assert built.find("Session-Id")[0] in everything
        order = [(each.defined_in, each.name) for each in everything]
        assert order == sorted(order)

    def test_a_version_names_one_document(self, built):
        with pytest.raises(model.ModelError, match="name it"):
            built.messages(version="1.0.0")
        with pytest.raises(model.ModelError, match="name it"):
            built.applications(version="1.0.0")


class TestEffectiveApplicationId:
    def test_a_bare_header_takes_its_application_scope(self, built):
        (ccr, *_) = (
            message
            for message in built.messages("TS29.212")
            if message.abbreviation == "CCR"
        )

        assert (ccr.application_id, ccr.header_application_id) == (16777238, None)
        assert ccr.is_request

    def test_a_printed_id_is_both(self, built):
        (uar, uaa, *_) = built.messages("TS29.229")

        assert uar.application_id == uar.header_application_id == 16777216
        assert uar.is_request and not uaa.is_request

    def test_a_message_and_its_application_agree(self, built):
        for application in built.applications():
            for message in application.messages:
                assert message.application_id == application.application_id


class TestReadingsOfOneAvp:
    def test_a_reading_names_the_table_that_produced_it(self, built):
        """oneM2M TS-0004's table adds P under May to RFC 6733's Session-Id."""
        readings = {
            ast.AvpFlag.PROTECTED in avp.flag_rules.may: avp
            for avp in built.find("Session-Id")
        }

        assert readings[False].read_through == "RFC6733"
        assert readings[True].read_through == "oneM2M-TS-0004"
        assert built.resolve("oneM2M-TS-0004", "Session-Id") == readings[True]
        assert built.resolve("TS29.229", "Session-Id") == readings[False]

    def test_a_table_agreeing_with_the_origin_produces_nothing_new(self, built):
        avp = built.resolve("TS29.229", "Session-Id")

        assert avp is not None and avp.read_through == avp.defined_in == "RFC6733"

    def test_an_older_copys_table_is_named_with_its_version(self, built):
        """Two copies of TS 29.061 read 3GPP-RAT-Type apart, so the reference
        alone would not tell the readings apart."""
        names = {avp.read_through for avp in built.find("3GPP-RAT-Type")}

        assert "TS29.061" in names
        assert any(name.startswith("TS29.061 V") for name in names)

    def test_every_reading_of_an_identity_says_where_it_came_from(self, built):
        for avp in built.avps():
            assert avp.read_through
        for identity, readings in built._by_identity.items():
            told = {
                (avp.defined_in, avp.read_through, avp.across_releases)
                for avp in readings
            }
            assert len(told) == len(readings), identity

    def test_a_member_read_through_a_citing_table_names_it(self, built):
        """TS 32.299's Supported-Features holds its own Feature-List."""
        avp = built.resolve("TS32.299", "Supported-Features")

        assert avp is not None and avp.defined_in == "TS29.229"
        assert avp.read_through == "TS32.299"

    def test_definition_is_the_defining_documents_reading(self, built):
        avp = built.definition("Session-Id")

        assert avp is not None
        assert (avp.defined_in, avp.read_through) == ("RFC6733", "RFC6733")
        assert ast.AvpFlag.PROTECTED not in avp.flag_rules.may
        assert built.definition((0, 263)) == avp

    @pytest.mark.parametrize(
        ("name", "document"),
        [
            # Extended from TS 29.212 by a local copy TS 29.272 also re-uses.
            ("Allocation-Retention-Priority", "TS29.212"),
            # TS 29.214 succeeds TS 29.209, and ETSI's copy cites them.
            ("Flows", "TS29.214"),
            # RFC 8506 obsoletes RFC 4006.
            ("CC-Request-Type", "RFC8506"),
            # TS 29.212 cites itself from its Gxx tables, which is no re-use.
            # By identity: 3GPP2 X.S0013-014 has one of that name in its space.
            ((10415, 1001), "TS29.212"),
        ],
    )
    def test_definition_picks_among_documents_redefining_a_name(
        self, built, name, document
    ):
        avp = built.definition(name)

        assert avp is not None and avp.defined_in == document

    def test_definition_of_nothing_is_none(self, built):
        assert built.definition("No-Such-AVP") is None
        assert built.definition((1, 1)) is None
        # A hole has no reading to give; `hole` says why.
        assert built.definition("Charging-Characteristics") is None
        assert built.hole("TS29.234", "Charging-Characteristics") is not None

    def test_definition_refuses_a_name_two_avps_claim(self, built):
        with pytest.raises(model.ModelError, match=r"\(10415, 864\), \(45687, 1008\)"):
            built.definition("Originator")

        avp = built.definition((45687, 1008))
        assert avp is not None and avp.name == "Originator"


class TestPrintingAndSerialising:
    def test_a_repr_says_what_it_is_in_a_line(self, built):
        message = next(
            each for each in built.messages("TS32.299") if each.abbreviation == "CCR"
        )
        (application, *_) = built.applications("TS29.229")
        everything = [
            message,
            application,
            *message.avps,
            *built.avps("TS32.299"),
            *built.holes(),
            *built.undefined(),
            *built.registry(ast.RegistryKind.APPLICATION_IDS),
            *built.marks("TS29.212", "AN-GW-Address"),
            model.Alias("TS29.336", "External-Identifier", "source"),
            model.Placeholder(built.undefined()[0]),
            model.Supplied(
                1, 2, model.DataType.UTF8_STRING, model.FlagRules(), "source"
            ),
        ]

        for each in everything:
            assert len(repr(each)) < 300, repr(each)
        assert repr(built.definition("Session-Id")) == (
            "<Avp Session-Id (0, 263) UTF8String in RFC6733>"
        )
        assert repr(application) == (
            "<Application TS29.229 16777216, clause 6, 12 messages>"
        )
        grouped = built.definition("Supported-Features")
        assert repr(grouped).endswith(", 4 members>")
        enumerated = built.definition("DRMP")
        assert repr(enumerated).endswith(", 16 values>")

    def test_a_message_serialises_to_json_with_sorted_flags(self, built):
        (uar, *_) = built.messages("TS29.229")

        plain = uar.to_dict()

        assert json.loads(json.dumps(plain)) == plain
        assert plain["flags"] == ["PXY", "REQ"]
        assert plain["is_request"] is True
        session = plain["avps"][0]
        assert (session["name"], session["min_occurs"]) == ("Session-Id", 1)
        assert session["avp"]["flag_rules"]["must"] == ["M"]
        assert session["avp"]["flag_rules"]["must_not"] == ["V"]
        assert session["avp"]["read_through"] == "RFC6733"

    def test_every_public_type_serialises(self, built):
        placeholder = model.Placeholder(built.undefined()[0])
        supplied = model.Supplied(
            1, 2, model.DataType.UTF8_STRING, model.FlagRules(), "source"
        )
        for each in (
            *built.applications("TS29.229"),
            *built.avps("TS32.299"),
            *built.holes(),
            *built.undefined(),
            *built.registry(ast.RegistryKind.APPLICATION_IDS),
            *built.marks("TS29.212", "AN-GW-Address"),
            *built.across_releases("oneM2M-TS-0004"),
            model.Alias("TS29.336", "External-Identifier", "source"),
            placeholder,
            supplied,
            model.FlagRules(must=frozenset({model.AvpFlag.VENDOR})),
        ):
            plain = each.to_dict()
            assert json.loads(json.dumps(plain)) == plain

    def test_an_enumerated_says_which_kind_each_value_is(self, built):
        plain = built.resolve("TS32.299", "SM-Service-Type").to_dict()

        kinds = {value["kind"] for value in plain["values"]}

        assert kinds >= {"value", "vendor-specific"}


class TestEntryPoints:
    @pytest.mark.parametrize(
        ("spelling", "reference"),
        [
            ("TS 29.229", "TS29.229"),
            ("ts29.229", "TS29.229"),
            ("3GPP TS 29.229", "TS29.229"),
            ("rfc6733", "RFC6733"),
            ("RFC 6733", "RFC6733"),
            ("ETSI TS 183 017", "ETSI-TS183.017"),
            ("3gpp2 x.s0057", "3GPP2-X.S0057"),
            ("onem2m ts-0004", "oneM2M-TS-0004"),
        ],
    )
    def test_a_reference_is_read_however_it_is_spelled(
        self, built, spelling, reference
    ):
        assert built.applications(spelling) == built.applications(reference)
        assert built.holes(spelling) == built.holes(reference)
        assert {each.reference for each in built.applications(spelling)} <= {reference}

    def test_every_query_takes_the_spelling(self, built):
        spelling = "ts 29.229"

        avp = built.resolve(spelling, "Public-Identity")
        assert avp is not None and avp.defined_in == "TS29.229"
        assert built.messages(spelling) == built.messages("TS29.229")
        assert built.avps(spelling) == built.avps("TS29.229")
        assert built.table_rows(spelling, "Public-Identity")
        assert built.undefined("ts 29.345") == built.undefined("TS29.345")
        assert built.across_releases("ts 32.299") == built.across_releases("TS32.299")

    def test_an_unknown_reference_suggests_close_ones(self, built):
        with pytest.raises(model.ModelError, match=r"did you mean .*TS29\.229"):
            built.resolve("TS 29.299", "Public-Identity")
        with pytest.raises(model.ModelError, match="no copy of Nonsense"):
            built.messages("Nonsense")

    def test_an_unknown_version_lists_the_held_ones(self, built):
        with pytest.raises(model.ModelError, match=r"V1\.0\.0.*holds.*11\.20\.0"):
            built.messages("TS32.299", version="1.0.0")

    def test_installed_builds_over_the_installed_corpus(self, built):
        assert model.Model.installed().references() == built.references()

    def test_installed_passes_the_build_options(self):
        rebuilt = model.Model.installed(undefined=model.UndefinedPolicy.DROP)

        assert rebuilt.undefined_policy is model.UndefinedPolicy.DROP

    def test_references_is_a_tuple_as_every_query_returns(self, built):
        assert isinstance(built.references(), tuple)

    def test_the_consumers_types_need_no_module_named_ast(self):
        assert model.DataType is ast.DataType
        assert model.AvpFlag is ast.AvpFlag
        assert model.CommandFlag is ast.CommandFlag
        assert model.RegistryKind is ast.RegistryKind
        assert {"DataType", "AvpFlag", "CommandFlag", "RegistryKind"} <= set(
            model.__all__
        )
        assert "ast" not in model.__all__
        assert all(hasattr(model, name) for name in model.__all__)
