```
           _      __            __        __
 _      __(_)____/ /_____  ____/ /       / /___  ____  ____ ___
| | /| / / / ___/ //_/ _ \/ __  /       / / __ \/ __ \/ __ `__ \
| |/ |/ / / /__/ ,< /  __/ /_/ /       / / /_/ / /_/ / / / / / /
|__/|__/_/\___/_/|_|\___/\__,_/       /_/\____/\____/_/ /_/ /_/
```

**Local-first orchestration runtime for agent ecosystems.** 0.1 ships the
**`compose` surface** — it resolves, version-checks, and installs the `wicked-*`
peer set. Conduct (gate/flow) ships separately.

Sibling to wicked-bus / wicked-brain / wicked-testing / wicked-vault. The npm
package launches a bundled Python 3 core, so `python3` must be on PATH.

## Install

The CLI runs via `npx wicked-loom <command>` once the package is present —
there is no separate install step. It launches a bundled Python core, so
`python3` must be on PATH.

## Use

```bash
npx wicked-loom doctor                      # check every peer
npx wicked-loom resolve vault               # print vault's runnable command
npx wicked-loom compose install --peer bus  # install one peer
```

## Resolution ladder

For each peer: `WICKED_<PEER>_BIN` env (empty = kill-switch) → `PATH` →
`npx <package>`.

## Peers

vault · testing · brain · bus — pins mirror wicked-garden's `required-peers`.

## Conduct (gate + flow)

Synchronous, fail-closed evidence gating and an archetype-agnostic flow runtime.

    npx wicked-loom gate test-report --scope build-1        # re-derive one produces via the vault
    npx wicked-loom gate verdict --scope b1 --with-attestations
    npx wicked-loom flow run ./flow-def.json                 # run a flow definition
    npx wicked-loom flow status build-1                      # read a flow's state
    npx wicked-loom flow resume build-1                      # continue past an approved hard gate

**Invariants:** gates are synchronous and re-derive every call (an event never
satisfies a gate); a missing vault fails **closed** (`gate: "unavailable"`,
never a pass); the verifier spec is fail-**soft** (absent → generic detection,
never blocks). The runner is archetype-agnostic — it executes any flow
definition (`phases[]` with optional `gate`/`hitl`, `peers_required`,
`verifier_spec_ref`) and parks at any `hard:*` gate, never self-approving.

The headless bus-consumer / unattended execution mode is **deferred** — this
release emits transition events best-effort but does not react to them.

## Flow definition

    {
      "flow_id": "build-1",
      "phases": [
        { "name": "plan",   "gate": null,                   "hitl": "none" },
        { "name": "test",   "gate": "produces:test-report", "hitl": "discrete:review" },
        { "name": "review", "gate": "produces:verdict",     "hitl": "hard:final-verdict" }
      ],
      "peers_required": ["vault", "testing"],
      "verifier_spec_ref": null
    }

## License

MIT © Mike Parcewski. See [`LICENSE`](LICENSE).
