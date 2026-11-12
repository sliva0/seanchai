"""What a consumer's CI does: load the installed corpus and resolve an AVP.

Run with `-I` by a Python holding the two wheels and not the repository, by
`tests/test_packaging.py` and by the CI step installing the wheels for real.
"""

import json
import sys
import tempfile
from pathlib import Path

import seanchai_corpus

import seanchai
from seanchai import corpus, export, model, wireshark

prefix = Path(sys.prefix).resolve()
for module in (seanchai, seanchai_corpus):
    assert module.__file__ is not None
    location = Path(module.__file__).resolve()
    assert location.is_relative_to(prefix), f"{location} is not in {prefix}"

books = corpus.Corpus.installed()
assert books.record is not None, "the installed corpus lost its record of holes"
assert books.rules.format in corpus.FORMATS, "the installed corpus lost its format"
assert books.rules.release_stand_ins, "the installed corpus lost its rules"
assert len(corpus.Corpus.installed(raw=True)) == len(books)
assert books.version == seanchai_corpus.__version__
assert seanchai.__version__

avp = model.Model.build(books).resolve("TS29.229", "Public-Identity")
assert avp is not None
assert (avp.vendor_id, avp.code) == (10415, 601), avp

# What an export needs from the corrections comes with the corpus: no module
# is executed, and none is here to execute.
with tempfile.TemporaryDirectory() as scratch:
    output = Path(scratch) / "export"
    export.export_corpus(corpus.Corpus.load([seanchai_corpus.CORPUS_DIR]), output)
    document = json.loads((output / "documents" / "29229-j10.json").read_text("utf-8"))
    assert (output / "syntax" / "dad.tmLanguage.json").is_file()
reasons = document["corrections"]
assert reasons, "the installed corpus lost its corrections record"
assert all(item["reason"] for item in reasons.values()), reasons

# The plugin's Lua comes with the library: its checks and its Wireshark side.
plugin = wireshark.generate(books, application_ids=[0]).text
assert "function M.validate(rules, pdu, prefs)" in plugin, "core.lua is missing"
assert "register_postdissector(proto)" in plugin, "plugin.lua is missing"
assert wireshark.EXPLORER_LINE.findall(plugin) == [wireshark.EXPLORER]
assert wireshark.VERSIONS_LINE.findall(plugin) == [
    f"seanchai {seanchai.__version__}, corpus {seanchai_corpus.__version__}"
]

print(f"seanchai-corpus {seanchai_corpus.__version__}: {len(books)} documents")
