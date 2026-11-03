import pytest
from conftest import _corpus

from seanchai.dad import ast, formatter, parser


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


def _spec(*sections):
    return ast.Specification(
        specification="Test", version="1", vendor_id=10415, sections=sections
    )


def _boundary_specs():
    """Shapes absent from the committed corpus, pinned by the round-trip invariant."""
    source = ast.SourceRef(section="1")
    return {
        "empty-file": _spec(),
        "message-without-avps": _spec(
            ast.Message(
                name="Bare-Request",
                abbreviation="BR",
                source=source,
                command_code=0,
                flags=frozenset(),
                application_id=0,
                avps=(),
            )
        ),
        "every-command-flag": _spec(
            ast.Message(
                name="Full-Request",
                abbreviation="FULL",
                source=source,
                command_code=2**24 - 1,
                flags=frozenset(ast.CommandFlag),
                application_id=2**32 - 1,
                avps=(),
            )
        ),
        "occurrence-extremes": _spec(
            ast.GroupedAvp(
                name="Group",
                source=source,
                code=1,
                avps=(
                    ast.AvpRule(
                        name="Unbounded",
                        presence=ast.Presence.OPTIONAL,
                        min_occurs=0,
                        max_occurs=None,
                    ),
                    ast.AvpRule(
                        name="Wide",
                        presence=ast.Presence.FIXED,
                        min_occurs=2**32 - 1,
                        max_occurs=2**32 - 1,
                    ),
                    ast.AvpRule(name="Bold", presence=ast.Presence.REQUIRED, bold=True),
                    ast.AvpRule(
                        name="Struck",
                        presence=ast.Presence.OPTIONAL,
                        strikethrough=True,
                    ),
                    ast.AvpRule(
                        name="Both",
                        presence=ast.Presence.OPTIONAL,
                        bold=True,
                        strikethrough=True,
                    ),
                ),
            )
        ),
        "enum-description-and-range": _spec(
            ast.EnumeratedAvp(
                name="Mode",
                source=source,
                code=1,
                values=(
                    ast.EnumValue(name="Short", value=1, description="first"),
                    ast.ReservedValues(first=2, last=4),
                    ast.EnumValue(name="Long-Name", value=200),
                ),
            )
        ),
        "enum-vendor-specific": _spec(
            ast.EnumeratedAvp(
                name="Mode",
                source=source,
                code=1,
                values=(
                    ast.EnumValue(name="Short", value=1, description="first"),
                    ast.ReservedValues(first=2, last=99),
                    ast.VendorSpecificValues(
                        first=100, last=199, description="; Version: 9"
                    ),
                    ast.VendorSpecificValues(first=2**32 - 1, last=2**32 - 1),
                ),
            )
        ),
        "enum-with-only-reserved": _spec(
            ast.EnumeratedAvp(
                name="Mode",
                source=source,
                code=1,
                values=(ast.ReservedValues(first=0, last=2**32 - 1),),
            )
        ),
        # Inline free text at the edge of what the constraint allows: one
        # character, an internal run of spaces the formatter must not collapse,
        # and text shaped like a directive, which is only safe because it never
        # starts a line.
        "awkward-inline-text": ast.Specification(
            specification="X",
            version="1",
            vendor_id=10415,
            sections=(
                ast.EnumeratedAvp(
                    name="Mode",
                    source=source,
                    code=1,
                    values=(
                        ast.EnumValue(name="A", value=0, description="x"),
                        ast.EnumValue(name="B", value=1, description="two  spaces"),
                        ast.EnumValue(name="C", value=2, description="; Version: 9"),
                    ),
                ),
            ),
        ),
        "long-names": _spec(
            ast.AvpTable(
                table="1/1",
                columns=tuple(ast.AvpColumn),
                source=ast.SourceRef(section="1.2.3A", page=2**32 - 1),
                rows=(
                    ast.AvpTableRow(
                        name="A-Very-Long-Attribute-Name-3GPP-Style",
                        code=None,
                        section=None,
                        data_type=ast.DataType.OCTET_STRING,
                        # The widest flag cell the columns can hold; the four
                        # rules are disjoint, so every flag it names is in one.
                        flag_rules=ast.AvpFlagRules(must=frozenset(ast.AvpFlag)),
                        may_encrypt=True,
                    ),
                ),
            )
        ),
    }


@pytest.mark.parametrize("spec", _boundary_specs().values(), ids=_boundary_specs())
def test_formatting_is_idempotent_and_survives_a_round_trip(spec):
    once = formatter.format_spec(spec)

    assert parser.parse(once) == spec
    assert formatter.format_spec(parser.parse(once)) == once


class ExtendedMessage(ast.Message):
    extra: str = "lost"


_EXTENDED_MESSAGE = ExtendedMessage(
    name="Example-Request",
    abbreviation="EXR",
    source=ast.SourceRef(section="1"),
    command_code=1,
    flags=frozenset(),
    application_id=None,
    avps=(),
)


@pytest.mark.parametrize("section", [object(), _EXTENDED_MESSAGE])
def test_an_unregistered_section_type_fails_loudly(section):
    with pytest.raises(TypeError, match=f"no formatter for {type(section).__name__}"):
        formatter._format_section(section, ("sections", 0), formatter.Comments())


def test_a_standing_note_for_a_last_row_deletion_prints_after_the_rows():
    # With no sibling left to stand before, the note is keyed by the position
    # one past the last row and prints at the end of the table's lines —
    # where the deleted row stood.
    table = ast.ReusedAvps(
        table="6.4",
        source=ast.SourceRef(section="6.4"),
        rows=(ast.ReusedAvpRow(name="Load", origin="RFC8583"),),
    )
    spec = _spec(table)

    note = "deleted: re-used AVPs row 'Doomed' (f.py:9)"
    standing: formatter.Notes = {("sections", 0, "rows", 1): [note]}
    annotated = formatter.format_spec(spec, formatter.Comments(standing=standing))
    lines = annotated.splitlines()

    marker = lines.index(f";; {note}")
    assert lines[marker - 1].startswith("Load")
    assert marker == len(lines) - 1


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


def test_comments_are_keyed_by_the_path_of_their_line():
    _, (trailing, standing, detached) = parser.parse_with_comments(_COMMENTED)

    assert trailing[("sections", 0, "name")] == ["on a directive"]
    assert trailing[("sections", 0)] == ["on the header rule"]
    assert standing[("sections", 0, "avps", 0)] == ["before a rule"]
    assert standing[("sections", 0, "avps", 1)] == ["", "at the end;; of the section"]
    assert standing[()] == ["at the end of the header"]
    assert detached[()] == ["before the header"]
    assert detached[("sections", 1)] == ["one comment block", "and another, merged"]
    assert detached[("sections", 3)] == ["after the last section"]


def test_markers_share_one_column_with_bold_before_strikethrough():
    grouped = ast.GroupedAvp(
        name="Group",
        source=ast.SourceRef(section="1"),
        code=1,
        avps=(
            ast.AvpRule(name="Plain", presence=ast.Presence.REQUIRED),
            ast.AvpRule(
                name="Struck", presence=ast.Presence.OPTIONAL, strikethrough=True
            ),
            ast.AvpRule(
                name="Both",
                presence=ast.Presence.OPTIONAL,
                bold=True,
                strikethrough=True,
            ),
        ),
    )
    spec = ast.Specification(specification="Test", vendor_id=0, sections=(grouped,))

    assert formatter.format_spec(spec).splitlines()[-3:] == [
        "        { Plain }",
        "        [ Struck ] ; strikethrough",
        "        [ Both ]   ; bold ; strikethrough",
    ]


def test_a_commented_out_rule_lines_up_with_the_body():
    # TS 32.299 clause 6.4.2's CCR strikes `* [ Used-Service-Unit ]`.
    struck = ast.AvpRule(
        name="Used-Service-Unit",
        presence=ast.Presence.OPTIONAL,
        min_occurs=0,
        max_occurs=None,
        strikethrough=True,
    )
    body = [
        ast.AvpRule(name="Session-Id", presence=ast.Presence.FIXED),
        ast.AvpRule(name="Service-Information", presence=ast.Presence.OPTIONAL),
    ]

    note = formatter.commented_avp_rule(struck, body)

    assert f";; {note}" == ";;    * [ Used-Service-Unit ]   ; strikethrough"
    # Longer than the body, it ends its own line rather than overrun it.
    assert formatter.commented_avp_rule(struck, body[:1]) == (
        "   * [ Used-Service-Unit ] ; strikethrough"
    )


def test_a_label_wider_than_its_cells_widens_its_column():
    """Every label sits at its column's start: TS 29.212 table 5a.3.0.1's
    `Acc-Type` and `Applicability` are wider than any of their cells."""
    table = ast.AvpTable(
        table="5a.3.0.1",
        source=ast.SourceRef(section="5a.3.0"),
        columns=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.ACCESS_TYPES,
            ast.AvpColumn.APPLICABILITY,
        ),
        rows=(
            ast.AvpTableRow(
                name="QoS-Rule-Base-Name",
                marks={
                    ast.MarkColumn.ACCESS_TYPES: ("All",),
                    ast.MarkColumn.APPLICABILITY: ("Rel9",),
                },
            ),
            ast.AvpTableRow(name="QoS-Rule-Name"),
        ),
    )
    spec = ast.Specification(
        specification="3GPP TS 29.212", vendor_id=10415, sections=(table,)
    )

    lines = formatter.format_spec(spec).splitlines()[-3:]

    assert lines == [
        "; Columns: Name      Acc-Type   Applicability",
        "QoS-Rule-Base-Name   All        Rel9",
        'QoS-Rule-Name        ""         ""',
    ]


_VALUE_TABLE = """\
; Specification: 3GPP TS 29.999
; Version: 1.2.3
; Vendor-ID: 10415
;; a block of its own


; Type: Value Table
; AVP: Feature-List ;; the AVP
; Kind: features ;; the kind
; Feature-List-ID: 1 ;; the list
; Application: S6a/S6d ;; the application
; Section: 7.3.10.1
; Table: 7.3.10/1
;; before a row
SiFC         = 0  ; M ;; trailing
"SMS in MME" = 10 ; O
Bare         = 11
;; at the end


; Type: Value Table
; AVP: Result-Code
; Kind: result-codes
; Section: 7.1
DIAMETER_SUCCESS = 2001 ; 7.1.2
;; DIAMETER_UNNUMBERED (56x1) ; 7.1.3
ELECTION_LOST    = 4003
"""


def test_a_value_table_round_trips_exactly_with_its_comments():
    spec, comments = parser.parse_with_comments(_VALUE_TABLE)

    text = formatter.format_spec(spec, comments)

    assert text == _VALUE_TABLE
    assert parser.parse(text) == spec
    again, comments = parser.parse_with_comments(text)
    assert formatter.format_spec(again, comments) == text


def test_a_value_table_aligns_and_quotes_as_an_enum_body_does():
    spec = ast.Specification(
        specification="RFC 9999",
        vendor_id=0,
        sections=(
            ast.ValueTable(
                avp="Result-Code",
                kind=ast.ValueKind.RESULT_CODES,
                source=ast.SourceRef(section="7.1"),
                rows=(
                    ast.ValueRow(name="SHORT_NAME", value=1, section="7.1.1"),
                    ast.ValueRow(name='A "quoted" name', value=2001),
                ),
            ),
        ),
    )

    text = formatter.format_spec(spec)

    assert text.endswith(
        "; Section: 7.1\n"
        "SHORT_NAME          = 1    ; 7.1.1\n"
        '"A \\"quoted\\" name" = 2001\n'
    )
    assert parser.parse(text) == spec
