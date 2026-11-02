# Website plan

A static site over the corpus: every `.dad` file as a page with syntax
highlighting, every AVP name a link to its definition, every page number a
link into the source document, and search. Hosted on GitHub Pages for the
public site, and buildable for self-hosting with the source PDFs beside it.
Nothing here is built yet; this records the design and its decisions.

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

Seanchaí gains an export command, `seanchai export -o DIR`, that writes
the resolved model as JSON. The site is a frontend over that JSON and holds
no Python. The export carries, per document: the file's text split into
token spans with a highlighting class each, taken from the AST so the
classes are exact and match the editor grammars; every name's resolution
target (document, section) from `Model.resolve`, including re-used names
and cross-release citations; the holes with their recorded reasons; the
linter's findings and accepted notes; each correction's id and reason;
the source link, version and page per section. Plus a search index of
every AVP, command and application name with its definer, identity and
Wireshark alias.

The export is tested like the generators: byte for byte over the committed
corpus, with every link target checked to exist.

## The site

A separate repository, a Vite application with client-side routing, taking
the export as input. Static hosting as a single-page app with hash routes,
or prerendered per document for shareable deep links; prerendering is
preferred once it is cheap.

- **Document page.** The `.dad` text verbatim, each token a span with its
  class. Names link to their definition, in this file or another. A
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
- **Search.** Client-side over the index: substring on names, aliases
  included, with a per-name panel showing definer, identity and every
  document that re-uses or tabulates it.
- **Deep links.** `#29272-i70/7.3.138` opens the document at the section
  and the pane at its page.

## Build and deployment

- Public: a GitHub Actions job in the site repository installs
  `seanchai` and `seanchai-corpus` from PyPI, runs the export, builds the
  site and deploys with the Pages actions. No source documents are
  downloaded.
- Self-hosted: the same build with a flag and a path to `specifications/`,
  copying the 3GPP PDFs (about 27 MB for the current corpus) and the
  PDF.js viewer into the output.

## Order of work

1. The export command and its tests.
2. The site: document page with highlighting and links, index, search.
3. The pane for RFCs.
4. The self-hosted mode with PDF.js.
5. Raw view, findings, corrections inline.
