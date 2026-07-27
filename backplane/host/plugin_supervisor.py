"""Detects an unexpected plugin subprocess exit and restarts it, up to a
capped number of attempts within a rolling window -- crossing the cap
means it's crash-looping, and the host gives up and surfaces that via a
callback (a toast, in production) rather than respawning forever.

Existing hotkey/tray registrations for the plugin are never touched
across a restart. PluginProcess's register_hotkey handler wires each
hotkey's callback to call ``self.ipc.send(...)`` -- a live attribute
lookup at dispatch time, not a value frozen when the hotkey was
registered -- so the moment PluginProcess.start() re-accepts a connection
on the same pipe address, already-registered hotkeys start reaching the
new subprocess automatically. There is deliberately no unregister-then-
re-register step here, matching ARCHITECTURE.md's build-plan risk notes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from backplane.host.subprocess_manager import PluginProcess


@dataclass
class RestartPolicy:
    max_attempts: int = 5
    window_seconds: float = 60.0
    restart_delay_seconds: float = 1.0


class PluginSupervisor:
    def __init__(
        self,
        plugin_process: PluginProcess,
        policy: Optional[RestartPolicy] = None,
        on_crash_loop: Optional[Callable[[str], None]] = None,
        on_restart: Optional[Callable[[str], None]] = None,
    ):
        self.plugin_process = plugin_process
        self.policy = policy or RestartPolicy()
        self._on_crash_loop = on_crash_loop or (lambda name: None)
        self._on_restart = on_restart or (lambda name: None)
        self._restart_times: List[float] = []
        self._stopping = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self.gave_up = False

    def start(self, **start_kwargs) -> None:
        self.plugin_process.start(**start_kwargs)
        self._watcher_thread = threading.Thread(
            target=self._watch, daemon=True, name=f"backplane-supervisor-{self.plugin_process.plugin_name}"
        )
        self._watcher_thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self.plugin_process.stop()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=5)

    def _watch(self) -> None:
        while not self._stopping.is_set():
            popen = self.plugin_process._popen
            if popen is None:
                return
            popen.wait()  # blocks until this launch of the subprocess exits
            if self._stopping.is_set():
                return  # a deliberate stop() -- not a crash, don't restart

            now = time.monotonic()
            self._restart_times = [t for t in self._restart_times if now - t < self.policy.window_seconds]
            if len(self._restart_times) >= self.policy.max_attempts:
                self.gave_up = True
                self._on_crash_loop(self.plugin_process.plugin_name)
                return

            self._restart_times.append(now)
            time.sleep(self.policy.restart_delay_seconds)
            if self._stopping.is_set():
                return

            try:
                self.plugin_process.start()
                self._on_restart(self.plugin_process.plugin_name)
            except Exception:
                continue  # failed to relaunch -- counts as another crash next loop
