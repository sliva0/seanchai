"""Every committed file is canonical, and a hand-edited file's comments
survive formatting."""

import pytest
from conftest import _corpus

from seanchai.dad import formatter, parser


@pytest.mark.parametrize(
    "path", _corpus(raw=True) + _corpus(raw=False), ids=lambda path: path.name
)
def test_every_committed_dad_file_round_trips_exactly(path):
    """A corrected file is canonical output *plus* `;;` notes, which the parser
    discards — so the invariant is against the file with its notes stripped."""
    text = path.read_text()
    # A deleted section's note is a block of its own, so blocks left with
    # nothing but notes go entirely; a trailing note leaves its line.
    blocks = []
    for block in text.split("\n\n\n"):
        lines = [
            line.split(" ;; ")[0]
            for line in block.splitlines()
            if not line.lstrip().startswith(";;")
        ]
        if lines:
            blocks.append("\n".join(lines))
    canonical = "\n\n\n".join(blocks).rstrip("\n") + "\n"
    spec = parser.parse(text)

    assert formatter.format_spec(spec) == canonical
    assert parser.parse(formatter.format_spec(spec)) == spec


# Comments in every place a hand-edited file can put them, and the canonical
# form `format` writes them back in: each stays on or before the line it was
# on or before, while indentation, column alignment and the spacing of
# comment blocks are the formatter's.
_COMMENTED = """\
;; before the header

; Specification: X ;; on a header line
;; before a header line
; Version: 1
; Vendor-ID: 10415
;; at the end of the header


;; glued to the next section
; Type: Message
; Name: A-Request, AR ;; on a directive
; Section: 1
;; before the header rule
<A-Request> ::= < Diameter Header: 1, REQ, 2 > ;; on the header rule
    ;; before a rule
        { X } ;;tight
;;
;; at the end;; of the section


;; one comment block

;; and another, merged

; Type: Enumerated AVP
; Name: E
; Section: 2
E ::= < Enumerated AVP header: 5 >
  A = 1 ; description ;; on a value
;; at the end of the values


; Type: AVP Table
; Section: 3
;; before the columns
; Columns: Name Code
X 1

;; after the last section
"""

_COMMENTED_CANONICAL = """\
;; before the header


; Specification: X ;; on a header line
;; before a header line
; Version: 1
; Vendor-ID: 10415
;; at the end of the header


;; glued to the next section
; Type: Message
; Name: A-Request, AR ;; on a directive
; Section: 1
;; before the header rule
<A-Request> ::= < Diameter Header: 1, REQ, 2 > ;; on the header rule
;; before a rule
        { X } ;; tight
;;
;; at the end;; of the section


;; one comment block
;; and another, merged


; Type: Enumerated AVP
; Name: E
; Section: 2
E ::= < Enumerated AVP header: 5 >
        A = 1 ; description ;; on a value
        ;; at the end of the values


; Type: AVP Table
; Section: 3
;; before the columns
; Columns: Name   Code
X                 1


;; after the last section
"""


def test_comments_are_written_back_where_they_stood():
    spec, comments = parser.parse_with_comments(_COMMENTED)

    assert spec == parser.parse(_COMMENTED)
    assert formatter.format_spec(spec, comments) == _COMMENTED_CANONICAL
    spec, comments = parser.parse_with_comments(_COMMENTED_CANONICAL)
    assert formatter.format_spec(spec, comments) == _COMMENTED_CANONICAL
