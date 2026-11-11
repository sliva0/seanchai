"""The consumer model: the corpus resolved into objects a generator can use.

Built once from a `corpus.Corpus`. Message entries point at `Avp` objects, a
grouped AVP lists its members, and every AVP carries its `(vendor-id, code)`,
type and flag rules. A name the corpus cannot complete is a `Hole`, allowed
only as far as `Model.build`'s `holes` policy permits; `Undefined AVP` names
follow its `undefined` policy.

Where the AST holds conflicting statements this layer picks one without
comment; the linter reports the conflicts. docs/consumers.md states the
resolution order, the hole and undefined policies, and cross-release
citations.
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
