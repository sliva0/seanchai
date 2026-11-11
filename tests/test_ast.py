"""The semantic constraints docs/grammar.md lists, which the model enforces
for every producer: the parser, the extractors and the corrections."""

import pydantic
import pytest

from seanchai.dad import ast

_SOURCE = ast.SourceRef(section="6.3")
_V = frozenset({ast.AvpFlag.VENDOR})


def _table(*columns, row):
    return ast.AvpTable(columns=columns, source=_SOURCE, rows=(row,))


def _values(kind, *rows, **fields):
    return ast.ValueTable(avp="A", kind=kind, source=_SOURCE, rows=rows, **fields)


@pytest.mark.parametrize(
    ("build", "fact"),
    [
        (lambda: ast.ReservedValues(first=5, last=2), "reserved range 5-2 is inverted"),
        (lambda: ast.VoidValues(first=5, last=2), "void range 5-2 is inverted"),
        (
            lambda: ast.VendorSpecificValues(first=5, last=2),
            "vendor-specific range 5-2 is inverted",
        ),
        (
            lambda: ast.AvpRule(
                name="A", presence=ast.Presence.OPTIONAL, min_occurs=5, max_occurs=2
            ),
            "5*2 is inverted",
        ),
        (
            lambda: ast.RegistryReservation(first=9, last=1),
            "reserved range 9..1 is inverted",
        ),
        (lambda: ast.AvpFlagRules(must=_V, must_not=_V), "both must and must_not"),
        (
            lambda: ast.ApplicationScope(
                name="Gx", source=_SOURCE, application_id=1, applies_to=("5.*", "5.*")
            ),
            "names a clause twice",
        ),
        # A quoted data type is that type, so it has one spelling.
        (
            lambda: ast.AvpTableRow(name="A", printed_type="Grouped"),
            "naming no Diameter",
        ),
        (
            lambda: _table(ast.AvpColumn.NAME, row=ast.AvpTableRow(name="A", code=1)),
            "no Code column",
        ),
        (
            lambda: _table(ast.AvpColumn.CODE, row=ast.AvpTableRow(name="A", code=1)),
            "no Name column",
        ),
        (
            lambda: _table(
                ast.AvpColumn.NAME, ast.AvpColumn.NAME, row=ast.AvpTableRow(name="A")
            ),
            "duplicate column",
        ),
        (
            lambda: _table(
                ast.AvpColumn.NAME,
                row=ast.AvpTableRow(name="A", printed_type="Integer"),
            ),
            "no Type column",
        ),
        (
            lambda: ast.AvpTableRow(
                name="A", marks={ast.MarkColumn.APPLICABILITY: ("-",)}
            ),
            "printed dash",
        ),
        (
            lambda: _values(
                ast.ValueKind.BITS, ast.ValueRow(name="A", value=0), application="X"
            ),
            "features table's",
        ),
        (
            lambda: _values(
                ast.ValueKind.BITS, ast.ValueRow(name="A", value=0, origin="TS29.229")
            ),
            "result code's",
        ),
        (lambda: _values(ast.ValueKind.BITS), "at least 1 item"),
        (
            lambda: ast.UndefinedAvp(name="AVP", source=_SOURCE),
            "wildcard",
        ),
        (
            lambda: ast.Message(
                name="A",
                abbreviation="AR",
                source=_SOURCE,
                command_code=2**24,
                flags=frozenset(),
                application_id=None,
                avps=(),
            ),
            "less than 16777216",
        ),
        # A line-oriented format: a newline would inject a second directive,
        # and padding would write trailing whitespace the parser refuses.
        (
            lambda: ast.Specification(
                specification="TS\n; Vendor-ID: 0", vendor_id=0, sections=()
            ),
            "String should match pattern",
        ),
        (lambda: ast.EnumValue(name=" Padded", value=0), "should match pattern"),
        (lambda: ast.EnumValue(name="A", value=0, description="a ;; b"), "comment"),
    ],
)
def test_the_model_refuses_what_the_grammar_forbids(build, fact):
    with pytest.raises(pydantic.ValidationError, match=fact):
        build()
