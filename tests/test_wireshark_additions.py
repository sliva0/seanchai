"""The staged Wireshark additions are what the generator writes today.

The generator checks that every patch applies to the pinned dictionary on
its own, in order, and after the defect series; this pins the committed
patches to its output, so a corpus change that adds, drops or reshapes an
absent AVP shows up as a stale series.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "integrations" / "wireshark" / "additions.py"
_COMMITTED = _ROOT / "integrations" / "wireshark" / "additions"


def _generator():
    spec = importlib.util.spec_from_file_location("additions", _SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through the module's entry.
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.sources
def test_the_committed_additions_are_the_generators_output(tmp_path):
    output = tmp_path / "additions"

    assert _generator().main(["-o", str(output)]) == 0

    written = {path.name: path.read_bytes() for path in output.iterdir()}
    committed = {path.name: path.read_bytes() for path in _COMMITTED.iterdir()}
    assert written.keys() == committed.keys()
    for name, text in written.items():
        assert text == committed[name], name
