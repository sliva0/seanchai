"""The RFC text extractor: the shapes it refuses and the declarations it checks.

Every shape a corpus RFC prints is pinned by `test_real_sources.py`; these
are the failures no committed RFC reaches, each a small text modelled on the
RFC named beside it.
"""

import pytest
from conftest import _declare

from seanchai.dad import ast
from seanchai.extractor import rfc_text
from seanchai.extractor.errors import ExtractionError

_HEADER_BOX = """\
                                            +----------+
                                            | AVP Flag |
                                            |  rules   |
                                            |----+-----|
                   AVP  Section             |    |MUST |
   Attribute Name  Code Defined  Data Type  |MUST| NOT |
   -----------------------------------------|----+-----|
"""
_ROW = "   Class             25  8.20    OctetString| M  |  V  |\n"
_RULE = "   -----------------------------------------|----+-----|\n"


def _rfc(body: str) -> str:
    """A minimal RFC text: a cover header block, then `body`."""
    return (
        "Internet Engineering Task Force (IETF)                        A. Author\n"
        "Request for Comments: 9999                                     Somewhere\n"
        "Category: Standards Track\n"
        "\n"
        "                       A Synthetic Protocol\n"
        "\n" + body
    )


def _table(*rows: str, header: str = _HEADER_BOX, rule: str = _RULE) -> str:
    """RFC 6733 clause 4.5's AVP table shape."""
    return "4.5.  Synthetic Base AVPs\n\n" + header + "".join(rows) + rule


def _read(tmp_path, body: str, *quirks: str, warnings: list[str] | None = None):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc(body), encoding="utf-8")
    declarations = "".join(f'[[quirk]]\nname = "{q}"\nreason = "x"\n' for q in quirks)
    sources = _declare(tmp_path, declarations) if quirks else None
    return rfc_text.extract(path, sources_dir=sources, warnings=warnings)


def _enumerated(clause: str) -> str:
    """A table typing `Prompt` Enumerated, and its clause (RFC 4005's shape)."""
    return (
        _table("   Prompt            76  5.3     Enumerated | M  |  V  |\n")
        + "\n5.3.  Prompt AVP\n\n"
        "   The Prompt AVP (AVP Code 76) is of type Enumerated.\n" + clause
    )


# RFC 4740 tables 2 and 3: codes and types in one table, flags in the next.
_CODES_TABLE = (
    "   +-----------------------+------+---------------+-------+\n"
    "   | Attribute Name        | AVP  | Reference     | Data- |\n"
    "   |                       | Code |               | Type  |\n"
    "   +-----------------------+------+---------------+-------+\n"
    "   | SIP-Server-URI        |  371 | Section 9.2   | UTF8S |\n"
    "   | SIP-Item-Number       |  378 | Section 9.5.2 | U32   |\n"
    "   +-----------------------+------+---------------+-------+\n"
    "\n"
    "                   Table 2: Defined AVPs\n"
    "\n"
)


def _flags_table(*names: str) -> str:
    return (
        "   +-----------------------+------+-----+-----+------+------+\n"
        "   | Attribute Name        | MUST | MAY | SHD | MUST | Encr |\n"
        "   |                       |      |     | NOT |  NOT |      |\n"
        "   +-----------------------+------+-----+-----+------+------+\n"
        + "".join(
            f"   | {name:<21} |   M  |  P  |     |   V  |   N  |\n" for name in names
        )
        + "   +-----------------------+------+-----+-----+------+------+\n"
    )


# RFC 5866 clause 7.2, with the boxed legend RFC 6736 prints under its table.
_BOXED_LEGEND = (
    "7.2.  Defined AVPs\n\n"
    "                                                  +-------------------+\n"
    "                                                  |    AVP Flag rules |\n"
    "   +----------------------------------------------|----+--------+-----+\n"
    "   |                       AVP  Section           |    |    SHLD| MUST|\n"
    "   | Attribute Name        Code Defined Data Type |MUST|     NOT|  NOT|\n"
    "   +----------------------------------------------+----+--------+-----+\n"
    "   |QoS-Authorization-Data 579    7.2  OctetString| M  |        |  V  |\n"
    "   +----------------------------------------------+----+--------+-----+\n"
    "   |M - Mandatory bit. An AVP with the M bit set and its value MUST   |\n"
    "   +------------------------------------------------------------------+\n"
)

# RFC 6738 clause 8: a row citing a note for its origin.
_NOTED_TABLE = (
    "8.  AVP Flag Rules\n\n"
    "                                                 +---------+\n"
    "                                                 |AVP Flag |\n"
    "                                                 |  Rules  |\n"
    "                                                 +----+----+\n"
    "                       AVP  Section              |    |MUST|\n"
    "    Attribute Name     Code Defined   Value Type |MUST| NOT|\n"
    "   +---------------------------------------------+----+----+\n"
    "   |Key-Lifetime        584  Note 1   Integer64  |  M | V  |\n"
    "   +---------------------------------------------+----+----+\n"
    "   |Ni                  588  6.1.1    OctetString|  M | V  |\n"
    "   +---------------------------------------------+----+----+\n\n"
)

# RFC 6736 table 2, under a clause naming no document it re-uses from.
_REUSED_WITHOUT_ORIGIN = (
    "8.3.  Reused NASREQ AVPs\n\n   Nothing cited here.\n\n"
    "                                       +---------------------+\n"
    "                                       |    AVP Flag Rules   |\n"
    "   +------------------+------+---------|----+-----+----+-----|----+\n"
    "   |                  | AVP  |         |    |     |SHLD| MUST|    |\n"
    "   | Attribute Name   | Code |Value Type|MUST| MAY| NOT|  NOT|Encr|\n"
    "   |------------------|------|---------|----+-----+----+-----|----|\n"
    "   | Calling-Station- |  31  |UTF8String| M  |  P |    |  V  | Y  |\n"
    "   |   Id             |      |          |    |    |    |     |    |\n"
    "   +------------------+------+---------|----+-----+----+-----|----+\n"
)


def _ruled(*lines: str) -> str:
    """A command whose body continues with `lines`."""
    return (
        "5.1.  Foo-Request (FOR) Command\n\n"
        "   <Foo-Request> ::= < Diameter Header: 268, REQ, PXY >\n"
        "                     < Session-Id >\n"
        + "".join(f"                     {line}\n" if line else "\n" for line in lines)
    )


def _registry(token: str) -> str:
    """RFC 4006 clause 12's IANA registry for an enumerated AVP."""
    return (
        "9.5.  Namespaces\n\n"
        "   IANA has created a registry for use with the enumerated Prompt AVP.\n\n"
        "   Token                                        | Value    | Description\n"
        "   ---------------------------------------------+----------+------------\n"
        f"   {token:<45}| 1        | RFC 9999\n"
    )


_REFUSED = [
    pytest.param(
        _table(_ROW, header=_HEADER_BOX.replace("Data Type", "Val. Type")),
        (),
        "unrecognized AVP table header",
        id="header-spelling",
    ),
    pytest.param(
        _table("   Acct-                                    | M  |  V  |\n"),
        (),
        "incomplete AVP table row",
        id="wrapped-row-without-cells",
    ),
    pytest.param(
        _table(_ROW.replace("OctetString", "OctedString")),
        (),
        "OctedString",
        id="type-typo",
    ),
    # Shapes a corpus RFC prints, each refused until its document declares it.
    pytest.param(
        _table(_ROW, "   Rest of the AVPs                          |    |     |\n"),
        (),
        "`prose-catchall-row`",
        id="catchall-row",
    ),
    pytest.param(
        _table("   MIP-Filter-      342  5.5     UTF8String | M  |  V  |\n   Rule\n"),
        (),
        "`bare-name-continuation`",
        id="bare-name-continuation",
    ),
    pytest.param(
        _table(_ROW, rule="   ------------------------------------ ----|----+-----|\n"),
        (),
        "flag cells",
        id="ragged-separator",
    ),
    pytest.param(
        "9.  AVPs\n\n" + _CODES_TABLE, (), "`type-short-forms`", id="type-short-forms"
    ),
    pytest.param(
        "9.  AVPs\n\n"
        + _CODES_TABLE
        + _flags_table("SIP-Item-Number", "SIP-Server-URI"),
        ("type-short-forms",),
        "`split-avp-tables`",
        id="split-tables",
    ),
    pytest.param(
        "9.  AVPs\n\n" + _CODES_TABLE + _flags_table("SIP-Item-Number"),
        ("split-avp-tables", "type-short-forms"),
        "SIP-Server-URI",
        id="split-tables-disagree",
    ),
    pytest.param(_BOXED_LEGEND, (), "flag cells", id="boxed-legend"),
    pytest.param(
        _REUSED_WITHOUT_ORIGIN,
        ("reused-avp-tables",),
        "names no origin",
        id="reused-without-origin",
    ),
    pytest.param(
        _NOTED_TABLE + "   Note 1: The Key AVP is defined in [RFC6734].\n",
        ("note-avp-origins",),
        "does not name Key-Lifetime",
        id="note-names-another-avp",
    ),
    pytest.param(
        _NOTED_TABLE.split("   |Ni ")[0]
        + "\n   Note 1: The Key-Lifetime AVP is defined in [RFC6734].\n",
        ("note-avp-origins",),
        "8: the AVP table has no rows: every row cites a note",
        id="every-row-noted",
    ),
    pytest.param(_table(), (), "has no rows under it", id="header-without-rows"),
    # Enumerated values.
    pytest.param(
        _enumerated(
            "   The supported values are listed in [RADIUSTypes].  The\n"
            "   complete list of defined values can be found in [RADIUS].\n"
        ),
        ("external-enum-values",),
        "names 2 sources",
        id="two-value-sources",
    ),
    pytest.param(
        _enumerated(
            "   Cause Value Name              |  RADIUS   | Diameter  |\n"
            "   ------------------------------|-----------+-----------+\n"
            "   User Request                  |     1     |   11      |\n"
            "   Lost Carrier                  |     2     |           |\n"
            "   ------------------------------|-----------+-----------+\n"
        ),
        ("cause-mapping-table",),
        r"5\.3: unreadable table row",
        id="mapping-row",
    ),
    pytest.param(
        _enumerated("   This specification defines one value, ECHO.\n\n")
        + _registry("NO_ECHO"),
        ("registry-enum-values",),
        "'NO_ECHO' is not named",
        id="registry-value-unnamed",
    ),
    # Command bodies.
    pytest.param(_ruled("…", "* [ AVP ]"), (), "`elided-members`", id="elided-line"),
    pytest.param(
        _ruled("[ OC-OLR ] ]", "* [ AVP ]"), (), "is no ABNF member", id="broken-member"
    ),
    pytest.param(
        _ruled("[ First ]", "This sentence ends the body too soon.", "[ Later ]"),
        (),
        "follows the end of",
        id="member-after-body",
    ),
    # A declaration the document no longer needs is as wrong as a missing one.
    pytest.param(
        "10.1.  AVP Codes\n\n"
        "   |Attribute Name      Code Defined     Data Type|\n"
        "   |QoS-Resources       508  3.1         Grouped  |\n",
        ("prose-avp-codes",),
        "changed nothing",
        id="quirk-unneeded",
    ),
    pytest.param(
        _table(_ROW),
        ("prose-avp-codez",),
        "prose-avp-codez.*clause-avp-table",
        id="quirk-unknown",
    ),
]


@pytest.mark.parametrize(("body", "quirks", "message"), _REFUSED)
def test_a_shape_it_cannot_read_faithfully_is_refused(tmp_path, body, quirks, message):
    with pytest.raises(ExtractionError, match=message):
        _read(tmp_path, body, *quirks)


def test_a_declaration_without_a_reason_or_for_an_exclusion_is_refused(tmp_path):
    path = tmp_path / "rfc9999.txt"
    path.write_text(_rfc(_table(_ROW)), encoding="utf-8")

    sources = _declare(tmp_path, '[[quirk]]\nname = "prose-avp-codes"\n')
    with pytest.raises(ExtractionError, match="no `reason`"):
        rfc_text.extract(path, sources_dir=sources)
    # Only the docx extractor leaves clauses out.
    sources = _declare(
        tmp_path, '[[exclude]]\nsection = "8"\nname = "A"\nreason = "x"\n'
    )
    with pytest.raises(ExtractionError, match="left nothing out"):
        rfc_text.extract(path, sources_dir=sources)


def test_a_table_row_without_a_defining_sentence_is_warned_about(tmp_path):
    """RFC 4005 clause 4.2.1's table prints no Code column; a row whose clause
    states no code keeps none, and says so."""
    body = (
        "4.2.1.  Session AVPs\n\n"
        "                                            +-----------+\n"
        "                                            | AVP Flag |\n"
        "                                            |   Rules  |\n"
        "                                            |-----+-----+\n"
        "                                            |MUST | MUST|\n"
        "   Attribute Name          Section Defined  |     |  NOT|\n"
        "   -----------------------------------------|-----+-----|\n"
        "   NAS-Port                4.2.2            |  M  |  V  |\n"
        "   NAS-Port-Type           4.2.3            |  M  |  V  |\n"
        "   -----------------------------------------|-----+-----|\n\n"
        "4.2.2.  NAS-Port AVP\n\n"
        "   Discussed elsewhere.\n\n"
        "4.2.3.  NAS-Port-Type AVP\n\n"
        "   The NAS-Port-Type AVP (AVP Code 61) is of type Enumerated.\n"
    )
    warnings: list[str] = []

    spec = _read(tmp_path, body, "prose-avp-codes", warnings=warnings)

    (table,) = [s for s in spec.sections if isinstance(s, ast.AvpTable)]
    assert [row.code for row in table.rows] == [None, 61]
    assert any("'NAS-Port'" in w and "no defining sentence" in w for w in warnings)


def test_value_lines_it_does_not_read_are_warned_about(tmp_path):
    warnings: list[str] = []

    spec = _read(tmp_path, _enumerated("      0  No Echo\n      1  Echo\n"),
                 warnings=warnings)  # fmt: skip

    (prompt,) = [s for s in spec.sections if isinstance(s, ast.EnumeratedAvp)]
    assert prompt.values == (ast.EnumValue(name="Echo", value=1),)
    assert any(
        "1 value line(s) not read" in w and "'0  No Echo'" in w for w in warnings
    )
