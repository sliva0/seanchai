"""The Wireshark dictionary oracle: parsing and the cross-check rules."""

from pathlib import Path

import pytest

from seanchai import oracle
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
    two known dictionary-side quirks."""
    from seanchai.dad import parser

    loaded = oracle.Oracle.load(_ROOT / "specifications" / "wireshark")
    spec = parser.parse(
        (_ROOT / "dad" / "rfc" / "rfc6733.dad").read_text(encoding="utf-8")
    )

    findings = oracle.crosscheck(spec, loaded)

    # Both sides of each are pinned: Wireshark names code 50
    # Accounting-Multi-Session-Id where the RFC says Acct-Multi-Session-Id,
    # and types Authorization-Lifetime Integer32 where the RFC says
    # Unsigned32.
    assert sorted(finding.rule for finding in findings) == [
        "name-disagrees",
        "type-disagrees",
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
