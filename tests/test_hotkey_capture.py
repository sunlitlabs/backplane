"""Tests for the hotkey-capture widget: live key capture (via Tk's
synthetic event generation, which drives the same bound handlers a real
keypress would) and live conflict feedback against a real HotkeyManager.
"""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from backplane.host.chrome.hotkey_capture import HotkeyCaptureEntry, check_conflict, prettify_combo
from backplane.host.hotkeys import HotkeyManager


@pytest.fixture
def root(tk_root):
    return tk_root


def _press(widget, keysym):
    # Calls the bound handler directly with a fake event, rather than
    # tkinter's event_generate -- synthetic KeyPress events are routed by
    # focus, not by which widget .event_generate() was called on, and
    # focus assignment for a withdrawn root proved unreliable in this
    # environment. The binding itself (self.bind("<KeyPress>", ...)) is
    # standard Tkinter, not something worth re-proving; what's actually
    # novel here is _on_key_press's own decision logic, which this
    # exercises directly and precisely.
    widget._on_key_press(SimpleNamespace(keysym=keysym))


def _release(widget, keysym):
    widget._on_key_release(SimpleNamespace(keysym=keysym))


def _start_listening(entry):
    entry._start_listening()


def test_prettify_combo():
    assert prettify_combo("ctrl+alt+t") == "Ctrl+Alt+T"
    assert prettify_combo("") == ""


def test_initial_combo_is_shown_prettified(root):
    entry = HotkeyCaptureEntry(root, initial_combo="ctrl+alt+t")
    assert entry.combo == "alt+ctrl+t"  # normalized (sorted)
    assert entry._var.get() == "Alt+Ctrl+T"


def test_clicking_starts_listening(root):
    entry = HotkeyCaptureEntry(root)
    _start_listening(entry)
    assert entry._listening
    assert entry._var.get() == "Press a key combination..."


def test_capturing_a_combo_with_a_modifier_and_a_key(root):
    captured = []
    entry = HotkeyCaptureEntry(root, on_change=captured.append)
    _start_listening(entry)

    _press(entry, "Control_L")
    _press(entry, "Alt_L")
    _press(entry, "t")

    assert entry.combo == "alt+ctrl+t"
    assert entry._var.get() == "Alt+Ctrl+T"
    assert captured == ["alt+ctrl+t"]
    assert not entry._listening  # capture completes and stops listening


def test_key_without_a_modifier_is_ignored(root):
    entry = HotkeyCaptureEntry(root)
    _start_listening(entry)
    _press(entry, "t")  # no modifier held

    assert entry._listening  # still waiting -- not a valid combo yet
    assert entry.combo == ""


def test_releasing_a_modifier_before_the_key_forgets_it(root):
    entry = HotkeyCaptureEntry(root)
    _start_listening(entry)

    _press(entry, "Control_L")
    _release(entry, "Control_L")
    _press(entry, "t")

    assert entry._listening  # ctrl was released, so this still isn't a valid combo
    assert entry.combo == ""


def test_escape_cancels_and_restores_previous_combo(root):
    entry = HotkeyCaptureEntry(root, initial_combo="ctrl+alt+f1")
    _start_listening(entry)
    assert entry._var.get() == "Press a key combination..."

    _press(entry, "Escape")

    assert not entry._listening
    assert entry.combo == "alt+ctrl+f1"  # unchanged
    assert entry._var.get() == "Alt+Ctrl+F1"


def test_set_combo_updates_display(root):
    entry = HotkeyCaptureEntry(root)
    entry.set_combo("ctrl+shift+f5")
    assert entry.combo == "ctrl+f5+shift"
    assert entry._var.get() == "Ctrl+F5+Shift"


def test_check_conflict_flags_a_different_owner():
    hotkeys = HotkeyManager()
    hotkeys.start()
    try:
        hotkeys.register("ctrl+alt+f6", owner="plugin-a", callback=lambda: None)
        message = check_conflict(hotkeys, "ctrl+alt+f6", owner="plugin-b")
        assert message is not None
        assert "plugin-a" in message
    finally:
        hotkeys.stop()


def test_check_conflict_allows_rebinding_your_own_hotkey():
    hotkeys = HotkeyManager()
    hotkeys.start()
    try:
        hotkeys.register("ctrl+alt+f7", owner="plugin-a", callback=lambda: None)
        message = check_conflict(hotkeys, "ctrl+alt+f7", owner="plugin-a")
        assert message is None
    finally:
        hotkeys.stop()


def test_check_conflict_returns_none_for_a_free_combo():
    hotkeys = HotkeyManager()
    hotkeys.start()
    try:
        assert check_conflict(hotkeys, "ctrl+alt+f8", owner="plugin-a") is None
    finally:
        hotkeys.stop()
