# Proposal: output corrections

**Status: proposed, not implemented.**

The pipeline has two patch layers by design. The first,
[input patches](extractor.md#input-patches), fixes typos in the source document
that would otherwise break extraction — a flags cell reading `M. V`, a rule name
with spaces instead of hyphens. The second fixes data that extracts and parses
perfectly well but is *wrong*: an AVP code that the spec's own table misprints, a
clause reference pointing at the wrong section, an application id the header
omits.

Only the first exists today. This document proposes the second.

## Framing

The two layers are the same operation at different altitudes: input patches are
find/replace on *text*, corrections are find/replace on *typed fields*. Keeping
that symmetry means the second layer inherits the first one's best property —
every patch declares what it expects to find, so it cannot silently rot when the
source document changes between versions.

The historical plan (see the README and TODO of commit `cd52de2`) was to store
corrections as textual diffs against the raw `.dad` and re-apply them with
`patch(1)` on each version bump. That has two problems. It gives no accounting:
a hunk either applies or conflicts, with no way to say "this was needed because
the spec printed an empty application id, and if that gets fixed upstream I want
to be told". And it is brittle in exactly the case the workflow exists for — a
correction anchored on three lines of context breaks whenever the spec edits an
adjacent AVP, which is the normal case on a version bump.

That framing also settles the notation question in a specific way: **Python as
the notation, declarative data as the content.** A module-level list, not a
function that mutates the tree. That gives imports of the real enums, type
checking, and loops when twenty rows need the same fix — without giving up
per-correction accounting or reviewability.

## The file

`corrections/TS29.272.py`:

```python
from seanchai.dad import ast
from seanchai.dad.corrections import Correction, avp_rule, definition, table_row

CORRECTIONS = [
    Correction(
        target=table_row(name="MME-Location-Information"),
        field="code",
        expect=1600,
        replace=1602,
        reason="table 7.3.1/1 prints the Trace-Data code by mistake",
        versions="18.6.0",
    ),
    Correction(
        target=definition("Update-Location-Request"),
        field="application_id",
        expect=None,
        replace=16777251,
        reason="VCSG command headers omit the application id",
        versions="18.0.0..18.6.0",
    ),
    Correction(
        target=avp_rule(parent="Subscription-Data", name="Roaming-Restricted"),
        field="max_occurs",
        expect=None,
        replace=1,
        reason="§7.3.2 body prints a bare * on a non-repeating AVP",
    ),
]
```

## Semantics

- **`expect` is mandatory and checked.** A mismatch is an error, not a warning —
  the same posture as the strict extractor. If 3GPP fixes the typo upstream, the
  next extraction fails loudly and the correction gets deleted; that is exactly
  the event worth being told about.
- **A target matching zero nodes is an error too.** `versions` downgrades both to
  a warning when the parsed version falls outside the declared range, so a
  correction can stay in the file across a bump where it no longer applies.
- **Selectors address identity, never position**: `definition(name)`,
  `table_row(name)`, `reused_row(name)`, `enum_value(avp, name)`,
  `avp_rule(parent, name)`. Indices are what make a text diff brittle in the
  first place; don't reintroduce them here.
- **Ambiguity is an error.** A selector matching two nodes must be narrowed —
  `definition("Update-Location-Request", application_id=16777251)` for the
  dual-application sections of TS 29.272.

## Implementation

A generic walk that rebuilds the frozen tree:
`apply(spec, corrections) -> tuple[Specification, list[str]]`, roughly 60–80
lines in `dad/corrections.py`, plus one small dataclass per selector kind.

It belongs in `dad/`, not `extractor/`: corrections operate on the format, and a
downstream consumer may want to apply them without going near the docx path.

Escape hatch for anything the field model cannot express (deleting a bogus row,
splitting a section): `Correction(target=..., edit=lambda node: ...)`, under the
same `expect` and accounting contract. Don't build more than that until a case
demands it — the same instinct that has so far kept structural override files
out of the extractor.

## Pipeline

```text
docx ──input patches──► extract ──► 29272-i60.raw.dad (committed)
                                              │
                                        corrections
                                              ▼
                                    TS29.272.dad (committed)
```

Both files are committed, so the diff between them is generated and reviewable —
semantic corrections stay readable as a diff without being *stored* as one, and
the correction file is the reproducible recipe.

CLI: `seanchai extract … --corrections DIR`, explicit rather than the
`./patches`-if-present auto-discovery the input patches use, because this
imports Python from the given directory. Plus `seanchai correct IN.dad -o
OUT.dad`, so the layer can be re-run without a docx.

Input patches stay in `patches/`; corrections go in `corrections/`. Two
directories, so which layer a fix belongs to is visible from the path.

## Testing

- `apply(apply(spec)) == apply(spec)` — idempotency.
- Rot detection: an `expect` that no longer matches errors; outside its
  `versions` range it warns instead.
- An ambiguous selector errors.
- Once the linter exists: `raw.dad` may fail it, the corrected file must pass.
  That is the real acceptance criterion for this layer — corrections are what
  take a specification from "parses" to "internally consistent".

## Deliberately out of scope

Auto-generating a corrections file by diffing a hand-edited `.dad` against the
raw one. Probably the right ergonomics eventually, but it needs the layer to
exist and be used first.
