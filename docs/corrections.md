# Corrections

Every fix to a document is declared in an edit layer, states what it expects
to find, and fails once that is gone, so a fix made upstream shows up as a
failure.

## The edit layers

| Layer | Fixes | Where |
|---|---|---|
| transcriptions | documents no extractor reads, copied by hand as printed | `edits/transcriptions/<SpecRef>.dad` |
| input patches | source typos that break extraction, and case-only misspellings of a name | `edits/sources/<SpecRef>.toml`, `[[patch]]` |
| quirks | readings too heuristic to run undeclared | same file, `[[quirk]]` |
| exclusions | clauses the document has not finished, left out of both files | same file, `[[exclude]]` |
| extractor code | exact-match structure that fails loudly on its own | `src/seanchai/extractor/` |
| corrections | data that parses but is wrong | `edits/corrections/<SpecRef>.py` |
| interpretations | what a clause's prose says of an AVP's value or presence | same file, `Interpret` |
| acceptances | linter notes a clause makes deliberate; no data changes | same file, `Accept` |

[extractor.md](extractor.md#source-declarations) covers input patches,
quirks and exclusions, and [transcriptions](extractor.md#transcriptions).
This file covers corrections and acceptances
(`src/seanchai/dad/corrections.py`).

## The file

A correction module holds a module-level `CORRECTIONS` list:

```python
from seanchai.dad.corrections import Correction, definition

CORRECTIONS = [
    Correction(
        id="area-scope-code",
        target=definition("Area-Scope"),
        field="code",
        expect=1623,
        replace=1624,
        reason="clause 7.3.138's AVP header prints Job-Type's code; table"
        " 7.3.1/1 and the TS 29.230 registry both assign Area-Scope 1624",
        versions="18.6.0..18.7.0",
    ),
]
```

The node is rebuilt through pydantic, so a wrong `field` or value fails.
`id` is kebab-case, unique in the module, and names what is corrected
(`bearer-identifier-spelling`), not where.

## Semantics

- `expect` is required and checked. A mismatch is an error.
- A target must match exactly one node. Narrow it with a discriminator:
  `definition("Update-Location-Request", application_id=16777251)`.
  `application_id=None` filters for no id; omitting the argument does not
  filter.
- `versions` is `"18.6.0"` or `"18.0.0..18.2.0"`, inclusive, with `*` for an
  open bound; patches and quirks use the same type. A declaration applies to
  the releases its range spans, to an older undeclared release below them
  and to a newer one past them, checked as ever
  ([extractor.md](extractor.md#releases)); an interpretation only to the
  releases its range spans ([below](#interpreted-constraints)). Within a
  release the range only warns: `regenerate` reports a parsed version
  outside it but still applies the declaration. Write it as a string literal
  so `--expand-ranges` can rewrite it
  ([development.md](development.md#version-upgrades)).
- Corrections apply to raw files only, transcriptions included. Correcting a
  corrected file fails every `expect`, which keeps "already corrected"
  distinct from "fixed upstream".
- Selectors address identity:
  - `definition(name)`, `undefined(name)`, `application_scope(name)`,
    `header()`
  - `table_row(name, table=)`, `flag_rules(table_row(...))` (one field per
    correction, so moving a flag from Must to Must not is two),
    `reused_row(name, section=)`
  - `avp_table(label)` and `reused_avps(label, section=)`, with `None` for a
    table or block printing no label
  - `enum_value(avp, name, value=, occurrence=)`,
    `avp_rule(parent, name, occurrence=)`
  - `value_table(avp, section=, feature_list_id=)`,
    `value_row(parent, name, value=)`, `parent` being a `value_table` or the
    AVP's name
  - `registry_row(registry, code)`, `registry_reservation(first, last)`
  - `information_elements(label, section=)`, `None` and the clause for a
    table printing no caption, and `element_row(parent, name, occurrence=)`,
    `parent` an `information_elements`
- `occurrence=n` picks the n-th of several identical rules or values of one
  name in one body, as in TS 29.229's RTA, which prints `< Session-Id >`
  twice. It fails once the name stops repeating.
- A correction replaces one field of one node. Structural fields such as
  `avps` cannot be replaced. Several corrections to one node apply in
  declaration order. Two corrections to the same field, or replacing a value
  with itself, are rejected.
- All corrections resolve against the original tree before anything is
  rebuilt, so a failure leaves no half-corrected file.

## Operations

`Correction(id, target, field, expect, replace, reason, versions)` replaces
one field. A blank field takes `expect=None`: RFC 4590 states no Diameter type
for the attributes RFC 4740 imports as AVPs, and its module supplies them
citing TS 29.229 and Wireshark's dictionary.

`Delete(id, target, expect, reason)` removes a node. `expect` is the whole
node, so the deletion fails when upstream changes or removes it. Deleting a
node while correcting something inside it, or emptying a table, is refused.

`Insert(id, into, node, after, reason)` adds a node and expects no node of
that name to exist.

| `into` | `node` | `after` |
|---|---|---|
| `avp_table(label)`, `reused_avps(label)`, `value_table()` | a row | the row it follows, or `None` to append |
| `definition(name)` | an `ast.AvpRule` or `ast.EnumValue` | the member or value it follows |
| `header()` | an `Application Scope` or `Undefined AVP` block | `None` |

- `reused_avps(label)` matching no block creates the re-used block after
  the AVP table with that label; `reused_avps(None, section="5.2")` does so
  for RFC 5779's unlabelled table.
- `drawn_from` names the source of the node's fields, for the note to print:
  `from clause 16.4.7`.
- An inserted `Undefined AVP` block expects no definition, row or block of
  that name in the corrected tree, and a body in its clause that uses it.
- A row with a vendor its table has no column for needs a `Correction`
  adding `Vendor-ID` to the table's `columns` first (TS 29.229's
  `Line-Identifier`, in ETSI's vendor 13019).

`Supply(id, target=definition(name), expect, values, reason)` fills the
values of an enumerated AVP whose clause cites another document for them.
`expect` is the `; Values:` text and the AVP must have no values. `reason`
cites the external clause, or a registry's name and last-updated date. With
`extend=True` the values follow a partial printed list, and a name or number
already printed is refused (RFC 4005's NAS-Port-Type prints 0 to 25).

`Supply(id, target=table_row(name, table=), expect, data_type=, flag_rules=,
reason)` fills the blank Type or flag cells of an AVP-table row typed by
reference (TS 32.299 table 7.2.0.1's `refer [223]`). `expect` is the whole
row, and the file must list the AVP as re-used.

There is no free-form edit, `move` or `split`. A new structural case gets a
named operation with its own `expect`.

## Interpreted constraints

`Interpret` declares what a person read in a clause's prose about one AVP's
value or presence, as rules of a closed set of kinds, each after the
sentences it was read from (`src/seanchai/dad/interpret.py`). It inserts an
`Interpreted Constraints` block
([grammar.md](grammar.md#interpreted-constraints)) into the corrected file,
in clause order after the last block of its clause or one before it, marked
on its `; Type:` line:

```python
from seanchai.dad.ast import Codec
from seanchai.dad.interpret import Interpret, encoding, exclude, reading

CORRECTIONS += [
    Interpret(
        id="visited-plmn-id-layout",
        avp="Visited-PLMN-Id",
        section="7.3.9",
        readings=(
            reading(
                (
                    "This AVP shall contain the concatenation of MCC and MNC.",
                    "The content of this AVP shall be encoded as an octet"
                    " string according to table 7.3.9-1.",
                ),
                encoding(Codec.PLMN_ID),
            ),
        ),
        versions="19.6.0",
    ),
    Interpret(
        id="apn-configuration-context-identifier",
        avp="Context-Identifier",
        within="APN-Configuration",
        section="7.3.35",
        readings=(
            reading(
                "The Context-Identifier in the APN-Configuration AVP shall"
                " identify that APN configuration, and it shall not have a"
                " value of zero.",
                exclude(0),
            ),
        ),
        versions="19.6.0",
    ),
]
```

```dad
; Type: Interpreted Constraints ;; interpreted: (TS29.272.py#visited-plmn-id-layout)
```

- The rules are built by `octets`, `digits` and `characters` (`length`),
  `range_of`, `exclude`, `encoding` and `element`, `present_if`,
  `absent_if`, `requires` and `excludes` over `present`, `equals` and `bit`
  conditions (a bare name is `present`), and `text_only`.
- `command` (with `application_id`) or `within` scopes the rules to the AVP
  as a member of that command or grouped AVP; `table` names the table
  printing the quotes, an information element's description.
- Applying it expects the corrected file to hold every AVP it names, one
  command of the scope's name, the AVP in the command's or the grouped
  AVP's printed body, and no other block for the same AVP, scope and
  clause.
- `seanchai corpus regenerate` holds every quote to the clause it cites:
  it must be within one paragraph or table cell of the clause once
  whitespace is collapsed, as the extractor reads it. A miss fails the
  document, as an `expect` does. A transcription has no source text to hold
  a quote to, so a module for one is refused.
- The block's `; Page:` is not declared: it is the clause's page in the copy
  corrected, from the PDF's outline, or for an RFC the page its section
  starts on, which `regenerate` reads from the source, so that one
  declaration serves the copies of several releases. Applied without the
  source (`seanchai corpus correct`), a block carries no page.
- `reason` is not declared: the record holds the quotes.
- An interpretation applies only to copies of the releases its range spans,
  since whether a clause prints a sentence is a fact of each copy. Another
  release's are not applied to a copy, but offered: `regenerate` counts them
  in a warning, and with `--expand-ranges`, on a copy of a release no
  interpretation of the module spans, it holds the quotes of each of the
  nearest reviewed release's (the oldest above, else the newest below) to
  the copy's text. Each it finds is applied and its range widened to the
  copy; each it does not is reported as `not carried:` with the sentence the
  clause lacks, and stays out. Going back to Release 18, 149 of TS 29.272's
  154 carried; the five that did not read sentences Release 19 added. A
  declaration built in a comprehension, whose id is not a literal, is widened
  by hand.

[consumers.md](consumers.md#interpreted-constraints) describes the kinds and
codecs and how far to trust them.

## Acceptances

`Accept` marks a linter note as deliberate on a clause's word, such as an
interface printing its own body for an AVP it re-uses. The linter then
reports it as accepted.

```python
Accept(
    id="serving-node-t4-body",
    rule="reused-body-differs",
    target=definition("Serving-Node"),
    expect="Serving-Node's body, against TS29.173's definition: adds"
    " IP-SM-GW-Name, ...",
    reason="clause 6.4.12 says the AVP 'is originally defined in 3GPP TS"
    " 29.173 [8]' and lists the member combinations 'allowed' for"
    " T4-triggering, ...",
    versions="18.2.0",
)
```

- `rule` is the linter rule, `target` the node the finding is about, and
  `expect` the finding's exact message.
- `reason` cites the clause that makes it deliberate; without one, the note
  stays open. A misprinted clause citation (`section-mismatch`) is accepted
  citing the real clause.
- An acceptance changes no data; `seanchai corpus correct` refuses a module
  with only acceptances. The linter checks them against a corpus
  ([linter.md](linter.md#acceptances)).

## The record of known holes

The corpus's `holes.toml` records names the corpus cannot complete
([consumers.md](consumers.md#known-holes)). It changes no file. Each entry's
`reason` cites the version, clause and what was searched, naming the
correction involved as `module#id` where one inserted the block or row.
`missing` is checked like `expect`: an entry that no longer matches fails the
default build. `releases = [18]` holds an entry to those releases the corpus
holds whole, for a hole one release reads and another does not; without it
an entry holds in all of them, and must name a hole in each.

## The corrections record

No wheel ships `edits/`, so `seanchai corpus regenerate` also writes the
corpus's `corrections.json` next to `holes.toml`. Per document file stem it
holds:

- the document's reference and version;
- each declaration's citation, kind and reason (an interpretation's
  clause and quotes);
- what each acceptance accepts: rule, message and the tree paths its target
  reaches;
- the name corrections, in declaration order, that `seanchai export` uses to
  link a raw file's spellings.

A document with no declarations for its release has no entry. The file is
sorted JSON, one field per line. `tests/test_correction_record.py` fails when
it does not match the modules.

## Output

The raw file `29272-j60.raw.dad` and `edits/corrections/TS29.272.py` produce
the corrected `29272-j60.dad`; all three are committed. Every corrected line
carries a `;;` note citing the declaration as `module#id`:

```dad
Area-Scope ::= < AVP header: 1624 10415 > ;; corrected: (TS29.272.py#area-scope-code)
```

- A correction to a definition is cited on its header rule; one to a row's
  flag rules, on the row.
- A correction to a field of the file header, a table or an application
  scope is cited on the directive line that prints the field (`; Bases:`,
  `; Table:`, `; Columns:`, `; Application-ID:`, `; Note:`, an information
  element table's `; Command:`, `; From:` and `; AVP:`), or on the
  block's first line when it removes that line.
- A deletion's note replaces the deleted line:
  `;; deleted: AVP table row 'Load' (TS29.229.py#load-row-not-local)`.
- An interpretation's block is marked `;; interpreted:` on its `; Type:`
  line.
- An inserted row is marked `;; inserted:`, with its source where the
  `Insert` gives one:
  `;; inserted: from clause 6.3.43 (TS29.229.py#wildcarded-impu-row-missing)`.
  An inserted block is marked on its `; Type:` line.
- Every value or cell a `Supply` fills is marked `;; supplied:`.

Notes are `;;` comments keyed by `ast.TreePath` and placed by the rules in
[dad-format.md](dad-format.md#comments), so the annotated file parses to the
corrected tree. `corrections.apply_with_comments(spec, comments, edits)`
carries a raw file's own comments along (TS 32.299's struck members) and
returns them merged with the notes.

## CLI

- `seanchai corpus regenerate` and `seanchai lint` read `edits/corrections/`.
- `seanchai corpus extract … --corrections DIR` corrects one extraction; a
  document without a module is fine.
- `seanchai corpus correct RAW.dad --corrections DIR -o OUT.dad` corrects one
  raw file and requires a module with at least one correction.

For one file the directory must be given, since loading it runs Python. The
module name comes from `; Specification:` through `ast.spec_ref`.
