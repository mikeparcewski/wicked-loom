from unittest.mock import patch

from loom import gate
from loom.compose import RunResult


def _runner(stdout="", code=0):
    def run(cmd, timeout=None):
        return RunResult(returncode=code, stdout=stdout, stderr="")
    return run


def test_gate_passes_when_vault_reports_pass():
    with patch.object(gate, "resolve", return_value=["wicked-vault"]):
        r = gate.run_gate("test-report", scope="build-1",
                          run=_runner(stdout='{"overall":"PASS"}'))
    assert r["satisfied"] is True
    assert r["gate"] == "vault-cross-check"
    assert r["re_derived"] is True
    assert r["overall"] == "PASS"


def test_gate_rejects_when_vault_reports_reject():
    with patch.object(gate, "resolve", return_value=["wicked-vault"]):
        r = gate.run_gate("test-report", scope="build-1",
                          run=_runner(stdout='{"overall":"REJECT"}'))
    assert r["satisfied"] is False
    assert r["overall"] == "REJECT"


def test_gate_fails_closed_when_vault_unresolvable():
    with patch.object(gate, "resolve", return_value=None):
        r = gate.run_gate("test-report", scope="build-1", run=_runner())
    assert r["satisfied"] is False
    assert r["gate"] == "unavailable"
    assert r["re_derived"] is False


def test_gate_fails_closed_when_vault_unrunnable():
    def boom(cmd, timeout=None):
        raise FileNotFoundError("vault gone")
    with patch.object(gate, "resolve", return_value=["wicked-vault"]):
        r = gate.run_gate("test-report", scope="build-1", run=boom)
    assert r["satisfied"] is False
    assert r["gate"] == "unavailable"


def test_gate_fails_closed_on_non_json_output():
    with patch.object(gate, "resolve", return_value=["wicked-vault"]):
        r = gate.run_gate("test-report", scope="build-1",
                          run=_runner(stdout="not json"))
    assert r["satisfied"] is False
    assert r["overall"] == "ERROR"


def test_with_attestations_forwarded_to_vault():
    seen = {}

    def run(cmd, timeout=None):
        seen["cmd"] = cmd
        return RunResult(returncode=0, stdout='{"overall":"PASS"}', stderr="")

    with patch.object(gate, "resolve", return_value=["wicked-vault"]):
        gate.run_gate("verdict", scope="build-1", with_attestations=True, run=run)
    assert "--with-attestations" in seen["cmd"]


def test_verifier_spec_forwarded_when_present():
    seen = {}

    def run(cmd, timeout=None):
        seen["cmd"] = cmd
        return RunResult(returncode=0, stdout='{"overall":"PASS"}', stderr="")

    with patch.object(gate, "resolve", return_value=["wicked-vault"]):
        gate.run_gate("verdict", scope="build-1",
                      verifier_spec="/tmp/verify.json", run=run)
    assert "--verifier-spec" in seen["cmd"]
    assert "/tmp/verify.json" in seen["cmd"]


def test_verifier_spec_absent_is_fail_soft_not_blocking():
    # No verifier_spec given -> the gate still runs and can PASS (I3).
    with patch.object(gate, "resolve", return_value=["wicked-vault"]):
        r = gate.run_gate("verdict", scope="build-1",
                          run=_runner(stdout='{"overall":"PASS"}'))
    assert r["satisfied"] is True
    assert "--verifier-spec" not in r.get("argv", [])
