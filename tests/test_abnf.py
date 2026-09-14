"""The parser and the extractor read different dialects of the same ABNF: the
parser reads canonical `.dad` text, the extractor reads what Word gives it.
These tests pin the two to the same meaning — nothing else does, and a format
change otherwise needs two edits with no failing test if you forget one."""

import pytest

from seanchai.dad import abnf


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
