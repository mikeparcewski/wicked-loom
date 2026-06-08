"""manifest.py — the wicked-* peer set: what each peer is and how to reach it.

Source of truth ported from wicked-garden docs/required-peers.md + plugin.json.
Version pins are the MAJOR.MINOR floor (the `^x.y` in plugin.json), compared by
compose.py. Install commands are headless (npm/npx) — the `/plugin install`
path is CC-UX sugar, not the only route.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Peer:
    name: str
    npm_package: str
    env_var: str           # runtime override env var, e.g. WICKED_VAULT_BIN
    version_pin: str        # MAJOR.MINOR floor, e.g. "0.3"
    install_cmd: list[str]  # headless install command
    probe_cmd: list[str]    # command to print the installed version


PEERS: dict[str, Peer] = {
    "vault": Peer(
        name="vault",
        npm_package="wicked-vault",
        env_var="WICKED_VAULT_BIN",
        version_pin="0.3",
        install_cmd=["npx", "wicked-vault-install"],
        probe_cmd=["wicked-vault", "--version"],
    ),
    "testing": Peer(
        name="testing",
        npm_package="wicked-testing",
        env_var="WICKED_TESTING_BIN",
        version_pin="0.3",
        install_cmd=["npx", "wicked-testing", "install"],
        probe_cmd=["wicked-testing", "--version"],
    ),
    "brain": Peer(
        name="brain",
        npm_package="wicked-brain",
        env_var="WICKED_BRAIN_BIN",
        version_pin="0.14",
        install_cmd=["npm", "install", "-g", "wicked-brain@latest"],
        probe_cmd=["wicked-brain-server", "--version"],
    ),
    "bus": Peer(
        name="bus",
        npm_package="wicked-bus",
        env_var="WICKED_BUS_BIN",
        version_pin="2.0",
        install_cmd=["npm", "install", "-g", "wicked-bus@latest"],
        probe_cmd=["wicked-bus", "--version"],
    ),
}


def get(name: str) -> "Peer | None":
    """Return the Peer for ``name`` or None if unknown."""
    return PEERS.get(name)
