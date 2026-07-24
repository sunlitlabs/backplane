"""Tests for the update-flow dialogs. These block on wait_window() until a
button is clicked, exactly like a real modal dialog -- so each test
schedules a synthetic click via root.after() before calling the function,
the same way a real click would arrive while the dialog pumps events.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from backplane.host.chrome.update_dialog import (
    ProgressDialog,
    ask_restart_action,
    ask_update_action,
)


@pytest.fixture(scope="module")
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def _find_button(widget, text):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return child
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def _click_button_soon(root, text, delay_ms=50):
    def _click():
        dialog = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        button = _find_button(dialog, text)
        assert button is not None, f"no button with text {text!r} found"
        button.invoke()

    root.after(delay_ms, _click)


def test_ask_update_action_now(root):
    _click_button_soon(root, "Update now")
    assert ask_update_action(root, "v1.2.3") == "now"


def test_ask_update_action_wait(root):
    _click_button_soon(root, "Remind me later")
    assert ask_update_action(root, "v1.2.3") == "wait"


def test_ask_update_action_skip(root):
    _click_button_soon(root, "Skip this version")
    assert ask_update_action(root, "v1.2.3") == "skip"


def test_ask_restart_action_now(root):
    _click_button_soon(root, "Restart now")
    assert ask_restart_action(root) == "now"


def test_ask_restart_action_later(root):
    _click_button_soon(root, "Later")
    assert ask_restart_action(root) == "later"


def test_progress_dialog_updates_and_closes(root):
    dialog = ProgressDialog(root, title="Test progress")
    dialog.set_progress(1, 4, "Downloading a.py...")
    assert dialog._progress["value"] == 1
    assert dialog._progress["maximum"] == 4
    assert dialog._label_var.get() == "Downloading a.py..."

    dialog.set_progress(4, 4, "Done")
    assert dialog._progress["value"] == 4

    dialog.close()
