# Wireshark plugin

A Wireshark plugin that checks every Diameter message in a capture against the
documents in the corpus. It reports each breach in a subtree under the PDU, as
expert info, and as fields to filter on. It runs in Wireshark 4.2 (Lua 5.2)
and later, and in tshark.

## Generating and running

```sh
seanchai wireshark-plugin -o ~/.local/lib/wireshark/plugins/seanchai_diameter.lua
```

With nothing installed, uv fetches the library and the corpus for the one run:

```sh
uvx --from 'seanchai[corpus]' seanchai wireshark-plugin -o ~/.local/lib/wireshark/plugins/seanchai_diameter.lua
```

`seanchai wireshark-plugin` writes one Lua file: the rules, read from the
corpus as `seanchai dictionary` reads it, together with `core.lua` (the
checks) and `plugin.lua` (the Wireshark side), which come with the library in
`seanchai.wireshark`. Its `generate` does the same from Python.

| Option | Effect |
|---|---|
| `-o FILE` | the file to write |
| `--application ID` | only this application id's commands; repeatable |
| `--document REF` | only this document's commands; repeatable |
| `--corpus DIR` | read another corpus than the installed one; repeatable |
| `--explorer URL` | the default of the `seanchai.explorer_url` preference, `https://sliva0.github.io/seanchai-explorer/` by default; `''` for none |
| `--rules-only` | write the rules alone, as a Lua chunk returning them, for running `core.lua` outside Wireshark |

Regenerate after upgrading the corpus. The plugin's `seanchai.corpus` field
says which corpus it holds.

To check a capture without installing the plugin:

```sh
tshark -r capture.pcap -X lua_script:seanchai_diameter.lua -Y "seanchai.errors > 0"
tshark -r capture.pcap -X lua_script:seanchai_diameter.lua -q -z expert,note
```

## What it checks

The plugin reads each reassembled `diameter` PDU's octets itself, so
Wireshark's own dictionary and decoding play no part. Section numbers are RFC
6733's.

- Header: version 1; a length that matches the message and is a multiple of
  4; reserved flags clear; the E bit only on answers and the T bit only on
  requests (section 3); the P bit as the command's header prints PXY.
- AVP framing: lengths that cover the header and stay inside the container;
  padding to 4 octets, all zero; reserved flags clear (section 4.1).
- The command's ABNF: required AVPs present, none more often than allowed,
  fixed AVPs in place, and no unlisted AVP unless the rule ends in
  `* [ AVP ]`. An AVP a rule lists on two lines (TS 29.234's RAR, `{
  Destination-Host }` and `[ Destination-Host ]`) may occur as often as the
  lines together allow. An answer with the E bit set is held to its document's
  `<answer-message>` instead: TS 29.229's for Cx, RFC 6733 section 7.2's for
  most.
- Grouped AVPs: the same, against the members of the reading the command's
  document means, at any depth. `Failed-AVP` is checked only for its
  `1* { AVP }`, since section 7.5 lets it hold the failed AVP as received.
  An AVP only `* [ AVP ]` admits is held to the reading the body's
  interpreted rules on it were read for, where it has some (TS 32.299's CCA,
  its Supported-Features, whose Feature-List-ID TS 32.299 sets M), else to
  the defining document's.
  One a table types Grouped and no document prints a rule for (TS 29.128's
  `APN-Rate-Control-Status`) is checked for its framing only.
- Flags, per that reading's flag rules: a bit clear under Must or set under
  Must not is an error, and a bit set under Should not is a warning. An M bit
  left to the application is not checked. A P bit no rule allows is a warning.
- Data formats: octet counts of the integer, float and Time types; an
  Address's family and length for IPv4 and IPv6; UTF8String as valid UTF-8;
  DiameterIdentity as an ASCII host name; DiameterURI and IPFilterRule by
  section 4.3.1's syntax.
- Values: an Enumerated value the reading defines or leaves to vendors, and not
  one it reserves or voids, where the corpus holds its values (RFC 5777's
  `Treatment-Action` is typed Enumerated by a table, its values unread); a
  Result-Code some document defines; bits some document names; an Unsigned32
  value some document's `values` table names, a note, since no clause says
  its table holds every value (TS 29.272 leaves Group-Service-Id above 1000
  to the home operator); the E bit set on a protocol error (3xxx) and on no
  other answer. A code missing from a command's table of result codes
  (TS 29.228's, 29.273's, 29.328's) is not checked: no table says it lists
  every code, and none lists the protocol errors an agent returns.
- Unknown AVPs: an AVP no document defines is a warning with the M bit set,
  since a receiver would answer `DIAMETER_AVP_UNSUPPORTED`, and a note without.
- Interpreted constraints ([constraints.md](constraints.md)), what a person
  read in the clauses' prose, each a note whose line ends in `interpreted`,
  since the reading is ours however firmly the quote words it:
  a length in octets, digits or characters, a range, an excluded value, an
  encoding, another document's element as far as the element registry reads
  it ([constraints.md](constraints.md#elements)), a rule on the AVP's own
  bits, the members a grouped AVP holds (`constraint-length`, `-range`,
  `-exclude`, `-encoding`, `-element`, `-bits`, `-members`), for the AVP
  wherever its reading's document reads it and as
  a member of the command or grouped AVP holding it, a grouped AVP's rules
  read for one application (`; Application-ID:`) only in a message whose
  header, or a relayed message's application-id AVPs, name that
  application; the predicates tying a
  member's presence to its siblings, on each instance of it, a path from it
  reading that one, or with no scope an AVP's to its own
  members (`constraint-present-if`, `-absent-if`, `-requires`, `-excludes`),
  a value a sibling's condition restricts
  (`constraint-values`), an answer's AVP echoing the request's
  (`constraint-equals`), an AVP never sent in its scope
  (`constraint-absent`), and a member two grouped AVPs beside each other
  hold with one value (`constraint-unique`). An element the registry has no
  entry for or checks nothing of is not checked, `text-only` not at all, and
  a rule naming a value or bit no table numbers is left out.
- An answer's rules on the request it answers
  ([constraints.md](constraints.md#the-block)), against that request where
  the capture holds it ([Requests](#requests)).

It cannot check what the documents say only in prose and no one has read as
a constraint, what depends on negotiated features, or anything across more
than a request and its answer.

## Requests

A rule of an answer may read the request it answers (`request/` in
[grammar.md](grammar.md#interpreted-constraints)). The plugin keeps, of
each request it meets, the data of the AVPs some loaded rule reads of that
command's requests, and nothing of a request no rule reads; the generated
rules list them per application and command code (`requests` in the rules),
a path through grouped AVPs as its identities joined by `/`.

- An answer is paired with the request Wireshark's own Diameter dissector
  pairs it with (`diameter.answer_to`, by conversation, Hop-by-Hop and
  End-to-End identifiers), and among that frame's PDUs the one with the
  answer's identifiers. Where Wireshark pairs none, it takes the last
  request before it between the same two endpoints, either way round, with
  the same identifiers.
- Requests are kept from the first pass, so a frame dissected again in any
  order, or an answer the second pass of `tshark -2` sees before its
  request, finds its request. A request retransmitted with the T bit, or
  seen twice on two links, is kept once per frame; the pairing picks one.
- At most 100,000 requests are kept, the oldest dropped first, and the
  store is cleared with each capture.
- An answer whose request the capture does not hold, or whose rules read a
  request that was dropped, leaves those rules unchecked: no finding, and
  `seanchai.request_missing` on the message's subtree counts them, once per
  answer, for a display filter. An answer read against its request has
  `seanchai.request_frame` on its subtree and under each finding of a rule
  on the request, linking that frame.

## Findings

Each finding is one line in the `seanchai` subtree, on the octets it is
about, so selecting it marks the AVP in Wireshark's own Diameter tree and in
the bytes. A Lua post-dissector cannot add to the items another dissector
drew, so the line cannot sit under the AVP's own item; it names the AVP
instead:

```text
Seanchaí Diameter validation: ULR, 0 errors, 0 warnings, 1 note
    Note: … > MIP-Home-Agent-Host > Destination-Realm: not epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org [TS 29.272 7.3.43, interpreted]
        [Path: Subscription-Data > APN-Configuration-Profile > APN-Configuration > MIP6-Agent-Info > MIP-Home-Agent-Host > Destination-Realm]
```

A line is `Severity: place: problem [source]`:

- The place is the AVP, after its parent and `…` where it sits deeper; an AVP
  of the message itself is named alone. A finding about what a body lacks
  (a required AVP, a predicate's member, unlisted AVPs `* [ AVP ]` needs)
  names the body: the grouped AVP, or the command's abbreviation, or
  `answer-message`, on that AVP's octets or the command code's. A finding of
  the message header names `Header`. `seanchai.path`, beneath, is the whole
  path.
- The problem says what is wrong once, as `missing Session-Id`, `M bit clear,
  must be set`, `occurs 2 times, at most 1`, `16 digits, not 14 to 15`.
- The source is the document and clause, `[TS 29.272 7.3.43]`, a flag rule's
  table, `[TS 29.061 table 9a]`, and `interpreted` for an interpreted
  constraint. An unknown command or AVP has none. The reference beneath has
  the table and page, and the links.

A members rule naming more than three members lists two and how many more on
the line, and all of them in the expert info. An element's finding cites TS
29.272's clause, which names the element, and says beneath it, as
`seanchai.element`, the element, the documents its layout was read from and
what is checked:

```text
Note: … > Trace-Data > Trace-NE-Type-List: 4 octets, not 3 [TS 29.272 7.3.68, interpreted]
    [Path: Subscription-Data > Trace-Data > Trace-NE-Type-List]
    [Element: TS 32.422 5.4 List of NE Types (TS 32.422 V19.7.0): 3 octets; octet 3 bits 8-7 (spare) 00]
```

| Severity | Expert info, to filter on | Group | For |
|---|---|---|---|
| Error | `seanchai.violation` | Malformed | a rule a document states (the ABNF, a Must or Must not flag rule, a data format, framing, a reserved or void value) broken |
| Warning | `seanchai.warning` | Protocol | a bit set under Should not, reserved flags or nonzero padding, a value or Result-Code no document defines, an unknown AVP with the M bit, the E bit against the Result-Code |
| Note | `seanchai.note` | Protocol | an unknown command or AVP without the M bit, a bit, an Unsigned32 value of a `values` table or an Experimental-Result-Code no document names, a member the corpus cannot complete, an AVP only `* [ AVP ]` admits |
| Note | `seanchai.interpreted` | Protocol | an interpreted constraint broken |

Each message's counts are `seanchai.errors`, `seanchai.warnings` and
`seanchai.notes`, the notes counting interpreted ones: `seanchai.errors > 0`,
`seanchai.warnings > 0`, `seanchai.notes > 0` filter for messages, and
`seanchai.interpreted` for those breaking an interpreted rule.

## Which definition a message is held to

A message is looked up by application id, command code and R bit. If no
document defines the command under that id, definitions that print no id
answer for it, such as RFC 6733's STR, ASR and RAR. A relayed message
(0xffffffff) is looked up under the application its `Auth-Application-Id`,
`Acct-Application-Id` or `Vendor-Specific-Application-Id` names.

Where several documents define one command under one id (TS 32.299, RFC 8506
and OMA's charging document all print CCR in application 4), each is a
candidate. The message is reported against the one it breaks least, chosen by:

1. fewest errors;
2. fewest warnings;
3. fewest breaches of interpreted constraints;
4. most of its AVPs listed by the rule rather than left to `* [ AVP ]`;
5. the document TS 29.230's registry allocates the id to.

The other candidates follow with their counts. A document another candidate's
header obsoletes is none (`; Obsoletes:`): RFC 4005 and RFC 4006, which RFC
7155 and RFC 8506 obsolete.

Three preferences, under Protocols, Seanchaí in Wireshark, or with `-o` in
tshark (`-o seanchai.pin:TS32.299`):

| Preference | Effect |
|---|---|
| Pinned documents (`seanchai.pin`) | comma-separated references; where one defines the command, only it is a candidate |
| Note AVPs only `* [ AVP ]` admits (`seanchai.wildcard_notes`) | a note for each AVP the rule does not list; off by default |
| Explorer address (`seanchai.explorer_url`) | the explorer site the references link to (see [References](#references)); empty for no such links |

## References

Each finding's line ends in where the rule it reports is written, in short
([Findings](#findings)), and says it in full beneath: the
document, clause, table and page, as `TS 29.061 clause 16a.5, table 9a, page
129`, with a link to the publisher's copy there and one to the explorer site
at that clause. The command line has the same for the command's definition.
The explorer link starts at the `seanchai.explorer_url` preference, read as
each packet is dissected, so a mirror of the site needs no new plugin; the
publisher's link does not depend on it.

| Finding | Cites |
|---|---|
| a flag rule (`flag-must`, `flag-must-not`, `flag-should-not`) | a row whose cell states that rule for that bit, from the reading's document (its AVP table, then its re-used table's M-bit column), the document completing the flags, or the defining one: its table's clause; the line ends in the document and table. RFC 6733 section 4.1.1 for V under Must not on an IETF AVP no row places, and the reading's clause for any other rule no row states; with none, the line ends in the reading's document |
| an AVP missing, too often, out of place or not allowed; a note on `* [ AVP ]` or a name the corpus cannot complete | the command's ABNF, or the answer-message's; inside a Grouped AVP, its rule |
| an Enumerated value undefined, reserved or void | the Enumerated AVP's clause |
| a Result-Code or Experimental-Result-Code no document defines | that AVP's clause, RFC 6733 section 7.1 or 7.7 |
| bits no document names | the AVP's first bit table |
| the header's P bit | the command's ABNF, whose header prints PXY or not |
| the header, the AVP framing, the P bit of an AVP, an unknown AVP with the M bit | RFC 6733 section 3, or 4.1 |
| data formats | RFC 6733 section 4.2 (the integer and float types) or 4.3.1 |
| the E bit | RFC 6733 section 7.1.3 for a protocol error without it, 7.2 for another answer with it |
| an interpreted constraint | the clause its quotes were read from, and the table where they are an information element's description |

An unknown command or AVP cites nothing: no document defines it.

The publisher's link opens a PDF at the page (`#page=N`) and an RFC at its
section in rfc-editor.org's HTML rendering (`#section-7.2`). A 3GPP2 document's
pages are its printed page numbers, which no fragment reaches, so its link is
the PDF alone and the reference says `printed page`; oneM2M's document is a
member download, linked as it is. The explorer link is
`#<file>/<clause>?name=<name>`, the `.dad` file's stem as the explorer names
it.

Every reference has an explorer link while the preference is set. Where the
cited clause is a section of RFC 6733 the corpus places nothing in, the link
goes where the explorer has something to show, and the Reference and
Specification lines still cite the rule's section:

| Finding | Explorer link |
|---|---|
| a data format, the AVP's framing or P bit | the AVP's defining clause, with its name, where its type is stated |
| the header, the E bit | the command's definition, as the command line's |
| anything else, or a case above with nowhere to go | the cited document (`#<file>`) |

The tree then says where the link goes, the field's value staying the URL:

```text
[Reference: RFC 6733 section 4.3.1, page 44]
[Explorer: Destination-Host, RFC 6733 section 6.5: https://sliva0.github.io/seanchai-explorer/#rfc6733/6.5?name=Destination-Host]
```

An unknown AVP with the M bit, which no document defines, links to
RFC 6733 itself; an unknown command or AVP has no reference and no link.

Wireshark's Lua API cannot mark a field as a URL, as a C dissector's
`proto_item_set_url` does (up to 4.7 at least), so the links are plain string
fields: copy one with Copy, Value.

## The marked lines

Two lines near the top of the plugin are a stable contract, for a tool that
reads or edits the file as text without parsing Lua, such as a page offering
it for download:

```lua
-- seanchai:versions seanchai 0.2.0, corpus 2026.11.11
local EXPLORER = "https://sliva0.github.io/seanchai-explorer/" -- seanchai:explorer
```

The file is UTF-8 with LF line endings on every platform, Windows included:
no line ends in a CR. It holds exactly one line matching
`^local EXPLORER = "[^"\\]*" -- seanchai:explorer$`, and the plugin takes the
`seanchai.explorer_url` preference's default from it. A tool may rewrite this
one line, keeping its form, to set another default address or `""` for none;
the address may not hold a double quote, a backslash or a line break, which
`--explorer` refuses. Everything else in the file is generated: do not edit
it.

The versions line names the library and corpus versions the rules came from,
as the `seanchai.corpus` field does; a corpus read with `--corpus` is
`unversioned`. `seanchai.wireshark.EXPLORER_LINE` and `VERSIONS_LINE` match
the two lines.

## Fields

| Field                | Holds                                                 |
|----------------------|-------------------------------------------------------|
| `seanchai.command`   | the definition the message was held to                |
| `seanchai.document`  | its document, as `TS29.272`                           |
| `seanchai.section`   | its clause                                            |
| `seanchai.form`      | the command's body, or the answer-message it took     |
| `seanchai.errors`    | how many findings are errors; `warnings`, `notes`     |
| `seanchai.finding`   | one finding's line, on the octets it is about         |
| `seanchai.rule`      | the finding's kind, as `avp-missing` or `flag-must`   |
| `seanchai.path`      | the AVP or body it is about, from the message's top   |
| `seanchai.element`   | an element's finding: the element, where it was read  |
| `seanchai.candidate` | another definition, with its counts                   |
| `seanchai.corpus`    | the seanchai and corpus versions the rules came from  |
| `seanchai.reference` | where a finding's rule, or the command, is written    |
| `seanchai.cited`     | that document, as `TS29.061`                          |
| `seanchai.url`       | the publisher's copy at that place                    |
| `seanchai.explorer`  | the explorer site at that clause                      |
| `seanchai.request_frame` | the request an answer was read against            |
| `seanchai.request_missing` | how many rules on the request went unchecked, the request not in the capture |

The findings are expert info too ([Findings](#findings)).

## Testing

`tests/test_wireshark_validator.py` runs `core.lua` under each of `lua5.1` to
`lua5.4` found on PATH, over messages it encodes, and the generated plugin
under `tshark` over a capture of them, with the preference set and the marked
line rewritten. `tests/test_vectors.py` runs it over the
[test messages](consumers.md#test-messages) of every application, each
built as `seanchai vectors --application` builds it: every valid one draws
no error, warning or note of an interpreted rule and every negative one
exactly the finding it expects, from the whole corpus's rules under each
Lua and from the application's own (`--application`) under one, an
interpreted rule's as `seanchai.interpreted` under tshark, and a synthetic
document's request and answer pairs, each answer read against its request
in the core and paired by the plugin in a capture, and left unchecked
without it. Both skip what is not installed.
