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
from ..dad.ast import (
    AvpFlag,
    Category,
    Codec,
    CommandFlag,
    DataType,
    LengthUnit,
    PredicateKind,
    RegistryKind,
    ValueKind,
)
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
    Command,
    Constraint,
    Element,
    ElementTable,
    Enumerated,
    Grouped,
    Hole,
    HolePolicy,
    Marks,
    Member,
    MemberPath,
    Message,
    Met,
    Placeholder,
    Reached,
    Supplied,
    SupplyKey,
    Undefined,
    UndefinedPolicy,
    ValueTable,
)
from ._wire import VENDORS, Vendor, basic_type

__all__ = [
    "VENDORS",
    "Alias",
    "Allocation",
    "AnswerMessage",
    "Application",
    "Avp",
    "AvpFlag",
    "Category",
    "Codec",
    "Command",
    "CommandFlag",
    "Constraint",
    "DataType",
    "Element",
    "ElementTable",
    "Enumerated",
    "FlagRules",
    "Grouped",
    "Hole",
    "HolePolicy",
    "IncompleteCorpusError",
    "LengthUnit",
    "Marks",
    "Member",
    "MemberPath",
    "Message",
    "Met",
    "Missing",
    "Model",
    "ModelError",
    "Placeholder",
    "PredicateKind",
    "Reached",
    "RegistryKind",
    "StaleHoleRecordError",
    "Supplied",
    "SupplyKey",
    "Undefined",
    "UndefinedPolicy",
    "ValueKind",
    "ValueTable",
    "Vendor",
    "basic_type",
    "supplied_from",
]
