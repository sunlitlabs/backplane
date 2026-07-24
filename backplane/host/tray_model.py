"""Tracks which plugins are registered for tray presence and renders
either one icon per plugin ("separate") or one combined icon ("combined")
from the exact same registered data.

This is what makes solo-vs-combined a pure display-mode setting rather
than a different install or process model (per ARCHITECTURE.md): flipping
the mode just changes how many Tray instances exist and how their menus
are shaped, using the same PluginTrayInfo the host already has for every
registered plugin.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import pystray
from PIL import Image

from backplane.host.tray import Tray, TrayItem, build_flat_menu

DISPLAY_MODES = ("separate", "combined")


@dataclass
class PluginTrayInfo:
    name: str
    display_name: str
    menu_items: List[TrayItem] = field(default_factory=list)
    icon_image: Optional[Image.Image] = None


class TrayModel:
    _COMBINED_KEY = "__combined__"

    def __init__(self, mode: str = "separate", on_exit: Optional[Callable[[], None]] = None):
        _validate_mode(mode)
        self._mode = mode
        self._on_exit = on_exit or (lambda: None)
        self._plugins: Dict[str, PluginTrayInfo] = {}
        self._trays: Dict[str, Tray] = {}
        self._lock = threading.RLock()

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        _validate_mode(mode)
        with self._lock:
            if mode == self._mode:
                return
            self._mode = mode
            self._rebuild()

    def register_plugin(self, info: PluginTrayInfo) -> None:
        with self._lock:
            self._plugins[info.name] = info
            self._rebuild()

    def unregister_plugin(self, name: str) -> None:
        with self._lock:
            self._plugins.pop(name, None)
            self._rebuild()

    def update_plugin_menu(self, name: str, menu_items: List[TrayItem]) -> None:
        with self._lock:
            if name not in self._plugins:
                return
            self._plugins[name].menu_items = list(menu_items)
            self._rebuild()

    def tray_count(self) -> int:
        with self._lock:
            return len(self._trays)

    def get_tray(self, key: str) -> Optional[Tray]:
        with self._lock:
            return self._trays.get(key)

    def stop(self) -> None:
        with self._lock:
            for tray in self._trays.values():
                tray.stop()
            self._trays.clear()

    def _rebuild(self) -> None:
        desired_keys = set(self._plugins.keys()) if self._mode == "separate" else {self._COMBINED_KEY}

        for key in list(self._trays.keys()):
            if key not in desired_keys:
                self._trays.pop(key).stop()

        if self._mode == "separate":
            for name, info in self._plugins.items():
                menu = build_flat_menu(list(info.menu_items) + [TrayItem("Exit", self._on_exit)])
                existing = self._trays.get(name)
                if existing is not None:
                    existing.set_menu(menu)
                else:
                    tray = Tray(name=name, title=info.display_name, menu=menu, image=info.icon_image)
                    tray.start()
                    self._trays[name] = tray
        else:
            menu = _build_combined_menu(self._plugins, self._on_exit)
            existing = self._trays.get(self._COMBINED_KEY)
            if existing is not None:
                existing.set_menu(menu)
            else:
                tray = Tray(name="backplane-combined", title="Backplane", menu=menu)
                tray.start()
                self._trays[self._COMBINED_KEY] = tray


def _validate_mode(mode: str) -> None:
    if mode not in DISPLAY_MODES:
        raise ValueError(f"Unknown tray display mode {mode!r}, expected one of {DISPLAY_MODES}")


def _build_combined_menu(
    plugins: Dict[str, PluginTrayInfo], on_exit: Callable[[], None]
) -> pystray.Menu:
    entries = []
    for info in plugins.values():
        submenu = build_flat_menu(info.menu_items)
        entries.append(pystray.MenuItem(info.display_name, submenu))
    if entries:
        entries.append(pystray.Menu.SEPARATOR)
    entries.append(pystray.MenuItem("Exit Backplane", _exit_callback(on_exit)))
    return pystray.Menu(*entries)


def _exit_callback(callback: Callable[[], None]):
    def _on_click(icon, item):
        callback()

    return _on_click
