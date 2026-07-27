"""Tests for PluginSupervisor: restarting a crashed plugin, preserving
hotkey registrations across that restart without re-registering, leaving
a deliberate stop() alone, and giving up (not respawning forever) once a
plugin crash-loops past the cap.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from backplane.host.hotkeys import HotkeyManager, normalize_combo
from backplane.host.plugin_supervisor import PluginSupervisor, RestartPolicy
from backplane.host.subprocess_manager import PluginProcess

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"
CRASHY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "crashy_plugin"


def _wait_for(predicate, timeout=5.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_supervisor_restarts_a_crashed_plugin():
    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR)
    supervisor = PluginSupervisor(process, policy=RestartPolicy(restart_delay_seconds=0.1))
    restarted = []
    supervisor._on_restart = restarted.append

    try:
        supervisor.start(connect_timeout=10)
        first_pid = process._popen.pid

        process._popen.kill()  # simulate a real crash

        assert _wait_for(lambda: restarted, timeout=10)
        assert _wait_for(lambda: process.is_running(), timeout=10)
        assert process._popen.pid != first_pid
    finally:
        supervisor.stop()


def test_supervisor_preserves_hotkey_registration_across_restart():
    hotkeys = HotkeyManager()
    hotkeys.start()
    received = []

    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR, hotkey_manager=hotkeys)
    process.ipc.on("notify", received.append)
    supervisor = PluginSupervisor(process, policy=RestartPolicy(restart_delay_seconds=0.1))
    restarted = []
    supervisor._on_restart = restarted.append

    try:
        supervisor.start(connect_timeout=10)
        process.ipc.send("invoke", {"method": "register_test_hotkey", "args": ["my_hotkey", "ctrl+alt+f24"]})
        assert _wait_for(lambda: any(n.get("title") == "hotkey_registered" for n in received))

        # Crash and wait for the restart to complete (ready signaled again).
        received.clear()
        process._popen.kill()
        assert _wait_for(lambda: restarted, timeout=10)
        assert _wait_for(lambda: process._ready.is_set(), timeout=10)

        # The registration in HotkeyManager was never touched -- fire the
        # *original* stored callback and confirm it reaches the *new*
        # subprocess (proving the live self.ipc lookup, not a stale one).
        with hotkeys._lock:
            hotkey_id = hotkeys._combo_to_id[normalize_combo("ctrl+alt+f24")]
            callback = hotkeys._registrations[hotkey_id].callback
        callback()

        assert _wait_for(lambda: any(n.get("title") == "Hotkey fired" for n in received))
    finally:
        supervisor.stop()
        hotkeys.stop()


def test_deliberate_stop_does_not_trigger_a_restart():
    process = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR)
    supervisor = PluginSupervisor(process, policy=RestartPolicy(restart_delay_seconds=0.1))
    restarted = []
    supervisor._on_restart = restarted.append

    supervisor.start(connect_timeout=10)
    supervisor.stop()

    time.sleep(1.0)  # give a buggy implementation a chance to restart anyway
    assert restarted == []
    assert not process.is_running()


def test_supervisor_gives_up_after_max_attempts():
    process = PluginProcess("crashy-plugin", CRASHY_PLUGIN_DIR)
    policy = RestartPolicy(max_attempts=2, window_seconds=60.0, restart_delay_seconds=0.1)
    crash_looped = []
    supervisor = PluginSupervisor(process, policy=policy, on_crash_loop=crash_looped.append)

    # crashy-plugin exits on its own (sys.exit(1)) before ever connecting,
    # so PluginProcess.start()'s normal accept()/ready-wait would just time
    # out -- spawn it directly and start the watcher loop the same way
    # start() would, without waiting on a handshake this plugin never completes.
    supervisor.plugin_process._popen = subprocess.Popen(
        [sys.executable, "-B", "-m", "backplane.plugin_runtime.main", str(CRASHY_PLUGIN_DIR), process.ipc.address]
    )
    supervisor._watcher_thread = threading.Thread(target=supervisor._watch, daemon=True)
    supervisor._watcher_thread.start()

    assert _wait_for(lambda: crash_looped, timeout=10)
    assert supervisor.gave_up
    assert crash_looped == ["crashy-plugin"]
