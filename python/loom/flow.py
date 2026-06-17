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

The never-fake contract (capability-gap): before re-deriving a gated phase, the
runner checks the flow's ``peers_required`` against the manifest's declared
capability ``status``. If a required peer is unknown, unresolvable, or not
``wired`` (planned/experimental), the runner blocks FAIL-CLOSED with a precise
``capability-gap`` — naming exactly which peer must be installed/wired — instead
of letting the gate fail opaquely as a generic "unavailable". This activates the
previously-inert ``peers_required`` field (captured into state by flowstate but
never read here before) and makes loom's fail-closed posture diagnosable. It is
strictly additive to the gate: it can only BLOCK, never satisfy (consistent with
I2 — loom never invents a pass).

The vault runner and bus runner are injected (``vault_run`` / ``bus_run``) so a
flow test never spawns a real vault or bus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from loom import busemit, flowstate, manifest
from loom.compose import RunResult, _default_run
from loom.gate import run_gate
from loom.resolve import resolve  # re-exported so tests can patch flow.resolve

Runner = Callable[..., RunResult]

_GATE_PREFIX = "produces:"


def _is_hard(hitl: Optional[str]) -> bool:
    """A hard gate is any hitl discipline of the form ``hard:*`` (spec §3.1)."""
    return isinstance(hitl, str) and hitl.startswith("hard:")


def _capability_gaps(peers_required: list) -> list:
    """Return one gap descriptor per required peer the runtime must NOT depend
    on yet. The never-fake check: a required peer is a gap when it is

      * unknown   — not in the manifest at all, or
      * unwired   — declared capability ``status`` is not ``wired``
                    (planned/experimental), or
      * unresolvable — no runnable command resolves (PATH/npx/env kill-switch).

    Pure + deterministic (resolve() spawns nothing). Each descriptor names the
    offending peer and WHY, plus the install command when one is known — so the
    emitted gap tells an operator exactly what to do.
    """
    gaps = []
    for name in peers_required:
        peer = manifest.get(name)
        if peer is None:
            gaps.append({"peer": name, "reason": "unknown",
                         "detail": f"required peer {name!r} is not a known peer"})
            continue
        if not peer.is_wired:
            gaps.append({"peer": name, "reason": "unwired",
                         "capability": peer.status,
                         "install_cmd": peer.install_cmd,
                         "detail": f"required peer {name!r} capability is "
                                   f"{peer.status!r}, not 'wired'"})
            continue
        if resolve(name) is None:
            gaps.append({"peer": name, "reason": "unresolvable",
                         "install_cmd": peer.install_cmd,
                         "detail": f"required peer {name!r} is wired but does not "
                                   f"resolve (install it or set "
                                   f"{peer.env_var})"})
    return gaps


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

    peers_required = state.get("peers_required", [])

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

        # Never-fake: a gated phase depends on its required peers. If any is
        # unknown/unwired/unresolvable, BLOCK fail-closed with a precise gap
        # BEFORE re-deriving — so the failure reads "peer X not wired", not a
        # generic "gate unavailable". This only blocks; it never satisfies (I2).
        gaps = _capability_gaps(peers_required)
        if gaps:
            verdict = {
                "satisfied": False,
                "gate": "capability-gap",
                "overall": "CAPABILITY_GAP",
                "re_derived": False,
                "gaps": gaps,
                "detail": "required peer(s) not wired/resolvable; flow blocks "
                          "fail-closed without re-deriving (never-fake).",
            }
            state["gate_verdicts"][name] = verdict
            busemit.emit("capability-gap",
                         {"flow_id": flow_id, "phase": name, "gaps": gaps},
                         run=bus_run)
            flowstate.save_state(state, state_dir=state_dir)
            return state  # blocked on capability; status stays "running" (I2)

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
