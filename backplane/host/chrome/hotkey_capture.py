"""A shared Tk widget for capturing a global hotkey combo by pressing keys
live, rather than requiring the user to type a combo as text -- generalized
for Backplane's own Tkinter chrome from the strongest existing reference
(CrierTTS's Qt-based HotkeyEdit). Requires at least one modifier, matching
hotkeys.py's own parse_combo requirement, and can report a live conflict
against a HotkeyManager's current registrations as soon as a combo is
captured (an OS-level conflict with some other application is only ever
caught by an actual registration attempt, at save time).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from backplane.host.hotkeys import HotkeyManager, HotkeyParseError, normalize_combo, parse_combo

_MODIFIER_KEYSYMS = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "Shift_L": "shift",
    "Shift_R": "shift",
    "Super_L": "win",
    "Super_R": "win",
    "Win_L": "win",
    "Win_R": "win",
}

_KEYSYM_TO_KEYNAME = {}
for _ch in "0123456789":
    _KEYSYM_TO_KEYNAME[_ch] = _ch
for _ch in "abcdefghijklmnopqrstuvwxyz":
    _KEYSYM_TO_KEYNAME[_ch] = _ch
    _KEYSYM_TO_KEYNAME[_ch.upper()] = _ch
for _i in range(1, 25):
    _KEYSYM_TO_KEYNAME[f"F{_i}"] = f"f{_i}"
_KEYSYM_TO_KEYNAME.update(
    {
        "space": "space",
        "Tab": "tab",
        "Return": "enter",
        "Escape": "esc",
        "BackSpace": "backspace",
        "Delete": "delete",
        "Insert": "insert",
        "Home": "home",
        "End": "end",
        "Prior": "pageup",
        "Next": "pagedown",
        "Up": "up",
        "Down": "down",
        "Left": "left",
        "Right": "right",
    }
)


def prettify_combo(combo: str) -> str:
    if not combo:
        return ""
    return "+".join(part.capitalize() for part in combo.split("+"))


class HotkeyCaptureEntry(ttk.Entry):
    """A read-only field showing the current combo; clicking it starts
    "listening" for the next real key-press-with-modifier, which becomes
    the new combo. Escape cancels and restores the previous value."""

    def __init__(
        self,
        parent: tk.Misc,
        initial_combo: str = "",
        on_change: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        self._combo = normalize_combo(initial_combo) if initial_combo else ""
        self._var = tk.StringVar(value=prettify_combo(self._combo))
        super().__init__(parent, textvariable=self._var, state="readonly", **kwargs)

        self._on_change = on_change
        self._held_modifiers: set = set()
        self._listening = False

        self.bind("<Button-1>", self._start_listening)
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<FocusOut>", lambda _e: self._stop_listening())

    @property
    def combo(self) -> str:
        return self._combo

    def set_combo(self, combo: str) -> None:
        self._combo = normalize_combo(combo) if combo else ""
        self._var.set(prettify_combo(self._combo))

    def _start_listening(self, _event=None):
        self._listening = True
        self._held_modifiers.clear()
        self._var.set("Press a key combination...")
        self.focus_set()
        return "break"

    def _stop_listening(self) -> None:
        if self._listening:
            self._listening = False
            self._var.set(prettify_combo(self._combo))

    def _on_key_press(self, event):
        if not self._listening:
            return "break"

        keysym = event.keysym
        if keysym in _MODIFIER_KEYSYMS:
            self._held_modifiers.add(_MODIFIER_KEYSYMS[keysym])
            return "break"

        if keysym == "Escape":
            self._stop_listening()
            return "break"

        key_name = _KEYSYM_TO_KEYNAME.get(keysym)
        if key_name is None or not self._held_modifiers:
            return "break"  # no modifier held yet, or an unrecognized key -- keep listening

        combo = "+".join(sorted(self._held_modifiers) + [key_name])
        try:
            parse_combo(combo)
        except HotkeyParseError:
            return "break"

        self._combo = normalize_combo(combo)
        self._listening = False
        self._var.set(prettify_combo(self._combo))
        if self._on_change:
            self._on_change(self._combo)
        return "break"

    def _on_key_release(self, event):
        if not self._listening:
            return "break"
        released = _MODIFIER_KEYSYMS.get(event.keysym)
        if released:
            self._held_modifiers.discard(released)
        return "break"


def check_conflict(hotkey_manager: HotkeyManager, combo: str, owner: str) -> Optional[str]:
    """Returns a human-readable message if ``combo`` is already claimed by
    a different owner, or None if it's free (as far as in-process
    bookkeeping knows). For live feedback in a settings UI, without
    attempting a real registration."""
    existing_owner = hotkey_manager.get_owner_of(combo)
    if existing_owner is not None and existing_owner != owner:
        return f"Already used by {existing_owner}"
    return None
