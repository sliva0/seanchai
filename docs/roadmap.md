# Roadmap

Open work, grouped by area and ordered by value within each. Items are
lettered so they can be referred to; a finished item is removed and its
letter is not reused. What exists is described in the per-module documents.

## Format

- **A. `seanchai format`, preserving comments.** There is no way to
  normalise a hand-edited file from the CLI, and the parser discards `;;`
  comments, so normalising would delete every annotation. Proposal: a
  trailing comment belongs to the node on its line, a whole-line comment to
  the node on the next line; the parser returns `(spec, comments)` in the
  `Notes` shape `format_spec` already takes.
- **B. Key formatter notes and correction edits by tree path**, not
  `id(node)`. Works today because the tree outlives every use, but nothing
  enforces it. Same mechanism A wants; do them together.
- **C. `; EXTERNALLY-DEFINED` marker and a `Supply` correction.** For an
  enumerated AVP whose clause says the values live in another document
  (29.272's `Alert-Reason`): the extractor records the fact instead of an
  empty body, and `Supply` fills a whole hand-notated section, marked
  `;; supplied:` on every line, expecting the marker and no values. Waits
  for a consumer that needs those values.
- **D. Model the machine-readable source columns when a consumer asks.**
  29.212's "Acc. Type" and "Applicability", 29.214's "Applicability",
  29.061's "Applicable Reference Points", 29.172's re-used-table Code/Type.
  Three axes under four labels; modelling means deciding what each means.
  The extractor warns about them today, which is the right amount of
  machinery until then.

## Linter and corpus

- **E. A rule for one document's tables disagreeing about one AVP.** TS
  29.061 prints `3GPP-IMSI` in two per-interface tables with different flag
  rules and nothing reports it; today only conflicting *codes* fail. Compare
  same-name rows across one file's tables on type, flags and encrypt.
  Probably a note. Also check whether the model's first-table-wins `tabled`
  resolution should surface the ambiguity.
- **F. An occurrence-narrowing `Delete`.** TS 29.229's RTA prints
  `< Session-Id >` twice (clause 6.1.10); `Delete` treats two matches as
  ambiguity, so the corpus carries the duplicate.
- **G. Stage the Wireshark merge requests** listed in
  [oracle.md](oracle.md#what-still-reports).
- **H. Auto-expand advisory version ranges** when a newer or older version
  still applies cleanly, behind a CLI flag. Needs comment-preserving TOML
  rewriting.

## Sources

- **J. Remaining docx shapes.** 29.330's AVP table is a header row and one
  blank row (drop an all-blank table, keep the non-empty invariant). 29.230's
  registry tables lack the "AVP Flag rules" dispatch header. 29.305 is
  unexamined.
- **K. Legacy `.doc` specifications**: 29.201, 29.215, 29.217, 29.219,
  29.343, 29.368, 29.468, 32.299 and TR 29.909 ship as binary `.doc`. 32.299
  is an unresolved origin in six files, 29.368 in two. TS 29.154 is cited
  and not in the catalog at all.
- **P. RFCs 5580, 6734 and 6942**, cited by TS 29.273 and not in the
  catalog. Plain text like every other RFC, so adding them is catalog entries
  plus `regenerate --add`; each clears an unresolved origin.
- **L. Downloader: read the 3GPP archive throughout**, not only for the
  PDF-matched fallback, so every old version stays available for raw-vs-raw
  diffs; derive the ETSI `Link:` URL (needs the edition suffix, probably by
  listing the ETSI deliver directory); and stage a whole corpus version
  before publishing it, since a half-failed run today leaves a mix of old
  and new specs.

## Consumers

- **M. The *generate* direction.** Validation exists; what remains is a
  dictionary in a format the consumer chooses (Python classes, a JSON schema,
  XML). Seanchaí supplies definitions and queries; output syntax is the
  script's business.
- **N. Make the model rigid.** `Avp.code`, data type and flag rules are all
  `| None`, and every `None` is a hole in the corpus, not a fact about
  Diameter. When the upstream gaps (tables without type or flag columns for
  re-used rows, the standing unresolved references) are worked off, make the
  fields required so the model fails to build on an incomplete corpus — with
  whatever escape hatch hand-authored files turn out to need.
- **O. Carry Wireshark's AVP name in the model** alongside the
  specification's, for consumers interoperating with Wireshark-derived
  tooling. Waits for a consumer that maps between the namings; the corpus
  itself always keeps the specification's spelling.
