"""Phase 2: prove the host<->plugin subprocess architecture works
end-to-end -- a real subprocess, real named-pipe IPC, both directions in
one round trip: the host tells the plugin (over IPC) to fire a hotkey
callback, and that callback calls back into the host via notify() (also
over IPC). This is the smallest slice that proves the whole architecture,
not just its individual pieces in isolation.
"""

from __future__ import annotations

import time
from pathlib import Path

from backplane.host.subprocess_manager import PluginProcess

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


def test_host_to_plugin_and_back_round_trip():
    received_notifies = []

    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR)
    process.ipc.on("notify", received_notifies.append)

    process.start(connect_timeout=10)
    try:
        assert process.is_running()

        # host -> IPC -> plugin: tell the dummy plugin's on_hotkey to fire.
        process.ipc.send("invoke", {"method": "on_hotkey", "args": ["test_hotkey"]})

        # plugin -> IPC -> host: on_hotkey calls host.notify(), which
        # should arrive back here via the registered handler.
        deadline = time.time() + 5
        while time.time() < deadline and not received_notifies:
            time.sleep(0.05)

        assert received_notifies, "Plugin never called back via notify()"
        assert received_notifies[0]["title"] == "Hotkey fired"
        assert received_notifies[0]["message"] == "id=test_hotkey"
    finally:
        process.stop()
