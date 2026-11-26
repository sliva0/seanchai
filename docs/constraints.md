# Interpreted constraints

A `.dad` file says what a document prints as structure: an AVP is an
`OctetString`, an `Unsigned32`. The clause defining the AVP says more, in
prose: "encoded as a TBCD-string", "in the range of 0 to 255", "shall only be
present when Non-IP-PDN-Type-Indicator is set to TRUE (1)". No extractor reads
that reliably, so a person reads the clause and writes down what it says,
pinned to the sentences read. The corpus calls the result interpreted
constraints.

## What "interpreted" means

Everything else in the corpus is what a document prints, or a correction of
it with its reason. An interpreted constraint is a reading of prose: someone
decided that "It should consist of 14 digits ... It may also include a 15th
digit" means `length 14..15 digits` of `digits`. The corpus keeps that apart
from the printed facts, so a consumer can weigh it:

- The blocks are written by hand, one file per document, in the document's
  interpretations file, `edits/interpretations/TS29.272.dadx`, in the block
  syntax itself ([below](#the-interpretations-file)). Only a corrected file
  holds them, `; Type: Interpreted Constraints`; the raw file is what the
  extractor read. A note on each block's `; Type:` line cites the block it
  was merged from (`;; interpreted: (TS29.272.dadx#imei-digits)`).
- Each rule stands after the sentences it was read from, verbatim. Rebuilding
  the corpus from the documents checks every sentence against its clause, and
  fails when the document no longer prints it, as a correction does when the
  document is fixed. The block's page is the clause's in that copy's PDF.
- `; Versions:` is the range of the document's versions the reading was
  checked against. An RFC has one edition and no version, and its blocks
  name none. A reading is carried to another release's copy only once
  its sentences are found there, and is otherwise left out of that copy: of
  TS 29.272's 350, Release 19's copy holds 345 and Release 18's 339
  ([below](#the-interpretations-file)).
- The model's `Constraint`, the dictionary's and the export's say
  `interpreted`; the Wireshark plugin reports a breach as a note, whatever
  the quote's wording, its line ending in `interpreted`
  ([wireshark-plugin.md](wireshark-plugin.md#findings)).
- What no kind below expresses is recorded as `text-only`: the quote, and no
  rule a checker could run. A checker reports it unknown, never a guess.

Trust a rule as far as you trust its quote. Where the quote says "should", or
is a NOTE, the rule is the reader's; read the quote before rejecting traffic
on it.

## The block

[grammar.md](grammar.md#interpreted-constraints) defines it. Each kind, as
TS 29.272's file prints it:

```dad
; Type: Interpreted Constraints ;; interpreted: (TS29.272.dadx#imei-digits)
; AVP: IMEI
; Section: 7.3.4
; Page: 100
; Versions: 19.6.0
"It should consist of 14 digits, including the 8-digit Type Allocation Code (TAC) and the 6-digit Serial Number (SNR). It may also include a 15th digit."
    encoding digits
    length 14..15 digits


; Type: Interpreted Constraints ;; interpreted: (TS29.272.dadx#ue-usage-type-range)
; AVP: UE-Usage-Type
; Section: 7.3.202
; Page: 166
; Versions: 19.6.0
"The allowed values of UE-Usage-Type shall be in the range of 0 to 255."
    range 0..255


; Type: Interpreted Constraints ;; interpreted: (TS29.272.dadx#apn-configuration-non-ip-delivery)
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
| `encoding` | `encoding plmn-id`, `encoding element TS29.002 17.7.8 "E-UTRAN-CGI"` | the payload is laid out as the codec, or the element registry's entry, says |
| `present-if` | `present-if Result-Code = DIAMETER_SUCCESS` | the AVP is present when a condition holds |
| `absent-if` | `absent-if Emergency-Services bit Emergency-Indication` | the AVP is absent when a condition holds |
| `requires` | `requires DSR-Flags bit "Trace Data Withdrawal"` | a condition holds when the AVP is present |
| `excludes` | `excludes Other-AVP` | no condition holds when the AVP is present |
| `default` | `default FALSE`, `default 0` | (what an absent AVP is read as) |
| `bits` | `bits at-most-one 3 6`, `bits at-least-one 0 1`, `bits set 1`, `bits clear 4 5 6 7`, `bits only 9` | of these bits of the AVP's own value, at most one is set, at least one, each is set, each is clear, or none but these is set |
| `members` | `members at-least-one SCEF-Reference-ID SCEF-Reference-ID-Ext`, `members only IMEI Software-Version` | of the grouped AVP's members, at least one of these is present (one name: it is), or none but these |
| `unique` | `unique` | no two of the `; Within:` grouped AVPs beside each other hold the AVP with the same value |
| `values` | `values 1 if Monitoring-Type = 1` | the integer value is one of these when a condition holds |
| `equals` | `equals request/User-Name` | the AVP holds, octet for octet, the value of each one named, where both are present |
| `absent` | `absent` | the AVP is not present in the block's scope |
| `text-only` | `text-only` | (a reader decides) |

A predicate's conditions, and a `values` rule's, are alternatives (`or`), each
one or more conditions that must all hold (`and`, which binds tighter; there are
no parentheses), each on a sibling in the block's `; Command:` or `; Within:`
grouped AVP: present, holding a value (a number, or a name its values or result
codes give it), holding one of several
(`Result-Code in DIAMETER_SUCCESS, DIAMETER_MULTI_ROUND_AUTH`, names, numbers
and ranges such as `5000..5999`, which holds as the `or` of each value's `=`
would), or with a bit set (a number, or its bit table's name: a
Feature-List's, a feature's name in its features table, of the feature lists
of the block's application and of the Feature-List-ID the same `and` holds
beside it, a name standing for two bits there refused), or with `not`
none of these
(`present-if MIP6-Agent-Info and not MIP6-Agent-Info/MIP-Home-Agent-Host`,
`absent-if not Result-Code in DIAMETER_SUCCESS, DIAMETER_LIMITED_SUCCESS`). A
condition resting on a value that cannot be read is unknown, and so is what it
decides: `not` of an unknown is unknown, an `and` of a false one is false.
Several predicates in one block must all hold. `absent-if` and `excludes` say
the same of a presence condition, read from the other side; the kinds follow the
clause's wording. `; Application-ID:` after `; Within:` holds them only where a
message of that application, by its header's id, carries the grouped AVP.
`; Messages: answers` (or `requests`), with no other scope, holds them in every
answer (or request) of any application whose document is built on the reading
one (`; Bases:`), an answer with the E bit set, which takes the
`<answer-message>`, among them, a condition on a member of the message and, in
an answer, `request/` on the request it answers: RFC 6733's "MUST NOT be present
in answer messages" (section 6.5). Without a scope the rules hold wherever the
document reads the AVP, and a predicate there has no siblings to test, only the
AVP's own members through a path. A scope's AVP is a member its body prints or
one its `* [ AVP ]` admits, so a block may hold a command to a sentence about an
AVP its ABNF leaves to the wildcard; `absent` says such an AVP is never sent
there. A member of a grouped AVP the command holds is the grouped AVP's scope,
not the command's.

A name may be a path through grouped AVPs, `/` between the names, relative
to the block's scope: `MIP6-Agent-Info/MIP-Home-Agent-Host` tests the
MIP-Home-Agent-Host member of the command's MIP6-Agent-Info, which a sibling
condition cannot, and reaches a member of a grouped AVP the document re-uses
from another, as the defining document prints its body. With no scope a
path starts at the block's AVP itself, present wherever the rule is checked,
so the predicate is a grouped AVP's on its own members. Of the AVPs a path
names, any one meeting the condition does, but where the path starts at the
block's own AVP: a rule is checked on each instance of its AVP, and such a
path reads that instance alone. So `absent-if CC-Request-Type =
INITIAL_REQUEST and not Multiple-Services-Credit-Control/Requested-Service-Unit`
on Multiple-Services-Credit-Control holds every one of an initial request to
carry a Requested-Service-Unit (RFC 4006 section 5.2), where a path from the
command through another AVP of the name, or from a sibling, reads any one:
a rule on each instance of a repeated grouped AVP is written on that AVP,
or as a block within it. An `equals` rule holds its AVP to every AVP its
path names: each Monitoring-Event-Configuration's SCEF-ID is the CIR's
Origin-Host (TS 29.336 clause 8.4.5). A `members` rule may name a
member of a grouped
AVP another document defines (IMEI in TS 29.272's Terminal-Information, as
TS 29.273 re-uses it).

In a block scoped to an answer, a name after `request/` is a member of the
request the answer answers: the same command code with the R bit under the
same application, printed at the block's `; Request-Section:` where the
document prints that request more than once there, as TS 29.273 prints
Diameter-EAP-Request for STa and SWd under one application. A condition may
test it as it tests a sibling (`absent-if request/Emergency-Services bit
Emergency-Indication`), or compare a sibling's value with it
(`Result-Code = request/Result-Code`), and `equals` holds the AVP to it. Of
the request's members of a name, any one meeting the condition does. A rule
reading the request is checked only where the request is at hand: what
reads the answer alone reports it unchecked, never broken. A rule across
more than one exchange (an earlier answer, a session's state) has no form:
it is `text-only`.

A `bits` rule numbers bits as the AVP's bit table does, bit 0 the least
significant; an OctetString's bits are those of its octets read as one
big-endian number, so `bits clear 4 5 6 7` is a one-octet AVP's four most
significant bits. `members` says of a grouped AVP what `bits` says of a flags
AVP, by member name. `unique` holds across the grouped AVPs one body holds, and
needs `; Within:`: TS 29.272's Service-Selection within APN-Configuration
differs from one APN-Configuration of an APN-Configuration-Profile to the next.
There is no kind for "should": a rule read from "should" is a rule like any
other, its quote saying how far to trust it.

## Codecs

The set is closed, and holds the layouts the interpreted documents' clauses
name. A layout no clause states is not here.

| Codec | Layout | Defined in |
|---|---|---|
| `e164-tbcd` | an international number, ITU-T E.164 (1 to 15 decimal digits), as a TBCD-string: two digits an octet, the first in bits 1-4, "1111" filling bits 5-8 of the last octet after an odd count; no octet for the nature of address and numbering plan | TS 29.002 clause 17.7.8, as TS 29.272 clauses 7.3.39, 7.3.85, 7.3.91, 7.3.102, 7.3.157 and 7.3.159 and TS 29.329 clause 6.3.2 say |
| `plmn-id` | MCC and MNC in 3 octets: MCC digits 2 and 1, then MNC digit 3 (or "1111" for a 2-digit MNC) and MCC digit 3, then MNC digits 2 and 1 | TS 29.272 table 7.3.9/1, after TS 24.008 clause 10.5.1.13 |
| `plmn-id-prefix` | a `plmn-id` in the first 3 octets, more octets after it | TS 29.272 table 7.3.64/1 (Trace-Reference) |
| `digits` | decimal digits as text, a character each | TS 29.272 clauses 7.3.4, 7.3.5, 7.3.50 |
| `labels` | one or more non-empty labels separated by dots | TS 29.272 clause 7.3.32 |
| `apn` | `labels`, or the wild card `*` | TS 29.272 clause 7.3.36 |
| `plmn-domain` | `mnc<MNC>.mcc<MCC>.3gppnetwork.org`, MNC 2 or 3 digits, MCC 3, in any case | TS 29.272 clause 7.3.105 |
| `epc-plmn-domain` | `epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org` | TS 29.272 clause 7.3.43 |
| `ip-address` | an Address of family 1 (IPv4, 4 octets) or 2 (IPv6, 16) | RFC 6733 clause 4.3.1, as TS 29.272 clauses 7.3.98 and 7.3.109 restrict it |
| `time-zone` | a sign and decimal digits, the offset from UTC in 15 minutes: `+8`, a zero offset `+0`, never `-0` | TS 29.272 clause 7.3.163 |
| `mac-address` | a 6-octet MAC address as text, each octet two upper-case hexadecimal digits, joined by dashes: `00-10-A4-23-19-C0` | TS 29.273 clauses 5.2.3.23 and 5.2.3.30 |
| `ip-filter` | an IPFilterRule as TS 29.212 restricts it: `permit`, `in` or `out`, a protocol number or `ip`, `from` a source and `to` a destination, each `any`, `assigned` or an IPv4 or IPv6 number with an optional mask width, then optional ports, a list of ports and port ranges; no options, no `!`. A clause restricting it further says so after the codec: the direction (`out`), and for the source (`from`) and the destination (`to`) the keywords the address may be, `any`, `assigned`, both or neither, and the ports `port` (one) or `port-or-range` (one port or one range), so that `encoding ip-filter out from any to assigned` admits `permit out 17 from 192.0.2.10/32 5060 to assigned` and refuses `permit out ip from any to any` | RFC 6733 clause 4.3.1, as TS 29.212 clause 5.3.34 restricts it; further, TS 29.212 clauses 5.3.13, 5.3.54 and 5.4.2, TS 29.214 clause 5.3.8, ETSI TS 183 017 clause 7.3.17 |
| `session-id` | a Session-Id's text: the sender's DiameterIdentity (a host name in ASCII, its labels of letters, digits and inner hyphens, at most 63 octets each and 255 in all), then nothing or a `;` and any text: `aaa.example.com;1876543210;523` | RFC 6733 clauses 8.8 and 9.8.5 |
| `base64` | text in base64: characters of its alphabet, four to a group, the last group padded with `=`: `c2VhbmNoYWk=` | RFC 4648 clause 4, as TS 29.214 clause 5.3.77 names it |
| `element` | another document's information element, carried whole: its document, and the clause and name of the element | the cited document, as the element registry reads it ([below](#elements)) |

A clause pointing at another document without stating a layout ("Octets are
coded according to TS 29.002 [24]") is an `element` of that document, named
as specifically as the clause allows: the MAP type an AVP's name and clause
mean (`TS29.002 17.7.5 "SS-Code"`), the parameter of TS 32.422 it takes its
values from (`TS32.422 5.10.19 "Positioning Method"`).

`seanchai.constraints` checks a payload in Python: `codec_problem(codec,
payload)` says why a payload is no such layout, `digit_count` counts its
digits, `element_problem(rule, payload, data_type)` why it is not the element
an `encoding element` rule names, and `check(rule, payload, data_type, codec,
request)` tells whether a length, range, exclude, encoding or bits rule
holds, and a rule reading only the request where `request`, the request's
AVPs, is given; None where the payload alone cannot tell (another predicate,
a `values`, `members` or `unique` rule, an element the registry does not
have or checks nothing of, a `default`, `text-only`). `holds(rule, avp,
scope, request)` tells whether a predicate, a `values` or an `equals` rule
holds of the AVP named `avp` in `scope`, its run of AVPs (`Avp`: a name, a
type, a payload or members, and the numbers its names stand for), of each
AVP of that name in turn, a path from the name reading that one. A rule
reading the request with no request given is not evaluated: its `Check` is
None with `needs_request`, neither a pass nor a breach. A `bits` rule holds
of an unsigned integer's payload or an OctetString's (`bits_value`,
`bits_problem`).

## Elements

What an element looks like is not written in the `.dadx` file, which only
names it, but in the library's element registry, `seanchai.elements`: one
`Element` per document, clause and name, read from the defining document and
built from a closed set of declarative shapes, so that no file carries code:

| Shape | Holds when |
|---|---|
| `Octets` | the payload has so many octets, or a range of them |
| `Plmn` | three octets from a given one are a PLMN identity, as `plmn-id` |
| `Field` | bits of an octet, or running across octets, numbered 8 to 1 as the documents number them, take one of a set or range of values; a spare field takes the value it is coded with |
| `OneBit` | at most one bit of an octet is set |
| `Integer` | an integer-typed payload's value is within bounds |
| `Tbcd` | the octets from a given one are TBCD digits, "1111" filling only the last octet's bits 8-5 |
| `Fqdn` | the text is one of a few domain-name templates, `mmec<MMEC:hex:2>.mmegi<MMEGI:hex:4>.mme.epc...`, in any case |

Each entry cites every clause its layout was read from, with the edition read
(`Source`: TS 29.002 V19.1.0 clause 17.7.8, `E-UTRAN-CGI ::= OCTET STRING
(SIZE (7))`), following the references as far as they are concrete: MAP's
E-UTRAN-CGI to TS 29.118 clause 9.4.3a and on to TS 29.274's ECGI field. The
editions are Release 19's latest of each document the interpreted documents
cite non-specifically, as their references clauses mean; 3GPP2 publishes
A.S0022-0 v2.0 as its newest. Release 18's copies are held to the same
entries, though their references mean Release 18's editions, which were
mostly not read: where an element differs between the releases, a Release
18 sender would draw a note it does not deserve. TS 32.422's last Release
18 edition, V18.7.0, was read against V19.7.0 for the trace entries: its
Triggering Events, List of NE Types and List of Interfaces print the same
octets and bits, and of clause 5.10's elements only List of Measurements
differs, V19.7.0 numbering M10 in a bit V18.7.0 leaves spare, which the
entry does not check. Each says how deep its check goes, its `depth`:

- `full`: everything the document lets a sender get wrong is checked; an
  entry whose every value is defined checks nothing and says so (TS 24.008's
  4-bit eDRX fields);
- `partial`: some of it, the entry saying what is not and why;
- `length`: the octet count alone;
- `none`: nothing, the entry saying why.

A spare bit is checked to be what the document codes it as, unless the
document tells the receiver to ignore it, as TS 24.008 clause 10.5 and TS
29.274 clause 8.1 do: such a bit is no error of the message. A reserved
code point is checked only where the document says it is not sent; one a
receiver reads as another (TS 24.008's "All other values shall be
interpreted as 0000") is not. Where the AVP alone does not say which
variant applies, a RAT's table of bits or a measurement quantity's range,
only what every variant shares is checked.

A finding is a note like any other interpreted rule's, `constraint-element`,
its line citing TS 29.272's clause and, beneath it, the element and the
documents read ([wireshark-plugin.md](wireshark-plugin.md#findings)).
`elements.problem(entry, payload, data_type)` checks a payload against an
entry, `elements.lookup(document, clause, name)` finds one, `sample` and
`breaking` give the payloads `seanchai vectors` sends, and the dictionary's
and the export's rules carry the entry as `element_entry`
([consumers.md](consumers.md#the-dictionary), [website.md](website.md#blocks)).
The linter notes an element the registry has no entry for as
`constraint-element-unknown`: another document's interpretations may name
one before the registry learns it, and nothing checks it meanwhile.

TS 29.272's 45 `encoding element` rules name 42 entries, of which 36 check
something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| 3GPP2-MEID | 3GPP2 A.S0022 A Mobile Identity (MEID) | 3GPP2 A.S0022-0 v2.0 Annex A | 8 octets; octet 1 bits 4-1 (odd/even indicator 0, type of identity 001) 0001; octet 8 bits 8-5 (fill) 1111 | full | the 14 MEID hex digits take any value 0H to FH. 3gpp2.org publishes A.S0022-0 v2.0 (April 2010) as the newest revision; later revisions TIA republishes were not read |
| Destination-Host | TS 29.303 4.3.2 | TS 29.303 V19.1.0 4.3.2 | nothing | none | the clause binds the operator provisioning host names to the form, and tells implementations to treat a host name not of the form as valid, so a breach is no error of the message; the host name itself is checked as a DiameterIdentity |
| Regional-Subscription-Zone-Code | TS 23.003 4.4 Zone Code | TS 23.003 V19.8.0 4.4 | 2 octets | full | the code is in full hexadecimal representation: any value |
| RAND | TS 33.401 RAND | TS 33.401 V19.2.0 6.1.2; TS 33.102 V19.1.0 6.3.7 | 16 octets | full | a random number: any value |
| XRES | TS 33.401 XRES | TS 33.401 V19.2.0 6.1.2; TS 33.102 V19.1.0 6.3.7 | 4 to 16 octets | full | a function's output: any value |
| AUTN | TS 33.401 AUTN | TS 33.401 V19.2.0 6.1.2; TS 33.102 V19.1.0 6.3.2; TS 33.102 V19.1.0 6.3.7 | 16 octets | full | its fields take any value: the AMF's bits are the operator's |
| KASME | TS 33.401 K_ASME | TS 33.401 V19.2.0 6.2 | 32 octets | full | a key: any value |
| SRES | TS 33.102 SRES | TS 33.102 V19.1.0 6.8.1.2 | 4 octets | full | a function's output: any value |
| Trace-NE-Type-List | TS 32.422 5.4 List of NE Types | TS 32.422 V19.7.0 5.4 | 3 octets; octet 3 bits 8-7 (spare) 00 | full | every other bit is an NE type, set or not |
| Trace-Interface-List | TS 32.422 5.5 List of Interfaces | TS 32.422 V19.7.0 5.5 | 23 octets | length | the spare bits in each network element's bitmap are not checked: several of the bitmaps print fewer cells than bits, so which bits a spare cell spans is not certain, and NOTE 5 says the bitmaps may number bits otherwise than the signalling specifications do |
| Trace-Event-List | TS 32.422 5.1 Triggering Events | TS 32.422 V19.7.0 5.1 | 17 octets | length | the spare bits in each network element's bitmap are not checked: several of the bitmaps print fewer cells than bits, so which bits a spare cell spans is not certain |
| OMC-Id | TS 29.002 17.7.8 AddressString | TS 29.002 V19.1.0 17.7.2; TS 29.002 V19.1.0 17.7.8 | 1 to 20 octets; octet 1 bit 8 (extension, 1 for no extension) 1; octets 2 on TBCD digits (0-9, *, #, a, b, c), '1111' filling only the last octet's bits 8-5 | full | the nature of address and numbering plan values the type marks reserved are not refused, since it does not say they are not sent |
| PDP-Type | TS 29.002 17.7.1 PDP-Type | TS 29.002 V19.1.0 17.7.1; TS 29.060 V19.0.0 7.7.27 | 2 octets; octet 1 bits 8-5 (spare) 1111; octet 1 bit 4 to octet 2 bit 1 (PDP type organisation and number) PPP (0x001), Non-IP (0x002), IPv4 (0x121) or IPv6 (0x157) | full |  |
| Ext-PDP-Type | TS 29.002 17.7.1 Ext-PDP-Type | TS 29.002 V19.1.0 17.7.1; TS 29.060 V19.0.0 7.7.27 | 2 octets; octet 1 bits 8-5 (spare) 1111; octet 1 bit 4 to octet 2 bit 1 (PDP type organisation and number) IPv4v6 (0x18D) | full |  |
| QoS-Subscribed | TS 29.002 17.7.1 QoS-Subscribed | TS 29.002 V19.1.0 17.7.1; TS 24.008 V19.5.0 10.5.6.5 | 3 to 18 octets | length | the octets' fields are not checked: TS 24.008 has the receiver map a reserved value to another rather than refuse it, and its spare bits are ignored by the receiving side (clause 10.5) |
| CSG-Id | TS 23.003 4.7 CSG-ID | TS 23.003 V19.8.0 4.7 | nothing | none | the document fixes only the identity's 27 bits; where they sit in the Unsigned32 AVP is TS 29.272's own sentence, read as a bits rule beside it |
| SS-Code | TS 29.002 17.7.5 SS-Code | TS 29.002 V19.1.0 17.7.5 | 1 octet; octet 1 (SS-Code) a code clause 17.7.5 defines | full |  |
| SS-Status | TS 29.002 17.7.4 SS-Status | TS 29.002 V19.1.0 17.7.4 | 1 octet; octet 1 bits 8-5 (unused) 0000 | full |  |
| ServiceTypeIdentity | TS 29.002 17.7.8 LCSServiceTypeID | TS 29.002 V19.1.0 17.7.8 | an integer 0 to 127 | full | a standard type the clause has not yet named is reserved for one, not refused |
| TS-Code | TS 29.002 17.7.9 TeleserviceCode | TS 29.002 V19.1.0 17.7.9 | 1 octet; octet 1 (TeleserviceCode) a code clause 17.7.9 defines | full | Ext-TeleserviceCode's octets 2 to 5, reserved for future use, are not the type named |
| E-UTRAN-Cell-Global-Identity | TS 29.002 17.7.8 E-UTRAN-CGI | TS 29.002 V19.1.0 17.7.8; TS 29.118 V19.1.0 9.4.3a; TS 29.274 V19.6.0 8.21.5 | 7 octets; a PLMN identity in octets 1 to 3 | full | octet 4's bits 8-5 are the spare bits TS 29.274 clause 8.1 says are sent as 0 and not evaluated by the receiver; the ECI takes any value |
| Tracking-Area-Identity | TS 29.002 17.7.8 TA-Id | TS 29.002 V19.1.0 17.7.8; TS 29.118 V19.1.0 9.4.21a; TS 29.274 V19.6.0 8.21.4 | 5 octets; a PLMN identity in octets 1 to 3 | full | the tracking area code takes any value, its coding being each administration's |
| Cell-Global-Identity | TS 29.002 17.7.8 CellGlobalIdOrServiceAreaIdFixedLength | TS 29.002 V19.1.0 17.7.8 | 7 octets; a PLMN identity in octets 1 to 3 | full | the location area code and the cell identity or service area code take any value |
| Routing-Area-Identity | TS 29.002 17.7.8 RAIdentity | TS 29.002 V19.1.0 17.7.8; TS 29.060 V19.0.0 7.7.3 | 6 octets; a PLMN identity in octets 1 to 3 | full | the location and routing area codes take any value |
| Location-Area-Identity | TS 29.002 17.7.8 LAIFixedLength | TS 29.002 V19.1.0 17.7.8 | 5 octets; a PLMN identity in octets 1 to 3 | full | the location area code takes any value |
| Service-Area-Identity | TS 29.002 17.7.8 CellGlobalIdOrServiceAreaIdFixedLength | TS 29.002 V19.1.0 17.7.8 | 7 octets; a PLMN identity in octets 1 to 3 | full | the location area code and the cell identity or service area code take any value |
| Geographical-Information | TS 29.002 17.7.1 GeographicalInformation | TS 29.002 V19.1.0 17.7.1; TS 23.032 V19.0.0 7.3.2; TS 23.032 V19.0.0 7.2 | 8 octets; octet 1 bits 8-5 (type of shape) 0001; octet 1 bits 4-1 (spare) 0000; octet 8 bit 8 (spare) 0 | full | the latitude, longitude and uncertainty code take any value |
| Geodetic-Information | TS 29.002 17.7.1 GeodeticInformation | TS 29.002 V19.1.0 17.7.1; ITU-T Q.763 (12/1999) 3.88 | 10 octets; octet 1 bits 8-5 (spare) 0000; octet 2 bits 7-1 (type of shape) 0000001; octet 9 bit 8 (spare) 0; octet 10 bit 8 (spare) 0; octet 10 bits 7-1 (confidence) 0 to 100 | full | the extension bit's value for a parameter of one octet of shape is not stated; the LPRI's spare code 11 is one for future use, not refused |
| Age-Of-Location-Information | TS 29.002 17.7.8 AgeOfLocationInformation | TS 29.002 V19.1.0 17.7.8 | an integer 0 to 32767 | full |  |
| List-Of-Measurements | TS 32.422 5.10.3 List of Measurements | TS 32.422 V19.7.0 5.10.3 | octet 2 bit 8 (spare) 0; octets 3 to 4 (spare) all 0 | partial | only the bits spare in every RAT's table are checked: the AVP does not say which RAT its bits are read for, and octet 2's other spare bits are measurements in another RAT |
| Reporting-Trigger | TS 32.422 5.10.4 Reporting Trigger | TS 32.422 V19.7.0 5.10.4 | nothing | none | the document defines one octet, TS 29.272 an Unsigned32 whose most significant bit is bit 8 of its first octet, so which of the four octets holds the bitmap is said by neither |
| Event-Threshold-RSRP | TS 32.422 5.10.7 Event Threshold for Event A2 | TS 32.422 V19.7.0 5.10.7 | an integer 0 to 127 | partial | an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not checked: the AVP does not say which RAT it is for |
| Event-Threshold-RSRQ | TS 32.422 5.10.7 Event Threshold for Event A2 | TS 32.422 V19.7.0 5.10.7 | an integer 0 to 127 | partial | an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not checked: the AVP does not say which RAT it is for |
| Positioning-Method | TS 32.422 5.10.19 Positioning Method | TS 32.422 V19.7.0 5.10.19 | octet 1 bits 8-3 (spare) 000000 | partial | bit 2, spare in NR, is E-Cell ID in LTE, and the AVP does not say which RAT it is for |
| Measurement-Quantity | TS 32.422 5.10.15 Measurement Quantity | TS 32.422 V19.7.0 5.10.15 | at most one bit of octet 1 set | full | bits 8-4 are reserved, not refused, since the clause does not say they are not sent |
| Event-Threshold-Event-1F | TS 32.422 5.10.13 Event Threshold for Event 1f | TS 32.422 V19.7.0 5.10.13 | an integer -120 to 165 | partial | the narrower range of the measurement quantity (CPICH RSCP -120..-25, Ec/No -24..0, pathloss 30..165) is not checked: it is another AVP's |
| Event-Threshold-Event-1I | TS 32.422 5.10.14 Event Threshold for Event 1i | TS 32.422 V19.7.0 5.10.14 | an integer -120 to -25 | full |  |
| SGs-MME-Identity | TS 23.003 19.4.2.4 MME node FQDN | TS 23.003 V19.8.0 19.4.2.4; TS 23.003 V19.8.0 19.2 | mmec<MMEC>.mmegi<MMEGI>.mme.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org (MMEC 2 hexadecimal digits, MMEGI 4 hexadecimal digits, MNC 3 digits, MCC 3 digits), in any case | full |  |
| Coupled-Node-Diameter-ID | TS 23.003 19.4.2 MME or SGSN node FQDN | TS 23.003 V19.8.0 19.4.2.4; TS 23.003 V19.8.0 19.4.2.6; TS 23.003 V19.8.0 19.2 | mmec<MMEC>.mmegi<MMEGI>.mme.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org or nri-sgsn<NRI>.rac<RAC>.lac<LAC>.rac.epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org (MMEC 2 hexadecimal digits, MMEGI 4 hexadecimal digits, MNC 3 digits, MCC 3 digits, NRI 4 hexadecimal digits, RAC 4 hexadecimal digits, LAC 4 hexadecimal digits), in any case | full |  |
| eDRX-Cycle-Length-Value | TS 24.008 10.5.5.32 eDRX value | TS 24.008 V19.5.0 10.5.5.32 | every 4-bit value is valid, an undefined one read as 0000; nothing to refuse | full | the octet carrying the field is held to TS 29.272's own length and bits rules instead |
| Paging-Time-Window-Length | TS 24.008 10.5.5.32 Paging Time Window | TS 24.008 V19.5.0 10.5.5.32 | every 4-bit value is defined; nothing to refuse | full | the octet carrying the field is held to TS 29.272's own length and bits rules instead |
| 5QI | TS 23.501 5QI | TS 23.501 V19.9.0 5.7.2.1 | nothing | none | the document gives no range: beside the standardized values a 5QI may be a pre-configured or dynamically assigned one |
| Event-Threshold-SINR | TS 32.422 5.10.7 Event Threshold for Event A2 | TS 32.422 V19.7.0 5.10.7 | an integer 0 to 127 | partial | an LTE threshold's narrower range (RSRP 0-97, RSRQ 0-34) is not checked: the AVP does not say which RAT it is for |
| Collection-Period-M7-NR | TS 32.422 5.10.35 Collection Period M7 in NR | TS 32.422 V19.7.0 5.10.35 | an integer 1 to 60 | full |  |
| NR-Cell-Global-Identity | TS 29.002 17.7.8 NR-CGI | TS 29.002 V19.1.0 17.7.8; TS 38.413 V19.4.0 9.3.1.7 | 8 octets; a PLMN identity in octets 1 to 3 | partial | where the 36 bits of the NR cell identity sit in the last five octets, and what the other four are, neither document says |

TS 29.329's 3 name 3 entries, of which 2 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| User-Data | TS 29.328 C Sh-Data | TS 29.328 V19.2.0 Annex C; TS 29.328 V19.2.0 Annex D | nothing | none | an XML document the schema of Annex D defines: no shape of the registry reads XML |
| Call-Reference-Number | TS 29.002 17.7.3 CallReferenceNumber | TS 29.002 V19.1.0 17.7.3 | 1 to 8 octets | full | the octets take any value: the type says nothing more of them |
| AS-Number | TS 29.002 17.7.8 ISDN-AddressString | TS 29.002 V19.1.0 17.7.3; TS 29.002 V19.1.0 17.7.8 | 1 to 9 octets; octet 1 bit 8 (extension, 1 for no extension) 1; octets 2 on TBCD digits (0-9, *, #, a, b, c), '1111' filling only the last octet's bits 8-5 | full | the nature of address and numbering plan values the type marks reserved are not refused, since it does not say they are not sent |

TS 29.273's 6 name 6 entries, of which 4 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| ANID | TS 24.302 8.1.1 Access Network Identity | TS 24.302 V19.0.0 8.1.1.1; TS 24.302 V19.0.0 8.1.1.2 | nothing | none | no shape of the registry bounds a text's octets, and a prefix the tables do not name is 'Not defined', not refused: NOTE 6 leaves further prefixes to be defined |
| Full-Network-Name | TS 24.302 8.2.5.1 Full name value | TS 24.302 V19.0.0 8.2.5.1; TS 24.008 V19.5.0 10.5.3.5a | at least 1 octet; octet 1 bit 8 (ext) 1 | partial | the coding scheme's reserved values 010 to 111 are not refused, since the clause does not say they are not sent, and the text string, with the spare bits its last octet holds, is not decoded |
| Short-Network-Name | TS 24.302 8.2.5.2 Short name value | TS 24.302 V19.0.0 8.2.5.2; TS 24.008 V19.5.0 10.5.3.5a | at least 1 octet; octet 1 bit 8 (ext) 1 | partial | as Full-Network-Name's |
| MIP-FA-RK | TS 33.402 9.2.1.2.2 FA-RK | TS 33.402 V19.0.0 9.2.1.2.2 | 20 octets | full | a key: any value |
| MIP-FA-RK-SPI | TS 33.402 9.2.1.2.2 FA-RK-SPI | TS 33.402 V19.0.0 9.2.1.2.2 | nothing | none | a derived index: the clause steps it clear of the other active SPIs and of the top of the range, which a single message cannot show |
| WLCP-Key | TS 33.402 A.3 WLCP key | TS 33.402 V19.0.0 A.3; TS 33.402 V19.0.0 A.1; TS 33.220 V19.1.0 B.2.0 | 32 octets | full | a key: any value |

TS 29.212's 5 name 5 entries, all of which check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| RAN-NAS-Release-Cause | TS 29.274 8.103 RAN/NAS Cause | TS 29.274 V19.6.0 8.103 | at least 2 octets | partial | that a Diameter or IKEv2 cause takes two octets is not checked: no shape ties a length to a field's value; the protocol types 6 to 15 are spare, not refused, since the clause does not say they are not sent, and the cause type and value take any value |
| Presence-Reporting-Area-Elements-List | TS 29.274 8.108 Presence Reporting Area Action | TS 29.274 V19.6.0 8.108 | at least 6 octets | partial | that the elements' octets add up to the counts is not checked: no shape sums them; the spare bits of octets 10 to 14 are the ones TS 29.274 clause 8.1 says are sent as 0 and not evaluated by the receiver, and each count's own bits bound it at 15 or 63 |
| Presence-Reporting-Area-Identifier | TS 29.274 8.109 PRA Identifier | TS 29.274 V19.6.0 8.109; TS 23.003 V19.8.0 19.10 | 3 octets | full | the identifier takes any value, its most significant bit telling a UE-dedicated area from a core network predefined one |
| Framed-IPv6-Prefix | RFC 3162 2.3 Framed-IPv6-Prefix | RFC 3162 (August 2001) 2.3 | 2 to 18 octets; octet 1 (Reserved) 00000000; octet 2 (Prefix-Length) 00000000 to 10000000 | partial | that the bits beyond the prefix length are zero is not checked: no shape reads a length from a field |
| Framed-IPv6-Prefix (an Sd CCR's) | TS 29.212 5b.4.0 Framed-IPv6-Prefix | TS 29.212 V19.1.0 5b.4.0; RFC 3162 (August 2001) 2.3 | 18 octets; octet 1 (Reserved) 00000000; octet 2 (Prefix-Length) 10000000 | full | the address takes any value |


TS 29.214's 6 name 6 entries, of which 5 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| NID | TS 23.003 12.7.1 NID | TS 23.003 V19.8.0 12.7.1 | nothing | none | the clause gives the NID as 11 hexadecimal digits, and neither it nor TS 29.214 clause 5.3.68 says how an OctetString carries them, as 11 characters or packed in 44 bits |
| 5GMM-Cause | TS 24.501 9.11.3.2 5GMM cause | TS 24.501 V19.8.0 9.11.3.2 | an integer 0 to 65535 | partial | whether the Unsigned32 carries the cause value alone or the element's two octets with its IEI the clauses do not say, so only that it fits in two octets is checked; a value table 9.11.3.2.1 does not name is read as 'protocol error, unspecified', not refused |
| 5GSM-Cause | TS 24.501 9.11.4.2 5GSM cause | TS 24.501 V19.8.0 9.11.4.2 | an integer 0 to 65535 | partial | as 5GMM-Cause's; a value table 9.11.4.2.1 does not name is read as 'Request rejected, unspecified' |
| NGAP-Group | TS 38.413 9.4.5 Cause | TS 38.413 V19.4.0 9.4.5 | an integer 0 to 4 | full | the CHOICE's choice-Extensions holds no IE in this edition, so the five groups 0 to 4 are all |
| Framed-IPv6-Prefix | RFC 3162 2.3 Framed-IPv6-Prefix | RFC 3162 (August 2001) 2.3 | as TS 29.212's | partial | as TS 29.212's |
| Framed-IPv6-Prefix (the AF's) | TS 29.214 5.4.0 Framed-IPv6-Prefix | TS 29.214 V19.3.0 5.4.0; RFC 3162 (August 2001) 2.3 | 18 octets; octet 1 (Reserved) 00000000; octet 2 (Prefix-Length) 10000000 | full | the address takes any value |

TS 32.299's 8 name 8 entries, of which 3 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| Bearer-Capability | TS 29.078 5.1 BearerCapability | TS 29.078 V19.0.0 5.1; TS 29.078 V19.0.0 5.5 | 2 to 11 octets | length | the User Service Information's fields are ETSI EN 300 356-1's, a document the corpus does not hold, and are not read |
| Location-Estimate | TS 23.032 7 Geographical area description | TS 23.032 V19.0.0 7.2; TS 23.032 V19.0.0 7.3.1 | at least 7 octets | partial | the shape's own layout and length are not checked: the AVP may carry any of them; the type codes table 2a reserves are not refused, since the clause does not say they are not sent |
| PDN-Connection-Charging-ID | TS 29.061 16.4.7.2 3GPP-Charging-Id | TS 29.061 V19.1.0 16.4.7.2 | a 32-bit charging identifier: every value of the Unsigned32 | full |  |
| Radio-Frequency | TS 36.331 6.3.4 ARFCN-ValueEUTRA-r9 | TS 36.331 V19.4.0 6.3.4; TS 36.331 V19.4.0 8.1 | nothing | none | the clause gives an ASN.1 type, and clause 8.1's unaligned PER is the transfer syntax of RRC PDUs: neither it nor TS 32.299 clause 7.2.160A says by which rules the OctetString encodes the value |
| Radio-Parameter-Set-Values | TS 36.331 9.3.2 SL-Preconfiguration-r12 | TS 36.331 V19.4.0 9.3.2; TS 36.331 V19.4.0 8.1 | nothing | none | the clause gives an ASN.1 type, which no shape of the registry decodes, and neither it nor TS 32.299 clause 7.2.160C says by which encoding rules the OctetString carries it |
| SM-User-Data-Header | TS 23.040 9.2.3.24 User-Data-Header | TS 23.040 V19.0.0 9.2.3.24 | at least 1 octet | length | whether the AVP carries the Length of User Data Header octet before the information elements neither document says, so the lengths the header's fields give are not checked; an identifier the clause reserves is skipped by the receiver, not refused |
| WLAN-Operator-Name | TS 23.003 19.8 TWAN Operator Name | TS 23.003 V19.8.0 19.8 | nothing | none | no shape of the registry reads a domain name's labels, their characters and how each begins and ends |
| Nr-Cgi | TS 23.003 19.6A NCGI | TS 23.003 V19.8.0 19.6A | nothing | none | the clause gives the NCGI as a PLMN identity and 36 bits, and neither it nor TS 32.299 clause 7.2.254 says how a UTF8String spells them |

TS 29.338's 9 name 4 entries, of which 3 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| SM-RP-SMEA | TS 23.040 9.1.2.5 Address fields | TS 23.040 V19.0.0 9.1.2.5 | 2 to 12 octets | length | the Type-of-Address is not checked: a receiver reads its reserved values as Unknown, and the octets the clause draws are a figure; that the Address-Length counts the Address-Value's semi-octets is not checked: no shape ties a length to a field |
| MME-Absent-User-Diagnostic-SM, MSC-, SGSN-, SMSF-3GPP-, SMSF-Non-3GPP- and Absent-User-Diagnostic-SM | TS 23.040 3.3.2 Reason for absence | TS 23.040 V19.0.0 3.3.2 | an integer 0 to 255 | full | the values 14 to 255 the table reserves are not refused, since it does not say they are not sent |
| SM-RP-UI | TS 23.040 9.2.2 TPDU | TS 23.040 V19.0.0 9.2.2; TS 23.040 V19.0.0 9.2.3.1 | at least 1 octet | length | the PDU's type and fields are not checked: what a TP-MTI value means turns on the direction, which the AVP does not carry, and a receiver reads the reserved one as an SMS-DELIVER |
| HSS-ID | TS 23.003 5.3 HSS-ID | TS 23.003 V19.8.0 5.3 | nothing | none | no shape of the registry bounds a text's digits |

TS 29.128's 10 name 10 entries, of which 5 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| S1AP-Cause | TS 36.413 9.2.1.3 Cause | TS 36.413 V19.2.0 9.3.4 | nothing | none | how many values a cause has turns on its group, which another AVP (Cause-Type) carries, and every group's ENUMERATED is extensible, so no bound holds of each |
| RANAP-Cause | TS 25.413 9.2.1.4 Cause | TS 25.413 V19.0.0 9.3.4 | an integer 1 to 512 | partial | value 256, which the module's comment says 'shall not be used', is not refused: no shape leaves out one value of a range; a value its group's INTEGER names no cause for is not refused either, since the groups leave room for causes to come |
| BSSGP-Cause | TS 48.018 11.3.8 Cause | TS 48.018 V19.0.0 11.3.8 | an integer 0 to 255 | full | a value the table does not list is treated as 'protocol error - unspecified', not refused |
| GMM-Cause | TS 24.008 10.5.5.14 GMM cause | TS 24.008 V19.5.0 10.5.5.14 | an integer 0 to 255 | full | a value table 10.5.147 does not name is read as 'Protocol error, unspecified', not refused |
| SM-Cause | TS 24.008 10.5.6.6 SM cause | TS 24.008 V19.5.0 10.5.6.6; TS 24.008 V19.5.0 10.5.6.6A | an integer 0 to 255 | full | a value table 10.5.157 does not name is read as another, not refused |
| Extended-PCO | TS 24.301 9.9.4.26 Extended protocol configuration options | TS 24.301 V19.8.0 9.9.4.26; TS 24.008 V19.5.0 10.5.6.3A; TS 24.008 V19.5.0 10.5.6.3 | 1 to 65535 octets; octet 1 bit 8 (ext) 1 | partial | the spare bits, which the receiver ignores (TS 24.008 clause 10.5), the configuration protocol and the protocol and container entries are not checked: no shape walks a list of entries |
| Uplink-Number-Of-Packets-Allowed, Number-Of-Additional-Exception-Reports, Downlink-Number-Of-Packets-Allowed | TS 29.274 8.38 (the field of that name) | TS 29.274 V19.6.0 8.38 | 4 octets the Unsigned32 carries whole: every value | full |  |
| APN-Rate-Control-Status-Validity-Time | TS 29.274 8.38 APN Rate Control Status validity Time | TS 29.274 V19.6.0 8.38 | 8 octets the Unsigned64 carries whole: every value | full |  |

RFC 8506's 4 name 4 entries, of which 2 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| User-Equipment-Info-IMEISV | TS 23.003 6.2.2 IMEISV | TS 23.003 V19.8.0 6.2.2 | nothing | none | the clause gives the IMEISV as 16 decimal digits, and neither it nor RFC 8506 clause 8.53 says how an OctetString carries them, as 16 characters or packed two to an octet |
| User-Equipment-Info-MAC | RFC 5777 4.1.7.8 MAC-Address | RFC 5777 (February 2010) 4.1.7.8 | 6 octets | full | the address takes any value |
| User-Equipment-Info-ModifiedEUI64 | RFC 4291 2.5.1 Modified EUI-64 | RFC 4291 (February 2006) 2.5.1 | 8 octets | full | the identifier takes any value, its 'u' bit set or not |
| User-Equipment-Info-IMEI | TS 23.003 6.2.1 IMEI | TS 23.003 V19.8.0 6.2.1 | nothing | none | the clause gives the IMEI as 15 decimal digits, and neither it nor RFC 8506 clause 8.57 says how an OctetString carries them, as 15 characters or packed two to an octet |

TS 29.061's 6 name 6 entries, of which 3 check something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| 3GPP-CAMEL-Charging-Info | TS 29.060 7.7.54 CAMEL Charging Information Container | TS 29.060 V19.0.0 7.7.54 | nothing | none | the container holds TS 32.298's CAMELInformationPDP in its ASN.1 encoding, tag and length included, which no shape of the registry decodes |
| TWAN-Identifier | TS 29.274 8.100 TWAN Identifier | TS 29.274 V19.6.0 8.100 | at least 2 octets; octet 2 (SSID Length) 00000000 to 00100000 | partial | the fields the flags make present, and that the lengths add up to the payload's, are not checked: no shape reads a length or a flag from a field; the spare bits of octet 5, the payload's first, are the ones TS 29.274 clause 8.1 says are sent as 0 and not evaluated by the receiver |
| TMGI | TS 24.008 10.5.6.13 Temporary Mobile Group Identity | TS 24.008 V19.5.0 10.5.6.13 | nothing | none | the element is a type 4 information element of 5 to 8 octets, and neither it nor TS 29.061 clause 17.7.2 says whether the AVP carries its IEI and length octets or its contents alone |
| Required-MBMS-Bearer-Capabilities | TS 24.008 10.5.6.14 MBMS bearer capabilities | TS 24.008 V19.5.0 10.5.6.14 | nothing | none | the element's octets are binary, and neither it nor TS 29.061 clause 17.7.3, which types the AVP UTF8String and calls its content UTF-8 encoded, says how a UTF8String spells them |
| Additional-MBMS-Trace-Info | TS 29.060 7.7.68 Additional MBMS Trace Info | TS 29.060 V19.0.0 7.7.68 | 8 octets | length | the fields are not placed: figure 7.7.68.1 numbers Trace Reference2 octets 4 to 6 and the Trace Recording Session Reference no octets of its own, so where each field sits is not certain; the Trace Activity Control's reserved values would not be refused, since the figure does not say they are not sent |
| MBMS-Time-To-Data-Transfer | TS 48.018 11.3.92 Time to MBMS Data Transfer | TS 48.018 V19.0.0 11.3.92 | 1 octet | full | every value of the octet is a time, 1 to 256 seconds |

TS 29.173's 1 names 1 entry, which checks something:

| AVP | Element | Read | Checked | Depth | Not checked |
|---|---|---|---|---|---|
| LMSI | TS 23.003 2.5 LMSI | TS 23.003 V19.8.0 2.5 | 4 octets; octets 1 to 4 (LMSI) 0x00000001 to 0xffffffff | full | any value but zero, which the clause reserves for an LMSI the VLR is not to interpret |

## Reading them

- The model: `Avp.constraints` holds what the reading document read of the
  AVP wherever it appears, or else its origin's, as value tables are; a
  document's rules on an AVP it re-uses make its reading one of its own,
  read through it, so they hold where that document reads the AVP;
  `Grouped.member_constraints` what it read of the grouped AVP's members,
  and the origin's of the members it does not read;
  `Message.constraints` what it read of the command's members.
  ([Precedence](#precedence) says which document's rules hold where.)
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
- The Wireshark plugin checks lengths, ranges, exclusions, the codecs, an
  `element` as far as its registry entry does, `bits`, `members` and `unique`
  rules, and the predicates, `values` and `equals` rules whose names
  resolve, those reading the request against the request the capture holds;
  a `default` breaks nothing on the wire
  ([wireshark-plugin.md](wireshark-plugin.md#what-it-checks)).

## Precedence

A rule belongs to the document whose clause it reads, and holds where that
document's reading reaches: a block on a command, the command's print; a block
within a grouped AVP, that AVP wherever the document reads it; a block with no
scope, the AVP wherever the document reads it. A document reading an AVP or
grouped AVP another defines reads the origin's rules with it, unless it reads
that AVP itself, in the same scope: its blocks on the AVP with no scope set
aside the origin's with no scope, and its blocks on a member within the grouped
AVP the origin's on that member. So RFC 6733's reading of
Vendor-Specific-Application-Id's Auth-Application-Id holds in TS 32.299, which
reads only its Vendor-Id there, and a document that says otherwise of an AVP
than its origin does writes its own reading of it, which is the one checked
where it reads the AVP. A block within a grouped AVP for one application
(`; Application-ID:`) holds in that application's messages alone, and sets the
origin's rules on the member aside as one for every application does. A block
holding in every answer or request (`; Messages:`) holds in each command of a
document built on its own, relays', proxies' and redirect agents' answers among
them, unless the command's document reads the AVP in a block of its own on the
command, which sets it aside there: RFC 6733's Session-Id echo of section 6.2
holds in S6a's ULA, and its ACA reads Session-Id in clause 9.7.2 instead. An
answer with the E bit set holds the rules that read no request, since its
`<answer-message>` answers any. A block on a command never reaches another
document's print of it: RFC 6733's rules on its STR bind no application's own
Session-Termination-Request.

## The interpretations file

A document's interpretations are written in `edits/interpretations/`, one
file per document named by its reference with the suffix `.dadx`:
`TS29.272.dadx`. The syntax is the `.dad` syntax
([grammar.md](grammar.md#interpretations-files)); the suffix keeps the corpus
loaders and `--with`, which read `*.dad`, from taking the file for a
document. It holds a `; Interprets:` header naming the document as its
`; Specification:` does (`3GPP TS 29.272`, `RFC 6733`), then the blocks,
in the document's clause order, so a reviewer reads it beside the
specification:

```dad
; Interprets: 3GPP TS 29.272


; Type: Interpreted Constraints
; Id: apn-configuration-non-ip-delivery
; AVP: Non-IP-Data-Delivery-Mechanism
; Within: APN-Configuration
; Section: 7.3.35
; Versions: 18.7.0..19.6.0
"The Non-IP-Data-Delivery-Mechanism shall only be present when Non-IP-PDN-Type-Indicator is set to TRUE (1)."
    requires Non-IP-PDN-Type-Indicator = TRUE
```

- A person writes the scope (`; AVP:`, `; Within:` with `; Application-ID:`,
  `; Messages:`, or `; Command:` with `; Application-ID:`, `; Command-Section:`
  and `; Request-Section:`, `; Section:`, `; Table:`), the quotes and the rules,
  and `; Versions:`, the range the quotes were checked against, which an RFC's
  file, with no version to name, leaves out (a block naming one, or a 3GPP block
  naming none, is refused). `; Application-ID:` names the application of the
  command's print: its header's id, or where the header names none, the one the
  application scope covering its clause gives it, as TS 29.212's Gx and Gxx
  prints of CC-Request take theirs. After `; Within:` it names the application
  whose messages, by their header's id, carry the grouped AVP the rules hold in:
  where a document sets a member's value "for the SWm application" in a clause
  of each application, as TS 29.273 sets Feature-List-ID. `; Command-Section:`
  names the clause of the command's block where the document prints the command
  more than once for one application: TS 29.273 prints Diameter-EAP-Answer for
  STa and SWd under STa's application.
- `; Id:` names the block: a kebab-case name, unique in the file, naming what
  is read (`imei-digits`), not where. The corrected file's note and the
  corrections record cite it as `TS29.272.dadx#imei-digits`, so it stays put
  when the clause is renumbered or the block moves.
- `; Page:` is not written: it is the clause's page in each copy, read from
  that copy's source as the block is merged, so one block serves the copies
  of several releases.
- `;;` comments are the author's notes; they stay in the file and do not
  reach the corrected one.

`seanchai corpus regenerate` merges the file into each corrected copy after
the document's corrections:

- Each block whose range spans the copy's release is placed after the last
  block whose clause sorts at or before its own, in the order written: a
  block reading clause 7.3.9 follows clause 7.3.8's, and one reading an
  information element's description follows its table.
- Every quote must be within one paragraph or table cell of its clause, or
  of a clause containing it (RFC 6733 clause 10 prints the symbols of clause
  10.1's table), once whitespace is collapsed, as the extractor reads it;
  an RFC's quote within one paragraph, its lines joined, a word its hyphen
  breaks across a line
  ("out-of-" over "order") joined whole, and a paragraph running on across
  a page break, its running footer and header dropped, where its last line
  before the break was filled to 72 columns and the next line keeps its
  indent. A miss fails the document, naming the
  file and line of the quote:
  `edits/interpretations/TS29.272.dadx:435: imei-digits: clause 7.3.4 does
  not print 'It should consist of 16 digits, ...'`.
- A transcription (`edits/transcriptions/`) has no extracted source, so its
  quotes are held to the text of the PDF it was copied from, which
  `seanchai corpus download --only transcribed` fetches: a clause runs from
  its outline heading's line to the next heading's, the running header
  ("ETSI TS 183 017 V3.2.1 (2010-02)") dropped and a word its hyphen breaks
  across a line joined whole, and a quote must be within the clause's text
  (`transcription.pdf_clause_texts`). Where the PDF is not downloaded the
  blocks are merged unchecked, under a warning naming the PDF. Either way
  each block's note in the corrected file ends `, quoted from the PDF`
  (`;; interpreted: (ETSI-TS183.017.dadx#flow-usage-default), quoted from
  the PDF`), and the model's, the dictionary's and the export's constraint
  say `quoted_from_pdf`, so that a consumer can tell a reading held to a
  hand transcription's PDF from one held to an extracted source. A block's
  page is the one the transcription prints for its clause, none where it
  prints no block of the clause, so that the corrected file does not turn
  on whether the PDF is at hand. The transcription states its version, so
  each block names `; Versions:`.
- Merging expects the corrected file to hold every AVP a block names, one
  command of its scope's name, application and clause, the AVP in the
  command's or the grouped AVP's printed body, and no other block for the
  same AVP, scope and clause.
- A block applies only to copies of the releases its range spans, since
  whether a clause prints a sentence is a fact of each copy. Every block
  whose range does not span a copy's release is offered to it, whatever the
  other blocks' ranges, unless a copy of the document in another release
  the corpus holds lies between the two, which the widened range would
  claim without the block being held to it. `regenerate` counts those
  whose quotes the copy prints in a warning, and with `--expand-ranges`
  merges each and widens its `; Versions:` line to the copy in the file;
  each whose quotes it does not print is reported as `not carried:` with
  the sentence the clause lacks, and stays out. Such a run reads a
  document's copies newest first, so that going back widens a block one
  release at a time. A copy of a release the corpus holds only for
  citations (TS 29.212's Release 11) is offered nothing unless the run is
  given `--offer-cited`. Release 18's copy holds 339 of TS 29.272's 350:
  six it does not read sentences Release 19 added, and five read a bit
  table Release 19 extends, a block for each release's table (`bits only`
  of ULR-Flags, MPS-Priority, Subscription-Data-Flags,
  Supported-Monitoring-Events and AIR-Flags), which merging keeps apart,
  as no clause takes two blocks on one AVP and scope.
- `corrections.json` records each block by its citation, kind `interpret`,
  with its clause and quotes
  ([corrections.md](corrections.md#the-corrections-record)).

`seanchai format` keeps the file in canonical form, comments included, and
`seanchai lint FILE.dadx` checks it: its syntax, rules, ids and clause order
as it is read, and with a corpus the `constraint-*` rules in each copy of the
document a block's range spans, as the copy would read the block merged in
place of its own ([linter.md](linter.md#interpreted-constraints)).
`seanchai corpus correct` and `corpus extract` take `--interpretations DIR`
to merge a file without its source: no quote is checked and no block is
paged.

A file of your own beside a private `--with` document is not read: write
that document's Interpreted Constraints blocks in its `.dad` itself, as any
file may hold them, with no source to hold their quotes to.

## Adding them for another document

1. Read every AVP clause of the document, and the descriptions of its
   information-element tables' C rows. Keep the source text at hand:
   `seanchai.extractor.tgpp_docx.clause_texts(docx, Path("edits/sources"))`
   gives each clause's paragraphs and cells as the quote check reads them.
2. Create `edits/interpretations/<SpecRef>.dadx` with its `; Interprets:`
   line, and for each rule a clause states write a block, in clause order:
   an `; Id:`, the AVP, its scope where the clause speaks of the AVP in a
   command or grouped AVP, the clause and table, the version read as
   `; Versions:`, and readings of the shortest quotes that state the rule.
3. Prefer `text-only` to a rule the quote does not settle. A rule depending
   on an earlier message, a feature, the node, the interface or the
   subscriber is `text-only`; so is a NOTE outside a table, which states no
   requirement. A clause pointing at another document for a layout is an
   `element`, named by its clause and name in that document.
4. Run `uv run seanchai format edits/interpretations/<SpecRef>.dadx` and
   `uv run seanchai lint edits/interpretations/<SpecRef>.dadx`, then
   `uv run seanchai corpus regenerate --spec <SpecRef>`. A quote the clause
   does not print fails the document at the quote's line.
5. A layout no codec describes needs a codec, defined with its clause in
   `ast.Codec`, `seanchai.constraints`, the plugin's `core.lua` and this
   page, with byte vectors in `tests/test_constraints.py`.
6. An element the registry lacks (`constraint-element-unknown`) needs an
   entry in `seanchai.elements`, read from the defining document, a copy
   fetched for the purpose: its sources with the edition read, its checks in
   the shapes above, its depth and what it leaves unchecked, and an example
   payload. `tests/test_elements.py` holds every entry to its example, to the
   payloads breaking it and to `core.lua`, which reads the shapes the plugin
   is generated with.

## TS 29.272

TS 29.272 V19.6.0 is read completely: every AVP clause of clause 7.3, every
row of its information-element tables stating a condition, C, O or M, the
procedure clauses for what they state of one message, clause 7.1.4's
sessions, clause 7.2.2's Vendor-Specific-Application-Id and clause 7.4's
result codes.

| | |
|---|---|
| AVP clauses (clause 7.3, not its General and Void clauses) | 247 |
| with something to declare | 124, in 151 blocks |
| with nothing to declare | 123 |
| information-element rows | 73 blocks: the 45 C rows, of which 35 state a condition, and the M and O rows stating one: the IMSI's format in 12 requests, the 3GPP Vendor-Id of 12 answers' Experimental-Result, Terminal-Information's members in ULR and ECR, the Active-APN's of an explicit APN, ULR's SF-Provisional-Indication, ULA's and AIA's Error-Diagnostic, DSR's External-Identifier, RSR's Subscription-Data and Subscription-Data-Deletion, NOR's Context-Identifier |
| procedure clauses (5.2.1.1.3, 5.2.2.1.2, 5.2.2.1.3, 5.2.3.1.2, 5.2.3.1.3, 5A.2.2.1.2, 6.2.1.2) | 11 blocks |
| session handling (7.1.4) | 54 blocks: Auth-Session-State NO_STATE_MAINTAINED, no Authorization-Lifetime or Session-Timeout, in each of S6a's 16 and S13's 2 commands |
| Vendor-Specific-Application-Id (7.2.2) | 28 blocks, `text-only`, one per command |
| result codes (7.4.3, 7.4.4) | 28 blocks, a permanent and a transient one per answer |
| blocks | 350, Release 19's copy holding 345: 109 on an AVP wherever read, 43 within a grouped AVP, 193 within a command |
| readings | 382 |

| Rules | |
|---|---|
| `encoding`, a codec | 33: `digits` 15 (12 of them the IMSI), `e164-tbcd` 6, `plmn-id` 3, `ip-address` 3, `plmn-id-prefix`, `labels`, `apn`, `plmn-domain`, `epc-plmn-domain`, `time-zone` |
| `encoding element` | 45, naming 42 entries of the registry; 39 rules checked, 6 not ([above](#elements)) |
| `length` | 24: 10 in octets, 14 in digits |
| `range` | 27: Auth-Session-State in 18 commands, Extended-Max-Requested-BW-UL and -DL, and 7 of the AVP clauses |
| `exclude` | 34: Result-Code in each of 14 answers twice, none of clause 7.4's codes no IETF document the corpus holds numbers, and 6 of the AVP clauses and rows |
| `requires`, `present-if`, `absent-if`, `excludes` | 41, 13, 31, 14 |
| `default` | 10 |
| `bits` | 31: `only` 20 (19 flags tables' "Bits not defined in this table shall be cleared", five of them a block per release, and DSR-Flags on S7a), `clear` 5 (Supported-Monitoring-Events' S6t-only bits over S6a among them), `at-most-one` 3 (DSR-Flags), `at-least-one` 2 (Preferred-Data-Mode, and PDP-Type, whose bit 1 or 8 leaves out the element's PPP), `set` (Reachability-Type) |
| `members` | 8: `at-least-one` 5 (AESE-Communication-Pattern, Monitoring-Event-Configuration, EPS-Subscribed-QoS-Profile and AMBR in an APN-Configuration of a profile, IMEI in ECR's Terminal-Information), `only` 3 (Terminal-Information in ULR, NOR and ECR) |
| `unique` | 2: Context-Identifier and Service-Selection in APN-Configuration |
| `values` | 5: Reachability-Information in Monitoring-Event-Report, Maximum-Number-of-Reports for a last known location, Error-Diagnostic's values by the experimental code in ULA and AIA |
| `absent` | 37: Authorization-Lifetime and Session-Timeout in 18 commands, MIP6-Home-Link-Prefix in S6a's MIP6-Agent-Info |
| reading the request | 8: the IDA's EPS-User-State and EPS-Location-Information where the IDR's IDR-Flags asks for them, its Monitoring-Event-Config-Status beside the IDR's Monitoring-Event-Configuration, no success for an IDR asking the current location alone, the ULA's and UVA's subscription data unless the request skips it, and an AIA's no vectors and no success where both of the AIR's requested-info AVPs hold Re-Synchronization-Info |
| `text-only` | 83 |

The text-only rules are mostly conditions on the node, the interface, an
earlier message or a feature (an information element's "shall be present if
the MME supports SMS in MME", the IDA's Local-Time-Zone, which clause
5.2.2.1.2 has the MME or SGSN provide "if supported"), what an absent AVP
means where that is no value or differs between commands (MDT-User-Consent's
in ULA and IDR), conditions on an OctetString's value (PDP-Type's Non-IP,
two octets no condition compares), and clause 7.2.2's
Vendor-Specific-Application-Id, which the sentence forbids the sending node
and the NOTE has every command format print for intermediate agents not
complying with RFC 6733, so a message captured past such an agent may hold
it rightly. A row read as an answer's rule on its request is held to a
success's answer, `Result-Code = DIAMETER_SUCCESS`, where the row says
nothing of an error's: an IDA reporting one carries no EPS-User-State
though the IDR asked for it. Where a procedure answers with a result code
an earlier error may pre-empt (DIAMETER_UNABLE_TO_COMPLY for an IDR asking
the current location alone, clause 5.2.2.1.2), the rule says no success,
not which code. The rest a single message could show but no kind says: a
text value (Specific-APN-Info only for the wild card APN `*`, the default
APN not the wild card), a reference between two members (the profile's
Context-Identifier naming its default APN-Configuration), a count (an
Item-Number in each of more than one vector, clause 5.2.3.1.3), a mapping
between two bit tables (PLMN-RAT-Usage-Control's bits against
Access-Restriction-Data's), and the address type of Ext-PDP-Address against
PDP-Address's. Access-Restriction-Data's "Bits 11 and 12 are only used when
bit 4 is not set" says what they mean, not that they are clear.

A ULR's own flags say its sender: S6a/S6d-Indicator set is an MME's, clear
an SGSN's on S6d, and Node-Type-Indicator clear a single node, so clause
7.3.7's "An SGSN shall not set this bit" and "A standalone MME shall not
set this bit" are read on ULR-Flags itself. An Active-APN without
Specific-APN-Info is an explicitly subscribed APN's, which table
5.2.1.1.1/1 has carry Service-Selection, MIP6-Agent-Info and
Visited-Network-Identifier. MIP6-Home-Link-Prefix "not used in S6a/S6d" is
read within MIP6-Agent-Info for S6a's application alone (`; Application-ID:
16777251`), so SWx's MIP6-Agent-Info, which TS 29.273 reads as TS 29.272
does, keeps its prefix; User-State's RESERVED (5), "should not be used by
MME or SGSN over S6a/S6d", likewise within MME-User-State and
SGSN-User-State.

Three sentences disagree with the document. UVA-Flags' table copies
UVR-Flags' note, "cleared by the sending MME or SGSN and discarded by the
receiving CSS", though the CSS sends the UVA: the sentence binds no sender
of the AVP and is text-only. Clause 5A.2.2.1.2 answers an S7a/S7d IDR
holding no CSG-Subscription-Data with DIAMETER_ERROR_SUBS_DATA_ABSENT,
where that IDR carries VPLMN-CSG-Subscription-Data, at least one, and the
document defines no such code: text-only. Clause 7.3.41's NOTE gives
Max-Requested-Bandwidth-UL and -DL a range from 1, where clause 7.3.2 lets
one of the UE-AMBR's two be 0: the NOTE's range is read of the extended
bandwidths alone.

## TS 29.329

TS 29.329 V19.1.0 is read completely: every AVP clause of clause 6.3, the
notes under the commands of clause 6.1, clause 6.2's sentence on its
result codes and clause 7.1's features. Its commands' information-element
tables and its procedures are TS 29.328's, whose clauses are not read here.
Clause 8, the Sh-ee application Release 19 adds, is left out of the
extraction as unfinished (`edits/sources/TS29.329.toml`: its application id
"xx1" under an Editor's Note, command codes TS 29.230 table 5.1/1 gives
other commands, 5004 listed as its own experimental code), so neither its
commands nor its AVPs are in the corpus, and no reading of its clauses
(Report-Period "shall be present if reportMode is \"PERIODIC\"", clause
8.3.9) can be held to a message. Release 18's copy, V18.0.0, prints every
sentence read and holds all 18 blocks.

| | |
|---|---|
| AVP clauses (clause 6.3, not its overview) | 36 |
| with something to declare | 9, in 11 blocks |
| with nothing to declare | 27 |
| notes under the commands | 2, both on a feature |
| the result codes' clause, 6.2 | 1 sentence, a block per answer |
| the features' clause, 7.1 | 1 sentence, Update-Eff-Enhance's |
| blocks | 18: 8 on an AVP wherever read, 3 within a grouped AVP, 7 within a command |
| readings | 18 |

| Rules | |
|---|---|
| `encoding`, a codec | 1: `e164-tbcd` (MSISDN) |
| `encoding element` | 3, naming 3 entries of the registry; 2 rules checked, 1 not ([above](#elements)) |
| `requires` | 1: One-Time-Notification in SNR, on Data-Reference |
| `excludes` | 3: User-Identity's Public-Identity and MSISDN beside another identity, Feature-List's Update-Eff-Enhance without Update-Eff in Sh's feature list 1 |
| `absent-if` | 4: Result-Code in UDA, PUA, SNA and PNA, beside one of clause 6.2's codes in Experimental-Result's Experimental-Result-Code under the 3GPP Vendor-Id |
| `exclude` | 4: Result-Code in UDA, PUA, SNA and PNA, none of clause 6.2's codes RFC 6733 and the other IETF documents the corpus holds do not number too (4100, 4101, 5100 to 5108) |
| `default` | 1: Pre-paging-Supported |
| `bits` | 1: `only` (UDR-Flags) |
| `members` | 1: `at-least-one` (User-Identity) |
| `text-only` | 3 |

The text-only rules are the two notes making a second Data-Reference in PUR,
and any in PUA, depend on both nodes supporting Update-Eff-Enhance, and
Wildcarded-Public-Identity's "only contains a Wildcarded PSI", which a
Wildcarded IMPU's text does not differ from. User-Identity's "either ... or"
is read as one of its three members: at least one, and no Public-Identity or
MSISDN beside another. Update-Eff-Enhance "requires Update-Eff is
supported" is read within Supported-Features in Sh's messages (`;
Application-ID: 16777217`), its Vendor-Id 10415 and Feature-List-ID 1, each
feature by its name in table 7.1.1: a list naming Update-Eff-Enhance names
Update-Eff. Clause 6.2's "Result-Code AVP
shall be absent" is read of each answer as a path into its
Experimental-Result, under the 3GPP
Vendor-Id, the codes the clause lists, those it takes from TS 29.229 among
them; and as no Result-Code holding one of them, but 5002, 5008 and 5011,
numbers RFC 6733 gives codes of its own (DIAMETER_UNKNOWN_SESSION_ID,
DIAMETER_AVP_NOT_ALLOWED, DIAMETER_UNSUPPORTED_VERSION). Left unread:
Data-Reference's value 20, which the clause marks reserved without saying it
is not sent; Server-Name's "SIP-URL", for which no codec exists; User-Data's
Sh-Data XML, which the element registry names and checks nothing of, no
shape reading an XML schema; and table 6.3/2's note on a receiver not
understanding an AVP with the M bit, which is the base protocol's.

## TS 29.273

TS 29.273 V19.2.0 is read completely: every AVP clause of clauses 5.2.3,
7.2.3, 8.2.3 and 9.2.3, every row of the information-element tables of
clauses 4.1.2, 5.1.2, 6.1.2, 7.1.2, 8.1.2, 9.1.2 and 11.1.2 stating a
condition or a value, C, O or M, the procedure clauses for what they state
of one message, the session-handling clauses, clause 10's result codes,
the features tables and Annex D.2's DRMP. Release 18's copy, V18.6.0,
prints every sentence read and holds all 363 blocks: it prints a reference
to another 3GPP document as "3GPP TS" where Release 19 prints "TS", so a
quote ends before such a reference.

The document prints Diameter-EAP-Request and -Answer for SWa with no
application and for STa and SWd under 16777250, the Re-Auth-Request and
-Answer of SWa and STa under 16777250, and S6b's AA-Request and -Answer
twice under 16777272, each print with a body of its own; a block names the
print its table describes with `; Command-Section:`, as the corrections
attaching the tables do. The plugin holds a message to the print it breaks
least
([wireshark-plugin.md](wireshark-plugin.md#which-definition-a-message-is-held-to)),
so a rule of one print where another print of the procedure reads none
breaks nothing: SWd, which carries STa's first exchange through the 3GPP
AAA Proxy (clause 6.1.2.1.1), takes table 5.1.2.1/2's and 5.1.2.1/1's
rules on its own prints, and its session handling STa's. SWa's prints name
no application, so traffic under 16777250 is held to STa's and SWd's: a
rule on them holds of the print as read.

Where procedures share a print and a row holds of one, the message tells
them apart where it can. An ERP re-authentication's request sets DER-Flags'
ERP-Re-Authentication (clause 5.2.3.20) and its success carries the rMSK in
Key, with no EAP-Master-Session-Key or ERP-Realm (table 5.1.2.5.1/2): the
first exchange's EAP-Master-Session-Key is read where the request sets no
such bit, its ERP-Realm beside a Key with an EAP-Master-Session-Key. A
first exchange's DIAMETER_MULTI_ROUND_AUTH authorizing the SCM sets
DEA-Flags' TWAN-S2a-Connectivity-Indicator, an EAP round's none, so a row
allowed with "DIAMETER_SUCCESS or DIAMETER_MULTI_ROUND_AUTH, and
TWAN-S2a-Connectivity-Indicator is set" reads both. S6b's PMIPv6 and GTPv2
request carries MIP6-Feature-Vector (table 9.1.2.2.1/1), DSMIPv6's,
sharing the print, none (table 9.1.2.5.1/3): QoS-Resources after a
QoS-Capability, and MIP6-Feature-Vector after a success, are read where
the request holds one. A re-authentication's answer is the first
exchange's print: a row there allowing DIAMETER_SUCCESS alone, where the
first exchange's allows the SCM's DIAMETER_MULTI_ROUND_AUTH too, is
text-only, since reading it would refuse the first exchange's answer. The
first exchange is SWa's and STa's (clause 4.2.1) and carries the AAA
server's trust decision under 16777250: AN-Trusted's "For the STa case,
the value TRUSTED" is text-only, no message showing the STa case apart
from the value.

| | |
|---|---|
| AVP clauses (clauses 5.2.3, 7.2.3, 8.2.3 and 9.2.3, not their General, Void and grouping clauses) | 81 |
| with something to declare | 37, in 59 blocks (8.2.3.16's features table among them, the SAA's DCN-related data) |
| with nothing to declare | 44 |
| information-element rows | 208 blocks: the C rows, of which 147 state a condition, and the M and O rows stating one: Auth-Request-Type's and Re-Auth-Request-Type's value in 21 commands, the IMSI's digits in 5, SWa's AN-Trusted, Server-Assignment-Type's values, the SCM's requested and granted connectivity parameters, SWm's Terminal-Information, SIP-Authenticate's length; SWd's copies of STa's rows among them |
| procedure clauses | 9.1.2.1.3's relocated PDN GW, 9.1.2.5.1's P-CSCF restoration RAR, 9.1.2.5.2's RAA, 8.1.2.3.2's P-CSCF restoration PPR, in 4 blocks |
| session-handling clauses | 4.2.4's, 5.2.4's, 7.2.4's and 9.2.4's Auth-Session-State, never sent (41 blocks, SWa's 4 and SWd's 2 among them), and 8.2.4's Auth-Session-State NO_STATE_MAINTAINED and Authorization-Lifetime and Session-Timeout never sent (24) |
| result codes (10.3.1) | 26 blocks, one per answer |
| Annex D.2 | 1 block, DRMP |
| blocks | 363: 35 on an AVP wherever read, 35 within a grouped AVP, 293 within a command |
| readings | 399 |

| Rules | |
|---|---|
| `encoding`, a codec | 13: `digits` 5 (the IMSI in MAR, MAA, SAR, SAA and RTR), `plmn-domain` 3 (S6b's requests), `mac-address` 2 (HESSID, TWAG-UP-Address), `ip-address` 2 (TWAG-CP-Address, Served-Party-IP-Address), `labels` |
| `encoding element` | 6, naming 6 entries of the registry; 4 rules checked, 2 not ([above](#elements)) |
| `length` | 12: 7 in octets (SSID, HESSID, TWAG-UP-Address, SIP-Authenticate, S6b's Visited-Network-Identifier thrice), 5 in digits |
| `range` | 32: Auth-Request-Type in 18 commands, Re-Auth-Request-Type in 3 RARs, Auth-Session-State NO_STATE_MAINTAINED in SWx's 8, SWa's AN-Trusted UNTRUSTED, PDN-Type in TWAN-Connectivity-Parameters, Server-Assignment-Type |
| `exclude` | 28: Result-Code in each of 26 answers, none of clause 10.3's codes IETF RFC 6733 does not number too, Subscription-Id-Type, Server-Assignment-Type's codes no row names |
| `requires`, `present-if`, `absent-if`, `excludes` | 46, 48, 20, 4 |
| `values` | 4: Feature-List-ID 1 within a 3GPP Supported-Features, in each of the 4 applications' messages |
| `absent` | 58: Auth-Session-State in every SWa, STa, SWd, SWm and S6b command but the ASR, whose Auth-Session-State a 3GPP AAA Proxy may set (clauses 5.1.2.2.3, 7.1.2.4.3, 9.1.2.4.4), Authorization-Lifetime and Session-Timeout in SWx's 8 commands, MIP6-Home-Link-Prefix in S6b's MIP6-Agent-Info |
| reading the request | 17: SAA's Non-3GPP-User-Data as the SAR's Server-Assignment-Type asks, and its UE-Usage-Type as its Supported-Features do, S6b answers' QoS-Resources only after a QoS-Capability, MIP-Session-Key after an MIP-MN-HA-SPI, MIP6-Feature-Vector after a PMIPv6 or GTPv2 request's, no APN-Configuration for an emergency, no success for an RAR asking AUTHORIZE_AUTHENTICATE, STa's AA-Answer's MIP6-Feature-Vector only after the request's, the ERP answer's Key and the first exchange's EAP-Master-Session-Key by the request's DER-Flags (in STa's and SWd's prints), SWa's Mobile-Node-Identifier after a BBF Transport-Access-Type, SWm's subscription data not after an emergency request |
| `default` | 1: Access-Authorization-Flags in TWAN-Access-Info |
| `bits` | 20: `only` 14 (a flags AVP's NOTE that undefined bits are cleared, and the selected TWAN-Connection-Mode SCM or MCM in STa's and SWd's answer), `at-most-one` 3 and `at-least-one` 2 (the selected mode one of the two, RAR-Flags' P-CSCF restoration alone), `set` (SWx SAR's Emergency-Indication) |
| `members` | 18: `only` 7 (Trace-Info in an answer), `at-least-one` 11 (Trace-Info, Access-Network-Info's SSID, IMEI in STa's and SWd's Terminal-Information, the requested connectivity's Connectivity-Flags and PDN-Type, a PGW identity's address or host name) |
| `unique` | 1: WLAN-Identifier in TWAN-Access-Info, octet for octet |
| `text-only` | 124 |

Most text-only rules are conditions on the node, the subscription, the
operator's policy, the procedure or an earlier message ("shall be sent to
the 3GPP AAA Server if the UE has access priority", "if this information is
available in the user subscription", "was not set in the initial
Authentication and Authorization Answer"). A row whose condition is partly
the node's keeps the part a message shows where that part alone holds of
every message the row allows: "shall contain the MSISDN of the UE and shall
be sent if it is available" is read as the Subscription-Id's type, and
"shall be included only if the QoS-Capability AVP was received in the
authorization request and the authorization succeeded" as the request's
QoS-Capability. A "should" a clause qualifies with "if available"
(User-Location-Info-Time beside the WLAN Location Information, clauses
7.1.2.1.2 and 7.1.2.2.2) is text-only. Non-3GPP-User-Data "not empty" is
read as a member the body prints present, neither Trace-Info nor
Emergency-Info beside it, which may be what it downloads; that the P-CSCF
restoration's PPR holds an empty one no kind says. SWd's Full- and
Short-Network-Name "shall be set" beside a Visited-Network-Identifier
are text-only, the 3GPP AAA Proxy inserting the identifier into every
request it forwards (clause 6.1.2.1.1); STa's are read. The rest a single
message could show but the format cannot say: a text value (the
authentication scheme in SIP-Auth-Data-Item, EAP-AKA', ANID's "HRPD", the
reset PPR's "*" or IMSI prefix), a byte of a variable-length payload
(Location-Information's Code, Operator-Name's Namespace ID), a count
(SIP-Number-Auth-Items against the SIP-Auth-Data-Items, at most one
TWAN-Access-Info without a WLAN-Identifier), a length a scope cannot tell
apart (SIP-Authorization's XRES in the answer and RAND and AUTS in the
synchronization failure's request), an address family's bits (an IPv6
interface identifier's upper 64 bits zero), the QoS-Profile-Id deep in
QoS-Resources, and the flags of MIP6-Feature-Vector, whose clause 5.2.3.3
gives their masks in prose (PMIP6_SUPPORTED bit 40, ASSIGN_LOCAL_IP 43,
MIP4_SUPPORTED 44, OPTIMIZED_IDLE_MODE_MOBILITY 45, GTPv2_SUPPORTED 46)
where the corpus holds a bit table of RFC 5447's two and RFC 5779's three
only: a `bits` rule naming 43 to 46 names a bit no table holds. Five rows'
AVP the command's ABNF leaves to its `* [ AVP ]` and whose condition is the
node's (Transport-Access-Type in STa's and SWd's request,
IMEI-Check-In-VPLMN-Result, AMBR in STa's AA-Answer, AN-Trusted in S6b's
Diameter-EAP-Answer) are read where the document reads the AVP.
ME-Identity-Check-Request's and -Answer's rows (clause 11) are TS 29.272's
commands, which this file does not print, and TS 29.272's file reads them.

Clause 10.3.1's "the Result-Code AVP shall be absent" beside one of its
codes in Experimental-Result is read in SWx's four answers, whose bodies
leave Result-Code optional; the other answers print `{ Result-Code }`,
which the sentence contradicts, and read only the exclusion of clause
10.3's codes RFC 6733 does not number too (5450 to 5456, 5554). Two other
sentences disagree with what the corpus prints: STa's trace rows list
"Trace-Depth-List", and leave Trace-NE-Type-List out where TS 29.272's
Trace-Data, which they re-use, requires it, so no reading of Trace-Data's
members is added to TS 29.272's; and SWm's table 7.2.3.1/1 types
Mobile-Node-Identifier OctetString against clause 5.2.3.2's UTF8String, a
pinned `table-row-mismatch`. TS 29.272's readings within Active-APN hold
where this document re-uses it ([Precedence](#precedence)), so the HSS
restoration request's Active-APN rows are read there.

The session-handling clauses' "shall not include the Auth-Session-State
AVP" (clauses 5.2.4, 7.2.4, 9.2.4, and 4.2.4's SWa, the same as STa's) and
"Neither the Authorization-Lifetime AVP nor the Session-Timeout AVP shall
be present" (clause 8.2.4) are read as `absent` in each command of the
interface, a body admitting the AVP through its `* [ AVP ]`;
Non-3GPP-User-Data's Session-Timeout is that grouped AVP's member, not the
command's. Left unread: DER-Flags' and DEA-Flags' "This bit is only
applicable to the TWAN authentication and authorization procedure", which
says what a bit means, not when it is set; the detailed-behaviour clauses'
result codes, which are what a node answers with, not a condition on an
AVP; the C rows saying only what an AVP holds when present ("If present,
this IE shall contain the untrusted non-3GPP access network technology
type"); and SWx's NOTE on Vendor-Specific-Application-Id, which says why
the commands print it and forbids nothing.

## TS 29.212

TS 29.212 V19.1.0 is read for each of its applications, Gx, Gxx, Sd, St and
S15: every AVP clause of clauses 5.3, 5a.3, 5b.3, 5c.3 and E.6.3, the
re-used AVPs' descriptions of tables 5.4.0.1, 5a.4.0.1, 5b.4.0.1, 5c.4.1.1
and E.6.4.1.1, the supported-features and result-code clauses, 5.4.2's
Flow-Description, the messages' clauses' application ids (5.6.1, 5a.6.1,
5b.6.1, 5c.6.1, E.6.6.1), and the procedure clauses of clauses 4.5, 4a.5,
4b.5, 4b.5a, 4c.4 and E.5 for what they state of one message. Release 18's
copy, V18.2.0, prints every sentence read and holds all 209 blocks; the
Release 11 copy, held for citations, is offered none. The re-used AVPs'
tables of Gxx, Sd, St and S15 mostly repeat Gx's descriptions, which a
block on the AVP wherever read, or within the document's own grouped AVP,
already reads.

The document has no information-element tables, and prints CC-Request,
CC-Answer, RA-Request and RA-Answer for Gx, Gxx, Sd and S15 with no
application id in their headers, and TS-Request and TS-Answer for Sd and
St: a block names the print's application with `; Application-ID:`, which
the application scope covering its clause gives it, Gx's in clause 5.6,
Gxx's in 5a.6, Sd's in 5b.6, St's in 5c.6, S15's in E.6. A PCC rule's
Charging-Rule-Definition modifies the one installed before it, keeping what
it omits (clause 5.3.4), and an ADC rule's ADC-Rule-Definition likewise
(clause 5b.3.3), so a condition on their members is `text-only`; what they
may never hold is read (a PCC rule's QoS-Information names no bearer,
clause 4.5.5.0).

| | |
|---|---|
| AVP clauses (clause 5.3, not its General and Void clauses) | 130 |
| with something to declare | 63, in 108 blocks |
| with nothing to declare | 67 |
| Gxx's, Sd's, St's and S15's AVP clauses (5a.3, 5b.3, 5c.3, E.6.3) | 19, 5 with something to declare, in 11 blocks |
| re-used AVPs' descriptions (tables 5.4.0.1, 5b.4.0.1) | 12 blocks |
| supported features, Flow-Description, result codes, application ids (5.4.1, 5.4.2, 5.5.1, 5a.4.1, 5b.4.1, 5b.5.1, 5c.4.2, E.6.4.2, 5.6.1 to E.6.6.1) | 29 blocks |
| procedure clauses (4.5.1 to 4.5.30, 4a.5.1 to 4a.5.10.4, 4b.5.1.1 to 4b.5a.2, 4c.4.1 to 4c.4.4, E.5.3.1 to E.5.3.2.2) | 49 blocks |
| blocks | 209: 61 on an AVP wherever read, 46 within a grouped AVP, 102 within a command |
| readings | 245 |

| Rules | |
|---|---|
| `encoding`, a codec | 12: `ip-address` 6 (AN-GW-Address, CoA-IP-Address, Routing-IP-Address, TDF-IP-Address, HeNB-Local-IP-Address, UE-Local-IP-Address), `ip-filter` 6 (`out` Flow-Description wherever read and in Routing-Filter, `out from any to assigned` TFT-Filter and Packet-Filter-Content, `out from any port-or-range to assigned port-or-range` Flow-Description in Flow-Information, `from any assigned port to any assigned port` Tunnel-Header-Filter) |
| `encoding element` | 5, naming 5 entries of the registry, all checked ([above](#elements)) |
| `length` | 1: ToS-Traffic-Class, 2 octets |
| `range` | 19: Auth-Application-Id in the 13 commands printing it, Extended-APN-AMBR-DL and -UL at least 4294968, UDP-Source-Port and TCP-Source-Port 0 to 65535, Priority-Level 1 to 15, Routing-Filter's Flow-Direction BIDIRECTIONAL |
| `exclude` | 2: Event-Trigger's obsolete values 8, 9, 10, 38 and 41, Sd's Usage-Monitoring-Level PCC_RULE_LEVEL |
| `requires`, `present-if`, `absent-if`, `excludes` | 13, 59, 29, 2 |
| `values` | 7: NO_EVENT_TRIGGERS alone in Gx's, Gxx's and Sd's CCA and RAR, St's address notification's Request-Type 1 |
| reading the request | 3: the initial CCA's Supported-Features beside the CCR's, Sd's and St's TSA's none without the TSR's |
| `default` | 4: QoS-Negotiation, Pre-emption-Capability, Pre-emption-Vulnerability, Usage-Monitoring-Level in Gx's messages |
| `bits` | 2: `set` and `clear`, an ADC rule's ToS-Traffic-Class mask 11111100 |
| `members` | 12: `at-least-one` 10 (TDF-Information's realm and host or address, Conditional-APN-Aggregate-Max-Bitrate's bandwidths and conditions, the Flow-Description and Flow-Direction of Application-Detection-Information's Flow-Information, Tunnel-Information's length or filter, CS-Service-Resource-Report's operation, identifier and cause), `only` 2 (an ADC rule's QoS-Information, its maximum bandwidths, and Sd's Application-Detection-Information's Flow-Information) |
| `text-only` | 95 |

Most checked rules are clause 5.3.7's: an event trigger a CCR reports, of
any of its Event-Trigger AVPs, with the AVP the value's description says it
is sent with (SGSN_CHANGE's 3GPP-SGSN-Address or 3GPP-SGSN-IPv6-Address,
TAI_CHANGE's 3GPP-User-Location-Info, USAGE_REPORT's
Usage-Monitoring-Information), 29 conditions, and the procedures'. Gx's
initial CCR carries a Subscription-Id but for xDSL or an emergency
session's IMEI(SV) (clauses 4.5.1, 4.5.15.2.1), Gxx's the AN-GW-Address and
a Subscription-Id likewise (4a.5.1, 4a.5.12.1.1), Sd's TS-Request the UE's
IPv4 address or IPv6 prefix (4b.5.1.1), as Sd's initial CCR, the
unsolicited TDF session's, does (4b.5a.2), St's initial TS-Request, its
Request-Type 0, the address and its ADC rules (4c.4.1), and S15's initial
CCR the HeNB-Local-IP-Address (E.5.3.1). An addition's CCR carries
QoS-Information (4.5.1, 4a.5.1), a Gxx deletion's every
Packet-Filter-Information its identifier; a CCA rejecting with one of
clause 4.5.1's three codes provisions no PCC rule; an Event-Trigger
NO_EVENT_TRIGGERS stands alone (4.5.3, 4a.5.8, 4b.5.3); a removed access's
CCA or RAR names its IP-CAN-Type (4.5.25.2.3), an unavailable or available
again access's CCR its IP-CAN-Type and reason (4.5.25.2.7). A CCR's every
Usage-Monitoring-Information, a report, holds its key and usage (4.5.17.0,
4b.5.7.1), a threshold its key (4.5.16), and a disabling one its key and
nothing else (4.5.17.3). A failure's rule report in a Gx RAA, an Sd TSA or
RAA and an St TSA names its rules, code and status (4.5.12, 4b.5.5, 4c.4.3),
an St TNR's its code and INACTIVE; an address event's Event-Report-Indication
in Sd's RAR and St's TSR carries the address (4b.5.8, 4c.4.4). Each
application's Auth-Application-Id is its own in each command printing it,
and Sd's and St's TS-Request and TS-Answer hold it in their
Vendor-Specific-Application-Id (5b.6.1, 5c.6.1). Each Gx and Sd answer's
Experimental-Result has the 3GPP vendor (5.5.1, 5b.5.1). A deletion's
Packet-Filter-Information "only the Packet-Filter-Identifier" is read on the
CCR as the AVP absent where it holds another member, a path into it, since
its own scope does not see the command's Packet-Filter-Operation.

Flow-Description is clause 5.4.2's `ip-filter` within Flow-Information:
`out`, the source an address or `any`, the destination an address or
`assigned`, each port one port or one range. Wherever else the document
reads it, in Routing-Filter among them, whose clause 5.3.72 lets it read
"permit out ip from any to any", it is held to the clause's other
restrictions, `out` with no options and no `!`; that unscoped block also
sets aside TS 29.214's reading, which refuses `assigned`. TFT-Filter and
Packet-Filter-Content take `any` and `assigned` as clauses 5.3.13 and
5.3.54 set them, the source's and the destination's, and
Tunnel-Header-Filter one port at each end (5.3.34). An Sd CCR's
Framed-IPv6-Prefix is the TDF's full address, prefix length 128 (table
5b.4.0.1), the registry's TS 29.212 entry; Sd's Usage-Monitoring-Level is
SESSION_LEVEL or ADC_RULE_LEVEL, and Application-Detection-Information's
Flow-Information holds its Flow-Description and Flow-Direction alone, read
in Sd's messages (`; Application-ID: 16777303`), while clause 5.3.61's
default PCC_RULE_LEVEL is read in Gx's alone; an ADC rule's QoS-Information
holds the maximum bandwidths, the extended ones among them, as clause
4b.5.1.3 says, where table 5b.4.0.1 names only the basic two.

The text-only rules are mostly conditions on the node, the bearer binding,
the subscription or an earlier message ("For GPRS scenarios where the
bearer binding is performed by the PCRF", "If ... not been previously
provided, its absence shall indicate", "the PCRF supports Rel-8 Gxx
functionality"), the members of a Charging-Rule-Definition or an
ADC-Rule-Definition (Flows "if and only if AF-Charging-Identifier AVP is
also present", which a modification keeping the identifier provided before
may break), a Gx initial CCR's address, which an IPv4 address allocated
later or a Non-IP PDN connection leaves out, a modification's
QoS-Information, which the UE's request decides, an S15 allocation's CCR,
no AVP telling it apart, and defaults resting on what was supplied before.
St's TSA is held to its request's Request-Type 0, "0 (initial request)"
(clause 5c.2). The rest a single message could show but the format cannot
say: which of a CCR's Charging-Rule-Reports are a lost bearer's, a text's
start (an NBIFOM Routing-Rule-Identifier's "PCEF" or "PCRF"), digits as
text where a sibling's type says IMEISV, User-Equipment-Info-Extension's
members, which RFC 8506 defines and this document does not print,
Granted-Service-Unit's and Used-Service-Unit's re-used members, which a
`members` rule cannot name beside the Monitoring-Time their `* [ AVP ]`
admits, and whose "one of the CC-Input-Octets and CC-Output-Octets" clause
4.5.16's "the uplink and downlink volume" threshold contradicts, the rule
reports' "Multiple instances ... shall be used" where codes differ, a count
(the one Charging-Rule-Name or QoS-Rule-Name beside a Content-Version, whose
base names are read absent), non-GBR QCIs, which are TS 23.203's, and
Max-PLR-DL's and Max-PLR-UL's range 0 to 1000, which the clauses read of an
Unsigned32 and table 5.3.0.1, as the corpus prints it, types Float32: the
document disagrees with itself in V18.2.0, V19.1.0 and Release 20's V20.0.0
alike, and implementations split (Wireshark's dictionary types the AVPs
Float32, freeDiameter's Unsigned32, changing the table's type), so the
corpus keeps the table's type and the range is read of neither. No linter
rule reads the type a plain AVP's clause states, so the disagreement is
recorded here and in the blocks, not as a finding. Clause 5.3.27's "The
Event-Trigger AVP with value IP-CAN-CHANGE shall be provided together with
the IP-CAN-Type AVP" is read as clause 5.3.7's IP-CAN_CHANGE is, the
event's IP-CAN-Type, not as no IP-CAN-Type without the event, clause
5.3.7's NBIFOM event triggers carrying one too; clause 5.3.53's
unconditional "shall include the Flow-Direction AVP" is text-only, beside
its sentence excusing a Flow-Information holding only a
Packet-Filter-Identifier; clause 5.3.40 names Extended-APN-AMBR-DL for the
uplink, citing 5.3.135's Extended-APN-AMBR-UL; and clauses 5.3.105 and
5.3.128 give the basic bandwidths "lower or equal to 2^32-1 bps" and the
extended ones "higher than 2^32 bps", leaving 2^32 itself to neither, where
clause 4.5.30 says "higher than 2^32-1 bps": the extended AVPs' range is
4.5.30's. Left unread: the sentences saying a value or an AVP is
"applicable" or "not applicable" to an interface or a release, with no
"shall" (Session-Release-Cause's values "to be used by Sd only",
Charging-Rule-Install's IP-CAN-Type "Only the 3GPP-EPS and Non-3GPP-EPS
IP-CAN type values are applicable in this release", Max-PLR's "only
applicable for PCC rule with QCI=1"), but table 5b.4.0.1's restrictions of
Gx's grouped AVPs in Sd's messages; "is provided" and "may ... when"
sentences (the NBIFOM event triggers' IP-CAN type, Quota-Consumption-Time
beside a CC-Time, Annex B's modification of a TFT adding filters without
an identifier, which keeps a Gx or Gxx modification's
Packet-Filter-Information from being held to one); and the M-bit and vendor
settings of table 5.4.0.1, which the AVP table's flags already state.

## TS 29.214

TS 29.214 V19.3.0 is read for Rx: every AVP clause of clause 5.3, the
re-used AVPs' descriptions of table 5.4.0.1, clause 5.1's application id,
5.4.1's supported features and 5.5.1's result codes, and the procedure
clauses of clause 4.4 for what they state of one message. Release 18's
copy, V18.4.0, holds 92 of the 93 blocks: it prints no clause 4.4.6.10,
whose PC-Session-Recovery-Status Release 19 added. Release 19 prints that
clause's heading as a paragraph of clause 4.4.6.9, whose text it is read
as.
The document has no information-element tables, and prints each command once
under 16777236. Service information modifies what was provisioned before it
(clauses 5.3.16 and 5.3.18), and an AA-Request is the session's first only
where its optional Rx-Request-Type says INITIAL_REQUEST, so what an initial
or a modifying request must carry is `text-only`.

| | |
|---|---|
| AVP clauses (clause 5.3, not its General clause) | 82 |
| with something to declare | 31, in 45 blocks |
| with nothing to declare | 51 |
| re-used AVPs' descriptions (table 5.4.0.1) | 7 blocks |
| protocol, supported features, result codes (5.1, 5.4.1, 5.5.1) | 5 blocks |
| procedure clauses (4.4.1, 4.4.2, 4.4.4, 4.4.6.6, 4.4.6.7, 4.4.6.9, 4.4.7, 4.4.9, 4.4.10, 4.4.12) | 35 blocks |
| Annex B.1.1's media component numbers | 1 block |
| blocks | 93: 42 on an AVP wherever read, 12 within a grouped AVP, 39 within a command |
| readings | 108 |

| Rules | |
|---|---|
| `encoding`, a codec | 2: `ip-filter from any port to any` (Flow-Description), `base64` (GLI-Identifier) |
| `encoding element` | 6, naming 6 entries of the registry, 5 checked ([above](#elements)) |
| `length` | 2, in octets: ToS-Traffic-Class 2, GLI-Identifier at most 200 |
| `range` | 9: Auth-Application-Id 16777236, the 8 extended bandwidth AVPs at least 4294968 |
| `requires`, `present-if`, `absent-if`, `excludes` | 6, 22, 3, 1 |
| reading the request | 2: the restoration AAA's Auth-Session-State, the initial AAA's Supported-Features beside the AAR's |
| `default` | 9 |
| `values` | 4: Auth-Session-State NO_STATE_MAINTAINED in the restoration AAR and AAA, Media-Component-Number 0 for AF signalling, an update AAR's Specific-Action one-time |
| `bits` | 3: `at-most-one` (Pre-emption-Control-Info), `set` and `clear`, ToS-Traffic-Class's mask 11111100 |
| `members` | 4: `only` 3 (Acceptable-Service-Info's Media-Component-Description, Sponsored-Connectivity-Data's Granted- and Used-Service-Unit), `at-least-one` (Wireline-User-Location-Info) |
| `text-only` | 44, 2 of them the Supported-Features Vendor-Id |

Most checked rules are clause 5.3.13's: a value a RAR reports, of any of its
Specific-Action AVPs, with the AVP its description says it carries (the
Flows of seven bearer and credit events, IP-CAN_CHANGE's IP-CAN-Type,
PLMN_CHANGE's 3GPP-SGSN-MCC-MNC, CHARGING_CORRELATION_EXCHANGE's
Access-Network-Charging-Identifier), with clause 4.4.6.6's usage report in
the Sponsored-Connectivity-Data's Used-Service-Unit and 4.4.6.10's
PC-Session-Recovery-Status. Clause 4.4.7's P-CSCF restoration AAR, which
its Rx-Request-Type PCSCF_RESTORATION tells apart, carries Auth-Session-State
NO_STATE_MAINTAINED, and the IMSI and APN where it holds no address, and its
AAA the same Auth-Session-State; clause 4.4.12's AAR, which its MPS-Action
AUTHORIZE_AND_ENABLE_MPS_FOR_AF_SIGNALLING tells apart, an MPS-Identifier, a
Media-Component-Description and the UE's address, and among its
Media-Component-Descriptions one numbered 0 and a Flow-Description, read on
MPS-Action so that the paths read any of them (which one holds the filter no
path binds); a restoration AAR holding no IMSI holds an address, read on
Framed-IP-Address, since a rule on Subscription-Id reads each instance, an
MSISDN's too. An AAR subscribing to ACCESS_NETWORK_INFO_REPORT carries
Required-Access-Info (4.4.6.7), an AAR's Reservation-Priority is DEFAULT
where absent (4.4.1), an update's Specific-Action only a one-time value,
ACCESS_NETWORK_INFO_REPORT (12) or Release 19's CN_HEALTH_MONITOR (21)
(5.3.13), and a RAR's IP-CAN_CHANGE its IP-CAN-Type, or an MA PDU session's
in MA-Information, which a later ATSSS report carries alone (Annex E.4).
Clause 4.4.10 holds every extended bandwidth AVP to more than 2^32-1 bit/s,
at least 4294968 kbit/s. Wireline-User-Location-Info holds the Cable or the
BBF location, an HFC-Node-Identifier never beside a GLI-Identifier and a
Line-Type only beside one (5.3.75); GLI-Identifier is `base64`; the AF's
Framed-IPv6-Prefix is the registry's TS 29.214 entry, the UE's full address
with a prefix length of 128 (table 5.4.0.1). Flow-Description is clause
5.3.8's `ip-filter from any port to any`, the restrictions of TS 29.212's
`ip-filter` with no `assigned` and the source port one port: "Lists or
ranges shall not be used" stands in the source port's item, and "a single
IP flow" is no count of the destination's ports, ETSI TS 183 017 clause
7.3.17 printing it beside "Source and destination port (list or ranges)"
as this clause's address masks and omitted ports stand beside it.

The text-only rules are mostly conditions on an earlier message, the
session or a feature ("if the PCRF has previously requested to be updated
with this information", "When the Extended-Max-Requested-BW-NR feature is
supported", "Non-one-time-specific-action value(s) may only be provided in
the initial AA-Request"), what the PCRF has available, and texts no kind
reads: Codec-Data's lines, Service-URN's and FLUS-Identifier's starts,
3GPP-User-Location-Info's layout chosen by its type, User-Equipment-Info's
digits, and HFC-Node-Identifier's CableLabs layout, which no reference of
the corpus names, a later AAR, the time it waits and its service
information (Retry-Interval, 4.4.1; an AAR only after the previous one's
answer, 4.4.2), what the PCRF received over Gx (4.4.9's several
Content-Versions), a component's number kept across two SDP offers (Annex
B.1.1), the server's FILTER_RESTRICTIONS for a filter no condition tests,
and the AAA's Supported-Features M bit and common features (5.4.1). A
Sponsored-Connectivity-Data's Granted-Service-Unit and Used-Service-Unit are
not held to one of CC-Input-Octets and CC-Output-Octets: the units are TS
29.212's usage monitoring's, whose clause 4.5.16 sets "the uplink and
downlink volume" as a threshold. A RAR's location report carries
ACCESS_NETWORK_INFO_REPORT (clause 4.4.6.7), but a RAR reporting a bearer's
release carries the location too, under its own Specific-Action, so that is
`text-only`.

The document names its extended bandwidth AVPs otherwise than it defines
them: clauses 5.3.14, 5.3.15, 5.3.32, 5.3.33 and 5.3.41 to 5.3.44 print
Extended-Max-Requested-Bandwidth-DL and the like for clauses 5.3.52 to
5.3.59's Extended-Max-Requested-BW-DL, clause 5.3.44 opens "The
Min-Desired-Bandwidth-DL AVP (AVP code 546)" for the UL AVP, and clause
5.3.24 names Extended-Max-Requested-BW-DL twice where the second is the UL.
Left unread: the M-bit and vendor settings of table 5.4.0.1; the sentences
saying a value or an AVP is "applicable" or "not applicable", with no
"shall" (Framed-IP-Address's values 0xFFFFFFFF and 0xFFFFFFFE, NID's "only
applicable in 5GS"); "will" and "may" sentences (Acceptable-Service-Info's
"only the Media-Component-Description AVP will be provided"); the procedure
clauses repeating clause 5.3.13's value descriptions (4.4.6.3, 4.4.6.4,
4.4.6.5, 4.4.6.9); and Annex A's P-CSCF procedures and Annex E's
interworking with 5GS, which state what an IMS node or a PCF does, not
what an Rx message carries.

## TS 32.299

TS 32.299 V19.0.0 is read completely for Rf and Ro: clause 6's procedure
clauses for what they state of one message, clause 7.1's Diameter AVPs and
every AVP clause of clause 7.2's 3GPP specific AVPs, 7.2.0A to 7.2.255,
and Annex B's overload control AVPs. Clauses 7.3 to 7.5 only list other
documents' AVPs. Release 18's copy, V18.0.0, prints every sentence read and
holds all 103 blocks. The commands' information-element tables of clauses
6.2 and 6.4 give each member's category, OM, OC, M, O or `-` for an AVP
3GPP does not use, which the corpus already reads
([grammar.md](grammar.md#information-elements)), so no block restates
them; two descriptions state more, read at their tables: the CCA's
G-S-U-Pool-Reference "Only used in ECUR and SCUR", and the CCR's
Announcement-Information "Not used in CCR", which its category OC
contradicts. Rf's commands print once under 3 and Ro's once under 4.

| | |
|---|---|
| clause 6's procedure clauses and tables (6.1.1, 6.1.2, 6.3.3 to 6.3.5, 6.4.2, 6.4.3, 6.5.1.1, 6.5.3, 6.5.4, 6.5.10.3) | 18 blocks |
| clause 7.1's AVP clauses (not its General and Void clauses) | 17 |
| with something to declare | 9, in 15 blocks |
| clause 7.2's AVP clauses, 7.2.0A to 7.2.255 (not Void) | 417 |
| with something to declare | 57, in 69 blocks |
| Annex B's overload control AVPs (B.2.1 to B.2.3) | 1 block |
| blocks | 103: 50 on an AVP wherever read, 18 within a grouped AVP, 35 within a command |
| readings | 126 |

| Rules | |
|---|---|
| `encoding`, a codec | 4: `e164-tbcd` 3 (ISUP-Location-Number, MSC-Address, VLR-Number), `labels` (Called-Station-Id) |
| `encoding element` | 8, naming 8 entries of the registry, 3 checked ([above](#elements)) |
| `length` | 1: SM-Status, 1 octet |
| `range` | 7: Acct-Application-Id 3 in ACR and ACA, Auth-Application-Id 4 in CCR, CCA and RAR, Vendor-Specific-Application-Id's Vendor-Id 10415, PDP-Address-Prefix-Length 0 to 128 |
| `exclude` | 1: a Multiple-Services-Credit-Control's Reporting-Reason, none of the values one quota type's Used-Service-Unit carries |
| `requires`, `present-if`, `absent-if`, `excludes` | 7, 7, 2, 11 |
| `absent` | 6: Reporting-Reason at the level of each command |
| `values` | 11: an ACA's Accounting-Record-Type and a CCA's CC-Request-Type the request's, in clauses 6.1.1, 6.1.2 and 6.3.3 to 6.3.5's flows |
| reading the request | 13: the 11 `values` rules, and the initial ACA's and CCA's Supported-Features with DIAMETER_ERROR_FEATURE_UNSUPPORTED |
| `default` | 14 |
| `members` | 4, each `at-least-one`: Address-Domain, Basic-Service-Code, Offline-Charging's Multiple-Services-Credit-Control's Rating-Group, 3GPP-OC-Specific-Reduction's rating group or request type |
| `text-only` | 45, one of them the Supported-Features Vendor-Id |

Most checked rules are defaults ("If this AVP is not present, this means
...") and clause 7.2.175's Reporting-Reason: never at command level, sent
only beside a usage report, a Used-Service-Unit always with its reason,
RATING_CONDITION_CHANGE with a Trigger. A CCR's PDP-Context-Type only in
the initial CCR (clause 7.2.138), a CCR's Multiple-Services-Credit-Control
holding no Quota-Holding-Time, which "may only occur in a CCA command"
(clause 7.2.160), and a CCR reporting CHANGE_OF_UE_PRESENCE_IN_PRESENCE_
REPORTING_AREA carrying the area's identifier and status in its
PS-Information (clause 7.2.236) are read on the CCR through paths into the
AVPs holding them, and RFC 4006's Final-Unit-Indication with TERMINATE
holding nothing else (clause 6.5.3) through paths from the AVP itself. The
flows of clauses 6.1.1, 6.1.2 and 6.3.3 to 6.3.5 give an answer the record
or request type of its request, held to a success's answer where the step
says nothing of an error's; the refund's answer carries "the related result
code", whatever it is. Clause 6.5.10.3 reads an "initial" request as an
ACR[Start] or a CCR[Initial], whether an event's is one it does not say;
the request's Supported-Features, which the ACR's and CCR's ABNF leave to
their `* [ AVP ]`, no rule reads, and an answer with
DIAMETER_ERROR_FEATURE_UNSUPPORTED answers a request holding one.

The rest are read where the document prints the AVPs they bind. Each
Multiple-Services-Credit-Control of an Offline-Charging holds its
Rating-Group and not both Quota-Consumption-Time and Time-Quota-Mechanism
(clause 7.2.121), each instance read through paths from it; the clause lists
what the AVP carries for offline control, not that its `* [ AVP ]` admits
nothing else. A threshold is sent beside a Granted-Service-Unit of its unit
(clauses 7.2.229, 7.2.240, 7.2.243), within Multiple-Services-Credit-Control,
and a Quota-Consumption-Time or Time-Quota-Mechanism beside a time quota
(7.2.159, 7.2.228) in a CCA's own Multiple-Services-Credit-Control, since
Offline-Charging's sets the mechanism with no quota granted. A CCA answering
an EVENT_REQUEST, IEC's, holds no G-S-U-Pool-Reference, ECUR's and SCUR's
alone (table 6.4.3.1); a Trigger beside RATING_CONDITION_CHANGE names a
Trigger-Type, an empty one resetting the triggers instead (6.5.1.2); a
Basic-Service-Code holds one of Bearer-Service and Teleservice; the
Service-Information of Ro's CCR and CCA holds no Subscription-Id, "only
used on the Rf interface"; and Acct-Application-Id is 3 in the ACR and ACA,
Auth-Application-Id 4 in the CCR, CCA and RAR. Clause 7.1.11 has the
Result-Code operate as RFC 6733 and RFC 4006 describe it: the document's
own blocks on the ACA's and CCA's Failed-AVP set aside RFC 6733's reading of
every answer ([Precedence](#precedence)), so the ACA and the CCA read its
seven codes again beside DIAMETER_RATING_FAILED, as RFC 4006's and RFC
8506's CCA do. A CCR's Presence-Reporting-Area-Information holding both the
identifier and the status no path binds, the PS-Information holding
several.

The text-only rules are conditions on the SIP signalling, the charging
domain, the node's configuration or an earlier message (Called-Asserted-
Identity "when the P-Asserted-Identity SIP header field is available",
User-Equipment-Info's digits for PS or IMS charging, Refund-Information "if
previously received in CCA for IEC", the client's default
Quota-Holding-Time, the server's support of Supported-Features, the
features a request is constructed with, the Envelope's reports an earlier
Envelope-Reporting asked for, POOL_EXHAUSTED in the
Multiple-Services-Credit-Control "if all quota types use the same pool"),
texts, orders and comparisons no kind reads (User-Name's NAI,
Time-Indicator below the granted quota, Service-Context-Id's form, the
Envelopes' and
Transit-IOI-List's chronological order, Message-Body's Content-Type,
Variable-Part-Value's digits by its Variable-Part-Type), what an absent AVP
means where that is no value or no `default` holds alone
(PDP-Address-Prefix-Length's 64, an IPv6 PDP-Address's alone; a CCA's
absent Quota-Consumption-Time, which within Offline-Charging's
Multiple-Services-Credit-Control is the Offline-Charging AVP's own;
Time-Indicator's), and NOTEs, which state no requirement (SDP-Media-
Component's charging identifiers, Trigger-Type's values not used together).
Authorised-QoS's and Subscriber-Role's "This AVP is not used" and
SM-Discharge-Time "only used in scenarios in which the delivery of the
Delivery-Report ... is being charged" are text-only. The values for all
quota types of clause 7.2.175 "are used directly" in the
Multiple-Services-Credit-Control, which says what they mean, not that a
Used-Service-Unit never carries one; UNI-PDU-CP-Only-Flag's default is the
value 0 an absent AVP means, the clause's "when Control Plane CIoT EPS
Optimization is enabled" qualifying both.

The document is wrong in places the corpus reads around: clause 7.2.171Ab
holds Related-Trigger to a Trigger-Type "indirect change condition" clause
7.2.236 does not define (it is Change-Condition's 34, clause 7.2.37), read
`text-only`; clause 7.2.236 prints "74 CHANGE_IN_SERVING_PLMN_RATE_CONTROL"
at the end of value 73's description paragraph, which a correction inserts as
Trigger-Type's value 74, and clause 7.2.207 prints SM-Message-Type's value 2
"2. SM Service Request", which an input patch reads as the others are read;
clause 7.2.46B's heading and text name CSG-Membership-Indication
CSG--Indication; clause 7.2.138's PDP-Context-Type "shall only be present
in the CCR[Initial]", which the CCR's block reads, where table 7.2.0.1 marks
it for the ACR too, so no ACR's is read absent; table 6.4.2.1 puts
Announcement-Information OC in the CCR beside "Not used in CCR.", which
table 7.2.0.1, marking it for the CCA alone, agrees with, read `text-only`;
clause 7.2.103's "application-sdp" is no media type, read `text-only`;
clause 7.2.35B types Civic-Address-Information OctetString where table
7.2.0.1 types it UTF8String; clause 6.5.1.3 names
RATING_CONDITION_CHANGE RATING_CONDITION_ANGE, beside the sentences clause
7.2.175 states and the file reads there; and clause 6.5.5 names
DIAMETER_AUTHORIZATION_REJECTED DIAMETER-AUTHORIZATION-REJECTED. Left
unread: "is" sentences (Traffic-Data-Volumes' 3GPP-Charging-Id "is
included when charging per IP-CAN session is active", Served-Party-IP-
Address "only provided by the P-CSCF"); the sentences saying a value is
"only applicable" (Trigger-Type's 24 and 62, the CCR table's 3GPP-RAT-Type);
the Rating-Group's "unique Rating Group value" of each quota, which RFC 4006
states; the result codes' descriptions of clause 7.1.11 but
DIAMETER_RATING_FAILED's Failed-AVP and the Result-Code's operating as RFC
6733 and RFC 4006 describe it, and the result codes clause 6's
procedures answer with, which are what a node answers, not a condition on
an AVP; and clause 6.3.7.1's Tariff-Change-Usage "not used directly within
the Multiple-Services-Credit-Control AVP", which the command's struck member
already says.

## TS 29.338

TS 29.338 V19.3.0 is read completely for S6c and SGd/Gdd: clause 4's common
aspects, every AVP clause of clauses 5.3.3 and 6.3.3, every C row of the
information-element tables of clauses 5.2.1.1, 5.2.2.1, 5.2.3.1, 6.2.1.1,
6.2.2.1 and 6.2.3.1 and the M and O rows stating a condition, the commands'
clauses 5.3.2.2 and 6.3.2.2, the routing clause 5.3.1.1.2, clause 7's
result codes, and the procedure clauses for what they state of one
message. Release 18's copy, V18.2.0, holds 144 of the 155 blocks V19.3.0
holds and one of its own: it prints no MPS-Priority sentences in clauses
5.2.1.3, 6.2.1.2 and 6.2.2.3, no Serving-Node Alert rows or their NOTE in
table 5.2.3.1-2 and no failed-delivery rows in table 5.2.3.1-1, and its
MWD-Status table ends at bit 4, read in a block whose quote only it
prints. S6c's commands print once under
16777312 and SGd's under 16777313; ALR and ALA serve SGd and Gdd too under
S6c's application (clause 6.3.2.2), so the tables of clauses 5.2.2.1 and
6.2.3.1 both describe the one print.

| | |
|---|---|
| AVP clauses (clauses 5.3.3 and 6.3.3, not their General clauses) | 57 |
| with something to declare | 22, in 39 blocks |
| with nothing to declare | 35 |
| information-element C rows | 40, of which 35 state a condition |
| the tables' blocks (clauses 5.2.1.1 to 6.2.3.1), M and O rows and each answer's Result among them | 55 |
| clause 4's common aspects (4.5, 4.9), 5.2.1.3's HSS, 5.3.1.1.2's routing, 5.3.2.2's and 6.3.2.2's commands, 6.2.1.2's and 6.2.2.3's MPS, 7.3.1's result codes | 30, 10, 3, 2, 10, 2, 5 blocks |
| blocks | 156 in the file, V19.3.0 holding 155 and V18.2.0 145: 116 within a command, 19 within a grouped AVP, 21 on an AVP wherever read |
| readings | 167 |

| Rules | |
|---|---|
| `encoding`, a codec | 7: `e164-tbcd` 4 (SC-Address, SMS-GMSC-Address, SMSF-3GPP-Number, SMSF-Non-3GPP-Number), `digits` 3 (HSS-ID, the SRR's and TFR's User-Name) |
| `encoding element` | 9, naming 4 entries of the registry; 8 rules checked, 1 not ([above](#elements)) |
| `length` | 4: SM-RP-UI, at most 200 octets, and HSS-ID and the SRR's and TFR's User-Name, 6 to 15 digits |
| `range` | 10: Auth-Session-State NO_STATE_MAINTAINED in each of the 10 commands |
| `exclude` | 5: Result-Code in each answer, none of 5550 to 5558 |
| `requires`, `present-if`, `absent-if`, `excludes` | 26, 12, 9, 9 |
| `values` | 2: Feature-List-ID 1 within a 3GPP Supported-Features, in S6c's messages and in SGd's |
| `absent` | 20: Authorization-Lifetime and Session-Timeout in each of the 10 commands |
| reading the request | 2: the SRA's Serving-Node in a success's answer to a request without SM-Delivery-Not-Intended, the TFA's Requested-Retransmission-Time only after a Maximum-Retransmission-Time |
| `bits` | 7: `only` 6 (a flags AVP's NOTE that undefined bits are cleared, MWD-Status's once per release), `at-least-one` (the SGd ALR's SMS-GMSC-Alert-Event) |
| `members` | 2: `at-least-one`, Serving-Node's and Additional-Serving-Node's numbers |
| `text-only` | 63, 10 of them Vendor-Specific-Application-Id's in each command and 10 the Supported-Features Vendor-Id |

Clause 4.5's "shall include ... the Auth-Session-State AVP set to the value
NO_STATE_MAINTAINED (1)" and "Neither the Authorization-Lifetime AVP nor the
Session-Timeout AVP shall be present" are read in each of the ten commands, the
two AVPs RFC 6733 defines admitted through each body's `* [ AVP ]`. Clauses
5.3.2.2's and 6.3.2.2's "The Vendor-Specific-Application-Id AVP shall not be
included in any command sent by Diameter nodes supporting applications defined
in this specification" is `text-only` in each: it binds the sending node, the
next sentence has the receiver ignore the AVP, and the NOTE has every command
format print it for intermediate agents not complying with RFC 6733, so a
message captured past such an agent may hold it rightly. Clause 4.9's "for
features defined in this document, the Vendor-Id AVP shall contain the vendor ID
of 3GPP (10415)" is `text-only` in each command carrying Supported-Features: TS
29.229 clause 6.3.29 has a vendor's own features carry its own Vendor-Id, and
only the Vendor-Id and Feature-List-ID tell which list an AVP carries, so
whether it is the document's the message does not say. Clauses 5.3.3.12's and
6.3.3.8's Feature-List-ID 1 is the 3GPP list's, the one whose Vendor-Id is
10415, read within Supported-Features in S6c's messages and in SGd's
(`; Application-ID:`), as TS 29.273's four applications' are. Serving-Node's and
Additional-Serving-Node's "The following combinations are allowed" (clauses
5.3.3.6 and 5.3.3.7) are read member by member: one of the numbers present, and
each member only beside the others of its combination; combination b's condition
is the HSS's, so its members are allowed whatever it. Each answer's Result row
holds the Experimental-Result to the 3GPP vendor, and clause 7.3.1's "the
Result-Code AVP shall be absent" beside one of its ten codes is read in each
answer as TS 29.329's clause 6.2 is: an Experimental-Result under the 3GPP
Vendor-Id, and no Result-Code holding one of the codes, 5550 to 5558, but
DIAMETER_ERROR_USER_UNKNOWN, whose 5001 is RFC 6733's DIAMETER_AVP_UNSUPPORTED
too; the row's mandatory result is a Result-Code where the answer holds no
Experimental-Result, the body printing both optional. An SRR's or ALR's or
RDR's SMSMI-Correlation-ID holds the destination's
SIP-URI and neither the originating one nor the HSS-ID, an OFR's all three and a
TFR's the two SIP-URIs, read through paths from the command, whose
SMSMI-Correlation-ID other commands fill otherwise; a TFA's
Requested-Retransmission-Time "may only be present if" the answer reports
DIAMETER_ERROR_ABSENT_USER and the request held a Maximum-Retransmission-Time.
The SM-Delivery-Failure-Cause an OFA or TFA carries with
DIAMETER_ERROR_SM_DELIVERY_FAILURE holds one of the causes its table names,
clause 6.3.3.6's values, read under that code alone, which the row's list
is conditioned on; the TFA's "UE error" is EQUIPMENT_PROTOCOL_ERROR, MAP's
equipmentProtocolError, which clause 6.3.3.6's NOTE says the values follow.
An RDR holds at least one node's SM-Delivery-Outcome and no MSC's cause
beside an MME's, read on the causes within SM-Delivery-Outcome; that the
outcome present holds its cause, not a diagnostic alone, no rule says, a
path three AVPs deep from the command leaving the test messages no valid
RDR. An OFR's outcome is the IP-SM-GW's with its cause. HSS-ID and the
SRR's and TFR's User-Name, an IMSI or an HSS-ID, are digits, 6 to 15 (TS
23.003 clauses 2.2 and 5.3). An SGd ALR, which its SMS-GMSC-Alert-Event
tells from S6c's, names one of the two events, and its new serving node
holds the MME's number for MT SMS or the SGSN's number (table 6.2.3.1-1).

The text-only rules are mostly conditions on the node, a feature, the
subscription, what the HSS stores or an earlier message ("shall be present
when the MSISDN exists", "if the SMS-GMSC supports receiving of the two
numbers from the HSS", "when given by the MME and stored in the HSS", "if
the feature \"SMSF-Support\" is not supported", "shall be present when the
request is sent to a MME", "If allowed by local policy"). A row whose
condition is partly the node's keeps the part a message shows where that
part alone holds of every message the row allows: an SRR without an MSISDN
carries a User-Name, and an SRA's Serving-Node is held to a success's answer
to a request without SM-Delivery-Not-Intended, whose answer "may" lack it.
Clause 5.2.1.3's IP-SM-GW number for an SMSMI-Correlation-ID is text-only:
it binds an HSS answering a request it does not forward, and the HSS
forwards requests to an SMS Router as a proxy (clause 5.3.1.1.2), which
answer the SRA does not tell apart. The routing clause's Destination-Host
"if the SMS-GMSC or the SMS router has stored or can obtain the
address/name" of the HSS, the MPS-Priority of an OFR or TFR after an earlier
IDR, ULA or SRA, and the RDR's failed nodes "as previously provided" in an
earlier SRA are text-only.
The rest a single message could show but no kind says: two AVPs' contents
differing (an Additional-Serving-Node not repeating the Serving-Node, the
RDA's Alert MSISDN differing from the request's), two times compared (the
Requested-Retransmission-Time within the Maximum-Retransmission-Time), and
SM-Delivery-Timer's and SM-Delivery-Start-Time's "should be included", a
presence with no condition of an AVP the ABNF prints optional. The SRA's
"only one serving node address" without the GPRS indicator is text-only,
since an HSS answering an SMS-GMSC without SMSF-Support may carry an SMSF's
address in Additional-Serving-Node (clause 5.3.3.13).

The document is wrong in places the corpus reads around: clause 5.2.1.3
names DIAMETER_SUCCESS DIAMETER_SUCCESSFUL and DIAMETER_ERROR_SERVICE_BARRED
DIAMETER_ SERVICE _ERROR_BARRED, in sentences no block reads; clause
6.3.3.10 types SM-Delivery-Timer Integer where table 6.3.3.1/1 types it
Unsigned32, which the corpus keeps, no rule reading its value; clause
5.3.3.6's body prints an IP-SM-GW-Realm no allowed combination names,
read `text-only`; clause 6.2.2.2 answers a facility not supported with
DIAMETER_ERROR_FACILITY_NOT_SUPPORTED, and clause 7.3.10 allows the MME
DIAMETER_ERROR_SERVICE_BARRED, where the TFA's Result row lists neither,
so no rule holds the TFA to the row's list; clause 6.3.3.12's OFR-Flags
bit names UTRAN under both the set bit's Gdd and the cleared bit's SGd, and
no rule reads the bit; and clause 5.3.3.11's heading names
SGSN-Absent-User-Diagnostic-SM SGSN-Absent-Subscriber-Diagnostic-SM. Left
unread: the C rows saying only what an AVP holds when present ("This
information element shall contain the RP-Message Type Indicator") and the
"may" rows (Absent-User-Diagnostic-SM "may be present when
Experimental-Result-Code is set to DIAMETER_ERROR_ABSENT_USER"); clause
4.7's Capabilities-Exchange AVPs, which are RFC 6733's commands' and this
file does not print; the routing clause 6.3.1, which says what a node that
can obtain an address puts in Destination-Host; the SM-RP-SMEA's
Type-of-Address bits, which TS 23.040 clause 9.1.2.5 draws in a figure the
element's entry does not read; the procedures' result codes, which are
what a node answers with; the sentences repeating
a table row (clause 6.2.2.3's SMS-GMSC address beside a
Maximum-Retransmission-Time), read at the row; Feature-List's SMSF-Support
description, which the SRA's NOTE rows read; and Annex A's DRMP, an
operator's priority.

## TS 29.128

TS 29.128 V19.2.0 is read completely for T6a/T6b, T6ai/T6bi and T7: the
information-element tables of clause 5's procedures (5.2.1 to 5.8.1), with
the procedure clauses for what they state of one message, clause 6.1's
common aspects, clause 6.2.2's commands, clause 6.3's result codes and
every AVP clause of clause 6.4. Release 18's copy, V18.0.0, holds 104 of the
105 blocks: it prints no clause 5.2.2.8, whose store and forward satellite
event Release 19 added. Each command prints once under
16777346, for every interface, so a table describing one direction of a
command (the MME's or SGSN's Connection-Management-Request of clause 5.7.1,
the SCEF's of 5.8.1) describes the one print: a rule is read only where it
holds of both, as an establishment's AVPs, which the SCEF never requests.

| | |
|---|---|
| AVP clauses (clause 6.4, not its General clause) | 45 |
| with something to declare | 15, in 16 blocks |
| with nothing to declare | 30 |
| information-element C rows | 18, of which 15 state a condition |
| the tables' blocks (clauses 5.2.1 to 5.8.1), M rows and each answer's Result among them | 26 |
| procedure clauses (5.2.2.0 to 5.2.2.8, 5.7.2) | 8 blocks |
| clause 6.1.4's sessions, 6.1.9's Supported-Features, 6.2.2's commands, 6.3.3's result codes | 30, 10, 10, 5 blocks |
| blocks | 105: 84 within a command, 8 within a grouped AVP, 13 on an AVP wherever read |
| readings | 105 |

| Rules | |
|---|---|
| `encoding`, a codec | 1: `labels` (Service-Selection) |
| `encoding element` | 10, naming 10 entries of the registry; 5 rules checked, 5 not ([above](#elements)) |
| `range` | 10: Auth-Session-State NO_STATE_MAINTAINED in each of the 10 commands |
| `exclude` | 7: Uplink-Rate-Limit and Downlink-Rate-Limit 1 to 9, each answer's Result-Code none of the codes clause 6.3.3 lists but 5001 |
| `requires`, `present-if`, `absent-if` | 12, 8, 5 |
| `absent` | 20: Authorization-Lifetime and Session-Timeout in each of the 10 commands |
| reading the request | 1: the CMA's PDN-Connection-Charging-ID answering an establishment with DIAMETER_SUCCESS |
| `values` | 1: a reachability report's Reachability-Information REACHABLE_FOR_DATA |
| `bits` | 2, each `only`: CMR-Flags, TDA-Flags |
| `text-only` | 35, 10 of them Vendor-Specific-Application-Id's in each command and 10 the Supported-Features Vendor-Id |

Clause 6.1.4's session handling and clause 6.2.2's Vendor-Specific-
Application-Id are read in each of the ten commands as TS 29.338's clauses
4.5 and 5.3.2.2 are, and clause 6.3.3's "the Result-Code AVP shall be
absent" beside one of its twelve codes in each answer, TS 29.172's
DIAMETER_ERROR_UNREACHABLE_USER (4221) among them. Clause 5.2.2's report
contents are read within Monitoring-Event-Report, as the document prints
its body: the event a report carries is its Monitoring-Type, TS 29.336's
Unsigned32, whose values clause 8.4.7 names, so a location report
(LOCATION_REPORTING) carries its EPS-Location-Information, a communication
failure's (COMMUNICATION_FAILURE) its Communication-Failure-Information, and
a reachability report (UE_REACHABILITY, or UE_REACHABILITY_AND_IDLE_STATUS_
INDICATION without an Idle-Status-Indication, its NOTE says)
Reachability-Information REACHABLE_FOR_DATA, written 1 in a `values` rule.
Connection-Action is an Unsigned32 too, clause 6.4.18 naming
CONNECTION_ESTABLISHMENT.

The text-only rules are mostly conditions on the node, a feature, the
subscription or what a node needs to send ("if present in the subscription
data received from the HSS", "if the MME or SGSN receives Extended PCO
information from the UE", "If an immediate report is available", "When the
\"Extended Reference IDs\" feature is supported", "if Serving PLMN Rate
Control is configured"), a request's purpose its own AVP's presence already
tells (Non-IP-Data "shall be present when the request conveys Non-IP
data"), and two times compared (the TDA's Requested-Retransmission-Time
within the request's Maximum-Retransmission-Time). The CMR's RAT-Type and
Visited-PLMN-Id "shall be present if the request is for a T6a/b connection
establishment or for a T6a/b connection update" are read of an
establishment alone: an update is the SCEF's request too (clause 5.8.1),
whose table names neither.

The document is wrong in places the corpus reads around: clauses 5.2.2.7
and 5.2.2.8 number PDN_CONNECTIVITY_STATUS 8 and SAT_SF_OPERATION_INFO 9,
the values clause 5.2.2.2 and 5.2.2.6 give UE_REACHABILITY_AND_IDLE_STATUS_
INDICATION and AVAILABILITY_AFTER_DDN_FAILURE_AND_IDLE_STATUS_INDICATION,
where TS 29.336 clause 8.4.7 numbers them 10 and 11, so the two events'
AVPs are read `text-only`; clause 6.4.3's text names an
SCEF-Reference-ID-Ext its Monitoring-Event-Report body does not print, nor
admit through a `* [ AVP ]`; table 5.8.1-1 has the SCEF's
Connection-Action indicate "a T6a/b connection update" where clauses 5.8.1
and 5.8.3 have it request a release too; and clause 6.4.35's text runs
into Annex A's heading, "Annex A (normative): Diameter overload control
mechanism". Left unread: the C and O rows saying only what an AVP holds when
present and the "may" rows (the TDA's Requested-Retransmission-Time "may be
present if" the answer reports DIAMETER_ERROR_USER_TEMPORARILY_UNREACHABLE);
clause 6.1.7's Capabilities-Exchange AVPs, RFC 6733's commands'; the
routing clause 6.1.6; the procedures' result codes, which are what a node
answers with; Cause-Type's and the other Unsigned32 AVPs' value lists,
which the clauses do not say are all a sender may send; and Annex A's
overload control and Annex B's DRMP.

## TS 29.336

TS 29.336 V19.1.0 is read completely for S6m/S6n and S6t: the
information-element tables of clauses 5.2.1.1, 7.2.1.1, 7.2.2.1 and 7.2.3.1,
with the procedure clauses for what they state of one message, clauses 6.1
and 8.1's common aspects, 6.2.2's and 8.2.2's commands, 6.3.3's and 8.3.3's
result codes and every AVP clause of clauses 6.4 and 8.4. Release 18's copy,
V18.2.0, holds 158 of the 159 blocks: its Supported-Monitoring-Events table
ends at bit 8, and it prints no sentence of its own a bits rule could be
pinned to. SIR and SIA print once under 16777310 for S6m and S6n alike, the
S6m/S6n Indicator of SIR-Flags telling the MTC-IWF's request from the
MTC-AAA's (table 6.4.10/1); S6t's commands print once under 16777345, NIR
and NIA serving both directions, the SCEF's request told apart by its
NIDD-Authorization-Request and the HSS's by its NIDD-Authorization-Update
(table 7.2.3.1-1). Whether an S6t External-Identifier names a group the
User-Identifier's Type-Of-External-Identifier says, which its `* [ AVP ]`
admits as clause 8.4.36's S6t format prints it, its absence an individual
UE's identity.

| | |
|---|---|
| AVP clauses (clauses 6.4 and 8.4, not their General clauses) | 103 |
| with something to declare | 41, in 70 blocks |
| with nothing to declare | 62 |
| information-element C rows | 16, each stating a condition |
| the tables' blocks (clauses 5.2.1.1 to 7.2.3.1), M and O rows and each answer's Result among them | 30 |
| procedure clauses (5.2.1.2 to 5.2.1.4, 7.2.1.2, 7.2.2.2, 7.2.3.2) | 14 blocks |
| clauses 6.1.4's and 8.1.4's sessions, 8.1.6's routing, 6.1.9's and 8.1.9's Supported-Features, 6.2.2's and 8.2.2's commands, 6.3.3's and 8.3.3's result codes | 24, 1, 8, 8, 4 blocks |
| blocks | 159: 91 within a command, 38 within a grouped AVP, 30 on an AVP wherever read |
| readings | 172 |

| Rules | |
|---|---|
| `encoding`, a codec | 4: `e164-tbcd` 2 (the SIR's SCS-Identity, IP-SM-GW-Number), `labels` (Service-Selection), `ip-address` (PDN-Connectivity-Status-Report's Served-Party-IP-Address) |
| `range` | 9: Auth-Session-State NO_STATE_MAINTAINED in each of the 8 commands, PDN-Connectivity-Status-Report's Non-IP-PDN-Type-Indicator TRUE |
| `exclude` | 5: PDN-Connectivity-Status-Report's PDN-Type IPv4_OR_IPv6, each answer's Result-Code none of the codes clauses 6.3.3 and 8.3.3 list but 5001 |
| `requires`, `present-if`, `absent-if`, `excludes` | 33, 12, 13, 13 |
| `absent` | 16: Authorization-Lifetime and Session-Timeout in each of the 8 commands |
| `equals` | 1: the CIR's Origin-Host, the SCEF-ID of its Monitoring-Event-Configuration |
| reading the request | 10: the SIA's Service-Data after the SIR's Service-ID and its User-Identifier answering S6n, the CIA's User-Identifier, Number-Of-UEs and IMSI-Group-Id as the CIR's group or flags ask, its Monitoring-Event-Config-Status after a Monitoring-Event-Configuration and its Enhanced-Coverage-Restriction-Data after the query, the NIA's NIDD-Authorization-Response answering the HSS's update and holding the IMSI for an MSISDN, its Group-User-Identifier for a group |
| `default` | 6: Reachability-Type, MONTE-Location-Type, Scheduled-Communication-Time's Time-Of-Day-Start, Type-Of-External-Identifier, Supported-Monitoring-Events, PLMN-ID-Requested |
| `values` | 1: Maximum-Number-of-Reports at most one for an SMS reachability or a last known location (clause 8.4.8) |
| `bits` | 16: `only` 12, a flags AVP's NOTE that undefined bits are cleared, Supported-Monitoring-Events' in Release 19 alone; `at-most-one` 4 (Reachability-Type, IMEI-Change, Battery-Indicator's bit 0 against bits 1 and 2) |
| `members` | 12, each `at-least-one`: User-Identifier not empty, Serving-Node's and Additional-Serving-Node's numbers, the reference IDs of Monitoring-Event-Configuration, AESE-Communication-Pattern and Updated-Network-Configuration, the SCEF's NIDD-Authorization-Request's APN, each Group-User-Identifier's IMSI and MSISDN or External-Identifier, AdditionalIdentifiers, Exclude-Identifiers, Include-Identifiers |
| `text-only` | 49, 8 of them Vendor-Specific-Application-Id's in each command and 8 the Supported-Features Vendor-Id |

Clauses 6.1.4 and 8.1.4's session handling and clauses 6.2.2 and 8.2.2's
Vendor-Specific-Application-Id are read in each of the eight commands as TS
29.338's clauses 4.5 and 5.3.2.2 are, clause 6.1.4 opening on the MTC-IWF
and its requirement the application's client's and server's, and clauses
6.3.3's and 8.3.3's "the Result-Code AVP shall be absent" beside one of their
three and eight codes in each answer. The tables' "exactly one" identifier
of a request's User-Identifier (the SIR's, the CIR's) is read through paths
from the command as at least one of those the row names and no two, the
MTC-AAA's request holding only the IMSI (clause 5.2.1.4); Serving-Node's and
Additional-Serving-Node's "The following combinations are allowed" (clauses
6.4.12 and 6.4.13) member by member as TS 29.338 reads its own, combination g
naming the IP-SM-GW-Realm TS 29.338's leaves out. A CIR deleting all
monitoring events carries no new one, a Monitoring-Event-Configuration with
a reference ID (clause 7.2.1.2); an RIR's report of PDN_CONNECTIVITY_STATUS
its PDN-Connectivity-Status-Report (clause 8.4.77), read on each
Monitoring-Event-Report, its paths reading that report; and the HSS's NIR
its Destination-Host (clause 8.1.6). Maximum-Number-of-Reports' conditions
hold of an absent Reachability-Type or MONTE-Location-Type too, whose
defaults are the values the clause names (clauses 8.4.12, 8.4.16). The
blocks with no scope, or within a grouped AVP, hold where TS 29.128 and TS
29.272 read the AVPs, which they re-use from this document
([Precedence](#precedence)): Monitoring-Event-Configuration's reference IDs
and Maximum-Number-of-Reports in T6a's, which TS 29.272's own blocks on the
AVP set aside in S6a's, Battery-Indicator's bits in S6a's
Communication-Pattern-Set.

The text-only rules are mostly conditions on the node, a feature, the
subscription, what the HSS stores or decides, or an earlier message ("if
available, the MSISDN of the user shall also be returned", "It shall be
present if the user is not registered in any serving node", "When the
\"Extended Reference IDs\" feature is supported", "following a previous NIA
with an incomplete Group User Identifier List"), which node sends a SIR,
which only the bit itself shows (clauses 5.2.1.3, 5.2.1.4), a request's
purpose its own AVP's presence tells (AdditionalIdentifiers), and what an
absent AVP means where that is no value of its own (Reference-ID-Validity-
Time, Day-Of-Week-Mask, the PLMN lists' Visited-PLMN-Id, an APN-less
APN-Validity-Time or PDN-Connectivity-Status-Configuration). The rest a
single message could show but no kind says: External-Identifier's
identifier, a UE's or a group's of TS 23.003 clauses 19.7.2 and 19.7.3 by
the interface and Type-Of-External-Identifier, a username@realm text no
codec reads; Service-Result's Vendor-Id, which turns on which document
defines a code the base protocol's and 3GPP's share numbers of (5001); two
values compared (a Suggested-Network-Configuration's reference IDs, the
NIA's granted validity time against the NIR's requested one); an IPv6
prefix's low 64 bits; an External Identifier in the NIR, which may be a
group's whose IMSIs go in the Group-User-Identifier (clause 7.2.3.2 step 4);
and Time-Of-Day-End's "end of the day", RFC 5777's 86400 or one second
before it.

The document disagrees with itself where the corpus reads around it: table
7.2.3.1-1 has the SCEF's NIR hold "either an External Identifier or an
MSISDN (exactly one, and only one ...)", where clause 7.2.3.2's step 6 and
NOTE 2 have its User-Identifier contain an IMSI, so only "not both" is read;
clause 8.4.70 has NIR-Flags' Incomplete Group-User-Identifier-List bit set
"when the SCEF indicates" that more segments will follow in NIR commands,
which clause 7.2.3.2's step 6a has the HSS send; clause 7.2.2.3 has the SCEF
"set Experimental-Result to DIAMETER_SUCCESS", a Result-Code value; clauses
8.4.84 and 8.4.85 have Exclude-Identifiers and Include-Identifiers "contain
External Group Identifiers or MSISDNs", where clause 7.2.1.2's step 5 lists
in them the UEs of a group, read only as at least one of the two AVPs;
clause 5.2.1.4 has the MTC-AAA "only include the User Identifier IE", beside
the SIR-Flags its ABNF requires; and Release 18's clause 8.2.6 sends the RIA
"from the HSS to the SCEF". Left unread: the C and O rows saying only what an
AVP holds when present and the "may" and "should" sentences (T4-Data's
"should not be present" for Teleservice Not Provisioned or Call Barred,
Exclude-Identifiers' "may be included"); clauses 6.1.7 and 8.1.7's
Capabilities-Exchange AVPs, RFC 6733's commands'; the routing clauses 6.1.6
and 8.1.6 but the HSS's requests; the procedures' result codes, which are
what a node answers with; the sentences repeating the ABNF (a grouped AVP's
required SCEF-Reference-ID "included ... by the sender") or a table row
(clause 5.2.1.2's Serving-Node left out for an absent user, read at clause
6.4.8, step 6a's Group-User-Identifier, read in its no-scope block);
Monitoring-Type's and the other Unsigned32 AVPs' value lists, which the
clauses do not say are all a sender may send; what a bit or value means
("This bit shall be set if the SCEF wants to"); the IMSI a User-Name holds,
which no codec reads; and Annex A's overload control and Annex B's message
priorities.

## TS 29.061

TS 29.061 V19.1.0 is read for Gi and SGi, Gmb and SGmb: clause 16.4.7.2's
3GPP vendor-specific sub-attributes, which table 9a lists as Gi's and SGi's
Diameter AVPs, clause 16a's procedures, commands and result codes, clause
17's procedures, commands and every AVP clause of 17.7, and clause 20's
procedures, commands, every AVP clause of 20.5a and 20.7's supported
features. Release 18's copy, V18.1.0, prints every sentence read and holds
all 82 blocks. Clauses 17.7a and 20.5 have re-used RADIUS attributes
"translated to Diameter AVPs as described in IETF RFC 7155", as table 9a's
note does: the AVP carries the sub-attribute's value, whose "Length" counts
its 3GPP Type and Length octets too, so clause 16.4.7.2's "Length: 6" is an
AVP of 4 octets. The document prints AA-Request and AA-Answer under NASREQ
(1) and Gmb (16777223), and Re-Auth-Request, ST-Request and
Abort-Session-Request under Gmb and SGmb (16777292): a block names its
print's application.

| | |
|---|---|
| clause 16.4.7.2's sub-attributes, table 9a's AVPs | 31 |
| with something to declare | 27, in 27 blocks |
| with nothing to declare | 4 |
| Gmb's AVP clauses (17.7.2 to 17.7.25, not Void) | 23 |
| with something to declare | 16, in 16 blocks |
| SGmb's AVP clauses (20.5a.1 to 20.5a.12) | 12 |
| with something to declare | 4, in 4 blocks |
| procedure and command clauses (16a.2, 16a.3.1, 16a.6, 17, 17.6.1 to 17.6.5, 17.7.15, 20.1, 20.3.4, 20.4.1, 20.4.2, 20.7) | 35 blocks |
| blocks | 82: 35 within a command, 47 on an AVP wherever read |
| readings | 89 |

| Rules | |
|---|---|
| `encoding`, a codec | 6: `digits` (3GPP-IMSI, 3GPP-IMSI-MCC-MNC, 3GPP-GGSN-MCC-MNC, 3GPP-SGSN-MCC-MNC, 3GPP-Selection-Mode, 3GPP-IMEISV) |
| `encoding element` | 6, naming 6 entries of the registry; 3 rules checked, 3 not ([above](#elements)) |
| `length` | 35: 6 in digits, the six codecs' (IMSI at most 15, MCC and MNC 5 or 6, IMEI(SV) 14 to 16), 29 in octets, 16 of the sub-attributes' values (an address 4 or 16, 3GPP-Charging-Id 4, 3GPP-MS-TimeZone 2) and 13 of Gmb's and SGmb's AVPs (MBMS-Session-Duration 3, RAI 11 or 12, MBMS-Service-Area 3 to 513, MBMS-Cell-List 9 to 28674) |
| `range` | 8: Auth-Application-Id 16777223 in Gmb's 5 commands printing it and 16777292 in SGmb's 3 (clauses 17, 20.1) |
| `requires`, `present-if`, `absent-if`, `excludes` | 1, 13, 3, 1 |
| reading the request | 6: the AAA's Gmb specific AVPs after the AAR's Additional-MBMS-Trace-Info, but its 3GPP-IMSI, SGmb's heartbeat RAA's MBMS-StartStop-Indication and Restart-Counter |
| `default` | 1: MBMS-User-Data-Mode-Indication Unicast |
| `values` | 1: the heartbeat RAA's MBMS-StartStop-Indication HEARTBEAT |
| `bits` | 2, each `only`: MBMS-Flags, Diagnostic-Info |
| `text-only` | 19, 2 of them SGmb's Supported-Features Vendor-Id |

The sub-attributes' blocks have no scope, and hold wherever a document
reads the AVP, TS 29.212's, 29.214's and 32.299's among them, but where a
document reads the AVP itself (TS 29.214's 3GPP-User-Location-Info). A
digit or text value is a UTF-8 string of characters: the MCC-MNC AVPs "3
digits" and "2 or 3 digits" with "no padding characters", 3GPP-Selection-
Mode "a character that represents a single digit", 3GPP-IMEISV's n of 14, 15
or 16. 3GPP-NSAPI's one hexadecimal character, 3GPP-Charging-Characteristics'
four, RAI's MCC and MNC digits and hexadecimal LAC and RAC are read as their
octets alone, no codec reading hexadecimal characters. Gmb's AAR carrying
Additional-MBMS-Trace-Info activates a trace session, since an AAR for any
other purpose carries none (clause 17.6.1): it holds none of the AVPs the
clause forbids then, and its AAA none of the Gmb specific AVPs but 3GPP-IMSI
(17.6.2), the answer's 3GPP-IMSI held to a success's. A RAR's
MBMS-StartStop-Indication tells a session start, update or heartbeat (17.6.5,
20.4.1): Gmb's and SGmb's update carries its MBMS-Session-Duration and
MBMS-Time-To-Data-Transfer and Gmb's its MBMS-Service-Area, SGmb's start its
MBMS-Time-To-Data-Transfer and MBMS-Service-Area, Gmb's start its
MBMS-Session-Identity and MBMS-Session-Repetition-Number together (17.7.15),
and SGmb's heartbeat its Restart-Counter, the heartbeat's RAA the
MBMS-StartStop-Indication HEARTBEAT and its Restart-Counter where it
answers with DIAMETER_SUCCESS. Clause 16a.6's Experimental-Result "containing
the Vendor-Id AVP set to the value of 3GPP's vendor identifier (10415)" is
read in the ASA, Gi's one answer printing it, and clause 20.7's
Supported-Features Vendor-Id in SGmb's RAR and RAA, as TS 29.336's are.
Clause 20.3.4's heading Release 19 and 18 print as a paragraph of clause
20.3.3, whose text it is read as.

The text-only rules are mostly conditions on the node, the procedure or an
earlier message (a re-authorization's AUTHORIZE_ONLY with the initial
request's Session-Id, an interim record for a deferred IPv4 address, an AAR
modifying an MBMS UE context, a trace session's deactivation, a changed list
of downstream nodes or service area, the BM-SC's use of local MBMS
information, a detected path failure, the initial RAR and RAA, which a
session start's or heartbeat's RAR need not be, since a broadcast service's
later sessions keep the first one's Session-Id), and layouts no kind reads:
3GPP-GPRS-Negotiated-QoS-Profile's release indicator and hexadecimal octets,
3GPP-User-Location-Info's location, coded by the node and the type in its
first octet, MBMS-Required-QoS's octets in a UTF8String, MBMS-Session-
Duration's seconds and days, at most 86400 and 18, a field of the three
octets, and MBMS-Service-Area's codes each present once. The values a
document's own Gi and SGi messages do not carry, 3GPP-User-Location-Info's
5GS types (which "shall not apply for the present specification"), are an
octet of an OctetString, which no kind reads under a scope, and a
session update's MBMS-Time-To-Data-Transfer "with the value set to 0" is
read as its presence alone. 3GPP-UE-Local-IP-Address's 5 or 17 octets are
read as their bounds, no kind saying a length is one of two.

The document is wrong in places the corpus reads around: clause 16.4.7.2
prints 3GPP-Secondary-RAT-Usage with "Length=28" and its Usage Data UL in
octets 20 to 28, nine octets where TS 29.274 clause 8.132's is eight, so no
length is read; it prints the bounds of 3GPP-IMSI, 3GPP-IPv6-DNS-Servers and
External-Identifier with "<=" and ">=" in a symbol font the extraction drops
("Length: m 17"), so no bound is quoted from such a line; and clause
17.6.3 names Additional-MBMS-Trace-Info Additonal-MBMS-Trace-Info. Left
unread: table 7's presence column (3GPP-PDP-Type "mandatory if attribute 7 is
present"), which names RADIUS messages and no Diameter command; 3GPP-PDP-
Type's values, which the clause says a PDP type "may have", and the
sentences saying values "do not apply" or are "only applicable", with no
shall (PDP types 5 and 6, a P-GW's "0", "2", "3" and "4", RAT types 51 to
58, the Secondary RAT Usage's RAT values); 3GPP-Session-Stop-Indicator,
which table 9a does not list as a Diameter AVP, and 3GPP-Teardown-Indicator,
which it has no AVP for; clause 16a.5's P-GW not sending an AVP whose
information is not up to date, a node's; the "should" and "may" sentences
(the GGSN's NSAPI values 05 to 0F, Alternative-APN "only includes it if");
the lower-case "must" of DIAMETER_ERROR_START_INDICATION's Failed-AVP
(clause 17.8.2), as RFC 4005's lower case is; MBMS-GW-SSM-IPv6-Address's
"IPv6 prefix" and the UDP ports, which the clauses give no length; the
sentences saying what a value or AVP means or is "only valid for"
(MBMS-Counting-Information, MBMS-Data-Transfer-Start); clause 20.4.1's
QoS-Information members that "are applicable", TS 29.212's AVP; clause
17.6.5's "other bold marked AVPs ... as given by the previous, corresponding
MBMS Session Start procedure", which names no AVP; the routing, session and
capabilities-exchange sentences; and the procedures' result codes, which
are what a node answers with.

## TS 29.154

TS 29.154 V19.0.0 is read completely for Nt and Nta: the procedures of
clauses 4.4 and A.4 for what they state of one message, clauses 5 and A.6's
protocol, every AVP clause of 5.3 and A.6.3, the supported features of 5.4.2
and A.6.4.2 and the commands' clauses 5.6.1 and A.6.6.1. Release 18's copy,
V18.0.0, prints every sentence read and holds all 37 blocks. Nt's BTR and
BTA print once under 16777348 and Nta's ECR, ECA, ERR and ERA under
16777358. The document has no information-element tables; Nt's BTR is a
transfer policy request or notification as its Transfer-Request-Type, an
Unsigned32 clause 5.3.4 names the values of, says, 0 or 1.

| | |
|---|---|
| AVP clauses (clauses 5.3 and A.6.3, not their General clauses) | 16 |
| with something to declare | 3, in 3 blocks |
| with nothing to declare | 13 |
| procedure clauses (4.4.1, A.4.1, A.4.2) | 18 blocks |
| clauses 5.2's and A.6.2's sessions, 5.4.2's and A.6.4.2's supported features, 5.6.1's and A.6.6.1's commands | 6, 4, 6 blocks |
| blocks | 37: 30 within a command, 5 within a grouped AVP, 2 on an AVP wherever read |
| readings | 43 |

| Rules | |
|---|---|
| `encoding element` | 1: Network-Area-Info-List, TS 29.274's Presence Reporting Area Action from octet 9, as TS 29.212's Presence-Reporting-Area-Elements-List ([above](#elements)) |
| `range` | 7: Auth-Session-State NO_STATE_MAINTAINED in each of the 6 commands, Event-Configuration's Monitoring-Type LOCATION_REPORTING |
| `requires`, `present-if` | 2, 10 |
| reading the request | 2: the BTA's Transfer-Policy and Reference-Id answering a transfer policy request |
| `members` | 4, each `at-least-one`: a Transfer-Policy's Time-Window and Rating-Group, Event-Configuration's Location-Information-Configuration and its MONTE-Location-Type |
| `unique` | 1: Transfer-Policy-Id within Transfer-Policy |
| `text-only` | 19, 4 of them Vendor-Specific-Application-Id's in each of Nta's commands and 4 the Supported-Features Vendor-Id |

A transfer policy request's BTR carries the ASP's identity, a volume, the
number of UEs and the time window, the volume the downlink's, the uplink's
or both, or the total's, read as at least one of the three on CC-Total-
Octets; a notification's its Reference-Id, Transfer-Policy-Id and
Destination-Host; and the BTA answering a request with DIAMETER_SUCCESS its
Transfer-Policy and Reference-Id (clause 4.4.1). The transfer policies of
one BTA share its Reference-Id, so their Transfer-Policy-Ids differ (clause
5.3.9). Clause 5.6.1's application identifier "in the Auth-Application-Id AVP
within the Vendor-Specific-Application-Id grouped AVP" is read on the BTR and
BTA through a path into it, RFC 6733's AVP, and clauses 5.4.2's and
A.6.4.2's Supported-Features Vendor-Id in each command printing it, as TS
29.336's are. Clause A.6.6.1's Vendor-Specific-Application-Id is
`text-only` in Nta's commands, as TS 29.338's clause 5.3.2.2 is, and the
successful ECA its Event-Configuration-Status (A.4.1).
Network-Area-Info-List, as TS 29.212's Presence-Reporting-Area-Elements-List,
holds the Presence Reporting Area Action from its octet 9: the entry those
read.

The text-only rules are mostly conditions on the node, a feature, what the
PCRF holds or an earlier message ("if supported by the SCEF and PCRF
respectively", "If the PCRF has at least one active IP-CAN session ... the
PCEF/BBERF supports the NetLoc feature", "if available and local policy
allows it", "If the PCRF receives NetLoc-Access-Support"), a Reference-Id
unique per PLMN, which no message shows, and what no kind says: the BTA's
PCRF-Address beside more than one Transfer-Policy, which no kind counts,
and the ECR's Event-Configuration, a presence with no condition of an AVP
the ABNF prints optional. Left unread: Transfer-Request-Type's values, which
the clause does not say are all a sender may send; the tables' "Only ... is
applicable" (Location-Information-Configuration's MONTE-Location-Type,
Monitoring-Type's LOCATION_REPORTING), with no shall, and the latter read
from clause A.4.1's shall; the sentences repeating the ABNF (the
Time-Window's start and end times, the Event-Reports' final report); the
header's Application-ID of clauses 5.1 and A.6.1, which no rule reads; the
capabilities exchange of clauses 5.2 and A.6.2, RFC 6733's commands'; and
the procedures' result codes (A.4.2's DIAMETER_ERROR_SCEF_REFERENCE_ID_
UNKNOWN), which are what a node answers with.

## TS 29.173

TS 29.173 V19.0.0 is read completely for SLh: the information-element
tables of clause 5.2.1.1, with the procedure clause 5.2.1.2 for what it
states of one message, clause 6.1's common aspects, 6.2.2's commands, 6.3's
result codes and every AVP clause of 6.4. Release 18's copy, V18.0.0,
prints every sentence read and holds all 30 blocks. RIR and RIA print once
under 16777291. The document defines Serving-Node and
Additional-Serving-Node, which TS 29.336 and TS 29.338 re-use with bodies of
their own: a block within them reaches those prints too
([Precedence](#precedence)), but for a member a document reads itself, and
no print but this one's holds an LCS-Capabilities-Sets.

| | |
|---|---|
| AVP clauses (clause 6.4, not its General clause) | 14 |
| with something to declare | 6, in 6 blocks |
| with nothing to declare | 8 |
| information-element C rows | 9, of which 8 state a condition with shall, the LMSI's with should |
| the tables' blocks (clause 5.2.1.1), the answer's Result among them | 9 |
| procedure clause 5.2.1.2 | 6 blocks |
| clause 6.1.4's sessions, 6.2.2's commands, 6.3.3's result codes | 6, 2, 1 blocks |
| blocks | 30: 20 within a command, 4 within a grouped AVP, 6 on an AVP wherever read |
| readings | 31 |

| Rules | |
|---|---|
| `encoding`, a codec | 3: `e164-tbcd` (MSC-Number), `ip-address` 2 (GMLC-Address, PPR-Address) |
| `encoding element` | 1: LMSI, TS 23.003's ([above](#elements)) |
| `range` | 2: Auth-Session-State NO_STATE_MAINTAINED in both commands |
| `exclude` | 1: the RIA's Result-Code, not 5490 |
| `values` | 1: Feature-List-ID 1 within a 3GPP Supported-Features |
| `requires`, `present-if`, `absent-if` | 1, 5, 7 |
| `absent` | 4: Authorization-Lifetime and Session-Timeout in both commands |
| `bits` | 1, `only`: RIA-Flags |
| `text-only` | 7, 2 of them Vendor-Specific-Application-Id's in both commands |

Clause 6.1.4's session handling and clause 6.2.2's Vendor-Specific-
Application-Id are read in both commands as TS 29.338's clauses 4.5 and
5.3.2.2 are, and clause 6.3.3's "the Result-Code AVP shall be absent" beside
one of its two codes in the answer, TS 29.229's DIAMETER_ERROR_USER_UNKNOWN
(5001) among them; the RIA's Result row holds the Experimental-Result to the
3GPP vendor. An RIR without an MSISDN carries the IMSI, its User-Name, and
one without an IMSI its MSISDN, and a successful RIA likewise; the RIA's
Serving-Node is present on success and absent otherwise, and its
Additional-Serving-Node, GMLC-Address and PPR-Address absent but on success.
A serving node is an MME, whose LCS-Capabilities-Sets clause 5.2.1.2 keeps
off SLh, where it holds an MME-Name and no other node's identity (SGSN-Number,
SGSN-Name, MSC-Number, 3GPP-AAA-Server-Name), read within Serving-Node and
Additional-Serving-Node: a node holding more might be a combined MME/SGSN.
The LMSI is TS 23.003's four octets, which the VLR "shall not allocate the
value zero".

The text-only rules are conditions on the subscription and on what the HSS
has received or registered ("the subscription is MSISDN-less", "if and only
if the HSS has received an indication that the Lgd interface is supported",
"except if the HSS has received an indication that the Lg interface is not
supported", the combined MME/SGSN's optimized LCS procedure, an S4-SGSN's
Capability Set 5). Left unread: the "should" and "may" rows (the RIA's LMSI,
GMLC-Address and PPR-Address "should be present if"); the procedure's
"returns" sentences, with no shall, which the table rows read (the IMSI or
MSISDN not provided, either or both when both were); the rows saying only
what an AVP holds when present (the GMLC Number's E.164 number, TS 29.272's
AVP); LCS-Capabilities-Sets' bits, whose meaning clause 6.4.6 gives TS
29.002; Feature-List's null value, "no feature used by the application", and
its NOTE; clause 6.1.3's accounting and 6.1.5's SCTP; the routing clause
6.1.6, which says what a GMLC that knows the HSS puts in Destination-Host;
clause 6.1.7's Capabilities-Exchange AVPs, RFC 6733's commands'; the
header's Application-ID of clause 6.2.2, which no rule reads; clause
5.2.1.3's receiver preferring the serving node; and the procedure's result
codes, which are what the HSS answers with.

## RFC 6733

RFC 6733 is read for what it says of the base protocol's AVPs and its own
commands: sections 3 to 9, and section 10.1's occurrence table. The base
protocol's AVPs are read by every application, so a block with no scope says
only what the RFC says of the AVP wherever it is sent; what it says of
answer messages in general is read in every answer of any application
(`; Messages: answers`), and what it says of one of its commands on its own
prints of CER/CEA, DWR/DWA, DPR/DPA, RAR/RAA, STR/STA, ASR/ASA and ACR/ACA,
which no application's own print of a command shares
([Precedence](#precedence)). An RFC has one edition, so no block names
`; Versions:`.

| | |
|---|---|
| sections 5.3 to 9.8 (capabilities, routing, errors, sessions, accounting) | 39 blocks |
| section 10.1's table, each "0" cell of an AVP the command's body admits only through `* [ AVP ]` | 321 blocks |
| blocks | 360: 332 within a command, 7 in every answer, 1 within a grouped AVP, 20 on an AVP wherever read |
| readings | 363 |

| Rules | |
|---|---|
| `encoding`, a codec | 2: `session-id` (Session-Id, Acct-Multi-Session-Id) |
| `exclude` | 1: Supported-Vendor-Id 0 |
| `default` | 1: Inband-Security-Id NO_INBAND_SECURITY |
| `members` | 1: `at-least-one`, Vendor-Specific-Application-Id's Auth- and Acct-Application-Id |
| `excludes` | 1: the two within Vendor-Specific-Application-Id, exactly one of them |
| `present-if` | 5, in every answer: Session-Id and Proxy-Info after the request's (section 6.2), Failed-AVP with the seven permanent failures whose clause requires one (7.1.5), Redirect-Host with DIAMETER_REDIRECT_INDICATION (6.12) and Redirect-Max-Cache-Time beside a Redirect-Host-Usage other than DONT_CACHE (6.14) |
| `equals` | 2: Session-Id in every answer (section 6.2) and in ACA (9.7.2), the request's |
| `absent` | 329: Destination-Host and Destination-Realm in every answer (sections 6.5, 6.6) and in CER, DPR and DWR, which cannot be proxied (6.1), and table 10.1's other "0" cells |
| reading the request | 4: the answers' Session-Id and Proxy-Info, ACA's Session-Id |
| `text-only` | 22 |

The header's fields and flags (sections 3 and 7.2: the version, the R, P, E
and T bits, a protocol error's E bit, the P bit an answer shares with its
request) are what the Wireshark plugin checks of the header
([wireshark-plugin.md](wireshark-plugin.md#what-it-checks)), and no block
reads them; nor sections 4.2 and 4.3.1's data formats, which the plugin
checks by type. A Session-Id begins with its sender's DiameterIdentity,
the `session-id` codec, whatever follows its first `;`. An answer with the E
bit set conforms to section 7.2's `<answer-message>`, not to its command's
CCF, and holds the rules in every answer that read no request: Redirect-Host
and Redirect-Max-Cache-Time with DIAMETER_REDIRECT_INDICATION (sections
6.12, 6.14), whose answer is a protocol error's and so sets the E bit
(7.1.3), Destination-Host and Destination-Realm absent, and Failed-AVP with
the permanent failures, which section 7.1.5 lets such an answer carry. The
Session-Id and Proxy-Info echo holds of each command's answer, against its
own request; an `<answer-message>` answers any, and is not held to one.

The text-only rules are conditions on the transport (Host-IP-Address per
address over SCTP), the node (an unsolicited agent-initiated request's
Destination-Host, which host set a Result-Code for Error-Reporting-Host, a
server's intent to extend an authorization), the session or an earlier
message (Route-Record against the peer's CER, Auth-Session-State in a
re-authorization, Origin-State-Id rising, Session-Binding's bits on later
messages, Class carried on, a sub-session's identifier rising, the service an
ACR accounts), two values compared (Session-Timeout and
Authorization-Lifetime, an answer's Authorization-Lifetime and its request's),
the header's Application-ID, which no rule reads (Auth-Application-Id,
Acct-Application-Id and Vendor-Specific-Application-Id "MUST match the
Application Id present in the Diameter message header", sections 6.8, 6.9,
6.11), and the applications' auth answers (Re-Auth-Request-Type beside a
positive Authorization-Lifetime, section 8.12), which no block of this file
is scoped to.

The document disagrees with itself where the corpus reads around it: table
10.1 gives Inband-Security-Id "0" in CER and CEA, whose bodies print
`* [ Inband-Security-Id ]` (sections 5.3.1, 5.3.2) and whose clause 6.10
calls its use there "NOT RECOMMENDED", so no block reads the cells; and the
table gives the RAR Acct-Interim-Interval and Accounting-Realtime-Required
"0-1", which its body admits only through `* [ AVP ]`. Left unread: section
10.2's accounting table, whose requirements it calls "guidelines, which may
be expanded, and/or overridden by application-specific requirements";
DIAMETER_MISSING_AVP's Failed-AVP, which "SHOULD be included"; clause 7.1.3's
"these errors MUST only be used in answer messages whose 'E' bit is set",
which the plugin checks as the E bit's; the "MUST" sentences of what a node
does on receipt (routing, loop detection, failover, the state machines of
sections 5.6, 8.1 and 8.2); clause 7.6's Result-Code or Experimental-Result,
which the base protocol's answers' bodies already require; and the IANA
section's assignments.

## RFC 4006

RFC 4006 is read for what it says of the credit-control AVPs and its own
CCR and CCA: sections 3 to 9, and section 10.1's occurrence table. RFC 8506
obsoletes it, so the Wireshark plugin holds a message to RFC 8506's print of
the commands, not RFC 4006's
([wireshark-plugin.md](wireshark-plugin.md#which-definition-a-message-is-held-to)),
but TS 32.299 reads the credit-control AVPs from RFC 4006: a block with no
scope, or within a grouped AVP, holds in Ro's commands, and a block on the
CCR or CCA binds RFC 4006's print alone ([Precedence](#precedence)). An RFC
has one edition, so no block names `; Versions:`.

| | |
|---|---|
| sections 3 to 9.2 (the commands, the procedures, the AVPs, the result codes) | 42 blocks |
| section 10.1's table, each "0" cell of an AVP the command's body admits only through `* [ AVP ]` | 26 blocks |
| blocks | 68: 49 within a command, 8 within a grouped AVP, 11 on an AVP wherever read |
| readings | 74 |

| Rules | |
|---|---|
| `range` | 1: the CCR's Auth-Application-Id 4 |
| `present-if` | 9: the CCA's Failed-AVP with DIAMETER_RATING_FAILED (sections 4.1.3, 8.43, 9.2) and with RFC 6733's seven codes (9), the CCR's Service-Identifier for a PRICE_ENQUIRY, its Subscription-Id for a CHECK_BALANCE and its Requested-Action for an EVENT_REQUEST, Final-Unit-Indication's Redirect-Server for REDIRECT (8.34, 8.37) |
| `absent-if` | 3: the CCR's Multiple-Services-Credit-Control without a Requested-Service-Unit in an INITIAL_REQUEST (5.2, 8.16), or holding a Tariff-Change-Usage |
| `excludes` | 2: Final-Unit-Indication with TERMINATE holding nothing else, a G-S-U-Pool-Reference's unit type absent from its Granted-Service-Unit |
| `values` | 3: the CCR's CC-Request-Type EVENT_REQUEST for a PRICE_ENQUIRY, a CHECK_BALANCE and a REFUND_ACCOUNT |
| `default` | 5: CC-Session-Failover, Credit-Control-Failure-Handling, Direct-Debiting-Failure-Handling, Multiple-Services-Indicator, Exponent within Unit-Value |
| `absent` | 26: table 10.1's "0" cells |
| `text-only` | 25 |

Section 6's one-time events are told apart by their Requested-Action: a
PRICE_ENQUIRY, CHECK_BALANCE or REFUND_ACCOUNT CCR is an EVENT_REQUEST,
and a price enquiry carries its Service-Identifier, a balance check its
Subscription-Id. The initial interrogation's Multiple-Services-Credit-
Control carries a Requested-Service-Unit (sections 5.2, 8.16) and a CCR's
holds no Tariff-Change-Usage of its own, the Used-Service-Unit's member
reporting the tariff change (8.16): both are read on the CCR through a
path into the AVP, whose own scope does not see the CC-Request-Type. A
G-S-U-Pool-Reference names the unit type of a pool, and the
Multiple-Services-Credit-Control's Granted-Service-Unit holds that type's
units (8.16): TIME its CC-Time, MONEY its CC-Money, each octet type its
count and SERVICE-SPECIFIC-UNITS its CC-Service-Specific-Units (8.32).
The document's own blocks on the CCA's Failed-AVP set aside RFC 6733's
reading of every answer ([Precedence](#precedence)), so the CCA reads its
seven codes again, on section 9's "The Credit-Control-Answer message
includes the Result-Code AVP, which may indicate that an error was present
in the Credit-Control-Request message", beside DIAMETER_RATING_FAILED.

The text-only rules are conditions on the session or an earlier message
(the session's one Session-Id, the first UPDATE_REQUEST's CC-Request-Number
1, the Multiple-Services-Indicator in the first interrogation, the used
units of each type the previous answer granted, a tariff change an earlier
CCA announced, the Validity-Time answering a request after the final
units), the node or the server (the Credit-Control AVP of an AA request
from a node with credit-control capabilities, the granted units a server
returns within Multiple-Services-Credit-Control, a Service-Context-Id
identifying one document), two AVPs compared (the G-S-U-Pool-References of
one pool, the two quotas of a tariff change), what an absent AVP means
where that is no value (CC-Sub-Session-Id, Tariff-Time-Change,
Tariff-Change-Usage), and texts no kind reads: Currency-Code's ISO 4217
codes, Service-Context-Id's `"service-context" "@" "domain"`, and the
address or identifier Redirect-Server-Address, Subscription-Id-Data and
User-Equipment-Info-Value carry by their sibling's type.

Left unread: section 8.2's CC-Request-Number 0 for an INITIAL_REQUEST or
EVENT_REQUEST, "an easy way to produce unique numbers", no requirement;
section 1.3's advertised Auth-Application-Id 4, RFC 6733's CER and CEA,
which this file does not print; the sentences repeating the commands'
ABNF (the Service-Context-Id "at the command level", CC-Request-Type in
every CCR, the Final-Unit-Action in every Final-Unit-Indication, "a maximum
of one instance of the same unit type"); the sentences saying what a value
is "applicable only" to or "to be used only" in, with no MUST
(Check-Balance-Result, Tariff-Change-Usage's UNIT_INDETERMINATE); the
"MUST" sentences of what a node does on receipt (failover, the T flag on a
retransmission, terminating a session on DIAMETER_BAD_ANSWER, the state
machines of section 7); the result codes a server answers with; and
section 10.2's RAR and RAA table, which allows its AVPs and forbids none.

## RFC 8506

RFC 8506 is read as RFC 4006 is, sections 3 to 9 and section 10.1's
occurrence table, for what it says of the credit-control AVPs and its own
CCR and CCA; where it repeats RFC 4006, its file quotes its own text. It
obsoletes RFC 4006, so its print of the commands is the one the Wireshark
plugin holds an application 4 message to beside TS 32.299's and OMA's,
and TS 29.212 reads the credit-control AVPs from it: a block with no scope,
or within a grouped AVP, holds in Gx's commands, and a block on the CCR or
CCA binds RFC 8506's print alone ([Precedence](#precedence)). An RFC has
one edition, so no block names `; Versions:`.

| | |
|---|---|
| sections 3 to 9.2 (the commands, the procedures, the AVPs, the result codes) | 68 blocks |
| section 10.1's table, each "0" cell of an AVP the command's body admits only through `* [ AVP ]` | 29 blocks |
| blocks | 97: 52 within a command, 20 within a grouped AVP, 25 on an AVP wherever read |
| readings | 104 |

| Rules | |
|---|---|
| `encoding`, a codec | 1: `ip-address` (Redirect-Address-IPAddress) |
| `encoding element` | 4, naming 4 entries of the registry; 2 rules checked, 2 not ([above](#elements)) |
| `length` | 1: User-Equipment-Info-EUI64, 8 octets |
| `range` | 1: the CCR's Auth-Application-Id 4 |
| `present-if` | 11: RFC 4006's nine, the CCR's Subscription-Id for a CHECK_BALANCE only where it holds no Subscription-Id-Extension, and QoS-Final-Unit-Indication's Redirect-Server-Extension for REDIRECT (8.64, 8.68) |
| `absent-if` | 2: the CCR's Multiple-Services-Credit-Control without a Requested-Service-Unit in an INITIAL_REQUEST (5.2, 8.16) |
| `excludes` | 13: Final-Unit-Indication and QoS-Final-Unit-Indication with TERMINATE holding nothing else, a G-S-U-Pool-Reference's unit type absent from its Granted-Service-Unit, and the members of User-Equipment-Info-Extension (4), Subscription-Id-Extension (4) and Redirect-Server-Extension (2) two at a time |
| `values` | 3: as RFC 4006's |
| `default` | 5: as RFC 4006's |
| `absent` | 29: table 10.1's "0" cells |
| `text-only` | 34 |

The rules RFC 4006 states the document states again, but for the CCR's
Tariff-Change-Usage: where RFC 4006 keeps it out of a request's
Multiple-Services-Credit-Control, section 8.16 has a client reporting units
either side of a tariff change use the Used-Service-Unit's, which turns on
an earlier answer, and is `text-only`. Its extension AVPs hold "exactly
one" member (sections 8.52, 8.58, 8.64): no two of the members its body
names, read member by member against those after it; that one is present
is not read, since each body's `[ AVP ]` may carry the one AVP of an
identifier type defined later. The MAC and the modified EUI-64 of
User-Equipment-Info-Extension are RFC 5777's and RFC 4291's elements, its
EUI-64 the clause's own 64 bits, and its IMEI and IMEISV TS 23.003's,
whose digits neither document says how an OctetString carries.

The text-only rules are RFC 4006's, and the extensions' identifiers and
addresses as texts other documents define (E.164, E.212, SIP URI, NAI,
URL), which no codec or element reads, Subscription-Id-Extension's one
identifier, which its `[ AVP ]` may carry, and its use beside
Subscription-Id where "full backward compatibility with [RFC4006] is
required", the node's.

The document disagrees with itself where the corpus reads around it:
section 8.34 has a Final-Unit-Indication with REDIRECT carry "the
Redirect-Server AVP or the Redirect-Server-Extension AVP (at least one)",
where its body holds no Redirect-Server-Extension and no `* [ AVP ]`, so
the block reads the Redirect-Server, as section 8.37 does. Left unread: as
RFC 4006's, section 8.2's CC-Request-Number, which "should be set to 0" for
an INITIAL_REQUEST or EVENT_REQUEST and so states no requirement; section
8.38's receiver "MAY be liberal" in the IPv6 text it accepts; and the
SHOULDs keeping RFC 4006's AVPs beside their extensions for older peers.

## RFC 7683, RFC 8581, RFC 8583 and RFC 7944

The overload control documents define AVPs and no command: RFC 7683's
OC-Supported-Features and OC-OLR, RFC 8581's peer reports, RFC 8583's Load
and RFC 7944's DRMP ride every application's requests and answers through
their `* [ AVP ]`. A block here has no scope or is within one of the
documents' own grouped AVPs, and holds wherever a document reading the AVP
reads it. RFC 8581 reprints RFC 7683's OC-Supported-Features and OC-OLR
with its own members, so its blocks are within them, and RFC 7683's hold in
its reading too ([Precedence](#precedence)). An RFC has one edition, so no
block names `; Versions:`.

| | RFC 7683 | RFC 8581 | RFC 8583 | RFC 7944 |
|---|---|---|---|---|
| sections read | 5 to 7 | 6 and 7 | 6 and 7 | 8 and 9 |
| blocks | 11: 8 on an AVP wherever read, 3 within a grouped AVP | 7, within a grouped AVP | 3, on an AVP wherever read | 1, on an AVP wherever read |
| readings | 17 | 9 | 7 | 1 |

| Rules | |
|---|---|
| `range` | 3: OC-Validity-Duration at most 86,400 seconds, OC-Reduction-Percentage at most 100 (RFC 7683 sections 7.5, 7.7), Load-Value at most 65535 (RFC 8583 section 7.3) |
| `default` | 1: OC-Validity-Duration 30 (RFC 7683 section 7.5) |
| `present-if` | 2: a peer report's SourceID, within an OC-OLR whose OC-Report-Type is PEER_REPORT (RFC 8581 sections 6.2.4, 7.2) |
| `members` | 3: a Load's SourceID, Load-Type and Load-Value, which an endpoint's report and an agent's carry alike (RFC 8583 section 6.1.1, section 6.1.2's same sentences of an agent's recorded `text-only` beside them) |
| `text-only` | 25: RFC 7683's 14, RFC 8581's 7, RFC 8583's 3, RFC 7944's 1 |

A receiver reads an OC-Validity-Duration above the maximum as the default
and ignores an OC-Reduction-Percentage above 100 (RFC 7683 sections 7.5,
7.7), which says how it recovers from such a value, not that one is sent:
the ranges are the values the clauses define.

The text-only rules are the node's support of the DOIC solution or of the
OC_PEER_REPORT feature, which decides an OC-Supported-Features in each
request, its OC-Feature-Vector's bits and an RFC 8581 node's SourceID and
OC-Peer-Algo; an answer read against its request (the answer's
OC-Supported-Features and OC-OLR only after the request's, its one
selected algorithm among the request's), which no block of these files is
scoped to, a feature vector's scope not telling a request's from an
answer's; the reports' sequence numbers against earlier reports; a report
type the reacting node advertised; the OC-Reduction-Percentage of the loss
algorithm, which the answer's OC-Supported-Features selects outside the
OC-OLR; and the default priority of a message with no DRMP, which a node's
configuration sets (RFC 7944 section 8). Whose DiameterIdentity a
SourceID holds, and a Load's Load-Type, HOST for an endpoint and PEER for
an agent (RFC 8583 sections 6.1.1, 6.1.2), are the sender's role, which
the message does not show. Left unread: the reserved value 0 of
OC-Feature-Vector and OC-Peer-Algo, which the clauses do not say is not
sent; RFC 8581 section 7.1's "A supporting node must also include the
SourceID AVP", no requirement in its lower case; and what a node does on
receipt (the OCS entries, abatement, stripping reports from untrusted
peers, RFC 7944's priority handling).

## RFC 5447, RFC 5777, RFC 5778 and RFC 5779

RFC 5447's MIP6-Agent-Info, MIP6-Home-Link-Prefix and MIP6-Feature-Vector,
RFC 5777's QoS-Resources and QoS-Capability with their members, and RFC
5779's PMIPv6 AVPs serve any application whose command admits them, so
their blocks have no scope or are within the documents' own grouped AVPs,
and hold wherever a document reading the AVP reads it: RFC 5447's in TS
29.272's MIP6-Agent-Info too ([Precedence](#precedence)).
RFC 5778 prints its own DER and DEA under MIP6I (7) and MIR and MIA under
MIP6A (8), which no other document's print shares. An RFC has one edition,
so no block names `; Versions:`.

| | RFC 5447 | RFC 5777 | RFC 5778 | RFC 5779 |
|---|---|---|---|---|
| sections read | 4 and 6 | 3 to 6 | 3 to 8 | 4 to 7 |
| blocks | 3: 2 on an AVP wherever read, 1 within a grouped AVP | 39: 22 on an AVP wherever read, 17 within a grouped AVP | 43: 38 within a command, 28 of them table 8.1's "0" cells, 1 within a grouped AVP, 4 on an AVP wherever read | 6: 5 on an AVP wherever read, 1 within a grouped AVP |
| readings | 4 | 47 | 43 | 9 |

| Rules | |
|---|---|
| `encoding`, a codec | 8: `ip-address` (RFC 5447's MIP-Home-Agent-Address within MIP6-Agent-Info, RFC 5777's IP-Address, IP-Address-Start and IP-Address-End, RFC 5778's MIP-Mobile-Node-Address and MIP-Careof-Address, RFC 5779's PMIP6-IPv4-Home-Address and PMIP6-DHCP-Server-Address) |
| `length` | 9: MIP6-Home-Link-Prefix 17 octets, RFC 5777's MAC-Address and MAC-Address-Mask-Pattern 6, EUI64-Address and EUI64-Address-Mask-Pattern 8, ETH-Ether-Type and ETH-SAP 2, MIP-Timestamp 8, PMIP6-IPv4-Home-Address 6, an IPv4 Address |
| `range` | 13: RFC 5777's IP-Mask-Bit-Mask-Width 0 to 128, Port, the four VLAN-IDs 0 to 4095, the two user priorities 0 to 7, Time-Of-Day-Start and -End, Day-Of-Month-Mask 0 to 2147483647 and Timezone-Offset; the DER's Auth-Request-Type AUTHORIZE_AUTHENTICATE (RFC 5778 section 5.1.1) |
| `default` | 10: RFC 5777's Direction BOTH, Negated False, Port-Start 0, Port-End 65535, Time-Of-Day-Start 0, Time-Of-Day-End 86399, the two fractional seconds 0 and Timezone-Flag UTC; RFC 5778's MIP-Replay-Mode None within MIP-MN-HA-MSA |
| `members` | 1: MIP6-Agent-Info's MIP-Home-Agent-Address or MIP-Home-Agent-Host (RFC 5447 section 4.2.1) |
| `bits` | 3: Day-Of-Week-Mask's and Month-Of-Year-Mask's undefined bits clear (RFC 5777 sections 4.2.4, 4.2.6), MIP6-Home-Link-Prefix's low 64 bits clear within RFC 5779's MIP6-Agent-Info (section 5.3) |
| `present-if`, `absent-if`, `excludes` | 7, 2, 1: Timezone-Offset with OFFSET, a Filter-Rule's QoS-Parameters for a shape or mark action, ETH-Ether-Type without ETH-SAP (RFC 5777); the MIR's MIP-MN-AAA-SPI, MIP-Authenticator and MIP-MAC-Mobility-Data for MIP6_AUTH_MN_AAA, the successful MIA's MIP-Mobile-Node-Address, and the MIA's MIP-MN-HA-MSA holding a MIP-MN-HA-SPI and a MIP-Algorithm-Type where the MIR's mode is MIP6_AUTH_MN_AAA (RFC 5778) |
| `values` | 1: the MIR's Auth-Request-Type AUTHORIZE_AUTHENTICATE for MIP6_AUTH_MN_AAA (RFC 5778 section 6.20) |
| `absent` | 28: RFC 5778 table 8.1's "0" cells |
| reading the request | 2: the MIA's MIP-MN-HA-MSA members after the MIR's MIP6_AUTH_MN_AAA |
| `text-only` | 21: RFC 5447's 1, RFC 5777's 11, RFC 5778's 3, RFC 5779's 6 |

RFC 5777's Treatment-Action values, listed in clause 5.1's prose and read
by no value table, are written as numbers, 1 shape and 2 mark. An absent
Time-Of-Day-End ends the window "one second before midnight", the
inclusive offset 86399. The MIA's MIP-MN-HA-SPI and MIP-Algorithm-Type
(RFC 5778 sections 6.4, 6.13) are read on the MIA through paths into its
MIP-MN-HA-MSA, whose own scope does not see the MIR's MIP6-Auth-Mode; the
MIP-MN-HA-MSA a server returns is taken for the "valid" one. An Address of
6 octets is an IPv4 one, so RFC 5779's PMIP6-IPv4-Home-Address is
`ip-address` and 6 octets. MIP6-Home-Link-Prefix's "low 64 bits of the
prefix" (RFC 5779 section 5.3) are the last 8 of RFC 5447's 17 octets,
bits 0 to 63; RFC 5779 prints its own MIP6-Agent-Info, which no other
document re-uses, so the rule holds there alone.

The text-only rules are what the node decides or learnt outside the
message (RFC 5778's User-Name copied from the Binding Update's MN-NAI
option, the Chargeable-User-Identity an accounting request carries "if it
is available in the home agent", RFC 5779's all-zero address where the LMA
delegates the assignment, a Service-Selection the MAG received from the
MN, whether a VLAN-ID-Range means a single VLAN-ID), what the server
assigned (RFC 5778's home address of a prefix-only assignment), two values
compared (RFC 5777's IP-Address-Start below IP-Address-End), a Classifier's
attributes against its Protocol, what an absent AVP means where that is no
value of the AVP's own (an address range's open end, a mask matching every
day or month, an open-ended window, a Time's or a grouped AVP's default,
QoS-Profile-Template's), the trailing prefix bits after the prefix length,
which no kind reads from a field, and texts no codec reads: RFC 5779's
Mobile-Node-Identifier NAI, Calling-Station-Id's link-layer identifier,
which RFC 5213 lets be of another length than the `mac-address` codec's
six octets, and a Service-Selection unique in the PMIPv6 domain.

The documents disagree with themselves where the corpus reads around
them: RFC 5777 clause 4.1.7.7's heading names IP-Mask-Bit-Mask-Width,
its text and clause 4.1.7.6's body IP-Bit-Mask-Width, as a correction
reads; clause 4.2.5 names Day-Of-Month-Mask Day-Of-Month, and clause 4.2.9
names Absolute-End-Time Time-Of-Day-End; RFC 5778 section 6.20 names
DIAMETER_ERROR_MIP6_AUTH_MODE DIAMETER_ERROR_AUTH_MODE, in a sentence on
the server's answer no block reads, and section 8.1's table gives the DER
MIP6-Agent-Info "1" and MIP-Mobile-Node-Address "1-2", where section
5.1.1's body prints them optional and has only the first DER carry them,
and the MIA MIP-MSA-Lifetime "1", an AVP its body holds only within
MIP-MN-HA-MSA, so no block reads those cells. Left unread: the header's
Application-ID, which RFC 5778 sections 5.1.1 and 5.1.2 set to 7 and no
rule reads; RFC 5447's MIP6-Feature-Vector "with value 0 MUST be
supported", a node's; the sentences repeating the ABNF (RFC 5777's
"Exactly one Classifier-ID AVP", "Exactly zero or one Protocol AVP"); what
a classifier or time window matches, and an AVP's absence making a
comparison "irrelevant"; TCP-Flag-Type's "unused" bits and RFC 5778
section 6.14's replay modes "supported by this specification", with no
MUST; the first DER and last DEA carrying the bootstrapping AVPs, with no
MUST; RFC 5778 section 8.2's accounting table, on RFC 6733's ACR and ACA,
which the document does not print; RFC 5779's User-Name in NAI form and
the LMA's Auth-Request-Type AUTHORIZE_ONLY (sections 4.1, 4.2.1), RFC 6733's
AVPs the file does not print and a request's interface the message does
not show; its LMA address information, RFC 5447's rule again (section
4.2.2), and the session mapping of section 6; and RFC 5447 section 6's and
RFC 5779 section 7's occurrence tables, generic requests and answers of
whichever application carries the AVPs, which no scope names, RFC 5779's
symbols undefined in the document.

## RFC 4005, RFC 7155 and RFC 4072

RFC 4005 and RFC 7155, which obsoletes it, are read alike for what they
say of the NASREQ AVPs and their own commands: RFC 4005's sections 1 to 9
and section 10.1's occurrence table, RFC 7155's sections 1 to 4 and
section 5.1's; where RFC 7155 repeats RFC 4005, its file quotes its own
text. RFC 4072 is read for its DER and DEA, sections 2 to 4 and section
5.1's table. A block with no scope, or within a grouped AVP, holds
wherever a document reading the AVP reads it, and a block on a command
binds the document's own print of it ([Precedence](#precedence)): RFC
4005's and RFC 7155's AA-Request and AA-Answer under NASREQ (1), RFC
4072's DER and DEA under Diameter EAP (5), which neither RFC 5778's prints
under MIP6I nor TS 29.273's share. An RFC has one edition, so no block
names `; Versions:`.

| | RFC 4005 | RFC 7155 | RFC 4072 |
|---|---|---|---|
| sections read | 1 to 9, 10.1 | 1 to 4, 5.1 | 2 to 4, 5.1 |
| table 10.1's or 5.1's "0" cells, each an AVP the command's body admits only through `* [ AVP ]` | 50: 34 in AA-Request, 16 in AA-Answer | 51: 34 and 17, the AA-Answer's Route-Record among them | 43: 31 in Diameter-EAP-Request, 12 in Diameter-EAP-Answer |
| blocks | 80: 63 within a command, 3 within a grouped AVP, 14 on an AVP wherever read | 80: 63 within a command, 3 within a grouped AVP, 14 on an AVP wherever read | 50, within a command |
| readings | 80 | 80 | 50 |

| Rules | |
|---|---|
| `length` | 15: Originating-Line-Info 2 octets, User-Password at most 128, CHAP-Ident 1, CHAP-Response 16, ARAP-Challenge-Response 8, Framed-IP-Address and Framed-IP-Netmask 4, in each NASREQ document; the DER's EAP-Key-Name empty (RFC 4072 section 4.1.4) |
| `range` | 14: Auth-Application-Id 1 in RFC 4005's AA-Request and AA-Answer (section 1.3) and in RFC 7155's AA-Request, Re-Auth-Request, Session-Termination-Request and Abort-Session-Request (section 1.5); Framed-MTU 64 to 65535, Framed-AppleTalk-Link and -Network and Login-TCP-Port at most 65535, in each |
| `requires`, `present-if`, `excludes` | 10, 5, 3: the AA-Request's CHAP-Auth with a CHAP-Challenge and its ARAP-Password without a User-Password or CHAP-Auth, the AA-Answer's Login-LAT-Service, -Node, -Group and -Port with Login-Service LAT, CHAP-Auth's CHAP-Response for CHAP with MD5, in each NASREQ document; RFC 4005's Accounting-Request and -Answer holding an Acct-Application-Id or a Vendor-Specific-Application-Id (sections 3.9, 3.10); the DEA's EAP-Reissued-Payload with DIAMETER_MULTI_ROUND_AUTH and no EAP-Payload, and its Reply-Message never beside an EAP-Payload (RFC 4072 sections 2.4, 2.8.3) |
| `absent` | 144: the tables' "0" cells |
| `text-only` | 19: RFC 4005's 8, RFC 7155's 7, RFC 4072's 4 |

The text-only rules are an earlier message (the State an AA-Request or DER
returns from the answer before, RFC 4005 section 9.3.4's State returned
unmodified), the server's choice (a Tunneling's Tunnel-Client-Auth-Id and
Tunnel-Server-Auth-Id "if an authentication name other than the default
is desired", a fatal error's EAP Failure), a request's OctetString value
(the AA-Answer's Framed-IP-Netmask after the request's 0xFFFFFFFF), the
EAP packet's Code within the EAP-Payload (no EAP Request in a DER, no
DIAMETER_MULTI_ROUND_AUTH beside an EAP-Success or EAP-Failure), and texts
no codec reads: the QoSFilterRule, Framed-Route's and Framed-IPv6-Route's
prefixes. RFC 4072's non-fatal error answer is the DEA with
DIAMETER_MULTI_ROUND_AUTH and no EAP-Payload, as the section's next
paragraph reads it, every other round's answer carrying its EAP Request.

The documents disagree with themselves where the corpus reads around
them: RFC 4005 sections 6.17.2 to 6.17.4 and RFC 7155 sections 4.4.11.5.2
to 4.4.11.5.4 name Login-Service Login-Service-Type, read as Login-Service;
the tables of RFC 4005 and RFC 4072 spell Framed-AppleTalk-Link, -Network
and -Zone Framed-Appletalk-, as RFC 7155 spells them throughout; and the
AppleTalk AVPs "MUST only be present in an authorization response"
(RFC 4005 sections 6.13.1 to 6.13.3, RFC 7155 4.4.10.7.1 to 4.4.10.7.3),
which the AA-Request's "0" cells read, where both documents'
Accounting-Request bodies print them. Left unread: the sections'
"is only present when" and "can only be present in" sentences, with no
MUST (ARAP-Password with an ARAP Framed-Protocol, the accounting octet and
packet counters of an INTERIM_RECORD or STOP_RECORD); the accounting
tables of RFC 4005 section 10.2, RFC 7155 section 5.2 and RFC 4072 section
5.2, whose cells turn on the Service-Type's access, and the last two's on
RFC 6733's ACR and ACA, which neither prints, and which in places contradict
the sections (Accounting-Input-Octets "1" in every ACR, where section 8.1
has it only in an interim or stop record); the sentences repeating the
ABNF (the answers' Result-Code, RFC 7155's Acct-Application-Id, the DER's
one EAP-Payload); the lower-case "it must have an Acct-Application-Id
inside" of a Vendor-Specific-Application-Id; the CER and CEA the documents
advertise in, RFC 6733's; the session's rules (one Session-Id, a STOP
record, a re-authorization) and what a node does on receipt (a
translation agent's RADIUS side, RFC 4005 section 9, its prohibited RADIUS
attributes, which have no AVP of their name); and the authorization AVPs
a successful answer carries "relevant to the service", the server's.

## ETSI TS 183 017

ETSI TS 183 017 V3.2.1 is read for Gq': the procedures of clause 5 for what
they state of one message, clause 6's use of the base protocol and clause
7's commands, result codes and every AVP clause of 7.3. The document is a
hand transcription, so its quotes are held to the text of the PDF it was
copied from ([above](#the-interpretations-file)), and every block is
`quoted_from_pdf`. Each command prints once, under Gq's 16777222. Most of
its AVPs are TS 29.209's, which clause 7.3 prints again with bodies and
values of its own, and Codec-Data TS 29.214's. TS 29.214 and ES 283 026
re-use its Reservation-Priority, whose blocks here are the AAR's and the
Media-Component-Description's this document prints, which neither shares;
the blocks with no scope hold where a document reading the AVP from this
one reads it, TS 183 020, built on it, among them.

| | |
|---|---|
| AVP clauses (clause 7.3, not its General clause) | 39 |
| with something to declare | 7, in 7 blocks |
| with nothing to declare | 32 |
| procedure clauses (5.1.1, 5.1.2) | 4 blocks |
| clause 6.5's routing, 7.1.3's RAR | 2, 1 blocks |
| blocks | 14: 7 within a command, 2 within a grouped AVP, 5 on an AVP wherever read |
| readings | 14 |

| Rules | |
|---|---|
| `encoding`, a codec | 1: `ip-filter from any to any` (Flow-Description) |
| `present-if` | 2: the AF's AAR and STR's Destination-Host beside the Destination-Realm both require |
| `default` | 4: Reservation-Priority DEFAULT in the AAR and in a Media-Component-Description, Flow-Usage NO_INFORMATION, SIP-Forking-Indication SINGLE_DIALOGUE |
| `text-only` | 7 |

Clause 6.5's "Both the Destination-Realm and Destination-Host AVPs shall be
present in the request" is read on the AF's requests, the AAR and STR, as
the Destination-Host present beside the Destination-Realm their bodies
require; the SPDF's RAR and ASR require both already. Flow-Description is
`ip-filter from any to any`: "permit", no options, no "!" and no
"assigned" at either end, the ports any list or range, as clause 7.3.17's
"Source and destination port (list or ranges)" allows.

The text-only rules are conditions on the procedure or an earlier message
(a hard-state reservation's Authorization-Lifetime, the initial AAR's
correlation identifier, a Reservation-Priority not modified) and counts no
kind makes: a RAR's Specific-Action values not combined, the
Binding-Input-List's pairs for each Media-Component-Description, a
Flow-Grouping without Flows alone, at most two Codec-Data AVPs, an offer
and an answer. The PDF prints words split by a space ("va lues",
"AF-Charging-Id entifier"), as a quote must print them, and none is quoted
here. Left unread: the "may" and "is used" sentences (the Gq
Auth-Application-Id "is used together with the command code", Specific-
Action's other values "not relevant ... and are not used"); clause 5.1.2's
AVPs that "shall have the same value" as the initial AAR's, six AVPs of an
earlier message; the SPDF's result codes (clauses 5.2.1, 7.2), which are
what a node answers with, and the vendor of each code, which clause 7.2
states and an Experimental-Result-Code's number alone does not tell;
Codec-Data's coding, TS 29.214's AVP, as that document reads it; the
capabilities exchange and transport of clauses 6.4 and 6.6; and Annex A's
SIP forking and Annex B's SDP mapping, what a P-CSCF does.
