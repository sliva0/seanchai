"""The base of every error this library raises on purpose.

Each module keeps its own error, and each stays what it was (most are a
`ValueError`), so `except seanchai.SeanchaiError` catches any refusal and
nothing else changes. This module imports nothing, so `seanchai` can re-export
the base without pulling in any machinery.
"""

__all__ = ["MissingExtraError", "SeanchaiError"]


class SeanchaiError(Exception):
    """A failure this library reports on purpose."""


class MissingExtraError(SeanchaiError, ImportError):
    """An operation needs `seanchai[extract]`, which is not installed: `python-docx`
    and `pypdf`, what reading and validating source documents takes. The model,
    the export and the lookup commands need neither."""

    def __init__(self, what: str) -> None:
        super().__init__(f'{what}: pip install "seanchai[extract]"')
