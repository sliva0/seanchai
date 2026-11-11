# The site export

`seanchai export -o DIR` writes the resolved corpus as JSON for
[seanchai-explorer](https://github.com/sliva0/seanchai-explorer), a static site
that shows every `.dad` file with highlighting, links names to their
definitions and page numbers into the source documents, and searches the
corpus. The site reads only what the export writes.

## Two modes

| Mode | Command | Sources in the export |
|---|---|---|
| Public | `seanchai export -o DIR` | RFC texts, if `--specifications` names a download holding them |
| Self-hosted | `seanchai export -o DIR --include-pdfs --specifications specifications` | RFC texts and every source PDF, about 24 MB |

In public mode the site opens a page number at ETSI's own URL with `#page=N`.
ETSI's PDF responses refuse framing and cross-origin reads from other sites
(checked 2026-11-02), so only a copy on the site's own origin can be shown
beside the document. That is what self-hosted mode copies in. Redistributing
ETSI's renderings publicly needs ETSI's written permission, so keep a
self-hosted export behind your own access control.

Neither mode needs a checkout. What each needs downloaded:

- `seanchai corpus download --only rfc --only wireshark` fetches the RFC
  texts and Wireshark's dictionary, without `seanchai[extract]`. Pass
  `--wireshark specifications/wireshark` to the export to put Wireshark's AVP
  names in the search index.
- `seanchai corpus download --only 3gpp --only transcribed` fetches the PDFs
  for `--include-pdfs`, the transcribed ones into
  `specifications/transcriptions/`. These need `seanchai[extract]`.

## Data boundary

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

`<id>` is the file's stem, as `29272-j60`. The files are compact JSON with
sorted keys; the grammar is copied as it stands. The same inputs give the
same bytes: there are no timestamps.

`seanchai.export_schema` holds the shapes as pydantic models.
`SCHEMA_VERSION`, now 2, is written into every file except `schema.json` and
the grammar, and changes when a reader would have to. `schema.json`'s root is
one of the four file shapes, so a fixture can be validated against it. A field
with no default is always written, null where it says nothing. A field with
one, as most of a token's, a line's and a block's are, is left out while it
holds it: a member with no `bold` is not bold, a block with no `rows` has none.

### The output directory

The export is built beside `DIR` and replaces it whole once it succeeds, so a
failed run leaves the previous export as it was. It refuses a non-empty `DIR`
unless `DIR/index.json` has `generator` `"seanchai"`, and refuses a corpus
with no documents.

### `index.json`

`generator` (always `"seanchai"`), `seanchai_version`, `corpus_version`,
`mode` (`public` or `self-hosted`), and a summary of every document.
`corpus_version` is null when `--corpus PATH` exported a corpus other than
the installed one. A summary's `interfaces` lists the Diameter interfaces or
reference points the document specifies, or an RFC's application, from the
corpus's `interfaces.toml`: `[]` for none, null where the corpus does not say.

### `documents/<id>.json`

A document holds:

- the file's text as tokens;
- `blocks`, its `; Type:` blocks as structure (below);
- `sections`, for a table of contents;
- its holes with their recorded reasons;
- the linter's findings and accepted notes;
- each correction's kind and reason, by citation;
- its `source`, whose `kind` is `etsi-pdf`, `rfc-text` or `other`, so the
  client knows what it can open.

An entry of `sections` has `section`, `page` and `title`, in document order
(6.3.4, 6.3.7A, 6.3.10, then annexes). The title comes from the clause's
`; Type:` and `; Name:`, as "Message User-Data-Request", "AVP Table" or
"Grouped AVP Server-Capabilities". A clause listing re-used origins reads
"Reused AVPs Server-Name". A clause only table rows name reads
"AVP PCSCF-FQDN" or "AVP 3GPP-IMSI and 37 more".

Joining every token's text gives the file byte for byte. A token may also
have:

- `target`: document, section, and for a re-used row's origin the AVP's
  `name`, from `Model.resolve`, re-used names and cross-release citations
  included;
- `source`: section and page, for a link into the source;
- `avp`;
- `correction`: the citation of a `;;` note;
- `kind`: `comment` for a `;;` comment, `correction-note` for one citing a
  correction.

Tokens carry no highlighting. The site highlights with
`syntax/dad.tmLanguage.json`, the editors' grammar. A line has `anchor` (the
clause it is the link target of), `section`, and, on a raw line the corrected
file changes, `warning`.

Correction reasons come from the corpus's `corrections.json`
([corrections.md](corrections.md#the-corrections-record)), so a plain
`pip install` has them. `--corrections DIRECTORY` reads them from a checkout's
correction modules instead. A note citing a correction the record lacks is
refused as a stale record.

### Blocks

`blocks` holds one entry per `; Type:` block in file order, in the document
and in its raw mirror alike, each describing its own file's lines. Every
`line` is an index into that file's `lines`. A block has `type`, `line` (its
`; Type:` line), `last` (its last line, a trailing comment included),
`section`, `page`, `fields` (its other directives as printed, `Name` to
`Applies-To`) and the `name` its `; Name:` or `; AVP:` gives. By type:

- Message, Answer Message, Grouped AVP, Reprinted AVP: `rule`, with the
  `::=` line and `members`. A member has `name`, `presence` (`fixed`,
  `required`, `optional`), `qualifier` as printed, `min` and `max` by RFC 6733
  clause 3.2 (`max` null for no bound), `bold`, and `struck` for a line the
  extractor comments out with its `; strikethrough`, which is no member of
  the rule the corpus reads. A Message has `abbreviation` and `command`:
  `code`, `request`, `flags`, `header_application_id`, the effective
  `application_id`, and `application`, `stated_in` and `scope` as the search
  entry reads them. A Grouped or Reprinted AVP has `avp`, its header's `code`
  and `vendor_id`.
- Enumerated AVP: `avp` and `values`, each a `value` with its `name` or a
  `reserved`, `void` or `vendor-specific` range `first` to `last`.
- AVP Table, Reused AVPs: `columns` and `rows`. A row has `name`, `cells` as
  printed (`""` blank, `-` a dash, quotes kept), `marks` per mark column,
  unquoted, and an AVP table row's `vendor`, the vendor space it places the
  AVP in.
- Registry: `columns`, `allocations` (`cells`, `code`, `name`,
  `abbreviation`, `documents` its Defined-In cell resolves to, and an AVP
  Codes row's `vendor`) and `reservations`.
- Value Table: `value_rows`, each `name`, `value`, a result code's own
  `section`, a feature's `mark`, and a result code's `origin` with the
  `origin_target` its token links to.

`commands` gives where a block's lines name a command, as `line`, `start` and
`end` character offsets: a Message's name, abbreviation and rule head, the
request and answer halves of a Command Codes row's name and abbreviation
cells, and a table's column named by one of the file's commands (TS 32.299's
ACR to CCA). Each has `code`, `request`, `name`, `abbreviation`, and `block`,
the index of the Message block it names, null for a registry's half.

### `search.json`

A search entry is one name as one document means it: an AVP, command,
application or registry row. It has its `target`, `defined_in`, and an
`identity` whose fields depend on the kind (`vendor_id` and `code` for an
AVP). A command's `application_id` is the effective one, from its header or
the Application Scope block covering its clause; `header_application_id` is
what the header prints. `abbreviation` is a command's own. `wireshark_name`
is Wireshark's name for an AVP, filled with `--wireshark`.

A value table's row is an entry of `kind` `value`. Its target is its clause,
and its `identity` has `value_kind` (`result-codes`, `bits`, `features`), the
`avp`, the `value`, and a feature's `application` and `feature_list_id`. Its
`defined_in` is a result code's `from` document where the row names one. In
the text:

- the name's token targets the clause;
- the `; AVP:` line targets the AVP;
- a result code's clause has a `source`, and its `from` document targets the
  clause listing the code there, with the code's `name`;
- a row in a subclause is that clause's `anchor`, and a clause only such rows
  name reads "Value DIAMETER_SUCCESS" in `sections`.
