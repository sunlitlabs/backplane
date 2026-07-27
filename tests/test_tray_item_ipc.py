"""Proves add_tray_item/on_tray_item works end-to-end over real IPC and
real TrayModel wiring -- the sibling of register_hotkey/on_hotkey, closing
the gap where the plugin contract mentioned host.add_tray_item() but
nothing ever implemented it.
"""

from __future__ import annotations

import time
from pathlib import Path

from backplane.host.subprocess_manager import PluginProcess
from backplane.host.tray_model import TrayModel

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


def _wait_for(predicate, timeout=5.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_plugin_process_registers_into_tray_model_on_start_and_removes_on_stop():
    tray_model = TrayModel(mode="separate")
    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR, tray_model=tray_model, display_name="Dummy Plugin")
    try:
        assert tray_model.tray_count() == 0
        process.start(connect_timeout=10)
        assert tray_model.tray_count() == 1
        assert tray_model.get_tray("dummy-plugin") is not None
    finally:
        process.stop()
    assert tray_model.tray_count() == 0


def test_plugin_can_add_a_tray_item_and_have_it_fire_through_ipc():
    tray_model = TrayModel(mode="separate")
    received = []
    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR, tray_model=tray_model)
    process.ipc.on("notify", received.append)

    try:
        process.start(connect_timeout=10)
        process.ipc.send("invoke", {"method": "add_test_tray_item", "args": ["item1", "Do Thing"]})

        assert _wait_for(lambda: any(n.get("title") == "tray_item_added" for n in received))

        tray = tray_model.get_tray("dummy-plugin")
        labels = [item.text for item in tray._icon.menu]
        assert "Do Thing" in labels

        # Simulate a click by invoking the stored callback directly (same
        # reasoning as the hotkey IPC test: real click delivery is a
        # pystray/OS concern, already exercised elsewhere; this proves the
        # IPC wiring from click -> plugin).
        with tray_model._lock:
            info = tray_model._plugins["dummy-plugin"]
            callback = next(item.callback for item in info.menu_items if item.label == "Do Thing")
        callback()

        assert _wait_for(lambda: any(n.get("title") == "Tray item clicked" for n in received))
        clicked = [n for n in received if n.get("title") == "Tray item clicked"]
        assert clicked[0]["message"] == "id=item1"
    finally:
        process.stop()


def test_settings_item_is_added_when_open_settings_callback_given():
    tray_model = TrayModel(mode="separate")
    opened = []
    process = PluginProcess(
        "dummy-plugin",
        DUMMY_PLUGIN_DIR,
        tray_model=tray_model,
        open_settings_callback=opened.append,
    )
    try:
        process.start(connect_timeout=10)
        tray = tray_model.get_tray("dummy-plugin")
        labels = [item.text for item in tray._icon.menu]
        assert "Settings..." in labels

        with tray_model._lock:
            info = tray_model._plugins["dummy-plugin"]
            callback = next(item.callback for item in info.menu_items if item.label == "Settings...")
        callback()
        assert opened == ["dummy-plugin"]
    finally:
        process.stop()
