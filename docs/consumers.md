# Consumers: the model and the integrations

`seanchai` needs Python 3.12 or newer. With the corpus installed, every
snippet here runs as it stands:

```sh
pip install "seanchai[corpus]"
```

## Recipes

### Generate a dictionary

`Model.reached` gives one entry per `(vendor-id, code)` that applications,
commands or error answers reach, at any depth, whichever document defines
it. Cx's commands reach RFC 6733's `Destination-Host`, which no table of TS
29.229 lists. An entry holds the defining document's reading, every distinct
reading met with the member paths it is met at, the value tables met with it,
the defining reading's result codes, which a reading listing codes of its own
sets aside (TS 29.212's Result-Code carries its clause 5.5 in place of RFC
6733's 7.1, which Gx's answers carry too), and `conflicts`, the fields in
which those readings disagree. `Member.avp` stays the reading at each member.

```python
import seanchai
from seanchai.corpus import Corpus
from seanchai.model import AvpFlag, Enumerated, Grouped, Model

corpus = Corpus.installed()
model = Model.build(corpus)
(cx,) = model.applications("TS 29.229", application_id=16777216)
# What Cx's answers hold in place of their bodies when the E bit is set.
error_answer = model.answer_message("TS 29.229")

# Record both versions: the generated output depends on both.
print(f"# seanchai {seanchai.__version__}, corpus {corpus.version}")

for command in cx.commands:  # request and answer, paired by code
    for message in (*command.requests, *command.answers):
        # `< >` is a fixed position, `{ }` required and `[ ]` optional.
        print(message.abbreviation, message.command_code, message.is_request)
        for member in message.avps:
            print(" ", member.name, member.rule.presence, member.max_occurs)

for member in (*cx.walk(), *error_answer.walk()):
    if member.hole is not None:
        # A name the corpus cannot complete; the hole says what it lacks.
        print(f"# skipped: {member.hole}")
    # Neither avp nor hole: the `* [ AVP ]` wildcard, grammar and not an AVP.

for entry in model.reached(cx, error_answer):
    avp = entry.readings[0].avp
    if entry.conflicts:
        # The readings met disagree, as where a citing table sets other
        # flags: a backend keeping one per AVP chooses here.
        for met in entry.readings:
            print("#", avp.name, met.avp.read_through, met.paths[0])
    rules = avp.flag_rules
    # M is in Must, May or Must not; or RFC 6733 leaves it to the application.
    open_m = AvpFlag.MANDATORY in rules.application_defined
    mandatory = "app" if open_m else AvpFlag.MANDATORY in rules.must
    print(avp.vendor_id, avp.code, avp.name, avp.basic_type, mandatory)
    if isinstance(avp, Grouped):
        print("  holds", [member.name for member in avp.members])
    elif isinstance(avp, Enumerated):
        print("  values", len(avp.values))
    for table in entry.value_tables:  # result codes, bits, this Cx's features
        print(" ", table.kind, table.reference, len(table.rows))
```

Under `UndefinedPolicy.SUPPLY` a supplied definition is a reading like any
other, its `supplied` naming the source ([undefined names](#undefined-names)).
`seanchai dictionary` writes the same as JSON
([the dictionary](#the-dictionary)).

### Look up one AVP

`definition` returns the defining document's reading of a name or a
`(vendor-id, code)`. `readings` returns every reading, because a citing
document's table can change the flags, and its interpretations add rules of
its own. `Avp.read_through` names the document whose table or reading did.

```python
from seanchai.model import Model

model = Model.installed()

avp = model.definition("Session-Id")
print(avp.identity, avp.data_type, avp.defined_in, avp.flag_rules.to_dict())

for reading in model.readings("Session-Id"):
    print(reading.read_through, reading.flag_rules.to_dict())

# As one document means it, which is the reading its commands hold:
print(model.resolve("TS29.229", "Session-Id"))

# A name two AVPs claim raises `ModelError`; ask by identity instead.
print(model.definition((45687, 1008)))
print(len(model.readings((0, 110))))  # RFC 4590's Digest-Qop, read two ways
```

### List an application's commands

```python
from seanchai.model import Model

model = Model.installed()

for application in model.applications("TS 29.212"):
    print(application.name, application.application_id, application.clause)
    for message in application.messages:
        kind = "request" if message.is_request else "answer"
        print(" ", message.abbreviation, message.command_code, kind)
```

## Without Python

An installed `seanchai[corpus]` answers from the command line, with no
checkout and no downloads:

```sh
seanchai show Session-Id          # the defining document's reading, and others
seanchai show 10415:601 --json    # by VENDOR:CODE
seanchai show Session-Id --document TS29.229   # as one document reads it
seanchai commands TS29.229        # code, request or answer, id, document, section
seanchai commands --application 16777216 --json
seanchai dictionary -o cx.json --application 16777216
```

`show --document REF --version V` reads an older copy of that document the
corpus holds. With `--json`, `show` and `commands` print the shapes
`dictionary` writes. All three are pydantic models in `seanchai.dictionary`,
under one `format_version`; `dictionary.json_schema()`, which
`seanchai dictionary --schema FILE` writes, describes them.

All three read the installed corpus, or with `--corpus PATH` (repeatable)
another. `--with PATH` (repeatable) reads your own `.dad` files beside it:
proprietary AVPs and commands. Such a file names a private document, its
`; Vendor-ID:` your vendor's and `; Bases: RFC6733` giving the base
protocol's AVPs:

```dad
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
        [ ULR-Flags ]


; Type: AVP Table
; Section: 2
; Columns: Name   Code   Type          Must   May   S.not   M.not
ACME-Token        1      OctetString   M,V    -     -       -


; Type: Reused AVPs
; Section: 2
; Columns: Name   From
ULR-Flags         TS29.272
```

Another of your files cites it as `Private-ACME-HSS`. A private document
follows no release, so `TS29.272` means the copy of the release read, the
newest by default.
`seanchai dictionary --with acme.dad --application 4242` then holds
ACME-Probe-Request, `ACME-Token` as `99999:1` and TS 29.272's `ULR-Flags`.
Over another corpus, or with `--with`, holes the corpus's record does not
list are allowed and listed in the output.

### The dictionary

`seanchai dictionary -o FILE` writes one compact JSON file with sorted keys.
The same corpus and options give the same bytes.

| Option | Keeps |
|---|---|
| `--document REF` | that document's applications; alone, also every AVP its tables list |
| `--version V` | with one `--document`, that held version of it |
| `--application ID` | that application's commands and the AVPs they use |
| `--strict` | nothing, and exits 1, if the selection reaches a hole |
| `--policy` | what becomes of [undefined names](#undefined-names): `hole` (default), `drop`, `placeholder` or `supply` |
| `--supply SIDECAR.dad` | the sidecar `--policy supply` reads |
| `--alias NAME REF TARGET` | for `--policy supply`, reads the undefined `NAME` as `REF`'s `TARGET` (`model.Alias`) |
| `--wireshark DIR` | each AVP's `wireshark_name` from Wireshark's dictionary |

`--document`, `--application`, `--supply` and `--alias` repeat. Every field
is always written, null or empty where it says nothing.

```text
format_version     2, changes when a reader would have to
seanchai_version, corpus_version, undefined_policy, strict
documents, version, application_ids   what was selected; no ids is every application
resolved[]         reference, version: every copy the output was read from
vendors[]          vendor_id, name, source, for each vendor id used
applications[]     id, reference, version, application_id, clause, name,
                   stated_in, commands[], pairs[], marks[]
  commands[]       name, abbreviation, command_code, is_request, flags,
                   application_id (on the wire), header_application_id,
                   defined_in, section, members[], dropped[], walk[],
                   answer_message
    elements[]     name, category, avps, either, printed, within, parents,
                   reference, version, section, table, page: its information
                   elements
    constraints[]  as constraints[] below: what its document read of its
                   members
    result_codes[] name, value, vendor_id, defined_in, reference, version,
                   section, table, page: the codes a table of its result
                   codes lists
  pairs[]          command_code, requests[], answers[]: indexes into commands
  marks[]          name, avp, table, section, marks: what the application's
                   tables mark about the names it reaches
answer_messages[]  id, defined_in, defined_version, section, read_through,
                   version, members[], dropped[], walk[], constraints[]
avps[]             id, defining, kind (plain, grouped, enumerated), name,
                   vendor_id, code, data_type, basic_type, flag_rules,
                   may_encrypt, defined_in, version, section, read_through,
                   completed_by, across_releases, supplied, wireshark_name,
                   members[], dropped[], values[], values_source
holes[]            id, name, reference, version, missing, what it does state,
                   recorded (the reason)
value_tables[]     kind (result-codes, bits, features, values), avp, avp_ids,
                   applications, reference, version, vendor_id, section, page,
                   table, application, feature_list_id, rows[]
constraints[]      interpreted, avp, avp_ids, command, application_id,
                   command_section, request_section, within, reference,
                   version, section, table, page, versions,
                   quoted_from_pdf, messages, readings[]: quotes, rules[]
conflicts[]        vendor_id, code, defining, fields, obsolete,
                   readings[]: avp, obsoleted_by, paths[]
```

- A member has `name`, `presence` (`fixed`, `required`, `optional`),
  `min_occurs`, `max_occurs` (null is unbounded) and `kind`. Kind `avp` names
  an `avps[].id` in `avp`; `hole` names a `holes[].id` in `hole`;
  `placeholder` holds its block; `wildcard` is the `* [ AVP ]` line. `alias`
  is set for a `model.Alias`. A command's own member has `elements`, indexes
  into the command's `elements[]` mapping it; a grouped AVP's member has
  none.
- `walk` lists every AVP `id` the command reaches, at any depth.
- An AVP `id` depends on the reading and the corpus, never on the selection
  (`dictionary.avp_id`). The defining document's reading, `defining`, is
  `vendor:code`. Another adds `@` and the document it is read through, then
  ` in DOCUMENT` where it is defined elsewhere and ` via DOCUMENT` where a
  citation outside the citing document's release reached it:
  `0:110@TS29.229 in RFC4590`, `10415:600@TS29.229 via TS29.234`. An older
  copy is spelled with its version, `TS32.299 V11.20.0`.
- `basic_type` is the RFC 6733 section 4.2 format `data_type` is carried in,
  `OctetString` for a `DiameterIdentity`. `may_encrypt` is the Encrypt cell
  of the table giving the flag rules, null where it prints none.
- `values[]` entries have `kind` (`value`, `reserved`, `void`,
  `vendor-specific`), `name`, `value`, `first`, `last` and `description`. No
  dictionary may assign a `reserved` or `void` value.
- `dropped` lists what `--policy drop` removed, each naming its hole.
- `answer_message` names the `answer_messages[]` entry an answer takes with
  the E bit set ([error answers](#error-answers)); it is null for a request.
  That entry's `id` is `read_through/defined_in:section`, as
  `TS29.272/RFC6733:7.2`, an older copy spelled with its version;
  `defined_version` is the version of the copy of `defined_in` a base
  resolved to where that is an older one, and `version` `read_through`'s.
- An application's `id` is `reference/clause/application_id`, `-` for no id.
- `value_tables[]` holds the tables of every reading the selection reaches and
  those the application's document prints for the names it reaches, as
  `Model.reached` gives them: S6a holds RFC 6733's result codes and TS 29.273's
  `Emergency-Services` bits, and Gx RFC 6733's codes beside TS 29.212's
  own. A features table is kept only for the applications whose feature
  list it numbers, since `Feature-List` means other features on each
  interface; `applications` names them, and `avp_ids`
  the readings carrying the table. Without `--application`, the documents'
  own tables are all kept. A row has `name`, `value`, a result code's own
  `section`, and a feature's `mark` (the M/O column).
- `conflicts[]` lists each identity the output reads two ways that disagree
  in a field a codec stores (`fields`: `flag_rules`, `may_encrypt`,
  `data_type`, `members`, `values`, `name`), each reading with the paths it
  is met at: `application` (null in an error answer), `command`, `section`
  and the member `names` down to it. A backend storing one flag rule per AVP
  chooses there. A reading's `obsoleted_by` names the documents of the corpus
  whose headers obsolete the one it is defined in or read through
  (`; Obsoletes:`); a conflict is `obsolete` when the other readings agree,
  so that only an obsoleted document dissents, as RFC 4005's `NAS-Port`
  against RFC 7155's. Such conflicts stay listed, since an application whose
  document cites the obsoleted RFC (TS 29.061 builds on RFC 4005) means that
  reading; a backend following the current documents skips them.
- `constraints[]` holds the interpreted constraints on the AVPs the output
  reaches, wherever the reading document reads them (`within` null) or as
  members of a grouped AVP (`within` its name, and `application_id` the
  application whose messages it holds in, where it holds in one only, which
  a dictionary of other applications leaves out), each naming the readings
  carrying it in `avp_ids`: the AVP's own, or the grouped AVP's. A command's
  `constraints` are its members', `avp_ids` the members of that name.
  `interpreted` is always true: a person read them in the clause's prose
  ([below](#interpreted-constraints)); `quoted_from_pdf` is true for a hand
  transcription's, its quotes held to the text of the PDF the document was
  copied from, there being no extracted source. A rule has `kind` and the
  fields its kind uses, the others null or empty: a length's `unit`, `low`
  and `high`,
  a range's `low` and `high`, exclude's `values`, an encoding's `codec` and
  an `element`'s `document`, `clause` and `element`, with `element_entry`,
  the element registry's entry for it or null where it has none (`title`,
  `check` in words, `depth`, `unchecked`, what it leaves and why, and
  `sources`, each `document`, `edition`, `clause` and `where`;
  [constraints.md](constraints.md#elements)), a predicate's
  `conditions`, alternatives each a list of conditions that must all hold,
  a default's `value`, a bits rule's `relation` and `bits`, a
  members rule's `relation` and `members`, a values rule's `values` and
  `conditions`, and an equals rule's `reference`; `unique` and `absent`
  have none. A condition names its AVP by `root` and `path`: `path` the
  names from the constraint's scope down to it, through the grouped AVPs
  it names, `root` null for a sibling or `request` for a member of the
  request the answer answers, printed at the constraint's
  `request_section`; it has `value` (a number, a name, or a reference,
  `root` and `path`, to the AVP whose value it tests against), `values`
  (an `in` list, one of whose values it holds: each a number, a name, or a
  range `{"low": 5000, "high": 5999}` of the numbers from `low` to `high`,
  empty for any other test) or `bit`, or none of them for presence, and
  `negated`, true where it must not hold. A reference is the same `root`
  and `path`.
- `resolved` lists each document copy an AVP, hole, table, application or
  error answer of the output comes from, cited copies included: the copy of
  the document printing an error answer that its base resolved to.

### One AVP

`seanchai show NAME --json` prints a `dictionary.Lookup`, indented:

```text
format_version, seanchai_version, corpus_version, undefined_policy
avp                the id of the reading asked for
avps[]             that reading first; then the identity's other readings, by
                   id; then every AVP their bodies name, at any depth
holes[]            what their bodies name and the corpus cannot complete
value_tables[]     those of the identity's readings, each with its avp_ids
constraints[]      those of the identity's readings, each with its avp_ids
```

Entries have the dictionary's shapes and ids, and every id a member names is
in the output.

```json
{
  "format_version": 2,
  "corpus_version": "2026.11.12",
  "undefined_policy": "hole",
  "avp": "0:110@TS29.229 in RFC4590",
  "avps": [
    {"id": "0:110@TS29.229 in RFC4590", "defining": false,
     "name": "Digest-Qop", "read_through": "TS29.229", "...": "..."},
    {"id": "0:110", "defining": true, "name": "Digest-Qop",
     "read_through": "RFC4590", "...": "..."}
  ],
  "holes": [],
  "value_tables": [],
  "...": "..."
}
```

### What changed

`seanchai diff OLD NEW` compares two versions of a document as a stack sees
them: two `.dad` files, each read in the installed corpus (or `--corpus`) in
place of its copy, or two corpus directories. Extract an older version into
a scratch directory first
([development.md](development.md#version-upgrades)):

```sh
seanchai corpus download --spec TS29.272 --version 18.6.0
seanchai corpus regenerate --spec TS29.272 -o old \
    --manifest specifications/versions/TS29.272/18.6.0/manifest.json
seanchai diff old/3gpp/rel-18/29272-i60.dad NEW.dad
```

```text
TS29.272 18.6.0 -> TS29.272 18.7.0: 0 breaking, 0 compatible, 16 editorial

editorial
  element-renamed    TS29.272 16777251/ULR element Supported-Features:
    Supported Features (See 3GPP TS 29.229 [9]) -> Supported Features (See
    TS 29.229 [9])  [document, TS29.272 5.2.1.1.1]
```

Commands match by application id, command code and direction, AVPs by
`(vendor-id, code)` and the document reading them, members by the AVP they
name, values and table rows by number, information elements by the AVPs
they map to. A changed name is a rename. Each change has an impact:

| Impact | Changes |
|---|---|
| `breaking` | a command, required member, AVP, value or row removed; a required member added; presence, occurrence or the order of fixed members changed; the M or V bit's rule, the basic type, the command flags changed; a value voided; an information element's category to or from M; an interpreted rule replaced by another; a hole reached |
| `compatible` | a command, optional member, AVP, value or row added; a derived type over the same basic type; another flag's rule; a category changed between any two but M; an interpreted rule read or dropped; a hole closed |
| `editorial` | a rename; the Encrypt cell; an element added or removed beside the ABNF; a result code a table lists added or removed; a text-only rule or a quote |

Every change names the command paths it affects, down from the command
(`S6a/ULR > Subscription-Data > AMBR`), and where each side states it. Where
both files have their raw mirror beside them, a `raw/` tree as
`corpus regenerate -o` writes, or both corpora theirs, each change says
where it comes from: `document` where the raw files differ the same way and
the version moved, `extraction` where they differ and it did not,
`corrections` where they agree. A name one side leaves a hole is reported
once, as the hole.

`--json` prints a `diff.Diff`, keys sorted, and `--schema FILE` writes its
JSON Schema. From Python, `seanchai.diff.diff(old_model, new_model,
documents=..., raw=(old_raw_corpus, new_raw_corpus))` returns it,
`diff.compare` compares two dictionaries, and `diff.overlay(corpus, files)`
reads a file in place of a corpus's copy.

### Test messages

`seanchai vectors -o FILE.json` writes test messages for a stack's own test
suite, per command of the selection (`--application`, `--document`):

- `minimal`: the fixed and required members only, a grouped AVP filled the
  same way at any depth;
- `maximal`: every optional member too, a repeatable one twice;
- `negative`: one per rule broken, each from the minimal or maximal message
  with one thing changed: a required AVP missing, an AVP once too often, a
  fixed AVP out of place, the M bit clear where it must be set, the V bit
  set on an IETF AVP, a reserved or void Enumerated value, a bit or an
  Unsigned32 value of a `values` table no document names, UTF-8 that is not,
  an integer of three octets, an AVP the rule does not admit where it has
  no `* [ AVP ]`, an answer with the E bit and a Result-Code that is no
  protocol error, and each interpreted constraint the
  plugin checks: a length, a range, an excluded value, a codec's layout,
  another document's element as the element registry checks it, a rule on
  bits, a predicate on a command's own member or a grouped AVP's, a
  members, unique or values rule, an AVP an `absent` rule keeps out, and
  an answer's rule on its
  request.

A negative breaking an interpreted rule of a command's print that another
print of the command under its application id does not hold (TS 29.273's two
S6b AA-Answers, STa's and SWd's Diameter-EAP-Answer), or that it leaves to
its `* [ AVP ]` where the rule is the AVP's wherever read (SWa's
Diameter-EAP-Request, which prints no Visited-Network-Identifier), is listed
in `skipped`: a checker may hold the message to the other print, which it
breaks nothing of; so is one whose breaking value breaks a predicate on a
path to it too. A value rule of a member is broken at that member's own
place, another AVP of its reading and value elsewhere left as it is (TS
29.273's PDN-Type in TWAN-Connectivity-Parameters beside APN-Configuration's).
A rule on each instance of a repeated grouped AVP is broken beside a valid
copy of the instance, unless the copy would hold a member a `unique` rule
keeps apart from it (TS 29.272's Context-Identifier in each APN-Configuration).
A grouped AVP's `members` rule is broken only where emptying
it keeps its command's predicates on paths into it, which TS 29.336's SIR,
CIR, CIA, RIR and NIR do not. Nothing inside a `Failed-AVP` is broken, since
RFC 6733 section 7.5 lets it hold the failed AVP as received and a checker
holds it to its `1* { AVP }` alone. Any other interpreted rule no negative
breaks alone is listed in `skipped` with why: no value of the AVP breaks it
and keeps its other rules, breaking it breaks another predicate too, its
conditions cannot be made to hold, and the like.

An answer whose rules read the request it answers is sent with that request,
`request` in the vector, the pair sharing Hop-by-Hop and End-to-End
identifiers no other vector has; a checker reads the request first. Each
such rule gets a valid pair, `maximal/request/<kind>/<AVP>/<clause>`, its
conditions met and the rule kept, and a negative one breaking it.

Values are valid for their type and for every constraint read of the AVP: a
codec's layout (a PLMN identity is MCC 123, MNC 45), an element's, a length, a
range, bits, a predicate's siblings, the members a grouped AVP must or may not
hold, a grouped AVP's own members a predicate of its command names through a
path, present, holding the number or name it asks or another than it forbids
(TS 29.336's CIR, its User-Identifier holding an External-Identifier or an
MSISDN and not both, TS 29.154's BTR, its Vendor-Specific-Application-Id
holding Nt's Auth-Application-Id and so no Acct-Application-Id, TS 29.272's
ULA, its Subscription-Data's Subscriber-Status OPERATOR_DETERMINED_BARRING
beside its Operator-Determined-Barring and its AMBR's two bandwidths not
both 0), of two optional AVPs a predicate keeps apart the one fewer other
AVPs' rules read left out (a maximal ULA keeps its Result-Code, which the
subscription data's rules read, and leaves out the Experimental-Result whose
code would set it aside, TS 29.272 clause 7.4.3), a distinct value of a
`unique` member in each repeated grouped AVP. An AVP a predicate wants
present that only `* [ AVP ]` admits is built as the predicate's reading
reads it, which the plugin holds it to (TS 32.299's CCA, its
Supported-Features after an initial request it answers with
DIAMETER_ERROR_FEATURE_UNSUPPORTED); where the body admits no such AVP the
command is listed in `skipped`. A command a
required member of which the corpus cannot complete is listed in `skipped` (TS
29.154's ECR under `--policy hole`); an optional one is left out. A command
printing no application id is sent in application 0.

```text
format_version     1, changes when a reader would have to
seanchai_version, corpus_version, application_ids
vectors[]          id (application/abbreviation/kind[/what]), kind, application_id,
                   command, abbreviation, command_code, is_request, error_bit,
                   document, section, octets (hex), tree[], request,
                   breaks, expected[]
  tree[]           name, code, vendor_id (null without V), flags, data (hex),
                   children[]
  request          null, or the request an answer answers: octets, tree[]
  breaks           rule, reference, version, section, page, table
  expected[]       rule and severity (error, warn, note): the finding the
                   Wireshark plugin reports, a note for a constraint- rule
skipped[]          command, what, reason
```

`--pcap FILE` also writes the messages as a capture, each over TCP to port
3868, an answer's request just before it, which Wireshark opens with the
plugin. `--schema FILE` writes the JSON
Schema. From Python, `seanchai.vectors.build(dictionary)` returns the same.

The vectors are the plugin's end-to-end test (`tests/test_vectors.py`): of
every application the corpus holds, each built as `--application` builds
it, each valid one draws no error, warning or note of an interpreted rule,
each negative one exactly the finding it expects, from the whole corpus's
plugin under every Lua and from the application's own under one, and S6a's
under tshark.
Read through python-diameter's codec, which checks types and no rule, the
library refuses exactly the vectors breaking a data format.

### Commands

`seanchai commands --json` prints a `dictionary.Listing`: `format_version`,
`seanchai_version`, `corpus_version` and `applications[]` as the dictionary
writes them, without `marks`, each command without `members`, `dropped`,
`walk`, `answer_message`, `elements` and `constraints`.

## Installing the corpus

The library and the corpus are separate packages, released separately, so pin
each on its own:

```sh
pip install seanchai seanchai-corpus   # or "seanchai[corpus]"
```

- `corpus.Corpus.installed()` loads the installed corpus with its record of
  known holes; `installed(raw=True)` loads its raw mirror, and
  `installed(extra=paths)` your own `.dad` files beside it. Without the
  package it raises `corpus.CorpusNotInstalledError`.
- `corpus.Corpus.load(path)` loads another directory, file, or list of them.
  A file named twice counts once. Two files of the same document, version and
  3GPP2 revision raise `corpus.CorpusError`.
- `seanchai_corpus.CORPUS_DIR` is the data directory.
- `Corpus.version` is the corpus package's version, the date it was
  regenerated, when `installed()` loaded it, and None otherwise.
  `seanchai.__version__` is the library's.

The corpus states its format as `format` in its `corpus.toml`, and
`corpus.FORMATS` lists the formats the library reads. `installed()`, and
`load` of a directory holding `corpus.toml`, raise `corpus.CorpusFormatError`
for any other. The error names the package to upgrade: `seanchai` for a newer
corpus, `seanchai-corpus` for an older one. `corpus.toml` also holds the
[resolution rules](#resolution-across-releases). A directory without it, a
subdirectory or a list of files loads with no format check and no rules.

### Releases

The corpus holds Release 18 and Release 19 whole: every catalogued 3GPP
document each release has, at its last version, beside the RFCs and the
other publishers' documents, which have no releases and take part in both.
`Corpus.releases` lists them, `(18, 19)`. A corpus is read at one, its
newest by default:

```python
from seanchai.corpus import Corpus
from seanchai.model import Model

model = Model.build(Corpus.installed(), release=18)  # or Model.installed(release=18)
model.release  # 18
model.version("TS29.272")  # "18.7.0"
```

```sh
seanchai dictionary --application 16777251 --release 18 -o s6a-18.json
seanchai diff --release 18 --release 19 --application 16777251
```

`--release N` takes the same meaning in `show`, `commands`, `dictionary`,
`vectors` and `wireshark-plugin`, and `seanchai diff --release 18 --release
19` compares the two readings of the corpus; its summary line names the two
releases and counts the documents read at another version, which `--json`
lists. The dictionary, `show --json`,
`commands --json` and each side of a diff name the release read as
`release`. `Corpus.at(18)` is the corpus viewed at Release 18, sharing its
copies; asking for a release the corpus holds only in part (Release 6, 7 or
11, whose trees hold the copies older documents cite) raises
`corpus.CorpusError`. The export holds every copy and reads each in its own
release ([website.md](website.md)).

Read at Release 18, each document's Release 18 copy answers every
reference-level query, a document that ended before it answers with its
final copy, and one begun after it is not held. A citation resolves by its
citing copy as ever ([below](#resolution-across-releases)), so a Release 18
document's references mean Release 18 copies; where a citation reaches a
copy outside the release read, as TS 32.299 V11.20.0's reach Release 19
copies through `release_stand_in`, that copy is named with its version.

`Corpus.interfaces`, read from the directory's `interfaces.toml`, names the
Diameter interfaces or reference points each document specifies, or an RFC's
application: `books.interfaces.of(entry)` gives `("Gx", "Gxx", "Sd", "St",
"S15")` for TS 29.212, `()` for one with none, and None for a document the
record does not list or a corpus without one.

Every error the library raises derives from `seanchai.SeanchaiError`.

## What the version covers

`seanchai` follows semantic versioning over:

- the names in the `__all__` of `seanchai`, `seanchai.model`,
  `seanchai.corpus`, `seanchai.dictionary`, `seanchai.constraints`,
  `seanchai.diff`, `seanchai.vectors` and `seanchai.errors`;
- the dictionary's JSON, versioned by its `format_version`, and `diff`'s and
  `vectors`', by their own;
- the `.dad` grammar and the corpus format it reads, `corpus.FORMATS`;
- the consumer commands' options, output and exit statuses: `show`,
  `commands`, `dictionary`, `diff`, `vectors`, `export`, `wireshark-plugin`,
  `lint` and `format`.

The rest may change in any minor release: the Python of `seanchai.dad` (the
AST, parser, formatter and corrections), `seanchai.linter`'s internals and
rule set, `seanchai.extractor`, `seanchai.downloader`, `seanchai.oracle`,
`seanchai.export`, `seanchai.export_schema`, `seanchai.wireshark`, the
`corpus` maintainer commands, `seanchai.cli`, and every module whose name
starts with an underscore. The export's JSON keeps its own `schema_version`
([website.md](website.md#data-boundary)). The model's types still hold AST
nodes where the corpus's text is the fact (`Member.rule`, `Enumerated.values`,
`ValueTable.rows`, `Allocation.entry`), and those fields are covered.
`seanchai-corpus` is versioned by the date it was regenerated.

## The model

`model.Model` resolves a corpus. A `Message`'s members point at `Avp` objects,
a `Grouped` lists its members, an `Enumerated` its values, and every AVP has
its `(vendor-id, code)`, type, flag rules and defining document. Unlike the
AST, the model never contradicts itself.

```python
from seanchai.model import Model, RegistryKind, ValueKind

# wireshark="specifications/wireshark" adds Avp.wireshark_name.
# `Model.build(corpus)` is the same over any corpus.
model = Model.installed()
model.references()  # every document, a tuple as every query returns
model.canonical("ts 29.229")  # how it spells a reference: TS29.229
model.messages("TS29.229")  # bodies resolved; no reference: the whole corpus
model.applications("TS29.212")  # commands per application and interface
model.applications(application_id=16777216)  # one id, across documents
model.applications("TS29.229")[0].commands  # requests and answers, paired by code
model.reached(model.applications("TS29.272")[0])  # one entry per identity reached
model.answer_message("TS29.272")  # what its answers take with the E bit set
model.avps("TS29.229")  # what a document's tables list; no reference: all
model.resolve("TS29.229", "DRMP")  # one name in one document's reading
model.definition("Public-Identity")  # the defining document's reading
model.readings("Public-Identity")  # every reading under a name
model.readings((10415, 601))  # every reading claiming an identity
model.table_rows("TS29.061", "3GPP-IMSI")  # every table's row for a name
model.marks("TS29.212", "AN-GW-Address")  # what each table marks about it
model.holes("TS32.299")  # what the corpus cannot complete; no reference: all
model.undefined("TS29.345")  # the names its Undefined AVP blocks declare
model.across_releases()  # what citations resolved across releases
model.registry(RegistryKind.APPLICATION_IDS, 16777216)  # TS 29.230's say
model.value_tables("TS29.272", avp="ULR-Flags")  # the numbers a document names
model.element_tables("TS29.228")  # information-element tables, with their commands
model.constraints("TS29.272")  # what its clauses' prose says, as read
model.value_tables(kind=ValueKind.FEATURES)  # one kind, the whole corpus
model.feature_lists()["S6a/S6d", 1]  # a feature list, by application and list id
model.definition("ULR-Flags").value_table  # the bits, read through resolution
model.version("TS29.061")  # the copy queries read; version="6.15.0" an older one
model.obsoleted_by("RFC4005")  # ("RFC7155",): what the corpus holds replacing it
model.avps("TS29.061", version="6.15.0")  # every document query takes version=
```

- `Model.build` and `Model.installed` are the only constructors; `Model(...)`
  raises `TypeError`. Both check the build against the corpus's
  [record of holes](#known-holes).
- A reference may be spelled "TS 29.229", "ts29.229" or "3GPP TS 29.229". One
  the corpus lacks raises `ModelError`, suggesting close ones.
- `applications` groups a document's commands by application id and clause,
  because documents share one id between interfaces (TS 29.273's SWa, STa and
  SWd).
- `Message.application_id` is the id on the wire: the header's, or, where the
  header prints none, the one the `Application Scope` block covering the
  command's clause states. `header_application_id` is what the header prints.
  `is_request` reads the R bit. `Application.commands` pairs requests and
  answers by code as `model.Command`s; a half a document prints twice, as TS
  29.273's AAR, is two entries of `requests` or `answers`.
- `Avp.basic_type`, and `model.basic_type(data_type)`, give the RFC 6733
  section 4.2 format a type is carried in (section 4.3.1 derives the others).
  `model.VENDORS` names each vendor id the corpus uses, with the source
  stating it. `Avp.may_encrypt` is the Encrypt cell of the table that gave
  the flag rules, None where it prints none.
- `reached` walks as `walk` does, but gives one `model.Reached` per identity:
  `definition`, every distinct reading met as a `model.Met` with its
  `model.MemberPath`s, the value tables met with it, and `conflicts`.
- A `Member` carries the ABNF `rule` as spelled, and `min_occurs` and
  `max_occurs` as RFC 6733 section 3.2 reads them. A command's own member
  carries `elements`, the information-element rows mapping it
  ([below](#information-elements)).
- `Enumerated.values` also holds `ast.ReservedValues` and `ast.VoidValues`,
  which a validator must refuse: a void value was assigned and withdrawn, a
  reserved one never assigned. `vendor_specific` holds the ranges a validator
  must allow without names. Where the clause defines its values elsewhere,
  `values_source` holds the citation and `values` only what a correction
  supplied.
- Built with `wireshark=`, a Wireshark Diameter dictionary directory, the
  model fills `Avp.wireshark_name` and `Hole.wireshark_name`
  ([oracle.md](oracle.md#in-the-model)). `name` is always the document's
  spelling.
- Every model type has a one-line `repr` and a `to_dict()` for `json.dumps`.
  Two readings are equal when their `to_dict()`s are: provenance such as
  `read_through` and `completed_by` counts, and only `Avp.value_tables`, the
  tables of the document a reading was met in, is in neither.

The AST stays public underneath. `parser.parse(text)` reads one file and drops
`;;` comments; `parser.parse_with_comments(text)` returns them too, for
`formatter.format_spec(spec, comments)` to write back.
`parser.parse_with_layout(text)` returns a `parser.Layout` beside the tree:
each section's lines and directives, the tree path each line states and each
table row's cells, for a reader tying the tree to the file's lines.

### Holes

An `Avp` has every field set: code, type and flag rules are never `None`. A
name the corpus cannot complete is a `model.Hole` instead. Where one appears
in a body, `Member.avp` is `None` and `Member.hole` is the hole. The
`* [ AVP ]` wildcard, and a placeholder under the `PLACEHOLDER` policy, are
the only members with neither.

A `Hole` has:

- `reference`, the document that falls short;
- `missing`, the `model.Missing` fields it leaves unstated (`VENDOR_ID`,
  `CODE`, `DATA_TYPE`, `FLAG_RULES`), or `DEFINITION` when the name resolves
  nowhere, or `UNDEFINED` when an `Undefined AVP` block declares it so;
  serialized as `code`, `definition` and so on;
- `origin`, the re-used origin the corpus lacks, or `conflict`, the
  disagreeing reading, where either applies;
- the vendor, code, type and flag rules its document does state;
- `recorded`, the reason from the record of known holes.

A hole has no members or values. For those, read the AST through
`table_rows` or `corpus.Entry.spec`.

### Known holes

Fourteen names are holes, each a fact its source does not state. The
corpus's `holes.toml` records each by document, name, missing fields and a
reason citing the version, the clause and what was searched
([corrections.md](corrections.md#the-record-of-known-holes)).
`corpus.Corpus.load` reads it into `Corpus.record` for the directory holding
it directly; a file list, a subdirectory and a raw corpus have no record.

`Model.build(corpus, holes=model.HolePolicy.…)` sets which holes a build
allows:

| `holes` | A hole the record lists | A hole it does not | An entry naming no hole |
|---|---|---|---|
| `RECORDED` (default) | builds; `Hole.recorded` its reason | `IncompleteCorpusError` | `StaleHoleRecordError` |
| `NONE` | `IncompleteCorpusError` | `IncompleteCorpusError` | not read |
| `ANY` | builds; `Hole.recorded` its reason | builds | not read |

A recorded hole is still a hole: `holes()` lists it and `resolve` returns
None. Use `ANY` for a partial or foreign corpus. `unrecorded_holes()` and
`stale_record_entries()` return what the default would refuse.

The record speaks for every release the corpus holds whole: an entry holds
in each of them unless its `releases` names some, and a build at a release
reads only the entries holding there, so an entry naming no hole in one
release is stale there. `KnownHole.releases` and `HoleRecord.at(release)`
give them. `seanchai lint` checks the record at every release. Release 18
reads the same fourteen, and one more name for one of them: TS 29.061's
`3GPP-Session-Stop-Indicator` in V19.1.0 too, the copy TS 32.299 V11.20.0's
citation reaches, which a Release 18 reading names with its version.

The fourteen, by cause:

- A field no source states, under every policy:
  - TS 29.061's `3GPP-Session-Stop-Indicator` row states only a code.
  - TS 29.234's `Charging-Characteristics` is typed "Integer", which is no
    Diameter type.
  - TS 29.229's `Wildcarded-IMPU` states no code or flag rule. TS 29.329's
    reading is complete, and Sh's commands hold that one.
  - ETSI TS 183 020's `Privacy-Indicator` states no flag rule.
- The ten [undefined names](#undefined-names), holes under the default
  policy.

### Undefined names

Ten names the documents use as members are defined nowhere:

- RFC 4004's three SPIs;
- RFC 5866's `Authorization-Session-Volume`;
- TS 29.345's `ProSe-Query-Code` and `ProSe-Response-Code`;
- TS 29.154's `External-Group-Identifier`;
- TS 32.299's `Submission-Timestamp` and `Network-Element`;
- TS 29.234's `Error-Cause`.

Each has an `Undefined AVP` block in its document's file, added by a
correction. `undefined(reference)` returns them as `model.Undefined`: the
name, document, clause, what the document says of the name, and every clause
whose body names it.

`Model.build(corpus, undefined=model.UndefinedPolicy.…)` chooses what the
model makes of these names:

| Policy | `resolve` | `hole` | Body member | `holes()` | `HolePolicy.NONE` |
|---|---|---|---|---|---|
| `HOLE` (default) | None | missing `undefined` | `Member.hole` | lists it | refuses |
| `DROP` | None | None | removed; `Grouped.dropped`, `Message.dropped` keep it | no | builds |
| `PLACEHOLDER` | None | None | in place, `Member.placeholder` a `model.Placeholder` | no; `placeholders()` | builds |
| `SUPPLY`, supplied | the consumer's `Avp`, `supplied` its source | None | `Member.avp` | no | builds |
| `SUPPLY`, `Alias` | the named AVP, unchanged | None | `Member.avp`, `Member.alias` the `Alias` | no | builds |
| `SUPPLY`, neither | as `HOLE` | | | | |

The policy applies only to names a block declares. `undefined_policy`
reports it; record it in generated output. `DROP` also removes required
members, such as RFC 4004's SPIs; `dropped` keeps each member's `rule`. For
a required member, use `SUPPLY`.

`SUPPLY` takes `supply=`, a mapping from a name, or from a more specific
`(reference, name)`, to one of:

- `model.Supplied`: vendor, code, type, flag rules (a `model.FlagRules`),
  members for a Grouped AVP, values for an Enumerated one, `may_encrypt`, and
  a required `source`. Its `Avp` names the
  block's document in `defined_in`, carries `source` in `supplied`, and
  resolves its members in the block's document.
- `model.Alias`: reads the name as an AVP the corpus completes, with a
  `source`. TS 29.336's `External-Identifier` carries an external group
  identifier on S6t and is most likely what TS 29.154 means by
  `External-Group-Identifier`; the corpus does not assume it.

```python
from seanchai.model import (
    Alias,
    AvpFlag,
    DataType,
    FlagRules,
    Model,
    Supplied,
    UndefinedPolicy,
)

model = Model.installed(
    undefined=UndefinedPolicy.SUPPLY,
    supply={
        "External-Group-Identifier": Alias(
            "TS29.336", "External-Identifier", source="our reading of TS 29.154"
        ),
        ("TS29.345", "ProSe-Query-Code"): Supplied(
            vendor_id=10415,
            code=59999,
            data_type=DataType.OCTET_STRING,
            flag_rules=FlagRules(must=frozenset({AvpFlag.VENDOR})),
            source="ACME HSS 4.2 dictionary",
        ),
    },
)
print(model.resolve("TS29.154", "External-Group-Identifier"))
print(model.resolve("TS29.345", "ProSe-Query-Code").supplied)
```

`model.supplied_from(*paths)` reads `Supplied`s from hand-authored `.dad`
sidecars: each `Grouped AVP` or `Enumerated AVP` section with its table row,
and each AVP-table row alone. It refuses, listing every such fact, a name two
sidecars supply, a row contradicting its definition's code, type or vendor,
and a V flag contradicting the vendor.

The build raises `ModelError` for:

- `SUPPLY` without `supply=`, or `supply=` under another policy;
- a key naming no block (a typo, or upstream has since defined the name);
- an `Alias` to a name the corpus does not complete, or a cycle of aliases;
- a `Supplied` claiming the `(vendor-id, code)` of an AVP the corpus defines,
  or two names' `Supplied`s claiming one identity.

### How a name resolves

In one document, a name resolves to the first of:

1. the document's own definition;
2. the origin its re-used table cites, followed recursively to the real
   definition;
3. an AVP-table row;
4. a `; Bases:` document.

Where several of one file's AVP tables list a name, the first row in file
order wins; `table_rows` returns every row. The [linter](linter.md) reports
the conflicts this order hides. Which copy of an origin answers is in
[linter.md](linter.md#resolving-an-origin) and
[below](#resolution-across-releases).

Flag rules belong to the application that uses the AVP (RFC 6733 section
4.1). When a document re-uses an AVP, flags in its own AVP tables win, each
from the first row placing it. A re-used table's M-bit column comes next
(`MUST`, `MUST-NOT`, or `-` for nothing). The origin supplies everything
else. For example, TS 29.229 table 6.3.0.1 puts M in Must for four
`Digest-*` AVPs for which RFC 4590 states no rule, and `readings` returns
both readings.

`Avp.flag_rules` and `Hole.flag_rules` are a `model.FlagRules`, a frozen
dataclass: the table's four columns plus `application_defined`. An IETF reading
stating no flags has M there (application-defined) and V in Must not (RFC 6733
sections 4.1 and 4.1.1); a vendor reading stating none stays a hole. A table row
keeps the AST's rules; compare it through
`model.FlagRules.printed(row.flag_rules)`.

A grouped AVP defined elsewhere keeps the defining document's body, in that
document's sense: TS 32.299's own `Originator` is (10415, 864), but its
re-used `M2M-Information`, from oneM2M TS-0004, holds oneM2M's `Originator`,
(45687, 1008). A member the citing document also describes, with the same
`(vendor-id, code)`, is read through the citing document.

Two documents whose tables change a reading alike give two readings, each
naming its own `read_through`: OMA-DDS-Charging_Data's and oneM2M TS-0004's
`Session-Id`.

A field the first reading leaves unstated comes from the next reading in the
order, if the two agree on every field both state. If they disagree, the name
becomes a hole naming the disagreeing document. `Avp.completed_by` names the
document that filled each field: through TS 29.329, `Wildcarded-IMPU` is TS
29.229's, with code, vendor and flags from TS 29.329 table 6.3.1. A table
row's vendor is its Vendor-ID cell, or else its V flag
([linter.md](linter.md#vendor-spaces)).

### Resolution across releases

The corpus can hold several copies of a document, one per release tree.
`corpus.Corpus.resolution` picks the copy a citation means, following 3GPP TR
21.801 clauses 6.6.6.5.2–6.6.6.5.3 and ETSI SR 001 262 clause 12:

1. A specific reference, one whose entry in the citing document's references
   clause names a version or release, means that version (a release: its
   last version).
2. A non-specific reference means the newest copy in the citing document's
   major version. Outside 3GPP, it means the latest version held.
3. Failing that, a later release's copy can answer if `corpus.toml` has an
   entry with evidence that it defines the cited AVPs alike. A document that
   ended before the citing release resolves to its final version.

The `.dad` files name no versions, so the corpus's `corpus.toml` states
these facts. `Corpus.load` reads it into `Corpus.rules`, a `corpus.Rules`.
Its tables:

| Table | Says |
|---|---|
| `cited_as` | a document its citers number otherwise than its publisher ("ETSI TS 283 034" for ES 283 034) |
| `cited_version` | the version a specific reference names |
| `latest_edition` | a non-3GPP copy whose references mean the latest edition |
| `final_version` | a document that ended before the citing release |
| `cited_revision`, `stand_in` | a 3GPP2 revision a citation names, and the held revision answering for it |
| `release_stand_in` | a later release's copy answering for a release version the corpus lacks |
| `release_fill` | named fields of named AVPs that a later release states and the meant copy leaves unstated |

With more than one release held whole the tables keep their meaning, since
each is keyed by the citing copy's version, or names a version outright: a
`cited_version` or `cited_revision` read from Release 19's references clause
says nothing of Release 18's copy, which has an entry of its own where its
clause says the same (TS 29.212 V18.2.0's and V19.1.0's X.S0057-B). A
`final_version` is one version in every release; a `release_stand_in` or
`release_fill` names the later copy that answers, which stays the answer in
a reading of an earlier release. `releases` names the releases held whole,
and the record of holes scopes an entry to some of them with `releases`
([Known holes](#known-holes)).

Maintaining entries is covered in [development.md](development.md). `load`
raises `corpus.CorpusError` for a malformed entry or one naming a copy the
corpus does not hold. Without `corpus.toml`, only the drafting rules apply.
`corpus.Corpus(entries, rules=..., record=...)` takes parsed entries, rules
and record as given.

What you get back:

- An `Avp` or `Hole` that took a field from another release's copy carries
  `across_releases`, a `corpus.CrossRelease` naming the citing and cited
  documents, the version and the `corpus.CitationRule`.
  `across_releases()` lists them all; the linter's `cross-release-origin`
  note reports them per file.
- For a `release_fill`, `Avp.completed_by` names the copy per field
  (`TS29.061 V19.1.0`) and the rule is `CitationRule.LATER_RELEASE`.
- Reference-level queries (`avps`, `holes`, `references`) read each
  document's copy in the release read ([Releases](#releases)). Any other
  copy answers only through a citation.
- Corpus-wide lookups (`readings`, `definition`, `avps()`) also find an
  identity only an older copy holds, where a citation reaches it, such as TS
  32.299 V11.20.0's `WLAN-Information`.

### Error answers

With the E bit set, an answer takes RFC 6733 section 7.2's
`<answer-message>` in place of its command's body.
`answer_message(reference)` returns the one `reference`'s answers take, as a
`model.AnswerMessage`: the document's own, or else the first its `; Bases:`
documents print, depth first. TS 29.229 prints its own in clause 7.3.1; TS
29.272 prints none and takes RFC 6733's. The body is read through
`reference`, and `read_through` says so.

### Marks

`marks` returns, for each row of a table with mark columns, the table's label
and clause and the row's marks per column, keyed by the column's name as
`; Columns:` spells it. Each cell is a tuple of marks, `()` for a dash, or
None when blank. The set of columns is open
([grammar.md](grammar.md#avp-table)); the document's legend gives their
meaning. The corpus holds:

| Column | Documents | Means |
|---|---|---|
| `Acc-Type` | TS 29.212, 29.215 | the IP-CAN access types the AVP applies to, `All` or a list |
| `Applicability` | several | the supported features the AVP belongs to (blank: base functionality); in TS 29.212 and 29.215 also the function (`CC`, `PC`, `Both`, `ADC`, `ABC`) |
| `Reference-Points` | TS 29.061 table 9a | `Gi`, `Sgi` |
| `ACR`, `ACA`, `CCR`, `CCA` | TS 32.299 | whether the command uses the AVP; `()` is "not used" |

None of them names an interface. A row's interface is its table's clause.

### Value tables

`value_tables` returns the tables a document prints for a numeric AVP's
values, as `model.ValueTable`s: `kind` (`ValueKind.RESULT_CODES`, `BITS` or
`FEATURES`), `avp`, the document, clause, page, table label and `rows`. A row
is an `ast.ValueRow` with `name` and `value`, plus a result code's `section`
and `origin` where they apply and a feature's M/O `mark`. `vendor_id` is the
vendor space the numbers belong to: a plain `Result-Code` table's is 0 and an
`Experimental-Result-Code` table's the file's `; Vendor-ID:`, the space its
Experimental-Result names; a bits or features table's is the vendor of the
AVP as the document reads it, 0 for RFC 5447's `MIP6-Feature-Vector` whoever
numbers its bits.

`Avp.value_tables` holds the tables the reading document prints for the
name, or else its origin's; `Avp.value_table` is the first.
`resolve("TS29.229", "Experimental-Result-Code").value_tables` gives TS
29.229's codes, though the AVP is RFC 6733's. A value table is not part of
the AVP's identity and does not make a second reading: a reading from
`readings` or `avps()` carries the tables of its `read_through` document, as
`resolve` there gives them.

`feature_lists()` keys feature tables by `(application, feature_list_id)`,
spelled as the caption does. Where two documents print one list, the first
in reference order answers.

### Information elements

Twenty documents print, per command, a table of its information elements:
each element's name, the AVPs it maps to and its category, M, C or O, which
often says more than the ABNF's brackets do. TS 32.299 prints its charging
commands' AVPs so, naming no element, each grouped AVP's members set off
under it, and categories as TS 32.240 gives them: M, C, OM and OC (operator
provisionable, mandatory or conditional), or a dash, not used.
`Message.elements` holds every row describing the command, as
`model.Element`s, and each member the rows
mapping it:

```python
from seanchai.model import Category, Model

model = Model.installed()
(s6a,) = model.applications("TS29.272", application_id=16777251)
ulr = s6a.commands[0].request
for member in ulr.avps:
    for element in member.elements:  # TS 29.272 table 5.2.1.1.1/1
        print(member.name, element.category, element.name, element.section)
mandatory = [
    member.name
    for member in ulr.avps
    if any(element.category is Category.MANDATORY for element in member.elements)
]
```

An `Element` has the element's `name` as printed (None in TS 32.299's
tables), `category` (None for a blank cell, `Category.NOT_USED` for a
printed dash), the `avps` it maps to, `either` where it offers one of them
("Result-Code / Experimental-Result"), `printed` for a mapping cell naming
no AVP, `within`, the grouped AVP whose members its table tabulates (TS
29.228 table 6.3.2, SIP-Auth-Data-Item's), and `parents`, the grouped AVPs
its row is set off under, outermost first (TS 32.299 table 6.4.2.1's
CC-Time under Multiple-Services-Credit-Control and Requested-Service-Unit).
A member holds the rows of neither of the last two: those describe a
grouped AVP's members, which `Message.elements` keeps. `reference`,
`version`, `section`, `table` and `page` locate the row, whose description
the document holds: the corpus does not copy it.

A table describes a command of its own document, or of the document it says
specifies it (TS 29.228's describe TS 29.229's commands), or a base's
([grammar.md](grammar.md#information-elements)). `element_tables(reference)`
returns each table as a `model.ElementTable` with the `commands` it
describes, none where it names no command, one printed for several
applications it does not choose between, or one printed more than once under
its application at no clause it names; the linter reports those and where
a category and the ABNF disagree
([linter.md](linter.md#information-elements)).

### Result codes per command

TS 29.228, 29.273 and 29.328 print, in a procedure's detailed behaviour, a
table of the result codes its answer may carry, each under a condition.
`Message.result_codes` holds each code such a table lists for the command,
as a `model.ResultCode`: its `name` as printed, the `value` and `vendor_id`
(0 for a Result-Code value) the result-code tables give it and the document
`defined_in` giving them, found in the table's document, the command's,
their bases, or else in every document of the corpus naming the code, those
of the table's vendor space where spaces disagree (RFC 4740 numbers its
`DIAMETER_ERROR_USER_UNKNOWN` 5032, 3GPP's documents 5001); None where none
does. `reference`, `section`, `table` and `page` locate the row, whose
condition the document holds. `result_code_tables(reference)` returns each
table as a `model.ResultCodeTable` with the `commands` it describes. No
table says it lists every code an answer may carry, and none lists the
protocol errors an agent returns, so nothing holds a message to one.

### Interpreted constraints

What a clause states in prose of an AVP's value or presence, its layout, a
range, a condition on its siblings, is no structure a document prints. TS
29.272's is read by hand and written as interpreted constraints, each rule
pinned to the sentences it was read from; [constraints.md](constraints.md)
gives the kinds, the codecs, how far to trust them and how to add them.

```python
from seanchai.model import Codec, Grouped, Model

model = Model.installed()
plmn = model.resolve("TS29.272", "Visited-PLMN-Id")
for constraint in plmn.constraints:  # TS 29.272 clause 7.3.9
    print(constraint.section, constraint.readings[0].quotes)
    print([rule.codec for rule in constraint.rules if rule.kind == "encoding"])
apn = model.resolve("TS29.272", "APN-Configuration")
assert isinstance(apn, Grouped)
for constraint in apn.member_constraints:  # its members, clause 7.3.35
    print(constraint.avp, [rule.kind for rule in constraint.rules])
(s6a,) = model.applications("TS29.272", application_id=16777251)
for message in s6a.messages:
    for constraint in message.constraints:  # its members, from clause 5
        print(message.abbreviation, constraint.avp, constraint.table)
```

- `Avp.constraints` holds what the document reading the AVP read of it wherever
  it appears, or failing any, its origin's, as `value_tables` does; like
  `value_tables` it is not part of the reading's identity. A document reading an
  AVP it re-uses with constraints of its own, on the AVP or its members, reads
  it through itself (`read_through`), so they hold where it reads the AVP and
  not wherever the definition is read: TS 29.272 clause 7.3.43's rules on RFC
  4004's MIP-Home-Agent-Host bind S6a's commands, not RFC 4004's
  AA-Mobile-Node-Request. `Grouped.member_constraints` holds what it read of the
  grouped AVP's members, each member it reads as it says and the others as the
  origin does, `Message.constraints` of the command's, then those holding in
  every answer or request (`messages`, RFC 6733's) on an AVP the command's own
  leave unread, each naming the command's request at `request_section`;
  `AnswerMessage.constraints` those of every answer that read no request.
- A `model.Constraint` has the `avp`, its scope (`command`, `application_id` and
  `command_section`, or `within` and the `application_id` whose messages it
  holds in, or `messages`, `answers` or `requests`, every one of any document
  built on its own), `request_section`, the clause of the request an answer's
  rules read, `reference`, `version`, `section`, `table` and `page`, `versions`,
  the range of versions the quotes were checked against (None for an RFC, which
  has one edition and no version), `quoted_from_pdf`, True for a hand
  transcription's, whose quotes are held to the PDF it was copied from, and
  `readings`, each an `ast.Reading` of `quotes` and `rules` (`ast.LengthRule`,
  `RangeRule`, `ExcludeRule`, `EncodingRule`, `PredicateRule`, `DefaultRule`,
  `BitsRule`, `MembersRule`, `UniqueRule`, `ValuesRule`, `EqualsRule`,
  `AbsentRule`, `TextOnly`). A condition is an `ast.Condition`, an
  `ast.Reference` (`root`, `path`) with a test. `interpreted` is always True.
  A condition's bit named as a feature (`Feature-List bit Update-Eff`) is the
  bit the reading document's features tables give it, of the feature lists
  of the constraint's application and of the Feature-List-ID its `and`
  holds beside it (`constraints.feature_list_id`):
  `constraints.feature_bits(name, lists, feature_list_id)` gives the bits a
  name stands for among lists, one where it is read, and
  `dictionary.feature_bit(dictionary, constraint, conjunction, condition)`
  the one bit a dictionary's condition stands for, None where it stands
  for none or several. A caller of `holds` gives a Feature-List's
  `constraints.Avp` its list's features as `bits`.
- `seanchai.constraints.check(rule, payload, data_type, codec, request)`
  tells whether a value rule holds of a payload, and `holds(rule, avp,
  scope, request)` whether a predicate, `values` or `equals` rule holds of
  a run of `constraints.Avp`s; one reading the request with none given is
  not evaluated (`Check.needs_request`). `codec_problem` says why a payload
  is no such layout ([constraints.md](constraints.md#codecs)), and
  `element_problem` why it is not the element an `encoding element` rule
  names, as `seanchai.elements` reads its document
  ([constraints.md](constraints.md#elements)).

### The registry

`registry(kind, code)` returns what the corpus's registries say of a code,
as `model.Allocation`s naming the registry document, table and clause. No
`Avp`, `Message` or `Application` takes anything from it. The linter's
`registry-*` rules report where documents and registry differ.

## The export

`seanchai export -o DIR` writes the resolved corpus as JSON for the static
site and other consumers without Python. It needs no checkout or downloads.
From Python, call `seanchai.export.export_corpus(corpus, output)`;
`seanchai.export_schema` holds the shape. The layout and fields are in
[website.md](website.md#data-boundary).

## The Wireshark plugin

`seanchai wireshark-plugin -o FILE.lua` writes a Wireshark plugin that checks
every Diameter message in a capture against the corpus and cites the clause
each finding's rule is written at. It needs no checkout or downloads. From
Python, `seanchai.wireshark.generate(corpus)` returns the same text. What it
checks, its fields and preferences, and the two lines of the file a tool may
read or rewrite are in [wireshark-plugin.md](wireshark-plugin.md).

## The integrations

Each target has a directory under `integrations/`. Its scripts declare their
dependencies as PEP 723 inline metadata, so `uv run` works from any
directory:

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 -o out/
```

They read the committed corpus unless `--corpus` names another.
`validate.py` checks [python-diameter](https://github.com/mensonen/diameter)
against a document; `generate.py` writes modules for it. See its
[README](../integrations/python_diameter/README.md).
