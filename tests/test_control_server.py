"""Tests for the host's control channel -- the fixed rendezvous pipe a
smart-launcher stub uses to find an already-running host. Uses a unique
address per test (never the real CONTROL_PIPE_ADDRESS) so tests never
collide with each other or with a real Backplane host that might be
running on this machine.
"""

from __future__ import annotations

import uuid

from backplane.host.control_server import ControlServer, ping_host, request_show_plugin


def _test_address() -> str:
    return rf"\\.\pipe\Backplane-Test-Control-{uuid.uuid4().hex[:12]}"


def test_ping_fails_when_no_server_is_running():
    assert ping_host(address=_test_address(), timeout=0.5) is False


def test_ping_succeeds_while_server_is_running():
    address = _test_address()
    server = ControlServer(on_show_plugin=lambda name: None, address=address)
    server.start()
    try:
        assert ping_host(address=address, timeout=2.0) is True
    finally:
        server.stop()


def test_ping_fails_after_server_stops():
    address = _test_address()
    server = ControlServer(on_show_plugin=lambda name: None, address=address)
    server.start()
    assert ping_host(address=address, timeout=2.0) is True
    server.stop()

    assert ping_host(address=address, timeout=0.5) is False


def test_request_show_plugin_invokes_the_callback_with_the_right_name():
    address = _test_address()
    shown = []
    server = ControlServer(on_show_plugin=shown.append, address=address)
    server.start()
    try:
        assert request_show_plugin("dummy-plugin", address=address, timeout=5.0) is True
        assert shown == ["dummy-plugin"]
    finally:
        server.stop()


def test_request_show_plugin_returns_false_if_callback_raises():
    address = _test_address()

    def _raise(name):
        raise RuntimeError(f"{name} is not registered")

    server = ControlServer(on_show_plugin=_raise, address=address)
    server.start()
    try:
        assert request_show_plugin("unknown-plugin", address=address, timeout=5.0) is False
    finally:
        server.stop()


def test_server_handles_multiple_sequential_connections():
    """Unlike the per-plugin IpcServer (one long-lived connection), the
    control server must keep serving new connections indefinitely."""
    address = _test_address()
    shown = []
    server = ControlServer(on_show_plugin=shown.append, address=address)
    server.start()
    try:
        for i in range(3):
            assert ping_host(address=address, timeout=2.0) is True
            assert request_show_plugin(f"plugin-{i}", address=address, timeout=2.0) is True
        assert shown == ["plugin-0", "plugin-1", "plugin-2"]
    finally:
        server.stop()
