"""A minimal PluginBase implementation used only to exercise Phase 2's
host<->plugin subprocess IPC round trip. Not a real product plugin.
"""

from __future__ import annotations

import threading

from backplane.contracts import PluginBase


class DummyPlugin(PluginBase):
    def __init__(self) -> None:
        self.host = None
        self._stop_event = threading.Event()

    def on_load(self, host) -> None:
        self.host = host

    def on_hotkey(self, hotkey_id: str) -> None:
        # Proves both IPC directions in one round trip: the host invoked
        # this method over IPC, and calling notify() here sends a message
        # back over the same channel.
        self.host.notify("Hotkey fired", f"id={hotkey_id}")

    def report_close_behavior(self) -> None:
        behavior = self.host.get_close_behavior()
        self.host.notify("close_behavior", behavior)

    def register_test_hotkey(self, hotkey_id: str, combo: str) -> None:
        self.host.register_hotkey(hotkey_id, combo)
        self.host.notify("hotkey_registered", hotkey_id)

    def on_tray_item(self, item_id: str) -> None:
        self.host.notify("Tray item clicked", f"id={item_id}")

    def add_test_tray_item(self, item_id: str, label: str) -> None:
        self.host.add_tray_item(item_id, label)
        self.host.notify("tray_item_added", item_id)

    def start(self) -> None:
        # Blocks so the subprocess stays alive to receive invoke messages;
        # the real contract is that start() owns the plugin's lifetime.
        self._stop_event.wait()

    def stop(self) -> None:
        self._stop_event.set()
