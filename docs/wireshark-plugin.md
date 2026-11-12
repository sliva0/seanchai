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
tshark -r capture.pcap -X lua_script:seanchai_diameter.lua -q -z expert,warn
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
  `* [ AVP ]`. An answer with the E bit set is held to its document's
  `<answer-message>` instead: TS 29.229's for Cx, RFC 6733 section 7.2's for
  most.
- Grouped AVPs: the same, against the members of the reading the command's
  document means, at any depth. `Failed-AVP` is checked only for its
  `1* { AVP }`, since section 7.5 lets it hold the failed AVP as received.
- Flags, per that reading's flag rules: a bit clear under Must or set under
  Must not is an error, and a bit set under Should not is a warning. An M bit
  left to the application is not checked. A P bit no rule allows is a warning.
- Data formats: octet counts of the integer, float and Time types; an
  Address's family and length for IPv4 and IPv6; UTF8String as valid UTF-8;
  DiameterIdentity as an ASCII host name; DiameterURI and IPFilterRule by
  section 4.3.1's syntax.
- Values: an Enumerated value the reading defines or leaves to vendors, and not
  one it reserves or voids; a Result-Code some document defines; bits some
  document names; the E bit set on a protocol error (3xxx) and on no other
  answer.
- Unknown AVPs: an AVP no document defines is a warning with the M bit set,
  since a receiver would answer `DIAMETER_AVP_UNSUPPORTED`, and a note without.

It cannot check what the documents say only in prose ("shall be present if
..."), what an OctetString holds, what depends on negotiated features, or
anything across messages.

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
3. most of its AVPs listed by the rule rather than left to `* [ AVP ]`;
4. the document TS 29.230's registry allocates the id to.

The other candidates follow with their counts. RFC 4005 and RFC 4006 are never
candidates, since RFC 7155 and RFC 8506 obsolete them.

Three preferences, under Protocols, Seanchaí in Wireshark, or with `-o` in
tshark (`-o seanchai.pin:TS32.299`):

| Preference | Effect |
|---|---|
| Pinned documents (`seanchai.pin`) | comma-separated references; where one defines the command, only it is a candidate |
| Note AVPs only `* [ AVP ]` admits (`seanchai.wildcard_notes`) | a note for each AVP the rule does not list; off by default |
| Explorer address (`seanchai.explorer_url`) | the explorer site the references link to (see [References](#references)); empty for no such links |

## References

Each finding says where the rule it reports is written, beneath its line: the
document, clause, table and page, as `TS 29.061 clause 16a.5, table 9a, page
129`, with a link to the publisher's copy there and one to the explorer site
at that clause. The command line has the same for the command's definition.
The explorer link starts at the `seanchai.explorer_url` preference, read as
each packet is dissected, so a mirror of the site needs no new plugin; the
publisher's link does not depend on it.

| Finding | Cites |
|---|---|
| a flag rule (`flag-must`, `flag-must-not`, `flag-should-not`) | the AVP-table row the reading's flag rules come from: its table's clause; the line ends in the document and table |
| an AVP missing, too often, out of place or not allowed; a note on `* [ AVP ]` or a name the corpus cannot complete | the command's ABNF, or the answer-message's; inside a Grouped AVP, its rule |
| an Enumerated value undefined, reserved or void | the Enumerated AVP's clause |
| a Result-Code or Experimental-Result-Code no document defines | that AVP's clause, RFC 6733 section 7.1 or 7.7 |
| bits no document names | the AVP's first bit table |
| the header's P bit | the command's ABNF, whose header prints PXY or not |
| the header, the AVP framing, the P bit of an AVP, an unknown AVP with the M bit | RFC 6733 section 3, or 4.1 |
| data formats | RFC 6733 section 4.2 (the integer and float types) or 4.3.1 |
| the E bit | RFC 6733 section 7.1.3 for a protocol error without it, 7.2 for another answer with it |

An unknown command or AVP cites nothing: no document defines it.

The publisher's link opens a PDF at the page (`#page=N`) and an RFC at its
section in rfc-editor.org's HTML rendering (`#section-7.2`). A 3GPP2 document's
pages are its printed page numbers, which no fragment reaches, so its link is
the PDF alone and the reference says `printed page`; oneM2M's document is a
member download, linked as it is. The explorer link is
`#<file>/<clause>?name=<name>`, the `.dad` file's stem as the explorer names
it; a section of RFC 6733 the corpus places nothing in gets none.

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

The file holds exactly one line matching
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
| `seanchai.finding`   | one finding, on the octets it is about                |
| `seanchai.rule`      | the finding's kind, as `avp-missing` or `flag-must`   |
| `seanchai.candidate` | another definition, with its counts                   |
| `seanchai.corpus`    | the seanchai and corpus versions the rules came from  |
| `seanchai.reference` | where a finding's rule, or the command, is written    |
| `seanchai.cited`     | that document, as `TS29.061`                          |
| `seanchai.url`       | the publisher's copy at that place                    |
| `seanchai.explorer`  | the explorer site at that clause                      |

Errors are expert info in the Malformed group; warnings and notes are in the
Protocol group.

## Testing

`tests/test_wireshark_validator.py` runs `core.lua` under each of `lua5.1` to
`lua5.4` found on PATH, over messages it encodes, and the generated plugin
under `tshark` over a capture of them, with the preference set and the marked
line rewritten. It skips what is not installed.
