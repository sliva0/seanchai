# The linter

`src/seanchai/linter.py` reports what a `.dad` file says that cannot all be
true. It is the counterpart to the extractor's rule: the extractor records
contradictions, the linter says them out loud.

```sh
uv run seanchai lint dad/3gpp/rel-18/*.dad
uv run seanchai lint --no-notes FILE.dad          # errors only
uv run seanchai lint --corpus dad FILE.dad        # also the cross-file rules
uv run seanchai lint --output-format concise ...  # file: severity: [rule] message
```

Errors exit non-zero; notes do not. **Error** means the file asserts two
things that cannot both be true. **Note** means something a single file
cannot judge.

## Single-file rules

- `duplicate-definition` — one name defined by two clauses.
- `one-name-two-commands` — one command name with two command codes. A
  repeated message name alone is normal (TS 29.272 defines IDR/DSR/RSR for
  S6a and S7a); TS 29.344 clauses 6.2.11/6.2.12 print 6.2.3/6.2.4's rule
  names above command 8388713.
- `duplicate-enum-value` — one enumerated AVP using a value or a value name
  twice.
- `duplicate-identity` — two AVPs claiming one `(vendor-id, code)`. TS 29.272
  clause 7.3.138 printed `Area-Scope` with `Job-Type`'s code while every name
  stayed unique.
- `row-without-code` — a table that declares a Code column printing a row
  without one. TS 29.229 and 29.329 tabulate RFC 8583's `Load` code-less in
  their own tables; corrections move it to the re-used table.
- `table-definition-mismatch` — a row disagreeing with the local clause that
  defines the same AVP, on code or type. Rows with no local clause are not
  compared.
- `vendor-id-mismatch` — a definition naming a vendor other than the file's
  `; Vendor-ID:`, or naming none while the AVP table marks `V` mandatory. A
  vendor-less definition with no such row is left alone: a genuine IETF-space
  AVP looks exactly like it, and a re-used one belongs to its origin.
- `local-and-reused` — an AVP both defined locally and listed as re-used.
  A note, because a re-print and an extension look the same from one file;
  superseded by the cross-file rules when the origin is readable.

## Cross-file rules

With `--corpus`, each re-used row is resolved against the document it cites.

- `reused-reprint` / `reused-extension` / `reused-body-differs` — what a
  local-and-reused AVP is doing, decided by comparing bodies. All notes: only
  the origin's editor knows which copy is current. TS 29.388's
  `V2X-Subscription-Data` neither re-prints nor extends 29.272's.
- `reused-code-conflict` — two documents giving one AVP two codes. An error:
  an AVP *is* its `(vendor-id, code)`.
- `reused-avp-not-in-origin` — the cited origin has never heard of it.
  TS 29.283 listed `Feature-Id` from TS 29.229 (now deleted by correction).
- `reused-origin-indirect` — the origin borrows it too. TS 29.172 cites
  `Service-Selection` from 29.272, which re-uses it from RFC 5778. Not
  corrected: "where I got this" and "who defined this" are different claims
  the From column does not distinguish.
- `origin-not-in-corpus` — one note per file listing the origins the corpus
  could not supply, so the reader knows which rules stayed silent.
- `unresolved-reference` — every AVP referenced in a message or grouped body
  must resolve to a local definition, a table row, a re-used row, or a
  `; Bases:` document. `* [ AVP ]` is grammar and is skipped. A note rather
  than an error while the six standing cases below exist.
- `base-not-in-corpus` — a `; Bases:` document the corpus lacks; reference
  resolution is skipped for that file rather than reporting every base AVP.

With `--corpus`, `duplicate-identity` also runs over re-used rows, since the
origin's `; Vendor-ID:` is readable then.

## Resolving an origin

A re-used row names a specification, never a version. The rule is **match
the major version, then take the newest**: an 18.x document resolves
`TS29.272` against 18.x copies and prefers 18.2.0 over 18.1.0. Nothing
resolves across a major version — a release boundary is where 3GPP may
change what an AVP means — which is also why the corpus is one directory per
release. RFCs resolve to whatever the corpus holds. Raw files are excluded
from a corpus by default; loading both copies would leave the choice to sort
order.

## Vendor spaces

An AVP's identity is `(vendor-id, code)`, and a `.dad` file supplies only
half of it in its tables: no vendor column, and clause headers omit the vendor
both for genuine IETF-space AVPs and when the document forgot. The file's own
`; Vendor-ID:` supplies the other half for local rows. TS 29.229 gives 621 to
its own `Primary-Charging-Collection-Function-Name` and lists RFC 7683's
`OC-Supported-Features` at 621 too; without the vendor those are a false
collision. Vendor 0 (the IETF space, spelled as an absent vendor in header
rules) is reconciled before comparing.

## Standing findings

Two tests in `tests/test_linter.py` pin what the committed corpus reports:
every raw file's single-file findings, and every corrected file's cross-file
notes. The corrected corpus has no errors; "clean" stays distinguishable from
"the rules never match". What still reports, and why each stays:

- **`reused-reprint`, `reused-body-differs`, `reused-origin-indirect`.** Two
  documents describe one AVP, and only the origin's editor knows which copy is
  current; correcting either would invent an agreement. The
  `reused-body-differs` cases are mostly `Serving-Node`-style AVPs whose
  clauses say they originate elsewhere and then print interface-specific
  bodies (29.128, 29.272, 29.283, 29.336, 29.337, 29.338, 29.388).
- **`origin-not-in-corpus`.** Every missing origin is a legacy `.doc` (TS
  32.299, 29.368, 29.217, 29.468; 29.154 is not in the catalog at all), or
  outside 3GPP/IETF (ETSI TS 283 034 and TS 183 017, 3GPP2 X.S0057, TS
  23.329). These clear as the corpus grows; see the roadmap.
- **`unresolved-reference`**, six, all AVPs no document defines, tabulates or
  allocates: RFC 4004's `MIP-HA-to-MN-SPI`, `MIP-MN-FA-SPI`, `MIP-MN-HA-SPI`
  (clauses 9.4–9.6; erratum 1462 renames one to another undefined name, and
  Wireshark carries the same dead end), and TS 29.345's `ProSe-Query-Code`
  and `ProSe-Response-Code` (clauses 6.3.53, 6.3.54), and TS 29.273's
  `NSWO-Authorization` (clause 5.2.2.1.2 prints only a member reference).
  The rule promotes to an error when these are gone, which needs the
  upstream documents to move.
