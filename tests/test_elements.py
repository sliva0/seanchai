"""The element registry (`seanchai.elements`): every `encoding element` rule
of the interpretations files names an entry, every entry is named, each
entry's example holds and each payload made to break it does not, and the
Wireshark plugin's `core.lua` says of each payload what Python says, under
every Lua on PATH."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import _ROOT

from seanchai import constraints, elements, linter, wireshark
from seanchai.dad import ast, parser
from seanchai.dad.ast import DataType
from seanchai.wireshark import _rules

CORE = Path(wireshark.__file__).parent / "core.lua"
LUAS = [name for name in ("lua5.1", "lua5.2", "lua5.3", "lua5.4") if shutil.which(name)]
INTERPRETATIONS = _ROOT / "edits" / "interpretations"


def _named() -> list[tuple[str, ast.EncodingRule]]:
    """Each `encoding element` rule of the interpretations files, with the
    AVP its block reads."""
    found = []
    for path in sorted(INTERPRETATIONS.glob("*.dadx")):
        tree, _ = parser.parse_interpretations(path.read_text("utf-8"))
        for block in tree.sections:
            for rule in block.body:
                if (
                    isinstance(rule, ast.EncodingRule)
                    and rule.codec is ast.Codec.ELEMENT
                ):
                    found.append((block.avp, rule))
    return found


def test_every_element_a_rule_names_is_registered():
    missing = [
        f"{avp}: {rule.document} {rule.clause} {rule.element}"
        for avp, rule in _named()
        if elements.of_rule(rule) is None
    ]

    assert missing == []


def test_every_registered_element_is_named_by_a_rule():
    named = {elements.of_rule(rule) for _, rule in _named()}

    assert [each.cited() for each in elements.REGISTRY if each not in named] == []


def test_every_entry_cites_what_it_read_and_says_what_it_leaves():
    for entry in elements.REGISTRY:
        assert entry.sources, entry.cited()
        assert all(source.edition and source.where for source in entry.sources)
        # An entry checking less than the whole layout says why; one checking
        # nothing in full says every value is valid, and only such a one.
        if entry.depth is not elements.Depth.FULL:
            assert entry.unchecked, entry.cited()
        assert (entry.valid is not None) == (
            entry.depth is elements.Depth.FULL and not entry.checks
        ), entry.cited()


def _type_of(entry: elements.Element) -> DataType:
    if entry.integer:
        low = next(
            shape.low for shape in entry.checks if isinstance(shape, elements.Integer)
        )
        return DataType.INTEGER32 if (low or 0) < 0 else DataType.UNSIGNED32
    if entry.text:
        return DataType.UTF8_STRING
    return DataType.OCTET_STRING


def _cases() -> list[tuple[elements.Element, bytes, DataType, bool]]:
    """Each checking entry's sample, which holds, and each payload breaking
    it, which does not."""
    cases = []
    for entry in elements.REGISTRY:
        if not entry.checks:
            continue
        data_type = _type_of(entry)
        good = elements.sample(entry, data_type)
        assert good is not None, entry.cited()
        cases.append((entry, good, data_type, True))
        broken = elements.breaking(entry, good, data_type)
        assert broken, entry.cited()
        cases += [(entry, each, data_type, False) for each in broken]
    return cases


CASES = _cases()


@pytest.mark.parametrize(
    ("entry", "payload", "data_type", "holds"),
    [pytest.param(*case, id=f"{case[0].cited()}-{case[1].hex()}") for case in CASES],
)
def test_each_entry_holds_of_its_sample_and_not_of_a_breach(
    entry, payload, data_type, holds
):
    assert (elements.problem(entry, payload, data_type) is None) is holds


@pytest.mark.parametrize(
    ("payload", "data_type", "reason"),
    [
        (b"\x21\xf3\x54\x00\x00\x00\x01", DataType.OCTET_STRING, None),
        (b"\x21\xf3\x54\x00\x00\x00", DataType.OCTET_STRING, "6 octets, not 7"),
        (
            b"\x21\xfa\x54\x00\x00\x00\x01",
            DataType.OCTET_STRING,
            "PLMN identity: an MCC or MNC digit is no decimal digit",
        ),
    ],
)
def test_check_reads_an_element_as_the_registry_does(payload, data_type, reason):
    rule = ast.EncodingRule(
        codec=ast.Codec.ELEMENT,
        document="TS29.002",
        clause="17.7.8",
        element="E-UTRAN-CGI",
    )

    found = constraints.check(rule, payload, data_type)

    assert found == constraints.Check(reason is None, reason)


@pytest.mark.parametrize(
    ("document", "clause", "name"),
    [
        ("TS23.501", None, "5QI"),  # registered, checking nothing
        ("TS29.999", "1.2", "Nowhere"),  # not registered
    ],
)
def test_check_cannot_tell_an_element_it_does_not_check(document, clause, name):
    rule = ast.EncodingRule(
        codec=ast.Codec.ELEMENT, document=document, clause=clause, element=name
    )

    assert constraints.check(rule, b"\x00", DataType.OCTET_STRING).holds is None


@pytest.mark.parametrize(
    ("entry", "payload", "problem"),
    [
        (
            "GeographicalInformation",
            "3000000100000105",
            "octet 1 bits 8-5 (type of shape) 0011, not 0001",
        ),
        (
            "GeodeticInformation",
            "0381000001000001057f",
            "octet 10 bits 7-1 (confidence) 1111111, not 0 to 100",
        ),
        (
            "PDP-Type",
            "f18d",
            "octet 1 bit 4 to octet 2 bit 1 (PDP type organisation and number)"
            " 0x18d, not PPP (0x001), Non-IP (0x002), IPv4 (0x121) or IPv6"
            " (0x157)",
        ),
        ("AddressString", "912143f5f6", "octet 4: '1111' filler before the last digit"),
        (
            "Measurement Quantity",
            "05",
            "bits 3 and 1 of octet 1 set, at most one may be",
        ),
        (
            "SS-Code",
            "1a",
            "octet 1 (SS-Code) 00011010, not a code clause 17.7.5 defines",
        ),
    ],
)
def test_a_problem_says_where_the_layout_breaks(entry, payload, problem):
    found = next(each for each in elements.REGISTRY if each.name == entry)

    assert elements.problem(found, bytes.fromhex(payload)) == problem


def test_an_fqdn_reads_its_templates_in_any_case():
    entry = elements.lookup("TS23.003", "19.4.2", "MME or SGSN node FQDN")
    assert entry is not None

    for text in (
        "mmec0A.mmegi8001.mme.epc.mnc015.mcc234.3gppnetwork.org",
        "NRI-SGSN0001.RAC00FF.LAC1234.RAC.EPC.MNC015.MCC234.3GPPNETWORK.ORG",
    ):
        assert elements.problem(entry, text.encode()) is None
    for text in (
        "mmec0A.mmegi8001.mme.epc.mnc15.mcc234.3gppnetwork.org",
        "mme1.example.org",
    ):
        assert elements.problem(entry, text.encode()) is not None


@pytest.mark.skipif(not LUAS, reason="no Lua interpreter on PATH")
@pytest.mark.parametrize("lua", LUAS)
def test_the_plugin_reads_each_element_as_python_does(lua, tmp_path):
    entries = [entry for entry in elements.REGISTRY if entry.checks]
    numbered = {entry: number for number, entry in enumerate(entries, 1)}
    lines = [
        f"local core = dofile({json.dumps(str(CORE))})",
        "local elements = {}",
        *(f"elements[{n}]={_rules._element(entry)}" for entry, n in numbered.items()),
        "local function unhex(text)",
        "  return (text:gsub('..', function(pair)",
        "    return string.char(tonumber(pair, 16)) end))",
        "end",
        "for index = 1, #arg, 3 do",
        "  print(core.element_problem(elements[tonumber(arg[index])],"
        " unhex(arg[index + 2]), arg[index + 1]) or 'ok')",
        "end",
    ]
    runner = tmp_path / "runner.lua"
    runner.write_text("\n".join(lines) + "\n", "utf-8")
    arguments = [
        part
        for entry, payload, data_type, _ in CASES
        for part in (str(numbered[entry]), data_type.value, payload.hex())
    ]
    done = subprocess.run(
        [lua, str(runner), *arguments], check=True, capture_output=True, text=True
    )

    assert done.stdout.splitlines() == [
        elements.problem(entry, payload, data_type) or "ok"
        for entry, payload, data_type, _ in CASES
    ]


_SPEC = (
    "; Specification: 3GPP TS 29.999\n; Version: 19.0.0\n; Vendor-ID: 10415\n\n\n"
    "; Type: AVP Table\n; Section: 6.3.1\n; Columns: Name Code Section Type Must\n"
    "Example-Number 1 6.3.2 OctetString V\n"
    "Example-Count 2 6.3.3 Unsigned32 V\n\n\n"
    "; Type: Interpreted Constraints\n; AVP: Example-Number\n; Section: 6.3.2\n"
    '; Versions: 19.0.0\n"Q."\n    encoding element TS29.999 4.1 "Unread"\n\n\n'
    "; Type: Interpreted Constraints\n; AVP: Example-Count\n; Section: 6.3.3\n"
    '; Versions: 19.0.0\n"Q."\n    encoding element TS29.002 17.7.8 "E-UTRAN-CGI"\n'
)


def test_the_linter_notes_an_element_the_registry_lacks():
    found = sorted(
        (finding.severity.value, finding.rule, finding.message)
        for finding in linter.lint(parser.parse(_SPEC))
        if finding.rule.startswith("constraint-")
    )

    assert found == [
        (
            "error",
            "constraint-type-mismatch",
            "Example-Count: element TS 29.002 17.7.8 E-UTRAN-CGI is checked as no"
            " Unsigned32",
        ),
        (
            "note",
            "constraint-element-unknown",
            'Example-Number: the element registry has no TS29.999 4.1 "Unread";'
            " nothing checks it",
        ),
    ]
