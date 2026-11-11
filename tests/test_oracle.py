"""The Wireshark oracle: the corpus against the pinned dictionary under
`specifications/wireshark`, then what the pinned data cannot show: an alias
going stale, a colliding identity, and what the oracle refuses to read.

The `sources` tests fail without `seanchai corpus download --only wireshark`.
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import _CORPUS_DIR

from seanchai import corpus, model, oracle
from seanchai.cli import main
from seanchai.dad import ast, formatter, parser

_ROOT = Path(__file__).parent.parent
_WIRESHARK = _ROOT / "specifications" / "wireshark"
_ALIASES = _ROOT / "integrations" / "wireshark" / "aliases.toml"


@pytest.fixture(scope="module")
def dictionary() -> oracle.Oracle:
    return oracle.Oracle.load(_WIRESHARK)


@pytest.mark.sources
def test_rfc_6733_agrees_with_the_dictionary_but_for_its_known_quirks(dictionary):
    """The dictionary's display types (Result-Code `Enumerated`) count as
    agreement. Wireshark names code 50 Accounting-Multi-Session-Id, types
    Authorization-Lifetime Integer32, and prefixes clause 7.1.4's
    ELECTION_LOST."""
    spec = parser.parse((_CORPUS_DIR / "rfc" / "rfc6733.dad").read_text("utf-8"))

    findings = oracle.crosscheck(spec, dictionary)

    assert sorted(str(finding).split("]")[0] for finding in findings) == [
        "[name-disagrees",
        "[type-disagrees",
        "[value-disagrees",
    ]
    assert (
        "[value-disagrees] Result-Code 4003 is ELECTION_LOST (clause 7.1.4): the"
        " dictionary calls it DIAMETER_ELECTION_LOST"
    ) in map(str, findings)


@pytest.mark.sources
def test_the_corpus_reports_what_docs_oracle_md_lists(dictionary):
    """Every accepted rename holds once and none is stale; the other findings
    are pinned by count, with one of each kind docs/oracle.md names."""
    aliases = oracle.load_aliases(_ALIASES)
    findings = {
        (entry.spec.specification, str(finding)): finding
        for entry in corpus.Corpus.load([_CORPUS_DIR]).newest()
        for finding in oracle.crosscheck(entry.spec, dictionary, aliases)
    }

    accepted = [finding for finding in findings.values() if finding.accepted_by]
    rules = [finding.rule for finding in findings.values()]
    assert len(accepted) == len(aliases) == 36
    assert "stale-alias" not in rules
    assert len(findings) - len(accepted) == 105
    assert rules.count("name-disagrees") == 70
    assert sum(rule.startswith("value-") for rule in rules) == 16
    for specification, line in [
        (
            "ETSI TS 183 066",
            "[name-disagrees] Data-Operation-Indicator (AVP table): the dictionary"
            " calls (vendor 13019, code 420) ETSI-Event-Type-420",
        ),
        (
            "3GPP2 X.S0013-014",
            "[type-disagrees] Flow-Identifier (AVP table): corpus says OctetString,"
            " the dictionary says UTF8String",
        ),
        (
            "3GPP TS 29.229",
            "accepted[name-disagrees] User-Data (AVP table): the dictionary calls"
            " (vendor 10415, code 606) Cx-User-Data (kept apart from TS 29.329's"
            " User-Data (10415, 702))",
        ),
    ]:
        assert (specification, line) in findings


@pytest.mark.sources
def test_the_model_reads_wiresharks_names_by_identity():
    built = model.Model.build(corpus.Corpus.load([_CORPUS_DIR]), wireshark=_WIRESHARK)

    user_data = built.resolve("TS29.229", "User-Data")
    session = built.resolve("RFC6733", "Session-Id")
    assert user_data is not None and session is not None
    assert (user_data.name, user_data.wireshark_name) == ("User-Data", "Cx-User-Data")
    assert session.wireshark_name == "Session-Id"


@pytest.mark.sources
def test_crosscheck_reports_without_failing_and_shows_accepted_renames(monkeypatch):
    monkeypatch.chdir(_ROOT)

    result = CliRunner().invoke(main, ["corpus", "crosscheck", "--show-accepted"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[-1] == (
        "checked 77 files against the dictionary: 105 findings, 36 accepted renames"
    )
    assert any(
        line.startswith("skipped ") and "an older copy than the one checked" in line
        for line in lines
    )
    assert any("accepted[name-disagrees] User-Data" in line for line in lines)


# --- what only a synthetic dictionary can show -----------------------------------


_AVP = (
    '<avp name="Vendor-AVP" code="700" vendor-id="TGPP">'
    '<type type-name="Unsigned32"/></avp>'
)
_VENDOR = '<vendor vendor-id="TGPP" code="10415" name="3GPP"/>'


def _dictionary_xml(directory: Path, body: str) -> Path:
    directory.mkdir(exist_ok=True)
    (directory / "dictionary.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n{body}', "utf-8"
    )
    return directory


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (None, "cannot read the dictionary"),
        ("<dictionary><base>", "does not parse"),
        ("<dictionary><base/></dictionary>", "holds no AVPs"),
        (f"<dictionary><base>{_AVP}</base></dictionary>", "undeclared vendor 'TGPP'"),
        ("<dictionary>&Missing;</dictionary>", "undeclared entity &Missing;"),
        (
            '<!DOCTYPE dictionary [<!ENTITY Gone SYSTEM "gone.xml">]>'
            "<dictionary>&Gone;</dictionary>",
            "entity file gone.xml is missing",
        ),
    ],
    ids=["absent", "malformed", "empty", "vendor", "entity", "entity-file"],
)
def test_an_unreadable_dictionary_is_refused(tmp_path, body, message):
    directory = tmp_path / "wireshark"
    if body is not None:
        _dictionary_xml(directory, body)

    with pytest.raises(oracle.OracleError, match=message):
        oracle.Oracle.load(directory)


@pytest.mark.parametrize("dictionary", ["/nonexistent", Path("/nonexistent"), 7])
def test_a_model_over_an_unreadable_dictionary_raises_a_model_error(dictionary):
    books = corpus.Corpus.load(_CORPUS_DIR / "rfc" / "rfc6733.dad")

    with pytest.raises(model.ModelError, match="cannot read the Wireshark dictionary"):
        model.Model.build(books, holes=model.HolePolicy.ANY, wireshark=dictionary)


_ALIAS = (
    '[[alias]]\nspecification = "TS29.999"\nname = "Spec-Name"\n'
    'wireshark = "Vendor-AVP"\nreason = {reason}\n'
)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (_ALIAS.format(reason='"kept apart"') * 2, "aliased twice"),
        (_ALIAS.format(reason='"kept"').replace('reason = "kept"\n', ""), "exactly"),
        (_ALIAS.format(reason='"""\n    """'), "empty or non-text"),
        ('other = "x"\n', r"only \[\[alias\]\] tables"),
    ],
    ids=["twice", "keys", "empty-reason", "not-a-table"],
)
def test_an_aliases_file_is_refused_unless_each_entry_is_whole(tmp_path, text, message):
    path = tmp_path / "aliases.toml"
    path.write_text(text)

    with pytest.raises(oracle.OracleError, match=message):
        oracle.load_aliases(path)


def test_an_alias_reads_its_reason_as_prose(tmp_path):
    path = tmp_path / "aliases.toml"
    path.write_text(_ALIAS.format(reason='"""\n    kept\n    apart\n    """'))

    assert oracle.load_aliases(path) == (
        oracle.Alias("TS29.999", "Spec-Name", "Vendor-AVP", "kept apart"),
    )


def _entry(name: str, code: int, type_name: str) -> oracle.DictionaryAvp:
    return oracle.DictionaryAvp(
        name=name,
        code=code,
        vendor=10415,
        type_name=type_name,
        grouped=False,
        enumerated=False,
    )


_KNOWN = oracle.Oracle(
    avps={
        (10415, 700): [_entry("Vendor-AVP", 700, "Unsigned32")],
        (10415, 701): [
            _entry("Clash-Text", 701, "UTF8String"),
            _entry("Clash-Number", 701, "Unsigned32"),
        ],
    }
)


def _vendor_spec(name: str, data_type: ast.DataType | None) -> ast.Specification:
    return ast.Specification(
        specification="3GPP TS 29.999",
        vendor_id=10415,
        version="18.0.0",
        sections=(
            ast.AvpTable(
                table="1",
                columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.TYPE),
                source=ast.SourceRef(section="4.5"),
                rows=(ast.AvpTableRow(name=name, code=700, data_type=data_type),),
            ),
        ),
    )


_U32 = ast.DataType.UNSIGNED32


@pytest.mark.parametrize(
    ("name", "data_type", "wireshark", "found"),
    [
        ("Spec-Name", _U32, "Vendor-AVP", "accepted[name-disagrees] Spec-Name"),
        (
            "Spec-Name",
            _U32,
            "Old-Name",
            "[stale-alias] Spec-Name (AVP table): the accepted rename Old-Name does"
            " not hold: the dictionary calls (vendor 10415, code 700) Vendor-AVP",
        ),
        # The dictionary has come round to the corpus's own spelling.
        ("Vendor-AVP", _U32, "Old-Name", "[stale-alias] Vendor-AVP (AVP table)"),
        (
            "Spec-Name",
            ast.DataType.UTF8_STRING,
            "Vendor-AVP",
            "[stale-alias] Spec-Name (AVP table): the accepted rename Vendor-AVP"
            " does not hold: corpus says UTF8String, the dictionary says Unsigned32",
        ),
        # A row stating no type confirms no rename.
        ("Spec-Name", None, "Vendor-AVP", "is unconfirmed, the corpus stating no"),
    ],
    ids=["accepted", "renamed", "own-spelling", "typed-otherwise", "typeless"],
)
def test_an_alias_holds_only_while_the_dictionary_agrees(
    name, data_type, wireshark, found
):
    alias = oracle.Alias("TS29.999", name, wireshark, "kept apart")
    elsewhere = oracle.Alias("TS29.998", name, wireshark, "kept apart")

    (finding,) = oracle.crosscheck(_vendor_spec(name, data_type), _KNOWN, [alias])

    assert found in str(finding)
    assert (finding.accepted_by is not None) == found.startswith("accepted")
    # An alias for another document changes nothing.
    if name != "Vendor-AVP":
        (other,) = oracle.crosscheck(_vendor_spec(name, data_type), _KNOWN, [elsewhere])
        assert other.rule == "name-disagrees" and other.accepted_by is None


def test_an_alias_naming_nothing_the_file_defines_is_stale():
    alias = oracle.Alias("TS29.999", "Gone", "Vendor-AVP", "kept apart")

    assert oracle.crosscheck(_vendor_spec("Vendor-AVP", _U32), _KNOWN, [alias]) == [
        oracle.Finding(
            "stale-alias",
            "Gone: the accepted rename Vendor-AVP names no AVP the file defines or"
            " tabulates",
        )
    ]


def test_name_for_settles_a_colliding_identity_by_spelling_then_type():
    assert _KNOWN.name_for(10415, 700, "Spec-Spelling", _U32) == "Vendor-AVP"
    assert _KNOWN.name_for(10415, 701, "Clash-Text", _U32) == "Clash-Text"
    assert _KNOWN.name_for(10415, 701, "Clash", _U32) == "Clash-Number"
    assert _KNOWN.name_for(10415, 701, "Clash", None) is None
    assert _KNOWN.name_for(10415, 702, "Absent", _U32) is None


def _written(path: Path, version: str, data_type: ast.DataType) -> None:
    spec = ast.Specification(
        specification="3GPP TS 29.999",
        vendor_id=10415,
        version=version,
        sections=(
            ast.AvpTable(
                table="1",
                columns=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.TYPE),
                source=ast.SourceRef(section="4.5"),
                rows=(
                    ast.AvpTableRow(name="Vendor-AVP", code=700, data_type=data_type),
                ),
            ),
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(formatter.format_spec(spec), encoding="utf-8")


def test_crosscheck_reads_the_newest_copy_of_each_document_only(tmp_path, monkeypatch):
    """The dictionary describes a document's newest copy: an older one is
    skipped and said to be, raw files under a directory are left out, and two
    files of one document and version are refused. With nothing named it reads
    the installed corpus, and names the package when there is none."""
    wireshark = _dictionary_xml(
        tmp_path / "dictionary",
        f"<dictionary><base>{_AVP}</base>{_VENDOR}</dictionary>",
    )
    corpus_dir = tmp_path / "dad"
    newest = corpus_dir / "3gpp/rel-18/29999-i00.dad"
    _written(newest, "18.0.0", ast.DataType.UNSIGNED32)
    _written(
        corpus_dir / "3gpp/rel-7/29999-700.dad", "7.0.0", ast.DataType.OCTET_STRING
    )
    mirror = corpus_dir / "raw/3gpp/rel-18/29999-i00.raw.dad"
    _written(mirror, "18.0.0", ast.DataType.OCTET_STRING)

    def crosscheck(*arguments):
        return CliRunner().invoke(
            main, ["corpus", "crosscheck", "--wireshark", str(wireshark), *arguments]
        )

    result = crosscheck(str(corpus_dir))
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        f"skipped {corpus_dir}/3gpp/rel-7/29999-700.dad: TS29.999 7.0.0, an older"
        " copy than the one checked",
        "checked 1 files against the dictionary: 0 findings",
    ]
    twice = crosscheck(str(newest), str(mirror))
    assert twice.exit_code != 0
    assert "give one copy" in twice.output

    monkeypatch.setattr(corpus, "installed_directory", lambda: newest.parent)
    installed = crosscheck()
    assert installed.output == "checked 1 files against the dictionary: 0 findings\n"
    monkeypatch.undo()
    monkeypatch.setitem(sys.modules, "seanchai_corpus", None)
    missing = crosscheck()
    assert missing.exit_code == 1
    assert "seanchai-corpus" in missing.output
