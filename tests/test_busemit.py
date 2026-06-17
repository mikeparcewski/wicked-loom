from unittest.mock import patch

from loom import busemit
from loom.compose import RunResult


def test_event_names_are_the_spec_set():
    assert busemit.EVENTS["started"] == "loom:flow:started"
    assert busemit.EVENTS["phase-advanced"] == "loom:flow:phase-advanced"
    assert busemit.EVENTS["gate-passed"] == "loom:flow:gate-passed"
    assert busemit.EVENTS["gate-failed"] == "loom:flow:gate-failed"
    assert busemit.EVENTS["capability-gap"] == "loom:flow:capability-gap"
    assert busemit.EVENTS["needs-human"] == "loom:flow:needs-human"
    assert busemit.EVENTS["completed"] == "loom:flow:completed"


def test_capability_gap_event_is_emittable():
    """The never-fake announcement is a real, fire-and-forget event like the
    rest — emits via the bus, reports True on accept."""
    seen = {}

    def run(cmd, timeout=None):
        seen["cmd"] = cmd
        return RunResult(returncode=0, stdout="", stderr="")

    with patch.object(busemit, "resolve", return_value=["wicked-bus"]):
        ok = busemit.emit("capability-gap",
                          {"flow_id": "f1", "phase": "test", "gaps": []}, run=run)
    assert ok is True
    assert "loom:flow:capability-gap" in seen["cmd"]


def test_emit_invokes_bus_with_event_and_payload():
    seen = {}

    def run(cmd, timeout=None):
        seen["cmd"] = cmd
        return RunResult(returncode=0, stdout="", stderr="")

    with patch.object(busemit, "resolve", return_value=["wicked-bus"]):
        ok = busemit.emit("started", {"flow_id": "build-1"}, run=run)
    assert ok is True
    assert "loom:flow:started" in seen["cmd"]


def test_emit_is_fail_soft_when_bus_unresolvable():
    with patch.object(busemit, "resolve", return_value=None):
        ok = busemit.emit("started", {"flow_id": "build-1"})
    assert ok is False  # best-effort: reports, never raises


def test_emit_never_raises_when_bus_errors():
    def boom(cmd, timeout=None):
        raise FileNotFoundError("bus gone")

    with patch.object(busemit, "resolve", return_value=["wicked-bus"]):
        ok = busemit.emit("needs-human", {"flow_id": "build-1"}, run=boom)
    assert ok is False  # swallowed at the boundary by design (I4), reported as data


def test_emit_unknown_event_is_false_not_raise():
    with patch.object(busemit, "resolve", return_value=["wicked-bus"]):
        ok = busemit.emit("frobnicate", {"flow_id": "build-1"})
    assert ok is False
