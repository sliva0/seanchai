"""The error an edit layer raises, shared by `corrections` and `interpretations`."""

from ..errors import SeanchaiError


class CorrectionError(SeanchaiError, ValueError):
    """A declaration that does not apply: declared wrongly, or no longer
    matching what it expects."""
