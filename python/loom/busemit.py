"""busemit.py — best-effort fire-and-forget bus emission. Emission ONLY.

The bus is the spine for everything that is NOT a gate verdict (spec §4.4/I4):
phase transitions, needs-human parks, audit. Emission is fire-and-forget — an
unresolvable, erroring, or slow bus must NEVER raise and NEVER block the flow.
An emitted event NEVER satisfies a gate (I4) — gates are synchronous and direct
(gate.py); this module only announces.

The bus consumer / projector and any headless reaction to these events are
DEFERRED (spec D3 / §9 D-headless). This file is the producer side only.

Stable event names (spec §4.3 #3):
  loom:flow:started | phase-advanced | gate-passed | gate-failed
                    | needs-human | completed
"""

from __future__ import annotations

import json
from typing import Callable

from loom.compose import RunResult, _default_run
from loom.resolve import resolve

Runner = Callable[..., RunResult]

_EMIT_TIMEOUT = 5  # seconds; emission is best-effort, keep it short (R5).

EVENTS: dict = {
    "started": "loom:flow:started",
    "phase-advanced": "loom:flow:phase-advanced",
    "gate-passed": "loom:flow:gate-passed",
    "gate-failed": "loom:flow:gate-failed",
    "needs-human": "loom:flow:needs-human",
    "completed": "loom:flow:completed",
}


def emit(event_key: str, payload: dict, *, run: Runner = _default_run) -> bool:
    """Fire-and-forget emit. Returns True iff the bus accepted it (exit 0).

    Never raises: an unknown event, an unresolvable bus, or any subprocess
    failure is reported as ``False`` (I4 — the bus is optional infrastructure).
    """
    event_type = EVENTS.get(event_key)
    if event_type is None:
        return False

    bus_prefix = resolve("bus")
    if bus_prefix is None:
        return False

    argv = list(bus_prefix) + ["emit", event_type, json.dumps(payload)]
    try:
        result = run(argv, timeout=_EMIT_TIMEOUT)
    except Exception:  # noqa: BLE001 — fire-and-forget; bus is optional (I4)
        return False
    return result.returncode == 0
