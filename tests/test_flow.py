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


# --- never-fake: peers_required is now READ; a non-wired/unresolvable peer
#     before a gated phase blocks fail-closed with a capability-gap -----------


def _gated_flow(flow_id, peers_required):
    """A flow whose FIRST phase is gateless and SECOND is gated — so the
    capability check (which guards gated phases) is what stops the walk."""
    return {
        "flow_id": flow_id,
        "phases": [
            {"name": "plan", "gate": None, "hitl": "none"},
            {"name": "test", "gate": "produces:test-report", "hitl": "discrete:review"},
        ],
        "peers_required": peers_required,
        "verifier_spec_ref": None,
    }


def _boom_vault():
    """A vault runner that MUST NOT be called: if the capability-gap fires
    before the gate, the gate is never re-derived, so this never runs."""
    def run(cmd, timeout=None):
        raise AssertionError("gate was re-derived despite a capability-gap")
    return run


def test_unwired_required_peer_emits_capability_gap_and_blocks(tmp_path):
    """A flow requiring a PLANNED peer blocks fail-closed BEFORE the gate: the
    runner emits capability-gap, records the verdict, never advances the gated
    phase, and never re-derives (the vault runner is never invoked). I2-style
    fail-closed — loom blocks, it never fakes a pass."""
    from loom import manifest
    planned = manifest.Peer(name="planned-peer", npm_package="wicked-planned",
                            env_var="WICKED_PLANNED_BIN", version_pin="1.0",
                            install_cmd=["npx", "wicked-planned"],
                            probe_cmd=["wicked-planned", "--version"],
                            status=manifest.STATUS_PLANNED)
    fd = _gated_flow("gap-planned", ["planned-peer"])
    events = []

    def recording_bus(cmd, timeout=None):
        events.append(cmd)
        return RunResult(returncode=0, stdout="", stderr="")

    with patch.dict(manifest.PEERS, {"planned-peer": planned}):
        with patch.object(flow, "resolve", return_value=["wicked-planned"]):
            st = flow.run_flow(fd, state_dir=tmp_path,
                               vault_run=_boom_vault(), bus_run=recording_bus)

    # Blocked at the gated phase ("test", idx 1) — NOT advanced, NOT parked.
    assert st["status"] == "running"
    assert st["parked"] is False
    assert st["current_phase"] == 1
    verdict = st["gate_verdicts"]["test"]
    assert verdict["satisfied"] is False
    assert verdict["gate"] == "capability-gap"
    assert verdict["overall"] == "CAPABILITY_GAP"
    assert verdict["re_derived"] is False
    # The gap names the offending peer and why.
    gap = verdict["gaps"][0]
    assert gap["peer"] == "planned-peer"
    assert gap["reason"] == "unwired"
    assert gap["capability"] == "planned"
    # A capability-gap event was announced on the bus (best-effort).
    assert any("loom:flow:capability-gap" in c for c in events)


def test_unknown_required_peer_is_a_capability_gap(tmp_path):
    """A flow requiring a peer that is not in the manifest at all -> gap with
    reason 'unknown'; fail-closed, no advance."""
    fd = _gated_flow("gap-unknown", ["does-not-exist"])
    with patch.object(flow, "resolve", return_value=None):
        st = flow.run_flow(fd, state_dir=tmp_path,
                           vault_run=_boom_vault(), bus_run=_silent_bus())
    assert st["status"] == "running"
    assert st["current_phase"] == 1
    gap = st["gate_verdicts"]["test"]["gaps"][0]
    assert gap["peer"] == "does-not-exist"
    assert gap["reason"] == "unknown"


def test_wired_but_unresolvable_required_peer_is_a_capability_gap(tmp_path):
    """A WIRED peer that does not resolve (kill-switch / not installed) is still
    a gap — diagnosable as 'unresolvable' with the install hint, instead of an
    opaque 'gate unavailable'."""
    fd = _gated_flow("gap-unresolvable", ["vault"])
    # vault IS wired (manifest default) but resolve() returns None here.
    with patch.object(flow, "resolve", return_value=None):
        st = flow.run_flow(fd, state_dir=tmp_path,
                           vault_run=_boom_vault(), bus_run=_silent_bus())
    assert st["status"] == "running"
    assert st["current_phase"] == 1
    gap = st["gate_verdicts"]["test"]["gaps"][0]
    assert gap["peer"] == "vault"
    assert gap["reason"] == "unresolvable"
    assert gap["install_cmd"] == ["npx", "wicked-vault-install"]


def test_capability_gap_is_persisted_and_visible_via_status(tmp_path):
    """The gap verdict is persisted exactly like a gate verdict — status()
    surfaces it without advancing."""
    fd = _gated_flow("gap-persist", ["does-not-exist"])
    with patch.object(flow, "resolve", return_value=None):
        flow.run_flow(fd, state_dir=tmp_path,
                      vault_run=_boom_vault(), bus_run=_silent_bus())
    st = flow.status("gap-persist", state_dir=tmp_path)
    assert st["gate_verdicts"]["test"]["gate"] == "capability-gap"
    assert st["status"] == "running"


def test_wired_resolvable_required_peer_does_not_gap(tmp_path):
    """Control: when every required peer is wired AND resolvable, there is NO
    gap — the gate re-derives normally and the flow advances. Proves the check
    is precise (it does not block a correctly-provisioned flow)."""
    fd = _gated_flow("no-gap", ["vault"])  # vault is wired by default
    # resolve() returns a command (peer resolvable) for both the capability
    # check (flow.resolve) AND the gate (gate.resolve).
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        from loom import gate
        with patch.object(gate, "resolve", return_value=["wicked-vault"]):
            st = flow.run_flow(fd, state_dir=tmp_path,
                               vault_run=_vault("PASS"), bus_run=_silent_bus())
    # No gap -> the gate re-derived (stub PASS) -> the flow COMPLETED past the
    # gated phase (no hard gate in this flow def).
    assert st["status"] == "completed"
    assert st["gate_verdicts"]["test"]["satisfied"] is True
    assert st["gate_verdicts"]["test"]["gate"] == "vault-cross-check"


def test_empty_peers_required_never_gaps(tmp_path):
    """A flow with no peers_required behaves exactly as before this change —
    activating the field must not regress the empty case."""
    fd = _gated_flow("empty-req", [])
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        from loom import gate
        with patch.object(gate, "resolve", return_value=["wicked-vault"]):
            st = flow.run_flow(fd, state_dir=tmp_path,
                               vault_run=_vault("PASS"), bus_run=_silent_bus())
    assert st["status"] == "completed"
    assert st["gate_verdicts"]["test"]["gate"] == "vault-cross-check"


# --- peers_required shape guard: null / missing / malformed must NOT crash or
#     misbehave. Treat null/missing as "no required peers"; never iterate a
#     non-list (a bare string would otherwise be walked char-by-char). ---------


def test_null_peers_required_treated_as_none_and_completes(tmp_path):
    """A flow def with an explicit ``"peers_required": null`` must NOT crash
    (``list(None)`` would). It is treated as "no required peers": construction
    succeeds and the gate re-derives normally to completion."""
    fd = _gated_flow("null-peers", None)  # peers_required is literally None
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        from loom import gate
        with patch.object(gate, "resolve", return_value=["wicked-vault"]):
            st = flow.run_flow(fd, state_dir=tmp_path,
                               vault_run=_vault("PASS"), bus_run=_silent_bus())
    assert st["peers_required"] == []          # normalized at construction
    assert st["status"] == "completed"         # no spurious capability-gap
    assert st["gate_verdicts"]["test"]["gate"] == "vault-cross-check"


def test_missing_peers_required_key_defaults_to_empty(tmp_path):
    """A flow def that OMITS peers_required entirely also normalizes to [] and
    behaves like the empty case (no gap)."""
    fd = {"flow_id": "missing-peers",
          "phases": [{"name": "test", "gate": "produces:test-report",
                      "hitl": "discrete:review"}],
          "verifier_spec_ref": None}  # note: no peers_required key at all
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        from loom import gate
        with patch.object(gate, "resolve", return_value=["wicked-vault"]):
            st = flow.run_flow(fd, state_dir=tmp_path,
                               vault_run=_vault("PASS"), bus_run=_silent_bus())
    assert st["peers_required"] == []
    assert st["status"] == "completed"


def test_string_peers_required_is_not_iterated_char_by_char(tmp_path):
    """A malformed ``"peers_required": "vault"`` (a bare string, not a list)
    must NOT be walked character-by-character into per-char 'unknown' gaps.
    The shape guard collapses any non-list to "no required peers", so the gate
    re-derives normally instead of fabricating bogus gaps for 'v','a','u'..."""
    fd = _gated_flow("string-peers", "vault")  # malformed: a str, not a list
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        from loom import gate
        with patch.object(gate, "resolve", return_value=["wicked-vault"]):
            st = flow.run_flow(fd, state_dir=tmp_path,
                               vault_run=_vault("PASS"), bus_run=_silent_bus())
    assert st["peers_required"] == []          # NOT ['v','a','u','l','t']
    assert st["status"] == "completed"
    assert st["gate_verdicts"]["test"]["gate"] == "vault-cross-check"


def test_advance_tolerates_malformed_peers_required_in_state_file(tmp_path):
    """The read boundary is guarded too: a hand-edited state file whose
    ``peers_required`` is a non-list (here a string) must not crash _advance
    nor be iterated char-by-char. We persist a normal flow, then corrupt the
    field on disk and resume; the run completes without a spurious gap."""
    from loom import flowstate
    fd = _gated_flow("corrupt-state", ["vault"])
    with patch.object(flow, "resolve", return_value=["wicked-vault"]):
        from loom import gate
        with patch.object(gate, "resolve", return_value=["wicked-vault"]):
            flow.run_flow(fd, state_dir=tmp_path,
                          vault_run=_vault("PASS"), bus_run=_silent_bus())
            # Corrupt the persisted state: peers_required -> a bare string.
            st = flowstate.load_state("corrupt-state", state_dir=tmp_path)
            st["peers_required"] = "vault"          # malformed on disk
            st["current_phase"] = 1                 # rewind to the gated phase
            st["status"] = flowstate.STATUS_RUNNING
            st["gate_verdicts"] = {}
            flowstate.save_state(st, state_dir=tmp_path)
            resumed = flow.resume("corrupt-state", state_dir=tmp_path,
                                  vault_run=_vault("PASS"), bus_run=_silent_bus())
    # _advance normalized the malformed field at the read boundary: no char-by-
    # char gap, the gate re-derived, the flow completed.
    assert resumed["status"] == "completed"
    assert resumed["gate_verdicts"]["test"]["gate"] == "vault-cross-check"


def test_normalize_peers_required_unit():
    """Direct unit coverage of the shared normalizer: null/missing/non-list ->
    []; a list keeps only its string entries (drops malformed non-string items)."""
    from loom import flowstate
    assert flowstate.normalize_peers_required(None) == []
    assert flowstate.normalize_peers_required("vault") == []
    assert flowstate.normalize_peers_required(42) == []
    assert flowstate.normalize_peers_required({"vault": 1}) == []
    assert flowstate.normalize_peers_required(["vault", "brain"]) == ["vault", "brain"]
    # Malformed mixed list: non-string entries are dropped, strings kept.
    assert flowstate.normalize_peers_required(["vault", None, 7, "brain"]) == ["vault", "brain"]
    assert flowstate.normalize_peers_required([]) == []
