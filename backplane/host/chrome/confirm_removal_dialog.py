"""A confirmation dialog for a plugin the registry's drift detection has
concluded is genuinely missing (its retry window elapsed with no files
found) -- ARCHITECTURE.md is explicit that this needs a real confirmation
step rather than an automatic purge, since a slow cloud-sync folder could
otherwise make a perfectly-installed plugin look uninstalled.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def ask_confirm_removal(parent: tk.Misc, plugin_name: str) -> bool:
    """Returns True if the user confirms the plugin should be treated as
    uninstalled, False to keep waiting (registry.cancel_missing should be
    called in that case). Blocks until the user chooses; closing the
    dialog is treated as "keep waiting", the safer default."""
    result = {"confirmed": False}
    dialog = tk.Toplevel(parent)
    dialog.title("Plugin missing")
    dialog.resizable(False, False)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=16)
    frame.grid(row=0, column=0)
    ttk.Label(
        frame,
        text=(
            f"Backplane can't find {plugin_name}'s files anymore.\n\n"
            "Was it uninstalled outside Backplane? If not, it may just be a slow "
            "sync -- choose \"Keep waiting\" and Backplane will keep checking."
        ),
        wraplength=360,
        justify="left",
    ).grid(row=0, column=0, columnspan=2, pady=(0, 12))

    def _choose(confirmed: bool) -> None:
        result["confirmed"] = confirmed
        dialog.destroy()

    ttk.Button(frame, text="Keep waiting", command=lambda: _choose(False)).grid(row=1, column=0, padx=4)
    ttk.Button(frame, text="Remove it now", command=lambda: _choose(True)).grid(row=1, column=1, padx=4)
    dialog.protocol("WM_DELETE_WINDOW", lambda: _choose(False))

    dialog.wait_window()
    return result["confirmed"]
