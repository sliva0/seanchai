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


class TestResolutionOrder:
    def test_a_local_definition_wins_over_the_reused_listing(self):
        """An extension means what the extending document says (TS 29.272
        re-defines nine of RFC 6733's AVPs with extra members)."""
        origin = _spec(
            "RFC6733",
            [_grouped("Thing", 1, "A", vendor_id=None)],
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
            [_table(_row("Digest-Thing", 7)), _reused("Digest-Thing", "RFC4590")],
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
            [_grouped("Thing", 1, "A", vendor_id=None)],
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

    def test_a_definition_among_its_own_descendants_stops_resolving(self):
        looped = _spec("3GPP TS 29.900", [_grouped("Loop", 1, "Loop")])
        resolved = _model(looped).resolve("TS29.900", "Loop")
        assert isinstance(resolved, model.Grouped)
        assert resolved.members[0].avp is None


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

    def test_the_two_code_621_spaces_stay_separate(self, built):
        """TS 29.229's own 621 and RFC 7683's 621 are different AVPs, which
        is the case that forced identity to be a (vendor, code) pair."""
        assert {a.name for a in built.identified(10415, 621)} == {
            "Primary-Charging-Collection-Function-Name"
        }
        assert {a.name for a in built.identified(0, 621)} == {"OC-Supported-Features"}

    def test_a_reused_chain_is_followed_across_files(self, built):
        drmp = built.resolve("TS29.229", "DRMP")
        assert drmp is not None
        assert drmp.defined_in == "RFC7944"
        assert isinstance(drmp, model.Enumerated)
