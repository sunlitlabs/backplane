"""Proves the real gap closed in Phase 9: a plugin can actually call
host.register_hotkey() over IPC (previously only tested by the host
directly invoking on_hotkey, never through the real registration path a
plugin would use).
"""

from __future__ import annotations

import time
from pathlib import Path

from backplane.host.hotkeys import HotkeyManager, normalize_combo
from backplane.host.subprocess_manager import PluginProcess

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


def test_plugin_can_register_a_hotkey_and_have_it_fire_through_ipc():
    hotkeys = HotkeyManager()
    hotkeys.start()

    received = []
    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR, hotkey_manager=hotkeys)
    process.ipc.on("notify", received.append)

    try:
        process.start(connect_timeout=10)
        process.ipc.send(
            "invoke",
            {"method": "register_test_hotkey", "args": ["my_hotkey", "ctrl+alt+f23"]},
        )

        deadline = time.time() + 5
        while time.time() < deadline and not any(n.get("title") == "hotkey_registered" for n in received):
            time.sleep(0.05)
        assert any(n.get("title") == "hotkey_registered" for n in received)

        # Registered correctly in the real HotkeyManager, owned by this plugin.
        assert hotkeys.get_owner_of("ctrl+alt+f23") == "dummy-plugin"

        # Fire it (bypassing real SendInput -- see Phase 1 notes on why that's
        # unreliable in this environment; this proves the callback wiring,
        # which real WM_HOTKEY delivery already independently exercises).
        with hotkeys._lock:
            hotkey_id = hotkeys._combo_to_id[normalize_combo("ctrl+alt+f23")]
            callback = hotkeys._registrations[hotkey_id].callback
        callback()

        deadline = time.time() + 5
        while time.time() < deadline and not any(n.get("title") == "Hotkey fired" for n in received):
            time.sleep(0.05)
        fired = [n for n in received if n.get("title") == "Hotkey fired"]
        assert fired and fired[0]["message"] == "id=my_hotkey"
    finally:
        process.stop()
        hotkeys.stop()
