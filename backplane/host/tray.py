"""Tray icon management (pystray-backed).

Phase 0 scope: a single icon with a static menu. Phase 5 generalizes this
into a TrayModel that rebuilds dynamically as plugins load/crash/restart and
supports both one-icon-per-plugin and one-combined-icon display modes.
"""

from __future__ import annotations

import threading
from typing import Callable, List, NamedTuple, Optional

import pystray
from PIL import Image, ImageDraw


class TrayItem(NamedTuple):
    label: str
    callback: Callable[[], None]


def make_placeholder_icon_image(size: int = 64) -> Image.Image:
    """A simple generated glyph, used until a plugin/host supplies a real
    .ico. Kept deliberately simple -- this is not meant to be the final
    Backplane brand mark."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 8
    draw.ellipse((margin, margin, size - margin, size - margin), fill=(40, 120, 200, 255))
    return image


class Tray:
    """Owns a single pystray.Icon running on its own daemon thread.

    pystray's Win32 backend just pumps GetMessage/DispatchMessage on
    whatever thread calls .run(), so running it on a dedicated thread while
    Tk owns the main thread is safe -- the same pattern already proven in
    this tool ecosystem.
    """

    def __init__(
        self,
        name: str,
        title: str,
        items: List[TrayItem],
        image: Optional[Image.Image] = None,
    ):
        self._items = list(items)
        self._icon = pystray.Icon(
            name,
            icon=image or make_placeholder_icon_image(),
            title=title,
            menu=self._build_menu(),
        )
        self._thread: Optional[threading.Thread] = None

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            *(
                pystray.MenuItem(item.label, _make_menu_callback(item.callback))
                for item in self._items
            )
        )

    def set_items(self, items: List[TrayItem]) -> None:
        self._items = list(items)
        self._icon.menu = self._build_menu()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._icon.run, name="backplane-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._icon.stop()


def _make_menu_callback(callback: Callable[[], None]):
    def _on_click(icon, item):
        callback()

    return _on_click
