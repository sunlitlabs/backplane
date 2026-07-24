"""Plugin-side IPC client -- the concrete object passed to
``PluginBase.on_load(host)``. Later phases add register_hotkey/
get_settings/get_secret/etc. to this same class as the host API surface
grows; Phase 2 scope is just notify() plus receiving invoked callbacks.
"""

from __future__ import annotations

import logging
import threading
from multiprocessing.connection import Client, Connection
from typing import Any, Optional

from backplane.host.ipc.protocol import decode_message, encode_message, make_message

logger = logging.getLogger("backplane.plugin")


class HostRPC:
    """Connects to the host's IPC channel and exposes the plugin-facing
    API. 'invoke' messages from the host call named methods directly on
    whatever target was set via ``set_invoke_target`` -- normally the
    loaded PluginBase instance itself, so the host can trigger
    on_hotkey/etc. without the plugin needing its own dispatch code.
    """

    def __init__(self, address: str):
        self._conn: Connection = Client(address, family="AF_PIPE")
        self._invoke_target: Optional[Any] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._recv_loop, name="backplane-plugin-ipc", daemon=True
        )

    def set_invoke_target(self, target: Any) -> None:
        self._invoke_target = target

    def start(self) -> None:
        self._thread.start()

    def notify(self, title: str, message: str) -> None:
        self._send("notify", {"title": title, "message": message})

    def signal_ready(self) -> None:
        """Tell the host on_load() has completed and it's safe to start
        dispatching invoke calls (hotkeys, menu clicks, etc.) -- a bare
        pipe connection existing is not sufficient evidence of that."""
        self._send("ready", {})

    def close(self) -> None:
        self._stop.set()
        try:
            self._conn.close()
        except Exception:
            pass

    def _send(self, message_type: str, payload: dict) -> None:
        self._conn.send_bytes(encode_message(make_message(message_type, payload)))

    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._conn.recv_bytes()
            except (EOFError, OSError):
                break
            try:
                message = decode_message(data)
            except Exception:
                logger.exception("Malformed IPC message from host, ignoring")
                continue
            if message.get("type") == "invoke":
                self._handle_invoke(message.get("payload") or {})

    def _handle_invoke(self, payload: dict) -> None:
        method_name = payload.get("method")
        args = payload.get("args") or []
        if self._invoke_target is None:
            logger.warning("Received invoke for %s before a target was set", method_name)
            return
        method = getattr(self._invoke_target, method_name, None)
        if method is None:
            logger.warning("Plugin has no method %s", method_name)
            return
        try:
            method(*args)
        except Exception:
            logger.exception("Error running invoked method %s", method_name)
