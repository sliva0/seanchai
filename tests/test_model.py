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


def _row(name, code, data_type=ast.DataType.UNSIGNED32):
    return ast.AvpTableRow(
        name=name,
        code=code,
        data_type=data_type,
        flag_rules=ast.AvpFlagRules(must=frozenset({ast.AvpFlag.VENDOR})),
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

    def _block(self, name, application_id, *scope):
        return ast.Application(
            name=name,
            source=ast.SourceRef(section="1.1"),
            application_id=application_id,
            scope=scope,
        )

    def test_a_block_gives_its_id_to_the_commands_whose_headers_print_none(self):
        built = _model(
            self._document(
                self._block("Gx", 16777238, "5"),
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
                self._block("Gx", 16777238, "5"),
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
                _table(_row("Digest-Thing", 7, ast.DataType.GROUPED)),
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
                _table(_row("Digest-Realm", 104, ast.DataType.UTF8_STRING)),
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
                (model.DATA_TYPE, model.FLAG_RULES),
                vendor_id=0,
                code=104,
            ),
        )

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
        """The origin only tabulates the AVP, so its vendor is its file's
        `; Vendor-ID:`, which is no claim against the definition's."""
        origin = _spec(
            "3GPP TS 29.901",
            [_table(_row("Thing", 1, ast.DataType.GROUPED))],
            vendor_id=999,
        )
        reprint = _spec(
            "3GPP TS 29.900",
            [_grouped("Thing", 1, "A"), _reused("Thing", "TS29.901")],
        )
        resolved = _model(origin, reprint).resolve("TS29.900", "Thing")
        assert resolved is not None
        assert resolved.identity == (10415, 1)
        assert ast.AvpFlag.VENDOR in resolved.flag_rules.must

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

    def test_a_member_with_a_hole_says_why_it_has_no_avp(self):
        absent = _spec(
            "3GPP TS 29.900",
            [
                _message("Test-Request", "Nowhere", "Elsewhere"),
                _reused("Elsewhere", "X.S0057"),
            ],
        )
        (message,) = _model(absent).messages("TS29.900")
        assert [member.avp for member in message.avps] == [None, None]
        assert [str(member.hole) for member in message.avps] == [
            "TS29.900 Nowhere: resolves nowhere",
            "TS29.900 Elsewhere: resolves nowhere"
            " (re-used from X.S0057, which the corpus lacks)",
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
        clause 7; TS 29.212's headers print no ids, so Gx, Gxx, Sd, St and
        annex E take theirs from the clauses stating them and split by
        clause; TS 29.273 shares 16777250 between SWa, STa and SWd."""

        def keys(reference):
            return [
                (app.application_id, app.clause, app.name, app.stated_in)
                for app in built.applications(reference)
            ]

        assert keys("TS29.272") == [
            (16777251, "7", None, None),
            (16777308, "7", None, None),
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

    def test_29229_types_the_digest_avps_rfc_4590_leaves_untyped(self, built):
        realm = built.resolve("TS29.229", "Digest-Realm")
        assert realm is not None
        assert (realm.defined_in, realm.data_type) == (
            "RFC4590",
            ast.DataType.UTF8_STRING,
        )
        assert built.resolve("RFC4590", "Digest-Realm") is None


# What keeps the committed corpus from building strictly, by document and
# cause. Each is a statement its source does not make: RFC 4072, 5447, 5777
# and 6734 print no flag-rule columns, RFC 4590 is a RADIUS document with no
# Diameter types, TS 32.299's untyped rows are roadmap item K, and every
# "resolves nowhere" is one of docs/linter.md's standing unresolved
# references or a re-used origin outside the corpus. A hole worked off
# shrinks this; a new one is a corpus regression.
_STANDING_HOLES = {
    "RFC4004": {
        "resolves nowhere": ["MIP-HA-to-MN-SPI", "MIP-MN-FA-SPI", "MIP-MN-HA-SPI"]
    },
    "RFC4005": {"no flag_rules": ["QoS-Filter-Rule"]},
    "RFC4072": {
        "no flag_rules": [
            "Accounting-EAP-Auth-Method",
            "EAP-Key-Name",
            "EAP-Master-Session-Key",
            "EAP-Payload",
            "EAP-Reissued-Payload",
        ]
    },
    "RFC4590": {
        "no data_type, no flag_rules": [
            "Digest-AKA-Auts",
            "Digest-Algorithm",
            "Digest-Auth-Param",
            "Digest-CNonce",
            "Digest-Domain",
            "Digest-Entity-Body-Hash",
            "Digest-HA1",
            "Digest-Method",
            "Digest-Nextnonce",
            "Digest-Nonce",
            "Digest-Nonce-Count",
            "Digest-Opaque",
            "Digest-Qop",
            "Digest-Realm",
            "Digest-Response",
            "Digest-Response-Auth",
            "Digest-Stale",
            "Digest-URI",
            "Digest-Username",
            "SIP-AOR",
        ]
    },
    "RFC5447": {
        "no flag_rules": [
            "MIP6-Agent-Info",
            "MIP6-Feature-Vector",
            "MIP6-Home-Link-Prefix",
        ]
    },
    "RFC5777": {
        "no flag_rules": [
            "Absolute-End-Fractional-Seconds",
            "Absolute-End-Time",
            "Absolute-Start-Fractional-Seconds",
            "Absolute-Start-Time",
            "C-VID-End",
            "C-VID-Start",
            "Classifier",
            "Classifier-ID",
            "Day-Of-Month-Mask",
            "Day-Of-Week-Mask",
            "Diffserv-Code-Point",
            "Direction",
            "ETH-Ether-Type",
            "ETH-Option",
            "ETH-Proto-Type",
            "ETH-SAP",
            "EUI64-Address",
            "EUI64-Address-Mask",
            "EUI64-Address-Mask-Pattern",
            "Excess-Treatment",
            "Filter-Rule",
            "Filter-Rule-Precedence",
            "Fragmentation-Flag",
            "From-Spec",
            "High-User-Priority",
            "ICMP-Code",
            "ICMP-Type",
            "ICMP-Type-Number",
            "IP-Address",
            "IP-Address-End",
            "IP-Address-Mask",
            "IP-Address-Range",
            "IP-Address-Start",
            "IP-Bit-Mask-Width",
            "IP-Option",
            "IP-Option-Type",
            "IP-Option-Value",
            "Low-User-Priority",
            "MAC-Address",
            "MAC-Address-Mask",
            "MAC-Address-Mask-Pattern",
            "Month-Of-Year-Mask",
            "Negated",
            "Port",
            "Port-End",
            "Port-Range",
            "Port-Start",
            "Protocol",
            "QoS-Capability",
            "QoS-Parameters",
            "QoS-Profile-Id",
            "QoS-Profile-Template",
            "QoS-Resources",
            "QoS-Semantics",
            "S-VID-End",
            "S-VID-Start",
            "TCP-Flag-Type",
            "TCP-Flags",
            "TCP-Option",
            "TCP-Option-Type",
            "TCP-Option-Value",
            "Time-Of-Day-Condition",
            "Time-Of-Day-End",
            "Time-Of-Day-Start",
            "Timezone-Flag",
            "Timezone-Offset",
            "To-Spec",
            "Treatment-Action",
            "Use-Assigned-Address",
            "User-Priority-Range",
            "VLAN-ID-Range",
        ]
    },
    "RFC6734": {
        "no flag_rules": [
            "Key",
            "Key-Lifetime",
            "Key-Name",
            "Key-SPI",
            "Key-Type",
            "Keying-Material",
        ]
    },
    "RFC7155": {"no flag_rules": ["QoS-Filter-Rule"]},
    "TS29.061": {"no data_type, no flag_rules": ["3GPP-Session-Stop-Indicator"]},
    "TS29.154": {"resolves nowhere": ["External-Group-Identifier"]},
    "TS29.212": {
        "resolves nowhere (re-used from X.S0057, which the corpus lacks)": [
            "3GPP2-BSID"
        ],
        "resolves nowhere (re-used from TS283.034, which the corpus lacks)": [
            "Logical-Access-ID",
            "Physical-Access-ID",
        ],
    },
    "TS29.214": {
        "resolves nowhere (re-used from TS183.017, which the corpus lacks)": [
            "Reservation-Priority"
        ]
    },
    "TS29.219": {
        "resolves nowhere (re-used from TS283.034, which the corpus lacks)": [
            "Logical-Access-ID",
            "Physical-Access-ID",
        ]
    },
    "TS29.229": {"resolves nowhere": ["Line-Identifier"]},
    "TS29.272": {"no flag_rules": ["MIP6-Agent-Info"]},
    "TS29.273": {
        "resolves nowhere (re-used from TS283.034, which the corpus lacks)": [
            "Logical-Access-ID"
        ],
        "resolves nowhere": ["NSWO-Authorization"],
    },
    "TS29.338": {
        "resolves nowhere (re-used from TS23.329, which the corpus lacks)": ["MSISDN"]
    },
    "TS29.345": {"resolves nowhere": ["ProSe-Query-Code", "ProSe-Response-Code"]},
    "TS29.389": {
        "no flag_rules": [
            "V2X-Application-Server",
            "V2X-Authorization-Data",
            "V2X-Permission-in-VPLMN",
        ]
    },
    "TS32.299": {
        "resolves nowhere": [
            "3GPP2-BSID",
            "Logical-Access-ID",
            "M2M-Information",
            "Monitored-HPLMN-Identifier",
            "Monitoring-Event-Report",
            "Network-Element",
            "Physical-Access-ID",
            "Service-ID",
            "Submission-Timestamp",
            "TCP-Source-Port",
        ],
        "no data_type, no flag_rules": [
            "Application-Server-ID",
            "Application-Service-Type",
            "Application-Session-ID",
            "Content-ID",
            "Content-Provider-ID",
            "DCD-Information",
            "Delivery-Status",
            "IM-Information",
            "Number-Of-Messages-Successfully-Exploded",
            "Number-Of-Messages-Successfully-Sent",
            "Service-Generic-Information",
            "Total-Number-Of-Messages-Exploded",
            "Total-Number-Of-Messages-Sent",
        ],
        "no data_type, no flag_rules (re-used from TS29.140, which the corpus lacks)": [
            "VAS-Id",
            "VASP-Id",
        ],
    },
}


def test_the_committed_corpus_does_not_build_strictly_for_its_standing_holes():
    with pytest.raises(model.IncompleteCorpusError) as raised:
        model.Model.build(corpus.Corpus.load([_ROOT / "dad"]), strict=True)
    actual: dict[str, dict[str, list[str]]] = {}
    for hole in raised.value.holes:
        why = str(hole).split(": ", 1)[1]
        actual.setdefault(hole.reference, {}).setdefault(why, []).append(hole.name)
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
    hole = named.hole("RFC4072", "EAP-Payload")
    assert hole is not None and hole.wireshark_name == "EAP-Payload"
