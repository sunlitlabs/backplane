"""Phase 3, full stack: a real plugin subprocess calls get_settings(),
set_settings(), set_secret(), and get_secret() over real IPC, and the host
side actually persists them via SettingsStore (a real JSON file) and
secrets.py (real Windows Credential Manager) -- not mocked at any layer.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from backplane.host.secrets import delete_secret, get_secret
from backplane.host.settings_store import SettingsStore
from backplane.host.subprocess_manager import PluginProcess

SETTINGS_DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "settings_dummy_plugin"

SCHEMA = {
    "version": 1,
    "fields": [
        {"key": "port", "type": "integer", "default": 8765},
        {"key": "api_key", "type": "secret"},
    ],
}


def test_settings_and_secrets_round_trip_through_real_ipc(tmp_path):
    plugin_name = f"settings-dummy-plugin-{uuid.uuid4().hex[:8]}"
    store = SettingsStore(tmp_path)

    received_notifies = []
    process = PluginProcess(
        plugin_name,
        SETTINGS_DUMMY_PLUGIN_DIR,
        settings_store=store,
        settings_schema=SCHEMA,
    )
    process.ipc.on("notify", received_notifies.append)

    try:
        process.start(connect_timeout=10)
        process.ipc.send("invoke", {"method": "run_settings_check", "args": []})

        deadline = time.time() + 5
        while time.time() < deadline and not received_notifies:
            time.sleep(0.05)

        assert received_notifies, "Plugin never reported back its settings check"
        result = json.loads(received_notifies[0]["message"])

        assert result["initial_port"] == 8765  # schema default, before any write
        assert result["updated_port"] == 9999  # after set_settings({"port": 9999})
        assert result["secret_value"] == "sk-round-trip-test"  # after set_secret + get_secret

        # And the host's own on-disk store actually has it, independent of
        # what the plugin was told -- proves persistence, not just IPC echo.
        on_disk = store.load(plugin_name, SCHEMA)
        assert on_disk["port"] == 9999

        # Same for the real Credential Manager entry.
        assert get_secret(plugin_name, "api_key") == "sk-round-trip-test"
    finally:
        process.stop()
        delete_secret(plugin_name, "api_key")
