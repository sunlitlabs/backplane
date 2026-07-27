"""Test for the About window: standard Tk chrome, so light coverage --
just that it constructs with the right content and the link triggers
webbrowser.open with the right URL (not a real browser launch in tests).
"""

from __future__ import annotations

import tkinter as tk

import pytest

from backplane.host.chrome import about as about_module
from backplane.host.chrome.about import AboutWindow


@pytest.fixture(scope="module")
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


def test_about_window_shows_name_and_version(root):
    win = AboutWindow(root, app_name="Backplane", version="1.2.3", repo_url="https://example.invalid/repo")
    try:
        texts = _all_label_texts(win.window)
        assert "Backplane" in texts
        assert "Version 1.2.3" in texts
        assert "https://example.invalid/repo" in texts
    finally:
        win.close()


def test_clicking_the_link_opens_the_repo_url(root, monkeypatch):
    opened = []
    monkeypatch.setattr(about_module.webbrowser, "open", lambda url: opened.append(url))

    win = AboutWindow(root, repo_url="https://example.invalid/repo")
    try:
        link = _find_widget_by_text(win.window, "https://example.invalid/repo")
        assert link is not None
        link.event_generate("<Button-1>")
        assert opened == ["https://example.invalid/repo"]
    finally:
        win.close()


def _all_label_texts(widget):
    texts = []
    for child in widget.winfo_children():
        if hasattr(child, "cget"):
            try:
                texts.append(child.cget("text"))
            except tk.TclError:
                pass
        texts.extend(_all_label_texts(child))
    return texts


def _find_widget_by_text(widget, text):
    for child in widget.winfo_children():
        try:
            if child.cget("text") == text:
                return child
        except tk.TclError:
            pass
        found = _find_widget_by_text(child, text)
        if found is not None:
            return found
    return None
