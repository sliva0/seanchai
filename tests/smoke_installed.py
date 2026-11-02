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
from seanchai import corpus, export, model

prefix = Path(sys.prefix).resolve()
for module in (seanchai, seanchai_corpus):
    assert module.__file__ is not None
    location = Path(module.__file__).resolve()
    assert location.is_relative_to(prefix), f"{location} is not in {prefix}"

books = corpus.Corpus.installed()
assert books.record is not None, "the installed corpus lost its record of holes"
assert len(corpus.Corpus.installed(raw=True)) == len(books)

avp = model.Model.build(books).resolve("TS29.229", "Public-Identity")
assert avp is not None
assert (avp.vendor_id, avp.code) == (10415, 601), avp

# What an export needs from the corrections comes with the corpus: no module
# is executed, and none is here to execute.
with tempfile.TemporaryDirectory() as scratch:
    output = Path(scratch) / "export"
    export.export_corpus(corpus.Corpus.load([seanchai_corpus.CORPUS_DIR]), output)
    document = json.loads((output / "documents" / "29229-i10.json").read_text("utf-8"))
reasons = document["corrections"]
assert reasons, "the installed corpus lost its corrections record"
assert all(reasons.values()), reasons

print(f"seanchai-corpus {seanchai_corpus.__version__}: {len(books)} documents")
