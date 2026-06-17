"""flowstate.py — per-flow JSON state. One file per flow_id.

phase_manager-style local state (spec §4.2 "persist phase state", §10 "local
JSON, deterministic, no network"). The state directory is a parameter so tests
inject a tmp dir and production injects a project-scoped path; this module never
hardcodes a home path and never spawns a process.

State schema:
  flow_id        : str (validated kebab/snake/alphanumeric, max 64 — no path sep)
  phases         : list[dict]  (the original flow-def phases, verbatim)
  current_phase  : int         (index into phases; == len(phases) when completed)
  gate_verdicts  : dict[phase_name -> verdict dict]
  parked         : bool
  parked_reason  : str | None
  status         : "running" | "parked" | "completed"
  created_at     : ISO8601 str (written, never asserted-on)
  updated_at     : ISO8601 str (written, never asserted-on)

Nothing here raises except on an unsafe flow_id (ValueError — a guard, not a
swallowed error, R4). A missing state file on load returns None.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_FLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

STATUS_RUNNING = "running"
STATUS_PARKED = "parked"
STATUS_COMPLETED = "completed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_peers_required(peers_required) -> list:
    """Coerce a flow/state ``peers_required`` field to a clean list of peer names.

    A flow def (or a hand-edited state file) may carry ``peers_required`` as
    ``null``/missing, or — malformed — as a non-list (e.g. a bare string).
    ``list(None)`` would raise and ``list("vault")`` would silently explode a
    string into characters, so we never feed this field to ``list()`` directly.
    Treat null/missing/any non-list as "no required peers", and keep only the
    string entries of a list (the peer names downstream code expects). This
    keeps state construction and the capability check fail-closed-by-evidence
    rather than crashing or misbehaving on shape (R4: guard, don't swallow).
    """
    if not isinstance(peers_required, list):
        return []
    return [p for p in peers_required if isinstance(p, str)]


def _validate_flow_id(flow_id: str) -> str:
    if not isinstance(flow_id, str) or not _FLOW_ID_RE.match(flow_id):
        raise ValueError(f"unsafe flow_id: {flow_id!r} (kebab/snake/alnum, max 64)")
    return flow_id


def _state_path(flow_id: str, state_dir: Path) -> Path:
    return Path(state_dir) / f"{_validate_flow_id(flow_id)}.json"


def new_state(flow_def: dict, *, state_dir: Path) -> dict:
    """Build a fresh running state from a flow definition. Does not persist."""
    flow_id = _validate_flow_id(flow_def["flow_id"])
    now = _now()
    return {
        "flow_id": flow_id,
        "phases": list(flow_def.get("phases", [])),
        "peers_required": normalize_peers_required(flow_def.get("peers_required")),
        "verifier_spec_ref": flow_def.get("verifier_spec_ref"),
        "current_phase": 0,
        "gate_verdicts": {},
        "parked": False,
        "parked_reason": None,
        "status": STATUS_RUNNING,
        "created_at": now,
        "updated_at": now,
    }


def save_state(state: dict, *, state_dir: Path) -> Path:
    """Atomically write the state file for ``state['flow_id']`` and return its path."""
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    path = _state_path(state["flow_id"], state_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_state(flow_id: str, *, state_dir: Path) -> Optional[dict]:
    """Load the state for ``flow_id``; None if no file exists."""
    path = _state_path(flow_id, state_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
