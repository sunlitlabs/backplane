"""Spawns and manages plugin subprocesses -- the host process is the only
thing that ever launches a plugin, which is what guarantees single-instance
semantics per plugin without any Qt/toolkit-specific mechanism.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from backplane.host import secrets as secrets_module
from backplane.host.hotkeys import HotkeyManager
from backplane.host.ipc.server import IpcServer, make_pipe_address
from backplane.host.settings_store import SettingsStore


class PluginProcess:
    """One running plugin subprocess and its IPC channel.

    ``settings_store``/``settings_schema`` are optional so Phase 2's bare
    dummy-plugin usage (no settings at all) keeps working unchanged; when
    both are given, get_settings/set_settings/get_secret/set_secret
    requests from the plugin are wired straight through to the host's
    stores.
    """

    def __init__(
        self,
        plugin_name: str,
        plugin_dir: Path,
        settings_store: Optional[SettingsStore] = None,
        settings_schema: Optional[Dict[str, Any]] = None,
        close_behavior: str = "quit",
        hotkey_manager: Optional[HotkeyManager] = None,
    ):
        self.plugin_name = plugin_name
        self.plugin_dir = plugin_dir
        self.ipc = IpcServer(make_pipe_address(plugin_name))
        self._popen: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self.ipc.on("ready", lambda _payload: self._ready.set())

        # Static for now -- resolving this from settings_default + a
        # per-install override in the settings store is the registry's job
        # (Phase 6), which is what will actually construct PluginProcess
        # instances for real plugins. This provides the mechanism.
        self.ipc.on_request("get_close_behavior", lambda _payload: close_behavior)

        if hotkey_manager is not None:
            self.ipc.on_request("register_hotkey", self._make_register_hotkey_handler(hotkey_manager))

        if settings_store is not None:
            schema = settings_schema or {"fields": []}
            self.ipc.on_request(
                "get_settings", lambda _payload: settings_store.load(plugin_name, schema)
            )
            self.ipc.on_request(
                "set_settings",
                lambda payload: settings_store.merge_and_save(
                    plugin_name, schema, payload.get("updates") or {}
                ),
            )
            self.ipc.on_request(
                "get_secret", lambda payload: secrets_module.get_secret(plugin_name, payload["key"])
            )
            self.ipc.on_request(
                "set_secret",
                lambda payload: secrets_module.set_secret(plugin_name, payload["key"], payload["value"]),
            )

    def _make_register_hotkey_handler(self, hotkey_manager: HotkeyManager):
        # Reads self.ipc at *dispatch* time (a live attribute lookup), not
        # a value frozen when the hotkey was registered -- so a restarted
        # subprocess (a fresh accept() on the same PluginProcess, per
        # PluginSupervisor) is reached automatically the moment it
        # reconnects, with no unregister/re-register step at all.
        def _handler(payload: dict) -> None:
            hotkey_id = payload["hotkey_id"]
            combo = payload["combo"]
            hotkey_manager.register(
                combo,
                owner=self.plugin_name,
                callback=lambda: self.ipc.send("invoke", {"method": "on_hotkey", "args": [hotkey_id]}),
            )

        return _handler

    def start(self, connect_timeout: float = 10.0, ready_timeout: float = 10.0) -> None:
        self._ready.clear()  # a restart must wait for a *fresh* ready signal, not a stale one
        self._popen = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "backplane.plugin_runtime.main",
                str(self.plugin_dir),
                self.ipc.address,
            ],
        )
        self.ipc.accept(timeout=connect_timeout)

        # A live pipe connection only proves the subprocess started and
        # connected -- not that its on_load() has finished running. Wait
        # for the plugin's own "ready" signal before returning, so callers
        # never send an invoke that races a still-initializing plugin.
        if not self._ready.wait(timeout=ready_timeout):
            raise TimeoutError(
                f"Plugin {self.plugin_name!r} connected but never signaled ready "
                f"within {ready_timeout}s"
            )

    def is_running(self) -> bool:
        return self._popen is not None and self._popen.poll() is None

    def stop(self, timeout: float = 5.0) -> None:
        self.ipc.close()
        if self._popen is not None:
            try:
                self._popen.terminate()
                self._popen.wait(timeout=timeout)
            except Exception:
                self._popen.kill()
