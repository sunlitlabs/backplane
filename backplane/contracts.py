"""The plugin contract: every plugin subclasses PluginBase and ships a
plugin.json manifest describing it (see plugin_manifest.py).
"""

from __future__ import annotations

from typing import Any


class PluginBase:
    """Base class every Backplane plugin subclasses.

    ``host`` (passed to ``on_load``) is the abstraction over tray/hotkeys/
    settings/secrets/notify -- concretely a HostRPC instance running inside
    the plugin's own subprocess. Plugins never touch OS/tray/hotkey/
    registry APIs directly, only this object.
    """

    def on_load(self, host: Any) -> None:
        """Called once, before start(), with the host API object."""

    def on_hotkey(self, hotkey_id: str) -> None:
        """Called when a hotkey this plugin registered fires."""

    def on_tray_item(self, item_id: str) -> None:
        """Called when a tray menu item this plugin added (via
        host.add_tray_item(item_id, label)) is clicked. There is no
        declarative get_menu_items() -- a callback can't cross the IPC
        boundary, so items are registered imperatively (typically in
        on_load), the same pattern as register_hotkey/on_hotkey."""

    def start(self) -> None:
        """Called after on_load(); do the plugin's actual work here."""

    def stop(self) -> None:
        """Called when the plugin subprocess is asked to shut down."""
