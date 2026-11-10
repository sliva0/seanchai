"""The errors a build or a query raises: `ModelError`, and the two a build
over a corpus with holes it refuses raises."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import corpus
from ..errors import SeanchaiError

if TYPE_CHECKING:
    from ._types import Hole


class ModelError(SeanchaiError, ValueError):
    pass


class IncompleteCorpusError(ModelError):
    """A build over a corpus with holes it refuses: every hole under
    `HolePolicy.NONE`, and by default those its record does not list. `holes`
    lists every one."""

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
    """A record of known holes listing what no longer is one, so that working
    a hole off shrinks the record; `entries` lists every stale one."""

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
