import shutil
from unittest.mock import patch

from loom import resolve


def test_env_var_override_wins(monkeypatch):
    monkeypatch.setenv("WICKED_VAULT_BIN", "/opt/custom/vault")
    assert resolve.resolve("vault") == ["/opt/custom/vault"]


def test_empty_env_var_is_killswitch(monkeypatch):
    monkeypatch.setenv("WICKED_VAULT_BIN", "")
    assert resolve.resolve("vault") is None


def test_path_lookup_when_no_env(monkeypatch):
    monkeypatch.delenv("WICKED_VAULT_BIN", raising=False)
    with patch.object(shutil, "which", return_value="/usr/local/bin/wicked-vault"):
        assert resolve.resolve("vault") == ["/usr/local/bin/wicked-vault"]


def test_npx_fallback_when_not_on_path(monkeypatch):
    monkeypatch.delenv("WICKED_VAULT_BIN", raising=False)
    with patch.object(shutil, "which", return_value=None):
        assert resolve.resolve("vault") == ["npx", "wicked-vault"]


def test_unknown_peer_returns_none():
    assert resolve.resolve("nope") is None


# --- resolve_version_bin: probe binary may differ from the run package ---


def test_version_bin_brain_resolves_server_via_path(monkeypatch):
    monkeypatch.delenv("WICKED_BRAIN_BIN", raising=False)
    with patch.object(shutil, "which", return_value="/usr/local/bin/wicked-brain-server"):
        assert resolve.resolve_version_bin("brain") == ["/usr/local/bin/wicked-brain-server"]


def test_version_bin_brain_npx_fallback_uses_server(monkeypatch):
    monkeypatch.delenv("WICKED_BRAIN_BIN", raising=False)
    with patch.object(shutil, "which", return_value=None):
        assert resolve.resolve_version_bin("brain") == ["npx", "wicked-brain-server"]


def test_version_bin_same_binary_peer_uses_npm_package(monkeypatch):
    monkeypatch.delenv("WICKED_VAULT_BIN", raising=False)
    with patch.object(shutil, "which", return_value=None):
        assert resolve.resolve_version_bin("vault") == ["npx", "wicked-vault"]


def test_version_bin_honors_killswitch(monkeypatch):
    monkeypatch.setenv("WICKED_BRAIN_BIN", "")
    assert resolve.resolve_version_bin("brain") is None


def test_version_bin_honors_env_override(monkeypatch):
    monkeypatch.setenv("WICKED_BRAIN_BIN", "/opt/custom/brain")
    assert resolve.resolve_version_bin("brain") == ["/opt/custom/brain"]


def test_version_bin_unknown_peer_returns_none():
    assert resolve.resolve_version_bin("nope") is None
