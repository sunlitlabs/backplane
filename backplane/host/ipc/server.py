"""Host-side IPC server: one instance per plugin subprocess, listening on
a dedicated named pipe (Windows) via multiprocessing.connection -- avoids
port allocation and any Windows Firewall "allow this app" prompt entirely,
which a background, launched-at-login host process must never trigger.
"""

from __future__ import annotations

import logging
import threading
import uuid
from multiprocessing.connection import Connection, Listener
from typing import Any, Callable, Dict, Optional

from backplane.host.ipc.protocol import decode_message, encode_message, make_message

logger = logging.getLogger("backplane")


def make_pipe_address(plugin_name: str) -> str:
    return rf"\\.\pipe\Backplane-{plugin_name}-{uuid.uuid4().hex[:12]}"


class IpcServer:
    """Listens for a single plugin subprocess's connection and exchanges
    JSON-framed messages with it.

    Incoming messages are dispatched to handlers registered by message
    type; handlers run on this server's own receive thread, so anything
    that touches Tk or another single-threaded resource must marshal onto
    its own thread itself -- the same rule as every other cross-thread
    boundary in the host process.
    """

    def __init__(self, address: str):
        self._address = address
        self._listener = Listener(address, family="AF_PIPE")
        self._conn: Optional[Connection] = None
        self._handlers: Dict[str, Callable[[dict], None]] = {}
        self._request_handlers: Dict[str, Callable[[dict], Any]] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def address(self) -> str:
        return self._address

    def on(self, message_type: str, handler: Callable[[dict], None]) -> None:
        """Register a fire-and-forget handler (e.g. 'notify', 'ready') --
        called for its side effect, no response is sent back."""
        self._handlers[message_type] = handler

    def on_request(self, message_type: str, handler: Callable[[dict], Any]) -> None:
        """Register a request/response handler (e.g. 'get_settings') --
        the handler's return value is sent back as a 'response' message
        correlated by id; a raised exception is sent back as an error
        response instead of propagating here."""
        self._request_handlers[message_type] = handler

    def accept(self, timeout: Optional[float] = None) -> None:
        """Block until the plugin subprocess connects, then start the
        receive loop. Listener.accept() has no native timeout, so it runs
        on a helper thread here and this joins with one."""
        result: Dict[str, Connection] = {}
        error: Dict[str, BaseException] = {}

        def _accept() -> None:
            try:
                result["conn"] = self._listener.accept()
            except BaseException as exc:  # noqa: BLE001 -- surfaced to the caller below
                error["exc"] = exc

        t = threading.Thread(target=_accept, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if "exc" in error:
            raise error["exc"]
        if "conn" not in result:
            raise TimeoutError(f"No plugin connected to {self._address} within {timeout}s")

        self._conn = result["conn"]
        self._thread = threading.Thread(
            target=self._recv_loop, name="backplane-ipc-server", daemon=True
        )
        self._thread.start()

    def send(self, message_type: str, payload: Optional[dict] = None) -> None:
        if self._conn is None:
            raise RuntimeError("No plugin connected yet")
        self._conn.send_bytes(encode_message(make_message(message_type, payload)))

    def close(self) -> None:
        self._stop.set()
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        try:
            self._listener.close()
        except Exception:
            pass

    def _recv_loop(self) -> None:
        assert self._conn is not None
        while not self._stop.is_set():
            try:
                data = self._conn.recv_bytes()
            except (EOFError, OSError):
                break
            try:
                message = decode_message(data)
            except Exception:
                logger.exception("Malformed IPC message from plugin, ignoring")
                continue

            msg_type = message.get("type")

            request_handler = self._request_handlers.get(msg_type)
            if request_handler is not None:
                try:
                    result = request_handler(message.get("payload") or {})
                    response_payload = {"ok": True, "result": result}
                except Exception as exc:  # noqa: BLE001 -- turned into an error response, not raised
                    logger.exception("Error handling IPC request type=%s", msg_type)
                    response_payload = {"ok": False, "error": str(exc)}
                self._conn.send_bytes(
                    encode_message(make_message("response", response_payload, msg_id=message.get("id")))
                )
                continue

            handler = self._handlers.get(msg_type)
            if handler:
                try:
                    handler(message.get("payload") or {})
                except Exception:
                    logger.exception("Error handling IPC message type=%s", msg_type)
            else:
                logger.warning("No handler for IPC message type=%s", msg_type)
