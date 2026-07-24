"""Tests for the two concrete "multi-window support" pieces Backplane
actually owns given plugins keep their own toolkit and windows entirely:
consistent taskbar identity regardless of window count, and the
close-behavior setting a plugin's own window-close code can consult.
"""

from __future__ import annotations

import time
from pathlib import Path

from backplane.host.subprocess_manager import PluginProcess
from backplane.plugin_runtime.window_identity import set_app_user_model_id

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


def test_set_app_user_model_id_does_not_raise():
    set_app_user_model_id("test-plugin")
    # Idempotent: setting it again (e.g. if called twice by mistake) must
    # not raise either.
    set_app_user_model_id("test-plugin")


def test_get_close_behavior_round_trips_through_real_ipc():
    received_notifies = []
    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR, close_behavior="minimize_to_tray")
    process.ipc.on("notify", received_notifies.append)

    process.start(connect_timeout=10)
    try:
        process.ipc.send("invoke", {"method": "report_close_behavior", "args": []})

        deadline = time.time() + 5
        while time.time() < deadline and not received_notifies:
            time.sleep(0.05)

        assert received_notifies, "Plugin never reported its close behavior"
        assert received_notifies[0]["message"] == "minimize_to_tray"
    finally:
        process.stop()
