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
            source=ast.SourceRef(section=section),
            rows=tuple(rows),
        ),
        section,
    )


def _row(name, code):
    return ast.AvpTableRow(
        name=name,
        code=code,
        section="6.3.1",
        data_type="Enumerated",
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
        grouped=[
            ast.GroupedAvp(
                name="Group",
                source=ast.SourceRef(section="6.3.1"),
                code=10,
                vendor_id=10415,
                avps=(),
            )
        ],
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
        reused_tables=[([ast.ReusedAvpRow(name="DRMP", origin="RFC7944")], "6.3.2")],
    )

    resolved = tgpp_docx._resolve(collected)

    assert resolved.definitions == []
    assert resolved.reused == [ast.ReusedAvpRow(name="DRMP", origin="RFC7944")]


def test_resolve_rejects_an_enum_with_no_code_in_the_avp_table(document):
    collected = tgpp_docx._Collected(
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
        reused_tables=[([], "6.3.2"), ([], "7.4.1")],
    )

    with pytest.raises(tgpp_docx.ExtractionError, match="more than one re-used"):
        tgpp_docx._resolve(collected)


def test_resolve_requires_an_avp_table():
    with pytest.raises(tgpp_docx.ExtractionError, match="no AVP table found"):
        tgpp_docx._resolve(tgpp_docx._Collected())
