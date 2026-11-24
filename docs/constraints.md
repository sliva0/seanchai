# Interpreted constraints

A `.dad` file says what a document prints as structure: an AVP is an
`OctetString`, an `Unsigned32`. The clause defining the AVP says more, in
prose: "encoded as a TBCD-string", "in the range of 0 to 255", "shall only be
present when Non-IP-PDN-Type-Indicator is set to TRUE (1)". No extractor reads
that reliably, so a person reads the clause and declares what it says, pinned
to the sentences read. The corpus calls the result interpreted constraints.

## What "interpreted" means

Everything else in the corpus is what a document prints, or a correction of
it with its reason. An interpreted constraint is a reading of prose: someone
decided that "It should consist of 14 digits ... It may also include a 15th
digit" means `length 14..15 digits` of `digits`. The corpus keeps that apart
from the printed facts, so a consumer can weigh it:

- Only a corrected file holds the block, `; Type: Interpreted Constraints`;
  the raw file is what the extractor read. A note on its `; Type:` line cites
  the declaration (`;; interpreted: (TS29.272.py#imei-digits)`).
- Each rule stands after the sentences it was read from, verbatim. Rebuilding
  the corpus from the documents checks every sentence against its clause and
  every page against the PDF, and fails when the document no longer prints
  it, as a correction does when the document is fixed.
- `; Versions:` is the range of the document's versions the reading was
  checked against.
- The model's `Constraint`, the dictionary's and the export's say
  `interpreted`; the Wireshark plugin reports a breach as a warning that names
  the rule interpreted.
- What no kind below expresses is recorded as `text-only`: the quote, and no
  rule a checker could run. A checker reports it unknown, never a guess.

Trust a rule as far as you trust its quote. Where the quote says "should", or
is a NOTE, the rule is the reader's; read the quote before rejecting traffic
on it.

## The block

[grammar.md](grammar.md#interpreted-constraints) defines it. Each kind, as
TS 29.272's file prints it:

```dad
; Type: Interpreted Constraints ;; interpreted: (TS29.272.py#imei-digits)
; AVP: IMEI
; Section: 7.3.4
; Page: 100
; Versions: 19.6.0
"It should consist of 14 digits, including the 8-digit Type Allocation Code (TAC) and the 6-digit Serial Number (SNR). It may also include a 15th digit."
    encoding digits
    length 14..15 digits


; Type: Interpreted Constraints ;; interpreted: (TS29.272.py#ue-usage-type-range)
; AVP: UE-Usage-Type
; Section: 7.3.202
; Page: 166
; Versions: 19.6.0
"The allowed values of UE-Usage-Type shall be in the range of 0 to 255."
    range 0..255


; Type: Interpreted Constraints ;; interpreted: (TS29.272.py#apn-configuration-non-ip-delivery)
; AVP: Non-IP-Data-Delivery-Mechanism
; Within: APN-Configuration
; Section: 7.3.35
; Page: 128
; Versions: 19.6.0
"The Non-IP-Data-Delivery-Mechanism shall only be present when Non-IP-PDN-Type-Indicator is set to TRUE (1)."
    requires Non-IP-PDN-Type-Indicator = TRUE
```

| Kind | Example | Holds when |
|---|---|---|
| `length` | `length 3 octets`, `length 14..15 digits`, `length 1..* characters` | the payload's octets, the digits its encoding carries, or its UTF-8 characters are within the bounds |
| `range` | `range 0..255`, `range -1..*` | the integer value is within the bounds |
| `exclude` | `exclude 0` | the integer value is none of these |
| `encoding` | `encoding plmn-id`, `encoding element TS24.008 10.5.5.32 "Extended DRX parameter"` | the payload is laid out as the codec says |
| `present-if` | `present-if Result-Code = DIAMETER_SUCCESS` | the AVP is present when a condition holds |
| `absent-if` | `absent-if Emergency-Services bit Emergency-Indication` | the AVP is absent when a condition holds |
| `requires` | `requires DSR-Flags bit "Trace Data Withdrawal"` | a condition holds when the AVP is present |
| `excludes` | `excludes Other-AVP` | no condition holds when the AVP is present |
| `default` | `default FALSE`, `default 0` | (what an absent AVP is read as) |
| `bits` | `bits at-most-one 3 6`, `bits at-least-one 0 1` | of these bits of the AVP's own value, at most one is set, or at least one |
| `text-only` | `text-only` | (a reader decides) |

A predicate's conditions are alternatives (`or`), each on a sibling in the
block's `; Command:` or `; Within:` grouped AVP: present, holding a value
(a number, or a name its values or result codes give it), or with a bit set
(a number, or its bit table's name). Several predicates in one block must all
hold. `absent-if` and `excludes` say the same of a presence condition, read
from the other side; the kinds follow the clause's wording. Without a scope
the rules hold wherever the document reads the AVP, and a predicate there has
no siblings to test.

## Codecs

The set is closed, and holds the layouts TS 29.272's clauses name. A layout
no clause states is not here.

| Codec | Layout | Defined in |
|---|---|---|
| `e164-tbcd` | an international number, ITU-T E.164 (1 to 15 decimal digits), as a TBCD-string: two digits an octet, the first in bits 1-4, "1111" filling bits 5-8 of the last octet after an odd count; no octet for the nature of address and numbering plan | TS 29.002 clause 17.7.8, as TS 29.272 clauses 7.3.39, 7.3.85, 7.3.91, 7.3.102, 7.3.157 and 7.3.159 say |
| `plmn-id` | MCC and MNC in 3 octets: MCC digits 2 and 1, then MNC digit 3 (or "1111" for a 2-digit MNC) and MCC digit 3, then MNC digits 2 and 1 | TS 29.272 table 7.3.9/1, after TS 24.008 clause 10.5.1.13 |
| `plmn-id-prefix` | a `plmn-id` in the first 3 octets, more octets after it | TS 29.272 table 7.3.64/1 (Trace-Reference) |
| `digits` | decimal digits as text, a character each | TS 29.272 clauses 7.3.4, 7.3.5, 7.3.50 |
| `labels` | one or more non-empty labels separated by dots | TS 29.272 clause 7.3.32 |
| `apn` | `labels`, or the wild card `*` | TS 29.272 clause 7.3.36 |
| `plmn-domain` | `mnc<MNC>.mcc<MCC>.3gppnetwork.org`, MNC 2 or 3 digits, MCC 3, in any case | TS 29.272 clause 7.3.105 |
| `epc-plmn-domain` | `epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org` | TS 29.272 clause 7.3.43 |
| `ip-address` | an Address of family 1 (IPv4, 4 octets) or 2 (IPv6, 16) | RFC 6733 clause 4.3.1, as TS 29.272 clauses 7.3.98 and 7.3.109 restrict it |
| `time-zone` | a sign and decimal digits, the offset from UTC in 15 minutes: `+8` | TS 29.272 clause 7.3.163 |
| `element` | another document's information element, carried whole: its document, and the clause and name where the clause gives them | the cited document |

An `element` is checked no further than a `length` beside it says: the corpus
does not implement other documents' elements. A clause pointing at another
document without stating a layout ("Octets are coded according to TS 29.002
[24]") is an `element` of that document.

`seanchai.constraints` checks a payload in Python: `codec_problem(codec,
payload)` says why a payload is no such layout, `digit_count` counts its
digits, and `check(rule, payload, data_type, codec)` tells whether a length,
range, exclude or encoding rule holds, None where the payload alone cannot
tell (a predicate, an `element`, a `default`, `text-only`). A `bits` rule
holds of an unsigned integer's payload.

## Reading them

- The model: `Avp.constraints` holds what the reading document read of the
  AVP wherever it appears, or else its origin's, as value tables are;
  `Grouped.member_constraints` what it read of the grouped AVP's members;
  `Message.constraints` what it read of the command's members.
  `Model.constraints(reference)` lists a document's. Each is a
  `model.Constraint` with its `readings` (`ast.Reading`: quotes and rules),
  clause, page, table and `versions`
  ([consumers.md](consumers.md#interpreted-constraints)).
- The dictionary: `constraints[]` holds those on the AVPs the selection
  reaches, each naming the readings carrying it in `avp_ids`; a command's own
  `constraints` its members'
  ([consumers.md](consumers.md#the-dictionary)).
- The export: an Interpreted Constraints block has `interpreted`, the
  `avp_target` its `; AVP:` line links to, and `readings`, each quote and
  rule at its line ([website.md](website.md#blocks)).
- The linter's `constraint-*` rules report a block naming what the file does
  not hold, a rule the AVP's type cannot meet, a value or bit no table names,
  and rules that cannot all hold
  ([linter.md](linter.md#interpreted-constraints)).
- The Wireshark plugin checks lengths, ranges, exclusions, the codecs but
  `element`, `bits` rules, and the predicates whose names resolve; a
  `default` breaks nothing on the wire
  ([wireshark-plugin.md](wireshark-plugin.md#what-it-checks)).

## Adding them for another document

1. Read every AVP clause of the document, and the descriptions of its
   information-element tables' C rows. Keep the source text at hand:
   `seanchai.extractor.tgpp_docx.clause_texts(docx, Path("edits/sources"))`
   gives each clause's paragraphs and cells as the quote check reads them,
   and `clause_pages(pdf)` each clause's page.
2. For each rule a clause states, declare an `Interpret` in the document's
   corrections module
   ([corrections.md](corrections.md#interpreted-constraints)), in clause
   order: the AVP, its scope where the clause speaks of the AVP in a
   command or grouped AVP, the clause, page and table, and readings of the
   shortest quotes that state the rule.
3. Prefer `text_only` to a rule the quote does not settle. A rule depending on
   an earlier message, a feature, the node, the interface or the subscriber
   is `text_only`; so is a NOTE outside a table, which states no requirement.
   A clause pointing at another document for a layout is an `element`.
4. Run `uv run seanchai corpus regenerate --spec <SpecRef>`. A quote the
   clause does not print, or a page the PDF does not give it, fails the
   document. Then `uv run seanchai lint` on the corrected file.
5. A layout no codec describes needs a codec, defined with its clause in
   `ast.Codec`, `seanchai.constraints`, the plugin's `core.lua` and this
   page, with byte vectors in `tests/test_constraints.py`.

A 3GPP docx and an RFC's text are checked against their source, an RFC's
quote within one paragraph, its lines joined. A transcription has no source
text to check against, so an `Interpret` for one is refused.

## TS 29.272

TS 29.272 V19.6.0 is read completely: every AVP clause of clause 7.3 and every
C row of its information-element tables.

| | |
|---|---|
| AVP clauses (clause 7.3, not its General and Void clauses) | 247 |
| with something to declare | 99, in 119 blocks |
| with nothing to declare | 148 |
| information-element C rows | 45, of which 35 state a condition, 10 of them typed |
| blocks | 154: 87 on an AVP wherever read, 32 within a grouped AVP, 35 within a command |
| readings | 174 |

| Rules | |
|---|---|
| `encoding`, a codec | 20: `e164-tbcd` 6, `plmn-id` 3, `digits` 3, `ip-address` 2, `plmn-id-prefix`, `labels`, `apn`, `plmn-domain`, `epc-plmn-domain`, `time-zone` |
| `encoding element` | 43 |
| `length` | 8: 6 in octets, 2 in digits |
| `range` | 7 |
| `exclude` | 3 |
| `requires`, `present-if`, `absent-if` | 17, 2, 2 |
| `default` | 9 |
| `bits` | 2: `at-most-one` (DSR-Flags), `at-least-one` (Preferred-Data-Mode) |
| `text-only` | 67 |

The text-only rules are mostly conditions on the node, the interface, an
earlier message or a feature (an information element's "shall be present if
the MME supports SMS in MME"), what an absent AVP means where that is no
value or differs between commands (MDT-User-Consent's in ULA and IDR), rules
on bits that depend on another bit or the interface (Access-Restriction-Data's
"Bits 11 and 12 are only used when bit 4 is not set"), and conditions on an
OctetString's value (PDP-Type's, whose octets the clauses do not spell out).
