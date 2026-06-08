from loom import flowstate

_FLOW = {
    "flow_id": "build-1",
    "phases": [
        {"name": "plan", "gate": None, "hitl": "none"},
        {"name": "test", "gate": "produces:test-report", "hitl": "discrete:review"},
    ],
    "peers_required": ["vault"],
    "verifier_spec_ref": None,
}


def test_new_state_starts_at_phase_zero_running(tmp_path):
    st = flowstate.new_state(_FLOW, state_dir=tmp_path)
    assert st["flow_id"] == "build-1"
    assert st["current_phase"] == 0
    assert st["status"] == "running"
    assert st["parked"] is False
    assert st["gate_verdicts"] == {}


def test_save_then_load_roundtrips(tmp_path):
    st = flowstate.new_state(_FLOW, state_dir=tmp_path)
    flowstate.save_state(st, state_dir=tmp_path)
    loaded = flowstate.load_state("build-1", state_dir=tmp_path)
    assert loaded["flow_id"] == "build-1"
    assert loaded["phases"] == _FLOW["phases"]
    assert loaded["current_phase"] == 0


def test_load_missing_flow_returns_none(tmp_path):
    assert flowstate.load_state("nope", state_dir=tmp_path) is None


def test_state_file_path_is_one_file_per_flow_id(tmp_path):
    flowstate.save_state(flowstate.new_state(_FLOW, state_dir=tmp_path),
                         state_dir=tmp_path)
    expected = tmp_path / "build-1.json"
    assert expected.exists()


def test_record_verdict_is_persisted(tmp_path):
    st = flowstate.new_state(_FLOW, state_dir=tmp_path)
    st["gate_verdicts"]["test"] = {"satisfied": True, "overall": "PASS"}
    flowstate.save_state(st, state_dir=tmp_path)
    loaded = flowstate.load_state("build-1", state_dir=tmp_path)
    assert loaded["gate_verdicts"]["test"]["satisfied"] is True


def test_unsafe_flow_id_is_rejected(tmp_path):
    bad = dict(_FLOW, flow_id="../etc/passwd")
    try:
        flowstate.new_state(bad, state_dir=tmp_path)
        raised = False
    except ValueError:
        raised = True
    assert raised is True
