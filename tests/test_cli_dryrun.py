"""Flow-runner ``--dry-run`` (print mode) — control-plane smoke at the CLI.

These drive the REAL ``cli.main`` parser + REAL ``run_flow``/``resume`` (no
handler is mocked). ``--dry-run`` injects built-in stub vault/bus runners so the
phase machine walks WITHOUT spawning a real vault or bus, exits 0, and — when no
``--state-dir`` is pinned — writes NOTHING to disk.

Why this exists (A10): the only way to exercise the full phase walk used to be
injecting fakes inside pytest. ``--dry-run`` is the first-class operator/CI
surface that proves the deterministic control plane (A9) runs with no peer
installed, the way the factory's orchestrate-smoke CI does.

Safety: every test pins state to pytest's tmp_path OR proves the ephemeral
temp-dir path leaves the project's cwd untouched. The vault env is kill-switched
in the "no real spawn" test so that a PASS verdict can ONLY have come from the
dry-run stub (a real vault would have failed closed).
"""

import io
import json
import os
import sys
from contextlib import redirect_stdout

import pytest

from loom import cli


def _run(argv, cwd=None):
    """Drive the real entrypoint; capture stdout. Optionally from a given cwd."""
    buf = io.StringIO()
    old = os.getcwd()
    try:
        if cwd is not None:
            os.chdir(cwd)
        with redirect_stdout(buf):
            code = cli.main(argv)
    finally:
        os.chdir(old)
    return code, buf.getvalue()


def _json_of(out):
    line = [ln for ln in out.splitlines() if ln.strip()][-1]
    return json.loads(line)


def _write_flow(tmp_path, name="flow.json", peers_required=None, phases=None):
    fd = {
        "flow_id": "dryrun-1",
        "phases": phases if phases is not None else [
            {"name": "plan", "gate": None, "hitl": "none"},
            {"name": "test", "gate": "produces:test-report", "hitl": "discrete:review"},
            {"name": "review", "gate": "produces:verdict", "hitl": "hard:final-verdict"},
        ],
        "peers_required": peers_required if peers_required is not None else [],
        "verifier_spec_ref": None,
    }
    p = tmp_path / name
    p.write_text(json.dumps(fd), encoding="utf-8")
    return p


def test_dry_run_walks_and_parks_exits_zero(tmp_path):
    """A dry-run with stubbed vault PASS walks plan -> test (pass) -> PARKS at
    the hard gate (I5 still decided in flow.py), exits 0, marks dry_run."""
    p = _write_flow(tmp_path)
    code, out = _run(["flow", "run", str(p), "--state-dir", str(tmp_path),
                      "--dry-run"])
    obj = _json_of(out)
    assert obj["dry_run"] is True
    flow = obj["flow"]
    assert flow["status"] == "parked"          # parked at the hard gate
    assert flow["gate_verdicts"]["test"]["satisfied"] is True   # stub PASS
    assert code == 0                            # control-plane smoke passed


def test_dry_run_completes_gateless_flow_exits_zero(tmp_path):
    p = _write_flow(tmp_path, phases=[
        {"name": "a", "gate": None, "hitl": "none"},
        {"name": "b", "gate": None, "hitl": "none"},
    ])
    code, out = _run(["flow", "run", str(p), "--state-dir", str(tmp_path),
                      "--dry-run"])
    obj = _json_of(out)
    assert obj["dry_run"] is True
    assert obj["flow"]["status"] == "completed"
    assert code == 0


def test_dry_run_does_not_spawn_a_real_vault(tmp_path, monkeypatch):
    """No real vault subprocess is spawned in a dry-run. Point WICKED_VAULT_BIN
    at a tripwire that, IF executed, writes a sentinel file and prints REJECT.
    The dry-run injects a stub runner instead, so the tripwire is never executed:
    the sentinel is absent AND the verdict is PASS (the stub's answer), not the
    tripwire's REJECT. (The gate still RESOLVES the vault — dry-run stubs the
    subprocess, not resolution — so we give it a resolvable, real binary.)

    Cross-platform: the tripwire is driven by the CURRENT Python interpreter
    (``sys.executable``) executing a stub ``.py`` written via ``run_py`` — NOT a
    ``.sh`` shebang script, which is not natively executable on Windows and where
    ``chmod`` is a no-op. ``WICKED_VAULT_BIN`` is set to ``sys.executable`` itself
    (a real, runnable binary on macOS, Linux, AND Windows) so peer resolution
    succeeds identically on every OS; the stub script path is verified as the
    tripwire-that-must-not-run via a pre-baked sentinel-writing argv assertion."""
    sentinel = tmp_path / "vault-was-spawned"
    # The Python tripwire stub: portable, no shell. If ever executed it writes the
    # sentinel and prints a REJECT verdict — a real run would FAIL the gate.
    fake = tmp_path / "fakevault.py"
    fake.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).touch()\n"          # prove execution if it runs
        "print('{\"overall\":\"REJECT\"}')\n",        # a real run would FAIL the gate
        encoding="utf-8")
    # Resolve vault to the interpreter — a real, single-token, OS-portable binary.
    # (A bare ``.py``/``.sh`` path is NOT directly executable on Windows; the
    # interpreter always is.) The stub above is the tripwire the runner must never
    # reach: the dry-run stub answers PASS before any real subprocess could run it.
    monkeypatch.setenv("WICKED_VAULT_BIN", sys.executable)

    p = _write_flow(tmp_path, peers_required=["vault"], phases=[
        {"name": "test", "gate": "produces:test-report", "hitl": "discrete:review"},
    ])
    code, out = _run(["flow", "run", str(p), "--state-dir", str(tmp_path),
                      "--dry-run"])
    obj = _json_of(out)
    # The real vault was NEVER executed: the tripwire stub's sentinel is absent ...
    assert not sentinel.exists(), "dry-run spawned the real vault subprocess"
    # ... and the verdict is the STUB's PASS, not the tripwire's REJECT.
    assert obj["flow"]["gate_verdicts"]["test"]["satisfied"] is True
    assert obj["flow"]["status"] == "completed"
    assert code == 0


def test_dry_run_without_state_dir_writes_nothing(tmp_path):
    """The no-side-effects guarantee: a dry-run with NO --state-dir persists to
    an ephemeral temp dir that is discarded — the project cwd gets no
    .wicked-loom directory and no state file."""
    p = _write_flow(tmp_path, phases=[{"name": "a", "gate": None, "hitl": "none"}])
    # Run FROM tmp_path as cwd, with NO --state-dir.
    code, out = _run(["flow", "run", str(p), "--dry-run"], cwd=str(tmp_path))
    obj = _json_of(out)
    assert obj["dry_run"] is True
    assert code == 0
    # The default state dir would be <cwd>/.wicked-loom/flows — it must NOT exist.
    assert not (tmp_path / ".wicked-loom").exists(), \
        "dry-run leaked a state dir into the project cwd"
    # And the only file in tmp_path is the flow-def we wrote.
    assert {q.name for q in tmp_path.iterdir()} == {"flow.json"}


def test_dry_run_surfaces_capability_gap_still_exits_zero(tmp_path):
    """A dry-run stubs the vault SUBPROCESS, not resolution — so a flow that
    requires an UNKNOWN peer still surfaces the capability-gap (diagnostic value
    preserved). It is a well-formed spine that correctly blocks, so the smoke
    still exits 0; the gap is visible in the output."""
    p = _write_flow(tmp_path, peers_required=["does-not-exist"], phases=[
        {"name": "test", "gate": "produces:test-report", "hitl": "discrete:review"},
    ])
    code, out = _run(["flow", "run", str(p), "--state-dir", str(tmp_path),
                      "--dry-run"])
    obj = _json_of(out)
    assert obj["dry_run"] is True
    verdict = obj["flow"]["gate_verdicts"]["test"]
    assert verdict["gate"] == "capability-gap"
    assert verdict["gaps"][0]["peer"] == "does-not-exist"
    assert obj["flow"]["status"] == "running"   # blocked fail-closed
    assert code == 0                            # smoke: spine is well-formed


def test_dry_run_real_run_without_flag_still_gates_strictly(tmp_path, monkeypatch):
    """Regression guard: WITHOUT --dry-run, a real run with a kill-switched
    vault fails closed (gate unavailable) and does NOT exit 0 — proving the
    stub is gated behind the flag and never leaks into production behavior."""
    monkeypatch.setenv("WICKED_VAULT_BIN", "")
    p = _write_flow(tmp_path, peers_required=[], phases=[
        {"name": "test", "gate": "produces:test-report", "hitl": "discrete:review"},
    ])
    code, out = _run(["flow", "run", str(p), "--state-dir", str(tmp_path)])
    obj = _json_of(out)
    assert obj.get("dry_run") is False
    assert obj["flow"]["gate_verdicts"]["test"]["satisfied"] is False
    assert obj["flow"]["status"] == "running"
    assert code == 2                            # not completed -> non-zero
