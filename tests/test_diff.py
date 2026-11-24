"""`seanchai diff` and `seanchai.diff`: what changed for a stack, over two
versions of a private document read in the installed corpus."""

import json

import pytest
from click.testing import CliRunner

from seanchai import diff
from seanchai.cli import main
from seanchai.corpus import Corpus
from seanchai.model import HolePolicy, Model

_OLD = """\
; Specification: Private ACME-HSS
; Version: 4.2
; Vendor-ID: 99999
; Bases: RFC6733


; Type: Message
; Name: ACME-Probe-Request, APR
; Section: 1
<ACME-Probe-Request> ::= < Diameter Header: 9999, REQ, 4242 >
        < Session-Id >
        { ACME-Token }
        [ ACME-Mode ]
        [ ACME-Group ]
        * [ AVP ]


; Type: Message
; Name: ACME-Probe-Answer, APA
; Section: 1
<ACME-Probe-Answer> ::= < Diameter Header: 9999, 4242 >
        < Session-Id >
        { Result-Code }


; Type: Grouped AVP
; Name: ACME-Group
; Section: 2.3
ACME-Group ::= < AVP header: 3 99999 >
        { ACME-Token }


; Type: Enumerated AVP
; Name: ACME-Mode
; Section: 2.2
ACME-Mode ::= < Enumerated AVP header: 2 99999 >
        FAST = 0
        SLOW = 1
        GONE = 2


; Type: AVP Table
; Section: 2
; Columns: Name   Code   Type          Must   May   S.not   M.not
ACME-Token        1      OctetString   M,V    -     -       -
ACME-Mode         2      Enumerated    M,V    -     -       -
ACME-Group        3      Grouped       M,V    -     -       -
"""

_NEW = (
    _OLD.replace("; Version: 4.2", "; Version: 4.3")
    .replace("        [ ACME-Mode ]\n", "        { ACME-Mode }\n")
    .replace("        SLOW = 1\n", "        SLOWER = 1\n")
    .replace("        GONE = 2\n", "        ZIPPY = 3\n")
    .replace(
        "ACME-Token        1      OctetString   M,V",
        "ACME-Token        1      OctetString   V  ",
    )
    .replace(
        "ACME-Group ::= < AVP header: 3 99999 >\n        { ACME-Token }\n",
        "ACME-Group ::= < AVP header: 3 99999 >\n        { ACME-Token }\n"
        "        [ ACME-Mode ]\n",
    )
)


def _write(directory, text, name):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _built(base, path):
    return Model.build(diff.overlay(base, [path]), holes=HolePolicy.ANY)


@pytest.fixture(scope="module")
def changes(tmp_path_factory):
    directory = tmp_path_factory.mktemp("diff")
    base = Corpus.installed()
    old = _write(directory, _OLD, "old/acme.dad")
    new = _write(directory, _NEW, "new/acme.dad")
    return diff.diff(
        _built(base, old), _built(base, new), documents=["Private-ACME-HSS"]
    )


def _found(changes, kind):
    return [
        (c.subject, c.field, c.before, c.after, c.impact)
        for c in changes.changes
        if c.kind == kind
    ]


def test_a_member_made_required_breaks_and_says_where(changes):
    (presence,) = [c for c in changes.changes if c.kind == "member-presence"]
    assert (presence.subject, presence.before, presence.after, presence.impact) == (
        "Private-ACME-HSS 4242/APR > ACME-Mode",
        "optional",
        "required",
        "breaking",
    )
    assert presence.paths == ("Private-ACME-HSS 4242/APR > ACME-Mode",)
    assert presence.new is not None and presence.new.version == "4.3"


def test_an_m_bit_change_breaks_on_the_wire(changes):
    assert _found(changes, "avp-flags") == [
        ("ACME-Token (99999:1)", "M bit", "must", "unstated", "breaking")
    ]
    (flags,) = [c for c in changes.changes if c.kind == "avp-flags"]
    assert "Private-ACME-HSS 4242/APR > ACME-Token" in flags.paths
    assert "Private-ACME-HSS 4242/APR > ACME-Group > ACME-Token" in flags.paths


def test_values_are_matched_by_number(changes):
    assert _found(changes, "value-renamed") == [
        ("ACME-Mode (99999:2)", "value 1", "SLOW", "SLOWER", "editorial")
    ]
    assert _found(changes, "value-removed") == [
        ("ACME-Mode (99999:2)", "value 2", "GONE (2)", None, "breaking")
    ]
    assert _found(changes, "value-added") == [
        ("ACME-Mode (99999:2)", "value 3", None, "ZIPPY (3)", "compatible")
    ]


def test_an_optional_member_added_to_a_grouped_avp_is_compatible(changes):
    assert _found(changes, "member-added") == [
        (
            "ACME-Group (99999:3) > ACME-Mode",
            None,
            None,
            "optional 0..1",
            "compatible",
        )
    ]


def test_the_diff_counts_orders_and_validates_as_its_schema(changes):
    assert changes.counts == {"breaking": 3, "compatible": 2, "editorial": 1}
    assert [c.impact for c in changes.changes] == sorted(
        (c.impact for c in changes.changes),
        key=["breaking", "compatible", "editorial"].index,
    )
    assert diff.Diff.model_validate_json(diff.dumps(changes)) == changes
    assert "Diff" in json.dumps(diff.json_schema())
    assert diff.render(changes).splitlines()[0] == (
        "Private-ACME-HSS 4.2 -> Private-ACME-HSS 4.3: 3 breaking, 2 compatible,"
        " 1 editorial"
    )


def test_the_command_says_where_each_change_comes_from(tmp_path):
    """Beside each file its raw mirror, as `corpus regenerate -o` writes it:
    the M bit moved in the raw file too, the value's name only in the
    corrected one."""
    raw_old = _OLD.replace("SLOW = 1", "SLOWER = 1")
    raw_new = _NEW
    old = _write(tmp_path, _OLD, "old/private/acme.dad")
    new = _write(tmp_path, _NEW, "new/private/acme.dad")
    _write(tmp_path, raw_old, "old/raw/private/acme.raw.dad")
    _write(tmp_path, raw_new, "new/raw/private/acme.raw.dad")

    result = CliRunner().invoke(main, ["diff", str(old), str(new), "--json"])

    assert result.exit_code == 0, result.output
    found = diff.Diff.model_validate_json(result.output)
    origins = {change.kind: change.origin for change in found.changes}
    assert origins["avp-flags"] == "document"
    assert origins["value-renamed"] == "corrections"
    again = CliRunner().invoke(main, ["diff", str(old), str(new), "--json"])
    assert again.output == result.output


def test_two_corpora_or_two_files_but_not_one_of_each(tmp_path):
    path = _write(tmp_path, _OLD, "acme.dad")
    result = CliRunner().invoke(main, ["diff", str(path), str(tmp_path)])
    assert result.exit_code == 2
    assert "two .dad files or two corpus directories" in result.output


def test_two_releases_of_the_corpus_compare_as_one_stack_sees_them():
    """oneM2M TS-0004 reaches TS 32.299 V11.20.0, whose citations Release 19's
    copies answer in either release, spelled `TS29.229 V19.1.0` in Release
    18's reading and `TS29.229` in Release 19's: one copy, so no change. TS
    29.329 gains a Data-Reference value in Release 19."""
    books = Corpus.installed()
    older, newer = (
        Model.build(books, release=release, holes=HolePolicy.ANY)
        for release in (18, 19)
    )

    unchanged = diff.diff(older, newer, documents=["oneM2M-TS-0004"])
    gained = diff.diff(older, newer, documents=["TS29.329"])

    assert (unchanged.old.release, unchanged.new.release) == (18, 19)
    assert unchanged.changes == ()
    assert gained.counts == {"breaking": 0, "compatible": 1, "editorial": 0}
