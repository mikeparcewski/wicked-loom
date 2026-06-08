"""resolve.py — the runtime resolution ladder for a peer's runnable command.

Ladder (highest priority first):
  1. WICKED_<PEER>_BIN env var — explicit override. Empty string is a
     deliberate kill-switch (returns None, resolution short-circuits cleanly).
  2. PATH — shutil.which(<npm_package>).
  3. npx fallback — ["npx", "<npm_package>"].

Returns a command as a list[str] (argv-ready) or None when unresolvable /
killed / unknown peer. Pure + deterministic: no process is spawned here.
"""

from __future__ import annotations

import os
import shutil

from loom import manifest


def resolve(peer_name: str) -> "list[str] | None":
    peer = manifest.get(peer_name)
    if peer is None:
        return None

    if peer.env_var in os.environ:
        override = os.environ[peer.env_var].strip()
        if override == "":
            return None  # kill-switch
        return [override]

    on_path = shutil.which(peer.npm_package)
    if on_path:
        return [on_path]

    return ["npx", peer.npm_package]
