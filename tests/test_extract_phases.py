"""Unit tests for the resolve phase of the extractor.

`extract()` runs collect → resolve → assemble. Collection is document-shaped
and covered end-to-end through the synthetic docx; resolution is the part that
reasons across sections, and these tests reach it without building a document.
"""

import docx
import pytest

from seanchai.dad import ast
from seanchai.extractor import tgpp_docx


def _avp_table(*rows, section="6.3", table="6.3.1"):
    return (
        ast.AvpTable(
            table=table,
            columns=tuple(ast.AvpColumn),
            source=ast.SourceRef(section=section),
            rows=tuple(rows),
        ),
        section,
    )


def _reused_table(*rows, label="6.3.2", section="6.3"):
    return tgpp_docx._ReusedTable(
        rows=list(rows),
        columns=ast.REUSED_COLUMNS,
        label=label,
        section=section,
    )


def _grouped(vendor_id=10415, name="Group"):
    return ast.GroupedAvp(
        name=name,
        source=ast.SourceRef(section="6.3.1"),
        code=10,
        vendor_id=vendor_id,
        avps=(),
    )


def _row(name, code):
    return ast.AvpTableRow(
        name=name,
        code=code,
        section="6.3.1",
        data_type=ast.DataType.ENUMERATED,
        flag_rules=ast.AvpFlagRules(),
        may_encrypt=False,
    )


def _enum_section(number, name, document):
    """A section shaped like an enumerated-AVP clause. The paragraphs carry a
    real docx paragraph because that is what bold inspection reads."""
    paragraphs = [
        tgpp_docx._Para(
            text=text, style=style, source=document.add_paragraph(text, style=None)
        )
        for text, style in [
            (f"The {name} AVP is of type Enumerated.", ""),
            ("Off (0)", "B1"),
        ]
    ]
    return tgpp_docx._Section(number=number, title=name, paragraphs=paragraphs)


@pytest.fixture
def document():
    return docx.Document()


def test_resolve_gives_pending_enums_their_code_and_the_specs_vendor_id(document):
    collected = tgpp_docx._Collected(
        grouped=[_grouped()],
        pending_enums=[(_enum_section("6.3.2", "Mode", document), "Mode")],
        avp_tables=[_avp_table(_row("Mode", 11))],
    )

    resolved = tgpp_docx._resolve(collected)

    enumerated = resolved.definitions[1]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert (enumerated.name, enumerated.code, enumerated.vendor_id) == (
        "Mode",
        11,
        10415,
    )


def test_resolve_skips_enums_defined_in_another_specification(document):
    # DRMP reads like a local enumerated AVP but its values live in RFC 7944.
    collected = tgpp_docx._Collected(
        pending_enums=[(_enum_section("6.3.2", "DRMP", document), "DRMP")],
        avp_tables=[_avp_table(_row("DRMP", None))],
        reused_tables=[_reused_table(ast.ReusedAvpRow(name="DRMP", origin="RFC7944"))],
    )

    resolved = tgpp_docx._resolve(collected)

    assert resolved.definitions == []
    assert resolved.reused == [ast.ReusedAvpRow(name="DRMP", origin="RFC7944")]


def test_a_grouped_avp_is_kept_even_when_it_is_also_listed_as_re_used():
    # The asymmetry with the enum case above is deliberate. TS 29.272 §7.3.40
    # re-prints TS 29.212's Allocation-Retention-Priority in full while listing
    # it as re-used; the document printed a body, so the file records it. The
    # resulting local/re-used conflict is a real inconsistency in the source
    # and belongs in a linter report, not in a silent deletion here.
    reused = ast.ReusedAvpRow(name="Foreign", origin="TS29.212")
    collected = tgpp_docx._Collected(
        grouped=[_grouped(name="Foreign"), _grouped(name="Local")],
        avp_tables=[_avp_table(_row("Local", 1))],
        reused_tables=[_reused_table(reused)],
    )

    resolved = tgpp_docx._resolve(collected)

    assert [definition.name for definition in resolved.definitions] == [
        "Foreign",
        "Local",
    ]
    assert resolved.reused == [reused]


def test_resolve_rejects_an_enum_with_no_code_in_the_avp_table(document):
    collected = tgpp_docx._Collected(
        grouped=[_grouped()],
        pending_enums=[(_enum_section("6.3.2", "Mode", document), "Mode")],
        avp_tables=[_avp_table(_row("Other", 1))],
    )

    with pytest.raises(tgpp_docx.ExtractionError, match="has no code in the AVP table"):
        tgpp_docx._resolve(collected)


def test_resolve_rejects_a_document_with_two_avp_tables():
    # No collected spec does this; the point is that it can't pass silently,
    # which is what the old last-table-wins accumulator did.
    collected = tgpp_docx._Collected(
        avp_tables=[
            _avp_table(_row("One", 1), section="6.3"),
            _avp_table(_row("Two", 2), section="7.3"),
        ]
    )

    with pytest.raises(
        tgpp_docx.ExtractionError, match=r"more than one AVP table.*6\.3, 7\.3"
    ):
        tgpp_docx._resolve(collected)


def test_resolve_rejects_a_document_with_two_reused_tables():
    collected = tgpp_docx._Collected(
        avp_tables=[_avp_table(_row("One", 1))],
        reused_tables=[_reused_table(label="6.3.2"), _reused_table(label="7.4.1")],
    )

    with pytest.raises(tgpp_docx.ExtractionError, match="more than one re-used"):
        tgpp_docx._resolve(collected)


def test_reserved_notes_are_placed_by_value_not_by_document_order(document):
    # "Values 4 to 6 are reserved" is written wherever the editor felt like it;
    # the `.dad` value list is ordered by number.
    paragraphs = [
        ("The Mode AVP is of type Enumerated.", ""),
        ("Values 4 to 6 are reserved.", "NO"),
        ("Off (0)", "B1"),
        ("Value 2 is reserved.", "NO"),
        ("On (8)", "B1"),
    ]
    section = tgpp_docx._Section(
        number="6.3.2",
        title="Mode",
        paragraphs=[
            tgpp_docx._Para(
                text=text, style=style, source=document.add_paragraph(text, style=None)
            )
            for text, style in paragraphs
        ],
    )

    enumerated = tgpp_docx._extract_enumerated(section, "Mode", code=11, vendor_id=None)

    assert enumerated.values == (
        ast.EnumValue(name="Off", value=0),
        ast.ReservedValues(first=2, last=2),
        ast.ReservedValues(first=4, last=6),
        ast.EnumValue(name="On", value=8),
    )


def test_resolve_uses_the_3gpp_vendor_when_no_grouped_header_supplies_it(document):
    # TS 29.109 has local enumerated AVPs but no grouped definitions. The
    # publisher fixes their vendor space just as surely as a header would.
    collected = tgpp_docx._Collected(
        pending_enums=[(_enum_section("6.3.2", "Mode", document), "Mode")],
        avp_tables=[_avp_table(_row("Mode", 11))],
    )

    resolved = tgpp_docx._resolve(collected)

    enumerated = resolved.definitions[0]
    assert isinstance(enumerated, ast.EnumeratedAvp)
    assert enumerated.vendor_id == tgpp_docx.TGPP_VENDOR


def test_resolve_refuses_conflicting_enumerated_vendor_ids(document):
    # Two different explicit vendor ids cannot both be this document's
    # implicit vendor for enumerated definitions.
    collected = tgpp_docx._Collected(
        grouped=[_grouped(10415), _grouped(vendor_id=13019)],
        pending_enums=[(_enum_section("6.3.2", "Mode", document), "Mode")],
        avp_tables=[_avp_table(_row("Mode", 11))],
    )

    with pytest.raises(tgpp_docx.ExtractionError, match="cannot resolve the vendor id"):
        tgpp_docx._resolve(collected)


def test_resolve_does_not_need_a_vendor_id_when_there_is_no_local_enum():
    resolved = tgpp_docx._resolve(
        tgpp_docx._Collected(avp_tables=[_avp_table(_row("One", 1))])
    )

    assert resolved.definitions == []


def test_a_reused_table_keeps_its_own_clause_not_the_avp_tables():
    # The two tables sit under one parent clause in the current fixtures, which
    # is exactly what hid this.
    collected = tgpp_docx._Collected(
        avp_tables=[_avp_table(_row("One", 1), section="6.3")],
        reused_tables=[
            _reused_table(
                ast.ReusedAvpRow(name="Load", origin="RFC7683"),
                label="7.4/1",
                section="7.4",
            )
        ],
    )

    sections = tgpp_docx._assemble(tgpp_docx._resolve(collected))

    reused = next(s for s in sections if isinstance(s, ast.ReusedAvps))
    assert (reused.table, reused.source.section) == ("7.4/1", "7.4")


def test_note_derived_reused_rows_are_attributed_to_the_avp_table():
    # With no re-used table in the document, the rows really did come from the
    # AVP table's NOTEs, so that is where the block is recorded.
    collected = tgpp_docx._Collected(
        avp_tables=[_avp_table(_row("One", 1), section="6.3", table="6.3.1")],
        note_reused=[ast.ReusedAvpRow(name="One", origin="RFC7683")],
    )

    sections = tgpp_docx._assemble(tgpp_docx._resolve(collected))

    reused = next(s for s in sections if isinstance(s, ast.ReusedAvps))
    assert (reused.table, reused.source.section) == ("6.3.1", "6.3")


def test_resolve_requires_an_avp_table():
    with pytest.raises(tgpp_docx.ExtractionError, match="no AVP table found"):
        tgpp_docx._resolve(tgpp_docx._Collected())
