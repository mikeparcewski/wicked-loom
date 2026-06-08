"""compose.py — version-check + install orchestration over the peer set.

check_peer:  resolve -> probe -> parse version -> compare MAJOR.MINOR to the pin.
install_peer: run the peer's headless install command.
check_all:   one check_peer row per known peer.

Subprocess execution is injected (the ``run`` parameter) so callers (and tests)
control side effects. Nothing here raises — failures are returned as status
rows ("ok" | "drift" | "missing" | "error" | "installed" | "install-failed").
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable

from loom import manifest
from loom.manifest import Peer
from loom.resolve import resolve_version_bin

_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., RunResult]


def _default_run(cmd: list[str], timeout: int = 30) -> RunResult:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return RunResult(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def _parse_version(text: str) -> "str | None":
    m = _VERSION_RE.search(text or "")
    if not m:
        return None
    major, minor, patch = m.group(1), m.group(2), m.group(3) or "0"
    return f"{major}.{minor}.{patch}"


def _meets_pin(installed: str, pin: str) -> bool:
    iv = _parse_version(installed)
    pv = _parse_version(pin)
    if iv is None or pv is None:
        return False
    ip = [int(x) for x in iv.split(".")]
    pp = [int(x) for x in pv.split(".")]
    return (ip[0], ip[1]) >= (pp[0], pp[1])  # MAJOR.MINOR floor


def _probe_command(version_cmd: list[str], peer: Peer) -> list[str]:
    """The version-probe argv: the resolved version binary + the probe's
    trailing args.

    The version binary can differ from the runnable package — brain runs as
    ``wicked-brain`` but reports its version via ``wicked-brain-server`` — so
    we resolve ``peer.version_package`` (not npm_package) here.

    e.g. version_cmd=["npx","wicked-brain-server"] + probe
         ["wicked-brain-server","--version"]
         -> ["npx","wicked-brain-server","--version"].
    """
    return version_cmd + peer.probe_cmd[1:]


def check_peer(name: str, run: Runner = _default_run) -> dict:
    peer = manifest.get(name)
    if peer is None:
        return {"peer": name, "status": "error", "detail": "unknown peer"}

    version_cmd = resolve_version_bin(name)
    if version_cmd is None:
        return {"peer": name, "status": "missing", "pin": peer.version_pin}

    try:
        result = run(_probe_command(version_cmd, peer))
    except Exception as e:  # noqa: BLE001 — surface as data, never crash (R4)
        return {"peer": name, "status": "error", "detail": str(e), "pin": peer.version_pin}

    if result.returncode != 0:
        return {"peer": name, "status": "error", "detail": result.stderr.strip(),
                "pin": peer.version_pin}

    installed = _parse_version(result.stdout)
    if installed is None:
        return {"peer": name, "status": "error", "detail": "unparseable version",
                "pin": peer.version_pin}

    status = "ok" if _meets_pin(installed, peer.version_pin) else "drift"
    return {"peer": name, "status": status, "installed": installed, "pin": peer.version_pin}


def install_peer(name: str, run: Runner = _default_run) -> dict:
    peer = manifest.get(name)
    if peer is None:
        return {"peer": name, "status": "error", "detail": "unknown peer"}
    try:
        result = run(peer.install_cmd, timeout=300)
    except Exception as e:  # noqa: BLE001
        return {"peer": name, "status": "install-failed", "detail": str(e)}
    if result.returncode != 0:
        return {"peer": name, "status": "install-failed", "detail": result.stderr.strip()}
    return {"peer": name, "status": "installed"}


def check_all(run: Runner = _default_run) -> list[dict]:
    return [check_peer(name, run=run) for name in manifest.PEERS]
