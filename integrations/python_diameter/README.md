# python-diameter

Two scripts over the [model](../../docs/consumers.md) for
[python-diameter](https://github.com/mensonen/diameter): `validate.py`
checks the library's merged command classes against one specification at a
time, and `generate.py` writes the protocol-specific classes the library
could carry beside them. Both carry PEP 723 metadata, so uv supplies
seanchai (and, for `validate.py`, the library).

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 TS29.272 -o out/cx_s6a
uv run integrations/python_diameter/generate.py --all -o out/protocols \
    --dictionary specifications/wireshark
```

`generate.py` takes references (`TS29.229`, `29.229`, `RFC6733`) or
`--all`, `--corpus` for a corpus other than the repository's `dad/`, and
`--dictionary` for Wireshark's AVP names. It replaces the output directory
only if every file in it is one it wrote. The output is a function of the
corpus and the dictionary alone, byte for byte: regenerating after a corpus
change gives a reviewable diff.

## Output layout

```
out/protocols/
  __init__.py        module list and the documents generated from
  _base.py           AvpDef, Rule, ProtocolMessage: copied from _base.py here
  avps.py            every AVP definition, deduplicated
  ts29_229.py        one module per application and interface
  ts29_212_5a.py     ...interface clause appended where a document has several
  ts29_272_16777308.py   ...application id where several share one clause
```

A module groups what `Model.applications` groups: one document's commands
for one application id under one interface clause. TS 29.212 gives
`ts29_212_5` (Gx), `_5a` (Gxx), `_5b` (Sd), `_5c` (St) and `_e_6` (S15); TS
29.273 gives one module per reference point, three of them sharing
16777250; RFC 6733 gives `rfc6733_5` (CER, DWR, DPR), `_8` (RAR, STR, ASR)
and `_9` (ACR); TS 32.299's clause 6 gives `ts32_299_3` (Rf) and `_4`
(Ro), and RFC 5778's clause 5 `rfc5778_7` and `_8`.

`avps.py` holds one `AvpDef` per distinct reading — name, code, vendor-id,
value class, flag rules, grouped members with their cardinality, enumerated
values and reserved ranges, and the defining documents:

```text
SERVER_CAPABILITIES = AvpDef(
    "Server-Capabilities", 603, 10415, AvpGrouped, FlagRules(must="MV"),
    members=(
        Rule(MANDATORY_CAPABILITY, max=None),
        Rule(OPTIONAL_CAPABILITY, max=None),
        Rule(SERVER_NAME, max=None),
        Rule(ANY_AVP, max=None),
    ),
    defined_in=("TS29.229",),
)
```

Readings that agree on everything that goes on the wire are one definition
whichever documents print them (TS 29.329's re-print of TS 29.229's
`Public-Identity`). Readings that differ stay apart, each suffixed with its
first defining document — `CC_TIME__RFC4006` and `CC_TIME__RFC8506`, since
RFC 8506 drops the P flag; `ALLOCATION_RETENTION_PRIORITY__TS29_212` and
`__TS29_272`, since TS 29.272 extends it — and each command names its own
document's. `BY_IDENTITY` lists every reading under its `(vendor-id, code)`.

A command module carries a class per command code and a Request and Answer
class per direction, whose rule table names the AVP definitions and carries
only what varies per command: presence (`FIXED` for `< >`, `REQUIRED` for
`{ }`, optional by default), `min` where RFC 6733 §3.2's default for the
presence does not give it, and `max` (`None` for `*`):

```python
APPLICATION_ID: int | None = 16777216


class UserAuthorization(ProtocolMessage):
    """The User-Authorization command, code 300."""

    code: int = 300
    name: str = "User-Authorization"
    application_id = APPLICATION_ID


class UserAuthorizationRequest(UserAuthorization):
    """User-Authorization-Request, clause 6.1.1."""

    session_id: str
    drmp: int
    vendor_specific_application_id: Grouped
    ...

    is_request = True
    is_proxyable = True
    avp_rules = (
        Rule(avps.SESSION_ID, FIXED),
        Rule(avps.DRMP),
        Rule(avps.VENDOR_SPECIFIC_APPLICATION_ID, REQUIRED),
        ...
        Rule(ANY_AVP, max=None),
        Rule(avps.PROXY_INFO, max=None),
        Rule(avps.ROUTE_RECORD, max=None),
    )
```

`COMMANDS` maps each command code to its command class, as the library's
`all_commands` does.

## Against the library today

`_base.py` stands in for the base classes the library would ship, and runs
on python-diameter 0.9.0 unchanged. It encodes and decodes by the rule
tables: every AVP a rule names is built from, and re-read as, its
definition's own value class with its code and vendor set, so TS 29.214's
`Codec-Data` is OctetString and `Authorization-Lifetime` Unsigned32 where
the library's dictionary says UTF8String and Integer32. The dictionary is
the fallback only for AVPs the generated set does not know: those landing in
`* [ AVP ]`, and a hole whose type no document states. It also builds a
grouped AVP's value class from its definition's members, sets the header's
command code, flags and (on a fresh message) application id, and derives
the library's `avp_def` tuples for code that introspects them.

Decoding fills, for each received AVP, the first rule naming its identity
that still has room, so a body naming one AVP twice gets its occurrences in
order; anything past every rule's maximum goes to the additional AVPs, so
re-encoding keeps it. Encoding checks every member's set values against its
`min` and `max` and raises `OccurrenceError`, a subclass of the library's
`AvpEncodeError` naming the command and member: a CER whose
`host_ip_address` is empty is refused, since RFC 6733 requires
`1* { Host-IP-Address }`. `0*1< X >` is fixed in position but optional.
`tests/test_python_diameter_generate.py` imports every generated module
against the library, round-trips a Cx UAR through `Message.from_bytes`, and
pins each of these behaviours.

**Backwards compatibility.** The generated package is additive: nothing in
it touches the library's merged classes, its `all_commands` table or its
AVP dictionary, so a user who does not import it sees no change. Choosing
the protocol-specific classes for a received message — by application id,
and by configuration where an id is shared (TS 29.273's SWa, STa and SWd)
or absent — is the library's switch to design; the per-module
`APPLICATION_ID` and `COMMANDS` are what it would read.

**Where it departs from the library's conventions**, and why:

- AVPs are `AvpDef` objects referenced by name, not `AVP_*`/`VENDOR_*`
  constants repeated in every `AvpGenDef` with a separate `AVP_DICTIONARY`
  entry: one definition carries what the library spreads over
  `constants.py`, `dictionary.py`, `grouped.py` and each command's
  `avp_def`. `avp_def` itself still exists, derived.
- Grouped AVP value classes are built at import from the definition's
  members rather than written out as dataclasses, so attributes inside a
  grouped value are not visible to an IDE and the class annotations say
  `Grouped`. Writing them out would repeat every member list.
- Enumerated values live on the definition as `(name, value)` pairs in the
  document's spelling (TS 32.299's `"PS to CS Transfer"`), not as `E_*`
  constants. An enumeration whose clause defines its values elsewhere has a
  comment naming the source above it (`# Values: TS 32.422 [23] for Trace
  Depth (TS29.272 clause 7.3.67).`) and no values.
- Attribute names are derived mechanically (`_base.attribute_name`):
  `3GPP-IMSI` is `tgpp_imsi` where the library writes some `3GPP-` AVPs
  without the prefix, a leading digit gets `avp_` (`avp_5qi`), a Python
  keyword or an attribute the base classes use gets a trailing underscore
  (`class_`), and a body naming one AVP twice (TS 29.345's
  `WiFi-P2P-Assistance-Info` prints `[ WLAN-Link-Layer-Id-List ]` twice)
  gets a counter through `Rule(..., attr=...)`.
- Classes are named after the document's own command names: TS 29.212's
  `CC-Request` is `CcRequest`, not the library's `CreditControlRequest`.
- The M flag follows the reading's flag rules (M in Must or Must-not)
  instead of the dictionary default, which is what makes the classes
  protocol-specific on the wire as well as in their member lists. Where the
  rules leave it open (M in May) it is unset; only a hole with no flag
  rules takes the dictionary's default.
- Unset required members raise at encode time, where the library's
  `generate_avps_from_defs` only logs them unless asked to be strict.
- `DiameterIdentity` is held as `AvpOctetString` and `DiameterURI` as
  `AvpUtf8String`, matching how the library's dictionary holds Origin-Host
  and Redirect-Host; `IPFilterRule` and `QoSFilterRule` as octets.
- `_base.py` registers nothing in the library's global dictionary, so the
  library's own classes and `Message.from_bytes` still type a received AVP
  by it; the generated classes re-read the payload by their definitions.

## Wireshark names

With `--dictionary` (the downloader's `specifications/wireshark`), an
`AvpDef` whose name Wireshark spells differently carries Wireshark's
spelling, and `avps.BY_WIRESHARK_NAME` maps that spelling to the readings
it names, for tooling that names AVPs Wireshark's way:

```text
USER_DATA = AvpDef(
    "User-Data", 606, 10415, AvpOctetString, FlagRules(must="MV"),
    defined_in=("TS29.229",),
    wireshark_name="Cx-User-Data",
)
```

Attributes and identifiers keep the document's spelling. Without a
dictionary, `wireshark_name` is None throughout and `BY_WIRESHARK_NAME` is
empty.

## Holes

The model is built non-strictly, and a hole is never dropped. A member
whose AVP the corpus knows the identity of but cannot complete is an
`AvpDef` with the missing fields `None` and `hole` set (RFC 4072's
`EAP-Payload` has no flag rules), so it still decodes. A name the corpus
resolves to no identity is an `AvpHole`, listed in `avps.HOLES`; its rule
stays in the table and has no attribute. Every rule naming either carries
the reason as a comment:

```text
        Rule(avps.EAP_PAYLOAD, REQUIRED),  # hole: RFC4072 EAP-Payload: no flag_rules
```

A grouped hole has no members (the model keeps none), so its value class
holds only `additional_avps`.

## What the documents leave to the reader

**Application ids.** The application id comes from the command header the
document prints, or, where the headers print none, from the
`Application Scope` block that records the document's statement in prose;
such a module's docstring names the clause (`The command headers print no application id;
clause 5.1 states Gx's.`). The 3GPP blocks are read from the documents (TS
29.154, 29.212, 29.214, 29.215, 29.217, 29.219, 29.343, 29.368, 29.468);
those for RFC 4004, 4005, 4006, 4072, 5778, 6733, 7155, 8506 and TS 32.299
are corrections citing the clause, since each words it differently. Two
readings are worth knowing: RFC 4005 clause 1.3 gives the commands it takes
from the base protocol "the Base application id value", and the block
follows clause 11.3 and RFC 7155 in giving all of clause 3 the NASREQ id 1;
RFC 6733's ACR is the base accounting application's 3, the split accounting
model of clause 9.3, where coupled accounting carries the using
application's id.

`rfc6733_8` alone keeps `APPLICATION_ID = None`: clause 2.5 says RAR, STR
and ASR "MUST carry the Application Id of the application" they serve.

**Commands printed twice.** A document that prints one command twice in one
interface clause gets one class when the bodies agree (TS 29.273's STa STR,
clauses 5.2.2.2.3 and 5.2.2.4.1, whose docstring cites both) and a second
class named with its clause when they differ (TS 29.273's clause 9 AAR,
application 16777272: `AaRequest_9_2_2_5_1`). `type_factory` returns the first.

**Header flags.** A class's `is_request` is its header's REQ flag. Where a
header's flag disagrees with the command's name the class says so in a
comment; the corpus corrects the two misprints known (TS 29.336 clause
8.2.5's RIR printed without REQ, TS 29.273 clause 7.2.2.1.4's AAA with it),
so the committed corpus generates no such class.
