# seanchai-corpus

The data of [Seanchaí](https://github.com/sliva0/seanchai): Diameter command
ABNFs and AVP definitions from 3GPP specifications, RFCs and a few other
documents, as `.dad` files. It holds:

- the corrected files and their raw mirror;
- the record of known holes and of each correction's reason;
- `corpus.toml`: the corpus's format, and the rules for which version of a
  document a citation means, each with its evidence;
- `interfaces.toml`: the Diameter interfaces each document specifies.

It has no dependencies and needs Python 3.10 or newer. The
[`seanchai`](https://pypi.org/project/seanchai/) library that reads it needs
Python 3.12 or newer.

```sh
pip install seanchai-corpus
```

```python
import seanchai_corpus

seanchai_corpus.CORPUS_DIR  # a pathlib.Path: 3gpp/, raw/, corpus.toml, ...
seanchai_corpus.__version__  # the date the corpus was regenerated
```

`seanchai` finds it with no path:

```python
from seanchai.model import Model

model = Model.installed()
model.resolve("TS29.229", "Public-Identity")
```

The version is the date the corpus was regenerated, as `YEAR.MONTH.DAY` with
no leading zeros. `format` in `corpus.toml` names the generation of the
grammar and layout the files use. A `seanchai` that cannot read that format
refuses the corpus and says which package to upgrade. The
[format](https://github.com/sliva0/seanchai/blob/main/docs/dad-format.md) and
[grammar](https://github.com/sliva0/seanchai/blob/main/docs/grammar.md) are
documented in the repository.

## License

MIT, see
[LICENSE](https://github.com/sliva0/seanchai/blob/main/packages/seanchai-corpus/LICENSE).
The definitions come from 3GPP, ETSI, 3GPP2, OMA, oneM2M and IETF documents,
which stay under their publishers' terms, as
[NOTICE](https://github.com/sliva0/seanchai/blob/main/packages/seanchai-corpus/NOTICE)
says.
