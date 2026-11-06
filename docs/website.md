# Website plan

A static site over the corpus: every `.dad` file as a page with syntax
highlighting, every AVP name a link to its definition, every page number a
link into the source document, and search. Hosted on GitHub Pages for the
public site, and buildable for self-hosting with the source PDFs beside it.
The export it reads exists; the site does not yet, and the rest of this records
its design and decisions.

## Two deployments

The site builds in two modes from one code base, chosen at build time:

- **Public** (GitHub Pages): no source PDFs are redistributed. A page
  number or section opens ETSI's own URL with `#page=N` in a new tab. RFCs
  are shown in the side pane from rfc-editor.org, whose HTML and text are
  framed and fetched without restriction.
- **Self-hosted**: the builder copies the downloaded ETSI PDFs from
  `specifications/` into the site, and the side pane shows them through a
  vendored PDF.js viewer with page jumps and text highlighting. For an
  organisation's own use behind its own access control; redistributing
  ETSI's renderings publicly needs ETSI's written permission.

Why two modes: ETSI's PDF responses carry `X-Frame-Options: SAMEORIGIN`,
`Content-Security-Policy: frame-ancestors 'self'` and a CORS header
allowing only portal.etsi.org (checked 2026-11-02), so neither an iframe
nor an in-page PDF.js viewer can show ETSI's copy from another origin.
Only a copy on the site's own origin can be framed.

## Data boundary

`seanchai export -o DIR` writes the resolved model as JSON. The site is a
frontend over that JSON and holds no Python.

```text
DIR/
  index.json              generator, versions, mode, every document's summary
  search.json             search entries and line mentions, for the search page
  schema.json             JSON Schema of the other files
  syntax/dad.tmLanguage.json   the editors' TextMate grammar, for highlighting
  documents/<id>.json     one corrected file and what its page shows
  documents/<id>.raw.json its raw mirror, for the raw view
  sources/                RFC texts and, self-hosted, the source PDFs
```

`<id>` is the file's stem, `29272-j60`. The files are compact JSON with sorted
keys, the grammar aside, which is copied as it stands. `seanchai.export_schema`
holds their shape as pydantic models and `SCHEMA_VERSION`, now 6, written into
every file but `schema.json` and the grammar; it changes when a reader would
have to. A fixture can be validated against `schema.json`, whose root is one of
the four file shapes. A field with no default is always written, null where it
says nothing; the mostly empty `Token`, `Line`, `Target` and `Citation` fields
are left out while they hold their default.

`index.json` also carries `generator`, always `"seanchai"`, and
`seanchai_version` and `corpus_version`, the second null for a corpus other than
the installed one. There are no timestamps: the same inputs give the same bytes
under any hash seed.

An export replaces its whole output directory, so it refuses one that is not
empty unless its `index.json` says that `generator`, or has exactly the shape of
schema version 1, 2 or 3, which came before the marker.

A document carries the file's text split into tokens, its `sections` for a table
of contents, its holes with their recorded reasons, the linter's findings and
accepted notes, each correction's kind and reason by citation, and its source.
`source.kind` is `etsi-pdf`, `rfc-text` or `other`, so the client need not infer
what it can open.

An entry of `sections` holds `section`, `page` and `title`, in document order
(6.3.4, 6.3.7A, 6.3.10, then annexes). The title is what the file places in the
clause: its `; Type:` and `; Name:`, as "Message User-Data-Request", "AVP Table"
or "Grouped AVP Server-Capabilities". Several blocks name each kind once, and a
clause only table rows name reads "AVP PCSCF-FQDN" or "AVP 3GPP-IMSI and 37
more".

A token holds its text, and every token joined gives the file, byte for byte. It
holds what a link needs: `target` (document, section, and for a re-used row's
origin the AVP's `name`) from `Model.resolve`, re-used names and cross-release
citations included; `source` (section, page) for a link into the source; `avp`;
and `correction`, a note's citation. `kind` marks the one thing the client needs
structurally: `comment` for a `;;` comment, `correction-note` for one citing a
declaration. Highlighting is not in the tokens: the site runs the export's
`syntax/dad.tmLanguage.json`, so it cannot disagree with the editors. A line
holds `anchor`, the clause it is the link target of, `section`, and `warning` on
a raw line the corrected file changes.

A search entry is one name as one document means it: an AVP, command,
application or registry row, with its target, `defined_in`, and an `identity`
naming its fields per kind (`vendor_id` and `code` for an AVP). A command's
`application_id` is the effective one, from its header or from the Application
Scope block covering its clause, and `header_application_id` what its header
prints. `abbreviation` is a command's own and `wireshark_name` Wireshark's name
for an AVP, filled with `--dictionary specifications/wireshark`. A value table's
name is an entry of its own, `kind` `value`: its target is its clause, and its
`identity` holds `value_kind` (`result-codes`, `bits`, `features`), the `avp`,
the `value` and a feature's `application` and `feature_list_id`; its
`defined_in` is a result code's `from` document where the row names one. In the
text the name's token targets the clause too, its `; AVP:` line the AVP, a
result code's clause a `source` and its `from` document the clause listing the
code there; a row in a subclause is that clause's `anchor`, and a
clause only such rows name reads "Value DIAMETER_SUCCESS" in `sections`.

Correction reasons come from the corpus's `corrections.json`, so a plain
`pip install` has them
([corrections.md](corrections.md#the-corrections-record)). A note citing what
the record does not hold is refused as a stale record.

An export owns its output directory. It is built beside it and replaces it whole
once it has succeeded, so nothing of an earlier mode or generation lingers and a
failed run changes nothing. A directory holding anything but a previous export
is refused, and so is a corpus with no documents.

The export is tested over the committed corpus: every byte preserved, every
link target checked to exist, and a digest per file pinned
([development.md](development.md#tests)).

## The site

A separate repository, a Vite application with client-side routing, taking
the export as input. Static hosting as a single-page app with hash routes,
or prerendered per document for shareable deep links; prerendering is
preferred once it is cheap.

- **Document page.** The `.dad` text verbatim, highlighted with the export's
  grammar.
  Names link to their definition, in this file or another. A
  `; Section:` and a `; Page:` link into the source as the deployment mode
  allows. A `;; corrected:` note expands the correction's reason inline.
  `; Bases:` and From cells link to document pages. A raw/corrected
  toggle, and the linter's findings folded under the header.
- **Side pane.** Document on the left, source on the right, resizable,
  hidden on narrow screens. Public mode: RFCs only, from rfc-editor.org.
  Self-hosted mode: PDF.js for 3GPP documents, driven from the page
  (`PDFViewerApplication.page` and the find controller for the clause
  number), RFCs as before.
- **Index.** Documents by publisher and release, with versions and the
  catalog's titles. Older pinned releases listed under their release with
  a note on why they are held.
- **Search.** Client-side over `search.json`: substring on names, aliases
  included, with a per-name panel showing definer, identity and every
  document that re-uses or tabulates it.
- **Deep links.** `#29272-j60/7.3.138` opens the document at the section
  and the pane at its page.

## Build and deployment

- Public: a GitHub Actions job in the site repository installs
  `seanchai` and `seanchai-corpus` from PyPI, runs the export, builds the
  site and deploys with the Pages actions. No source documents are needed;
  `seanchai download --only rfc --only wireshark` adds RFC texts and Wireshark's
  names, with no `seanchai[extract]`.
- Self-hosted: the same build with `--include-pdfs --specifications
  specifications`, copying the PDFs (about 24 MB for the current corpus), and
  the PDF.js viewer into the output. `seanchai download --only 3gpp` fetches the
  3GPP ones and `--only transcribed` what the hand transcriptions were copied
  from, into `specifications/transcriptions/`.

## Order of work

1. The site: document page with highlighting and links, index, search.
2. The pane for RFCs.
3. The self-hosted mode with PDF.js.
4. Raw view, findings, corrections inline.
