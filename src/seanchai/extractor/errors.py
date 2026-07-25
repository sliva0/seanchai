"""Errors raised while turning a source document into a `.dad` AST.

`ExtractionError` is the base every extraction failure inherits, so a caller
running a batch over a corpus can ask "did this document fail?" with one
`except` — a source-document problem and a rotted input patch are the same
answer to that question, even though they come from different modules.
"""


class ExtractionError(ValueError):
    pass
