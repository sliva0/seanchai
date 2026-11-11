"""The parser and the extractor read different dialects of the same ABNF: the
parser reads canonical `.dad` text, the extractor reads what Word gives it.
These tests pin the source dialect to the canonical meaning; the corpus pins
the canonical spelling."""

import pytest

from seanchai.dad import abnf


def test_a_source_header_s_trailing_comma_reads_as_its_canonical_spelling():
    # TS 29.272's VCSG commands print "8388638, REQ, PXY," with no id.
    command_code, flags, application_id = abnf.diameter_header("8388638, REQ, PXY,")

    assert abnf.diameter_header_items(command_code, flags, application_id) == (
        "8388638, REQ, PXY"
    )


@pytest.mark.parametrize(
    ("call", "message"),
    [
        # Accepting `, ,` would let `.dad` text parse that the formatter
        # never writes.
        (lambda: abnf.diameter_header("306, , REQ, 16777217"), "empty item"),
        (lambda: abnf.diameter_header("REQ, PXY, 4"), "needs a command code"),
        (lambda: abnf.diameter_header("306, REQ, XYZ, 4"), "malformed Diameter flags"),
        # A frozenset would swallow a repeat, and the file would silently
        # disagree with the document; an input patch is where the fix goes.
        (lambda: abnf.diameter_header("306, REQ, REQ, 16777217"), "repeats REQ"),
        (lambda: abnf.avp_flags("M, V, M"), "repeats M"),
    ],
    ids=["empty-item", "no-code", "unknown-flag", "header-repeat", "cell-repeat"],
)
def test_a_malformed_header_or_flag_cell_is_refused(call, message):
    with pytest.raises(abnf.AbnfError, match=message):
        call()
