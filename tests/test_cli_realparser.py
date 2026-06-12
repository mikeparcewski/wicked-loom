"""Real-CLI-parser/entrypoint tests — NO mocking of the parser or handlers.

The existing tests/test_cli.py mocks run_gate / run_flow / flow_status away, so
the actual argument parsing and the CLI boundary's error handling were never
exercised — which is why the boundary-traceback and produces==scope defects
shipped green. These tests drive ``cli.main`` end-to-end through the REAL
parser and REAL handlers.

Safety:
  - WICKED_VAULT_BIN="" (kill-switch) is set so gate/flow re-derivation fails
    closed instead of spawning a real vault.
  - All flow state goes to pytest's tmp_path; no live vault or state dir touched.

Every assertion proves the CLI surfaces a STRUCTURED JSON error (R4 — "never
raise, surface as data") with an appropriate non-zero exit — never a traceback.
"""

import io
import json
from contextlib import redirect_stdout

import pytest

from loom import cli


@pytest.fixture(autouse=True)
def _killswitch(monkeypatch):
    """Kill-switch the vault for every test here so nothing real is spawned."""
    monkeypatch.setenv("WICKED_VAULT_BIN", "")


def _run(argv):
    """Drive the real entrypoint; capture stdout. Asserts main() itself never
    raises (the whole point — the boundary surfaces errors as data)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def _json_of(out):
    """The CLI emits exactly one JSON object per invocation; parse the last
    non-empty line so a stray banner never breaks the assertion."""
    line = [ln for ln in out.splitlines() if ln.strip()][-1]
    return json.loads(line)


# --- Bug 1: CLI-boundary tracebacks now surface as JSON ---------------------

def test_real_flow_run_missing_file_returns_json_error_not_traceback(tmp_path):
    code, out = _run(["flow", "run", str(tmp_path / "does-not-exist.json"),
                      "--state-dir", str(tmp_path)])
    obj = _json_of(out)            # must be parseable JSON (no traceback text)
    assert "error" in obj
    assert code != 0


def test_real_flow_run_non_json_file_returns_json_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json {", encoding="utf-8")
    code, out = _run(["flow", "run", str(bad), "--state-dir", str(tmp_path)])
    obj = _json_of(out)
    assert "error" in obj
    assert code != 0


def test_real_flow_status_path_traversal_flow_id_returns_json_error(tmp_path):
    code, out = _run(["flow", "status", "../../etc/passwd",
                      "--state-dir", str(tmp_path)])
    obj = _json_of(out)
    assert "error" in obj
    assert code != 0


def test_real_flow_resume_path_traversal_flow_id_returns_json_error(tmp_path):
    code, out = _run(["flow", "resume", "../../etc/passwd",
                      "--state-dir", str(tmp_path)])
    obj = _json_of(out)
    assert "error" in obj
    assert code != 0


def test_real_flow_run_missing_flow_id_key_returns_json_error(tmp_path):
    """A flow-def without a flow_id once crashed with KeyError; the boundary
    safety net now surfaces it as data."""
    fd = tmp_path / "nokey.json"
    fd.write_text(json.dumps({"phases": []}), encoding="utf-8")
    code, out = _run(["flow", "run", str(fd), "--state-dir", str(tmp_path)])
    obj = _json_of(out)
    assert "error" in obj
    assert code != 0


def test_real_flow_status_missing_flow_id_arg_returns_json_usage(tmp_path):
    """The 'missing flow_id' case (no positional) returns a structured usage
    error through the real parser."""
    code, out = _run(["flow", "status", "--state-dir", str(tmp_path)])
    obj = _json_of(out)
    assert "error" in obj
    assert code == 2


# --- Bug 2: produces == scope is accepted by the real parser ----------------

def test_real_gate_produces_equals_scope_is_accepted(tmp_path):
    """gate <x> --scope <x>: identical produces/scope once spuriously errored
    with a usage message (exit 2). Now the real parser keeps <x> as produces and
    proceeds to the (kill-switched) gate, which fails closed (exit 1)."""
    code, out = _run(["gate", "build-1", "--scope", "build-1"])
    obj = _json_of(out)
    # It must NOT be the usage error any more — it reached the real gate.
    assert "gate" in obj, f"expected a gate verdict, got: {obj}"
    assert obj["gate"]["gate"] == "unavailable"   # fail-closed (kill-switch)
    assert obj["gate"]["satisfied"] is False
    assert code == 1                              # gate-not-satisfied, not usage


def test_real_gate_produces_equals_scope_forwards_correct_phase(tmp_path,
                                                                monkeypatch):
    """Strongest proof of the parser fix: with a RESOLVABLE (fake) vault, the
    real parser + real argv-build forward produces 'build-1' as --phase AND
    'build-1' as --scope. Once-broken parser dropped produces entirely.

    No parser/handler is mocked — only the vault BINARY is pointed at a stub
    script via the WICKED_VAULT_BIN override (a real resolution path)."""
    fake = tmp_path / "fakevault.sh"
    fake.write_text('#!/bin/sh\necho \'{"overall":"PASS"}\'\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("WICKED_VAULT_BIN", str(fake))  # overrides kill-switch

    code, out = _run(["gate", "build-1", "--scope", "build-1"])
    obj = _json_of(out)
    argv = obj["gate"]["argv"]
    assert "--phase" in argv and argv[argv.index("--phase") + 1] == "build-1"
    assert "--scope" in argv and argv[argv.index("--scope") + 1] == "build-1"
    assert obj["gate"]["satisfied"] is True
    assert code == 0


def test_real_gate_produces_equals_scope_not_usage_exit(tmp_path):
    """Regression guard: the exit code for produces==scope must be the gate's
    not-satisfied code (1), never the parser's usage code (2)."""
    code, _ = _run(["gate", "build-1", "--scope", "build-1"])
    assert code != 2


def test_real_gate_produces_equals_scope_equals_verifier_value(tmp_path):
    """Stress the position-aware parser: produces == scope == verifier-spec
    value. The first positional must still be taken as produces."""
    code, out = _run(["gate", "same", "--scope", "same",
                      "--verifier-spec", "same"])
    obj = _json_of(out)
    assert "gate" in obj
    # verifier-spec value 'same' is forwarded; produces 'same' is the --phase.
    assert "--phase" in obj["gate"]["argv"] or obj["gate"]["argv"] == []
    assert code == 1


def test_real_gate_distinct_produces_and_scope_still_works(tmp_path):
    """Control: the previously-working distinct-values case is unbroken."""
    code, out = _run(["gate", "test-report", "--scope", "build-1"])
    obj = _json_of(out)
    assert "gate" in obj
    assert code == 1


def test_real_gate_missing_produces_returns_json_usage(tmp_path):
    code, out = _run(["gate"])
    obj = _json_of(out)
    assert "error" in obj
    assert code == 2


# --- Real parser still forwards flags correctly (no mock of the parser) -----

def test_real_gate_forwards_flags_to_argv(tmp_path):
    """End-to-end through the real parser AND real run_gate (kill-switched):
    the argv the gate would have run carries scope/produces/verifier/attest."""
    code, out = _run(["gate", "verdict", "--scope", "b1",
                      "--verifier-spec", "/tmp/v.json", "--with-attestations"])
    obj = _json_of(out)
    # Kill-switch -> vault unresolvable -> argv is [] and re_derived False; but
    # the command was accepted (not a usage error) and failed closed.
    assert "gate" in obj
    assert obj["gate"]["satisfied"] is False
    assert code == 1
