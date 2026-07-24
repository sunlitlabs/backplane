"""Plugin-side IPC client -- the concrete object passed to
``PluginBase.on_load(host)``. Later phases add register_hotkey/
get_settings/get_secret/etc. to this same class as the host API surface
grows; Phase 2 scope is just notify() plus receiving invoked callbacks.
"""

from __future__ import annotations

import logging
import queue
import threading
from multiprocessing.connection import Client, Connection
from typing import Any, Dict, Optional

from backplane.host.ipc.protocol import decode_message, encode_message, make_message

logger = logging.getLogger("backplane.plugin")

DEFAULT_REQUEST_TIMEOUT = 10.0


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
        self._pending: Dict[int, "queue.Queue"] = {}
        self._pending_lock = threading.Lock()
        self._next_request_id = 1

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

    def get_settings(self) -> dict:
        return self._call("get_settings", {})

    def set_settings(self, updates: dict) -> dict:
        return self._call("set_settings", {"updates": updates})

    def get_secret(self, key: str) -> Optional[str]:
        return self._call("get_secret", {"key": key})

    def set_secret(self, key: str, value: str) -> None:
        self._call("set_secret", {"key": key, "value": value})

    def close(self) -> None:
        self._stop.set()
        try:
            self._conn.close()
        except Exception:
            pass

    def _send(self, message_type: str, payload: dict) -> None:
        self._conn.send_bytes(encode_message(make_message(message_type, payload)))

    def _call(self, message_type: str, payload: dict, timeout: float = DEFAULT_REQUEST_TIMEOUT) -> Any:
        """Send a request and block for the host's correlated response.
        Raises RuntimeError if the host reports an error, or queue.Empty's
        parent (via .get(timeout=...)) if the host never responds."""
        with self._pending_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            result_q: "queue.Queue" = queue.Queue(maxsize=1)
            self._pending[request_id] = result_q

        self._conn.send_bytes(encode_message(make_message(message_type, payload, msg_id=request_id)))

        try:
            response = result_q.get(timeout=timeout)
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if not response.get("ok", False):
            raise RuntimeError(response.get("error", f"Host returned an error for {message_type!r}"))
        return response.get("result")

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

            msg_type = message.get("type")
            if msg_type == "response":
                with self._pending_lock:
                    result_q = self._pending.get(message.get("id"))
                if result_q:
                    result_q.put(message.get("payload") or {})
                continue
            if msg_type == "invoke":
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

        # Must not call method() on this thread: this IS the receive loop,
        # and an invoked method (on_hotkey, a menu callback, ...) commonly
        # turns around and makes its own blocking host call (get_settings,
        # notify, ...) -- which can only ever be answered by this same loop
        # reading the next incoming message. Calling synchronously here
        # deadlocks the plugin against itself the first time that happens.
        # Same reasoning as the host's own WM_HOTKEY dispatch in hotkeys.py.
        def _run() -> None:
            try:
                method(*args)
            except Exception:
                logger.exception("Error running invoked method %s", method_name)

        threading.Thread(target=_run, daemon=True).start()
