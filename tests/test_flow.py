from unittest.mock import patch

from loom import flow
from loom.compose import RunResult


def _vault(overall="PASS", code=0):
    def run(cmd, timeout=None):
        import json
        return RunResult(returncode=code, stdout=json.dumps({"overall": overall}),
                         stderr="")
    return run


def _silent_bus():
    def run(cmd, timeout=None):
        return RunResult(returncode=0, stdout="", stderr="")
    return run


def _flow_def(flow_id="build-1"):
    return {
        "flow_id": flow_id,
        "phases": [
            {"name": "plan", "gate": None, "hitl": "none"},
            {"name": "implement", "gate": None, "hitl": "none"},
            {"name": "test", "gate": "produces:test-report", "hitl": "discrete:review"},
            {"name": "review", "gate": "produces:verdict", "hitl": "hard:final-verdict"},
        ],
        "peers_required": ["vault"],
        "verifier_spec_ref": None,
    }


def test_gateless_phases_advance_freely(tmp_path):
    fd = {"flow_id": "g-1",
          "phases": [{"name": "a", "gate": None, "hitl": "none"},
                     {"name": "b", "gate": None, "hitl": "none"}],
          "peers_required": [], "verifier_spec_ref": None}
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        st = flow.run_flow(fd, state_dir=tmp_path,
                           vault_run=_vault(), bus_run=_silent_bus())
    assert st["status"] == "completed"
    assert st["current_phase"] == 2


def test_flow_parks_at_hard_gate_after_pass(tmp_path):
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        st = flow.run_flow(_flow_def(), state_dir=tmp_path,
                           vault_run=_vault("PASS"), bus_run=_silent_bus())
    assert st["status"] == "parked"
    assert st["parked"] is True
    # parks AT the hard-gate phase ("review", index 3), not past it (I5).
    assert st["current_phase"] == 3
    assert st["gate_verdicts"]["review"]["satisfied"] is True


def test_flow_stops_unparked_when_gate_fails(tmp_path):
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        st = flow.run_flow(_flow_def(), state_dir=tmp_path,
                           vault_run=_vault("REJECT"), bus_run=_silent_bus())
    # stops at the first gated phase ("test", index 2) — not parked, just blocked.
    assert st["status"] == "running"
    assert st["parked"] is False
    assert st["current_phase"] == 2
    assert st["gate_verdicts"]["test"]["satisfied"] is False


def test_flow_fails_closed_when_vault_unresolvable(tmp_path):
    # Vault resolution happens inside gate.run_gate, so patch the name the gate
    # actually consults (gate.resolve) — patching flow.resolve is a no-op since
    # gate.py binds its own `resolve` import. (Plan-code fix: see report.)
    from loom import gate
    with patch.object(gate, "resolve", return_value=None):
        st = flow.run_flow(_flow_def(), state_dir=tmp_path,
                           vault_run=_vault(), bus_run=_silent_bus())
    assert st["status"] == "running"  # blocked at the gate, not advanced
    assert st["current_phase"] == 2
    assert st["gate_verdicts"]["test"]["gate"] == "unavailable"


def test_status_reads_without_advancing(tmp_path):
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        flow.run_flow(_flow_def("s-1"), state_dir=tmp_path,
                      vault_run=_vault("PASS"), bus_run=_silent_bus())
    st = flow.status("s-1", state_dir=tmp_path)
    assert st["flow_id"] == "s-1"
    assert st["status"] == "parked"


def test_status_unknown_flow_is_none(tmp_path):
    assert flow.status("nope", state_dir=tmp_path) is None


def test_resume_advances_past_an_approved_hard_gate(tmp_path):
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        flow.run_flow(_flow_def("r-1"), state_dir=tmp_path,
                      vault_run=_vault("PASS"), bus_run=_silent_bus())
        # human approved the parked hard gate out-of-band -> resume.
        st = flow.resume("r-1", state_dir=tmp_path,
                         vault_run=_vault("PASS"), bus_run=_silent_bus())
    assert st["status"] == "completed"
    assert st["parked"] is False
    assert st["current_phase"] == 4


def test_resume_unknown_flow_returns_none(tmp_path):
    assert flow.resume("nope", state_dir=tmp_path,
                       vault_run=_silent_bus(), bus_run=_silent_bus()) is None


def test_flow_is_archetype_agnostic(tmp_path):
    # A flow def with a made-up archetype-shaped name still runs purely off
    # gate/hitl fields — loom must not branch on archetype names (I6).
    fd = {"flow_id": "x-1",
          "phases": [{"name": "totally-made-up-phase", "gate": None, "hitl": "none"}],
          "peers_required": [], "verifier_spec_ref": None}
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        st = flow.run_flow(fd, state_dir=tmp_path,
                           vault_run=_vault(), bus_run=_silent_bus())
    assert st["status"] == "completed"
