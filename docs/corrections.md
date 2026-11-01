# Corrections

`src/seanchai/dad/corrections.py` is the second edit layer: for data that
extracts and parses fine but is *wrong* — a misprinted AVP code, a clause
reference to the wrong section, an application id no reading states. Input
patches are find/replace on text; corrections are find/replace on typed
fields, with the same declare-expect-fail-loudly contract.

## The file

`edits/corrections/TS29.272.py`, a module-level list of declarative data:

```python
from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
        id="area-scope-code",
        target=definition("Area-Scope"),
        field="code",
        expect=1623,
        replace=1624,
        reason="clause 7.3.138's AVP header prints Job-Type's code; table"
        " 7.3.1/1 and the TS 29.230 registry both assign Area-Scope 1624",
        versions="18.6.0..18.7.0",
    ),
]
```

Python is the notation (imports of real enums, loops for twenty rows), not
the validation: a `field` string is checked against the matched node and the
node is rebuilt through pydantic.

`id` is a short kebab-case name, unique within the module; a loop derives it
from the loop variable. It is what the corrected file cites, so name what is
corrected (`bearer-identifier-spelling`, `bases-nasreq`), not where.

## Semantics

- **`expect` is mandatory and checked.** A mismatch is an error. If the typo
  gets fixed upstream, the next extraction fails and the correction gets
  deleted — exactly the event worth being told about.
- **Zero matches is an error; more than one is an error.** Narrow with a
  discriminator: `definition("Update-Location-Request", application_id=16777251)`.
  `application_id=None` is a real filter (the VCSG headers carry `None`);
  omitting the argument means "do not filter".
- **`versions` is advisory within its release**: `"18.6.0"` or
  `"18.0.0..18.2.0"`, inclusive, `*` for an open bound, the same range type
  patches and quirks declare. A declaration applies to the releases its
  range spans and to none other ([extractor.md](extractor.md#releases)):
  TS 32.299's and TS 29.212's modules hold Release 18's corrections and
  Release 11's, TS 29.214's Release 7's too, each for its copy. Within a release `regenerate` warns when the parsed version
  falls outside the range, and never gates application. `regenerate --expand-ranges` rewrites a string literal
  in place to cover a version the module applied cleanly to (see
  [workflow.md](workflow.md#version-upgrades)), which is why a range is best
  written as a literal.
- **Deterministic, not idempotent.** Correcting already-corrected input fails
  every `expect`, which is what keeps "already corrected" distinguishable
  from "fixed upstream". The layer consumes raw files only, a
  transcription's included: a document copied by hand
  ([extractor.md](extractor.md#transcriptions)) is patched into its raw
  file and corrected in the module its `; Specification:` names
  (`ETSI-TS183.017.py`) like any other.
- **Selectors address identity, never position**: `definition(name)`,
  `table_row(name, table=)` (label narrows repeated rows),
  `flag_rules(table_row(...))` (a row's `must`, `may`, `should_not` and
  `must_not`, one field per correction: moving TS 29.273's RAT-Type M from
  Must to Must not is two), `reused_row(name, section=)`,
  `enum_value(avp, name, value=, occurrence=)`,
  `avp_rule(parent, name, occurrence=)`
  (parent may be a whole `definition` selector), `avp_table(label)`
  (`None` for a table printing no label, as an RFC's), `reused_avps(label)`, `application_scope(name)`,
  `undefined(name)` (an `Undefined AVP` block), `header()`.
- **Position only where identity runs out.** `occurrence=n` picks the n-th
  rule of one name in one body, counted from 1, for a body that prints a
  rule twice identically: TS 29.229 clause 6.1.10 prints RTA's
  `< Session-Id >` on two lines, and `Delete(target=avp_rule("Registration-Termination-Answer",
  "Session-Id", occurrence=2), expect=...)` removes the copy. `enum_value`
  takes it too, for a list printing one value twice: RFC 4005 clause 6.1
  lists Service-Type's `Callback Login (3)` and `Callback Framed (4)`, then
  repeats both among the values it qualifies. It matches only while the
  name still repeats, so the declaration fails once upstream drops the copy;
  `expect` is still the whole node.
- **One field of one node.** Replacing a structural field such as `avps` is
  rejected. Several fields of one node are replaced in declaration order,
  each through validation, so a flag leaves one column before it enters
  another. Ancestor and descendant corrections in one set are both applied;
  two corrections to the same field are rejected; replacing a value with
  itself is rejected.
- **All-or-nothing.** Every correction is resolved against the original tree
  before anything is rebuilt, so a failure leaves no half-corrected file.

## Operations

- **`Correction`**: replace one field; expects the old value. A blank
  field is replaced like any other, `expect=None`: RFC 4590, a RADIUS
  document, states no Diameter type or flag rule for the twenty
  attributes RFC 4740 imports as AVPs, and its module is a stand-in
  typing them for Diameter, one correction giving its table Type and
  flag-rule columns and three per row its type (UTF8String, for RFC
  4590's "Text", as TS 29.229 and Wireshark's dictionary type them) and
  Wireshark's flag rules, each citing that evidence.
- **`Delete(id, target, expect=<the full node>, reason)`**: expects the node to
  equal `expect` in every field, so it fails when upstream removes *or*
  changes the row. Deleting a node while correcting anything inside it is
  refused, as is emptying a table. Forcing case: TS 29.283's re-used
  `Feature-Id`, which TS 29.229 never defined.
- **`Insert(id, into=avp_table(label) | reused_avps(label) | definition(name), node, after=<name | None>, reason)`**:
  expects no row of that name to exist. Forcing case: TS 29.344 clause 6.3.13
  defines `Authorized-Discovery-Range` but table 6.3.1-1 omits the row;
  re-used-table inserts came from the reference triage (six members TS 29.337's
  table omits). A `reused_avps(label)` matching no block, where an AVP table
  carries that label, creates the table's re-used block right after it:
  TS 32.299 table 7.1.0.1 tabulates IETF AVPs without naming an origin per
  row, and its corrections give each name its RFC. Into `header()`,
  `Insert` adds an `Application Scope` block, after the file's others (`after`
  must be None), expecting no block of that name: the RFCs state their
  application ids in wordings no two share (RFC 4006 in its IANA
  considerations, RFC 6733 per command group in clauses 2.5 and 9.3), TS
  32.299 only through its Acct- and Auth-Application-Id AVP clauses (7.1.5,
  7.1.6), TS 29.272 for its VCSG commands in the command table's clause
  (7.2.2, 16777308) and TS 29.273 for SWa by naming STa's application
  (4.2.1, with the id in 5.2.1), so their blocks are inserted citing the
  clause. The command headers stay as printed. Into `header()`, `Insert`
  also adds an `Undefined AVP` block ([dad-format.md](dad-format.md#design-intent)),
  after the file's last section and any block inserted before it (`after`
  must be None), declaring a name the document uses as a member and
  nothing in the corpus defines; its `reason` cites what was searched
  (later versions, errata, the registry, Wireshark's dictionary) and
  any near-name or analogy found, which stays evidence and goes into no
  field. It expects, of the corrected tree, so that a member a correction
  renames is the name it declares, no definition, table row, re-used row
  or second block of that name, and a message or grouped body in its
  clause naming it; the day upstream defines the name, it fails. Forcing
  case: RFC 4004's three SPI members (clauses 9.4–9.6), after the
  corrections give clause 9.5's and 9.6's the names their prose and
  clause 11.1's table use. Into `definition(name)`, a
  message or grouped AVP, `Insert` adds an `ast.AvpRule`, `after` naming
  the member it follows, and expects no member of that name: RFC 5777's
  verified erratum 2333 restores three members `Time-Of-Day-Condition`'s
  ABNF omits, each defined in a clause of its own and tabulated in section
  10.1. Into an enumerated AVP's `definition(name)`, `Insert` adds an
  `ast.EnumValue` another document defines for the list, `after` naming
  the value it follows, and expects neither its name nor its number in the
  list: RFC 8581 clause 7.2.1 adds `PEER_REPORT 2` to RFC 7683's
  `OC-Report-Type`, and RFC 8581's file holds no definition of the AVP to
  carry it, so RFC 7683's correction inserts it citing that clause. A row
  stating a vendor its table prints no column for needs the column first, a `Correction` to the table's `columns` adding `Vendor-ID`
  with every printed row's cell blank: TS 29.229 clause 6.3.42 defines
  `Line-Identifier` in ETSI's vendor 13019, and table 6.3.0.1 omits it.
- **`Supply(id, target=definition(name), expect=<the ; Values: text>, values=(...), reason)`**:
  fills the value list of an enumerated AVP whose clause names another
  document for its values and prints none. It expects the section's
  `; Values:` citation, exactly, and no values, so it fails when upstream
  re-words the citation or starts printing the list itself; the citation
  stays, since the document still makes it. The reason cites the clause of
  the external document the values come from, or, for a registry, its
  name and the date it was Last Updated, since a registry still open makes
  the list a snapshot. Forcing case: TS 29.272 clause 7.3.67 gives
  `Trace-Depth` "those defined in TS 32.422 [23] for Trace Depth", which
  TS 32.422 V18.7.0 clause 5.3 numbers. A citation whose source holds no
  flat list stays unfilled ([dad-format.md](dad-format.md#design-intent)):
  TS 32.299's `API-Network-Service-Node` cites TS 23.682, whose V18.0.0
  names the network elements but numbers none of them.
- **`Supply(..., extend=True)`**: the same, for a section that prints part
  of the list it cites, the supplied values following the printed ones.
  It expects the citation and at least one printed value, and refuses a
  supplied name or number the section already holds, a number inside a
  printed reserved or vendor-specific range included, so it fails the day
  upstream prints one of them. Without `extend`, a section printing values
  is refused as before. Forcing case: RFC 4005 clause 4.4 prints
  NAS-Port-Type's values 0 to 25 and cites `[RADIUSTypes]`, whose registry
  has added 26 to 43 since; one declaration appends them where
  `Insert` would take one per value.
- **`Supply(id, target=table_row(name, table=), expect=<the row>, data_type=, flag_rules=, reason)`**:
  fills the blank Type cell, flag cells or both of an AVP-table row whose
  document types it by reference to another document. It expects the whole
  row, as `Delete` does, blank where it supplies, and requires the file to
  list the AVP as re-used, the citation saying where its definition lives,
  which stays. Forcing case: TS 32.299 table 7.2.0.1 types thirteen rows
  `refer [223]`, `OMA-DDS-Charging_Data`, and prints no flags for them;
  OMA's V1.0 states type and flags in table 11 of its clause 8.4, which
  each declaration cites. Three of the rows are typed by TS 32.299's own
  clauses (7.2.50, 7.2.69, 7.2.191: "is of type Grouped"), so their
  declarations expect the type and supply the flags alone; V11.20.0's
  table 7.2 rows for the same three, under the same clauses and reference
  [223], take the same flags by Release 11 declarations of their own. A re-used row has no cells a model reads for
  type or vendor, so an AVP only re-used from an absent document has
  nowhere to take a supplied type: the document has to enter the corpus,
  as 3GPP2 X.S0057 did, transcribed, for TS 29.212's `3GPP2-BSID`.

No arbitrary `edit=lambda` escape hatch and no `move`/`split`: a correction
that cannot be described cannot be reviewed. A structural case that appears
gets a named operation with its own `expect` contract.

## Acceptances

Some linter notes are a document saying on purpose what another says
otherwise: an interface printing its own body for an AVP it re-uses, or its
own flag rule. `Accept` acknowledges one such note, so it stops reading as
an open finding while staying recorded:

```python
Accept(
    id="serving-node-t4-body",
    rule="reused-body-differs",
    target=definition("Serving-Node"),
    expect="Serving-Node's body, against TS29.173's definition: adds"
    " IP-SM-GW-Name, ...",
    reason="clause 6.4.12 says the AVP 'is originally defined in 3GPP TS"
    " 29.173 [8]' and lists the member combinations 'allowed' for"
    " T4-triggering, ...",
    versions="18.2.0",
)
```

`rule` is the linter rule, `target` the node the finding is about, by the
selectors above, and `expect` the finding's message, exactly, so a document
that changes what it says fails the acceptance as a changed value fails a
correction. `reason` cites the clause that makes the override deliberate;
where no clause says so, the note stays open. An acceptance changes no
data: `apply` skips it, the corrected file carries no note for it, and a
module declaring only acceptances is one `seanchai correct` refuses, as it
corrects nothing. It is declared in `CORRECTIONS` beside the edits, with
the same `id` and `versions` rules. A clean rebuild checks nothing about
it, so `regenerate --expand-ranges` lints the rebuilt file and widens an
acceptance's range only when it still matches its finding, reporting the
rest as `not widened, stale`. The linter checks it, with `--corpus`, against the
corrected file ([linter.md](linter.md#acceptances)); the accepted findings
are listed by id under the linter's standing findings.

## The record of known holes

A correction changes a file; `dad/holes.toml` changes none, and records what
no correction can state: a name the corpus cannot complete
([consumers.md](consumers.md#known-holes)). Its entries follow this layer's
contract. `reason` cites the spec version and clause and what was searched,
as a correction's does, naming the correction involved as `module#id` where
one inserted the block or row (`TS29.061.py#3gpp-sgsn-mcc-mnc-row`), and
`missing` is checked as `expect` is: an entry that no longer matches fails
the default build, the same signal that the corpus moved and the declaration
should go.

## Output

```text
docx ──input patches──► extract ──► 29272-i70.raw.dad  (committed)
                                              │
                                 edits/corrections/TS29.272.py  (committed)
                                              ▼
                                     29272-i70.dad  (committed)
```

Every corrected line carries a trailing `;;` note citing the declaration as
`module#id`, so grepping the id finds it:

```dad
Area-Scope ::= < AVP header: 1624 10415 > ;; corrected: (TS29.272.py#area-scope-vendor)
```

A correction to a definition is cited on its header rule, whichever field
it changed, and one to a row's flag rules on the row. The file header, a table and an application scope have no such
line, so a correction to one of their fields is cited on the directive line
that field prints —
`; Bases: RFC6733, RFC4005 ;; corrected: (RFC4006.py#bases-nasreq)`,
`; Table:` for a table label, `; Columns:` for its columns,
`; Application-ID:` for an application's id, `; Note:` for an undefined
AVP's note —
and on the block's first line when it removes that line.

A deletion's note stands in the deleted line's place and names what is gone
(`;; deleted: AVP table row 'Load' (TS29.229.py#load-row-not-local)`); an
inserted row is marked `;; inserted:`, an inserted application scope or
undefined AVP on its `; Type:` line, and every value or row a `Supply` fills `;; supplied:`. Notes are `;;` comments, so an
annotated file parses to exactly the corrected tree, and they are placed by
the rules a hand-written comment follows ([dad-format.md](dad-format.md#comments)):
`seanchai format` keeps every note where it is, and a corrected file is
already in the form it writes. Edits are resolved, and notes keyed, by
`ast.TreePath` rather than by object, so a note marks the same line in a
copy or a re-parse of the corrected tree.
The citation is a name rather than a line number so that editing or
reformatting a module does not change every corrected file.

A raw file can carry comments of its own: TS 32.299's struck members, which
the extractor comments out (`tgpp_docx.extract_with_comments` returns them
beside the tree). `corrections.apply_with_comments(spec, comments, edits)`
carries them into the corrected file, each moving with the line it
attaches to, and returns them merged with the notes. A comment standing
before or trailing a deleted line stands where that line stood, before the
deletion's note, and one standing after it follows the note; inside a
deleted section it joins the section's note block. Comments on a directive
line a correction removes (`; Bases:` emptied) go with the correction's
note to the block's first line, standing before it or trailing it ahead
of the note. `seanchai correct` and
`regenerate` both carry them.

## CLI

`seanchai regenerate` rebuilds the corpus with `edits/corrections` (see
[workflow.md](workflow.md)), and `seanchai lint --corpus` reads its
acceptances from there too. For one file: `seanchai extract … --corrections
DIR` and `seanchai correct RAW.dad --corrections DIR -o OUT.dad`, where the
directory is explicit because loading it executes Python. `extract` tolerates a specification with no
module (a corpus run passes one directory for everything); `correct` requires
a module with at least one correction, since a mistyped path producing an
uncorrected file would look like success. The module name is derived from
`; Specification:` through `ast.spec_ref`, which accepts only canonical
references, and the resolved module must sit directly in the directory.
