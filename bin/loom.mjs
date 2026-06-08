#!/usr/bin/env node
// Thin launcher: find python3 and exec `python3 -m loom <args>` with python/ on PYTHONPATH.
// All logic lives in the Python module; this file only bridges npx -> python3.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const pyRoot = join(here, "..", "python");

function findPython() {
  for (const cand of ["python3", "python", "py"]) {
    const r = spawnSync(cand, ["--version"], { stdio: "ignore" });
    if (r.status === 0) return cand;
  }
  return null;
}

const python = findPython();
if (!python) {
  console.error("[wicked-loom] python3 is required but was not found on PATH.");
  process.exit(127);
}

const env = { ...process.env, PYTHONPATH: pyRoot + (process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : "") };
const res = spawnSync(python, ["-m", "loom", ...process.argv.slice(2)], { stdio: "inherit", env });
process.exit(res.status === null ? 1 : res.status);
