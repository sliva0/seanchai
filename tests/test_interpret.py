"""Interpreted constraints: the block's grammar, the `Interpret` declaration
that writes it, and the quote check against the source document."""

import pytest
from conftest import _ROOT

from seanchai.dad import ast, corrections, formatter, parser
from seanchai.dad.ast import Codec
from seanchai.dad.corrections import CorrectionError
from seanchai.dad.interpret import (
    Interpret,
    absent_if,
    bit,
    bits_at_least_one,
    bits_at_most_one,
    characters,
    default,
    digits,
    element,
    encoding,
    equals,
    exclude,
    excludes,
    octets,
    present_if,
    range_of,
    reading,
    requires,
    text_only,
)

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
    '"Third."',
    "    text-only",
)


def test_every_rule_reads_and_writes_back():
    spec, comments = parser.parse_with_comments(_EVERY_RULE)

    (block,) = spec.sections
    assert isinstance(block, ast.InterpretedConstraints)
    assert (block.command, block.application_id) == (
        "Delete-Subscriber-Data-Request",
        16777251,
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
    assert second.rules[-4:] == (
        ast.DefaultRule(value="FALSE"),
        ast.DefaultRule(value=0),
        ast.BitsRule(relation=ast.BitsRelation.AT_MOST_ONE, bits=(3, 6)),
        ast.BitsRule(relation=ast.BitsRelation.AT_LEAST_ONE, bits=(0, 1)),
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
    ],
)
def test_a_malformed_block_is_refused_at_its_line(text, lineno, fact):
    with pytest.raises(parser.DadParseError) as error:
        parser.parse(text)

    assert error.value.lineno == lineno
    assert fact in str(error.value)


def test_the_builders_spell_the_rules_the_file_prints():
    rules = [
        octets(3),
        octets(1, None),
        digits(14, 15),
        characters(None, 8),
        range_of(0, 255),
        exclude(0),
        encoding(Codec.E164_TBCD),
        element("TS23.003", "4.4", "Zone Code"),
        requires(equals("Non-IP-PDN-Type-Indicator", "TRUE")),
        present_if(bit("DSR-Flags", "Delete monitoring events")),
        absent_if("MIP6-Agent-Info"),
        excludes(equals("Level", 2), "Other"),
        default("NOT_RELAY_NODE"),
        bits_at_most_one(3, 6),
        bits_at_least_one(0, 1),
        text_only(),
    ]

    assert [formatter.constraint_rule(rule) for rule in rules] == [
        "length 3 octets",
        "length 1..* octets",
        "length 14..15 digits",
        "length *..8 characters",
        "range 0..255",
        "exclude 0",
        "encoding e164-tbcd",
        'encoding element TS23.003 4.4 "Zone Code"',
        "requires Non-IP-PDN-Type-Indicator = TRUE",
        'present-if DSR-Flags bit "Delete monitoring events"',
        "absent-if MIP6-Agent-Info",
        "excludes Level = 2 or Other",
        "default NOT_RELAY_NODE",
        "bits at-most-one 3 6",
        "bits at-least-one 0 1",
        "text-only",
    ]


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
    *,
    id: str = "example-number-layout",
    avp: str = "Example-Number",
    section: str = "6.3.2",
    page: int | None = None,
    readings: tuple[ast.Reading, ...] = (
        reading("It is a number.", encoding(Codec.E164_TBCD)),
    ),
    command: str | None = None,
    application_id: int | None = None,
    within: str | None = None,
    origin: str = "",
) -> Interpret:
    return Interpret(
        id=id,
        avp=avp,
        section=section,
        page=page,
        readings=readings,
        command=command,
        application_id=application_id,
        within=within,
        versions="19.0.0",
        origin=origin,
    )


def test_an_interpretation_stands_beside_the_clause_it_reads():
    spec, comments = parser.parse_with_comments(_RAW)
    declared = [
        _interpret(origin="TS29.999.py"),
        _interpret(
            id="example-flags-in-request",
            avp="Example-Number",
            command="Example-Request",
            section="6.1.1",
            readings=(
                reading("Only with the flag.", requires(bit("Example-Flags", 0))),
            ),
        ),
        _interpret(
            id="example-number-in-group",
            within="Example-Group",
            section="6.3.5",
            readings=(reading("Never zero.", text_only()),),
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
        " (TS29.999.py#example-number-layout)"
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
            [
                _interpret(
                    readings=(reading("Q.", requires("Example-Missing")),),
                )
            ],
            "the file holds no AVP 'Example-Missing'",
            id="condition",
        ),
        pytest.param(
            [_interpret(command="Example-Answer")],
            "0 commands 'Example-Answer' match",
            id="command",
        ),
        pytest.param(
            [_interpret(avp="Example-Flags", within="Example-Group")],
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


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        pytest.param({"id": "Not_Kebab"}, "kebab-case", id="id"),
        pytest.param({"readings": ()}, "reads something", id="nothing"),
        pytest.param({"application_id": 1}, "Application-ID", id="application"),
    ],
)
def test_an_interpretation_declared_wrongly_is_refused(fields, message):
    with pytest.raises(CorrectionError, match=message):
        _interpret(**fields)


def test_a_quote_is_held_to_its_clause_and_page():
    declared = [
        _interpret(
            page=12,
            readings=(
                reading(
                    ("It is  a\u00a0number.", "Encoded as TBCD."),
                    encoding(Codec.E164_TBCD),
                ),
            ),
        )
    ]
    clauses = {
        "6.3.2": ["The AVP is of type OctetString. It is a number.", "Encoded as TBCD."]
    }

    corrections.check_quotes(declared, clauses, {"6.3.2": 12})
    with pytest.raises(CorrectionError, match=r"does not print 'Encoded as TBCD\.'"):
        corrections.check_quotes(declared, {"6.3.2": ["It is a number."]})
    with pytest.raises(CorrectionError, match=r"is on page 13, not 12"):
        corrections.check_quotes(declared, clauses, {"6.3.2": 13})
    with pytest.raises(CorrectionError, match=r"has no clause 6\.3\.2"):
        corrections.check_quotes(declared, {})


@pytest.mark.sources
def test_a_quote_the_document_does_not_print_fails_against_the_source():
    """The real document's clause, as the regenerate step reads it."""
    from seanchai.extractor import tgpp_docx

    texts = tgpp_docx.clause_texts(
        _ROOT / "specifications/3gpp/Rel-19/TS_29.272/29272-j60.docx",
        _ROOT / "edits/sources",
    )
    printed = _interpret(
        avp="IMEI",
        section="7.3.4",
        readings=(reading("It may also include a 15th digit.", digits(14, 15)),),
    )
    misread = _interpret(
        avp="IMEI",
        section="7.3.4",
        readings=(reading("It may also include a 16th digit.", digits(14, 16)),),
    )

    corrections.check_quotes([printed], texts)
    with pytest.raises(CorrectionError, match="16th digit"):
        corrections.check_quotes([misread], texts)


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
    "",
    "",
    "; Type: AVP Table",
    "; Section: 6.3.1",
    "; Columns: Name Code Section Type Must",
    "Example-Number 1 6.3.2 OctetString V",
    "Example-Flags 2 6.3.4 Unsigned32 V",
    "Example-Mode 3 6.3.5 Enumerated V",
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
            "constraint-avp-unknown",
            "Example-Mode in Example-Group: the file holds no AVP Example-Group",
        ),
        (
            "constraint-command-unknown",
            "Example-Mode in Other-Request: names command Other-Request, which"
            " the file does not print",
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
            "Example-Mode: a bits rule needs an unsigned integer, not Enumerated",
        ),
        (
            "constraint-type-mismatch",
            "Example-Number: a range needs an integer, not OctetString",
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
    assert [each.rules for each in cited.constraints] == [(octets(3),)]
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
