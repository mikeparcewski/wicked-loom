"""cli.py — argument dispatch + JSON output for the compose surface.

Commands:
  loom resolve <peer>              -> {"peer","command"}            exit 0/1
  loom doctor                      -> {"peers":[check rows]}        exit 0/1
  loom compose install [--peer X]  -> {"results":[install rows]}    exit 0/1

No business logic lives here — only parsing + formatting.
"""

from __future__ import annotations

import json
import sys

from loom import manifest
from loom.compose import check_all, install_peer
from loom.resolve import resolve


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")


def _cmd_resolve(args: list[str]) -> int:
    if not args:
        _emit({"error": "usage: loom resolve <peer>"})
        return 2
    cmd = resolve(args[0])
    _emit({"peer": args[0], "command": cmd})
    return 0 if cmd is not None else 1


def _cmd_doctor(_args: list[str]) -> int:
    rows = check_all()
    _emit({"peers": rows})
    return 0 if all(r.get("status") == "ok" for r in rows) else 1


def _cmd_compose(args: list[str]) -> int:
    if not args or args[0] != "install":
        _emit({"error": "usage: loom compose install [--peer <name>]"})
        return 2
    target = None
    if "--peer" in args:
        i = args.index("--peer")
        if i + 1 < len(args):
            target = args[i + 1]
    names = [target] if target else list(manifest.PEERS)
    results = [install_peer(n) for n in names]
    _emit({"results": results})
    return 0 if all(r.get("status") == "installed" for r in results) else 1


_DISPATCH = {"resolve": _cmd_resolve, "doctor": _cmd_doctor, "compose": _cmd_compose}


def main(argv: "list[str] | None" = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        _emit({"commands": list(_DISPATCH)})
        return 0
    handler = _DISPATCH.get(argv[0])
    if handler is None:
        _emit({"error": f"unknown command: {argv[0]}", "commands": list(_DISPATCH)})
        return 2
    return handler(argv[1:])
