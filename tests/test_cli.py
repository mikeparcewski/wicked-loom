import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from loom import cli


def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def test_resolve_prints_command():
    with patch("loom.cli.resolve", return_value=["npx", "wicked-vault"]):
        code, out = _run(["resolve", "vault"])
    assert code == 0
    assert json.loads(out)["command"] == ["npx", "wicked-vault"]


def test_resolve_unresolvable_exits_nonzero():
    with patch("loom.cli.resolve", return_value=None):
        code, out = _run(["resolve", "vault"])
    assert code == 1
    assert json.loads(out)["command"] is None


def test_doctor_prints_all_rows():
    rows = [{"peer": "vault", "status": "ok"}]
    with patch("loom.cli.check_all", return_value=rows):
        code, out = _run(["doctor"])
    assert code == 0
    assert json.loads(out)["peers"] == rows


def test_doctor_exits_nonzero_on_missing_peer():
    rows = [{"peer": "vault", "status": "missing"}]
    with patch("loom.cli.check_all", return_value=rows):
        code, _ = _run(["doctor"])
    assert code == 1


def test_compose_install_targets_one_peer():
    with patch("loom.cli.install_peer", return_value={"peer": "vault", "status": "installed"}) as m:
        code, out = _run(["compose", "install", "--peer", "vault"])
    assert code == 0
    m.assert_called_once_with("vault")
    assert json.loads(out)["results"][0]["status"] == "installed"


def test_unknown_command_exits_two():
    code, _ = _run(["frobnicate"])
    assert code == 2
