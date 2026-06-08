from unittest.mock import patch

from loom import compose


def _runner(stdout="", code=0):
    def run(cmd, timeout=None):
        return compose.RunResult(returncode=code, stdout=stdout, stderr="")
    return run


def test_check_peer_satisfied_when_version_meets_pin():
    with patch.object(compose, "resolve", return_value=["wicked-vault"]):
        r = compose.check_peer("vault", run=_runner(stdout="wicked-vault 0.3.2\n"))
    assert r["status"] == "ok"
    assert r["installed"] == "0.3.2"
    assert r["pin"] == "0.3"


def test_check_peer_below_pin_is_drift():
    with patch.object(compose, "resolve", return_value=["wicked-vault"]):
        r = compose.check_peer("vault", run=_runner(stdout="0.2.9"))
    assert r["status"] == "drift"


def test_check_peer_unresolvable_is_missing():
    with patch.object(compose, "resolve", return_value=None):
        r = compose.check_peer("vault", run=_runner())
    assert r["status"] == "missing"


def test_check_peer_probe_failure_is_error():
    with patch.object(compose, "resolve", return_value=["wicked-vault"]):
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
    with patch.object(compose, "resolve", return_value=["x"]):
        rows = compose.check_all(run=_runner(stdout="9.9.9"))
    assert {row["peer"] for row in rows} == {"vault", "testing", "brain", "bus"}
