"""The `seanchai` command.

`_consumer` holds the commands reading a corpus, `_files` those checking and
rewriting `.dad` files, and `_corpus` the maintainers' `corpus` group. Exit
status 1 means an error or a finding, 2 a usage error.
"""

from ._base import main

# Each registers its commands on `main`, and help lists them in this order.
# isort: off
from . import _consumer, _files, _corpus  # noqa: F401
# isort: on

__all__ = ["main"]
