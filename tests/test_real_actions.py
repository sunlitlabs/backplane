"""Tests for the real LauncherActions wiring -- real VersionedInstall/
PluginRegistry against a temp directory (the actual mechanism), with only
the GitHub network calls faked (an external boundary, same approach as
test_updater.py).
"""

from __future__ import annotations

import json
from pathlib import Path

from backplane.installer import real_actions as ra
from backplane.host.updater import ReleaseInfo
from backplane.host.subprocess_manager import PluginProcess

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


def _fake_release(repo, tag="v1.0.0"):
    return ReleaseInfo(repo=repo, tag=tag, version=(1, 0, 0), manifest_url="https://example.invalid/manifest.json", html_url="h")


def test_install_component_installs_and_sets_current(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": ["plugin.json", "app.py"]})
    monkeypatch.setattr(
        ra,
        "fetch_release_files",
        lambda repo, tag, files: {"plugin.json": b'{"name": "x"}', "app.py": b"print('hi')"},
    )

    version = ra.install_component("owner/some-repo", tmp_path)

    assert version == "1.0.0"
    assert (tmp_path / "current" / "app.py").read_bytes() == b"print('hi')"
    assert (tmp_path / "current_version.txt").read_text(encoding="utf-8") == "1.0.0"


def test_build_real_actions_reflects_real_backplane_and_registry_state(tmp_path, monkeypatch):
    # These would otherwise touch the *real* Start Menu and the *real*
    # HKCU Run key on whatever machine runs this test -- the underlying
    # mechanisms are already verified for real in test_shell_integration.py;
    # this test is only about the wiring (are they called, with what).
    monkeypatch.setattr(ra, "set_run_on_startup", lambda *a, **kw: None)
    monkeypatch.setattr(ra, "create_shortcut", lambda *a, **kw: None)

    actions = ra.build_real_actions(backplane_root=tmp_path)

    # Nothing installed yet.
    assert actions.is_backplane_installed() is False
    assert actions.is_plugin_registered("dummy-plugin") is False

    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": ["plugin.json"]})
    monkeypatch.setattr(
        ra,
        "fetch_release_files",
        lambda repo, tag, files: {"plugin.json": json.dumps({"name": "dummy-plugin"}).encode()},
    )

    actions.bootstrap_backplane()
    assert actions.is_backplane_installed() is True

    actions.install_plugin("dummy-plugin", "owner/dummy-plugin")
    assert actions.is_plugin_registered("dummy-plugin") is True


def test_bootstrap_backplane_registers_host_startup(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ra, "set_run_on_startup", lambda name, command, enabled: calls.append((name, command, enabled)))
    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": ["plugin.json"]})
    monkeypatch.setattr(ra, "fetch_release_files", lambda repo, tag, files: {"plugin.json": b'{"name": "x"}'})

    actions = ra.build_real_actions(backplane_root=tmp_path)
    actions.bootstrap_backplane()

    assert len(calls) == 1
    name, command, enabled = calls[0]
    assert name == "Backplane"
    assert "backplane.host.process" in command
    assert enabled is True


def test_install_plugin_creates_start_menu_shortcut_when_enabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ra, "create_shortcut", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": ["plugin.json"]})
    monkeypatch.setattr(
        ra,
        "fetch_release_files",
        lambda repo, tag, files: {
            "plugin.json": json.dumps(
                {"name": "dummy-plugin", "display_name": "Dummy Plugin", "create_start_menu_entry_default": True}
            ).encode()
        },
    )

    actions = ra.build_real_actions(backplane_root=tmp_path)
    actions.install_plugin("dummy-plugin", "owner/dummy-plugin")

    assert len(calls) == 1
    (shortcut_path, target), kwargs = calls[0]
    assert shortcut_path.name == "Dummy Plugin.lnk"
    assert "backplane.installer.launch_cli" in kwargs["arguments"]
    assert "dummy-plugin" in kwargs["arguments"]
    assert "owner/dummy-plugin" in kwargs["arguments"]


def test_install_plugin_skips_shortcut_when_disabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ra, "create_shortcut", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": ["plugin.json"]})
    monkeypatch.setattr(
        ra,
        "fetch_release_files",
        lambda repo, tag, files: {
            "plugin.json": json.dumps(
                {"name": "dummy-plugin", "create_start_menu_entry_default": False}
            ).encode()
        },
    )

    actions = ra.build_real_actions(backplane_root=tmp_path)
    actions.install_plugin("dummy-plugin", "owner/dummy-plugin")

    assert calls == []


def test_install_plugin_deploys_nested_package_that_actually_runs(tmp_path, monkeypatch):
    """Proves the real gap closed here: a plugin installed through the
    actual install_component()/VersionedInstall path -- not a fixture
    hand-placed under a matching directory name -- can really be spawned
    and imported by run_plugin(). Previously every test either hand-placed
    dummy_plugin under a directory literally named "dummy_plugin" (its own
    package name) or never got far enough to actually run the installed
    code, so this exact path (version-numbered install dir -> resolved
    package dir -> subprocess spawn -> real IPC round trip) had never been
    exercised.
    """
    monkeypatch.setattr(ra, "set_run_on_startup", lambda *a, **kw: None)
    monkeypatch.setattr(ra, "create_shortcut", lambda *a, **kw: None)

    # Real file bytes from the fixture, nested under "dummy_plugin/" -- the
    # same files-list convention Backplane's own generate_manifest.py uses
    # (rooted at the package folder, e.g. "backplane/...").
    fixture_files = {
        f"dummy_plugin/{path.name}": path.read_bytes()
        for path in DUMMY_PLUGIN_DIR.glob("*.py")
    }
    fixture_files["dummy_plugin/plugin.json"] = (DUMMY_PLUGIN_DIR / "plugin.json").read_bytes()

    monkeypatch.setattr(ra, "fetch_latest_release", lambda repo: _fake_release(repo))
    monkeypatch.setattr(ra, "fetch_manifest", lambda release: {"version": "1.0.0", "files": list(fixture_files)})
    monkeypatch.setattr(ra, "fetch_release_files", lambda repo, tag, files: fixture_files)

    actions = ra.build_real_actions(backplane_root=tmp_path)
    actions.install_plugin("dummy-plugin", "owner/dummy-plugin")

    entry = ra.PluginRegistry(tmp_path / "registry.json").get("dummy-plugin")
    assert entry is not None
    install_dir = Path(entry.install_dir)
    # Resolved to the nested package dir, not the version-numbered folder.
    assert install_dir.name == "dummy_plugin"
    assert (install_dir / "plugin.json").exists()

    received = []
    process = PluginProcess("dummy-plugin", install_dir)
    process.ipc.on("notify", received.append)
    try:
        process.start(connect_timeout=10)
        process.ipc.send("invoke", {"method": "on_tray_item", "args": ["ping"]})

        import time
        deadline = time.time() + 5
        while time.time() < deadline and not received:
            time.sleep(0.05)
        assert received and received[0]["message"] == "id=ping"
    finally:
        process.stop()
