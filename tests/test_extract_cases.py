"""Source-document conventions the extractor claims to handle.

Each of these is a case collected from a real 3GPP specification (see
docs/extractor.md); the synthetic docx is modified per test rather than
carrying every case at once, so the shared fixture stays readable.
"""

import docx
import pytest

from seanchai.dad import ast
from seanchai.extractor import tgpp_docx


def _paragraph(document, text):
    return next(p for p in document.paragraphs if p.text == text)


def _declare(tmp_path, toml: str):
    """A sources directory declaring `toml` for the synthetic TS 29.999."""
    sources = tmp_path / "sources"
    sources.mkdir(exist_ok=True)
    (sources / "TS29.999.toml").write_text(toml, encoding="utf-8")
    return sources


def test_extract_rejects_an_abnf_line_with_mixed_bold(tmp_path, synthetic_spec_docx):
    # Word splits a line into runs at arbitrary points, and 3GPP files really
    # do carry bold on the brackets but not the name. When the *name* runs
    # disagree with each other there is no honest answer, so it fails.
    malformed = tmp_path / "mixed-bold.docx"
    document = docx.Document(synthetic_spec_docx)
    rule = _paragraph(document, "* [ Local-AVP ]")
    rule.runs[0].text = "* [ Local-"
    tail = rule.add_run("AVP ]")
    tail.bold = False
    document.save(malformed)

    with pytest.raises(tgpp_docx.ExtractionError, match="mixed bold in ABNF line"):
        tgpp_docx.extract(malformed)


def test_extract_reads_two_abnfs_from_one_command_section(
    tmp_path, synthetic_spec_docx
):
    # TS 29.272 defines IDR/DSR/RSR once for S6a and once for S7a in a single
    # clause; both ABNFs are real messages differing only in application id.
    two_abnfs = tmp_path / "two-application-ids.docx"
    document = docx.Document(synthetic_spec_docx)
    boundary = _paragraph(document, "6.3\tAVP Definitions")
    boundary.insert_paragraph_before(
        "< Example-Request > ::= < Diameter Header: 321, REQ, PXY, 43 >"
    )
    boundary.insert_paragraph_before("< Session-Id >")
    document.save(two_abnfs)

    spec = tgpp_docx.extract(two_abnfs)

    messages = [s for s in spec.sections if isinstance(s, ast.Message)]
    assert [message.application_id for message in messages] == [42, 43]
    assert all(message.name == "Example-Request" for message in messages)
    assert all(message.source.section == "6.1" for message in messages)


def test_extract_turns_an_avp_table_note_into_a_reused_row(
    tmp_path, synthetic_spec_docx
):
    # A row whose code cell is a NOTE reference has no code of its own; when
    # the note names a defining RFC, that is where the AVP comes from.
    with_note = tmp_path / "note-reference.docx"
    document = docx.Document(synthetic_spec_docx)
    table = document.tables[1]
    row = table.add_row()
    for cell, value in zip(
        row.cells,
        ["Noted-AVP", "NOTE 1", "", "Unsigned32", "M", "", "", "V", "No"],
        strict=True,
    ):
        cell.text = value
    note_row = table.add_row()
    note_row.cells[0].merge(
        note_row.cells[8]
    ).text = "NOTE 1: The value of this attribute is defined in IETF RFC 6733"
    document.save(with_note)

    # Deriving a row from a note's prose is the `note-defined-in-rfc` quirk:
    # undeclared it is an error, declared it produces the re-used row.
    with pytest.raises(tgpp_docx.ExtractionError, match="note-defined-in-rfc"):
        tgpp_docx.extract(with_note)

    sources = _declare(
        tmp_path,
        '[[quirk]]\nname = "note-defined-in-rfc"\nreason = "RFC note"\n',
    )
    spec = tgpp_docx.extract(with_note, sources_dir=sources)

    table_section = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    noted = next(row for row in table_section.rows if row.name == "Noted-AVP")
    assert noted.code is None
    reused = next(s for s in spec.sections if isinstance(s, ast.ReusedAvps))
    assert ast.ReusedAvpRow(name="Noted-AVP", origin="RFC6733") in reused.rows


def test_dotted_flags_cells_are_read_only_when_declared(
    tmp_path, synthetic_spec_docx
):
    # TS 29.061 and 29.212 write "M.V" — the space-less period is those
    # documents' separator convention; anywhere undeclared it is refused.
    dotted = tmp_path / "dotted-flags.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[1].cell(2, 4).text = "M.V"
    document.save(dotted)

    with pytest.raises(tgpp_docx.ExtractionError, match="dotted-flags"):
        tgpp_docx.extract(dotted)

    sources = _declare(
        tmp_path, '[[quirk]]\nname = "dotted-flags"\nreason = "M.V cells"\n'
    )
    spec = tgpp_docx.extract(dotted, sources_dir=sources)
    table = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    assert table.rows[0].flag_rules.must == {
        ast.AvpFlag.MANDATORY,
        ast.AvpFlag.VENDOR,
    }


def test_clause_parentheticals_are_stripped_only_when_declared(
    tmp_path, synthetic_spec_docx
):
    # TS 29.061 annotates clause cells as "16.4.7 (see Note)". A clause
    # number has no syntax for parentheses, so the tail is prose — but
    # dropping it is declared, not assumed.
    annotated = tmp_path / "clause-note.docx"
    document = docx.Document(synthetic_spec_docx)
    document.tables[1].cell(2, 2).text = "6.3.1 (see Note)"
    document.save(annotated)

    with pytest.raises(tgpp_docx.ExtractionError, match="clause-parenthetical"):
        tgpp_docx.extract(annotated)

    sources = _declare(
        tmp_path,
        '[[quirk]]\nname = "clause-parenthetical"\nreason = "see-note tails"\n',
    )
    spec = tgpp_docx.extract(annotated, sources_dir=sources)
    table = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    assert table.rows[0].section == "6.3.1"


@pytest.mark.parametrize(
    "label",
    ["6.3.1/1", "6.3.1-1", "B.1.1", "9A.2.1.1.1/1", "2a.1.1.1"],
    ids=["slash", "hyphen", "annex", "upper-letter", "lower-letter"],
)
def test_extract_accepts_every_table_numbering_style_3gpp_uses(
    tmp_path, synthetic_spec_docx, label
):
    # 3GPP numbers tables at least five ways and the corpus contains all of
    # them: the slash form is 29.229's and 29.272's, the hyphen form is what
    # 29.172, 29.283, 29.388 and 29.389 use, and the rest turn up in annexes.
    # A caption the extractor does not recognise is not a cosmetic loss — the
    # table it introduces is rejected outright for having no caption.
    renumbered = tmp_path / "caption.docx"
    document = docx.Document(synthetic_spec_docx)
    _paragraph(
        document, "Table 6.3.1: AVP definitions"
    ).text = f"Table {label}: AVP definitions"
    document.save(renumbered)

    spec = tgpp_docx.extract(renumbered)

    table = next(s for s in spec.sections if isinstance(s, ast.AvpTable))
    assert table.table == label


def test_extract_rejects_an_avp_table_whose_caption_it_cannot_read(
    tmp_path, synthetic_spec_docx
):
    """The caption is where `; Table:` comes from, and a table with no label a
    reader can look up is worse than no extraction at all."""
    uncaptioned = tmp_path / "uncaptioned.docx"
    document = docx.Document(synthetic_spec_docx)
    _paragraph(document, "Table 6.3.1: AVP definitions").text = "Table  : definitions"
    document.save(uncaptioned)

    with pytest.raises(tgpp_docx.ExtractionError, match="AVP table without a caption"):
        tgpp_docx.extract(uncaptioned)


def test_sources_file_name_matches_the_dad_spec_reference():
    assert tgpp_docx.sources_file_name("3GPP TS 29.272") == "TS29.272.toml"
