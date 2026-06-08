import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from loom import cli


def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def test_resolve_prints_command():
    with patch("loom.cli.resolve", return_value=["npx", "wicked-vault"]):
        code, out = _run(["resolve", "vault"])
    assert code == 0
    assert json.loads(out)["command"] == ["npx", "wicked-vault"]


def test_resolve_unresolvable_exits_nonzero():
    with patch("loom.cli.resolve", return_value=None):
        code, out = _run(["resolve", "vault"])
    assert code == 1
    assert json.loads(out)["command"] is None


def test_doctor_prints_all_rows():
    rows = [{"peer": "vault", "status": "ok"}]
    with patch("loom.cli.check_all", return_value=rows):
        code, out = _run(["doctor"])
    assert code == 0
    assert json.loads(out)["peers"] == rows


def test_doctor_exits_nonzero_on_missing_peer():
    rows = [{"peer": "vault", "status": "missing"}]
    with patch("loom.cli.check_all", return_value=rows):
        code, _ = _run(["doctor"])
    assert code == 1


def test_compose_install_targets_one_peer():
    with patch("loom.cli.install_peer", return_value={"peer": "vault", "status": "installed"}) as m:
        code, out = _run(["compose", "install", "--peer", "vault"])
    assert code == 0
    m.assert_called_once_with("vault")
    assert json.loads(out)["results"][0]["status"] == "installed"


def test_unknown_command_exits_two():
    code, _ = _run(["frobnicate"])
    assert code == 2


# --- conduct: gate + flow ---------------------------------------------------

import json as _json  # noqa: E402


def test_gate_command_satisfied_exits_zero():
    verdict = {"satisfied": True, "overall": "PASS", "gate": "vault-cross-check"}
    with patch("loom.cli.run_gate", return_value=verdict) as m:
        code, out = _run(["gate", "test-report", "--scope", "build-1"])
    assert code == 0
    assert _json.loads(out)["gate"]["satisfied"] is True
    m.assert_called_once()


def test_gate_command_unsatisfied_exits_one():
    verdict = {"satisfied": False, "overall": "REJECT", "gate": "vault-cross-check"}
    with patch("loom.cli.run_gate", return_value=verdict):
        code, _ = _run(["gate", "test-report", "--scope", "build-1"])
    assert code == 1


def test_gate_command_forwards_flags():
    with patch("loom.cli.run_gate", return_value={"satisfied": True}) as m:
        _run(["gate", "verdict", "--scope", "b1",
              "--verifier-spec", "/tmp/v.json", "--with-attestations"])
    _, kwargs = m.call_args
    assert kwargs["scope"] == "b1"
    assert kwargs["verifier_spec"] == "/tmp/v.json"
    assert kwargs["with_attestations"] is True


def test_gate_requires_produces_arg():
    code, _ = _run(["gate"])
    assert code == 2


def test_flow_run_completed_exits_zero(tmp_path):
    fd = {"flow_id": "cli-1",
          "phases": [{"name": "a", "gate": None, "hitl": "none"}],
          "peers_required": [], "verifier_spec_ref": None}
    p = tmp_path / "flow.json"
    p.write_text(_json.dumps(fd), encoding="utf-8")
    completed = {"flow_id": "cli-1", "status": "completed"}
    with patch("loom.cli.run_flow", return_value=completed) as m:
        code, out = _run(["flow", "run", str(p), "--state-dir", str(tmp_path)])
    assert code == 0
    assert _json.loads(out)["flow"]["status"] == "completed"
    m.assert_called_once()


def test_flow_run_parked_exits_two(tmp_path):
    fd = {"flow_id": "cli-2", "phases": [], "peers_required": [],
          "verifier_spec_ref": None}
    p = tmp_path / "flow.json"
    p.write_text(_json.dumps(fd), encoding="utf-8")
    with patch("loom.cli.run_flow", return_value={"status": "parked"}):
        code, _ = _run(["flow", "run", str(p), "--state-dir", str(tmp_path)])
    assert code == 2


def test_flow_status_found_exits_zero(tmp_path):
    with patch("loom.cli.flow_status", return_value={"flow_id": "x", "status": "running"}):
        code, out = _run(["flow", "status", "x", "--state-dir", str(tmp_path)])
    assert code == 0
    assert _json.loads(out)["flow"]["flow_id"] == "x"


def test_flow_status_missing_exits_one(tmp_path):
    with patch("loom.cli.flow_status", return_value=None):
        code, _ = _run(["flow", "status", "nope", "--state-dir", str(tmp_path)])
    assert code == 1


def test_flow_resume_completed_exits_zero(tmp_path):
    with patch("loom.cli.flow_resume", return_value={"status": "completed"}):
        code, _ = _run(["flow", "resume", "x", "--state-dir", str(tmp_path)])
    assert code == 0


def test_flow_resume_missing_exits_one(tmp_path):
    with patch("loom.cli.flow_resume", return_value=None):
        code, _ = _run(["flow", "resume", "nope", "--state-dir", str(tmp_path)])
    assert code == 1


def test_flow_unknown_subcommand_exits_two():
    code, _ = _run(["flow", "frobnicate"])
    assert code == 2
