"""Spawns and manages plugin subprocesses -- the host process is the only
thing that ever launches a plugin, which is what guarantees single-instance
semantics per plugin without any Qt/toolkit-specific mechanism.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from backplane.host.ipc.server import IpcServer, make_pipe_address


class PluginProcess:
    """One running plugin subprocess and its IPC channel."""

    def __init__(self, plugin_name: str, plugin_dir: Path):
        self.plugin_name = plugin_name
        self.plugin_dir = plugin_dir
        self.ipc = IpcServer(make_pipe_address(plugin_name))
        self._popen: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self.ipc.on("ready", lambda _payload: self._ready.set())

    def start(self, connect_timeout: float = 10.0, ready_timeout: float = 10.0) -> None:
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
