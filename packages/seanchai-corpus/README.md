# seanchai-corpus

The corpus of [Seanchaí](https://github.com/sliva0/seanchai): Diameter command
ABNFs and AVP definitions from 3GPP specifications, RFCs and a few other
documents, as `.dad` files, corrected and raw, with the record of known holes
and of each correction's reason, and `corpus.toml`: the corpus's format and the
rules, each with its evidence, for which version of a document a citation
means.
It holds the data and nothing else, depends on nothing, and needs Python 3.10 or
newer. The `seanchai` library that reads it needs Python 3.12 or newer.

```sh
pip install seanchai-corpus
```

```python
import seanchai_corpus

seanchai_corpus.CORPUS_DIR  # a pathlib.Path: 3gpp/, raw/, corpus.toml, ...
seanchai_corpus.__version__  # the date the corpus was regenerated
```

The [`seanchai`](https://pypi.org/project/seanchai/) library reads it with no
path:

```python
from seanchai import model

built = model.Model.installed()
built.resolve("TS29.229", "Public-Identity")
```

The version is the date the corpus was regenerated, as `YEAR.MONTH.DAY` with no
leading zeros. The format, `format` in `corpus.toml`, is the generation of the
grammar and layout the files are written in; a `seanchai` that does not read it
refuses the corpus and says which package to upgrade. The
[format](https://github.com/sliva0/seanchai/blob/main/docs/dad-format.md) and
[grammar](https://github.com/sliva0/seanchai/blob/main/docs/grammar.md) are
documented in the repository.

## License

MIT, see
[LICENSE](https://github.com/sliva0/seanchai/blob/main/packages/seanchai-corpus/LICENSE).
The definitions are taken from 3GPP, ETSI, 3GPP2, OMA, oneM2M and IETF
documents,
which stay under their publishers' terms, as
[NOTICE](https://github.com/sliva0/seanchai/blob/main/packages/seanchai-corpus/NOTICE)
says.
