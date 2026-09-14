# Corrections

`src/seanchai/dad/corrections.py` is the second edit layer: for data that
extracts and parses fine but is *wrong* — a misprinted AVP code, a clause
reference to the wrong section, an application id the header omits. Input
patches are find/replace on text; corrections are find/replace on typed
fields, with the same declare-expect-fail-loudly contract.

## The file

`edits/corrections/TS29.272.py`, a module-level list of declarative data:

```python
from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
        id="vcsg-application-id",
        target=definition("Update-VCSG-Location-Request"),
        field="application_id",
        expect=None,
        replace=16777308,
        reason="clause 7.2.2 assigns the VCSG commands to S7a/S7d (16777308);"
        " the command header omits the id",
        versions="18.6.0",
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
- **`versions` is advisory**: `"18.6.0"` or `"18.0.0..18.2.0"`, inclusive,
  `*` for an open bound, the same range type patches and quirks declare.
  `regenerate` warns when the parsed version falls outside it, and never
  gates application.
- **Deterministic, not idempotent.** Correcting already-corrected input fails
  every `expect`, which is what keeps "already corrected" distinguishable
  from "fixed upstream". The layer consumes raw files only.
- **Selectors address identity, never position**: `definition(name)`,
  `table_row(name, table=)` (label narrows repeated rows), `reused_row(name, section=)`,
  `enum_value(avp, name, value=)`, `avp_rule(parent, name)` (parent may be a
  whole `definition` selector), `avp_table(label)`, `reused_avps(label)`,
  `header()`.
- **One field of one node.** Replacing a structural field such as `avps` is
  rejected. Ancestor and descendant corrections in one set are both applied;
  two corrections to the same field are rejected; replacing a value with
  itself is rejected.
- **All-or-nothing.** Every correction is resolved against the original tree
  before anything is rebuilt, so a failure leaves no half-corrected file.

## Operations

- **`Correction`**: replace one field; expects the old value.
- **`Delete(id, target, expect=<the full node>, reason)`**: expects the node to
  equal `expect` in every field, so it fails when upstream removes *or*
  changes the row. Deleting a node while correcting anything inside it is
  refused, as is emptying a table. Forcing case: TS 29.283's re-used
  `Feature-Id`, which TS 29.229 never defined.
- **`Insert(id, into=avp_table(label) | reused_avps(label), node, after=<name | None>, reason)`**:
  expects no row of that name to exist. Forcing case: TS 29.344 clause 6.3.13
  defines `Authorized-Discovery-Range` but table 6.3.1-1 omits the row;
  re-used-table inserts came from the reference triage (six members TS 29.337's
  table omits).

No arbitrary `edit=lambda` escape hatch and no `move`/`split`: a correction
that cannot be described cannot be reviewed. A structural case that appears
gets a named operation with its own `expect` contract.

## Output

```text
docx ──input patches──► extract ──► 29272-i60.raw.dad  (committed)
                                              │
                                 edits/corrections/TS29.272.py  (committed)
                                              ▼
                                     29272-i60.dad  (committed)
```

Every corrected line carries a trailing `;;` note citing the declaration as
`module#id`, so grepping the id finds it:

```dad
Area-Scope ::= < AVP header: 1624 10415 > ;; corrected: (TS29.272.py#area-scope-vendor)
```

A deletion's note stands in the deleted line's place and names what is gone
(`;; deleted: AVP table row 'Load' (TS29.229.py#load-row-not-local)`); an
inserted row is marked `;; inserted:`. The parser discards `;;` comments, so
an annotated file is exactly canonical output plus notes, and reformatting
drops them — harmless, because corrected files are regenerated, never edited.
The citation is a name rather than a line number so that editing or
reformatting a module does not change every corrected file.

## CLI

`seanchai regenerate` rebuilds the corpus with `edits/corrections` (see
[workflow.md](workflow.md)). For one file: `seanchai extract … --corrections
DIR` and `seanchai correct RAW.dad --corrections DIR -o OUT.dad`, where the
directory is explicit because loading it executes Python. `extract` tolerates a specification with no
module (a corpus run passes one directory for everything); `correct` requires
a module with at least one correction, since a mistyped path producing an
uncorrected file would look like success. The module name is derived from
`; Specification:` through `ast.spec_ref`, which accepts only canonical
references, and the resolved module must sit directly in the directory.
