"""Errors raised while turning a source document into a `.dad` AST.

Every extraction failure is an `ExtractionError`, so a batch can catch one
type. The public entry points run inside `boundary()`, which re-raises
whatever a library throws on a malformed document (`KeyError`, `ValueError`,
pydantic's `ValidationError`, `zipfile.BadZipFile`, ...) as one.
"""

import contextlib
from collections.abc import Generator

from ..errors import SeanchaiError

__all__ = ["ExtractionError", "boundary"]


class ExtractionError(SeanchaiError, ValueError):
    pass


@contextlib.contextmanager
def boundary(operation: str) -> Generator[None]:
    """Re-raise anything that is not already an `ExtractionError` as one."""
    try:
        yield
    except ExtractionError:
        raise
    except Exception as error:
        raise ExtractionError(
            f"{operation}: {type(error).__name__}: {error}"
        ) from error
