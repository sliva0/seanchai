# Consumers: the model and the validators

## The model

The AST mirrors a file one-to-one and may contradict itself. `model.Model`
is the opposite contract: built once from a `corpus.Corpus`, it hands a
consumer a `Message` whose entries point at real `Avp` objects, a `Grouped`
that enumerates its members, an `Enumerated` with its values, and every AVP
knowing its `(vendor-id, code)`, type, flag rules and defining document.

```python
from seanchai import corpus, model

built = model.Model.build(corpus.Corpus.load([Path("dad")]))
built.messages("TS29.229")  # bodies resolved
built.avps("TS29.229")  # a spec's dictionary view
built.resolve("TS29.229", "DRMP")  # one name in one spec's reading
built.find("Public-Identity")  # every AVP under a name
built.identified(10415, 601)  # every AVP claiming an identity
built.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
```

The query set is thin on purpose: each query was written because a real
consumer needed it. The AST stays public underneath: `parser.parse(text)`
reads one file into it, discarding `;;` comments, and
`parser.parse_with_comments(text)` returns the comments too, as a
`formatter.Comments` (trailing, standing and detached, each keyed by
`ast.TreePath`) that `formatter.format_spec(spec, comments)` writes back in
place.

**Resolution policy.** A name resolves, in order, to the specification's own
definition, then to the origin its re-used table cites (recursively, so an
indirect citation lands on the real definition), then to an AVP-table row,
then to a `; Bases:` document. Local-over-reused makes an *extension* mean
what the extending document says, while a plain re-print resolves through
the origin. A name tabulated in several of one file's AVP tables takes its
table facts — flag rules, and type and code when no clause defines it — from
the first row in file order; `table_rows` returns every copy, which matters
where per-interface tables disagree (TS 29.061's `3GPP-IMSI`, the linter's
`table-row-mismatch`). The model never reports the conflicts this papers
over; run the linter for those. Vendor spaces follow the linter's reading. A name that
resolves nowhere stays a name (`Member.avp is None`), as does the
`* [ AVP ]` wildcard. Origins and bases use `corpus.Corpus.resolve`, the
match-major-take-newest rule in [linter.md](linter.md#resolving-an-origin).

## The validators

Each target gets a directory under `integrations/`; scripts carry PEP 723
inline metadata naming their dependencies, so uv supplies everything:

```sh
uv run integrations/python_diameter/validate.py TS29.229
```

### python-diameter

[python-diameter](https://github.com/mensonen/diameter) folds every use of a
command into one class, so "is this class right?" has no single answer; the
script checks one specification's claims at a time. That document's commands
must exist under the right codes, each direction's `avp_def` must cover the
ABNF's members matched by `(vendor-id, code)`, `is_required` must agree with
the brackets, and the document's own AVPs must be right — name, type,
mandatory default — in the library's global dictionary. An "extra AVP" may
be another specification's legitimate use of the same command class; a
corpus AVP with no resolvable identity is reported as unchecked.

The first Cx run (library 0.9.0, which pins TS 29.229 V13.1.0) reported 94
disagreements, the sharpest being three command classes carrying RFC 4740's
IETF `SIP-Auth-Data-Item` and `SIP-Number-Auth-Items` where TS 29.229
specifies 3GPP's codes 612 and 607 — a wire-level incompatibility. Findings
against a version-13 dictionary may simply be Release 13's truth; the reader
decides what becomes an upstream issue.

That run was also the corpus's sharpest review: it found an ABNF line the
extractor silently dropped (29.229's RTR prints `RTR-Flags ]` with no opening
bracket, now input-patched) and the `Load` rows that became the linter's
`row-without-code` rule.
