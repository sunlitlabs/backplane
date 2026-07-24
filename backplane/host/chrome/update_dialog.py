"""Update-flow dialogs: ask update-now/wait/skip, show progress while
applying, then ask restart-now/later.

Standard Tk chrome -- the part of Phase 7 that's actually novel to
Backplane's design (versioned installs, junctions, rollback, pruning)
lives in updater.py; this is just the UI wrapped around it.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional


def ask_update_action(parent: tk.Misc, version_label: str) -> str:
    """Returns 'now', 'wait', or 'skip'. Blocks until the user chooses (or
    closes the dialog, treated as 'wait')."""
    result = {"action": "wait"}
    dialog = tk.Toplevel(parent)
    dialog.title("Update available")
    dialog.resizable(False, False)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=16)
    frame.grid(row=0, column=0)
    ttk.Label(frame, text=f"A new version ({version_label}) is available.").grid(
        row=0, column=0, columnspan=3, pady=(0, 12)
    )

    def _choose(action: str) -> None:
        result["action"] = action
        dialog.destroy()

    ttk.Button(frame, text="Skip this version", command=lambda: _choose("skip")).grid(row=1, column=0, padx=4)
    ttk.Button(frame, text="Remind me later", command=lambda: _choose("wait")).grid(row=1, column=1, padx=4)
    ttk.Button(frame, text="Update now", command=lambda: _choose("now")).grid(row=1, column=2, padx=4)
    dialog.protocol("WM_DELETE_WINDOW", lambda: _choose("wait"))

    dialog.wait_window()
    return result["action"]


class ProgressDialog:
    """A determinate progress bar + status label. ``set_progress`` is safe
    to call from the same thread that's driving the update (typically a
    background thread) only if marshaled via root.after(0, ...) first --
    like every other cross-thread boundary in Backplane, this class itself
    assumes it's only ever touched from the Tk thread."""

    def __init__(self, parent: tk.Misc, title: str = "Updating..."):
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.resizable(False, False)

        frame = ttk.Frame(self.window, padding=16)
        frame.grid(row=0, column=0)

        self._label_var = tk.StringVar(value="Starting...")
        ttk.Label(frame, textvariable=self._label_var, width=40).grid(row=0, column=0, sticky="w")

        self._progress = ttk.Progressbar(frame, mode="determinate", length=300)
        self._progress.grid(row=1, column=0, pady=(8, 0))

    def set_progress(self, current: int, total: int, message: Optional[str] = None) -> None:
        self._progress["maximum"] = max(total, 1)
        self._progress["value"] = current
        if message is not None:
            self._label_var.set(message)
        self.window.update_idletasks()

    def close(self) -> None:
        self.window.destroy()


def ask_restart_action(parent: tk.Misc) -> str:
    """Returns 'now' or 'later'."""
    result = {"action": "later"}
    dialog = tk.Toplevel(parent)
    dialog.title("Update installed")
    dialog.resizable(False, False)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=16)
    frame.grid(row=0, column=0)
    ttk.Label(frame, text="The update has been installed. Restart now to apply it?").grid(
        row=0, column=0, columnspan=2, pady=(0, 12)
    )

    def _choose(action: str) -> None:
        result["action"] = action
        dialog.destroy()

    ttk.Button(frame, text="Later", command=lambda: _choose("later")).grid(row=1, column=0, padx=4)
    ttk.Button(frame, text="Restart now", command=lambda: _choose("now")).grid(row=1, column=1, padx=4)
    dialog.protocol("WM_DELETE_WINDOW", lambda: _choose("later"))

    dialog.wait_window()
    return result["action"]
