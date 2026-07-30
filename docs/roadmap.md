# Roadmap

Open work, roughly in the order it delivers value. What already exists is in
the README's status section and the per-module documents; completed review
rounds are recorded in [history/](history/). Finished work leaves this file —
the code and the document that owns the area say everything there is to say
about it.

When you learn something non-obvious while working — a source-document quirk,
a workflow gotcha, a convention that isn't visible in the code — write it
down in the document it belongs to ([extractor.md](extractor.md),
[workflow.md](workflow.md), [dad-format.md](dad-format.md),
[downloader.md](downloader.md), [oracle.md](oracle.md),
[consumers.md](consumers.md)). Cheap to write now,
expensive to rediscover later.

Before adding items here, read the conventions in
[development.md](development.md#working-on-these-documents) — several
tempting additions are settled decisions, not gaps.

Items are numbered so they can be referred to in a conversation. Finishing
one leaves a gap rather than renumbering what follows, so a number keeps
meaning the same item for as long as that item is open. New work takes the
next unused number, and nothing outside this file should cite one, because
the numbers do not survive a reorganisation of the document itself.

## Format

The format is deliberately unstable until publication — see the notices in
[grammar.md](grammar.md) and [dad-format.md](dad-format.md) — so a change
that needs it should just make it.

1. **Model the per-specification columns that carry machine-readable values,
   when a consumer needs them.** Free columns were tried and removed: every
   unmodelled source column so far turned out to hold prose, which `.dad`
   does not carry. The extractor warns about every unmodelled column that is
   not a known prose label, so the machine-readable candidates are visible
   rather than lost — see
   [extractor.md](extractor.md#columns-the-format-does-not-model). They are
   TS 29.212's "Acc. Type" (`3GPP-EPS`, `All`, `FBA`) and "Applicability"
   (`CC`/`PC`/`Both` plus feature names), TS 29.214's "Applicability"
   (feature names only), TS 29.061's "Applicable Reference Points" (`Gi`,
   `Sgi`), and the AVP Code / Value Type columns TS 29.172 prints in its
   *re-used* table.

   Modelling them means deciding what they mean, and they do not all mean
   the same thing: three axes under four labels, with the two columns named
   "Applicability" overlapping only partly. That is the work, and it wants a
   consumer asking for the data rather than a tidy-up impulse — until then
   the warning is the right amount of machinery.

2. **Add a `seanchai format` command, and make it preserve comments.** There
   is no way to normalise a `.dad` file from the CLI today, which
   [dad-format.md](dad-format.md) nonetheless assumes when it says hand
   edits are normalised by running the formatter. Adding the command is
   small; the part that needs designing is that `;;` comments do not survive
   a round trip — the parser discards them, so normalising a hand-authored
   file silently deletes every annotation in it.

   How comments attach is settled as a proposal: **a trailing comment
   belongs to the node whose line carries it, and a whole-line comment to
   the node whose line follows it.** Every non-comment line of a block maps
   one-to-one onto an AST node, so the parser can return `(spec, comments)`
   where `comments` is exactly the `Notes` mapping `format_spec` already
   accepts, and the command becomes
   `format_spec(*parse_with_comments(text))` with almost no new formatter
   code. Comments between blocks attach to the following section; comments
   in the file header attach to the `Specification`; the one genuinely new
   piece is a trailing bucket for comments after the last line of the file.
   Anchoring by line offset was considered and rejected: offsets drift when
   a section's line count changes; node anchoring is the mechanism
   correction notes already use.

## Linter and corpus quality

Both linter layers, reference resolution via `; Bases:`, and the Wireshark
oracle are built — [linter.md](linter.md) and [oracle.md](oracle.md) describe
the rules and what the corpus reports today. What remains is working the
standing findings off.

3. **Stage the Wireshark merge requests the triage identified.** The triage
   itself is done (July 2026): every standing linter and oracle finding was
   read against its primary clause, fifty of the fifty-five unresolved
   references became corrections, and what remains is documented in
   [linter.md](linter.md#standing-findings-and-why-each-one-stays) (five
   references to AVPs no document defines — unrepairable until upstream
   moves, and the reason `unresolved-reference` stays a note) and
   [oracle.md](oracle.md#the-triage-and-what-stands-after-it). The open
   work this leaves is the Wireshark-side defect list in oracle.md —
   `Call-Barring-Infor-List`, `Accounting-Multi-Session-Id`,
   `Authorization-Lifetime`'s Integer32 and the rest — each a candidate
   merge request into Wireshark's `resources/protocols/diameter/`
   dictionary, with the evidence already written down per finding.

20. **A linter rule for one document's tables disagreeing about one AVP.**
    A document with several definition sets can tabulate the same AVP more
    than once, and nothing today compares those rows against each other:
    the extractor fails only when the *codes* conflict (`_resolve`'s
    cross-table check), `duplicate-identity` wants two different names on
    one code, and `table-definition-mismatch` compares a row against its
    defining clause, not against another row. The real case: TS 29.061
    prints `3GPP-IMSI` (code 1, clause 16.4.7) in both its Gmb table 9a
    (§16a.5) and its SGmb table 10 (§17.7.0), with `Must: V` in one and
    `Must: M,V` in the other — a flag-rule disagreement the corpus records
    faithfully and nothing reports. The rule should compare same-name rows
    across one file's AVP tables on the cells the code check does not
    cover — type, flag rules, encrypt — and report disagreement per pair.
    Probably a note rather than an error: per-interface tables may
    legitimately impose different flag rules on one AVP (that is arguably
    what a per-interface table *is* for), so the finding is a
    reader-with-the-document-open call, like the oracle's. Also worth
    checking when implementing: whether the consumer model's
    first-table-wins `tabled` resolution should surface the ambiguity to
    consumers instead of silently picking the first row.

## More sources

Of the 34 specifications the downloader fetches, eighteen extract cleanly
and all eighteen are committed (plus sixteen RFCs). The rest fail in two
classes, and the classes matter more than the individual specs. 29.213 is
the one confirmed non-member: it holds no ABNF and no AVP tables — a
signalling-flows document with no dictionary content — so its rejection is
the extractor being right.

4. **Nine specifications never reach the extractor at all**, because 3GPP
   ships them as legacy binary `.doc` rather than `.docx`: 29.201, 29.215,
   29.217, 29.219, 29.343, 29.368, 29.468, 32.299 and TR 29.909. Reading
   that format, or finding a source that offers them as `.docx`, is a
   prerequisite the corpus does not currently admit to having. The citation
   pressure ranks them: 32.299 is an unresolved origin in six files
   (29.128, 29.172, 29.272, 29.336, 29.345, 29.389), 29.368 in two (29.336,
   and 29.337, which draws five reused AVPs from it), 29.217 in two. TS
   29.154 is also cited (29.214, 29.336) and is not in the catalog at all
   yet.

5. **Model the document shapes the remaining `.docx` specs use.** 29.228
   and 29.328 hold the Cx and Sh *messages* while 29.229 and 29.329 hold
   their AVPs, so a message-only document is a shape to model rather than
   reject. 29.330 arrives at the same shape differently: its AVP table
   holds a header row and one blank row, because the Sc interface defines
   no AVPs of its own — the fix is to drop an all-blank table (the AST's
   "tables are non-empty" invariant should stay) and then handle the
   message-only document it leaves. 29.230's registry tables need their own
   path — they lack the "AVP Flag rules" header the table dispatch keys on,
   and would be `_walk_table`'s third caller. 29.305 is unexamined.
   Related, and also a shape assumption: 29.273 has a command section with
   no ABNF; it is an unresolved origin in five files (29.173, 29.212,
   29.214, 29.272, 29.345), which makes it the most valuable single spec in
   this item.

6. **Downloader changes** for full archive fetching and link derivation —
   the remaining planned changes are listed in
   [downloader.md](downloader.md#planned-changes).

## Downstream consumers

This is the point of the project, and the reason the rest of it is worth
doing: Diameter has no published machine-readable schema the way 5G's 3GPP
protocols have OpenAPI, so every implementation invents its own dictionary
format. The deliverable is not a format everyone adopts — it is that
generating *your* format becomes a short script over a reviewed corpus.

7. **Carry Wireshark's AVP name in the consumer model.** The model itself is
   built — `src/seanchai/model.py`, with its resolution policy and query set
   recorded in [consumers.md](consumers.md) — and its one deliberately
   unbuilt piece is this: where Wireshark's dictionary spells an AVP
   differently — its deliberate disambiguations like `Cx-User-Data` — the
   consumer-facing data should carry Wireshark's name *as a piece of
   information* alongside the specification's, so a consumer interoperating
   with Wireshark-derived tooling can map between the two; the corpus itself
   always keeps the specification's spelling ([oracle.md](oracle.md)). It
   waits for a consumer that actually maps between the namings: the
   mensonen/diameter validator matches by `(vendor-id, code)` and never
   needed it, and adding it unasked would break the model's rule that every
   query was written by a real consumer first.

8. **The *generate* consumer direction.** Validation came first and exists:
   `integrations/python_diameter/validate.py` checks the
   [mensonen/diameter](https://github.com/mensonen/diameter) library against
   any one specification the corpus holds, passed as an argument; findings
   and scope reasoning are in [consumers.md](consumers.md). What remains is
   *generate*: a dictionary in a format the consumer chooses — Python class
   definitions for a library like mensonen/diameter, a JSON schema shaped
   like the 5G ones, an XML dictionary, whatever a given customer asks for.
   Seanchaí supplies the definitions and the queries; the output syntax is
   the script's business.

19. **Make the consumer model rigid: an `Avp` should always carry a code, a
    data type and flag rules.** All three are `| None` in `model.py` today,
    and every `None` is a hole in the corpus rather than a fact about
    Diameter — an AVP without a code has no wire identity, and one without
    a type cannot be decoded. The current sources of `None` (RFC 7155's
    code-less rows were the largest and are closed — the `prose-avp-codes`
    quirk, July 2026): tables that print no type or flag columns for
    re-used rows, definitions never tabulated at all, and the standing
    linter findings that keep some references unresolved. Each hole a
    consumer hits is really one of those upstream gaps; when they are
    worked off, the fields should become required so the model *fails to
    build* on an incomplete corpus instead of handing consumers `None` to
    re-check — with whatever escape hatch hand-authored extension files (9)
    turn out to need.

9. **Keep hand-authored `.dad` files viable**, so a proprietary Diameter
   extension or an uncovered specification can be written directly and slot
   into the same parser, linter and consumers. Nothing needs building for
   this now, and it should not grow features ahead of a real case; it is
   here because it is a standing constraint on format changes — see the
   design intent in [dad-format.md](dad-format.md#design-intent).

## Smaller items

10. A version type shared by input patches and corrections, so a recorded
    range can be compared against the parsed version and *warn* when it no
    longer covers it. Both layers currently record ranges without comparing
    them, and both must keep applying regardless — the range explains, it
    never gates.

11. A CLI flag that auto-expands an input patch's
    `first_version`/`last_version` range when a newer or older version is
    parsed and the patch still applied cleanly. Needs comment-preserving
    TOML rewriting (e.g. tomlkit), and the shared version type above (10).

12. Fix the `atomic_download` corrupt-cache wart described in
    [downloader.md](downloader.md).

13. Stage a whole corpus version before publishing it. `replace_extracted`
    rolls back a failed directory swap and a failed run no longer leaves a
    stale `manifest.json` behind, so no single artifact is corrupted — but a
    run that fails halfway still leaves a corpus where some specs are the
    new version and some are the old one. Only staging the whole thing
    fixes that.

14. Formatter notes and correction edits are keyed by `id(node)`, which
    works because the tree outlives every use but is an invariant nothing
    enforces — a caller that let the original tree be collected between
    `apply()` and `format_spec()` could see ids reused. Keying both by tree
    *path* would make the contract explicit; the same mechanism is what
    comment preservation (2) wants, so do them together.

15. `test_formats_every_section_and_optional_field_canonically` pins the
    canonical layout with space-counted string literals inside assertions.
    One committed golden `.dad` fixture compared whole would say the same
    thing and be reviewable as a file.

16. `Correction`, `Delete` and `Insert` in `corrections.py` each carry the
    same `reason`/`versions`/`origin` fields and the same `__post_init__`
    stamping `origin` via `_declared_at()` — three hand-rolled copies of one
    declaration contract. Not worth a base class for three; it is worth one
    the day `Supply` would make a fourth copy, so fold the shared shape out
    as part of implementing it.

17. A `Delete` selector cannot remove one of two *identical* nodes: `apply`
    treats a multi-match as ambiguity, which is right everywhere except TS
    29.229's RTA, whose ABNF prints `< Session-Id >` twice (clause 6.1.10,
    docx and PDF alike — found by the first consumer validation, see
    [consumers.md](consumers.md)). An occurrence-narrowing selector, or a
    deduplicating delete whose expectation is that exactly two equal nodes
    match, would let the corrected file drop the second line; until then the
    corpus carries the duplicate faithfully.
