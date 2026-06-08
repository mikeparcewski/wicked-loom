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

## License

MIT © Mike Parcewski. See [`LICENSE`](LICENSE).
