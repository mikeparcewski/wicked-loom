# wicked-loom

Local-first orchestration runtime for agent ecosystems. **0.1 ships the
`compose` surface** — it resolves, version-checks, and installs the `wicked-*`
peer set. Conduct (gate/flow) ships separately.

## Use

    npx wicked-loom doctor                      # check every peer
    npx wicked-loom resolve vault               # print vault's runnable command
    npx wicked-loom compose install --peer bus  # install one peer

Requires `python3` on PATH (the npm package launches a bundled Python core).

## Resolution ladder

For each peer: `WICKED_<PEER>_BIN` env (empty = kill-switch) → `PATH` →
`npx <package>`.

## Peers

vault · testing · brain · bus — pins mirror wicked-garden's `required-peers`.
