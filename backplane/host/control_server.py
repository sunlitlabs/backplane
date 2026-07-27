"""The host's control channel: a fixed, well-known named pipe that any
separate process (a plugin's smart-launcher stub) can connect to, to check
whether the host is running and ask it to show/focus a plugin.

Unlike the per-plugin IpcServer (a fresh, randomly-named pipe per
subprocess, known only because the host itself creates and hands out that
address), this pipe's address is fixed -- it has to be, since it's the one
rendezvous point a process with no existing connection to the host can use
to find it at all. Handles a sequence of short-lived connections (each
launcher-stub invocation connects once, asks one thing, disconnects)
rather than the one long-lived connection IpcServer manages per plugin.
"""

from __future__ import annotations

import logging
import threading
from multiprocessing.connection import Client, Listener
from typing import Callable, Optional

from backplane.host.ipc.protocol import decode_message, encode_message, make_message

logger = logging.getLogger("backplane")

CONTROL_PIPE_ADDRESS = r"\\.\pipe\SunlitLabs-Backplane-Control"

DEFAULT_PING_TIMEOUT = 2.0
DEFAULT_REQUEST_TIMEOUT = 5.0


class ControlServer:
    """Runs the host side of the control channel on its own thread."""

    def __init__(self, on_show_plugin: Callable[[str], None], address: str = CONTROL_PIPE_ADDRESS):
        self._address = address
        self._on_show_plugin = on_show_plugin
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="backplane-control", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Unblock a pending accept() by connecting to it once.
        try:
            Client(self._address, family="AF_PIPE").close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                listener = Listener(self._address, family="AF_PIPE")
            except Exception:
                logger.exception("Control server failed to bind %s", self._address)
                return
            try:
                conn = listener.accept()
            except Exception:
                continue
            finally:
                listener.close()

            if self._stop.is_set():
                conn.close()
                break

            try:
                self._handle_connection(conn)
            except Exception:
                logger.exception("Error handling control connection")
            finally:
                conn.close()

    def _handle_connection(self, conn) -> None:
        try:
            data = conn.recv_bytes()
        except EOFError:
            return
        message = decode_message(data)
        msg_type = message.get("type")

        if msg_type == "ping":
            conn.send_bytes(encode_message(make_message("response", {"ok": True, "result": "alive"})))
            return

        if msg_type == "show_plugin":
            plugin_name = message.get("payload", {}).get("name")
            try:
                self._on_show_plugin(plugin_name)
                conn.send_bytes(encode_message(make_message("response", {"ok": True, "result": None})))
            except Exception as exc:  # noqa: BLE001 -- turned into an error response, not raised
                conn.send_bytes(encode_message(make_message("response", {"ok": False, "error": str(exc)})))
            return

        conn.send_bytes(
            encode_message(make_message("response", {"ok": False, "error": f"Unknown message type {msg_type!r}"}))
        )


def ping_host(address: str = CONTROL_PIPE_ADDRESS, timeout: float = DEFAULT_PING_TIMEOUT) -> bool:
    """True if a host process is alive and responding on the control pipe."""
    try:
        conn = Client(address, family="AF_PIPE")
    except Exception:
        return False
    try:
        conn.send_bytes(encode_message(make_message("ping", {})))
        if not conn.poll(timeout):
            return False
        response = decode_message(conn.recv_bytes())
        return bool(response.get("payload", {}).get("ok", False))
    except Exception:
        return False
    finally:
        conn.close()


def request_show_plugin(
    plugin_name: str, address: str = CONTROL_PIPE_ADDRESS, timeout: float = DEFAULT_REQUEST_TIMEOUT
) -> bool:
    """True if the host acknowledged the request (the plugin is registered
    and was shown/focused/started). False if the host isn't reachable, or
    responded with an error (e.g. the plugin isn't registered) -- either
    way, the caller should fall through to the install/registration flow."""
    try:
        conn = Client(address, family="AF_PIPE")
    except Exception:
        return False
    try:
        conn.send_bytes(encode_message(make_message("show_plugin", {"name": plugin_name})))
        if not conn.poll(timeout):
            return False
        response = decode_message(conn.recv_bytes())
        return bool(response.get("payload", {}).get("ok", False))
    except Exception:
        return False
    finally:
        conn.close()
