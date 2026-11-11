# python-diameter

Two scripts for [python-diameter](https://github.com/mensonen/diameter), built
on the [model](../../docs/consumers.md):

- `validate.py` checks the library's command classes against the corpus, one
  document at a time.
- `generate.py` writes command modules per application, in the library's own
  shape.

Both carry PEP 723 metadata, so uv supplies seanchai and the library, and
either runs from any directory.

```sh
uv run integrations/python_diameter/validate.py TS29.229
uv run integrations/python_diameter/generate.py TS29.229 TS29.272 -o out/cx_s6a
uv run integrations/python_diameter/generate.py --all -o out/protocols \
    --wireshark specifications/wireshark
uv run integrations/python_diameter/generate.py --all -o out/protocols \
    --undefined supply --supply acme.dad
```

## Validating a checkout

`validate.py` takes references (`TS29.229`, `29.229`, `RFC6733`), `--all` or
`--claimed`, and prints which `diameter/__init__.py` it imported. One reference
ends with a count of its disagreements. Several get a heading each and then a
summary table, a row per document and a column per kind of finding. It exits 1
on any disagreement and 2 on a usage error.

```sh
# From a checkout of the library, against everything its README claims:
uv run ~/seanchai/integrations/python_diameter/validate.py --library . --claimed \
    --enumerated-as-integer --no-flags --grouped
# One document, its extras read against the same set:
uv run ~/seanchai/integrations/python_diameter/validate.py --library . --claimed \
    --enumerated-as-integer --no-flags --grouped TS29.229
```

| Option | Effect |
|---|---|
| `--library PATH` | import `diameter` from a checkout or its `src/` ahead of the installed package, refusing to go on if it imported something else; writes no bytecode there |
| `--ignore-extras` | report an `avp_def` entry the document's ABNF does not mention only if no checked document mentions it in that command and direction, or in that grouped AVP; hides nothing over one document |
| `--claimed [FILE]` | check the references FILE lists, one per line, `#` starting a comment, and imply `--ignore-extras` over that set; by default [`claimed.txt`](claimed.txt), what the README of python-diameter 0.9.0 claims; named references narrow what is checked and keep the set |
| `--enumerated-as-integer` | accept `AvpInteger32` for an Enumerated AVP; the library's `AvpEnumerated` is an alias of it |
| `--no-flags` | compare no M bits, neither the dictionary's defaults (`flag`) nor an explicit `is_mandatory` (`override`) |
| `--grouped` | hold each grouped class a checked command reaches against the AVP's body, at any depth: members, `is_required`, and `type_class` for Grouped members; without it only the top level is checked |
| `--wireshark PATH` | Wireshark's dictionary, by default `specifications/wireshark` after `seanchai corpus download --only wireshark`; a `name` finding where the library uses Wireshark's name (ignoring case and `-`/`_`) is hidden, does not count towards the exit status, and is counted in a closing `hidden:` line |
| `--names` | report those hidden names too |
| `--corpus DIR` | read another corpus than the installed one |
| `--summary-only` | print the summary without the findings |

Reading the results:

- `--no-flags` hides M-bit findings but does not excuse them. A default M bit
  is on the wire, and a peer can answer an M bit a table forbids with
  `DIAMETER_AVP_UNSUPPORTED`.
- `GenericSpec`, the library's class with no `avp_def`, reports every member
  of the body as missing under `--grouped`.
- An `is_required` of False in a merged class may be right for another
  document: RFC 7155 requires `Acct-Application-Id` and RFC 6733 does not.
- A member the document added after the release the library's docstring names
  is correct for that release.
- `--ignore-extras` reads only the checked documents. Run `--all
  --ignore-extras` to see the extras no document in the corpus mentions.

## Generating modules

`generate.py` takes references or `--all`, and `-o` for the output directory.

| Option | Effect |
|---|---|
| `--corpus DIR` | read another corpus than the installed one |
| `--wireshark PATH` | add Wireshark's AVP names as comments where they differ |
| `--undefined POLICY` | what to do with names the corpus declares defined nowhere ([below](#undefined-names)) |
| `--supply PATH.dad` | a sidecar supplying definitions, with `--undefined supply`; repeatable |

It reads the installed library for the names it references. It replaces the
output directory only if every file in it is one it wrote, and prints how many
additions each document needs. The output depends only on the corpus, the
Wireshark dictionary, the library version and the options, so regenerating
gives a reviewable diff.

### Output layout

```text
out/protocols/
  __init__.py            module list, the documents generated from, additions per module
  additions.py           what the library's dictionary and grouped classes lack
  ts29_229.py            one module per application and interface
  ts29_212_5a.py         ...interface clause appended where a document has several
  ts29_272_16777308.py   ...application id where several share one clause
```

A module holds one document's commands for one application id under one
interface clause, as `Model.applications` groups them. TS 29.212 gives
`ts29_212_5` (Gx), `_5a` (Gxx), `_5b` (Sd), `_5c` (St) and `_e_6` (S15). RFC
6733 gives `rfc6733_5` (CER, DWR, DPR), `_8` (RAR, STR, ASR) and `_9` (ACR).
TS 32.299's clause 6 gives `ts32_299_3` (Rf) and `_4` (Ro).

Each module follows `diameter/message/commands/*.py`: a `DefinedMessage` base
class per command code, and a Request and an Answer subclass with one
annotation and one `AvpGenDef` per member. Names are the library's where it has
them, and the document's otherwise. `is_required` comes from the brackets, and
`is_mandatory` is set wherever the flag rules fix the M bit:

```python
APPLICATION_ID = APP_3GPP_CX  # 16777216, 3GPP Cx/Px, TS29.230 table 4.1


class RegistrationTermination(DefinedMessage):
    code: int = 304
    name: str = "Registration-Termination"
    avp_def: AvpGenType
    ...


class RegistrationTerminationRequest(RegistrationTermination):
    """A Registration-Termination-Request message, clause 6.1.9."""
    session_id: str
    ...
    rtr_flags: int
    proxy_info: list[ProxyInfo]
    route_record: list[bytes]

    avp_def: AvpGenType = (
        AvpGenDef("session_id", AVP_SESSION_ID, is_required=True, is_mandatory=True),
        ...
        AvpGenDef("rtr_flags", AVP_TGPP_RTR_FLAGS, VENDOR_TGPP, is_mandatory=False),
        # * [ AVP ]
        AvpGenDef("proxy_info", AVP_PROXY_INFO, is_mandatory=True, type_class=ProxyInfo),
        AvpGenDef("route_record", AVP_ROUTE_RECORD, is_mandatory=True),
    )
```

`AVP_TGPP_RTR_FLAGS` is imported from `additions`. Imports are absolute, so a
module works where it was generated and inside the library.

### The additions

`additions.py` holds, in the shapes of `dictionary.py`, `constants.py` and
`grouped.py`:

- New entries for AVPs the dictionary lacks, under constants named the
  library's way (`AVP_TGPP_RTR_FLAGS = 659`), each with its defining clause as
  a comment. A new enumerated AVP gets `E_` constants for its values.
- Corrections for entries whose value class differs from the document's type
  (`AVP_RESULT_CODE` is AvpInteger32 where RFC 6733 says Unsigned32). Enumerated
  as AvpInteger32, and either string class for a string type, are left alone.
- Grouped dataclasses for every grouped reading the library's class does not
  match in member identities, nesting and M bits. Such a class is suffixed with
  its first document (`SupportedFeatures_3GPP2_X_S0013_006`). Readings with one
  body share a class.

Importing `additions` changes nothing. `register()` merges the new entries into
the library's dictionaries, which a module needs before it encodes an AVP only
`additions` defines. `register(corrections=True)` also replaces the corrected
entries.

### Adopting it in the library

The modules are additive and register nothing, since `all_commands` is built
once when `diameter.message.commands` is imported. To adopt them:

1. Put the modules in a package of their own beside the merged classes.
2. Merge `additions.py` into `constants.py`, `dictionary.py` and `grouped.py`,
   and drop the import from the modules.
3. Do not import the new package from `commands/__init__.py` above the
   `all_commands` table; its base classes would replace the merged classes for
   every code they share.
4. Add an opt-in dispatch from the header's application id and command code to
   a module's base class, built from each module's `APPLICATION_ID`. The tests
   do it by hand: `Message.from_bytes(data, plain_msg=True)`, then
   `ts29_229.UserAuthorization.type_factory(header)(header, avps)`.

### Limits

- Occurrence bounds: `AvpGenDef` has `is_required` and no minimum or maximum.
  Bounds other than `[ X ]`, `{ X }`, `*[ X ]` and `1*{ X }` are kept as a
  trailing comment, and nothing enforces them.
- A member printed twice gets one list attribute, with a comment naming both
  lines.
- Enumerated values get `E_` constants only for the AVPs `additions` adds.
- The library leaves `header.application_id` to the caller. `APPLICATION_ID`
  is the value to set.
- An M bit the flag rules leave open takes the dictionary's default.
- A hole is an `AvpGenDef` with the reason as a comment (`# hole: TS29.061
  3GPP-Session-Stop-Indicator: no data_type, no flag_rules`). A name with no
  identity, like `* [ AVP ]`, is a comment.

### Undefined names

Some members the corpus's documents use are defined nowhere
([consumers.md](../../docs/consumers.md#undefined-names)). `--undefined` sets
the policy, and `__init__.py`'s docstring records what became of each name:

- `hole`, the default: a comment in its place.
- `drop`: nothing in its place; the class's docstring says what it dropped and
  whether the ABNF required it.
- `placeholder`: a comment in its place, labelled as the consumer's choice.
- `supply`: definitions from one or more `--supply PATH.dad` sidecars, written
  as ordinary members, with an `additions.py` entry where the library lacks
  the identity. A sidecar claiming an identity the corpus defines is refused.

An `Alias` in a model passed to `generate()` gives the member the named AVP's
constant, with a comment saying what it was read as.

### Table marks and application ids

The ABNF decides a class's members. A document's table marks
([consumers.md](../../docs/consumers.md#the-model)) become comments on them,
read from the tables of the command's interface clause: TS 29.212's Gxx module
reads table 5a.4.0.1 and its Gx module 5.3.0.1. A TS 32.299 member marked `-`
("not used") stays, with a comment saying so. An `Acc-Type` of plain `All` is
not repeated.

The application id comes from the command header, or from the `Application
Scope` block where the headers print none; the module's docstring then names
the clause. `rfc6733_8` and TS 29.234's Wa, Wd, Wm and Wg modules have
`APPLICATION_ID = None`, because those commands carry the application they
serve.

A command printed twice in one interface clause gets one class when the bodies
agree, and a second class named with its clause when they differ
(`AaRequest_9_2_2_5_1`). `type_factory` returns the first. A class's
`header.is_request` is its header's REQ flag, with a comment where it
disagrees with the command's name.
