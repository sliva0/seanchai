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
[downloader.md](downloader.md), [oracle.md](oracle.md)). Cheap to write now,
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

3. **Triage every standing finding, then promote `unresolved-reference` to
   an error.** The two lists are
   [linter.md's](linter.md#standing-findings-and-why-each-one-stays) and
   [oracle.md's](oracle.md#what-the-first-run-found); several entries appear
   on both, which is the strongest evidence available. Each finding needs
   the primary specification clause read, and then lands in exactly one of
   three buckets: a corpus correction (extractor or the document's own
   table wrong), a merge request into Wireshark (the dictionary wrong), or
   "correct on both sides, stays a finding" (Wireshark's deliberate
   disambiguations). Strength-of-evidence order: the double-witnessed
   defects first (RFC 5777's `IP-Bit-Mask-Width` and `Treatment-Action`,
   29.336's `Periodic-time`, RFC 4005's `Framed-Appletalk-*` casing), then
   the remaining RFC ABNF misspellings, then the 3GPP re-used-table
   omissions (row `Insert` or a second `; Bases:` entry, per document),
   then the unexamined tail. When the list is empty or explained, the rule
   flips to `ERROR` and `lint --corpus` permanently proves every reference
   in the corpus resolves.

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

7. **A consumer model, distinct from the `.dad` AST.** These are two type
   hierarchies with opposite jobs, and collapsing them into one would damage
   both.

   The AST mirrors a file one-to-one and its job is fidelity. It has to be
   able to represent a specification that contradicts itself, because that
   is what the extractor is for: a grouped AVP both defined locally and
   listed as re-used stays as two nodes, an AVP-table row whose type
   disagrees with its definition keeps disagreeing. Nodes are frozen,
   round-trip is exact, and references are unresolved strings because that
   is what the file contains. Pressure to make this layer convenient is
   pressure to make it lie.

   The consumer model is what a generator or validator actually wants: a
   message whose ABNF entries point at real AVP objects rather than names, a
   grouped AVP that can enumerate its members, an AVP that knows its own
   `(vendor-id, code)` identity, its type, its flag rules and which
   specification introduced it — with methods, and with cross-references
   already followed across files. Built once from a parsed corpus and handed
   to the consumer resolved.

   The seam between the two is where the linter's unresolved questions land:
   you cannot resolve a reference into an object without the `; Bases:`
   rule, the origin-version rule (both settled — see
   [linter.md](linter.md)), or a policy for which of two conflicting
   definitions wins — the last being exactly what `reused-body-differs`
   reports without deciding. The consumer model is therefore downstream of
   the standing-findings work (3), and the linter is the tool that reports
   those conflicts instead of the model having to silently pick.

   The queries every consumer would otherwise rewrite belong here: every
   message defined in a specification with its ABNF and metadata, every
   grouped AVP, every plain AVP, every enumerated AVP with its values, and
   lookup of a single AVP by name or by `(vendor-id, code)`. Keep the set
   thin — the test for adding one is that a real consumer wrote it by hand
   first, which keeps [development.md](development.md#working-on-these-documents)'s
   rule about not designing API ahead of a second consumer intact. The AST
   stays public underneath for anything the model does not cover.

   Two facts about names belong to this layer, not the corpus. Where
   Wireshark's dictionary spells an AVP differently — its deliberate
   disambiguations like `Cx-User-Data` — the consumer-facing data should
   carry Wireshark's name *as a piece of information* alongside the
   specification's, so a consumer interoperating with Wireshark-derived
   tooling can map between the two; the corpus itself always keeps the
   specification's spelling ([oracle.md](oracle.md)). And neither layer
   carries prose: `.dad` has nowhere to put a clause's paragraphs, and
   automatic description capture was tried and removed (`e9856a9`) —
   narrative stays in the specification the `; Section:` pointer names.

8. **Two consumer directions, both first-class**, over the same model (7):

   *Generate* a dictionary in a format the consumer chooses — Python class
   definitions for a library like
   [mensonen/diameter](https://github.com/mensonen/diameter), a JSON schema
   shaped like the 5G ones, an XML dictionary, whatever a given customer
   asks for. Seanchaí supplies the definitions and the queries; the output
   syntax is the script's business.

   *Validate* a dictionary that already exists. Someone who has already
   hand-written their format does not want it regenerated and rediffed —
   they want to know whether it is correct. A script walks their dictionary,
   resolves each entry against the corpus, and reports what disagrees: a
   wrong code, a stale type, an AVP the spec no longer defines that way.
   This is the more valuable of the two for anyone with an existing
   implementation, since it costs them nothing to adopt — and the better one
   to build first, because it needs no opinion about output syntax while
   exercising exactly the lookups a generator needs.

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
