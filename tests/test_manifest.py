from loom import manifest


def test_known_peers_present():
    assert set(manifest.PEERS) == {"vault", "testing", "brain", "bus"}


def test_each_peer_has_required_fields():
    for name, peer in manifest.PEERS.items():
        assert peer.name == name
        assert peer.npm_package.startswith("wicked-")
        assert peer.env_var.startswith("WICKED_") and peer.env_var.endswith("_BIN")
        assert peer.version_pin  # non-empty
        assert isinstance(peer.install_cmd, list) and peer.install_cmd
        assert isinstance(peer.probe_cmd, list) and peer.probe_cmd


def test_vault_pins_match_garden():
    assert manifest.PEERS["vault"].version_pin == "0.3"
    assert manifest.PEERS["vault"].env_var == "WICKED_VAULT_BIN"


def test_get_unknown_peer_returns_none():
    assert manifest.get("nope") is None
