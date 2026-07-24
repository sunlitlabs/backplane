"""Tests for the plugin registry: registration/persistence, drift
detection (a missing plugin must survive a bounded retry window before
being reported, and clear itself if files reappear), and the canonical
uninstall routine tearing down every subsystem it knows about.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from backplane.host.hotkeys import HotkeyManager
from backplane.host.registry import PluginRegistry, UninstallContext, uninstall_plugin
from backplane.host.secrets import get_secret, set_secret
from backplane.host.settings_store import SettingsStore
from backplane.host.tray_model import PluginTrayInfo, TrayModel

MANIFEST = {"name": "test-plugin", "entrypoint": "test_plugin.plugin:TestPlugin"}


def _make_plugin_dir(base: Path, name: str = "test-plugin") -> Path:
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text('{"name": "%s"}' % name, encoding="utf-8")
    return plugin_dir


def test_register_and_get(tmp_path):
    registry = PluginRegistry(tmp_path / "registry.json")
    plugin_dir = _make_plugin_dir(tmp_path)

    registry.register("test-plugin", plugin_dir, MANIFEST)
    assert registry.is_registered("test-plugin")
    entry = registry.get("test-plugin")
    assert entry.install_dir == str(plugin_dir)
    assert entry.manifest == MANIFEST


def test_deregister_removes_entry(tmp_path):
    registry = PluginRegistry(tmp_path / "registry.json")
    plugin_dir = _make_plugin_dir(tmp_path)
    registry.register("test-plugin", plugin_dir, MANIFEST)

    registry.deregister("test-plugin")
    assert not registry.is_registered("test-plugin")
    assert registry.get("test-plugin") is None


def test_registry_persists_across_reload(tmp_path):
    registry_path = tmp_path / "registry.json"
    plugin_dir = _make_plugin_dir(tmp_path)

    first = PluginRegistry(registry_path)
    first.register("test-plugin", plugin_dir, MANIFEST)

    second = PluginRegistry(registry_path)
    assert second.is_registered("test-plugin")
    assert second.get("test-plugin").install_dir == str(plugin_dir)


def test_drift_not_reported_before_retry_window_elapses(tmp_path):
    registry = PluginRegistry(tmp_path / "registry.json", drift_retry_window=100.0)
    plugin_dir = _make_plugin_dir(tmp_path)
    registry.register("test-plugin", plugin_dir, MANIFEST)

    shutil.rmtree(plugin_dir)

    # Files just went missing -- must not be reported yet even after
    # several checks, since we're still inside the retry window.
    assert registry.check_drift(now=1000.0) == []
    assert registry.check_drift(now=1050.0) == []
    assert registry.get("test-plugin") is not None  # still registered


def test_drift_reported_once_retry_window_elapses(tmp_path):
    registry = PluginRegistry(tmp_path / "registry.json", drift_retry_window=100.0)
    plugin_dir = _make_plugin_dir(tmp_path)
    registry.register("test-plugin", plugin_dir, MANIFEST)

    shutil.rmtree(plugin_dir)

    assert registry.check_drift(now=1000.0) == []  # first sighting of "missing"
    assert registry.check_drift(now=1150.0) == ["test-plugin"]  # window elapsed
    # Reported exactly once -- a subsequent check must not report it again.
    assert registry.check_drift(now=1200.0) == []


def test_drift_clears_if_files_reappear_before_window_elapses(tmp_path):
    registry = PluginRegistry(tmp_path / "registry.json", drift_retry_window=100.0)
    plugin_dir = _make_plugin_dir(tmp_path)
    registry.register("test-plugin", plugin_dir, MANIFEST)

    shutil.rmtree(plugin_dir)
    assert registry.check_drift(now=1000.0) == []

    _make_plugin_dir(tmp_path)  # files come back (e.g. cloud sync catches up)
    assert registry.check_drift(now=1150.0) == []  # never reported

    # And the retry clock actually reset, rather than just being masked --
    # removing it again starts a fresh window instead of firing immediately.
    shutil.rmtree(plugin_dir)
    assert registry.check_drift(now=1160.0) == []
    assert registry.check_drift(now=1300.0) == ["test-plugin"]


def test_cancel_missing_clears_awaiting_confirmation(tmp_path):
    registry = PluginRegistry(tmp_path / "registry.json", drift_retry_window=100.0)
    plugin_dir = _make_plugin_dir(tmp_path)
    registry.register("test-plugin", plugin_dir, MANIFEST)
    shutil.rmtree(plugin_dir)

    registry.check_drift(now=1000.0)
    assert registry.check_drift(now=1150.0) == ["test-plugin"]
    assert registry.get("test-plugin").awaiting_confirmation

    registry.cancel_missing("test-plugin")
    assert not registry.get("test-plugin").awaiting_confirmation
    assert registry.is_registered("test-plugin")  # cancel != deregister


def test_uninstall_plugin_tears_down_every_subsystem(tmp_path):
    plugin_name = f"uninstall-test-{uuid.uuid4().hex[:8]}"
    registry = PluginRegistry(tmp_path / "registry.json")
    plugin_dir = _make_plugin_dir(tmp_path, plugin_name)
    registry.register(plugin_name, plugin_dir, {"name": plugin_name})

    tray_model = TrayModel(mode="separate")
    tray_model.register_plugin(PluginTrayInfo(plugin_name, plugin_name))
    assert tray_model.tray_count() == 1

    hotkeys = HotkeyManager()
    hotkeys.start()
    hotkeys.register("ctrl+alt+f17", owner=plugin_name, callback=lambda: None)

    settings_store = SettingsStore(tmp_path / "settings")
    settings_store.save(plugin_name, {"some_field": 123})

    set_secret(plugin_name, "api_key", "sk-uninstall-test")

    try:
        ctx = UninstallContext(tray_model=tray_model, hotkey_manager=hotkeys, settings_store=settings_store)
        uninstall_plugin(registry, plugin_name, ctx)

        assert not registry.is_registered(plugin_name)
        assert tray_model.tray_count() == 0
        assert not any(reg.owner == plugin_name for reg in hotkeys._registrations.values())
        assert not (tmp_path / "settings" / f"{plugin_name}.json").exists()
        assert get_secret(plugin_name, "api_key") is None
    finally:
        tray_model.stop()
        hotkeys.stop()
