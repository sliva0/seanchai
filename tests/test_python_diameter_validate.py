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


def _validate(*arguments, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *map(str, arguments)],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


@pytest.fixture
def fake(checkout, books):
    def run(*arguments):
        return _validate("--library", checkout, "--corpus", books, *arguments)

    return run


def test_one_reference_reports_as_it_always_has(fake):
    result = fake("TS29.901")

    assert result.returncode == 1, result.stderr
    for line in (_MISSING, _REQUIRED, _EXTRA_BETA, _EXTRA_STRAY, _ABSENT, _TYPE, _FLAG):
        assert line in result.stdout
    assert result.stdout.endswith(
        "\n8 disagreements across 1 commands and 6 TS29.901-defined AVPs\n"
    )
    assert "== " not in result.stdout
    assert "reference" not in result.stdout


def test_an_explicit_m_flag_is_held_against_the_reading(fake):
    assert _OVERRIDE in fake("TS29.901").stdout


def test_the_bare_number_names_the_document(fake):
    assert fake("29.901").stdout == fake("TS29.901").stdout


def test_a_reference_the_corpus_lacks_is_an_error(fake):
    result = fake("TS29.999")

    assert result.returncode == 2
    assert "TS29.999" in result.stderr


@pytest.mark.parametrize("given", ["checkout", "src"])
def test_library_takes_a_checkout_or_its_src(checkout, books, given):
    path = checkout if given == "checkout" else checkout / "src"

    result = _validate("--library", path, "--corpus", books, "TS29.901")

    first = result.stdout.splitlines()[0]
    assert first == f"library: {checkout / 'src' / 'diameter' / '__init__.py'}"
    assert _EXTRA_STRAY in result.stdout


def test_library_runs_from_another_directory(checkout, books, tmp_path):
    result = _validate(
        "--library", checkout, "--corpus", books, "TS29.901", cwd=tmp_path
    )

    assert result.returncode == 1, result.stderr
    assert str(checkout) in result.stdout.splitlines()[0]


def test_library_leaves_no_bytecode_in_the_checkout(checkout, books):
    _validate("--library", checkout, "--corpus", books, "TS29.901")

    assert not list(checkout.rglob("__pycache__"))


def test_library_refuses_a_directory_holding_no_library(books, tmp_path):
    result = _validate("--library", tmp_path, "--corpus", books, "TS29.901")

    assert result.returncode == 2
    assert "holds neither" in result.stderr


def test_without_library_the_installed_one_answers(books):
    result = _validate("--corpus", books, "TS29.901")

    assert "site-packages" in result.stdout.splitlines()[0]


def test_several_references_get_headings_a_summary_and_a_total(fake):
    result = fake("TS29.901", "TS29.902")

    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert "== TS29.901" in lines
    assert "== TS29.902" in lines
    rows = {line.split()[0]: line.split() for line in lines[-3:]}
    assert set(rows) == {"TS29.901", "TS29.902", "total"}
    heading = lines[-4].split()
    assert heading[:4] == ["reference", "commands", "avps", "findings"]
    for column in range(1, len(heading)):
        assert int(rows["total"][column]) == (
            int(rows["TS29.901"][column]) + int(rows["TS29.902"][column])
        )


def test_all_is_every_document_named(fake):
    assert fake("--all").stdout == fake("TS29.901", "TS29.902").stdout


def test_all_and_named_references_refuse_each_other(fake):
    assert fake("--all", "TS29.901").returncode == 2


def test_no_reference_is_refused(fake):
    assert fake().returncode == 2


def test_summary_only_prints_no_findings(fake):
    result = fake("--all", "--summary-only")

    assert _EXTRA_STRAY not in result.stdout
    assert "total" in result.stdout
    assert result.returncode == 1


def test_ignore_extras_keeps_what_no_checked_document_mentions(fake):
    plain = fake("TS29.901", "TS29.902").stdout
    filtered = fake("--ignore-extras", "TS29.901", "TS29.902").stdout

    assert _EXTRA_BETA in plain
    assert _EXTRA_BETA not in filtered
    assert _EXTRA_STRAY in filtered


def test_ignore_extras_over_one_document_says_it_hides_nothing(fake):
    result = fake("--ignore-extras", "TS29.901")

    assert _EXTRA_BETA in result.stdout
    assert "hides nothing" in result.stderr


def test_claimed_checks_the_listed_set_and_suppresses_over_it(fake, tmp_path):
    claimed = tmp_path / "claimed.txt"
    claimed.write_text("# what it claims\nTS29.901  # first\n\n29.902\n", "utf-8")

    result = fake("--claimed", claimed)

    assert "== TS29.902" in result.stdout
    assert _EXTRA_BETA not in result.stdout
    assert _EXTRA_STRAY in result.stdout


def test_claimed_with_a_reference_checks_it_alone_over_the_set(fake, tmp_path):
    claimed = tmp_path / "claimed.txt"
    claimed.write_text("TS29.901\nTS29.902\n", "utf-8")

    result = fake("--claimed", claimed, "TS29.901")

    assert "TS29.901-defined" in result.stdout
    assert _EXTRA_BETA not in result.stdout


def test_claimed_narrower_than_the_checked_document_keeps_the_extra(fake, tmp_path):
    claimed = tmp_path / "claimed.txt"
    claimed.write_text("TS29.901\n", "utf-8")

    assert _EXTRA_BETA in fake("--claimed", claimed).stdout


def test_claimed_naming_a_document_the_corpus_lacks_is_an_error(fake, tmp_path):
    claimed = tmp_path / "claimed.txt"
    claimed.write_text("TS29.999\n", "utf-8")

    assert fake("--claimed", claimed).returncode == 2


def test_claimed_file_missing_is_an_error(fake, tmp_path):
    assert fake("--claimed", tmp_path / "absent.txt").returncode == 2


def test_enumerated_as_integer_accepts_the_class_the_library_holds_it_in(fake):
    result = fake("--enumerated-as-integer", "TS29.901")

    assert _TYPE not in result.stdout
    assert _FLAG in result.stdout


def test_no_flags_drops_both_m_bit_comparisons(fake):
    result = fake("--no-flags", "TS29.901")

    assert _FLAG not in result.stdout
    assert _OVERRIDE not in result.stdout
    assert _TYPE in result.stdout


def test_grouped_holds_classes_against_bodies_only_when_asked(fake):
    plain = fake("TS29.901").stdout
    deep = fake("--grouped", "TS29.901").stdout

    for line in (_GROUPED_MISSING, _GROUPED_EXTRA, _NO_CLASS):
        assert line not in plain
        assert line in deep


def test_a_clean_document_exits_zero(checkout, tmp_path):
    (tmp_path / "clean.dad").write_text(
        textwrap.dedent(
            """\
            ; Specification: 3GPP TS 29.903
            ; Version: 19.0.0
            ; Vendor-ID: 10415


            ; Type: AVP Table
            ; Section: 7.3
            ; Columns: Name    Code  Type         Must  May  S.not  M.not
                       Shared  1     OctetString  V     -    -      M
            """
        ),
        "utf-8",
    )

    result = _validate("--library", checkout, "--corpus", tmp_path, "TS29.903")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "\n0 disagreements across 0 commands and 1 TS29.903-defined AVPs" in (
        result.stdout
    )


def test_the_claimed_list_is_in_the_corpus_and_the_real_library_loads():
    """`claimed.txt` is what README.md beside the script says, every line of it
    a document the corpus holds, against the library uv would install."""
    result = _validate("--claimed", "--summary-only", "--grouped")

    assert result.returncode == 1, result.stderr
    rows = {line.split()[0] for line in result.stdout.splitlines()[2:]}
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
