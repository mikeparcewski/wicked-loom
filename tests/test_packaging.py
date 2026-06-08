"""Packaging guards — the npm bin surface must match how consumers invoke loom.

Garden (and any peer-resolving consumer) resolves the CLI by the PACKAGE name
`wicked-loom` (e.g. `shutil.which("wicked-loom")` / `npx wicked-loom`). If the
bin were only named `loom`, a global/PATH install would not be found by that
lookup and the consumer would silently fall back to `npx` on every call. So the
package MUST expose a `wicked-loom` bin. `loom` is kept as an additive alias.
"""

import json
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "package.json"
_TARGET = "bin/loom.mjs"


def _bin():
    return json.loads(_PKG.read_text(encoding="utf-8")).get("bin", {})


def test_exposes_wicked_loom_bin():
    # The package name and the bin command must agree, so `which("wicked-loom")`
    # and `npx wicked-loom` resolve a real local executable.
    assert _bin().get("wicked-loom") == _TARGET


def test_keeps_loom_alias():
    assert _bin().get("loom") == _TARGET


def test_bin_target_exists():
    assert (_PKG.parent / _TARGET).is_file()
