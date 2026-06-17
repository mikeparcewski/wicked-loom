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


def test_version_package_defaults_to_npm_package():
    for name in ("vault", "testing", "bus"):
        peer = manifest.PEERS[name]
        assert peer.version_bin == ""  # no override
        assert peer.version_package == peer.npm_package


def test_brain_version_package_is_brain_server():
    brain = manifest.PEERS["brain"]
    assert brain.npm_package == "wicked-brain"
    assert brain.version_bin == "wicked-brain-server"
    assert brain.version_package == "wicked-brain-server"
    # probe_cmd[0] and version_package agree — the probe targets the same binary
    assert brain.probe_cmd[0] == brain.version_package


# --- capability status (the never-fake contract) ----------------------------


def test_every_shipped_peer_is_wired():
    """Every peer in the manifest today is a WIRED capability — the runtime is
    allowed to depend on each. (Flipping one to planned/experimental is the
    single edit that makes the runner emit a capability-gap.)"""
    for name, peer in manifest.PEERS.items():
        assert peer.status == manifest.STATUS_WIRED, name
        assert peer.is_wired is True, name


def test_status_field_defaults_to_wired():
    """A Peer constructed without an explicit status defaults to wired — so the
    field is backward-compatible with any positional/legacy construction."""
    p = manifest.Peer(name="x", npm_package="wicked-x", env_var="WICKED_X_BIN",
                      version_pin="1.0", install_cmd=["npx", "x"],
                      probe_cmd=["wicked-x", "--version"])
    assert p.status == manifest.STATUS_WIRED
    assert p.is_wired is True


def test_is_wired_is_false_for_planned_and_experimental():
    """The fail-closed predicate: only ``wired`` is trusted. planned /
    experimental / any unrecognised status are NOT wired."""
    base = dict(name="x", npm_package="wicked-x", env_var="WICKED_X_BIN",
                version_pin="1.0", install_cmd=["npx", "x"],
                probe_cmd=["wicked-x", "--version"])
    assert manifest.Peer(**base, status=manifest.STATUS_PLANNED).is_wired is False
    assert manifest.Peer(**base, status=manifest.STATUS_EXPERIMENTAL).is_wired is False
    assert manifest.Peer(**base, status="bogus").is_wired is False


def test_wired_statuses_set_trusts_only_wired():
    assert manifest.STATUS_WIRED in manifest.WIRED_STATUSES
    assert manifest.STATUS_PLANNED not in manifest.WIRED_STATUSES
    assert manifest.STATUS_EXPERIMENTAL not in manifest.WIRED_STATUSES
