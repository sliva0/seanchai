"""Reading the prose fields of the committed TOML files.

TOML files keep to 80 columns, so a long `reason` is a multi-line basic string
and its line breaks and indentation are layout, not text. Every reader passes
such a field through here, so the value is the same one line of prose however
the file wraps it. A field whose whitespace means something (a patch's `find`,
a name) never comes here (docs/development.md#conventions).
"""

from collections.abc import Collection, Mapping
from typing import Any


def collapse(text: str) -> str:
    """`text` stripped, with every run of whitespace made one space."""
    return " ".join(text.split())


def collapse_fields(table: Mapping[str, Any], keys: Collection[str]) -> dict[str, Any]:
    """A copy of `table` with its text fields named in `keys` collapsed. A value
    that is not text is kept, for the reader's own check to refuse or accept."""
    return {
        key: collapse(value) if key in keys and isinstance(value, str) else value
        for key, value in {**table}.items()
    }
