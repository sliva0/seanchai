"""The consumer model resolves names into objects by a stated policy.

The synthetic cases pin the resolution order — local definition, re-used
origin, table row, base document — and the corpus-level cases pin what the
committed files actually resolve to, so a policy change shows up as a
concrete AVP moving between documents rather than as a green run.
"""

from pathlib import Path

import pytest

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
    return model.Model.build(corpus.Corpus(_entry(spec) for spec in specs))


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
        assert resolved.flag_rules != ast.AvpFlagRules(must_not=_V)

    def test_a_citing_tables_m_bit_comes_before_rfc_6733s_rule(self):
        """TS 29.273 sets M for RFC 5777's `QoS-Capability` in its own table;
        its reading takes that, and RFC 5777's own reading keeps the rule."""
        origin = _spec(
            "RFC5777",
            [_flagless_table(ast.AvpTableRow(name="Port", code=530, data_type=_I32))],
            vendor_id=0,
            version=None,
        )
        rules = ast.AvpFlagRules(must=_M, must_not=_V)
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
        assert type(resolved.flag_rules) is ast.AvpFlagRules

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
        assert raised.value.holes == model.Model.build(books).holes()

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
    return model.Model.build(corpus.Corpus.load([_ROOT / "dad"]))


class TestOverTheCommittedCorpus:
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
        assert first.flag_rules == imsi.flag_rules
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
        assert arp.flag_rules == row.flag_rules

    def test_an_externally_defined_enumeration_is_complete(self, built):
        """TS 29.272 clause 7.3.67 defines Trace-Depth and points at TS
        32.422 for its values: an AVP with no values and their source, not a
        hole."""
        trace_depth = built.resolve("TS29.272", "Trace-Depth")
        assert isinstance(trace_depth, model.Enumerated)
        assert trace_depth.values == ()
        assert trace_depth.values_source == "TS 32.422 [23] for Trace Depth"
        assert built.hole("TS29.272", "Trace-Depth") is None
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

    def test_the_digest_avps_take_rfc_4590s_stand_in_types(self, built):
        """RFC 4590 types nothing; its corrections type all twenty
        UTF8String with Wireshark's flag rules, which TS 29.229's re-used
        Digest-Realm resolves to, ahead of its own table's M in Must."""
        realm = built.resolve("TS29.229", "Digest-Realm")
        assert realm is not None
        assert (realm.defined_in, realm.data_type) == (
            "RFC4590",
            ast.DataType.UTF8_STRING,
        )
        assert realm == built.resolve("RFC4590", "Digest-Realm")
        assert realm.flag_rules == ast.AvpFlagRules(
            may=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.PROTECTED}),
            must_not=frozenset({ast.AvpFlag.VENDOR}),
        )
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
        assert len(built.registry(ast.RegistryKind.APPLICATION_IDS)) == 54


# What keeps the committed corpus from building strictly, by document and
# cause. Each is a statement its source does not make: RFC 4590 is a RADIUS
# document with no Diameter types, TS 29.061's 3GPP-Session-Stop-Indicator
# row prints only a code, every "resolves nowhere" is one of
# docs/linter.md's standing unresolved references, and TS 32.299 V11.20.0's
# rows are re-used from Release 11 copies and OMA-DDS-Charging_Data, which
# the corpus lacks. A hole worked off shrinks this; a new one is a corpus
# regression. Roadmap item N lists them by cause.
_STANDING_HOLES = {
    "RFC4004": {
        "resolves nowhere": ["MIP-HA-to-MN-SPI", "MIP-MN-FA-SPI", "MIP-MN-to-HA-SPI"]
    },
    "TS29.061": {"no data_type, no flag_rules": ["3GPP-Session-Stop-Indicator"]},
    "TS29.154": {"resolves nowhere": ["External-Group-Identifier"]},
    "TS29.345": {"resolves nowhere": ["ProSe-Query-Code", "ProSe-Response-Code"]},
    "TS32.299": {
        "resolves nowhere": [
            "Network-Element",
            "Submission-Timestamp",
        ],
    },
    # oneM2M TS-0004's Service-Information is V11.20.0's ([31], "Release
    # 11"), whose body reaches what Release 11's other documents define;
    # the corpus holds them at Release 18, and their non-specific
    # references mean Release 11's. The three OMA-DDS-Charging_Data rows
    # are as Release 18's were before their types and flags were supplied.
    "TS32.299 V11.20.0": {
        "no data_type, no flag_rules (re-used from OMA-DDS-Charging_Data,"
        " which the corpus lacks)": [
            "DCD-Information",
            "IM-Information",
            "Service-Generic-Information",
        ],
        "no data_type, no flag_rules (re-used from TS29.061, which the corpus lacks)": [
            "3GPP-Charging-Characteristics",
            "3GPP-Charging-Id",
            "3GPP-GGSN-MCC-MNC",
            "3GPP-IMSI",
            "3GPP-IMSI-MCC-MNC",
            "3GPP-MS-TimeZone",
            "3GPP-NSAPI",
            "3GPP-PDP-Type",
            "3GPP-RAT-Type",
            "3GPP-SGSN-MCC-MNC",
            "3GPP-Selection-Mode",
            "3GPP-Session-Stop-Indicator",
            "3GPP-User-Location-Info",
            "CN-IP-Multicast-Distribution",
            "MBMS-2G-3G-Indicator",
            "MBMS-Data-Transfer-Start",
            "MBMS-Data-Transfer-Stop",
            "MBMS-Service-Area",
            "MBMS-Service-Type",
            "MBMS-Session-Identity",
            "RAI",
            "Required-MBMS-Bearer-Capabilities",
            "TMGI",
        ],
        "no data_type, no flag_rules (re-used from TS29.173, which the corpus lacks)": [
            "MME-Name",
            "MME-Realm",
        ],
        "no data_type, no flag_rules (re-used from TS29.212, which the corpus lacks)": [
            "3GPP2-BSID",
            "Charging-Rule-Base-Name",
            "QoS-Information",
            "User-Location-Info-Time",
        ],
        "no data_type, no flag_rules (re-used from TS29.214, which the corpus lacks)": [
            "AF-Charging-Identifier",
            "Access-Network-Charging-Identifier-Value",
            "Application-Service-Provider-Identity",
            "Flows",
            "Sponsor-Identity",
        ],
        "no data_type, no flag_rules (re-used from TS29.229, which the corpus lacks)": [
            "Server-Capabilities",
            "Session-Priority",
        ],
        "no data_type, no flag_rules (re-used from TS29.272, which the corpus lacks)": [
            "CSG-Id",
            "MME-Number-for-MT-SMS",
            "Terminal-Information",
        ],
        "no data_type, no flag_rules (re-used from TS29.273, which the corpus lacks)": [
            "SSID"
        ],
        "no data_type, no flag_rules (re-used from TS29.329, which the corpus lacks)": [
            "MSISDN"
        ],
    },
}


def test_every_row_citing_an_etsi_tispan_origin_resolves_to_its_transcription():
    """3GPP cites ES 283 034 as "ETSI TS 283 034" and TS 183 017 under its
    own number; each row resolves to the transcribed document's AVP, in
    ETSI's vendor space, and the transcriptions cite each other too."""
    books = corpus.Corpus.load([_ROOT / "dad"])
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
    built = model.Model.build(corpus.Corpus.load([_ROOT / "dad"]))

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
    built = model.Model.build(corpus.Corpus.load([_ROOT / "dad"]))

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
    X.S0057-B" [24] is revision 0, standing in. Each AVP so reached says
    so, and nothing else in the corpus resolves across releases."""
    built = model.Model.build(corpus.Corpus.load([_ROOT / "dad"]))

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
        ("ETSI-ES283.034", "TS29.209"),
        ("ETSI-TS183.017", "TS29.209"),
        ("ETSI-TS183.017", "TS29.214"),
        ("TS29.212", "3GPP2-X.S0057"),
        ("TS32.299", "TS29.140"),
        ("oneM2M-TS-0004", "TS32.299"),
    }
    # TS 29.212's and 32.299's 3GPP2-BSID are one Avp, revision 0 standing
    # in for TS 29.212's revision B.
    assert len(built.across_releases()) == 27


def test_ts_32_299s_m2m_information_resolves_to_onem2m_ts_0004():
    """TS 32.299 table 7.5.1 tabulates M2M-Information from oneM2M TS-0004
    ([301]), which the corpus extracts from oneM2M's Word file: vendor
    45687 per clause A.4, every member resolving, oneM2M's own in 45687
    and the rest in the space table A.4-1 gives each."""
    built = model.Model.build(corpus.Corpus.load([_ROOT / "dad"]))

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
    # Its own reading is complete; what it reaches in TS 32.299 V11.20.0
    # through Service-Information is that copy's (`_STANDING_HOLES`).
    assert {hole.document for hole in built.holes("oneM2M-TS-0004")} == {
        "TS32.299 V11.20.0"
    }


def test_the_committed_corpus_does_not_build_strictly_for_its_standing_holes():
    with pytest.raises(model.IncompleteCorpusError) as raised:
        model.Model.build(corpus.Corpus.load([_ROOT / "dad"]), strict=True)
    actual: dict[str, dict[str, list[str]]] = {}
    for hole in raised.value.holes:
        why = str(hole).split(": ", 1)[1]
        actual.setdefault(hole.document, {}).setdefault(why, []).append(hole.name)
    assert actual == _STANDING_HOLES


@pytest.mark.sources
def test_the_pinned_dictionary_names_the_avps_it_spells_differently():
    """Wireshark's deliberate disambiguations and its own defects both
    arrive as `wireshark_name`, beside the specifications' spelling."""
    named = model.Model.build(
        corpus.Corpus.load([_ROOT / "dad"]),
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
