"""The Wireshark dictionary `integrations/wireshark/dictionary.py` writes,
read back by the oracle: crosschecked against the corpus it was written from,
it agrees but for what the format cannot hold."""

import importlib.util
import sys
from pathlib import Path

import pytest

from seanchai import dictionary, model, oracle
from seanchai.corpus import Corpus

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "integrations" / "wireshark" / "dictionary.py"
_ALIASES = _ROOT / "integrations" / "wireshark" / "aliases.toml"

# What a round trip of the whole corpus reports, each something the format
# cannot hold:
_LEFT = {
    # A hole has no complete reading to write.
    ("absent-from-dictionary", "TS29.061"),
    ("absent-from-dictionary", "TS29.234"),
    # One reading per identity: RFC 7155's, which RFC 4005's differs from.
    ("name-disagrees", "RFC4005", "Framed-AppleTalk-Link"),
    ("name-disagrees", "RFC4005", "Framed-AppleTalk-Network"),
    ("name-disagrees", "RFC4005", "Framed-AppleTalk-Zone"),
    ("type-disagrees", "RFC4005", "Framed-IPX-Network"),
    # One name per AVP: another document's AVP holds it, and aliases.toml
    # gives none.
    ("name-disagrees", "TS29.154", "Time-Window"),
    ("name-disagrees", "TS29.283", "Sequence-Number"),
    ("name-disagrees", "TS29.345", "Filter-Id"),
    ("name-disagrees", "TS29.345", "MAC-Address"),
    ("name-disagrees", "TS29.468", "MBMS-GW-SSM-IP-Address"),
    ("name-disagrees", "TS29.468", "MBMS-GW-SSM-IPv6-Address"),
    ("name-disagrees", "TS29.468", "Radio-Frequency"),
    ("name-disagrees", "oneM2M-TS-0004", "Originator"),
    # A Grouped AVP no document prints a rule for: `<grouped>` holds members.
    ("type-disagrees", "TS29.128", "APN-Rate-Control-Status"),
    # One name per value of an AVP, whichever document names it first.
    ("value-disagrees", "TS29.329", "Experimental-Result-Code"),
    ("value-disagrees", "TS29.330", "Experimental-Result-Code"),
}


def _script():
    spec = importlib.util.spec_from_file_location("wireshark_dictionary", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    books = Corpus.installed()
    built = dictionary.build(model.Model.build(books), corpus_version=books.version)
    aliases = oracle.load_aliases(_ALIASES)
    script = _script()
    output = tmp_path_factory.mktemp("wireshark")
    files = script.generate(built, aliases)
    for name, text in files.files.items():
        (output / name).write_text(text, encoding="utf-8")
    return books, aliases, output, files, script, built


def test_the_round_trip_agrees_but_for_what_the_format_cannot_hold(written):
    books, aliases, output, _, _, _ = written
    read = oracle.Oracle.load(output)
    found = set()
    for entry in books.newest():
        for finding in oracle.crosscheck(entry.spec, read, aliases):
            if finding.accepted_by is not None:
                continue
            subject = finding.message.split(" ", 1)[0]
            found.add(
                (finding.rule, entry.reference)
                if finding.rule == "absent-from-dictionary"
                else (finding.rule, entry.reference, subject)
            )
    assert found == _LEFT


def test_the_files_are_the_same_on_every_run(written):
    _, aliases, _, files, script, built = written
    assert script.generate(built, aliases).files == files.files
    assert "dictionary.xml" in files.files
    assert "TS29.272.xml" in files.files
    assert '<application id="16777251"' in files.files["TS29.272.xml"]
