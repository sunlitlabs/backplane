"""A minimal PluginBase implementation used only to exercise Phase 3's
settings/secrets IPC round trip end-to-end (real subprocess, real named
pipe, real Credential Manager). Not a real product plugin.
"""

from __future__ import annotations

import json
import threading

from backplane.contracts import PluginBase


class SettingsDummyPlugin(PluginBase):
    def __init__(self) -> None:
        self.host = None
        self._stop_event = threading.Event()

    def on_load(self, host) -> None:
        self.host = host

    def run_settings_check(self) -> None:
        """Invoked by the host over IPC. Exercises every settings/secrets
        call and reports the results back via notify() so the test process
        can observe them without any shared memory across the process
        boundary."""
        initial = self.host.get_settings()
        updated = self.host.set_settings({"port": 9999})
        self.host.set_secret("api_key", "sk-round-trip-test")
        secret_value = self.host.get_secret("api_key")

        result = {
            "initial_port": initial.get("port"),
            "updated_port": updated.get("port"),
            "secret_value": secret_value,
        }
        self.host.notify("settings_check_result", json.dumps(result))

    def start(self) -> None:
        self._stop_event.wait()

    def stop(self) -> None:
        self._stop_event.set()
