"""Tests for the generic, schema-driven settings window: conditional
visibility (nested settings) and the save callback's value/secret split.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from backplane.host.chrome.settings_shell import SettingsWindow

SCHEMA = {
    "fields": [
        {"key": "enable_advanced", "type": "boolean", "default": False, "label": "Enable advanced"},
        {
            "key": "advanced_threshold",
            "type": "integer",
            "default": 10,
            "label": "Threshold",
            "show_if": {"key": "enable_advanced", "equals": True},
        },
        {"key": "api_key", "type": "secret", "label": "API Key"},
    ]
}


@pytest.fixture
def root(tk_root):
    # Shared session-scoped Tk() (see conftest.py) rather than a fresh one
    # per file: repeatedly creating and destroying Tk() within one process
    # is fragile (observed real Tcl-library-path errors once the full
    # suite -- many Tk-using test files -- ran together, not just within
    # this file alone). Each test still gets its own fresh Toplevel via
    # SettingsWindow and destroys only that.
    return tk_root


def test_conditional_field_hidden_by_default(root):
    win = SettingsWindow(root, "Test", SCHEMA, values={}, on_save=lambda *_: None)
    _, threshold_widget = win._rows["advanced_threshold"]
    assert not threshold_widget.winfo_ismapped()
    win.window.destroy()


def test_conditional_field_appears_when_toggled_on(root):
    win = SettingsWindow(root, "Test", SCHEMA, values={}, on_save=lambda *_: None)
    win._vars["enable_advanced"].set(True)
    root.update()  # let the trace-triggered visibility update run

    _, threshold_widget = win._rows["advanced_threshold"]
    assert threshold_widget.winfo_ismapped()
    win.window.destroy()


def test_secret_field_prefills_from_get_secret(root):
    win = SettingsWindow(
        root, "Test", SCHEMA, values={}, on_save=lambda *_: None, get_secret=lambda key: "prefilled-value"
    )
    assert win._vars["api_key"].get() == "prefilled-value"
    win.window.destroy()


def test_save_splits_values_and_secrets(root):
    captured = {}

    def on_save(values, secrets):
        captured["values"] = values
        captured["secrets"] = secrets

    win = SettingsWindow(
        root,
        "Test",
        SCHEMA,
        values={"enable_advanced": True, "advanced_threshold": 42},
        on_save=on_save,
    )
    win._vars["api_key"].set("new-secret-value")
    win._save()

    assert captured["values"]["enable_advanced"] is True
    assert captured["values"]["advanced_threshold"] == 42
    assert "api_key" not in captured["values"]
    assert captured["secrets"]["api_key"] == "new-secret-value"
