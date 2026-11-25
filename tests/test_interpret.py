"""Interpreted constraints: the block's grammar, the interpretations file
(`.dadx`) that writes it, its merge into a corrected file and the quote check
against the source document."""

import re
from pathlib import Path

import pytest
from conftest import _ROOT

from seanchai.dad import ast, corrections, formatter, interpretations, parser
from seanchai.dad.corrections import CorrectionError

_HEADER = "; Specification: 3GPP TS 29.999\n; Version: 19.0.0\n; Vendor-ID: 10415\n"


def _dad(*lines: str) -> str:
    return _HEADER + "\n\n" + "\n".join(lines) + "\n"


def _block(*body: str, scope: tuple[str, ...] = ()) -> str:
    return _dad(
        "; Type: Interpreted Constraints",
        "; AVP: Example",
        *scope,
        "; Section: 6.3.2",
        "; Versions: 19.0.0",
        *body,
    )


# Every kind and form, in canonical spelling.
_EVERY_RULE = _dad(
    "; Type: Interpreted Constraints",
    "; AVP: Context-Identifier",
    "; Command: Delete-Subscriber-Data-Request",
    "; Application-ID: 16777251",
    "; Command-Section: 7.2.27",
    "; Section: 5.2.2.2.1",
    "; Table: 5.2.2.2.1/1",
    "; Page: 43",
    "; Versions: 19.0.0..19.6.0",
    '"It shall be present only if the \\"X\\" bit is set."',
    '    requires DSR-Flags bit "PDN subscription contexts Withdrawal" or'
    " DSR-Flags bit 6",
    '"First." ;; two sentences, one reading',
    '"Second."',
    "    exclude 0, -1",
    "    range -1..*",
    "    range *..255",
    "    range 7",
    "    length 14..15 digits",
    "    length 3 octets",
    "    length 1..* characters",
    "    encoding plmn-id",
    '    encoding element TS24.008 10.5.5.32 "Extended DRX parameter"',
    "    encoding element TS29.002",
    '    present-if Result-Code = DIAMETER_SUCCESS or Mode = "a b" or Other',
    "    absent-if Emergency-Services bit Emergency-Indication",
    "    excludes Level = -1",
    "    default FALSE",
    "    default 0",
    "    bits at-most-one 3 6",
    "    bits at-least-one 0 1",
    "    bits set 1",
    "    bits clear 4 5 6 7",
    "    bits only 9",
    "    members at-least-one SCEF-Reference-ID SCEF-Reference-ID-Ext",
    "    members only IMEI",
    '    values 1, 2 if Monitoring-Type = UE_REACHABILITY or Flags bit "A b"',
    '"Third."',
    "    text-only",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Service-Selection",
    "; Within: APN-Configuration",
    "; Section: 7.3.35",
    "; Versions: 19.0.0",
    '"Unique."',
    "    unique",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Non-3GPP-User-Data",
    "; Command: Server-Assignment-Answer",
    "; Request-Section: 8.2.2.3",
    "; Section: 8.1.2.2.2.1",
    "; Versions: 19.0.0",
    '"As the request asked."',
    "    present-if request/Server-Assignment-Type = REGISTRATION",
    "    absent-if request/Emergency-Services bit Emergency-Indication",
    "    requires request/QoS-Capability or Result-Code = request/Result-Code",
    "    equals request/User-Name",
)


def test_every_rule_reads_and_writes_back():
    spec, comments = parser.parse_with_comments(_EVERY_RULE)

    block, unique_block, asked = spec.sections
    assert isinstance(asked, ast.InterpretedConstraints)
    assert asked.request_section == "8.2.2.3"
    present, _, requires, equals = asked.readings[0].rules
    assert present == ast.PredicateRule(
        kind=ast.PredicateKind.PRESENT_IF,
        conditions=(
            ast.Condition(
                root=ast.Root.REQUEST,
                path=("Server-Assignment-Type",),
                value="REGISTRATION",
            ),
        ),
    )
    assert isinstance(requires, ast.PredicateRule)
    assert requires.conditions[1].value == ast.Reference(
        root=ast.Root.REQUEST, path=("Result-Code",)
    )
    assert equals == ast.EqualsRule(
        reference=ast.Reference(root=ast.Root.REQUEST, path=("User-Name",))
    )
    assert all(ast.reads_request(rule) for rule in asked.readings[0].rules)
    assert isinstance(block, ast.InterpretedConstraints)
    assert isinstance(unique_block, ast.InterpretedConstraints)
    assert unique_block.body[1:] == (ast.UniqueRule(),)
    assert (block.command, block.application_id, block.command_section) == (
        "Delete-Subscriber-Data-Request",
        16777251,
        "7.2.27",
    )
    first, second, third = block.readings
    assert first.quotes == ('It shall be present only if the "X" bit is set.',)
    (rule,) = first.rules
    assert isinstance(rule, ast.PredicateRule)
    assert rule.kind is ast.PredicateKind.REQUIRES
    assert [condition.bit for condition in rule.conditions] == [
        "PDN subscription contexts Withdrawal",
        6,
    ]
    assert second.quotes == ("First.", "Second.")
    assert second.rules[1] == ast.RangeRule(low=-1, high=None)
    assert second.rules[3] == ast.RangeRule(low=7, high=7)
    assert second.rules[5] == ast.LengthRule(unit=ast.LengthUnit.OCTETS, low=3, high=3)
    assert second.rules[-10:] == (
        ast.DefaultRule(value="FALSE"),
        ast.DefaultRule(value=0),
        ast.BitsRule(relation=ast.BitsRelation.AT_MOST_ONE, bits=(3, 6)),
        ast.BitsRule(relation=ast.BitsRelation.AT_LEAST_ONE, bits=(0, 1)),
        ast.BitsRule(relation=ast.BitsRelation.SET, bits=(1,)),
        ast.BitsRule(relation=ast.BitsRelation.CLEAR, bits=(4, 5, 6, 7)),
        ast.BitsRule(relation=ast.BitsRelation.ONLY, bits=(9,)),
        ast.MembersRule(
            relation=ast.BitsRelation.AT_LEAST_ONE,
            members=("SCEF-Reference-ID", "SCEF-Reference-ID-Ext"),
        ),
        ast.MembersRule(relation=ast.BitsRelation.ONLY, members=("IMEI",)),
        ast.ValuesRule(
            values=(1, 2),
            conditions=(
                ast.Condition(path=("Monitoring-Type",), value="UE_REACHABILITY"),
                ast.Condition(path=("Flags",), bit="A b"),
            ),
        ),
    )
    assert third.rules == (ast.TextOnly(),)
    assert formatter.format_spec(spec, comments) == _EVERY_RULE


@pytest.mark.parametrize(
    ("text", "lineno", "fact"),
    [
        pytest.param(
            _block('"Q."', "    length 3 bytes"), 11, "unknown unit", id="unit"
        ),
        pytest.param(
            _block('"Q."', "    encoding tbcd"), 11, "unknown codec", id="codec"
        ),
        pytest.param(
            _block('"Q."', "    length 5..3 octets"), 11, "inverted", id="inverted"
        ),
        pytest.param(
            _block('"Q."', "    encoding plmn-id TS29.002"),
            11,
            "takes no document",
            id="codec-document",
        ),
        pytest.param(
            _block('"Q."', "    encoding element"),
            11,
            "names the document",
            id="element-document",
        ),
        pytest.param(
            _block('"Q."', "    requires X = 1 bit 2"),
            11,
            "malformed condition",
            id="value-and-bit",
        ),
        pytest.param(
            _block('"Q."', "    must-have X"), 11, "malformed rule", id="kind"
        ),
        pytest.param(
            _block('"Q."', "    bits exactly-one 1 2"),
            11,
            "unknown relation",
            id="bits-relation",
        ),
        pytest.param(
            _block('"Q."', "    bits at-most-one 2 2"),
            11,
            "names a bit twice",
            id="bits-twice",
        ),
        pytest.param(
            _block('"Q."', "    bits at-least-one 2"),
            11,
            "names two bits or more",
            id="bits-one",
        ),
        pytest.param(
            _block('"Q."', "    members set A B"),
            11,
            "unknown relation",
            id="members-relation",
        ),
        pytest.param(
            _block('"Q."', "    members only A A"),
            11,
            "names a member twice",
            id="members-twice",
        ),
        pytest.param(
            _block('"Q."', "    values 1 if"), 11, "malformed rule", id="values-bare"
        ),
        pytest.param(
            _block('"Q."', "    values 1, 1 if Mode = 2"),
            11,
            "names a value twice",
            id="values-twice",
        ),
        pytest.param(
            _block('"Q."', "    unique"),
            6,
            "unique holds among the grouped AVPs Within names",
            id="unique-unscoped",
        ),
        pytest.param(_block('"Q."', "length 3 octets"), 11, "indented", id="flush"),
        pytest.param(
            _block('"Q."', "    text-only", "    range 1"),
            6,
            "text-only is a reading's only rule",
            id="text-only-alone",
        ),
        pytest.param(
            _block("    range 1", '"Q."'), 6, "opens with the quote", id="rule-first"
        ),
        pytest.param(
            _block('"Q."', "    range 1", '"R."'), 6, "followed by", id="quote-last"
        ),
        pytest.param(
            _block('"Q."', "    range 1", scope=("; Application-ID: 1",)),
            6,
            "Application-ID",
            id="application-without-command",
        ),
        pytest.param(
            _block('"Q."', "    range 1", scope=("; Command-Section: 6.1.1",)),
            6,
            "Command-Section",
            id="command-section-without-command",
        ),
        pytest.param(
            _block(
                '"Q."',
                "    range 1",
                scope=("; Command: Example-Request", "; Within: Example-Group"),
            ),
            6,
            "a command or a grouped AVP",
            id="two-scopes",
        ),
        pytest.param(
            _dad(
                "; Type: Interpreted Constraints",
                "; AVP: Example",
                "; Section: 6.3.2",
                '"Q."',
                "    range 1",
            ),
            6,
            "missing directive 'Versions'",
            id="versions",
        ),
        pytest.param(
            _block(
                '"Q."',
                "    range 1",
                scope=("; Command: Example-Answer", "; Request-Section: 6.1.1"),
            ),
            6,
            "Request-Section names the request no rule reads",
            id="request-section-unread",
        ),
        pytest.param(
            _block(
                '"Q."',
                "    requires request/Example-Flags",
                scope=("; Within: Example-Group",),
            ),
            6,
            "reads the request in a block scoped to no answer",
            id="request-within",
        ),
        pytest.param(
            _block('"Q."', "    requires Example = Other/Flags"),
            11,
            "malformed condition",
            id="value-from-unrooted",
        ),
        pytest.param(
            _block('"Q."', "    equals"), 11, "malformed rule", id="equals-bare"
        ),
    ],
)
def test_a_malformed_block_is_refused_at_its_line(text, lineno, fact):
    with pytest.raises(parser.DadParseError) as error:
        parser.parse(text)

    assert error.value.lineno == lineno
    assert fact in str(error.value)


# --- the interpretations file ----------------------------------------------

_INTERPRETS = "; Interprets: 3GPP TS 29.999\n"


def _written(
    *body: str,
    id: str = "example-number-layout",
    avp: str = "Example-Number",
    section: str = "6.3.2",
    scope: tuple[str, ...] = (),
    versions: str = "19.0.0",
) -> str:
    """One block of an interpretations file, as a person writes it."""
    return "\n".join(
        (
            "; Type: Interpreted Constraints",
            f"; Id: {id}",
            f"; AVP: {avp}",
            *scope,
            f"; Section: {section}",
            f"; Versions: {versions}",
            *(body or ('"It is a number."', "    encoding e164-tbcd")),
        )
    )


def _dadx(*blocks: str) -> str:
    return _INTERPRETS + "".join(f"\n\n{block}\n" for block in blocks)


_FILE = (
    "; Interprets: 3GPP TS 29.999\n"
    ";; Read in clause order.\n"
    "\n"
    "\n"
    "; Type: Interpreted Constraints\n"
    "; Id: example-flags-in-request\n"
    "; AVP: Example-Number\n"
    "; Command: Example-Request\n"
    "; Application-ID: 99\n"
    "; Section: 6.1.1\n"
    "; Table: 6.1.1/1\n"
    "; Versions: 19.0.0 ;; widened by hand\n"
    '"Only with the flag."\n'
    "    requires Example-Flags bit 0\n"
    "\n"
    "\n"
    ";; The AVP's own clause.\n"
    "; Type: Interpreted Constraints\n"
    "; Id: example-number-layout\n"
    "; AVP: Example-Number\n"
    "; Section: 6.3.2\n"
    "; Versions: 18.0.0..19.0.0\n"
    '"It is a number."\n'
    "    encoding e164-tbcd\n"
)


def test_an_interpretations_file_reads_and_writes_back():
    tree, comments = parser.parse_interpretations_with_comments(_FILE)
    _, declared = interpretations.parse(_FILE, Path("TS29.999.dadx"))

    assert tree.interprets == "3GPP TS 29.999"
    assert [block.id for block in tree.sections] == [
        "example-flags-in-request",
        "example-number-layout",
    ]
    assert formatter.format_interpretations(tree, comments) == _FILE
    first, second = declared
    assert first.lines == (5, 13, 14)
    assert first.cited == "TS29.999.dadx#example-flags-in-request"
    assert first.at(0) == "TS29.999.dadx:13: example-flags-in-request"
    # The corrected file prints the block without its id.
    assert first.node == ast.InterpretedConstraints(
        avp="Example-Number",
        command="Example-Request",
        application_id=99,
        table="6.1.1/1",
        source=ast.SourceRef(section="6.1.1"),
        versions="19.0.0",
        body=(
            ast.Quote(text="Only with the flag."),
            ast.PredicateRule(
                kind=ast.PredicateKind.REQUIRES,
                conditions=(ast.Condition(path=("Example-Flags",), bit=0),),
            ),
        ),
    )
    assert "; Id:" not in formatter.format_spec(
        ast.Specification(
            specification="3GPP TS 29.999", vendor_id=10415, sections=(second.node,)
        )
    )


@pytest.mark.parametrize(
    ("text", "lineno", "fact"),
    [
        pytest.param(
            _dadx(_written()).replace("; Id: example-number-layout\n", ""),
            4,
            "missing directive 'Id'",
            id="no-id",
        ),
        pytest.param(
            _dadx(_written(id="Not_Kebab")), 5, "should match pattern", id="id"
        ),
        pytest.param(
            _dadx(_written(), _written(section="6.3.3")),
            14,
            "names the block at line 4 too",
            id="id-twice",
        ),
        pytest.param(
            _dadx(_written().replace("; Versions:", "; Page: 13\n; Versions:")),
            8,
            "a page is not written",
            id="page",
        ),
        pytest.param(
            _dadx(_written(), _written(id="earlier", section="6.3.1")),
            13,
            "clause 6.3.1 comes before clause 6.3.2",
            id="clause-order",
        ),
        pytest.param(
            _dadx(_written('"Q."')),
            4,
            "at least 2 items",
            id="nothing-read",
        ),
        pytest.param(
            _dadx(_written(scope=("; Application-ID: 1",))),
            4,
            "Application-ID",
            id="application-without-command",
        ),
        pytest.param(
            _dadx("; Type: Undefined AVP\n; Name: X\n; Section: 6.3.2"),
            4,
            "Interpreted Constraints blocks only",
            id="other-block",
        ),
        pytest.param(
            _dadx(_written()).replace("; Interprets:", "; Specification:"),
            1,
            "missing directive 'Interprets'",
            id="header",
        ),
        pytest.param(
            _dadx(_written()).replace("3GPP TS 29.999", "Nothing"),
            1,
            "does not name a supported document",
            id="document",
        ),
    ],
)
def test_a_malformed_interpretations_file_is_refused_at_its_line(text, lineno, fact):
    with pytest.raises(parser.DadParseError) as error:
        parser.parse_interpretations(text)

    assert error.value.lineno == lineno
    assert fact in str(error.value)


def test_a_document_reads_its_own_interpretations_file_and_no_other(tmp_path):
    (tmp_path / "TS29.999.dadx").write_text(_dadx(_written()), encoding="utf-8")
    (tmp_path / "TS29.998.dadx").write_text(_dadx(_written()), encoding="utf-8")

    (item,) = interpretations.load(tmp_path, "3GPP TS 29.999")
    assert item.cited == "TS29.999.dadx#example-number-layout"
    assert interpretations.load(tmp_path, "3GPP TS 29.997") == []
    assert interpretations.load(None, "3GPP TS 29.999") == []
    with pytest.raises(CorrectionError, match=r"interprets '3GPP TS 29\.999'"):
        interpretations.load(tmp_path, "3GPP TS 29.998")
    (tmp_path / "TS29.997.dadx").write_text("; Interprets: x\n", encoding="utf-8")
    with pytest.raises(CorrectionError, match=r"TS29\.997\.dadx: line 1:"):
        interpretations.load(tmp_path, "3GPP TS 29.997")


# --- the declaration ---------------------------------------------------------

_RAW = _dad(
    "; Type: Message",
    "; Name: Example-Request, EXR",
    "; Section: 6.1.1",
    "<Example-Request> ::= < Diameter Header: 9, REQ, 99 >",
    "        < Session-Id >",
    "        [ Example-Number ]",
    "        [ Example-Flags ]",
    "",
    "",
    "; Type: AVP Table",
    "; Section: 6.3.1",
    "; Columns: Name Code Section Type Must",
    "Example-Number 1 6.3.2 OctetString V",
    "Example-Flags 2 6.3.4 Unsigned32 V",
    "Example-Group 3 6.3.5 Grouped V",
    "",
    "",
    "; Type: Grouped AVP",
    "; Name: Example-Group",
    "; Section: 6.3.5",
    "Example-Group ::= < AVP header: 3 10415 >",
    "        [ Example-Number ]",
)


def _interpret(
    *body: str,
    path: Path | None = None,
    id: str = "example-number-layout",
    avp: str = "Example-Number",
    section: str = "6.3.2",
    scope: tuple[str, ...] = (),
    versions: str = "19.0.0",
) -> interpretations.Interpretation:
    """One block, as an interpretations file at `path` writes it."""
    text = _dadx(
        _written(*body, id=id, avp=avp, section=section, scope=scope, versions=versions)
    )
    _, (item,) = interpretations.parse(text, path)
    return item


def test_an_interpretation_applies_only_in_a_release_its_range_spans():
    """Release 18, which the correction's range spans, takes no Release 19
    interpretation; they are offered to it, and to Release 17 too, until one
    of the module's ranges spans the release."""
    correction = corrections.Correction(
        id="spelling",
        target=corrections.definition("Example-Number"),
        field="name",
        expect="Example-Numbr",
        replace="Example-Number",
        reason="typo",
        versions="18.0.0..19.0.0",
    )
    module = [correction, _interpret()]

    assert corrections.in_release(module, "19.0.0") == module
    assert corrections.in_release(module, "18.1.0") == [correction]
    assert corrections.offered(module, "18.1.0") == [_interpret()]
    assert corrections.offered(module, "17.0.0") == [_interpret()]
    assert corrections.offered(module, "19.0.0") == []
    widened = _interpret(id="reviewed", versions="18.1.0..19.0.0")
    assert corrections.offered([*module, widened], "18.1.0") == []
    assert corrections.in_release([*module, widened], "18.1.0") == [
        correction,
        widened,
    ]


def test_an_interpretation_stands_beside_the_clause_it_reads():
    spec, comments = parser.parse_with_comments(_RAW)
    declared = [
        _interpret(path=Path("TS29.999.dadx")),
        _interpret(
            '"Only with the flag."',
            "    requires Example-Flags bit 0",
            id="example-flags-in-request",
            scope=("; Command: Example-Request",),
            section="6.1.1",
        ),
        _interpret(
            '"Never zero."',
            "    text-only",
            id="example-number-in-group",
            scope=("; Within: Example-Group",),
            section="6.3.5",
        ),
    ]

    corrected, _, notes = corrections.apply_with_comments(spec, comments, declared)

    kinds = [(section.type, section.source.section) for section in corrected.sections]
    assert kinds == [
        ("Message", "6.1.1"),
        ("Interpreted Constraints", "6.1.1"),
        ("AVP Table", "6.3.1"),
        ("Interpreted Constraints", "6.3.2"),
        ("Grouped AVP", "6.3.5"),
        ("Interpreted Constraints", "6.3.5"),
    ]
    text = formatter.format_spec(corrected, notes)
    assert (
        "; Type: Interpreted Constraints ;; interpreted:"
        " (TS29.999.dadx#example-number-layout)"
    ) in text
    assert parser.parse(text) == corrected


@pytest.mark.parametrize(
    ("declared", "message"),
    [
        pytest.param(
            [_interpret(avp="Example-Missing")],
            "the file holds no AVP 'Example-Missing'",
            id="avp",
        ),
        pytest.param(
            [_interpret('"Q."', "    requires Example-Missing")],
            "the file holds no AVP 'Example-Missing'",
            id="condition",
        ),
        pytest.param(
            [_interpret(scope=("; Command: Example-Answer",))],
            "0 commands 'Example-Answer' match",
            id="command",
        ),
        pytest.param(
            [_interpret(avp="Example-Flags", scope=("; Within: Example-Group",))],
            "the body of Example-Group does not hold Example-Flags",
            id="member",
        ),
        pytest.param(
            [_interpret(), _interpret(id="again")],
            "already holds constraints on Example-Number",
            id="twice",
        ),
    ],
)
def test_an_interpretation_expects_what_it_names(declared, message):
    with pytest.raises(CorrectionError, match=message):
        corrections.apply(parser.parse(_RAW), declared)


# The command printed a second time under its one application, as TS 29.273
# prints Diameter-EAP-Request for STa and SWd.
_TWICE = _RAW + "\n".join(
    (
        "",
        "",
        "; Type: Message",
        "; Name: Example-Request, EXR",
        "; Section: 6.1.2",
        "<Example-Request> ::= < Diameter Header: 9, REQ, 99 >",
        "        < Session-Id >",
        "        [ Example-Flags ]",
        "",
    )
)


def test_an_interpretation_chooses_a_print_of_its_command_by_its_clause():
    chosen = _interpret(
        '"Only with the flag."',
        "    requires Example-Flags bit 0",
        id="example-number-in-first",
        scope=("; Command: Example-Request", "; Command-Section: 6.1.1"),
        section="6.1.1",
    )

    corrected, _ = corrections.apply(parser.parse(_TWICE), [chosen])

    (block,) = [
        section
        for section in corrected.sections
        if isinstance(section, ast.InterpretedConstraints)
    ]
    assert block.command_section == "6.1.1"
    for scope, message in (
        (("; Command: Example-Request",), "2 commands 'Example-Request' match"),
        (
            ("; Command: Example-Request", "; Command-Section: 6.1.2"),
            "the body of Example-Request does not hold Example-Number",
        ),
        (
            ("; Command: Example-Request", "; Command-Section: 6.1.3"),
            "0 commands 'Example-Request' match",
        ),
    ):
        with pytest.raises(CorrectionError, match=re.escape(message)):
            corrections.apply(
                parser.parse(_TWICE),
                [_interpret(id="example-number-in-request", scope=scope)],
            )


def test_a_quote_is_held_to_its_clause_and_its_page_read_from_the_copy():
    declared = [
        _interpret(
            '"It is  a\u00a0number."',
            '"Encoded as TBCD."',
            "    encoding e164-tbcd",
            path=Path("TS29.999.dadx"),
        )
    ]
    clauses = {
        "6.3.2": ["The AVP is of type OctetString. It is a number.", "Encoded as TBCD."]
    }

    interpretations.check_quotes(declared, clauses)
    with pytest.raises(
        CorrectionError,
        match=r"^TS29\.999\.dadx:10: example-number-layout: clause 6\.3\.2 does not"
        r" print 'Encoded as TBCD\.'$",
    ):
        interpretations.check_quotes(declared, {"6.3.2": ["It is a number."]})
    with pytest.raises(
        CorrectionError, match=r"^TS29\.999\.dadx:4: .* has no clause 6\.3\.2$"
    ):
        interpretations.check_quotes(declared, {})
    (item,) = declared
    assert interpretations.paged(item, {"6.3.2": 13}).node.source.page == 13
    assert interpretations.paged(item, {}).page is None
    assert interpretations.paged(item, None) is item


@pytest.mark.sources
def test_a_quote_the_document_does_not_print_fails_against_the_source():
    """The real document's clause, as the regenerate step reads it."""
    from seanchai.extractor import tgpp_docx

    texts = tgpp_docx.clause_texts(
        _ROOT / "specifications/3gpp/Rel-19/TS_29.272/29272-j60.docx",
        _ROOT / "edits/sources",
    )
    printed = _interpret(
        '"It may also include a 15th digit."',
        "    length 14..15 digits",
        avp="IMEI",
        section="7.3.4",
    )
    misread = _interpret(
        '"It may also include a 16th digit."',
        "    length 14..16 digits",
        avp="IMEI",
        section="7.3.4",
    )

    interpretations.check_quotes([printed], texts)
    with pytest.raises(CorrectionError, match="16th digit"):
        interpretations.check_quotes([misread], texts)


# --- the linter, the model and the dictionary ---------------------------------

_BROKEN = _dad(
    "; Type: Message",
    "; Name: Example-Request, EXR",
    "; Section: 6.1.1",
    "<Example-Request> ::= < Diameter Header: 9, REQ, 99 >",
    "        < Session-Id >",
    "        [ Example-Number ]",
    "        [ Example-Flags ]",
    "        [ Example-Mode ]",
    "        [ Example-Text ]",
    "",
    "",
    "; Type: AVP Table",
    "; Section: 6.3.1",
    "; Columns: Name Code Section Type Must",
    "Example-Number 1 6.3.2 OctetString V",
    "Example-Flags 2 6.3.4 Unsigned32 V",
    "Example-Mode 3 6.3.5 Enumerated V",
    "Example-Text 5 6.3.7 OctetString V",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Number",
    "; Section: 6.3.2",
    "; Versions: 19.0.0",
    '"Q."',
    "    range 0..5",
    "    encoding plmn-id",
    "    length 4 octets",
    "    encoding e164-tbcd",
    "",
    "",
    "; Type: Value Table",
    "; AVP: Example-Flags",
    "; Kind: bits",
    "; Section: 6.3.4",
    "Known = 0",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Flags",
    "; Command: Example-Request",
    "; Section: 6.3.4",
    "; Versions: 19.0.0",
    '"Q."',
    "    requires Example-Mode = NOPE or Example-Flags bit 40 or Example-Flags"
    " bit Unknown or Example-Number = 3 or Missing",
    "",
    "",
    "; Type: Enumerated AVP",
    "; Name: Example-Mode",
    "; Section: 6.3.5",
    "Example-Mode ::= < Enumerated AVP header: 3 10415 >",
    "        ON  = 0",
    "        OFF = 1",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Mode",
    "; Command: Other-Request",
    "; Section: 6.3.5",
    "; Versions: 19.0.0",
    '"Q."',
    "    range 2..3",
    "    exclude 2, 3",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Mode",
    "; Within: Example-Group",
    "; Section: 6.3.6",
    "; Versions: 19.0.0",
    '"Q."',
    "    length 4 characters",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Mode",
    "; Section: 6.3.5",
    "; Versions: 19.0.0",
    '"Q."',
    "    default MAYBE",
    "    bits at-most-one 1 2",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Flags",
    "; Section: 6.3.4",
    "; Versions: 19.0.0",
    '"Q."',
    "    bits at-least-one 0 7",
    "    default -1",
    "    bits set 0",
    "    bits clear 0",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Text",
    "; Command: Example-Request",
    "; Section: 6.3.7",
    "; Versions: 19.0.0",
    '"Q."',
    "    members only Example-Flags",
    "    values 300 if Example-Mode = ON",
    "",
    "",
    "; Type: Grouped AVP",
    "; Name: Example-Group",
    "; Section: 6.3.6",
    "Example-Group ::= < AVP header: 4 10415 >",
    "        [ Example-Mode ]",
    "",
    "",
    "; Type: Interpreted Constraints",
    "; AVP: Example-Group",
    "; Section: 6.3.6",
    "; Versions: 19.0.0",
    '"Q."',
    "    members at-least-one Example-Mode Example-Flags",
)


def test_the_linter_reports_what_cannot_hold():
    from seanchai import linter

    found = sorted(
        (finding.rule, finding.message)
        for finding in linter.lint(parser.parse(_BROKEN))
        if finding.rule.startswith("constraint-")
    )

    assert found == [
        (
            "constraint-avp-unknown",
            "Example-Flags in Example-Request: the file holds no AVP Missing",
        ),
        (
            "constraint-command-unknown",
            "Example-Mode in Other-Request: names command Other-Request, which"
            " the file does not print",
        ),
        (
            "constraint-contradiction",
            "Example-Flags in Example-Request: bit 0 is both set and clear",
        ),
        (
            "constraint-contradiction",
            "Example-Flags: bit 0 is both set and clear",
        ),
        (
            "constraint-contradiction",
            "Example-Mode in Other-Request: exclude leaves no value of the range",
        ),
        (
            "constraint-contradiction",
            "Example-Number: encodings e164-tbcd, plmn-id cannot both hold",
        ),
        (
            "constraint-contradiction",
            "Example-Number: the lengths in octets leave none",
        ),
        (
            "constraint-not-member",
            "Example-Group: a members rule names Example-Flags, which the body of"
            " Example-Group does not hold",
        ),
        (
            "constraint-type-mismatch",
            "Example-Flags in Example-Request: Example-Flags has no bit 40",
        ),
        (
            "constraint-type-mismatch",
            "Example-Flags in Example-Request: a condition tests a value of"
            " Example-Number, of type OctetString",
        ),
        (
            "constraint-type-mismatch",
            "Example-Flags: -1 is beyond what Unsigned32 holds",
        ),
        (
            "constraint-type-mismatch",
            "Example-Mode in Example-Group: a character length needs text, not"
            " Enumerated",
        ),
        (
            "constraint-type-mismatch",
            "Example-Mode: a bits rule needs an unsigned integer or an octet"
            " string, not Enumerated",
        ),
        (
            "constraint-type-mismatch",
            "Example-Number: a range needs an integer, not OctetString",
        ),
        (
            "constraint-type-mismatch",
            "Example-Text in Example-Request: a members rule needs a grouped"
            " AVP, not OctetString",
        ),
        (
            "constraint-type-mismatch",
            "Example-Text in Example-Request: a values rule needs an integer,"
            " not OctetString",
        ),
        (
            "constraint-value-unknown",
            "Example-Flags in Example-Request: Example-Flags names no bit 'Unknown'",
        ),
        (
            "constraint-value-unknown",
            "Example-Flags in Example-Request: Example-Mode names no value 'NOPE'",
        ),
        (
            "constraint-value-unknown",
            "Example-Flags: Example-Flags's bit table names no bit 7",
        ),
        (
            "constraint-value-unknown",
            "Example-Mode: Example-Mode names no value 'MAYBE'",
        ),
    ]


_ORIGIN = """\
; Specification: 3GPP TS 29.998
; Version: 19.0.0
; Vendor-ID: 10415


; Type: AVP Table
; Section: 6.3.1
; Columns: Name     Code   Section   Type          Must
Example-Number      1      6.3.2     OctetString   V
"""

_CITING = """\
; Specification: 3GPP TS 29.999
; Version: 19.0.0
; Vendor-ID: 10415


; Type: Message
; Name: Example-Request, EXR
; Section: 6.1.1
<Example-Request> ::= < Diameter Header: 9, REQ, 99 >
        < Session-Id >
        [ Example-Group ]
        [ Example-Number ]


; Type: Interpreted Constraints
; AVP: Example-Number
; Command: Example-Request
; Section: 6.1.1
; Versions: 19.0.0
"Only with a group."
    requires Example-Group


; Type: AVP Table
; Section: 6.3.1
; Columns: Name     Code   Section   Type     Must
Example-Group       2      6.3.3     Grouped  V


; Type: Reused AVPs
; Section: 6.3.1
; Columns: Name     From
Example-Number      TS29.998


; Type: Interpreted Constraints
; AVP: Example-Number
; Section: 6.3.2
; Versions: 19.0.0
"Three octets."
    length 3 octets


; Type: Grouped AVP
; Name: Example-Group
; Section: 6.3.3
Example-Group ::= < AVP header: 2 10415 >
        [ Example-Number ]


; Type: Interpreted Constraints
; AVP: Example-Number
; Within: Example-Group
; Section: 6.3.3
; Versions: 19.0.0
"Never zero."
    exclude 0
"""


def test_the_model_and_the_dictionary_carry_the_reading_documents_constraints(
    tmp_path,
):
    from seanchai import dictionary
    from seanchai.corpus import Corpus
    from seanchai.model import Grouped, HolePolicy, Model

    for name, text in (("29998-j00.dad", _ORIGIN), ("29999-j00.dad", _CITING)):
        (tmp_path / name).write_text(text, "utf-8")
    built = Model.build(Corpus.load(tmp_path), holes=HolePolicy.ANY)

    cited = built.resolve("TS29.999", "Example-Number")
    origin = built.resolve("TS29.998", "Example-Number")
    group = built.resolve("TS29.999", "Example-Group")
    (message,) = built.messages("TS29.999")
    assert cited is not None and origin is not None
    assert isinstance(group, Grouped)
    assert [each.rules for each in cited.constraints] == [
        (ast.LengthRule(unit=ast.LengthUnit.OCTETS, low=3, high=3),)
    ]
    assert all(each.interpreted for each in cited.constraints)
    assert origin.constraints == ()
    assert [each.within for each in group.member_constraints] == ["Example-Group"]
    assert [each.avp for each in message.constraints] == ["Example-Number"]
    assert len(built.constraints("TS29.999")) == 3

    output = dictionary.build(built, documents=["TS29.999"], application_ids=[99])
    (command,) = output.applications[0].commands
    (scoped,) = command.constraints
    assert (scoped.interpreted, scoped.avp_ids) == (True, ("10415:1",))
    assert scoped.readings[0].rules[0].kind == "requires"
    assert [(each.avp, each.within, each.avp_ids) for each in output.constraints] == [
        # TS 29.999's reading is TS 29.998's, so the one entry carries it.
        ("Example-Number", None, ("10415:1",)),
        ("Example-Number", "Example-Group", ("10415:2",)),
    ]


def test_the_linter_asks_a_command_printed_twice_for_its_clause():
    from seanchai import linter

    def found(*scope: str) -> list[str]:
        text = _TWICE + "\n".join(
            (
                "",
                "",
                "; Type: Interpreted Constraints",
                "; AVP: Example-Flags",
                *scope,
                "; Section: 6.3.4",
                "; Versions: 19.0.0",
                '"Q."',
                "    bits only 0",
                "",
            )
        )
        return [
            finding.message
            for finding in linter.lint(parser.parse(text))
            if finding.rule == "constraint-command-unknown"
        ]

    assert found("; Command: Example-Request") == [
        "Example-Flags in Example-Request: names command Example-Request, which"
        " the file prints at clauses 6.1.1, 6.1.2; Command-Section names one"
    ]
    assert found("; Command: Example-Request", "; Command-Section: 6.1.2") == []
    assert found("; Command: Example-Request", "; Command-Section: 6.1.3") == [
        "Example-Flags in Example-Request: names command Example-Request at"
        " clause 6.1.3, which the file does not print there"
    ]


_ASKED = _dad(
    "; Type: Message",
    "; Name: Example-Request, EXR",
    "; Section: 6.1.1",
    "<Example-Request> ::= < Diameter Header: 9, REQ, 99 >",
    "        < Session-Id >",
    "        [ Example-Flags ]",
    "        [ Example-Text ]",
    "",
    "",
    "; Type: Message",
    "; Name: Example-Answer, EXA",
    "; Section: 6.1.2",
    "<Example-Answer> ::= < Diameter Header: 9, 99 >",
    "        < Session-Id >",
    "        [ Example-Number ]",
    "        [ Example-Flags ]",
    "",
    "",
    "; Type: AVP Table",
    "; Section: 6.3.1",
    "; Columns: Name Code Section Type Must",
    "Example-Number 1 6.3.2 OctetString V",
    "Example-Flags 2 6.3.4 Unsigned32 V",
    "Example-Text 5 6.3.7 UTF8String V",
)


def _asked(*scope_and_rules: str, twice: bool = False) -> list[tuple[str, str]]:
    from seanchai import linter

    scope = [line for line in scope_and_rules if line.startswith(";")]
    rules = [line for line in scope_and_rules if not line.startswith(";")]
    again = (
        [
            "",
            "",
            "; Type: Message",
            "; Name: Example-Request, EXR",
            "; Section: 6.1.3",
            "<Example-Request> ::= < Diameter Header: 9, REQ, 99 >",
            "        < Session-Id >",
        ]
        if twice
        else []
    )
    text = _ASKED + "\n".join(
        (
            *again,
            "",
            "",
            "; Type: Interpreted Constraints",
            "; AVP: Example-Number",
            *scope,
            "; Section: 6.3.2",
            "; Versions: 19.0.0",
            '"Q."',
            *rules,
            "",
        )
    )
    return sorted(
        (finding.rule, finding.message)
        for finding in linter.lint(parser.parse(text))
        if finding.rule.startswith("constraint-")
    )


def test_the_linter_holds_a_rule_on_the_request_to_the_answers_request():
    answer = "; Command: Example-Answer"
    assert _asked(answer, "    requires request/Example-Flags bit 0") == []
    assert _asked(answer, "    equals request/Example-Text") == [
        (
            "constraint-type-mismatch",
            "Example-Number in Example-Answer: a rule compares Example-Number,"
            " of type OctetString, with Example-Text, of type UTF8String",
        )
    ]
    assert _asked(answer, "    requires request/Example-Number") == [
        (
            "constraint-not-member",
            "Example-Number in Example-Answer: a rule reads"
            " request/Example-Number, which the body of the request does not hold",
        )
    ]
    assert _asked(
        "; Command: Example-Request", "    requires request/Example-Flags"
    ) == [
        (
            "constraint-not-member",
            "Example-Number in Example-Request: the body of Example-Request does"
            " not hold Example-Number",
        ),
        (
            "constraint-request-unknown",
            "Example-Number in Example-Request: reads the request, but"
            " Example-Request is a request",
        ),
    ]
    assert _asked(answer, "    requires request/Example-Flags", twice=True) == [
        (
            "constraint-request-unknown",
            "Example-Number in Example-Answer: reads the request of"
            " Example-Answer, which the file prints at clauses 6.1.1, 6.1.3;"
            " Request-Section names one",
        )
    ]
    chosen = (answer, "; Request-Section: 6.1.1", "    requires request/Example-Flags")
    assert _asked(*chosen, twice=True) == []
    assert _asked(
        answer, "; Request-Section: 6.1.9", "    requires request/Example-Flags"
    ) == [
        (
            "constraint-request-unknown",
            "Example-Number in Example-Answer: reads the request, which"
            " Request-Section names at clause 6.1.9, where the file prints no"
            " request of Example-Answer",
        )
    ]


def test_the_model_resolves_the_request_an_answers_rules_read(tmp_path):
    from seanchai import dictionary
    from seanchai.corpus import Corpus
    from seanchai.model import HolePolicy, Model

    text = _ASKED + "\n".join(
        (
            "",
            "",
            "; Type: Interpreted Constraints",
            "; AVP: Example-Number",
            "; Command: Example-Answer",
            "; Section: 6.3.2",
            "; Versions: 19.0.0",
            '"Q."',
            "    present-if request/Example-Flags bit 0",
            "",
        )
    )
    (tmp_path / "29999-j00.dad").write_text(text, "utf-8")
    built = Model.build(Corpus.load(tmp_path), holes=HolePolicy.ANY)
    (constraint,) = built.constraints("TS29.999")
    assert constraint.request_section == "6.1.1"
    output = dictionary.build(built, documents=["TS29.999"], application_ids=[99])
    answer = next(c for c in output.applications[0].commands if not c.is_request)
    (scoped,) = answer.constraints
    assert scoped.request_section == "6.1.1"
    (condition,) = scoped.readings[0].rules[0].conditions
    assert (condition.root, condition.path, condition.bit) == (
        "request",
        ("Example-Flags",),
        0,
    )
