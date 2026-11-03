"""The base every error this library raises on purpose derives from.

Each module keeps its own error, and each error stays what it was (most are a
`ValueError`), so `except seanchai.SeanchaiError` is one way to ask whether the
library refused, and nothing else changes. This module imports nothing, so that
`seanchai` itself can re-export the base without pulling in any machinery.
"""


class SeanchaiError(Exception):
    """A failure this library reports on purpose."""
