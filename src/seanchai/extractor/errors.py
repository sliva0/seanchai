"""Errors raised while turning a source document into a `.dad` AST.

`ExtractionError` is the base every extraction failure inherits, so a caller
running a batch over a corpus can ask "did this document fail?" with one
`except` — a source-document problem and a rotted input patch are the same
answer to that question, even though they come from different modules.

`boundary()` makes that promise total. The extractor reads documents nobody
validated, through libraries that signal a malformed file with whatever
exception their own layer raises — `KeyError` from a lookup table, `ValueError`
from `int()`, pydantic's `ValidationError`, `zipfile.BadZipFile` from a docx
that is not one. Naming each of them at each call site would still leave the
next one uncovered, so the public entry points close the set instead.
"""

import contextlib
from collections.abc import Generator

from ..errors import SeanchaiError


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
