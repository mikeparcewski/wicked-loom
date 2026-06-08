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
from pathlib import Path

from loom import manifest
from loom.compose import check_all, install_peer
from loom.resolve import resolve
from loom.gate import run_gate
from loom.flow import run_flow, status as flow_status, resume as flow_resume


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


def _default_state_dir() -> Path:
    """Project-scoped local state dir. Honors WICKED_LOOM_STATE_DIR; else a
    cwd-anchored .wicked-loom/flows dir (deterministic, no network — spec §10)."""
    import os
    override = os.environ.get("WICKED_LOOM_STATE_DIR", "").strip()
    if override:
        return Path(override)
    return Path.cwd() / ".wicked-loom" / "flows"


def _opt(args: list, name: str) -> "str | None":
    """Return the value following ``--name`` in args, or None."""
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def _cmd_gate(args: list) -> int:
    positional = [a for a in args if not a.startswith("--")]
    # Strip values that belong to --scope / --verifier-spec from positionals.
    scope = _opt(args, "--scope") or "default"
    verifier_spec = _opt(args, "--verifier-spec")
    consumed = {scope, verifier_spec}
    produces = next((a for a in positional if a not in consumed), None)
    if produces is None:
        _emit({"error": "usage: loom gate <produces> [--scope S] "
                        "[--verifier-spec PATH] [--with-attestations]"})
        return 2
    verdict = run_gate(produces, scope=scope, verifier_spec=verifier_spec,
                       with_attestations="--with-attestations" in args)
    _emit({"gate": verdict})
    return 0 if verdict.get("satisfied") else 1


def _cmd_flow(args: list) -> int:
    if not args:
        _emit({"error": "usage: loom flow <run|status|resume> ..."})
        return 2
    sub, rest = args[0], args[1:]
    state_dir = Path(_opt(rest, "--state-dir") or _default_state_dir())
    positional = [a for a in rest if not a.startswith("--") and a != str(state_dir)]

    if sub == "run":
        if not positional:
            _emit({"error": "usage: loom flow run <flow-def.json> [--state-dir D]"})
            return 2
        flow_def = json.loads(Path(positional[0]).read_text(encoding="utf-8"))
        st = run_flow(flow_def, state_dir=state_dir)
        _emit({"flow": st})
        return 0 if st.get("status") == "completed" else 2

    if sub == "status":
        if not positional:
            _emit({"error": "usage: loom flow status <flow-id> [--state-dir D]"})
            return 2
        st = flow_status(positional[0], state_dir=state_dir)
        _emit({"flow": st})
        return 0 if st is not None else 1

    if sub == "resume":
        if not positional:
            _emit({"error": "usage: loom flow resume <flow-id> [--state-dir D]"})
            return 2
        st = flow_resume(positional[0], state_dir=state_dir)
        _emit({"flow": st})
        if st is None:
            return 1
        return 0 if st.get("status") == "completed" else 2

    _emit({"error": f"unknown flow subcommand: {sub}",
           "subcommands": ["run", "status", "resume"]})
    return 2


_DISPATCH = {
    "resolve": _cmd_resolve,
    "doctor": _cmd_doctor,
    "compose": _cmd_compose,
    "gate": _cmd_gate,
    "flow": _cmd_flow,
}


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
