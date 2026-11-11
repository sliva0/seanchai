"""The errors a model build or query raises."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import corpus
from ..errors import SeanchaiError

if TYPE_CHECKING:
    from ._types import Hole


class ModelError(SeanchaiError, ValueError):
    pass


class IncompleteCorpusError(ModelError):
    """A build met holes its `HolePolicy` refuses; `holes` lists them."""

    def __init__(self, holes: tuple[Hole, ...], *, unrecorded: bool = False) -> None:
        self.holes = holes
        listing = "".join(f"\n  {hole}" for hole in holes)
        # Only an undefined name is the consumer's to answer for.
        answer = (
            ", and undefined=... answers for the undefined names"
            if any(hole.undefined is not None for hole in holes)
            else ""
        )
        count = f"{len(holes)} hole{'' if len(holes) == 1 else 's'}"
        what = f"{count} its record does not list" if unrecorded else count
        super().__init__(
            f"the corpus has {what}"
            f" (Model.build(..., holes=HolePolicy.ANY) builds the rest{answer}):"
            f"{listing}"
        )


class StaleHoleRecordError(ModelError):
    """The record of known holes lists entries that are no longer holes;
    `entries` lists them."""

    def __init__(self, entries: tuple[corpus.KnownHole, ...]) -> None:
        self.entries = entries
        listing = "".join(f"\n  {_known(entry)}" for entry in entries)
        count = f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}"
        super().__init__(
            f"the corpus's record of known holes has {count} naming no hole, which"
            f" belong{'s' if len(entries) == 1 else ''} out of it:{listing}"
        )


def _known(entry: corpus.KnownHole) -> str:
    return f"{entry.document} {entry.name}: missing {', '.join(entry.missing)}"
