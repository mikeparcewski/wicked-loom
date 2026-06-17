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
from loom.compose import RunResult, check_all, install_peer
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


# Options that take a value (the next token is consumed by the option, not a
# positional). Used to extract positionals by POSITION, not by value — so a
# positional that happens to equal an option's value is not stolen.
_VALUE_OPTS = ("--scope", "--verifier-spec", "--state-dir")


def _positionals(args: list) -> list:
    """Return the positional tokens, skipping flags and the value tokens that
    belong to value-taking options. Position-aware so e.g.
    ``gate X --scope X`` keeps the first ``X`` as the produces positional."""
    out: list = []
    i = 0
    n = len(args)
    while i < n:
        tok = args[i]
        if tok in _VALUE_OPTS:
            i += 2  # skip the option and its value token
            continue
        if tok.startswith("--"):
            i += 1  # a bare flag (e.g. --with-attestations)
            continue
        out.append(tok)
        i += 1
    return out


def _cmd_gate(args: list) -> int:
    scope = _opt(args, "--scope") or "default"
    verifier_spec = _opt(args, "--verifier-spec")
    # Extract the produces positional by POSITION, not value-equality, so that
    # ``gate <x> --scope <x>`` (produces == scope) is accepted (parser bug fix).
    positional = _positionals(args)
    produces = positional[0] if positional else None
    if produces is None:
        _emit({"error": "usage: loom gate <produces> [--scope S] "
                        "[--verifier-spec PATH] [--with-attestations]"})
        return 2
    verdict = run_gate(produces, scope=scope, verifier_spec=verifier_spec,
                       with_attestations="--with-attestations" in args)
    _emit({"gate": verdict})
    return 0 if verdict.get("satisfied") else 1


def _load_flow_def(path_str: str) -> dict:
    """Read + parse a flow-def JSON file. Raises on missing file / bad JSON;
    the caller (``_cmd_flow``) turns those into structured JSON errors so the
    'never raise — surface as data' invariant holds at the CLI boundary."""
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def _dry_run_runners():
    """Built-in stub runners for ``--dry-run`` (print mode).

    The control-plane smoke: walk the phase machine with NO real peer SPAWNED.
      * vault stub returns ``{"overall":"PASS"}`` — the exact shape
        ``gate.run_gate`` parses — so gated phases re-derive to a pass and the
        walk proceeds (parking at any hard gate, exactly like production — I5 is
        decided in flow.py, which is untouched).
      * bus stub is a no-op success — no event is emitted off-box.
    These replace the SUBPROCESS execution only; peer RESOLUTION still runs
    (resolve() spawns nothing — pure PATH/env lookup). So a dry-run reflects the
    box's resolvability: a wired peer that does not resolve still surfaces a
    capability-gap, and a gate whose vault is unresolvable still fails closed —
    dry-run never weakens those invariants, it only avoids the real subprocess.
    In a normal env (or CI with node) every peer resolves via PATH/npx, so the
    walk runs end-to-end with nothing real executed.
    """
    def vault_run(cmd, timeout=None):
        return RunResult(returncode=0, stdout=json.dumps({"overall": "PASS"}),
                         stderr="")

    def bus_run(cmd, timeout=None):
        return RunResult(returncode=0, stdout="", stderr="")

    return vault_run, bus_run


def _cmd_flow(args: list) -> int:
    if not args:
        _emit({"error": "usage: loom flow <run|status|resume> ..."})
        return 2
    sub, rest = args[0], args[1:]
    dry_run = "--dry-run" in rest
    # In dry-run we MUST leave no trace: if the operator did not pin a
    # --state-dir, persist to an ephemeral temp dir that is discarded on exit,
    # so a control-plane smoke writes nothing into the project's .wicked-loom.
    explicit_state_dir = _opt(rest, "--state-dir")
    tmp_state = None
    if dry_run and not explicit_state_dir:
        import tempfile
        tmp_state = tempfile.TemporaryDirectory(prefix="loom-dryrun-")
        state_dir = Path(tmp_state.name)
    else:
        state_dir = Path(explicit_state_dir or _default_state_dir())
    # Position-aware: never confuse a positional with a --state-dir value.
    # ``--dry-run`` is a bare flag, so _positionals already skips it.
    positional = _positionals(rest)

    # In dry-run, inject stub vault/bus runners so the phase walk runs with no
    # real peer spawned (control-plane print mode). Production passes the real
    # defaults (run_flow/resume default to compose._default_run).
    runner_kw = {}
    if dry_run:
        vault_run, bus_run = _dry_run_runners()
        runner_kw = {"vault_run": vault_run, "bus_run": bus_run}

    # Every path that can raise (missing file, bad JSON, unsafe flow_id) is
    # wrapped here so the CLI boundary surfaces errors as JSON, never a raw
    # traceback (R4 — "never raise, surface as data").
    try:
        if sub == "run":
            if not positional:
                _emit({"error": "usage: loom flow run <flow-def.json> "
                                "[--state-dir D] [--dry-run]"})
                return 2
            flow_def = _load_flow_def(positional[0])
            st = run_flow(flow_def, state_dir=state_dir, **runner_kw)
            _emit({"flow": st, "dry_run": dry_run})
            # Dry-run is a control-plane smoke: a clean walk (completed OR a
            # legitimate park/block) means the spine is well-formed -> exit 0.
            # A real run still gates strictly (completed -> 0, else 2).
            if dry_run:
                return 0
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
                _emit({"error": "usage: loom flow resume <flow-id> "
                                "[--state-dir D] [--dry-run]"})
                return 2
            st = flow_resume(positional[0], state_dir=state_dir, **runner_kw)
            _emit({"flow": st, "dry_run": dry_run})
            if dry_run:
                return 0 if st is not None else 1
            if st is None:
                return 1
            return 0 if st.get("status") == "completed" else 2
    except FileNotFoundError as e:
        _emit({"error": "flow-def file not found", "detail": str(e)})
        return 2
    except json.JSONDecodeError as e:
        _emit({"error": "flow-def is not valid JSON", "detail": str(e)})
        return 2
    except ValueError as e:
        # e.g. unsafe / path-traversal flow_id rejected by flowstate guard.
        _emit({"error": "invalid flow argument", "detail": str(e)})
        return 2
    except OSError as e:  # noqa: BLE001 — any other fs error surfaces as data.
        _emit({"error": "flow I/O error", "detail": str(e)})
        return 2
    finally:
        # Discard the ephemeral dry-run state dir (if we created one) so a
        # control-plane smoke leaves NO trace on disk.
        if tmp_state is not None:
            tmp_state.cleanup()

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
    # Top-level safety net: the CLI boundary NEVER lets a raw traceback escape.
    # Any unhandled exception is surfaced as a structured JSON error with a
    # non-zero exit (R4 — "never raise, surface as data"). Fail-closed behavior
    # is preserved inside the handlers; this only guards the boundary itself.
    try:
        return handler(argv[1:])
    except Exception as e:  # noqa: BLE001 — surface as data, never traceback.
        _emit({"error": f"{type(e).__name__}: {e}",
               "command": argv[0],
               "detail": "loom never raises at the CLI boundary; "
                         "this error is surfaced as data (R4)."})
        return 2
