"""Tests for the named-mutex single-instance guard.

Includes a real cross-process test -- the same reasoning as the hotkey
manager's OS-level conflict test: an in-process-only check would prove
nothing about whether this actually stops a second, truly independent
process from doing the thing being guarded.
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from backplane.host.single_instance import SingleInstanceGuard
from backplane.host.subprocess_manager import PluginProcess

DUMMY_PLUGIN_DIR = Path(__file__).resolve().parent / "fixtures" / "dummy_plugin"


def test_second_acquire_in_process_fails():
    key = f"test-{uuid.uuid4().hex[:8]}"
    first = SingleInstanceGuard(key)
    assert first.acquired

    second = SingleInstanceGuard(key)
    assert not second.acquired

    first.release()
    second.release()


def test_release_frees_the_key_for_reacquisition():
    key = f"test-{uuid.uuid4().hex[:8]}"
    first = SingleInstanceGuard(key)
    assert first.acquired
    first.release()

    second = SingleInstanceGuard(key)
    assert second.acquired
    second.release()


def test_different_keys_do_not_conflict():
    key_a = f"test-a-{uuid.uuid4().hex[:8]}"
    key_b = f"test-b-{uuid.uuid4().hex[:8]}"
    guard_a = SingleInstanceGuard(key_a)
    guard_b = SingleInstanceGuard(key_b)
    try:
        assert guard_a.acquired
        assert guard_b.acquired
    finally:
        guard_a.release()
        guard_b.release()


def test_context_manager_releases_on_exit():
    key = f"test-{uuid.uuid4().hex[:8]}"
    with SingleInstanceGuard(key) as guard:
        assert guard.acquired

    reacquired = SingleInstanceGuard(key)
    assert reacquired.acquired
    reacquired.release()


def test_second_acquire_from_a_real_independent_process_fails():
    """The point of using a named Win32 mutex rather than a Python-level
    lock: a completely separate process, sharing no Python state with this
    test, must still be blocked from claiming the same key."""
    key = f"test-cross-process-{uuid.uuid4().hex[:8]}"

    holder_code = (
        "import time, sys; "
        "sys.path.insert(0, r'{repo_root}'); "
        "from backplane.host.single_instance import SingleInstanceGuard; "
        "g = SingleInstanceGuard('{key}'); "
        "print('ACQUIRED' if g.acquired else 'NOT_ACQUIRED', flush=True); "
        "time.sleep(5)"
    )
    import pathlib

    repo_root = str(pathlib.Path(__file__).resolve().parent.parent)
    holder = subprocess.Popen(
        [sys.executable, "-B", "-c", holder_code.format(repo_root=repo_root, key=key)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        first_line = holder.stdout.readline().strip()
        assert first_line == "ACQUIRED", f"holder process reported: {first_line!r}"

        # Give the OS a moment to finish registering the mutex, though
        # CreateMutexW's own return already implies it's visible immediately.
        time.sleep(0.2)

        here = SingleInstanceGuard(key)
        assert not here.acquired
        here.release()
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_second_plugin_process_launch_is_blocked_end_to_end():
    """The actual production path: plugin_runtime.loader acquires the
    guard (keyed by the plugin's manifest name) before ever connecting to
    the host's IPC pipe. A second real launch of the same plugin should
    never complete the handshake at all."""
    first = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR)
    second = PluginProcess("dummy-plugin", DUMMY_PLUGIN_DIR)
    try:
        first.start(connect_timeout=10)
        assert first.is_running()

        with pytest.raises(TimeoutError):
            second.start(connect_timeout=3, ready_timeout=3)
    finally:
        first.stop()
        second.stop()
