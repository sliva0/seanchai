"""The parser and the extractor read different dialects of the same ABNF: the
parser reads canonical `.dad` text, the extractor reads what Word gives it.
These tests pin the two to the same meaning — nothing else does, and a format
change otherwise needs two edits with no failing test if you forget one."""

import pytest

from seanchai.dad import abnf, ast, parser
from seanchai.extractor import tgpp_docx


@pytest.mark.parametrize(
    ("canonical", "source"),
    [
        ("        < Session-Id >", "< Session-Id >"),
        ("        { Origin-Host }", "{Origin-Host}"),
        ("        [ Destination-Host ]", "[ Destination-Host ]"),
        ("      * [ Supported-Features ]", "*[ Supported-Features ]"),
        ("    1*2 { Public-Identity }", "1*2 { Public-Identity }"),
        ("     0* [ Load ]", "0*[ Load ]"),
        ("     *5 [ Proxy-Info ]", "*5 [ Proxy-Info ]"),
    ],
)
def test_both_dialects_read_an_avp_rule_the_same_way(canonical, source):
    from_dad = parser._avp_rules([(1, canonical)])[0]

    match = tgpp_docx._ABNF_LINE_RE.match(source)
    assert match is not None, f"extractor dialect rejected {source!r}"
    from_docx = abnf.avp_rule(match)

    assert from_dad == from_docx


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ("306, REQ, PXY, 16777217", (306, {"REQ", "PXY"}, 16777217)),
        ("8388638, REQ, PXY,", (8388638, {"REQ", "PXY"}, None)),
        ("272, REQ, PXY, ERR, 4", (272, {"REQ", "PXY", "ERR"}, 4)),
        ("280", (280, set(), None)),
    ],
)
def test_diameter_header_items_round_trip(items, expected):
    command_code, flags, application_id = abnf.diameter_header(items)

    assert (command_code, {flag.value for flag in flags}, application_id) == expected
    # The canonical spelling re-reads as itself; only the source dialect's
    # trailing-comma and spacing slack is lost.
    canonical = abnf.diameter_header_items(command_code, flags, application_id)
    assert abnf.diameter_header(canonical) == (command_code, flags, application_id)


def test_diameter_header_rejects_an_interior_empty_item():
    # The trailing comma of "8388638, REQ, PXY," is a real source-document
    # convention; `, ,` in the middle is not, and accepting it would let
    # canonical `.dad` parse text the formatter can never emit.
    with pytest.raises(abnf.AbnfError, match="empty item"):
        abnf.diameter_header("306, , REQ, 16777217")


def test_diameter_header_rejects_a_missing_command_code():
    with pytest.raises(abnf.AbnfError, match="needs a command code"):
        abnf.diameter_header("REQ, PXY, 4")


def test_diameter_header_rejects_unknown_flags():
    with pytest.raises(abnf.AbnfError, match="malformed Diameter flags"):
        abnf.diameter_header("306, REQ, XYZ, 4")


def test_avp_flags_round_trip_through_the_canonical_cell():
    flags = abnf.avp_flags("M, V")

    assert flags == {ast.AvpFlag.MANDATORY, ast.AvpFlag.VENDOR}
    assert abnf.avp_flags_cell(flags) == "M,V"
    assert abnf.avp_flags(abnf.avp_flags_cell(flags)) == flags
    assert abnf.avp_flags_cell(frozenset()) == "-"


@pytest.mark.parametrize(
    ("min_occurs", "max_occurs", "text"),
    [(1, 1, ""), (0, None, "*"), (1, 2, "1*2"), (0, 5, "*5"), (2, None, "2*")],
)
def test_occurrence_qualifiers_round_trip(min_occurs, max_occurs, text):
    assert abnf.qualifier(min_occurs, max_occurs) == text
    minimum, _, maximum = text.partition("*")
    if text:
        assert abnf.occurrences(minimum, maximum) == (min_occurs, max_occurs)
    else:
        assert abnf.occurrences(None, None) == (1, 1)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: abnf.diameter_header("306, REQ, REQ, 16777217"), "repeats REQ"),
        (lambda: abnf.diameter_header("306, REQ, PXY, PXY"), "repeats PXY"),
        (lambda: abnf.avp_flags("M,M"), "repeats M"),
        (lambda: abnf.avp_flags("M, V, M"), "repeats M"),
    ],
    ids=["header-req", "header-pxy", "cell-adjacent", "cell-separated"],
)
def test_a_flag_named_twice_is_rejected_rather_than_collapsed(call, message):
    # A frozenset would swallow the repeat, so the file would format back as
    # the single flag and silently disagree with the document. Failing sends
    # the fix through an input patch, where it is declared and reviewed.
    with pytest.raises(abnf.AbnfError, match=message):
        call()


def test_mismatched_brackets_are_rejected_by_the_shared_layer():
    match = tgpp_docx._ABNF_LINE_RE.match("< Session-Id ]")
    assert match is not None

    with pytest.raises(abnf.AbnfError, match="mismatched brackets"):
        abnf.avp_rule(match)
