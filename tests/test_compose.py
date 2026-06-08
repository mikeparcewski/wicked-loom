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


def test_check_peer_probe_failure_is_error():
    with patch.object(compose, "resolve_version_bin", return_value=["wicked-vault"]):
        r = compose.check_peer("vault", run=_runner(code=1))
    assert r["status"] == "error"


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


def test_brain_probe_unparseable_version_is_error():
    """The original bug surfaced as 'unparseable version' when the wrong binary
    was probed; guard that a genuinely unparseable probe still classifies error."""
    run, _calls = _capturing_runner(stdout="not a version\n")
    with patch.object(compose, "resolve_version_bin",
                      return_value=["npx", "wicked-brain-server"]):
        r = compose.check_peer("brain", run=run)
    assert r["status"] == "error"
    assert r["detail"] == "unparseable version"


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
