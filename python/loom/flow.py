"""flow.py — the archetype-agnostic flow runner (conduct orchestration).

Executes a declarative flow definition (spec §3.1): advance phases; on a gated
phase, re-derive synchronously via gate.py; park at a hard gate; persist state
via flowstate.py; announce transitions via busemit.py (best-effort).

Invariants (spec §5):
  I1/I2/I3 — inherited from gate.py (synchronous, fail-closed, fail-soft spec).
  I4 — bus emission is best-effort and never gates; an event never advances a
       phase. Only a re-derived gate verdict advances.
  I5 — autonomy never overrides a hard gate: on a satisfied hard:* gate the flow
       PARKS and emits needs-human; it never self-approves. ``resume`` advances
       past an approved hard gate only because a human acted out-of-band.
  I6 — archetype-agnostic: this module branches ONLY on the flow definition's
       ``gate`` / ``hitl`` fields, never on archetype names.

The vault runner and bus runner are injected (``vault_run`` / ``bus_run``) so a
flow test never spawns a real vault or bus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from loom import busemit, flowstate
from loom.compose import RunResult, _default_run
from loom.gate import run_gate
from loom.resolve import resolve  # re-exported so tests can patch flow.resolve

Runner = Callable[..., RunResult]

_GATE_PREFIX = "produces:"


def _is_hard(hitl: Optional[str]) -> bool:
    """A hard gate is any hitl discipline of the form ``hard:*`` (spec §3.1)."""
    return isinstance(hitl, str) and hitl.startswith("hard:")


def _produces_of(gate_spec: str) -> str:
    """Map a flow-def gate string to the vault produces id.

    "produces:test-report" -> "test-report". A non-"produces:" gate string is
    passed through verbatim (still re-derived; never a vacuous pass — I2).
    """
    if gate_spec.startswith(_GATE_PREFIX):
        return gate_spec[len(_GATE_PREFIX):]
    return gate_spec


def _advance(state: dict, *, state_dir: Path,
             vault_run: Runner, bus_run: Runner) -> dict:
    """Run the phase loop from state['current_phase']; persist + return state."""
    phases = state["phases"]
    flow_id = state["flow_id"]
    verifier_spec = state.get("verifier_spec_ref")

    while state["current_phase"] < len(phases):
        phase = phases[state["current_phase"]]
        name = phase.get("name", str(state["current_phase"]))
        gate_spec = phase.get("gate")
        hitl = phase.get("hitl")

        if not gate_spec:
            busemit.emit("phase-advanced",
                         {"flow_id": flow_id, "phase": name}, run=bus_run)
            state["current_phase"] += 1
            continue

        verdict = run_gate(_produces_of(gate_spec), scope=flow_id,
                           with_attestations=_is_hard(hitl),
                           verifier_spec=verifier_spec, run=vault_run)
        state["gate_verdicts"][name] = verdict

        if not verdict.get("satisfied"):
            busemit.emit("gate-failed",
                         {"flow_id": flow_id, "phase": name,
                          "overall": verdict.get("overall")}, run=bus_run)
            flowstate.save_state(state, state_dir=state_dir)
            return state  # blocked on evidence; status stays "running" (I2)

        busemit.emit("gate-passed",
                     {"flow_id": flow_id, "phase": name}, run=bus_run)

        if _is_hard(hitl):
            state["parked"] = True
            state["parked_reason"] = f"hard gate at phase '{name}' ({hitl})"
            state["status"] = flowstate.STATUS_PARKED
            busemit.emit("needs-human",
                         {"flow_id": flow_id, "phase": name, "hitl": hitl},
                         run=bus_run)
            flowstate.save_state(state, state_dir=state_dir)
            return state  # PARK — loom never self-approves a hard gate (I5)

        busemit.emit("phase-advanced",
                     {"flow_id": flow_id, "phase": name}, run=bus_run)
        state["current_phase"] += 1

    state["status"] = flowstate.STATUS_COMPLETED
    busemit.emit("completed", {"flow_id": flow_id}, run=bus_run)
    flowstate.save_state(state, state_dir=state_dir)
    return state


def run_flow(flow_def: dict, *, state_dir: Path,
             vault_run: Runner = _default_run,
             bus_run: Runner = _default_run) -> dict:
    """Start a new flow: build state, emit started, advance through phases."""
    state = flowstate.new_state(flow_def, state_dir=state_dir)
    flowstate.save_state(state, state_dir=state_dir)
    busemit.emit("started", {"flow_id": state["flow_id"]}, run=bus_run)
    return _advance(state, state_dir=state_dir,
                    vault_run=vault_run, bus_run=bus_run)


def status(flow_id: str, *, state_dir: Path) -> Optional[dict]:
    """Read persisted flow state without advancing or any side effect."""
    return flowstate.load_state(flow_id, state_dir=state_dir)


def resume(flow_id: str, *, state_dir: Path,
           vault_run: Runner = _default_run,
           bus_run: Runner = _default_run) -> Optional[dict]:
    """Resume a parked/running flow. If parked at a hard gate, a human has
    approved it out-of-band (I5) — advance PAST that phase without re-running
    its gate, then continue the normal loop."""
    state = flowstate.load_state(flow_id, state_dir=state_dir)
    if state is None:
        return None
    if state.get("parked"):
        state["parked"] = False
        state["parked_reason"] = None
        state["status"] = flowstate.STATUS_RUNNING
        state["current_phase"] += 1  # human-approved hard gate: step past it
    return _advance(state, state_dir=state_dir,
                    vault_run=vault_run, bus_run=bus_run)
