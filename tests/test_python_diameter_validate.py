"""The python-diameter validator reads any checkout, and filters its noise.

A fake library and a two-document corpus hold one disagreement of each kind, so
each option's effect is a line appearing or going away. The script runs in a
subprocess because `--library` puts the fake `diameter` ahead of the real one,
which the generator's tests import in this interpreter.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).parent.parent / "integrations" / "python_diameter" / "validate.py"
)

_FIRST = """\
; Specification: 3GPP TS 29.901
; Version: 19.0.0
; Vendor-ID: 10415


; Type: Message
; Name: Example-Request, EXR
; Section: 6.1
<Example-Request> ::= < Diameter Header: 8388000, REQ, PXY, 16777000 >
        < Shared >
        { Alpha }
        [ Gone ]
        [ Box ]
        [ Plain ]


; Type: Grouped AVP
; Name: Box
; Section: 6.3.1
Box ::= < AVP header: 3 10415 >
        [ Inner ]


; Type: Grouped AVP
; Name: Plain
; Section: 6.3.2
Plain ::= < AVP header: 10 10415 >
        [ Inner ]


; Type: AVP Table
; Section: 6.3
; Columns: Name    Code  Type         Must  May  S.not  M.not
           Shared  1     OctetString  V     -    -      M
           Alpha   2     Enumerated   V     -    -      M
           Box     3     Grouped      V     -    -      M
           Inner   5     Unsigned32   V     -    -      M
           Gone    9     OctetString  V     -    -      M
           Plain   10    Grouped      V     -    -      M
"""

_SECOND = """\
; Specification: 3GPP TS 29.902
; Version: 19.0.0
; Vendor-ID: 10415


; Type: Message
; Name: Example-Request, EXR
; Section: 7.1
<Example-Request> ::= < Diameter Header: 8388000, REQ, PXY, 16777001 >
        < Shared >
        [ Beta ]


; Type: AVP Table
; Section: 7.3
; Columns: Name    Code  Type         Must  May  S.not  M.not
           Shared  1     OctetString  V     -    -      M
           Beta    4     OctetString  V     -    -      M
"""

_LIBRARY = {
    "diameter/__init__.py": "",
    "diameter/message/__init__.py": "",
    "diameter/message/_base.py": """\
        class Message: ...
        class DefinedMessage(Message): ...
        class UndefinedMessage(Message): ...
        """,
    "diameter/message/constants.py": """\
        VENDOR_TGPP = 10415
        AVP_TGPP_SHARED = 1
        """,
    "diameter/message/avp/__init__.py": "",
    "diameter/message/avp/generator.py": """\
        from typing import NamedTuple

        class AvpGenDef(NamedTuple):
            attr_name: str
            avp_code: int
            vendor_id: int = 0
            is_required: bool = False
            is_mandatory: "bool | None" = None
            type_class: "type | None" = None
        """,
    "diameter/message/avp/dictionary.py": """\
        from ..constants import *

        class AvpGrouped: ...
        class AvpInteger32: ...
        class AvpOctetString: ...
        class AvpUnsigned32: ...
        AvpEnumerated = AvpInteger32

        AVP_DICTIONARY = {}
        AVP_VENDOR_DICTIONARY = {}
        TGPP = {"vendor": 10415}
        AVP_VENDOR_DICTIONARY[10415] = {
            AVP_TGPP_SHARED: {"name": "Shared", "type": AvpOctetString, **TGPP},
            2: {"name": "Alpha", "type": AvpEnumerated, "mandatory": True, **TGPP},
            3: {"name": "Box", "type": AvpGrouped, **TGPP},
            4: {"name": "Beta", "type": AvpOctetString, **TGPP},
            5: {"name": "Inner", "type": AvpUnsigned32, **TGPP},
            10: {"name": "Plain", "type": AvpGrouped, **TGPP},
        }
        """,
    "diameter/message/avp/grouped.py": """\
        from .generator import AvpGenDef

        __all__ = ["BoxClass"]

        class BoxClass:
            avp_def = (AvpGenDef("other", 7, 10415),)
        """,
    "diameter/message/commands/__init__.py": """\
        from .._base import DefinedMessage
        from ..avp.generator import AvpGenDef
        from ..avp.grouped import BoxClass

        class Example(DefinedMessage):
            code = 8388000
            name = "Example"

        class ExampleRequest(Example):
            avp_def = (
                AvpGenDef("shared", 1, 10415, is_required=True, is_mandatory=True),
                AvpGenDef("alpha", 2, 10415),
                AvpGenDef("box", 3, 10415, type_class=BoxClass),
                AvpGenDef("plain", 10, 10415),
                AvpGenDef("beta", 4, 10415),
                AvpGenDef("stray", 8, 10415),
            )

        class ExampleAnswer(Example):
            avp_def = ()

        all_commands = {8388000: Example}
        """,
}

_MISSING = "Example-Request: Gone (vendor 10415, code 9, optional) is in clause 6.1's"
_REQUIRED = "Example-Request: Alpha is required in clause 6.1 but"
_OVERRIDE = "Example-Request: Shared's reading forbids the M flag, but"
_EXTRA_BETA = "ExampleRequest.avp_def carries beta (vendor 10415, code 4)"
_EXTRA_STRAY = "ExampleRequest.avp_def carries stray (vendor 10415, code 8)"
_ABSENT = "Gone (code 9): absent from AVP_VENDOR_DICTIONARY[10415]"
_TYPE = "Alpha (code 2): the library holds it as AvpInteger32"
_FLAG = "Alpha (code 2): the AVP table forbids the M flag"
_GROUPED_MISSING = "Box: Inner (vendor 10415, code 5, optional) is in TS29.901 clause"
_GROUPED_EXTRA = "Box: BoxClass.avp_def carries other (vendor 10415, code 7)"
_NO_CLASS = "Example-Request: Plain (vendor 10415, code 10) is Grouped but"


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture(scope="module")
def checkout(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("checkout")
    _write(root / "src", _LIBRARY)
    return root


@pytest.fixture(scope="module")
def books(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("corpus")
    _write(root, {"first.dad": _FIRST, "second.dad": _SECOND})
    return root


@pytest.fixture(scope="module")
def claims(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("claims")
    _write(
        root,
        {
            "both.txt": "# what it claims\nTS29.901  # first\n\n29.902\n",
            "first.txt": "TS29.901\n",
            "unknown.txt": "TS29.999\n",
        },
    )
    return root


def _validate(*arguments, cwd: Path | None = None, script: Path = _SCRIPT):
    return subprocess.run(
        [sys.executable, str(script), *map(str, arguments)],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


_ONE = "\n8 disagreements across 1 commands and 6 TS29.901-defined AVPs\n"
_REPORTED = [_MISSING, _REQUIRED, _OVERRIDE, _EXTRA_BETA, _EXTRA_STRAY, _ABSENT]
_REPORTED += [_TYPE, _FLAG]
_DEEP = [_GROUPED_MISSING, _GROUPED_EXTRA, _NO_CLASS]

# (arguments, exit status, lines reported, lines not reported, on stderr).
_CASES = [
    (["TS29.901"], 1, [*_REPORTED, _ONE], ["== ", "reference", *_DEEP], None),
    (["29.901"], 1, [*_REPORTED, _ONE], [], None),
    (["TS29.999"], 2, [], [], "TS29.999"),
    (["--all", "TS29.901"], 2, [], [], None),
    ([], 2, [], [], None),
    (["--all", "--summary-only"], 1, ["total"], [_EXTRA_STRAY], None),
    # An extra a checked document mentions is hidden; one none does stays.
    (
        ["--ignore-extras", "TS29.901", "TS29.902"],
        1,
        [_EXTRA_STRAY],
        [_EXTRA_BETA],
        None,
    ),
    (["--ignore-extras", "TS29.901"], 1, [_EXTRA_BETA], [], "hides nothing"),
    (
        ["--claimed", "{claims}/both.txt"],
        1,
        ["== TS29.902", _EXTRA_STRAY],
        [_EXTRA_BETA],
        None,
    ),
    (
        ["--claimed", "{claims}/both.txt", "TS29.901"],
        1,
        ["TS29.901-defined"],
        [_EXTRA_BETA],
        None,
    ),
    (["--claimed", "{claims}/first.txt"], 1, [_EXTRA_BETA], [], None),
    (["--claimed", "{claims}/unknown.txt"], 2, [], [], None),
    (["--claimed", "{claims}/absent.txt"], 2, [], [], None),
    (["--enumerated-as-integer", "TS29.901"], 1, [_FLAG], [_TYPE], None),
    (["--no-flags", "TS29.901"], 1, [_TYPE], [_FLAG, _OVERRIDE], None),
    (["--grouped", "TS29.901"], 1, _DEEP, [], None),
]


@pytest.mark.parametrize(
    ("arguments", "status", "reported", "unreported", "stderr"),
    _CASES,
    ids=[" ".join(case[0]) or "none" for case in _CASES],
)
def test_each_option_reports_or_hides_its_findings(
    checkout, books, claims, arguments, status, reported, unreported, stderr
):
    arguments = [each.format(claims=claims) for each in arguments]

    result = _validate("--library", checkout, "--corpus", books, *arguments)

    assert result.returncode == status, result.stdout + result.stderr
    assert not [line for line in reported if line not in result.stdout]
    assert not [line for line in unreported if line in result.stdout]
    if stderr:
        assert stderr in result.stderr


def test_several_references_get_headings_and_a_summary_that_adds_up(checkout, books):
    result = _validate("--library", checkout, "--corpus", books, "--all")

    assert result.returncode == 1
    assert (
        result.stdout
        == _validate(
            "--library", checkout, "--corpus", books, "TS29.901", "TS29.902"
        ).stdout
    )
    lines = result.stdout.splitlines()
    assert {"== TS29.901", "== TS29.902"} <= set(lines)
    rows = {line.split()[0]: line.split() for line in lines[-3:]}
    assert set(rows) == {"TS29.901", "TS29.902", "total"}
    heading = lines[-4].split()
    assert heading[:4] == ["reference", "commands", "avps", "findings"]
    for column in range(1, len(heading)):
        assert int(rows["total"][column]) == (
            int(rows["TS29.901"][column]) + int(rows["TS29.902"][column])
        )


@pytest.mark.parametrize("given", ["checkout", "src"])
def test_library_imports_a_checkout_or_its_src_from_anywhere(
    checkout, books, tmp_path, given
):
    path = checkout if given == "checkout" else checkout / "src"

    result = _validate("--library", path, "--corpus", books, "TS29.901", cwd=tmp_path)

    assert result.returncode == 1, result.stderr
    first = result.stdout.splitlines()[0]
    assert first == f"library: {checkout / 'src' / 'diameter' / '__init__.py'}"
    assert _EXTRA_STRAY in result.stdout
    assert not list(checkout.rglob("__pycache__"))


def test_library_refuses_a_directory_holding_none_and_defaults_to_the_installed(
    books, tmp_path
):
    refused = _validate("--library", tmp_path, "--corpus", books, "TS29.901")
    installed = _validate("--corpus", books, "TS29.901")

    assert refused.returncode == 2
    assert "holds neither" in refused.stderr
    assert "site-packages" in installed.stdout.splitlines()[0]


def test_a_clean_document_exits_zero(checkout, tmp_path):
    _write(
        tmp_path,
        {
            "clean.dad": """\
            ; Specification: 3GPP TS 29.903
            ; Version: 19.0.0
            ; Vendor-ID: 10415


            ; Type: AVP Table
            ; Section: 7.3
            ; Columns: Name    Code  Type         Must  May  S.not  M.not
                       Shared  1     OctetString  V     -    -      M
            """
        },
    )

    result = _validate("--library", checkout, "--corpus", tmp_path, "TS29.903")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "\n0 disagreements across 0 commands and 1 TS29.903-defined AVPs" in (
        result.stdout
    )


_RENAMED = """\
; Specification: 3GPP TS 29.904
; Version: 19.0.0
; Vendor-ID: 10415


; Type: AVP Table
; Section: 8.3
; Columns: Name         Code  Type         Must  May  S.not  M.not
           Doc-Shared   1     OctetString  V     -    -      M
           Doc-Beta     4     OctetString  V     -    -      M
           Doc-Inner    5     Unsigned32   V     -    -      M
           Doc-Alpha    2     Enumerated   V     -    -      M
"""

# Wireshark takes the library's name for Shared, the library's with other case
# and separators for Inner, neither's for Beta, and has no entry for Alpha.
_WIRESHARK = """\
<?xml version="1.0" encoding="UTF-8"?>
<dictionary>
  <base>
    <vendor vendor-id="TGPP" code="10415" name="3GPP"/>
  </base>
  <application id="16777000" name="Example">
    <avp name="Shared" code="1" vendor-id="TGPP">
      <type type-name="OctetString"/>
    </avp>
    <avp name="Wireshark-Beta" code="4" vendor-id="TGPP">
      <type type-name="OctetString"/>
    </avp>
    <avp name="IN_NER" code="5" vendor-id="TGPP">
      <type type-name="Unsigned32"/>
    </avp>
  </application>
</dictionary>
"""

_NAME_SHARED = "Doc-Shared (code 1): the library names it 'Shared'"
_NAME_INNER = "Doc-Inner (code 5): the library names it 'Inner'"
_NAME_BETA = "Doc-Beta (code 4): the library names it 'Beta'"
_NAME_ALPHA = "Doc-Alpha (code 2): the library names it 'Alpha'"


_NAMES = [_NAME_SHARED, _NAME_INNER, _NAME_BETA, _NAME_ALPHA]
_HIDDEN = "hidden: 2 names following Wireshark's dictionary (--names shows)\n"


@pytest.mark.parametrize(
    ("default", "arguments", "status", "reported", "tail"),
    [
        (None, ["--wireshark", "{wireshark}"], 1, [_NAME_BETA, _NAME_ALPHA], _HIDDEN),
        (None, ["--wireshark", "{wireshark}", "--names"], 1, _NAMES, "AVPs\n"),
        (None, [], 1, _NAMES, "AVPs\n"),
        # The repository's `specifications/wireshark`, beside the script.
        ("dictionary", [], 1, [_NAME_BETA, _NAME_ALPHA], _HIDDEN),
        ("empty", [], 1, _NAMES, "AVPs\n"),
        (None, ["--wireshark", "{absent}"], 2, [], ""),
    ],
    ids=["named", "names", "none", "default", "empty-default", "unreadable"],
)
def test_a_name_that_is_wiresharks_is_counted_not_reported(
    checkout, tmp_path, default, arguments, status, reported, tail
):
    """The document's own spellings throughout, leaving only name findings.
    Wireshark takes the library's name for Shared, the library's with other
    case and separators for Inner, neither's for Beta, and has no Alpha. The
    script runs from a copy, so its default dictionary is what the test puts
    beside it."""
    script = tmp_path / "repository" / "integrations" / "python_diameter" / _SCRIPT.name
    script.parent.mkdir(parents=True)
    script.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    _write(tmp_path / "corpus", {"renamed.dad": _RENAMED})
    _write(tmp_path / "wireshark", {"dictionary.xml": _WIRESHARK})
    beside = tmp_path / "repository" / "specifications" / "wireshark"
    if default == "dictionary":
        _write(beside, {"dictionary.xml": _WIRESHARK})
    elif default == "empty":
        beside.mkdir(parents=True)
    places = {"wireshark": tmp_path / "wireshark", "absent": tmp_path / "absent"}

    result = _validate(
        "--library",
        checkout,
        "--corpus",
        tmp_path / "corpus",
        "--enumerated-as-integer",
        "--no-flags",
        *(each.format(**places) for each in arguments),
        "TS29.904",
        script=script,
    )

    assert result.returncode == status, result.stdout + result.stderr
    if status == 2:
        assert "cannot read the Wireshark dictionary" in result.stderr
        return
    assert [line for line in _NAMES if line in result.stdout] == reported
    assert result.stdout.endswith(tail)
    disagreements = f"\n{len(reported)} disagreements across 0 commands and 4"
    assert disagreements in result.stdout


def test_hidden_names_alone_exit_zero_and_close_a_summary(checkout, tmp_path):
    _write(tmp_path / "wireshark", {"dictionary.xml": _WIRESHARK})
    _write(
        tmp_path / "only",
        {
            "only.dad": """\
            ; Specification: 3GPP TS 29.905
            ; Version: 19.0.0
            ; Vendor-ID: 10415


            ; Type: AVP Table
            ; Section: 9.3
            ; Columns: Name        Code  Type         Must  May  S.not  M.not
                       Doc-Shared  1     OctetString  V     -    -      M
            """
        },
    )
    _write(tmp_path / "both", {"renamed.dad": _RENAMED, "first.dad": _FIRST})
    wireshark = ["--wireshark", tmp_path / "wireshark"]

    alone = _validate(
        "--library", checkout, "--corpus", tmp_path / "only", *wireshark, "TS29.905"
    )
    summary = _validate(
        "--library",
        checkout,
        "--corpus",
        tmp_path / "both",
        *wireshark,
        "--summary-only",
        "--all",
    )

    assert alone.returncode == 0, alone.stdout + alone.stderr
    assert "\n0 disagreements across" in alone.stdout
    assert alone.stdout.endswith(
        "hidden: 1 name following Wireshark's dictionary (--names shows)\n"
    )
    lines = summary.stdout.splitlines()
    assert lines[-2].startswith("total")
    assert lines[-1].startswith("hidden: 2 names")


def test_the_claimed_list_is_in_the_corpus_and_the_real_library_loads():
    """`claimed.txt` is what README.md beside the script says, every line of it
    a document the corpus holds, against the library uv would install."""
    result = _validate("--claimed", "--summary-only", "--grouped")

    assert result.returncode == 1, result.stderr
    lines = result.stdout.splitlines()[2:]
    rows = {line.split()[0] for line in lines if not line.startswith("hidden:")}
    assert rows == {
        "reference",
        "RFC6733",
        "RFC4004",
        "RFC4005",
        "RFC7155",
        "RFC4006",
        "TS32.299",
        "RFC4072",
        "TS29.219",
        "TS29.229",
        "TS29.272",
        "TS29.329",
        "total",
    }
