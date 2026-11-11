"""Reading the prose fields of the committed TOML files.

TOML files keep to 80 columns, so a long `reason` wraps in a multi-line string
whose line breaks and indentation are layout. Every reader passes such a field
through here, so it reads as the same one line however the file wraps it. A
field whose whitespace matters (a patch's `find`, a name) never comes here
(docs/development.md).
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
