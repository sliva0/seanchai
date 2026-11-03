# Consumers: the model and the integrations

`seanchai` needs Python 3.14. Install it with the corpus and every snippet here
runs as it stands:

```sh
pip install "seanchai[corpus]"
```

## Recipes

### Generate a dictionary

`Application.avps()` is the closure of what an application's commands use, at
any depth, whichever document defines it. `Model.avps(reference)` is something
else: what a document's own tables list. Cx's commands use 104 AVPs and TS
29.229's tables list 82: RFC 6733's `Destination-Host` is in no table of TS
29.229's. Generate a dictionary from `Application.avps()`, or from
`Message.walk()` for one command.

```python
import seanchai
from seanchai import corpus, model

books = corpus.Corpus.installed()
built = model.Model.build(books)
(cx,) = built.applications("TS 29.229", application_id=16777216)

# Record both versions: the generated output depends on both.
print(f"# seanchai {seanchai.__version__}, corpus {books.version}")

dictionary = {}
for member in cx.avps():
    if member.avp is not None:
        # A citing table can read one AVP two ways: keep one per identity.
        dictionary.setdefault(member.avp.identity, member.avp)
    elif member.hole is not None:
        # A name the corpus cannot complete; the hole says what it lacks.
        print(f"# skipped: {member.hole}")
    # Neither: the `* [ AVP ]` wildcard, which is grammar and not an AVP.

for (vendor_id, code), avp in sorted(dictionary.items()):
    rules = avp.flag_rules
    # M is in Must, May or Must not; or RFC 6733 leaves it to the application.
    open_m = model.AvpFlag.MANDATORY in rules.application_defined
    mandatory = "app" if open_m else model.AvpFlag.MANDATORY in rules.must
    print(vendor_id, code, avp.name, avp.data_type, mandatory)
    if isinstance(avp, model.Grouped):
        print("  holds", [member.name for member in avp.members])
    elif isinstance(avp, model.Enumerated):
        print("  values", len(avp.values))
```

### Look up one AVP

`definition` takes a name or a `(vendor-id, code)` and returns the defining
document's reading. `find` returns every reading, since a citing document's
table can change the flags; `Avp.read_through` names the table that did.

```python
from seanchai import model

built = model.Model.installed()

avp = built.definition("Session-Id")
print(avp.identity, avp.data_type, avp.defined_in, avp.flag_rules.to_dict())

for reading in built.find("Session-Id"):
    print(reading.read_through, reading.flag_rules.to_dict())

# As one document means it, which is the reading its commands hold:
print(built.resolve("TS29.229", "Session-Id"))

# A name two AVPs claim raises `ModelError`; ask by identity instead.
print(built.definition((45687, 1008)))
```

### List an application's commands

```python
from seanchai import model

built = model.Model.installed()

for application in built.applications("TS 29.212"):
    print(application.name, application.application_id, application.clause)
    for message in application.messages:
        kind = "request" if message.is_request else "answer"
        print(" ", message.abbreviation, message.command_code, kind)
```

## Without Python

Most Diameter stacks are not Python. An installed `seanchai[corpus]` answers
from the command line, with no checkout and no downloads:

```sh
seanchai show Session-Id          # the defining document's reading, and others
seanchai show 10415:601 --json    # by VENDOR:CODE; --document REF for its reading
seanchai commands TS29.229        # code, request or answer, id, document, section
seanchai commands --application 16777216 --json
seanchai dictionary -o cx.json --application 16777216
```

`seanchai dictionary` writes one JSON file to generate from, compact with sorted
keys: the same corpus and options give the same bytes. `--document REF` and
`--application ID` narrow it, each repeatable. `--application` leaves what its
commands use; `--document` alone also keeps what the document's tables list.
`--policy` is the [undefined-name policy](#undefined-names), `hole` by default:
`drop`, `placeholder`, or `supply` with `--supply SIDECAR.dad`. Every field is
always written, null or empty where it says nothing, and `seanchai.dictionary`
holds the shape as pydantic models.

```text
format_version     2, changes when a reader would have to
seanchai_version, corpus_version, undefined_policy
documents, application_ids    what was selected; no ids is every application
applications[]     reference, application_id, clause, name, stated_in
  commands[]       name, abbreviation, command_code, is_request, flags,
                   application_id (on the wire), header_application_id,
                   defined_in, section, members[], dropped[], walk[]
avps[]             id, defining, kind (plain, grouped, enumerated), name,
                   vendor_id, code, data_type, flag_rules, defined_in, section,
                   read_through, completed_by, across_releases, supplied,
                   members[], dropped[], values[], values_source
holes[]            id, name, reference, version, missing, what it does state,
                   recorded (the reason)
value_tables[]     kind (result-codes, bits, features), avp, avp_id, reference,
                   version, vendor_id, section, page, table, application,
                   feature_list_id, rows[]
```

- A member is `name`, `presence` (`fixed`, `required`, `optional`),
  `min_occurs`, `max_occurs` (null is unbounded) and `kind`: `avp` names an
  `avps[].id` in `avp`, `hole` a `holes[].id` in `hole`, `placeholder` holds its
  block, and `wildcard` is the `* [ AVP ]` line. `alias` is set for a
  `model.Alias`.
- `walk` is `Message.walk`: every AVP `id` the command reaches, at any depth.
- An AVP `id` is `vendor:code`. A citing table can read an identity otherwise,
  and a command means its document's reading, so each further reading the
  selection holds is `vendor:code#2` and on. `defining` marks the defining
  document's. A generator wanting one entry per identity takes those with no
  `#`, as [the recipe](#generate-a-dictionary) does.
- `values[]` holds `kind` (`value`, `reserved`, `vendor-specific`), `name`,
  `value`, `first`, `last`, `description`.
- `dropped` is what `--policy drop` took out, each naming its hole.
- `value_tables[]` are the selected documents', and with `--application` those
  of the documents holding one. `avp_id` names the `avps[]` entry the document's
  reading of `avp` is, null where the selection holds none: TS 29.212 numbers
  the bits of a `Feature-List` it never names otherwise. A row of `rows[]` holds
  `name`, `value`, a result code's own `section`, and a feature's `mark`, the
  M/O column.

## Installing the corpus

The library and the corpus are two packages. `seanchai` holds no data, and
`seanchai-corpus` holds nothing else and depends on nothing, so a consumer's
CI pins each on its own:

```sh
pip install seanchai seanchai-corpus   # or "seanchai[corpus]"
```

`corpus.Corpus.installed()` loads the installed corpus with no path, record
of known holes included, and `installed(raw=True)` its raw mirror. Without the
package it raises `corpus.CorpusNotInstalledError`, naming the package.
`corpus.Corpus.load(path)` loads any other directory or file, or a list of them.
A file named twice counts once, and two files claiming one document, version and
3GPP2 revision raise `corpus.CorpusError` naming both, since which one answers
would depend on the order they were given in.

`seanchai_corpus.CORPUS_DIR` is the directory itself. `Corpus.version` is the
corpus package's version, the date it was regenerated, when `installed()` loaded
it, and None for any other corpus. `seanchai.__version__` is the library's. In
this repository the package is installed from the workspace, so the installed
corpus is the committed one.

Everything the library refuses derives from `seanchai.SeanchaiError`.

## The model

The AST mirrors a file one-to-one and may contradict itself. `model.Model`
is the opposite contract: built once from a `corpus.Corpus`, it hands a
consumer a `Message` whose members point at real `Avp` objects, a
`Grouped` that enumerates its members, an `Enumerated` with its values, and
every AVP knowing its `(vendor-id, code)`, type, flag rules and defining
document.

```python
from seanchai import model

# Strict against the corpus's holes.toml; dictionary="specifications/wireshark"
# adds Avp.wireshark_name. `Model.build(books)` is the same over any corpus.
built = model.Model.installed()
built.references()  # every document, a tuple as every query returns
built.canonical("ts 29.229")  # how it spells a reference: TS29.229
built.messages("TS29.229")  # bodies resolved; no reference: the whole corpus
built.applications("TS29.212")  # commands per application and interface
built.applications(application_id=16777216)  # one id, across documents
built.avps("TS29.229")  # what a document's tables list; no reference: all
built.resolve("TS29.229", "DRMP")  # one name in one document's reading
built.definition("Public-Identity")  # the defining document's reading
built.find("Public-Identity")  # every reading under a name
built.identified(10415, 601)  # every reading claiming an identity
built.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
built.marks("TS29.212", "AN-GW-Address")  # what each table marks about it
built.holes("TS32.299")  # what the corpus cannot complete; no reference: all
built.undefined("TS29.345")  # the names its Undefined AVP blocks declare
built.across_releases()  # what citations resolved across releases
built.registry(model.RegistryKind.APPLICATION_IDS, 16777216)  # TS 29.230's say
built.value_tables("TS29.272", avp="ULR-Flags")  # the numbers a document names
built.value_tables(kind=model.ValueKind.FEATURES)  # one kind, the whole corpus
built.feature_lists()["S6a/S6d", 1]  # a feature list, by application and list id
built.definition("ULR-Flags").value_table  # the bits, read through resolution
```

The query set is small on purpose. A reference may be spelled "TS 29.229",
"ts29.229" or "3GPP TS 29.229"; one the corpus lacks raises `ModelError`
suggesting close ones. `applications` groups a document's commands
by application id and the clause they sit under, since documents share one id
between interfaces (TS 29.273's SWa, STa and SWd). `Message.application_id` is
the id on the wire: the header's, or, for commands whose headers print none, the
one an `Application Scope` block covering their clause states.
`header_application_id` keeps what the header prints, and `is_request` reads its
R bit. A `Member` carries the ABNF rule as spelled,
markers included, and `min_occurs`/`max_occurs` as RFC 6733 section 3.2 reads
them. An `Enumerated` whose clause defines its values elsewhere carries the
citation in `values_source` and whatever values a correction supplied;
`vendor_specific` picks out the ranges a validator must allow under names the
document does not give. Every model type has a one-line `repr` and a `to_dict()`
for `json.dumps`, with its flags sorted.

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
4.1 and 4.1.1). `Avp.flag_rules` and `Hole.flag_rules` are always a
`model.FlagRules`: an `ast.AvpFlagRules` with a fifth column,
`application_defined`, holding M there rather than guessing Must or May and
empty everywhere else. A table row's rules stay the AST's and compare equal only
through `model.FlagRules.printed(row.flag_rules)`. A vendor reading stating
none stays a hole. Resolution
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
disagree about it. `Avp.completed_by` names the document stating each field
`defined_in`'s reading leaves unstated: through TS 29.329, `Wildcarded-IMPU` is
TS 29.229's, whose clause states no code, vendor or flags, and those are TS
29.329 table 6.3.1's.

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

**Value tables.** `value_tables` returns what a document names a numeric AVP's
numbers, as `model.ValueTable`s: `kind` (`ValueKind.RESULT_CODES`, `BITS` or
`FEATURES`), the `avp`, the document, its clause and page, the table's label,
and `rows`, each an `ast.ValueRow` with a `name`, a `value` and, for a result
code in a subclause its `section`, for a feature its M/O `mark`. A plain
`Result-Code` table's `vendor_id` is 0 and any other's the file's `;
Vendor-ID:`, the space an experimental code lives in. A plain AVP reads them
through resolution: `Avp.value_tables` holds the tables the reading document
prints for the name, or failing any its origin's, and `Avp.value_table` the
first. `definition("ULR-Flags")` exposes its bits, `definition("Result-Code")`
RFC 6733's codes, and `resolve("TS29.229", "Experimental-Result-Code")` TS
29.229's, though RFC 6733's AVP is the one it reads. A document's table is no
part of the AVP's identity, and makes no second reading of it. `feature_lists`
keys the feature tables naming an application by `(application,
feature_list_id)`, spelled as the caption does, and of two documents printing
one list the first in reference order answers.

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
outside 3GPP, the latest version there is. ETSI's clause 2.1 says the same of
the documents it cites ("the latest edition of the referenced document"), and
`LATEST_EDITIONS` reads that citation by citation. Neither rule says what a
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
  TS 29.210's and TS 29.234's of TS 29.229, are answered by Release 19
  copies so, as is ETSI TS 183 033's of TS 29.229 V6.6.0, a version it names
  that the catalog cannot pin, being no release's last. Where the releases
  differ, the older version is pinned
  instead: TS 29.212 V11.19.0 and TS 29.214 V11.16.0 for TS 32.299
  V11.20.0, and TS 29.061 V6.15.0 for TS 29.210, whose table puts M in
  Must on three AVPs Release 19 forbids it on.

Every version these name is a catalog pin the downloader checks against
the 3GPP archive on each download ([downloader.md](downloader.md)). An
`Avp` or `Hole` that took a field from such a copy carries
`across_releases`, a `corpus.CrossRelease` naming the citing and cited
documents, the version and the rule; `across_releases()` lists them for a
reader to audit, and the linter's `cross-release-origin` note says the same
per file. An older copy answers only through a citation: reference-level
queries (`avps`, `holes`, `references`) read the newest copy of each
document. Corpus-wide lookups (`find`, `definition`, `identified`, `avps()`)
also know an identity only an older copy holds, where a citation reaches it, so
`show` answers for every identity `seanchai dictionary` writes: TS 32.299
V11.20.0's `WLAN-Information`, through oneM2M TS-0004's `Service-Information`.

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

Seventeen names stand as holes, each a statement its source does not make.
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

The seventeen, by cause:

- **A field no source states**, under every policy. TS 29.061's
  `3GPP-Session-Stop-Indicator` row states only a code, and TS 29.061
  V6.15.0 numbers `3GPP-GPRS-Negotiated-QoS-Profile` and
  `3GPP-SGSN-MCC-MNC` as RADIUS sub-attributes without tabulating them. TS
  29.234's `Charging-Characteristics` is typed "Integer", no Diameter type. TS
  29.229's `Wildcarded-IMPU` states a type alone, though TS 29.329's reading of
  it is complete. ETSI TS 183 020's `Privacy-Indicator` states a code, a type
  and members and no flag rule, TS 183 066's table 7.4 printing its own only
  for its own interface.
- **An origin the corpus does not hold.** RFC 6736 table 3 re-uses
  `Egress-VLANID` from RFC 4675, a RADIUS document.
- **The twelve names that resolve nowhere**, the corpus's `Undefined AVP`
  blocks ([below](#undefined-names)), holes under the default policy and
  the consumer's to answer for under another.

### Undefined names

Eleven names the corpus's documents use as members are defined nowhere: RFC
4004's three SPIs, RFC 5866's `Authorization-Session-Volume`, TS 29.345's
`ProSe-Query-Code` and `ProSe-Response-Code`, TS 29.154's
`External-Group-Identifier`, TS 32.299's
`Submission-Timestamp` and `Network-Element`, TS 29.234's `Error-Cause` and TS
29.061's
`Delegated-IPv6-Prefix`, a RADIUS attribute of RFC 4818, which the corpus does
not hold. Each has an
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
document. An `Alias` reads the name as an AVP the corpus completes, with its
`source` too: TS 29.154's `External-Group-Identifier` as TS 29.336's
`External-Identifier`, which carries an external group identifier on S6t and is
most likely what TS 29.154's editors meant, though the corpus does not assume
it.

```python
from seanchai import model

built = model.Model.installed(
    undefined=model.UndefinedPolicy.SUPPLY,
    supply={
        "External-Group-Identifier": model.Alias(
            "TS29.336", "External-Identifier", source="our reading of TS 29.154"
        ),
        ("TS29.345", "ProSe-Query-Code"): model.Supplied(
            vendor_id=10415,
            code=59999,
            data_type=model.DataType.OCTET_STRING,
            flag_rules=model.FlagRules(must=frozenset({model.AvpFlag.VENDOR})),
            source="ACME HSS 4.2 dictionary",
        ),
    },
)
print(built.resolve("TS29.154", "External-Group-Identifier"))
print(built.resolve("TS29.345", "ProSe-Query-Code").supplied)
```

`model.supplied_from(*paths)` reads `Supplied`s from hand-authored `.dad`
sidecars: each `Grouped AVP` or `Enumerated AVP` section with its table
row, and each AVP-table row alone. A name two sidecars both supply is
refused, and so is a row contradicting its definition's code, type or vendor,
or its V flag contradicting its vendor; the error lists every such fact.

The build refuses, with `ModelError`: `SUPPLY` without `supply=` and
`supply=` under another policy; a key naming no block, since it is a typo
or upstream has since defined the name; an `Alias` to a name the corpus
does not complete; a `Supplied` claiming the `(vendor-id, code)` of an AVP
the corpus defines, or two names' `Supplied`s claiming one, since a
dictionary with two names on one identity is worse than a hole; and a cycle
of aliases. `undefined_policy` reports the build's policy, which a
generator records in its output.

## The export

`seanchai export -o DIR` writes the resolved corpus as JSON for a consumer with
no Python, the static site first. Run from an installed `seanchai[corpus]`, it
needs no checkout and no downloads. `seanchai.export.export_corpus(books,
output)` is the same from Python, and `seanchai.export_schema` holds the shape.
The file layout and fields are in [website.md](website.md#data-boundary).

## The integrations

Each target gets a directory under `integrations/`; scripts carry PEP 723
inline metadata naming their dependencies, so uv supplies everything:

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 -o out/
```

The scripts name `seanchai` and `seanchai-corpus` from this repository, so
they read the committed corpus unless `--corpus` names another.

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
