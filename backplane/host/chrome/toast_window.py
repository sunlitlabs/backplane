"""A shared toast/notification system (`host.notify(title, message)`),
available to any plugin, not just the updater -- built once so every tool
looks and behaves consistently. Standard Tk chrome (borderless Toplevel,
bottom-right of the work area, matching where a native Windows toast would
appear), with a queue so rapid successive notify() calls show one at a
time rather than overlapping.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, Tuple

DEFAULT_DURATION_MS = 4000
_MARGIN = 20
_WIDTH = 300
_HEIGHT = 80


class ToastWindow:
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str,
        duration_ms: int = DEFAULT_DURATION_MS,
        on_dismiss: Optional[Callable[[], None]] = None,
    ):
        self._on_dismiss = on_dismiss
        self._dismissed = False

        self.window = tk.Toplevel(parent)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)

        screen_w = parent.winfo_screenwidth()
        screen_h = parent.winfo_screenheight()
        x = screen_w - _WIDTH - _MARGIN
        y = screen_h - _HEIGHT - _MARGIN - 40  # clear of the taskbar
        self.window.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")

        frame = ttk.Frame(self.window, padding=10, relief="raised", borderwidth=1)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(frame, text=message, wraplength=_WIDTH - 20).pack(anchor="w", pady=(4, 0))

        self.window.bind("<Button-1>", lambda _e: self.dismiss())
        self._timer_id = self.window.after(duration_ms, self.dismiss)

    def dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        try:
            self.window.after_cancel(self._timer_id)
        except Exception:
            pass
        self.window.destroy()
        if self._on_dismiss:
            self._on_dismiss()


class ToastManager:
    """Owns the show-one-at-a-time queue. Only ever touched from the Tk
    thread -- callers marshal via root.after(0, ...) first, same rule as
    every other cross-thread boundary in the host process."""

    def __init__(self, parent: tk.Misc, duration_ms: int = DEFAULT_DURATION_MS):
        self._parent = parent
        self._duration_ms = duration_ms
        self._queue: List[Tuple[str, str]] = []
        self._current: Optional[ToastWindow] = None

    def show(self, title: str, message: str) -> None:
        self._queue.append((title, message))
        if self._current is None:
            self._show_next()

    def _show_next(self) -> None:
        if not self._queue:
            self._current = None
            return
        title, message = self._queue.pop(0)
        self._current = ToastWindow(
            self._parent, title, message, duration_ms=self._duration_ms, on_dismiss=self._show_next
        )
