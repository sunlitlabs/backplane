"""Tests for the drift-detected-plugin confirmation dialog. Same
button-click-scheduling pattern as test_update_dialog.py: the dialog
blocks on wait_window(), so a synthetic click is scheduled via root.after()
before calling it.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from backplane.host.chrome.confirm_removal_dialog import ask_confirm_removal


@pytest.fixture
def root(tk_root):
    return tk_root


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


def test_confirming_removal_returns_true(root):
    _click_button_soon(root, "Remove it now")
    assert ask_confirm_removal(root, "some-plugin") is True


def test_keep_waiting_returns_false(root):
    _click_button_soon(root, "Keep waiting")
    assert ask_confirm_removal(root, "some-plugin") is False
