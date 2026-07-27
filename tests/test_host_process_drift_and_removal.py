"""Tests for HostProcess's drift-check scheduling and confirm-removal
wiring -- constructed directly (not via subprocess/mainloop, since these
methods don't need a running event loop to exercise), with the actual
confirmation dialog monkeypatched (it's already tested for real in
test_confirm_removal_dialog.py; what's novel here is that a "yes" leads to
a real uninstall and a "no" leads to cancel_missing, using the real
registry/tray_model/hotkey_manager).
"""

from __future__ import annotations

import shutil
import tkinter as tk
import uuid
from pathlib import Path

import pytest

from backplane.host import process as process_module
from backplane.host.process import HostProcess

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


@pytest.fixture
def root(tk_root):
    return tk_root


def _make_host(tmp_path, monkeypatch, root):
    monkeypatch.setattr(process_module, "UPDATE_CHECK_STARTUP_DELAY_SECONDS", 10_000.0)
    control_address = rf"\\.\pipe\Backplane-Test-DriftHost-{uuid.uuid4().hex[:12]}"
    host = HostProcess(
        data_dir=tmp_path,
        log_path=tmp_path / "host.log",
        control_pipe_address=control_address,
        root=root,
    )
    return host


def _teardown(host):
    for supervisor in host._supervisors.values():
        supervisor.stop()
    host.control_server.stop()
    host.hotkey_manager.stop()
    host.tray_model.stop()  # tears down this host's own tray icons, not the shared root


def test_drift_check_confirms_and_uninstalls_when_user_confirms(tmp_path, monkeypatch, root):
    plugin_dir = tmp_path / "dummy_plugin"
    shutil.copytree(DUMMY_PLUGIN_DIR, plugin_dir)
    host = _make_host(tmp_path, monkeypatch, root)
    host.registry.register("copied-plugin", plugin_dir, {"name": "copied-plugin", "run_on_startup_default": False})
    host.registry.drift_retry_window = 0.01  # fire on the very next check

    monkeypatch.setattr(process_module, "ask_confirm_removal", lambda parent, name: True)

    shutil.rmtree(plugin_dir)
    host.registry.check_drift(now=1000.0)  # first sighting -- registers "missing since"
    host._run_drift_check_body(now=1000.02)  # past the (tiny) retry window now

    assert not host.registry.is_registered("copied-plugin")
    _teardown(host)


def test_drift_check_keeps_waiting_when_user_declines(tmp_path, monkeypatch, root):
    plugin_dir = tmp_path / "dummy_plugin"
    shutil.copytree(DUMMY_PLUGIN_DIR, plugin_dir)
    host = _make_host(tmp_path, monkeypatch, root)
    host.registry.register("copied-plugin", plugin_dir, {"name": "copied-plugin", "run_on_startup_default": False})
    host.registry.drift_retry_window = 0.01

    monkeypatch.setattr(process_module, "ask_confirm_removal", lambda parent, name: False)

    shutil.rmtree(plugin_dir)
    host.registry.check_drift(now=1000.0)
    host._run_drift_check_body(now=1000.02)

    assert host.registry.is_registered("copied-plugin")
    assert not host.registry.get("copied-plugin").awaiting_confirmation  # cancel_missing cleared it
    _teardown(host)


def test_start_plugin_registers_settings_item_when_schema_declared(tmp_path, monkeypatch, root):
    plugin_dir = tmp_path / "dummy_plugin"
    shutil.copytree(DUMMY_PLUGIN_DIR, plugin_dir)
    (plugin_dir / "settings_schema.json").write_text('{"fields": []}', encoding="utf-8")
    host = _make_host(tmp_path, monkeypatch, root)

    entry_manifest = {
        "name": "copied-plugin",
        "settings_schema": "settings_schema.json",
        "run_on_startup_default": True,
    }
    host.registry.register("copied-plugin", plugin_dir, entry_manifest)
    host._start_plugin(host.registry.get("copied-plugin"))

    tray = host.tray_model.get_tray("copied-plugin")
    labels = [item.text for item in tray._icon.menu]
    assert "Settings..." in labels

    _teardown(host)
