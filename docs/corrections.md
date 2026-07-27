# Output corrections

**Status: implemented in `src/seanchai/dad/corrections.py`.** This document is
the design and the reasoning behind it; the semantics below are what the code
does.

The pipeline has two patch layers by design. The first,
[input patches](extractor.md#input-patches), fixes typos in the source document
that would otherwise break extraction — a flags cell reading `M. V`, a rule name
with spaces instead of hyphens. The second fixes data that extracts and parses
perfectly well but is *wrong*: an AVP code that the spec's own table misprints, a
clause reference pointing at the wrong section, an application id the header
omits.

This document describes the second.

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

Python is the notation, not the validation: a string `field="code"` is not
statically checked against the target node, so the implementation still has to
verify that the field exists on the matched node and rebuild through pydantic.

## The file

`edits/corrections/TS29.272.py`:

```python
from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
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

That one is real: TS 29.272 prints `< Diameter Header: 8388638, REQ, PXY, >`
for the four VCSG commands, and clause 7.2.2 states the application id those
command codes belong to. The full set is in
`edits/corrections/TS29.272.py`.

## Semantics

- **`expect` is mandatory and checked.** A mismatch is an error, not a warning —
  the same posture as the strict extractor. If 3GPP fixes the typo upstream, the
  next extraction fails loudly and the correction gets deleted; that is exactly
  the event worth being told about.
- **A target matching zero nodes is an error too**, as is a selector that
  matches more than one.
- **`versions` is advisory and, for now, only recorded.** It documents where a
  correction is known to be needed, exactly as `first_version`/`last_version`
  do for input patches: it must never gate whether a correction is applied,
  because skipping one would silently ship an uncorrected file the first time a
  version moves. Comparing it against the parsed version — to warn, never to
  skip — needs a version type both layers can share, which neither has yet.
- **Applying corrections is deterministic but not idempotent.** Run twice
  against the same raw AST you get identical output; run against
  already-corrected input and every `expect` fails. That is deliberate —
  treating a matched `replace` as a no-op would make "already corrected"
  indistinguishable from "fixed upstream", which is the one thing `expect`
  exists to tell apart. So the layer consumes raw files and refuses to correct
  in place.
- **Selectors address identity, never position**: `definition(name)`,
  `table_row(name)`, `reused_row(name)`, `enum_value(avp, name)`,
  `avp_rule(parent, name)`. Indices are what make a text diff brittle in the
  first place; don't reintroduce them here.
- **Ambiguity is an error.** A selector matching two nodes must be narrowed —
  `definition("Update-Location-Request", application_id=16777251)` for the
  dual-application sections of TS 29.272. `avp_rule` takes a whole `definition`
  as its parent (a bare name is shorthand), so a rule inside one of two
  same-named commands is reachable by the same discriminator.
- **"Not specified" is a sentinel, not `None`.** `application_id=None` is a
  real value — it is exactly what the VCSG headers carry — so omitting the
  argument, not passing `None`, is what means "do not filter".
- **A correction addresses one field of one node, never a subtree.** Replacing
  a structural field such as `avps` is rejected: it would have to define what
  happens to a correction aimed at one of the children it discards, and
  correcting the child directly is the operation that exists. Ancestor and
  descendant corrections in the same set are legal and both applied.

## Implementation

`apply(spec, corrections) -> tuple[Specification, list[Result]]` in
`dad/corrections.py`, with one frozen dataclass per selector kind. Every
correction is resolved and checked against the original tree before anything is
rebuilt, so a failure part-way through a set cannot leave a half-corrected
file. Two corrections may touch two fields of the same node; two corrections to
the *same* field are rejected rather than silently ordered.

It belongs in `dad/`, not `extractor/`: corrections operate on the format, and a
downstream consumer may want to apply them without going near the docx path.

Rebuild through validation, not `model_copy(update=...)` — pydantic does not
validate update values, so a correction could otherwise write a code of
`"oops"` into a validated tree and only fail at format time, if at all.

No arbitrary `edit=lambda node: ...` escape hatch: it would sidestep both the
field validation above and the accounting that justifies the whole design, and
a correction that can't be described can't be reviewed. When a structural case
actually appears (deleting a bogus row, splitting a section), add a named
operation for it with the same `expect` contract — the same instinct that has
so far kept override files out of the extractor.

## Pipeline

```text
docx ──input patches──► extract ──► 29272-i60.raw.dad  (committed)
                                              │
                                 edits/corrections/TS29.272.py  (committed)
                                              ▼
                                     29272-i60.dad  (committed)
```

All three are committed: the raw file, the correction module, and the corrected
file the two produce. The corrected one is what any real use consumes — a
corpus of files that are knowingly wrong is a corpus nobody can use directly —
and the raw one is what makes the layer checkable, because `apply` needs raw
input and is deliberately non-idempotent. Storing only the corrected file would
mean re-downloading the sources to re-check a single correction. See
[dad/README.md](../dad/README.md).

The corrected file is the one anyone doing real work uses, so it says which of
its values a human overrode:

```dad
;; corrected: code 1623 -> 1624 [edits/corrections/TS29.272.py:31]
; Type: Grouped AVP
; Name: Area-Scope
```

The note carries what changed and where the declaration is, and no more — the
`reason` is a sentence, and it belongs next to the correction rather than
copied into a format that carries definitions. `Correction` captures its own
`file:line` at construction, by walking out to the first frame outside the
corrections module, so a correction built inside a helper or a comprehension
still cites the corrections file.

These are `;;` lines, which the parser discards. An annotated file is therefore
*exactly* canonical output plus notes: parsing it gives the same tree, and
reformatting it gives back the canonical text without them. That is the
intended relation rather than a wart — a note is a reader's aid, not data — but
it does mean a corrected file that gets reformatted loses its marks, which is
harmless because corrected files are regenerated rather than edited.

CLI: `seanchai extract … --corrections DIR`, explicit rather than the
`./edits/patches`-if-present auto-discovery the input patches use, because this
imports Python from the given directory. Plus `seanchai correct IN.dad -o
OUT.dad`, so the layer can be re-run without a docx.

The two commands want different answers to "this specification has no module":

- `extract --corrections` allows it. A corpus run passes one directory for
  every specification, and most of them have nothing to correct.
- `correct --corrections` requires a module with at least one correction.
  Correction is the whole point of the invocation, so a mistyped path that
  produced a cheerfully uncorrected file would be indistinguishable from
  success.

Because the module path is derived from the parsed `; Specification:` header
and importing it runs its Python, the derivation validates rather than cleans
up: `ast.spec_ref` accepts only canonical document references, and the resolved
candidate must sit directly in the resolved corrections directory. A file
claiming `; Specification: ../outside` gets an error, not `../outside.py`.

Input patches stay in `edits/patches/`; corrections go in
`edits/corrections/`. Two directories side by side, so which layer a fix
belongs to is visible from the path, and both are visibly *edits* rather than
source.

## Testing

- Determinism: applying the same corrections to the same raw AST twice gives
  byte-identical output. (Not idempotency — see the semantics above; feeding
  corrected output back in must error.)
- Rot detection: every committed correction is re-applied to the committed raw
  output, so a re-extraction that invalidates one fails the suite — offline,
  without the source documents. The corrected file is checked to already hold
  every `replace`, so the committed pair cannot drift apart.
- The intended semantic diff, pinned separately from the corrections that
  produce it. The rot check reads its expectation out of the file it is
  testing, so a wrong `expect`/`replace`/reason changed together stays green;
  a second test asserts that TS 29.272 changes exactly four application ids
  from `None` to `16777308` and no other field anywhere in the tree.
- An ambiguous selector errors, as does a field the target node doesn't have
  and a replacement value the model rejects.
- Raw output may fail the linter; the committed corrected file must pass. That
  is the real acceptance criterion for this layer — corrections are what take a
  specification from "parses" to "internally consistent".

## Deliberately out of scope

Auto-generating a corrections file by diffing a hand-edited `.dad` against the
raw one. Probably the right ergonomics eventually, but it needs the layer to
exist and be used first.
