# Corrections

`src/seanchai/dad/corrections.py` is the second edit layer, for data that
extracts and parses fine but is wrong: a misprinted AVP code, a clause
reference to the wrong section, an application id no reading states. Input
patches are find and replace on text; corrections are find and replace on
typed fields, with the same declare, expect and fail-loudly contract.

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
the validation: a `field` string is checked against the matched node and
the node is rebuilt through pydantic.

`id` is a short kebab-case name, unique within the module. It is what the
corrected file cites, so name what is corrected
(`bearer-identifier-spelling`, `bases-nasreq`), not where.

## Semantics

- **`expect` is mandatory and checked.** A mismatch is an error. If the typo
  gets fixed upstream, the next extraction fails and the correction gets
  deleted, which is exactly the event worth being told about.
- **Zero matches is an error; more than one is an error.** Narrow with a
  discriminator: `definition("Update-Location-Request",
  application_id=16777251)`. `application_id=None` is a real filter;
  omitting the argument means "do not filter".
- **`versions` is advisory within its release**: `"18.6.0"` or
  `"18.0.0..18.2.0"`, inclusive, `*` for an open bound, the same range type
  patches and quirks declare. A declaration applies to the releases its
  range spans, and to a newer undeclared release as a release upgrade
  ([extractor.md](extractor.md#releases)).
  Within a release `regenerate` warns when the parsed version falls outside
  the range and never gates application; `regenerate --expand-ranges`
  rewrites the string literal in place
  ([development.md](development.md#version-upgrades)), which is why a range
  is best written as a literal.
- **Deterministic, not idempotent.** Correcting already-corrected input
  fails every `expect`, which keeps "already corrected" distinguishable from
  "fixed upstream". The layer consumes raw files only, a transcription's
  included.
- **Selectors address identity, never position**: `definition(name)`,
  `table_row(name, table=)`, `flag_rules(table_row(...))` (one field per
  correction: moving a flag from Must to Must not is two), `reused_row(name,
  section=)`, `enum_value(avp, name, value=, occurrence=)`, `avp_rule(parent,
  name, occurrence=)`, `avp_table(label)` (`None` for a table printing no
  label), `reused_avps(label)`, `application_scope(name)`, `undefined(name)`,
  `header()`.
- **Position only where identity runs out.** `occurrence=n` picks the n-th
  rule of one name in one body, for a body that prints a rule twice
  identically (TS 29.229's RTA prints `< Session-Id >` on two lines), or
  the n-th value of one name in a list (RFC 4005 repeats two Service-Type
  values among those it qualifies). It matches only while the name still
  repeats, so the declaration fails once upstream drops the copy.
- **One field of one node.** Replacing a structural field such as `avps` is
  rejected. Several fields of one node are replaced in declaration order,
  each through validation. Two corrections to the same field are rejected;
  replacing a value with itself is rejected.
- **All or nothing.** Every correction is resolved against the original tree
  before anything is rebuilt, so a failure leaves no half-corrected file.

## Operations

- **`Correction`**: replace one field; expects the old value. A blank field
  is replaced like any other, with `expect=None`: RFC 4590, a RADIUS
  document, states no Diameter type or flag rule for the twenty attributes
  RFC 4740 imports as AVPs, and its module types them for Diameter citing TS
  29.229 and Wireshark's dictionary.
- **`Delete(id, target, expect=<the full node>, reason)`**: expects the node
  to equal `expect` in every field, so it fails when upstream removes or
  changes it. Deleting a node while correcting anything inside it is
  refused, as is emptying a table.
- **`Insert(id, into, node, after, reason)`**: expects no node of that name
  to exist. `into` is `avp_table(label)` or `reused_avps(label)` for a row,
  `definition(name)` for an `ast.AvpRule` or an `ast.EnumValue` (`after`
  naming the member or value it follows), or `header()` for an
  `Application Scope` or `Undefined AVP` block (`after` must be None). A
  `reused_avps(label)` matching no block, where an AVP table carries that
  label, creates the table's re-used block after it. An inserted
  `Undefined AVP` block expects, of the corrected tree, no definition,
  table row, re-used row or second block of that name, and a body in its
  clause naming it, so it fails the day upstream defines the name; its
  `reason` cites what was searched. A row stating a vendor its table prints
  no column for needs the column first, a `Correction` to the table's
  `columns` adding `Vendor-ID` with every printed row's cell blank (TS
  29.229's `Line-Identifier`, ETSI's vendor 13019).
- **`Supply(id, target=definition(name), expect=<the ; Values: text>,
  values=(...), reason)`**: fills the value list of an enumerated AVP whose
  clause names another document for its values. It expects the `; Values:`
  citation exactly and no values, so it fails when upstream re-words the
  citation or starts printing the list. The reason cites the clause of the
  external document, or, for a registry, its name and the date it was last
  updated, since an open registry makes the list a snapshot. With
  `extend=True`, for a section printing part of the list it cites, the
  supplied values follow the printed ones, and a supplied name or number the
  section already holds is refused (RFC 4005's NAS-Port-Type prints 0 to 25
  and the registry has added 26 to 43 since).
- **`Supply(id, target=table_row(name, table=), expect=<the row>, data_type=,
  flag_rules=, reason)`**: fills the blank Type cell, flag cells or both of
  an AVP-table row whose document types it by reference to another
  document. It expects the whole row, blank where it supplies, and requires
  the file to list the AVP as re-used (TS 32.299 table 7.2.0.1 types
  thirteen rows `refer [223]`, OMA-DDS-Charging_Data, whose table 11 states
  type and flags).

No arbitrary `edit=lambda` escape hatch and no `move` or `split`: a
correction that cannot be described cannot be reviewed. A structural case
that appears gets a named operation with its own `expect` contract.

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

`rule` is the linter rule, `target` the node the finding is about, and
`expect` the finding's message exactly, so a document that changes what it
says fails the acceptance. `reason` cites the clause that makes the override
deliberate; where no clause says so, the note stays open. An acceptance
changes no data: `apply` skips it, and a module declaring only acceptances
is one `seanchai correct` refuses. `regenerate --expand-ranges` widens an
acceptance's range only while it still matches its finding. The linter
checks it against a corpus ([linter.md](linter.md#acceptances)).

## The record of known holes

A correction changes a file; the corpus's `holes.toml` changes none, and
records what no correction can state: a name the corpus cannot complete
([consumers.md](consumers.md#known-holes)). Its entries follow this layer's
contract. `reason` cites the version and clause and what was searched,
naming the correction involved as `module#id` where one inserted the block
or row, and `missing` is checked as `expect` is: an entry that no longer
matches fails the default build.

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

A correction to a definition is cited on its header rule, one to a row's
flag rules on the row. The file header, a table and an application scope
have no such line, so a correction to one of their fields is cited on the
directive line that field prints (`; Bases:`, `; Table:`, `; Columns:`,
`; Application-ID:`, `; Note:`), and on the block's first line when it
removes that line.

A deletion's note stands in the deleted line's place and names what is gone
(`;; deleted: AVP table row 'Load' (TS29.229.py#load-row-not-local)`); an
inserted row is marked `;; inserted:`, an inserted block on its `; Type:`
line, and every value or row a `Supply` fills `;; supplied:`. Notes are
`;;` comments, so an annotated file parses to exactly the corrected tree,
and they are placed by the rules a hand-written comment follows
([dad-format.md](dad-format.md#comments)). Edits are resolved, and notes
keyed, by `ast.TreePath`, so a note marks the same line in a re-parse of
the tree. The citation is a name rather than a line number so that editing
a module does not change every corrected file.

A raw file can carry comments of its own (TS 32.299's struck members).
`corrections.apply_with_comments(spec, comments, edits)` carries them into
the corrected file, each moving with the line it attaches to, and returns
them merged with the notes.

## CLI

`seanchai regenerate` rebuilds the corpus with `edits/corrections`, and
`seanchai lint` reads its acceptances from there. For one file:
`seanchai extract … --corrections DIR` and `seanchai correct RAW.dad
--corrections DIR -o OUT.dad`, where the directory is explicit because
loading it executes Python. `extract` tolerates a document with no module;
`correct` requires a module with at least one correction, since a mistyped
path producing an uncorrected file would look like success. The module name
is derived from `; Specification:` through `ast.spec_ref`.
