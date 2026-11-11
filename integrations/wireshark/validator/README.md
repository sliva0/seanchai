# Wireshark validator

A Wireshark plugin that checks every Diameter message in a capture against the
documents in the corpus. It reports each breach in a subtree under the PDU, as
expert info, and as fields to filter on. It runs in Wireshark 4.2 (Lua 5.2)
and later, and in tshark.

## Generating and running

```sh
uv run integrations/wireshark/validator/generate.py \
    -o ~/.local/lib/wireshark/plugins/seanchai_diameter.lua
```

`generate.py` writes one Lua file: the rules, read from `seanchai dictionary`,
together with `core.lua` (the checks) and `plugin.lua` (the Wireshark side).

| Option | Effect |
|---|---|
| `-o PATH` | the file to write |
| `--application ID` | only this application id's commands; repeatable |
| `--document REF` | only this document's commands; repeatable |
| `--corpus DIR` | read another corpus than the installed one |
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

Two preferences, under Protocols, Seanchaí in Wireshark, or with `-o` in
tshark (`-o seanchai.pin:TS32.299`):

| Preference | Effect |
|---|---|
| Pinned documents (`seanchai.pin`) | comma-separated references; where one defines the command, only it is a candidate |
| Note AVPs only `* [ AVP ]` admits (`seanchai.wildcard_notes`) | a note for each AVP the rule does not list; off by default |

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

Errors are expert info in the Malformed group; warnings and notes are in the
Protocol group.

## Testing

`tests/test_wireshark_validator.py` runs `core.lua` under each of `lua5.1` to
`lua5.4` found on PATH, over messages it encodes, and the generated plugin
under `tshark` over a capture of them. It skips what is not installed.
