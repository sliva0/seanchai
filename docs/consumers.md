# Consumers: the model and the integrations

## The model

The AST mirrors a file one-to-one and may contradict itself. `model.Model`
is the opposite contract: built once from a `corpus.Corpus`, it hands a
consumer a `Message` whose members point at real `Avp` objects, a
`Grouped` that enumerates its members, an `Enumerated` with its values, and
every AVP knowing its `(vendor-id, code)`, type, flag rules and defining
document.

```python
import seanchai_corpus
from seanchai import corpus, model
from seanchai.dad import ast

built = model.Model.build(corpus.Corpus.load([seanchai_corpus.CORPUS_DIR]))
# strict against the corpus's holes.toml; dictionary=Path("specifications/wireshark")
# adds Avp.wireshark_name
built.messages("TS29.229")  # bodies resolved
built.applications("TS29.212")  # commands per application and interface
built.avps("TS29.229")  # a document's dictionary view
built.resolve("TS29.229", "DRMP")  # one name in one document's reading
built.find("Public-Identity")  # every AVP under a name
built.identified(10415, 601)  # every AVP claiming an identity
built.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
built.marks("TS29.212", "AN-GW-Address")  # what each table marks about it
built.holes("TS32.299")  # what the corpus cannot complete
built.undefined("TS29.345")  # the names its Undefined AVP blocks declare
built.across_releases()  # what citations resolved across releases
built.registry(ast.RegistryKind.APPLICATION_IDS, 16777216)  # TS 29.230's say
```

The query set is small on purpose. `applications` groups a document's commands
by application id and the clause they sit under, since documents share one id
between interfaces (TS 29.273's SWa, STa and SWd). The id is the header's, or,
for commands whose headers print none, the one an `Application Scope` block
covering their clause states. A `Member` carries the ABNF rule as spelled,
markers included, and `min_occurs`/`max_occurs` as RFC 6733 section 3.2 reads
them. An `Enumerated` whose clause defines its values elsewhere carries the
citation in `values_source` and whatever values a correction supplied;
`vendor_specific` picks out the ranges a validator must allow under names the
document does not give.

The AST stays public underneath: `parser.parse(text)` reads one file,
discarding `;;` comments, and `parser.parse_with_comments(text)` returns the
comments too, for `formatter.format_spec(spec, comments)` to write back.

**Resolution.** A name resolves, in order, to the document's own
definition, then to the origin its re-used table cites (recursively, so an
indirect citation lands on the real definition), then to an AVP-table row,
then to a `; Bases:` document. Local over re-used makes an extension mean
what the extending document says, while a plain re-print resolves through
the origin. A name tabulated in several of one file's AVP tables takes its
table facts from the first row in file order; `table_rows` returns every
copy. The model never reports the conflicts this order papers over; run
the linter for those. Origins resolve by the rules in
[linter.md](linter.md#resolving-an-origin) and
[below](#resolution-across-releases).

**The citing table's flag rules.** Flag rules are the application's: RFC
6733 section 4.1 has the M bit set "according to the rules defined in the
application specification that introduces or reuses this AVP". So where a
document re-uses an AVP and its own AVP tables state flag cells for it,
those cells outrank every other reading when the name resolves through
that document. They count per flag: each flag is where the first of the
document's rows placing it puts it. A re-used table's M-bit column ranks
below the document's AVP-table cells and above the origin: `MUST` puts M in
Must, `MUST-NOT` in Must not, and `-` says nothing. The origin still
supplies the code, type and vendor, names the defining document, and
supplies each flag no citing row places. An IETF reading stating no flags
takes the M bit as application-defined and V as Must not (RFC 6733 sections
4.1 and 4.1.1): its rules are a `model.FlagRules`, an `ast.AvpFlagRules`
with a fifth column, `application_defined`, holding M there rather than
guessing Must or May. A vendor reading stating none stays a hole. Resolution
through the origin is unchanged, so `identified` returns both readings of
such an identity. Examples: TS 29.229 table 6.3.0.1 puts M in Must for four
`Digest-*` AVPs RFC 4590 states no rule for; TS 29.272 table 7.3.1/2 marks
21 of TS 29.336's AVPs `MUST-NOT`.

A grouped AVP defined elsewhere keeps the defining document's body, but
each member the citing document defines, tabulates or re-uses is read
through it, with the precedence above, where that reading is the same
`(vendor-id, code)`; a member it says nothing of keeps the origin's
reading. The body names its members in the defining document's sense: TS
32.299's own `Originator` is (10415, 864), but its re-used
`M2M-Information`, oneM2M TS-0004's, holds oneM2M's `Originator`, (45687,
1008). A grouped member read through the citing document has its own
members read the same way. The linter's `reused-row-mismatch` reports each
disagreement, saying which side the model follows.

**Filling through.** A field the first reading leaves unstated comes from
the next reading along the order, if the two are the same AVP saying the
same thing: every field both state must be equal. The citing table's own
flag cells and its re-used row's M-bit take no part in this: they are laid
over the result afterwards, so they neither fill another reading nor
disagree with one. A table row's vendor is
its Vendor-ID cell where the table prints one, else its V flag: V under
Must not is IETF space, V under Must the file's `; Vendor-ID:`, and a row
stating neither agrees with any. A reading that disagrees fills nothing,
nor does any after it: the name stays a hole naming the disagreeing
document, rather than become one AVP assembled from two documents that
disagree about it.

**Marks.** `marks` returns, per row of a table printing mark columns, the
table's label and clause and the row's marks per column: a tuple of marks,
`()` where the cell prints a dash, None where it is blank. What they mean
is the document's legend, per label:

- `Acc-Type` (TS 29.212, 29.215): the IP-CAN access types the AVP applies
  to, `All` or a list.
- `Applicability`: the supported features the AVP belongs to, and in TS
  29.212 and 29.215 the function too (`CC`, `PC`, `Both`, `ADC`, `ABC`).
  Blank is the base functionality.
- `Reference-Points` (TS 29.061 table 9a): `Gi`, `Sgi`.
- `ACR`, `ACA`, `CCR`, `CCA` (TS 32.299): whether the AVP is used in that
  command; `()` for the dash clause 7.1.0 reads as "not used".

None of these names an interface. A document tabulating several interfaces
gives each its own tables, so a row's interface is its table's clause.

**The registry.** `registry(kind, code)` returns what the corpus's
registries say of a code, as `model.Allocation`s naming the registry
document, table and clause. It is evidence beside the model, not a reading
of it: no `Avp`, `Message` or `Application` takes anything from it, and
the linter's `registry-*` rules report where documents and registry differ.

### Resolution across releases

The corpus holds one copy of each document per release tree, and a citation
means the copy the drafting rules on references say it means. A *specific*
reference, whose entry in the citing document's references clause names a
version or a release, means that version (3GPP TR 21.801 clause 6.6.6.5.2;
ETSI SR 001 262 clause 12). A reference naming a release means its last
version. A *non-specific* reference means the latest version in the citing
document's release (TR 21.801 clause 6.6.6.5.3, and every 3GPP document's
clause 2), which is the match-major-take-newest rule; for a document
outside 3GPP, the latest version there is. Neither rule says what a
non-specific 3GPP reference means when the cited document ended before the
citing document's release; the corpus reads it as the document's final
version.

So `corpus.Corpus.resolution` takes, in order: a specific reference's named
version and no other; the newest copy in the citing document's major
version; and failing one, a later release's copy standing in by an
evidenced entry, or the cited document's final version when it ended in an
earlier release. The `.dad` grammar names no versions, so the facts this
needs live in `corpus.py`, each entry citing its source:

- `CITED_VERSIONS`: the version a specific reference names, keyed by
  (citing, cited) document and read from the citing document's references
  clause (TS 183 017's "3GPP TS 29.209 Release 6", oneM2M TS-0004's "3GPP
  TS 32.299 (Release 11)").
- `FINAL_VERSIONS`: documents that ended before the citing release (TS
  29.140 V7.0.0, TS 29.209 V6.8.0).
- `CITED_REVISIONS` and `STAND_INS`: a 3GPP2 revision letter a citation
  names, and the held revision answering for it with the evidence that the
  cited one is out of reach (TS 29.212 cites X.S0057-B; 3GPP2 publishes
  revision 0 alone, checked 2026-10-30).
- `RELEASE_STAND_INS`: keyed by citing document, citing version and cited
  document, a later release's copy answering for a release version the
  corpus lacks, with the evidence that both define alike everything the
  citing copy re-uses. TS 32.299 V11.20.0's six Release 11 references, and
  TS 29.210's and TS 29.234's of TS 29.229, are answered by Release 18
  copies so. Where the releases differ, the older version is pinned
  instead: TS 29.212 V11.19.0 and TS 29.214 V11.16.0 for TS 32.299
  V11.20.0, and TS 29.061 V6.15.0 for TS 29.210, whose table puts M in
  Must on three AVPs Release 18 forbids it on.

Every version these name is a catalog pin the downloader checks against
the 3GPP archive on each download ([downloader.md](downloader.md)). An
`Avp` or `Hole` that took a field from such a copy carries
`across_releases`, a `corpus.CrossRelease` naming the citing and cited
documents, the version and the rule; `across_releases()` lists them for a
reader to audit, and the linter's `cross-release-origin` note says the same
per file. An older copy answers only through a citation: reference-level
queries (`avps`, `holes`, `references`) read the newest copy of each
document.

**Holes.** An `Avp` has every field: code, type and flag rules are facts
some document states, or RFC 6733's rule for an IETF AVP's unplaced bits,
never `None`. A name the corpus cannot complete is a `model.Hole` instead,
naming the document that falls short and the fields it leaves unstated
(`code`, `data_type`, `flag_rules`), `definition` when the name resolves
nowhere, or `undefined` when an `Undefined AVP` block declares it so, plus
the re-used origin the corpus lacks or the disagreeing reading, if either
applies. `Member.avp` is `None` for a hole and `Member.hole` says which;
the `* [ AVP ]` wildcard, and a placeholder under that policy, are the
only `None`s without a hole. A hole keeps the
vendor, code, type and flag rules its document states, but not a grouped
AVP's members or an enumerated AVP's values; a consumer that wants those
reads the AST through `table_rows` or `corpus.Entry.spec`.

**Wireshark's names.** Built with `dictionary=`, the model fills
`Avp.wireshark_name` and `Hole.wireshark_name` with Wireshark's name for
the identity. `name` is always the document's spelling
([oracle.md](oracle.md#in-the-model)).

### Known holes

Thirteen names stand as holes, each a statement its source does not make.
The committed record, the corpus's `holes.toml`, lists them by
`Hole.document`, name, `Hole.missing` and a reason citing the version and
clause and what was searched
([corrections.md](corrections.md#the-record-of-known-holes)). The file sits
beside the `.dad` files because a consumer loads the corpus, not the edit
layers: `corpus.Corpus.load` reads it into `Corpus.record` for the directory
holding it directly. A file list or a subdirectory has no record, and neither
has a raw corpus.

| `strict` | A hole the record lists | A hole it does not | An entry naming no hole |
|---|---|---|---|
| `None` (default) | builds; `Hole.recorded` its reason | `IncompleteCorpusError` | `StaleHoleRecordError` |
| `True` | `IncompleteCorpusError` | `IncompleteCorpusError` | not read |
| `False` | builds; `Hole.recorded` its reason | builds | not read |

A recorded hole stays a hole: `holes()` reports it, `resolve` returns None,
and `Hole.recorded` holds the entry's reason. The default fails on a stale
entry so that working a hole off forces the record to shrink. An entry
going unused only because the build's `undefined` policy answered for its
name is not stale. `strict=True` is absolute, and `strict=False` is for a
consumer loading a partial or foreign corpus. `unrecorded_holes()` and
`stale_record_entries()` return what the default would refuse; the linter's
`unrecorded-hole` and `stale-hole-record` report the same.

The thirteen, by cause:

- **A field no source states**, under every policy. TS 29.061's
  `3GPP-Session-Stop-Indicator` row states only a code, and TS 29.061
  V6.15.0 numbers `3GPP-GPRS-Negotiated-QoS-Profile` and
  `3GPP-SGSN-MCC-MNC` as RADIUS sub-attributes without tabulating them. TS
  29.234's `Charging-Characteristics` is typed "Integer", no Diameter type.
- **The nine names that resolve nowhere**, the corpus's `Undefined AVP`
  blocks ([below](#undefined-names)), holes under the default policy and
  the consumer's to answer for under another.

### Undefined names

Nine names the corpus's documents use as members are defined nowhere: RFC
4004's three SPIs, TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`,
TS 29.154's `External-Group-Identifier`, TS 32.299's `Submission-Timestamp`
and `Network-Element`, and TS 29.234's `Error-Cause`. Each has an
`Undefined AVP` block in its document's file, inserted by a correction
citing what was searched, and `undefined(reference)` returns them as
`model.Undefined`: the name, the document, the clause, what the document
says of the name, and every clause whose body names it. A block is the last
reading of its name, after the bases: a definition appearing upstream wins
without it, and the linter's `undefined-avp-defined` reports the stale
block.

What the model makes of such a name is the consumer's choice,
`Model.build(books, undefined=model.UndefinedPolicy.…)`:

| Policy | `resolve` | `hole` | Body member | `holes()` | `strict=True` |
|---|---|---|---|---|---|
| `HOLE` (default) | None | missing `undefined` | `Member.hole` | lists it | refuses |
| `DROP` | None | None | removed; `Grouped.dropped`, `Message.dropped` keep it | no | builds |
| `PLACEHOLDER` | None | None | in place, `Member.placeholder` a `model.Placeholder` | no; `placeholders()` | builds |
| `SUPPLY`, supplied | the consumer's `Avp`, `supplied` its source | None | `Member.avp` | no | builds |
| `SUPPLY`, `Alias` | the named AVP, unchanged | None | `Member.avp`, `Member.alias` the `Alias` | no | builds |
| `SUPPLY`, neither | as `HOLE` | | | | |

Only a name a block declares is open to the choice. A name resolving
nowhere without one is a corpus defect (the linter's
`unresolved-reference`), and a field no reading states stays a hole under
every policy. A non-default policy is an explicit answer, so the answered
names are no holes, and `strict=True, undefined=PLACEHOLDER` builds
wherever nothing but such names is a hole.

`DROP` removes required members too: RFC 4004's SPIs and TS 29.154's
`External-Group-Identifier` are required, so a command built so no longer
carries what its ABNF requires. `dropped` keeps each member's `rule` for a
consumer that checks; where a dropped member is required, `SUPPLY` is the
better answer.

`SUPPLY` takes `supply=`, a mapping from a name, or `(reference, name)`,
which wins over it, to a `model.Supplied` or a `model.Alias`. A `Supplied`
states vendor, code, type, flag rules and `source`, mandatory provenance
("ACME HSS 4.2 dictionary"), with members for a Grouped AVP and values for
an Enumerated one. Its `Avp` names the block's document in `defined_in`,
carries the source in `supplied`, and resolves its members in the block's
document. An `Alias` reads the name as an AVP the corpus completes: TS
29.154's `External-Group-Identifier` as TS 29.336's `External-Identifier`,
which carries an external group identifier on S6t and is most likely what
TS 29.154's editors meant, though the corpus does not assume it.
`model.supplied_from(*paths)` reads `Supplied`s from hand-authored `.dad`
sidecars: each `Grouped AVP` or `Enumerated AVP` section with its table
row, and each AVP-table row alone. A name two sidecars both supply is
refused.

The build refuses, with `ModelError`: `SUPPLY` without `supply=` and
`supply=` under another policy; a key naming no block, since it is a typo
or upstream has since defined the name; an `Alias` to a name the corpus
does not complete; a `Supplied` claiming the `(vendor-id, code)` of an AVP
the corpus defines, or two names' `Supplied`s claiming one, since a
dictionary with two names on one identity is worse than a hole; and a cycle
of aliases. `undefined_policy` reports the build's policy, which a
generator records in its output.

## The integrations

Each target gets a directory under `integrations/`; scripts carry PEP 723
inline metadata naming their dependencies, so uv supplies everything:

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 -o out/
```

### python-diameter

[python-diameter](https://github.com/mensonen/diameter) folds every use of
a command into one class, so "is this class right?" has no single answer;
`validate.py` checks one document's claims at a time. That document's
commands must exist under the right codes, each direction's `avp_def` must
cover the ABNF's members matched by `(vendor-id, code)`, `is_required`
must agree with the brackets, and the document's own AVPs must be right in
the library's global dictionary. An "extra AVP" may be another document's
legitimate use of the same command class. A known hole is checked on what
its document states, and one with no `(vendor-id, code)` is reported as
unchecked.

`generate.py` is the other direction: one module per application and
interface, whose command classes carry that document's own members and are
written the way the library writes its own, so the library can carry them
beside its merged classes. What its dictionary lacks, or types otherwise
than the document, goes to an `additions.py` in the dictionary's shape.
Holes stay in the tables with their reason, and `--undefined` (with
`--supply` sidecars) passes the model's policy for undefined names. The
ABNF decides a class's members, and the tables' marks are comments on
them. The [README](../integrations/python_diameter/README.md) covers the
layout, the additions, how the library would adopt the modules, and what
its shape cannot carry.
