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
  commands.json           every document's commands and Command Codes rows
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
`SCHEMA_VERSION`, now 3, is written into every file except `schema.json` and
the grammar, and changes when a reader would have to. `schema.json`'s root is
one of the five file shapes, so a fixture can be validated against it. A field
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
`mode` (`public` or `self-hosted`), `releases`, the 3GPP releases the corpus
holds whole, and a summary of every document. The export holds every copy of
every release: a summary's `release` says which a 3GPP copy is of, and
`pinned` gives the reason the catalog holds a copy only for citations, null
for a copy of a release held whole. Each copy's page is read as its own
release reads it ([consumers.md](consumers.md#releases)): its holes, targets
and the commands its tables describe come from that release's model.
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
- `correction`: the citation of a `;;` note, a correction's
  `TS29.272.py#area-scope-code` or an interpretation's
  `TS29.272.dadx#imei-digits`;
- `kind`: `comment` for a `;;` comment, `correction-note` for one citing a
  correction or an interpretation.

Tokens carry no highlighting. The site highlights with
`syntax/dad.tmLanguage.json`, the editors' grammar. A line has `anchor` (the
clause it is the link target of), `section`, and, on a raw line the corrected
file changes, `warning`.

Correction reasons come from the corpus's `corrections.json`
([corrections.md](corrections.md#the-corrections-record)), so a plain
`pip install` has them. `--corrections DIRECTORY` reads them from a checkout's
correction modules instead, and with it `--interpretations DIRECTORY` its
interpretations files. A note citing a correction the record lacks is
refused as a stale record.

### Blocks

`blocks` holds one entry per `; Type:` block in file order, in the document
and in its raw mirror alike, each describing its own file's lines. Every
`line` is an index into that file's `lines`. A block has `type`, `line` (its
`; Type:` line), `last` (its last line, a trailing comment included),
`section`, `page`, `fields` (its other directives as printed, `Name` to
`Applies-To`) and the `name` its `; Name:` or `; AVP:` gives. By type:

- Message, Answer Message, Grouped AVP: `rule`, with the
  `::=` line and `members`. A member has `name`, `presence` (`fixed`,
  `required`, `optional`), `qualifier` as printed, `min` and `max` by RFC 6733
  clause 3.2 (`max` null for no bound), `bold`, `strikethrough` for a member
  printed struck through and kept, and `struck` for a line the
  extractor comments out with its `; strikethrough`, which is no member of
  the rule the corpus reads. A Message has `abbreviation` and `command`:
  `code`, `request`, `flags`, `header_application_id`, the effective
  `application_id`, the `application` the search entry names, and
  `application_clause`, the Application Scope clause to cite for it: for a
  bare header the one covering the command's clause, which states the id,
  else the one naming the application. Both are left out where no scope names
  it. `described_by` lists the Information Elements blocks describing the
  command, in any document (TS 29.228's for TS 29.229's commands), each its
  `document`, `section` and `table`: the reverse of their `described`. An
  Answer Message has no `name`, as its `<answer-message>` names no command:
  its rule's `name`, `answer-message`, is what labels it. A Grouped AVP has
  `avp`, its header's `code` and `vendor_id`; one reprinting another
  document's rule has `Reprints` in `fields`, its token targeting that
  document.
- Enumerated AVP: `avp` and `values`, each a `value` with its `name` or a
  `reserved`, `void` or `vendor-specific` range `first` to `last`.
- AVP Table, Reused AVPs: `columns` and `rows`. A row has `name`, `cells` as
  printed (`""` blank, `-` a dash, quotes kept), `marks` per mark column,
  unquoted, the `code` its Code cell prints, the `type` its Type cell prints
  where that is a Diameter data type (`DataType` in the schema), and an AVP
  table row's `vendor`, the vendor space it places the AVP in.
- Registry: `columns`, `allocations` (`cells`, `code`, `name`,
  `abbreviation`, a data `type` as a row's, `documents` its Defined-In cell
  resolves to, and an AVP Codes row's `vendor`) and `reservations`.
- Information Elements: `name`, the command its `; Command:` names,
  `columns` (`Name`, `AVP`, `Cat`, or `AVP`, `Cat` for TS 32.299's tables),
  `element_rows`, each `name` (null with no Name column), `cells` as
  printed, the `avps` its mapping cell names with `either` where it offers
  one of them, the cell as `printed` where it names none, `category` (`M`,
  `C`, `O`, `OM`, `OC`, `-` not used, null blank) and `depth`, the levels it
  is set off under a grouped AVP's row;
  and `described`, the Message blocks the corrected file's table finds its
  command at, empty in the raw view and where none is found. Its `; Command:`
  line's name and its rows' AVP names link where the command reads them.
- Command Result Codes: `name`, the command its `; Command:` names,
  `result_codes`, each `name` and the `value` and `vendor_id` the
  result-code tables give it (null where none does, and in the raw view),
  and `described`, as an Information Elements block's.
- Value Table: `value_kind` (`result-codes`, `bits`, `features`, `values`), a
  feature list's `feature_list_id` and `application`, the `avp_target` its
  `; AVP:` line links to, and `value_rows`, each `name`, `value`, a result
  code's own `section`, a feature's `mark`, and a result code's `origin` with
  the `origin_target` its token links to.
- Interpreted Constraints: `name`, the AVP its `; AVP:` names, with the
  `avp_target` that line links to; `interpreted`, true only here, for a block
  a person read in the clause's prose ([constraints.md](constraints.md));
  `quoted_from_pdf`, true for a hand transcription's block, its quotes held
  to the text of the PDF the document was copied from
  ([constraints.md](constraints.md#the-interpretations-file));
  its scope and `Versions` in `fields`; and `readings`, each `quotes` (`line`
  and `text`, unescaped) and `rules`, each at its `line`, the first of a rule
  wrapped over several, with `kind` and the fields of the dictionary's rule
  ([consumers.md](consumers.md#the-dictionary)), an `encoding element`
  rule's `element_entry` being omitted where the element registry has no
  entry for the element ([constraints.md](constraints.md#elements)); and
  `request_target`, where the request its rules read is printed, for a
  block scoped to an answer whose rules read one (`root` `request` on a
  condition or reference). A condition carries `value`, `bit`, or
  `values`, an `in` list's numbers, names and ranges `{"low", "high"}`, as
  the dictionary's does ([consumers.md](consumers.md#the-dictionary)).
  A clause nothing printed stands in, as a simple-typed AVP's, reads
  "Interpreted Constraints IMEI" in `sections`.

`commands` gives where a block's lines name a command, as `line`, `start` and
`end` character offsets: a Message's name, abbreviation and rule head, the
request and answer halves of a Command Codes row's name and abbreviation
cells, and a table's column named by one of the file's commands (TS 32.299's
ACR to CCA). Each has `code`, `request`, `name`, `abbreviation`, and `block`,
the index of the Message block it names, null for a registry's half, which
has `allocation` instead, its row's index in the block's `allocations`.

### `commands.json`

What a page shows of a command another document defines, small enough to
fetch beside one document. `commands` lists every Message block in document
order: the document's `id`, `name`, `abbreviation`, `section`, `page`, `line`
(its `; Type:` line), `code`, `flags` as printed, `header` (the id the header
prints), `application` (the effective id) and `scope`, the `name` and
`section` of the block's `application` and `application_clause`. `registry`
lists every Command Codes registry row with a code and a name: `document`,
`code`, `name`, `abbreviation`, `section`, `page`, `line`, `table` and
`defined`, its row's `documents`. `applications` maps an application id to
the name the first Application IDs registry row allocating it prints.

### `search.json`

A search entry is one name as one document means it: an AVP, command,
application, registry row, value or information element. It has its `target`,
`defined_in`, and an `identity` whose fields depend on the kind (`vendor_id` and
`code` for an AVP). A command's `application_id` is the effective one, from its
header or the Application Scope block covering its clause;
`header_application_id` is what the header prints. `abbreviation` is a command's
own. `wireshark_name` is Wireshark's name for an AVP, filled with `--wireshark`.

An information element is an entry of `kind` `element`, one per row of an
Information Elements block. Its target is the block's clause, and its
`identity` has the `category`, the `avps` it maps to and the `command` its
table describes.

A value table's row is an entry of `kind` `value`. Its target is its clause,
and its `identity` has `value_kind` (`result-codes`, `bits`, `features`,
`values`), the
`avp`, the `value`, and a feature's `application` and `feature_list_id`. Its
`defined_in` is a result code's `from` document where the row names one. In
the text:

- the name's token targets the clause;
- the `; AVP:` line targets the AVP;
- a result code's clause has a `source`, and its `from` document targets the
  clause listing the code there, with the code's `name`;
- a row in a subclause is that clause's `anchor`, and a clause only such rows
  name reads "Value DIAMETER_SUCCESS" in `sections`.
