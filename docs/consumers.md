# Downstream consumers: the model and the validators

This document owns `src/seanchai/model.py` — the consumer model, the resolved
layer the roadmap's downstream-consumer section asks for — and the scripts
under `integrations/`, which are the consumers that exist. The design brief the
model was built against is the reasoning recorded here; the roadmap keeps only
what remains open.

## The model

The `.dad` AST mirrors a file one-to-one and is allowed to contradict itself,
because recording contradictions is what the extractor is for. `model.Model`
is the opposite contract: built once from a `corpus.Corpus`, it hands a
consumer a `Message` whose ABNF entries point at real `Avp` objects rather
than names, a `Grouped` that enumerates its members, an `Enumerated` that
carries its values, and every AVP knowing its `(vendor-id, code)` identity,
its type, its flag rules and which document defined it. The two hierarchies
stay separate on purpose — pressure to make the AST convenient is pressure to
make it lie, and pressure to make the model faithful to one file's wording
defeats its point.

```python
from seanchai import corpus, model

built = model.Model.build(corpus.Corpus.load([Path("dad")]))
for message in built.messages("TS29.229"):     # bodies resolved
    ...
built.avps("TS29.229")                          # a spec's dictionary view
built.resolve("TS29.229", "DRMP")               # one name, one spec's reading
built.find("Public-Identity")                   # every AVP under a name
built.identified(10415, 601)                    # every AVP claiming an identity
```

The query set is deliberately thin: each of these was written because the
mensonen/diameter validator needed it, which is the bar
[development.md](development.md#other-conventions) sets for API. The AST stays
public underneath for anything else.

### The resolution policy

A name resolves, in order, to the specification's own definition, then to the
origin its re-used table cites (read recursively in the origin's context, so
an indirect citation still lands on the real definition), then to an AVP-table
row, then to a `; Bases:` document. The order encodes the seam the roadmap
flagged:

- **Local definition over re-used listing** makes an *extension* mean what the
  extending document says, while a plain re-print resolves through the origin
  — the same copy the linter compares against.
- **The linter, not the model, reports the conflicts.** Anything
  `reused-body-differs` or `table-definition-mismatch` would report is
  resolved here by the order above without comment; run the linter to see
  what the policy papered over.
- **Vendor spaces follow the linter's reading**: a table row that is neither
  defined locally nor listed as re-used claims the file's own `; Vendor-ID:`;
  a definition with no vendor-id is IETF-space (vendor 0).

A name that resolves nowhere stays a name (`Member.avp` is `None`), as does
the `* [ AVP ]` wildcard, which is grammar rather than a reference.

Origin and base resolution use `corpus.Corpus.resolve` — the match-major-take-
newest rule [linter.md](linter.md#resolving-an-origin) documents — and every
reference-level query answers from the newest copy the corpus holds.

Not built yet, deliberately: carrying Wireshark's disambiguated name
(`Cx-User-Data`) alongside the specification's. The roadmap keeps it; it
wants a consumer that actually maps between the two namings, and the one
consumer written so far matches by `(vendor-id, code)` and never needed it.

## The validators

Item 8's two directions — *generate* a dictionary, *validate* an existing one
— share the model. Validation was built first, because it needs no opinion
about output syntax while exercising exactly the lookups a generator needs.
Each target gets a directory under `integrations/` with short scripts.
Inline script metadata (PEP 723) names each script's dependencies — the
target library, and seanchai itself from the repository — so uv supplies
everything:

```sh
uv run integrations/python_diameter/validate.py TS29.229
```

### python-diameter

[python-diameter](https://github.com/mensonen/diameter) folds every use of a
command into one class — a single `UserAuthorization` serving every
specification that defines command 300 — so "is this class right?" has no
single answer. What *is* checkable is one specification's claims at a time,
which is the scope the script takes as its argument: that document's
commands must exist under the right codes (the library's command classes
are discovered by code, not by name), each direction's `avp_def` must cover
the ABNF's members matched by `(vendor-id, code)` (names differ freely),
`is_required` must agree with the ABNF's brackets, and the document's own
AVPs must be right — name, type, mandatory default — in the library's global
dictionary for their vendor space. An "extra AVP" finding can be another
specification's legitimate use of the same command class, which is the
reader's part of the job; and a corpus AVP that resolves to no
`(vendor-id, code)` is reported as unchecked rather than judged. RFC 7155
was the big case — 77 AVPs whose RADIUS-heritage codes sat only in prose —
until the `prose-avp-codes` quirk started completing its table rows from
the defining clauses (see [extractor.md](extractor.md#quirks)).

The first run — scoped to Cx, the six TS 29.229 commands — reported 94
disagreements (library 0.9.0, corpus Rel-18; the library pins TS 29.229
version 13.1.0). The classes, most interesting first:

- **Wrong AVP entirely, 7 findings**: `LocationInfo`, `MultimediaAuth` and
  `PushProfile` classes carry RFC 4740's IETF `SIP-Auth-Data-Item` (vendor 0,
  code 376) and `SIP-Number-Auth-Items` (vendor 0, code 382) where TS 29.229
  specifies 3GPP's codes 612 and 607 — a wire-level incompatibility, not a
  naming choice.
- **Missing from a command, 18**: `Session-Id` and `DRMP` absent from
  `UserAuthorizationRequest.avp_def` (the class docstring itself shows
  `msg.session_id`), `Load` absent from every answer, `RTR-Flags`,
  `Failed-PCSCF` and others post-Release-13.
- **Present but not in the spec's ABNF, 11**: `user_name` and `server_name`
  on `LocationInfoRequest`, `destination_host`/`proxy_info`/`route_record`
  on `RegistrationTerminationRequest`, `sar_flags` on `MultimediaAuthRequest`.
- **`is_required` disagrees, 11**: `Auth-Session-State` is `{ }`-required in
  every answer but optional in the library; `Server-Name` and
  `Public-Identity` inverted in several directions.
- **M-flag default wrong, 28**: the library defaults the mandatory bit on
  for nearly every V-only AVP whose table row puts `M` in MUST NOT
  (`Supported-Features`, `Feature-List`, the whole 6.3.44–6.3.66 run).
- **Absent from the global dictionary, 9**: codes 659–666 (Rel-14+) — plus
  `Digest-QoP`, which is really RFC 4590's vendor-0 AVP that the corpus reads
  as a 3GPP claim because the AVP table's `Digest-QoP` spelling misses the
  re-used table's registered `Digest-Qop` (the linter knows this case).
- **Missing from a command, `Load` specifically**: reported as RFC 8583's
  `(0, 650)` because the corpus resolves it through TS 29.229's re-used
  table — where a correction moved it after the first run showed the source
  prints it as a code-less row in the wrong table (below).
- **Name disagrees, 8**: the library uses Wireshark's disambiguations
  (`Cx-User-Data`, `3GPP-SIP-Authenticate`, `Wildcarded-PSI`) — the known
  naming split [oracle.md](oracle.md) records, information rather than defect.
- **Type disagrees, 9**: ten Enumerated AVPs held as `AvpInteger32`.
  RFC 6733 derives Enumerated from Integer32, so the wire is identical, but
  the library holds other TS 29.229 enumerations as `AvpEnumerated` — an
  inconsistency worth a look either way.

The report is a statement about two artifacts, exactly like the Wireshark
oracle's: "missing" findings against a version-13 dictionary may simply be
Release 13's truth, and the reader decides what becomes an upstream issue.

### What validating Cx found in the corpus itself

The first consumer run was also the corpus's sharpest review to date; both
finds are recorded where they were fixed:

- TS 29.229's RTR body prints `RTR-Flags ]` with no opening bracket — docx
  and PDF alike — and the extractor, which stops an ABNF at the first line
  that is not one, silently dropped that line *and* the `*[ AVP ]`,
  `*[ Proxy-Info ]`, `*[ Route-Record ]` tail behind it. Fixed by an input
  patch (`edits/sources/TS29.229.toml`); the four recovered lines are the
  whole corpus diff.
- TS 29.229's RTA prints `< Session-Id >` twice (clause 6.1.10, docx and PDF
  alike). The corpus records it faithfully, and the corrections layer cannot
  yet express the fix: a `Delete` selector matching two identical nodes is
  ambiguous by design. The roadmap carries the missing occurrence-narrowing
  selector; until then the duplicate stands, harmless to the validator since
  both lines resolve to the same identity.
- TS 29.229 and TS 29.329 both tabulate `Load` among their own AVPs with no
  code at all, while their prose clauses define it only by reference to
  RFC 8583 — a re-used AVP printed in the wrong table. Corrections move the
  row into each file's re-used table, and the case became the linter's
  `row-without-code` rule ([linter.md](linter.md)): a table that declares a
  Code column must fill it, because an AVP without a code has no wire
  identity.
