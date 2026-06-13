from unittest.mock import patch

from loom import compose


def _runner(stdout="", code=0):
    def run(cmd, timeout=None):
        return compose.RunResult(returncode=code, stdout=stdout, stderr="")
    return run


def _capturing_runner(stdout="9.9.9", code=0):
    """A runner that records every argv it was handed (for probe-target asserts)."""
    calls = []

    def run(cmd, timeout=None):
        calls.append(cmd)
        return compose.RunResult(returncode=code, stdout=stdout, stderr="")

    return run, calls


def test_check_peer_satisfied_when_version_meets_pin():
    with patch.object(compose, "resolve_version_bin", return_value=["wicked-vault"]):
        r = compose.check_peer("vault", run=_runner(stdout="wicked-vault 0.3.2\n"))
    assert r["status"] == "ok"
    assert r["installed"] == "0.3.2"
    assert r["pin"] == "0.3"


def test_check_peer_below_pin_is_drift():
    with patch.object(compose, "resolve_version_bin", return_value=["wicked-vault"]):
        r = compose.check_peer("vault", run=_runner(stdout="0.2.9"))
    assert r["status"] == "drift"


def test_check_peer_unresolvable_is_missing():
    with patch.object(compose, "resolve_version_bin", return_value=None):
        r = compose.check_peer("vault", run=_runner())
    assert r["status"] == "missing"


def test_check_peer_nonzero_exit_but_resolved_is_present_not_error():
    """A resolved binary that exits non-zero (e.g. an older CLI that prints
    help/usage for an unrecognized --version) is PRESENT and responding — not a
    hard error. Cry-wolf finding: this used to be reported as "error"."""
    with patch.object(compose, "resolve_version_bin", return_value=["wicked-vault"]):
        r = compose.check_peer("vault", run=_runner(code=1))
    assert r["status"] == "present"
    assert r["ok"] is True
    assert r["status"] != "error"


def test_check_peer_probe_raise_is_error():
    """The ONLY path to "error" after resolution succeeds: the probe attempt
    itself RAISES (binary vanished mid-call / OS error). Genuine fault."""
    def boom(cmd, timeout=None):
        raise OSError("No such file or directory")

    with patch.object(compose, "resolve_version_bin", return_value=["wicked-vault"]):
        r = compose.check_peer("vault", run=boom)
    assert r["status"] == "error"
    assert r["ok"] is False


def test_install_peer_runs_install_cmd_and_reports():
    calls = []

    def run(cmd, timeout=None):
        calls.append(cmd)
        return compose.RunResult(returncode=0, stdout="ok", stderr="")

    r = compose.install_peer("vault", run=run)
    assert calls == [["npx", "wicked-vault-install"]]
    assert r["status"] == "installed"


def test_install_unknown_peer_is_error():
    r = compose.install_peer("nope", run=_runner())
    assert r["status"] == "error"


def test_check_all_returns_one_row_per_peer():
    with patch.object(compose, "resolve_version_bin", return_value=["x"]):
        rows = compose.check_all(run=_runner(stdout="9.9.9"))
    assert {row["peer"] for row in rows} == {"vault", "testing", "brain", "bus"}


# --- version-probe binary targeting (issue: brain probed via wrong binary) ---


def test_brain_probe_targets_brain_server_not_brain():
    """Brain's version lives in wicked-brain-server; the probe must hit that
    binary, never the wicked-brain package."""
    run, calls = _capturing_runner(stdout="wicked-brain-server 0.14.0\n")
    with patch.object(compose, "resolve_version_bin",
                      return_value=["npx", "wicked-brain-server"]):
        r = compose.check_peer("brain", run=run)
    assert calls == [["npx", "wicked-brain-server", "--version"]]
    assert "wicked-brain-server" in calls[0]
    assert "wicked-brain" not in calls[0]  # the bare package never gets probed
    assert r["status"] == "ok"
    assert r["installed"] == "0.14.0"


def test_brain_probe_below_pin_is_drift():
    run, _calls = _capturing_runner(stdout="wicked-brain-server 0.13.9\n")
    with patch.object(compose, "resolve_version_bin",
                      return_value=["npx", "wicked-brain-server"]):
        r = compose.check_peer("brain", run=run)
    assert r["status"] == "drift"
    assert r["installed"] == "0.13.9"


def test_brain_probe_unparseable_version_is_present_not_error():
    """A probe that RAN but produced no parseable version means the peer is
    present and responding — version merely unknown. This must surface as the
    WARN-level "present" status (ok=True), NOT a hard "error" (cry-wolf finding:
    a responding peer was being reported as error)."""
    run, _calls = _capturing_runner(stdout="not a version\n")
    with patch.object(compose, "resolve_version_bin",
                      return_value=["npx", "wicked-brain-server"]):
        r = compose.check_peer("brain", run=run)
    assert r["status"] == "present"
    assert r["ok"] is True
    assert r["status"] != "error"


def test_same_binary_peers_probe_their_npm_package():
    """vault/testing/bus probe binary == npm_package binary — appending the
    probe's trailing args must not change which binary is invoked."""
    for name in ("vault", "testing", "bus"):
        peer = compose.manifest.get(name)
        run, calls = _capturing_runner(stdout="9.9.9")
        with patch.object(compose, "resolve_version_bin",
                          return_value=[peer.npm_package]):
            r = compose.check_peer(name, run=run)
        assert calls == [[peer.npm_package, "--version"]]
        assert r["status"] == "ok"


# --- cry-wolf finding: a HEALTHY bus must never be reported status=error ------
#
# Root cause: ``wicked-bus --version`` on an older/help-printing CLI emits the
# usage JSON to stdout and exits NON-ZERO. The probe got a clean RunResult (the
# bus is installed and responding), yet loom declared a hard "error". A healthy
# peer must never be reported as an error. The fix distinguishes "present but
# version unknown" (ok, warn-level) from "genuinely absent" (missing / raised).


# Verbatim shape of what a real, healthy `wicked-bus --version` prints today:
# usage JSON to stdout, exit code 1 (no clean version string anywhere).
_BUS_HELP_JSON = (
    '{\n'
    '  "usage": "wicked-bus <command> [options]",\n'
    '  "commands": ["init", "emit", "subscribe", "status"],\n'
    '  "global_flags": ["--db-path <path>", "--json", "--log-level <level>"]\n'
    '}\n'
)


def test_healthy_bus_with_help_style_version_output_is_not_error():
    """Drive the REAL probe with a fake bus that returns help-style JSON and a
    non-zero exit (the exact reproduction of the cry-wolf finding). A healthy,
    responding bus must NOT yield status "error"."""
    run, calls = _capturing_runner(stdout=_BUS_HELP_JSON, code=1)
    with patch.object(compose, "resolve_version_bin", return_value=["wicked-bus"]):
        r = compose.check_peer("bus", run=run)
    # The real probe binary/args were exercised — not stubbed away.
    assert calls == [["wicked-bus", "--version"]]
    # The healthy bus is NOT a hard error.
    assert r["status"] != "error"
    assert r["status"] == "present"
    assert r["ok"] is True


def test_healthy_bus_with_clean_version_output_is_ok():
    """The sibling fix gives wicked-bus a clean ``--version``. When that lands,
    loom parses it and reports ok — no regression for the modern bus."""
    run, calls = _capturing_runner(stdout="wicked-bus 2.1.0\n", code=0)
    with patch.object(compose, "resolve_version_bin", return_value=["wicked-bus"]):
        r = compose.check_peer("bus", run=run)
    assert calls == [["wicked-bus", "--version"]]
    assert r["status"] == "ok"
    assert r["ok"] is True
    assert r["installed"] == "2.1.0"


def test_neither_healthy_bus_case_reports_error():
    """Belt-and-suspenders over both healthy shapes (help-style + clean): the
    one thing that must hold is that a responding bus is never status=error."""
    for stdout, code in ((_BUS_HELP_JSON, 1), ("wicked-bus 2.0.0", 0)):
        run, _calls = _capturing_runner(stdout=stdout, code=code)
        with patch.object(compose, "resolve_version_bin", return_value=["wicked-bus"]):
            r = compose.check_peer("bus", run=run)
        assert r["status"] != "error"
        assert r["ok"] is True


def test_genuinely_absent_bus_is_missing_not_ok():
    """Fail-closed for a genuinely absent bus is preserved: unresolvable ->
    "missing", ok=False (NOT silently treated as healthy)."""
    with patch.object(compose, "resolve_version_bin", return_value=None):
        r = compose.check_peer("bus", run=_runner())
    assert r["status"] == "missing"
    assert r["ok"] is False
