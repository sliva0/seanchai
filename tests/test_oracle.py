"""The Wireshark dictionary oracle: parsing and the cross-check rules."""

import dataclasses
import sys
from pathlib import Path

import pytest
from conftest import _CORPUS_DIR

from seanchai import corpus, model, oracle
from seanchai.dad import ast

_ROOT = Path(__file__).parent.parent


_VENDOR_AVP = (
    "<avp name='Vendor-AVP' code='700' vendor-id='TGPP'>"
    "<type type-name='Unsigned32'/></avp>"
)


def _dictionary(tmp_path, vendor_file=_VENDOR_AVP):
    (tmp_path / "dictionary.ent").write_text('<!ENTITY Custom "">')
    (tmp_path / "TGPP.xml").write_text(
        f"<?xml version='1.0' encoding='UTF-8'?>\n{vendor_file}"
    )
    (tmp_path / "dictionary.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE dictionary SYSTEM "dictionary.dtd" [
    <!ENTITY TGPP SYSTEM "TGPP.xml">
    <!ENTITY % Custom SYSTEM "dictionary.ent">
    %Custom;
]>
<dictionary>
  <base>
    <avp name="Session-Id" code="263" vendor-id="None">
      <type type-name="UTF8String"/>
    </avp>
    <avp name="Result-Code" code="268" vendor-id="None">
      <type type-name="Enumerated"/>
      <enum name="DIAMETER_SUCCESS" code="2001"/>
    </avp>
    <avp name="Framed-IP-Address" code="8" vendor-id="None">
      <type type-name="IPAddress"/>
    </avp>
    <avp name="Proxy-Info" code="284" vendor-id="None">
      <grouped/>
    </avp>
  </base>
  &TGPP;
  &Custom;
  <vendor vendor-id="TGPP" code="10415" name="3GPP"/>
</dictionary>
"""
    )
    return oracle.Oracle.load(tmp_path)


def test_load_resolves_entities_vendors_and_internal_declarations(tmp_path):
    """Vendor files arrive as XML entities and `Custom` is an internal
    entity declared in dictionary.ent — both outside what ElementTree
    resolves on its own."""
    loaded = _dictionary(tmp_path)

    (entry,) = loaded.avps[(10415, 700)]
    assert (entry.name, entry.type_name) == ("Vendor-AVP", "Unsigned32")
    (base,) = loaded.avps[(0, 263)]
    assert base.name == "Session-Id"


def _spec(*sections, vendor_id=0):
    return ast.Specification(
        specification="RFC 9999" if vendor_id == 0 else "3GPP TS 29.999",
        vendor_id=vendor_id,
        version=None if vendor_id == 0 else "18.0.0",
        sections=sections,
    )


def _table(*rows):
    return ast.AvpTable(
        table="1",
        columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.TYPE),
        source=ast.SourceRef(section="4.5"),
        rows=rows,
    )


def _row(name, code, data_type):
    return ast.AvpTableRow(name=name, code=code, data_type=data_type)


def _rules(findings):
    return [finding.rule for finding in findings]


def test_dictionary_display_conventions_are_not_disagreements(tmp_path):
    """Wireshark types Result-Code `Enumerated` (a display convention — the
    RFC says Unsigned32) and Framed-IP-Address `IPAddress` (NASREQ says
    OctetString). The mapping absorbs both; a genuine mismatch still
    reports."""
    loaded = _dictionary(tmp_path)
    spec = _spec(
        _table(
            _row("Session-Id", 263, ast.DataType.UTF8_STRING),
            _row("Result-Code", 268, ast.DataType.UNSIGNED32),
            _row("Framed-IP-Address", 8, ast.DataType.OCTET_STRING),
            _row("Proxy-Info", 284, ast.DataType.GROUPED),
        )
    )

    assert oracle.crosscheck(spec, loaded) == []


def test_name_type_and_absence_each_report(tmp_path):
    loaded = _dictionary(tmp_path)
    spec = _spec(
        _table(
            _row("Session-ID", 263, ast.DataType.UTF8_STRING),
            _row("Proxy-Info", 284, ast.DataType.OCTET_STRING),
            _row("Brand-New", 9999, ast.DataType.UNSIGNED32),
        )
    )

    findings = oracle.crosscheck(spec, loaded)

    assert _rules(findings) == [
        "name-disagrees",
        "type-disagrees",
        "absent-from-dictionary",
    ]
    assert "calls (vendor 0, code 263) Session-Id" in findings[0].message


def test_a_row_forbidding_the_v_bit_is_checked_in_the_ietf_space(tmp_path):
    """TS 29.273 tabulates RFC 5778's AVPs with V in Must not in a vendor
    10415 file; the row's identity is vendor 0's, as the model reads it."""
    loaded = _dictionary(tmp_path)
    table = ast.AvpTable(
        table="1",
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.TYPE,
            ast.AvpColumn.MUST,
            ast.AvpColumn.MUST_NOT,
        ),
        source=ast.SourceRef(section="4.5"),
        rows=(
            ast.AvpTableRow(
                name="Session-Id",
                code=263,
                data_type=ast.DataType.UTF8_STRING,
                flag_rules=ast.AvpFlagRules(
                    must=frozenset({ast.AvpFlag.MANDATORY}),
                    must_not=frozenset({ast.AvpFlag.VENDOR}),
                ),
            ),
        ),
    )

    assert oracle.crosscheck(_spec(table, vendor_id=10415), loaded) == []


def test_reused_avps_are_the_origins_to_check_not_this_files(tmp_path):
    loaded = _dictionary(tmp_path)
    spec = _spec(
        _table(_row("Session-ID", 263, ast.DataType.UTF8_STRING)),
        ast.ReusedAvps(
            table="2",
            columns=(ast.ReusedColumn.NAME, ast.ReusedColumn.FROM),
            source=ast.SourceRef(section="4.6"),
            rows=(ast.ReusedAvpRow(name="Session-ID", origin="RFC6733"),),
        ),
    )

    assert oracle.crosscheck(spec, loaded) == []


@pytest.mark.sources
def test_the_pinned_dictionary_loads_and_the_base_protocol_agrees():
    """The real dictionary parses, and RFC 6733's `.dad` — the file
    hand-verification started from — reports no disagreements beyond the
    three known dictionary-side quirks."""
    from seanchai.dad import parser

    loaded = oracle.Oracle.load(_ROOT / "specifications" / "wireshark")
    spec = parser.parse(
        (_CORPUS_DIR / "rfc" / "rfc6733.dad").read_text(encoding="utf-8")
    )

    findings = oracle.crosscheck(spec, loaded)

    # Both sides of each are pinned: Wireshark names code 50
    # Accounting-Multi-Session-Id where the RFC says Acct-Multi-Session-Id,
    # and types Authorization-Lifetime Integer32 where the RFC says
    # Unsigned32; and it prefixes clause 7.1.4's ELECTION_LOST.
    assert sorted(finding.rule for finding in findings) == [
        "name-disagrees",
        "type-disagrees",
        "value-disagrees",
    ]


def test_name_for_reads_wireshark_spelling_by_identity(tmp_path):
    """The corpus spelling wins where Wireshark has it; otherwise the one
    name the identity carries, or among colliding entries the one whose type
    agrees. Ambiguity and absence both say None."""
    loaded = _dictionary(
        tmp_path,
        vendor_file=(
            "<avp name='Vendor-AVP' code='700' vendor-id='TGPP'>"
            "<type type-name='Unsigned32'/></avp>"
            "<avp name='Clash-Text' code='701' vendor-id='TGPP'>"
            "<type type-name='UTF8String'/></avp>"
            "<avp name='Clash-Number' code='701' vendor-id='TGPP'>"
            "<type type-name='Unsigned32'/></avp>"
        ),
    )
    u32 = ast.DataType.UNSIGNED32
    assert loaded.name_for(0, 263, "Session-Id", ast.DataType.UTF8_STRING) == (
        "Session-Id"
    )
    assert loaded.name_for(10415, 700, "Spec-Spelling", u32) == "Vendor-AVP"
    assert loaded.name_for(10415, 701, "Clash", u32) == "Clash-Number"
    assert loaded.name_for(10415, 701, "Clash-Text", u32) == "Clash-Text"
    assert loaded.name_for(10415, 701, "Clash", None) is None
    assert loaded.name_for(10415, 702, "Absent", u32) is None


def _alias(name, wireshark="Vendor-AVP"):
    return oracle.Alias(
        specification="TS29.999", name=name, wireshark=wireshark, reason="kept apart"
    )


def _vendor_spec(name, data_type: ast.DataType | None = ast.DataType.UNSIGNED32):
    return _spec(_table(_row(name, 700, data_type)), vendor_id=10415)


def test_an_accepted_alias_is_agreement(tmp_path):
    """The dictionary's `Vendor-AVP` is the document's `Spec-Name` under the
    same vendor, code and type: listed, the rename is accepted, not a
    disagreement; an alias for another document changes nothing."""
    loaded = _dictionary(tmp_path)
    spec = _vendor_spec("Spec-Name")

    (finding,) = oracle.crosscheck(spec, loaded, [_alias("Spec-Name")])

    assert (finding.rule, finding.accepted_by) == ("name-disagrees", "kept apart")
    assert str(finding).startswith("accepted[name-disagrees] Spec-Name")
    elsewhere = dataclasses.replace(_alias("Spec-Name"), specification="TS29.998")
    (finding,) = oracle.crosscheck(spec, loaded, [elsewhere])
    assert (finding.rule, finding.accepted_by) == ("name-disagrees", None)


def test_an_alias_the_dictionary_no_longer_carries_is_stale(tmp_path):
    """The identity under another name, the corpus's own spelling or none,
    and an alias naming nothing the file defines: each is reported."""
    loaded = _dictionary(tmp_path)

    (renamed,) = oracle.crosscheck(
        _vendor_spec("Spec-Name"), loaded, [_alias("Spec-Name", "Old-Name")]
    )
    (agrees,) = oracle.crosscheck(
        _vendor_spec("Vendor-AVP"), loaded, [_alias("Vendor-AVP", "Old-Name")]
    )
    unclaimed = oracle.crosscheck(_vendor_spec("Vendor-AVP"), loaded, [_alias("Gone")])

    assert renamed == oracle.Finding(
        "stale-alias",
        "Spec-Name (AVP table): the accepted rename Old-Name does not hold:"
        " the dictionary calls (vendor 10415, code 700) Vendor-AVP",
    )
    assert agrees.rule == "stale-alias"
    assert agrees.message.endswith("(vendor 10415, code 700) Vendor-AVP")
    assert unclaimed == [
        oracle.Finding(
            "stale-alias",
            "Gone: the accepted rename Vendor-AVP names no AVP the file defines"
            " or tabulates",
        )
    ]


def test_an_alias_typed_otherwise_still_reports(tmp_path):
    """A rename is agreement only while the types agree too."""
    loaded = _dictionary(tmp_path)
    spec = _vendor_spec("Spec-Name", ast.DataType.UTF8_STRING)

    (finding,) = oracle.crosscheck(spec, loaded, [_alias("Spec-Name")])

    assert finding == oracle.Finding(
        "stale-alias",
        "Spec-Name (AVP table): the accepted rename Vendor-AVP does not hold:"
        " corpus says UTF8String, the dictionary says Unsigned32",
    )


def test_an_alias_for_a_typeless_avp_is_not_accepted(tmp_path):
    """A rename is accepted only on the types' positive agreement: a corpus
    row stating no type confirms none, so the name disagreement stays a
    finding, unaccepted and not stale."""
    loaded = _dictionary(tmp_path)
    spec = _vendor_spec("Spec-Name", None)

    (finding,) = oracle.crosscheck(spec, loaded, [_alias("Spec-Name")])

    assert finding == oracle.Finding(
        "name-disagrees",
        "Spec-Name (AVP table): the dictionary calls (vendor 10415, code 700)"
        " Vendor-AVP; the accepted rename Vendor-AVP is unconfirmed, the corpus"
        " stating no type",
    )
    assert finding.accepted_by is None


def test_aliases_load_with_every_key_once_per_name(tmp_path):
    path = tmp_path / "aliases.toml"
    entry = (
        '[[alias]]\nspecification = "TS29.999"\nname = "Spec-Name"\n'
        'wireshark = "Vendor-AVP"\nreason = "kept apart"\n'
    )
    path.write_text(entry)
    assert oracle.load_aliases(path) == (_alias("Spec-Name"),)
    path.write_text(entry * 2)
    with pytest.raises(oracle.OracleError, match="aliased twice"):
        oracle.load_aliases(path)
    path.write_text(entry.replace('reason = "kept apart"\n', ""))
    with pytest.raises(oracle.OracleError, match="exactly the keys"):
        oracle.load_aliases(path)


@pytest.mark.sources
def test_the_accepted_aliases_hold_against_the_pinned_dictionary():
    """Every entry of the repository's list accepts its rename once, and
    none is stale: the thirty-six `name-disagrees` findings it lists are
    agreement, the other thirty-four name disagreements still report."""
    from seanchai import corpus

    loaded = oracle.Oracle.load(_ROOT / "specifications" / "wireshark")
    aliases = oracle.load_aliases(_ROOT / "integrations/wireshark/aliases.toml")
    books = corpus.Corpus(corpus.Corpus.load([_CORPUS_DIR]))
    findings = [
        finding
        for entry in books.newest()
        for finding in oracle.crosscheck(entry.spec, loaded, aliases)
    ]

    accepted = [finding for finding in findings if finding.accepted_by]
    assert len(accepted) == len(aliases) == 36
    assert not [finding for finding in findings if finding.rule == "stale-alias"]
    assert len(findings) - len(accepted) == 105
    assert sum(finding.rule == "name-disagrees" for finding in findings) == 70
    assert sum(finding.rule.startswith("value-") for finding in findings) == 16


def test_crosscheck_counts_accepted_renames_apart(tmp_path):
    from click.testing import CliRunner

    from seanchai.cli import main

    (tmp_path / "dictionary").mkdir()
    _dictionary(tmp_path / "dictionary")
    _written(tmp_path / "29999-i00.dad", "18.0.0", ast.DataType.UNSIGNED32, "Spec")
    aliases = tmp_path / "aliases.toml"
    aliases.write_text(
        '[[alias]]\nspecification = "TS29.999"\nname = "Spec"\n'
        'wireshark = "Vendor-AVP"\nreason = "kept apart"\n'
    )
    arguments = [
        "corpus",
        "crosscheck",
        "--wireshark",
        str(tmp_path / "dictionary"),
        "--aliases",
        str(aliases),
        str(tmp_path / "29999-i00.dad"),
    ]

    result = CliRunner().invoke(main, arguments)
    shown = CliRunner().invoke(main, [*arguments, "--show-accepted"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "checked 1 files against the dictionary: 0 findings, 1 accepted rename"
    ]
    assert shown.output.splitlines()[0] == (
        f"{tmp_path}/29999-i00.dad: accepted[name-disagrees] Spec (AVP table):"
        " the dictionary calls (vendor 10415, code 700) Vendor-AVP (kept apart)"
    )
    arguments[4] = str(tmp_path / "none.toml")
    missing = CliRunner().invoke(main, arguments)
    assert missing.exit_code != 0
    assert "does not exist" in missing.output


def _written(path, version, data_type, name="Vendor-AVP"):
    from seanchai.dad import formatter

    spec = ast.Specification(
        specification="3GPP TS 29.999",
        vendor_id=10415,
        version=version,
        sections=(_table(_row(name, 700, data_type)),),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(formatter.format_spec(spec), encoding="utf-8")


def test_crosscheck_reads_the_newest_copy_of_each_document_only(tmp_path):
    """The corpus holds TS 32.299 at Release 18 and, for oneM2M TS-0004's
    citation, at Release 11; the dictionary describes the document, so the
    older copy is skipped and said to be, and a directory's raw files are
    skipped as the corpus loader skips them."""
    from click.testing import CliRunner

    from seanchai.cli import main

    (tmp_path / "dictionary").mkdir()
    _dictionary(tmp_path / "dictionary")
    corpus = tmp_path / "dad"
    _written(corpus / "3gpp/rel-18/29999-i00.dad", "18.0.0", ast.DataType.UNSIGNED32)
    _written(corpus / "3gpp/rel-7/29999-700.dad", "7.0.0", ast.DataType.OCTET_STRING)
    _written(
        corpus / "raw/3gpp/rel-18/29999-i00.raw.dad",
        "18.0.0",
        ast.DataType.OCTET_STRING,
    )

    result = CliRunner().invoke(
        main,
        [
            "corpus",
            "crosscheck",
            "--wireshark",
            str(tmp_path / "dictionary"),
            str(corpus),
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f"skipped {corpus}/3gpp/rel-7/29999-700.dad: TS29.999 7.0.0, an older"
        " copy than the one checked",
        "checked 1 files against the dictionary: 0 findings",
    ]

    twice = CliRunner().invoke(
        main,
        [
            "corpus",
            "crosscheck",
            "--wireshark",
            str(tmp_path / "dictionary"),
            str(corpus / "3gpp/rel-18/29999-i00.dad"),
            str(corpus / "raw/3gpp/rel-18/29999-i00.raw.dad"),
        ],
    )
    assert twice.exit_code != 0
    assert "give one copy" in twice.output


def test_an_alias_reads_its_reason_as_prose(tmp_path):
    path = tmp_path / "aliases.toml"
    entry = (
        '[[alias]]\nspecification = "TS29.999"\nname = "Spec-Name"\n'
        'wireshark = "Vendor-AVP"\nreason = {reason}\n'
    )
    path.write_text(entry.format(reason='"""\n    kept\n    apart\n    """'))
    assert oracle.load_aliases(path) == (_alias("Spec-Name"),)
    path.write_text(entry.format(reason='"""\n    """'))
    with pytest.raises(oracle.OracleError, match="empty or non-text"):
        oracle.load_aliases(path)


def test_crosscheck_without_sources_checks_the_installed_corpus(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from seanchai import corpus
    from seanchai.cli import main

    (tmp_path / "dictionary").mkdir()
    _dictionary(tmp_path / "dictionary")
    installed = tmp_path / "installed"
    _written(installed / "29999-i00.dad", "18.0.0", ast.DataType.UNSIGNED32)
    monkeypatch.setattr(corpus, "installed_directory", lambda: installed)

    result = CliRunner().invoke(
        main, ["corpus", "crosscheck", "--wireshark", str(tmp_path / "dictionary")]
    )

    assert result.exit_code == 0, result.output
    assert result.output == "checked 1 files against the dictionary: 0 findings\n"


def test_crosscheck_without_sources_or_the_package_names_it(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from seanchai.cli import main

    (tmp_path / "dictionary").mkdir()
    _dictionary(tmp_path / "dictionary")
    monkeypatch.setitem(sys.modules, "seanchai_corpus", None)

    result = CliRunner().invoke(
        main, ["corpus", "crosscheck", "--wireshark", str(tmp_path / "dictionary")]
    )

    assert result.exit_code == 1
    assert "seanchai-corpus" in result.output


@pytest.mark.parametrize("dictionary", ["/nonexistent", Path("/nonexistent"), 7])
def test_a_model_build_over_an_unreadable_dictionary_raises_a_model_error(dictionary):
    books = corpus.Corpus.load(_CORPUS_DIR / "rfc" / "rfc6733.dad")

    with pytest.raises(model.ModelError, match="cannot read the Wireshark dictionary"):
        model.Model.build(books, holes=model.HolePolicy.ANY, wireshark=dictionary)


def _value_table(*rows, avp="Result-Code", kind=ast.ValueKind.RESULT_CODES):
    return ast.ValueTable(
        avp=avp,
        kind=kind,
        source=ast.SourceRef(section="7.1"),
        rows=tuple(ast.ValueRow(name=n, value=v, section=s) for n, v, s in rows),
    )


def test_a_value_table_is_compared_with_the_dictionary_s_values():
    known = oracle.Oracle(
        avps={
            (0, 268): [
                oracle.DictionaryAvp(
                    name="Result-Code",
                    code=268,
                    vendor=0,
                    type_name="Enumerated",
                    grouped=False,
                    enumerated=True,
                    values=(
                        (2001, "DIAMETER_SUCCESS"),
                        (4003, "DIAMETER_ELECTION_LOST"),
                    ),
                )
            ],
            (10415, 700): [
                oracle.DictionaryAvp(
                    name="Some-Flags",
                    code=700,
                    vendor=10415,
                    type_name="Unsigned32",
                    grouped=False,
                    enumerated=True,
                    values=((1, "First"), (2, "Second")),
                )
            ],
        }
    )
    spec = _spec(
        _value_table(
            ("DIAMETER_SUCCESS", 2001, "7.1.2"),
            ("ELECTION_LOST", 4003, "7.1.4"),
            ("DIAMETER_NEW", 5999, None),
        ),
        _value_table(
            ("First", 0, None),
            ("Other", 1, None),
            avp="Some-Flags",
            kind=ast.ValueKind.BITS,
        ),
        _value_table(("Mine", 0, None), avp="Unknown-To-It", kind=ast.ValueKind.BITS),
    )

    assert [str(finding) for finding in oracle.crosscheck(spec, known)] == [
        "[value-disagrees] Result-Code 4003 is ELECTION_LOST (clause 7.1.4): the"
        " dictionary calls it DIAMETER_ELECTION_LOST",
        "[value-absent-from-dictionary] 1 values of Result-Code (clause 7.1) are not"
        " in the dictionary: DIAMETER_NEW",
        "[value-disagrees] Some-Flags 1 is Other (clause 7.1): the dictionary calls"
        " it Second",
    ]
