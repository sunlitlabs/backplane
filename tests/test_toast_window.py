"""Tests for the toast notification queue: one visible at a time, shown
in order, auto-dismissing and advancing the queue.
"""

from __future__ import annotations

import time
import tkinter as tk

import pytest

from backplane.host.chrome.toast_window import ToastManager


@pytest.fixture
def root(tk_root):
    return tk_root


def _pump(root, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        time.sleep(0.01)


def _pump_until(root, predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_single_toast_shows_and_dismisses(root):
    manager = ToastManager(root, duration_ms=100)
    manager.show("Title", "Message")
    assert manager._current is not None

    _pump(root, 0.3)
    assert manager._current is None


def test_toasts_shown_one_at_a_time_in_order(root):
    manager = ToastManager(root, duration_ms=200)
    manager.show("First", "one")
    manager.show("Second", "two")

    first_window = manager._current.window
    assert len(manager._queue) == 1  # second is queued, not shown yet

    # Wait for exactly the hand-off: first gone, second now current.
    assert _pump_until(root, lambda: manager._current is not None and manager._current.window != first_window)
    assert not manager._queue

    assert _pump_until(root, lambda: manager._current is None)  # second dismisses too, eventually


def test_clicking_a_toast_dismisses_it_immediately(root):
    manager = ToastManager(root, duration_ms=10_000)  # long enough that only a click would dismiss it
    manager.show("Title", "Message")
    toast = manager._current

    toast.window.event_generate("<Button-1>")
    root.update()

    assert manager._current is None
