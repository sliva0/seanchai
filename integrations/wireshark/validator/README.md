# Wireshark validator

A Wireshark plugin that checks every Diameter message in a capture against the
documents in the corpus, and reports where a message breaks them: in its own
subtree under each PDU, as expert info, and as fields to filter on. It runs in
Wireshark 4.2 (Lua 5.2, Ubuntu 24.04's) and later, and in tshark.

```sh
uv run integrations/wireshark/validator/generate.py \
    -o ~/.local/lib/wireshark/plugins/seanchai_diameter.lua
```

`generate.py` writes one file holding the rules, read from `seanchai
dictionary`, and the two Lua files beside it: `core.lua`, the checks, and
`plugin.lua`, the Wireshark side. `--application ID` and `--document REF`,
each repeatable, narrow the rules as they narrow `seanchai dictionary`;
`--corpus DIR` reads another corpus; `--rules-only` writes the rules alone, as a
chunk returning them, for running `core.lua` outside Wireshark. Regenerate after
upgrading the corpus: the plugin's `seanchai.corpus` field says which it holds.

Without installing it, a capture can be checked from the command line:

```sh
tshark -r capture.pcap -X lua_script:seanchai_diameter.lua -Y "seanchai.errors > 0"
tshark -r capture.pcap -X lua_script:seanchai_diameter.lua -q -z expert,warn
```

## What it checks

The plugin reads each `diameter` PDU's octets itself, after Wireshark has
reassembled it, so neither Wireshark's dictionary nor its decoding stands
between the message and the corpus.

- **The header**: version 1, a length matching the message and a multiple of
  4, reserved flag bits clear, the E bit on answers only and the T bit on
  requests only (RFC 6733 section 3), and the P bit as the command's header
  prints PXY.
- **The AVPs' framing**: lengths covering their header and staying inside what
  holds them, padding to 4 octets and zero, reserved flag bits clear (section
  4.1).
- **The command's ABNF**: every required AVP present, none occurring more often
  than it allows, the fixed ones where they stand, and no AVP the rule does not
  list unless it ends in `* [ AVP ]`. With the E bit set, the answer is held to
  the `<answer-message>` its document takes instead of its command's body: TS
  29.229's own for Cx, RFC 6733 section 7.2's for most.
- **Grouped AVPs**, the same, against the members of the reading the command's
  document means, at any depth, a `* [ AVP ]` line's own bounds included.
  `Failed-AVP` is the exception: RFC 6733 section 7.5 has it hold the AVP that
  failed as received, or a zero-filled stand-in, so only its `1* { AVP }` is
  held to anything.
- **Flags**, per AVP, as that reading's flag rules say: a bit under Must not
  set, under Must set, under Should not clear. M left to the application is not
  checked. A P bit no rule allows draws a warning, since section 4.1 says it
  should be 0.
- **Data formats**: the octet counts of the integer, float and Time types; an
  Address's family and length for IPv4 and IPv6; UTF8String as valid UTF-8;
  DiameterIdentity as an ASCII host name; DiameterURI and IPFilterRule by
  section 4.3.1's syntax.
- **Values**: an Enumerated value the reading defines, or in a range it leaves
  to vendors, and not one it reserves or withdrew; a Result-Code some document
  defines; bits of a bit mask some document names; a protocol error (3xxx) with
  the E bit set and no other.
- **Unknown AVPs**: an AVP no document in the corpus defines, a warning with the
  M bit set, since a receiver not knowing it answers `DIAMETER_AVP_UNSUPPORTED`,
  and a note without.

What it cannot check is what the documents say only in prose ("shall be
present if ..."), what an OctetString holds inside, what depends on the
features a peer negotiated, and anything across messages.

## Which definition a message is held to

A message is looked up by application id, command code and R bit. Where no
document defines the command under that id, the definitions that print no id
answer for it: RFC 6733's STR, ASR and RAR, which carry the application's id on
the wire. A relayed message (0xffffffff) is looked up under the application its
`Auth-Application-Id`, `Acct-Application-Id` or
`Vendor-Specific-Application-Id` names.

Several documents can define one command under one id: TS 29.229 and 3GPP2
X.S0013-006 both print Cx, TS 32.299, RFC 8506 and OMA's charging document all
print CCR in application 4. Every one is a candidate, and the message is
reported against the one it breaks least: fewest errors, then fewest warnings,
then the one listing the most of its AVPs rather than leaving them to `* [ AVP
]`, then the one TS 29.230's registry allocates the id to. The other candidates
follow, each with its counts. RFC 4005 and RFC 4006 are no candidates, since
RFC 7155 and RFC 8506, which the corpus also holds, obsolete them.

Two preferences, under Protocols, Seanchaí, in Wireshark (`-o
seanchai.pin:TS32.299` in tshark):

- **Pinned documents**, comma-separated references: where one of them defines
  the command, only it is a candidate.
- **Note AVPs only `* [ AVP ]` admits**: a note for each AVP the command's
  rule does not list, off by default.

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

Errors are expert info of the Malformed group, warnings and notes of the
Protocol group.

## Testing

`tests/test_wireshark_validator.py` runs `core.lua` under every `lua5.1` to
`lua5.4` on PATH over messages it encodes, and the generated plugin under
`tshark` over a capture of them, skipping what is not installed.
