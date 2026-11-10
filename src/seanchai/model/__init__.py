"""The consumer model: the corpus resolved into objects a consumer can use.

The `.dad` AST mirrors a file one-to-one and is allowed to contradict itself;
this layer is the opposite. It is built once from a `corpus.Corpus` and hands
a consumer what a generator or validator actually wants: a message whose ABNF
entries point at real AVP objects rather than names, a grouped AVP that can
enumerate its members, an AVP that knows its `(vendor-id, code)` identity, its
type and its flag rules. The AST stays public underneath for anything this
model does not cover.

Where the AST keeps two disagreeing statements, this layer has to pick one,
and the policy is deliberately small:

- A name resolves, in order, to the specification's own definition, then to
  the origin a re-used row cites (read recursively in the origin's own
  context, so an indirect citation still lands on the real definition), then
  to an AVP-table row, then to a `; Bases:` document. A local definition
  winning over the re-used listing is what makes an *extension* (TS 29.272
  re-defines nine of RFC 6733's AVPs with extra members) mean what the
  extending document says; a plain re-print resolves to the origin's copy,
  which is also the copy the linter checks.
- A re-used name's flag rules are the citing document's where its own AVP
  table states them (RFC 6733 sections 4.1 and 4.5 leave them to the
  application): through TS 29.229, RFC 4590's `Digest-Qop` is M in Must, as
  table 6.3.0.1 says, and through RFC 4590 M in May. The origin supplies the
  rest, each flag the row places in no column included, and its own reading
  is untouched. The re-used table's M-bit cell ranks between the two: TS
  29.272's `RAT-Type`, `MUST` there, is M in Must, where TS 29.212 forbids
  it. The linter's `reused-row-mismatch` reports the disagreement between
  table row and origin and says which side this follows.
- A grouped AVP defined elsewhere keeps its defining document's body, but
  each member the citing document defines, tabulates or re-uses is read
  through the citing document, by the rules above, where that reading is
  the same `(vendor-id, code)`; one it says nothing of, or reads as another
  AVP, stays the origin's reading. TS 32.299's `Supported-Features` holds
  TS 32.299's `Feature-List`, M in Must, where TS 29.229's holds M in Must
  not; its `M2M-Information` holds oneM2M's `Originator`, not its own.
- A citation means the copy the drafting rules on references say
  (`corpus.Corpus.resolution`): the newest in the citing document's
  release, the version a specific reference names, or the final version of
  a document that ended before the citing release, or a 3GPP2 revision or
  later release's copy an entry of the corpus's `corpus.toml` lets stand in for
  the one cited (`corpus.Rules.stand_ins`, `release_stand_ins`), or state a
  named field of it (`release_fills`). An AVP reached outside the citing
  document's release, or revision, says so in `across_releases`; an older
  copy answers only through such a citation, never a reference-level query.
- The linter, not this module, is where the conflicts live: anything
  `reused-body-differs` or `table-definition-mismatch` would report is
  resolved here by the order above without comment. Run the linter to see
  what the policy papered over.
- An AVP-table row with no matching definition and no re-used listing is
  in the vendor its Vendor-ID cell states where its table prints one (oneM2M
  TS-0004), else IETF-space (vendor 0) where its V flag is Must-not and the
  file's own `; Vendor-ID:` space otherwise, exactly as the linter's
  `duplicate-identity` rule reads it (`AvpTableRow.stated_vendor`); a
  definition written with no vendor-id is IETF-space, the wire format's
  reading of an absent vendor.
- A name tabulated in more than one of a file's AVP tables takes its table
  facts (flag rules; type and code when nothing defines it) from the first
  row in file order. `Model.table_rows` returns all of them, for the
  documents whose per-interface tables disagree.
- A field the first reading in that order leaves unstated is taken from the
  next reading, as long as every field both state agrees (a table row whose
  V flag states no vendor infers it from its file, and agrees with any): a
  re-print tabulated
  nowhere takes its origin's flag rules. A disagreeing reading fills
  nothing and is named in the hole instead.
- An IETF-space AVP whose readings leave the M or V bit unplaced takes
  RFC 6733's rule for it (`FlagRules`): V is Must-not (section 4.1.1), and
  M is the using application's to set (section 4.1), which no document
  along the order did.

An `Avp` has every field; a name the corpus cannot complete is a `Hole`
instead, whether a field is unstated everywhere along the order or the name
resolves nowhere at all. `Model.build` allows the holes its `holes` policy
does (`HolePolicy`): by default those the corpus's record of known holes
lists (`corpus.HoleRecord`), refusing any other and any entry naming a hole
that no longer exists; `NONE` refuses recorded holes too, and `ANY` builds
anything. `Model.holes` lists them and `Member.avp` is `None` with
`Member.hole` saying why. `Member.avp` is also `None`, with no hole, for RFC
6733's `* [ AVP ]` wildcard, which is grammar rather than a reference.

A name an `Undefined AVP` block declares is the last reading along the
order, after the bases: it explains the failure and defines nothing, so a
definition that appears upstream or in a base wins without it. By default
it is a `Hole` missing `Missing.UNDEFINED`; `Model.build(...,
undefined=...)` takes the consumer's answer instead (`UndefinedPolicy`):
drop the member, keep it as an untyped `Placeholder`, or read a definition
the consumer `Supplied` (or an `Alias` for an AVP the corpus does define).
Only a block's name is open to that choice: a name resolving nowhere without
one, and a field no reading states, stay holes under every policy.
"""

from ..corpus import Missing
from ..dad.ast import AvpFlag, CommandFlag, DataType, RegistryKind, ValueKind
from ._errors import IncompleteCorpusError, ModelError, StaleHoleRecordError
from ._flags import FlagRules
from ._model import Model
from ._supply import supplied_from
from ._types import (
    Alias,
    Allocation,
    AnswerMessage,
    Application,
    Avp,
    Enumerated,
    Grouped,
    Hole,
    HolePolicy,
    Marks,
    Member,
    Message,
    Placeholder,
    Supplied,
    SupplyKey,
    Undefined,
    UndefinedPolicy,
    ValueTable,
)

__all__ = [
    "Alias",
    "Allocation",
    "AnswerMessage",
    "Application",
    "Avp",
    "AvpFlag",
    "CommandFlag",
    "DataType",
    "Enumerated",
    "FlagRules",
    "Grouped",
    "Hole",
    "HolePolicy",
    "IncompleteCorpusError",
    "Marks",
    "Member",
    "Message",
    "Missing",
    "Model",
    "ModelError",
    "Placeholder",
    "RegistryKind",
    "StaleHoleRecordError",
    "Supplied",
    "SupplyKey",
    "Undefined",
    "UndefinedPolicy",
    "ValueKind",
    "ValueTable",
    "supplied_from",
]
