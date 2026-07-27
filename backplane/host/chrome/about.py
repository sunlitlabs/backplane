"""A simple About window: name, version, and a clickable repo link.
Standard Tk chrome, same spirit as update_dialog.py.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from backplane import __version__

APP_NAME = "Backplane"
REPO_URL = "https://github.com/sunlitlabs/backplane"


class AboutWindow:
    def __init__(self, parent: tk.Misc, app_name: str = APP_NAME, version: str = __version__, repo_url: str = REPO_URL):
        self.window = tk.Toplevel(parent)
        self.window.title(f"About {app_name}")
        self.window.resizable(False, False)

        frame = ttk.Frame(self.window, padding=20)
        frame.grid(row=0, column=0)

        ttk.Label(frame, text=app_name, font=("TkDefaultFont", 14, "bold")).grid(row=0, column=0, pady=(0, 4))
        ttk.Label(frame, text=f"Version {version}").grid(row=1, column=0, pady=(0, 8))

        link = ttk.Label(frame, text=repo_url, foreground="blue", cursor="hand2")
        link.grid(row=2, column=0, pady=(0, 12))
        link.bind("<Button-1>", lambda _e: webbrowser.open(repo_url))

        ttk.Button(frame, text="Close", command=self.window.destroy).grid(row=3, column=0)

    def close(self) -> None:
        self.window.destroy()
