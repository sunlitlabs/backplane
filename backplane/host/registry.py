"""The plugin registry: install/uninstall are the registration trigger,
not a folder scan -- this is the source of truth for what's installed.

Also home to the one canonical uninstall routine (see ``uninstall_plugin``
below), used both when a user explicitly uninstalls a plugin and when the
registry concludes a plugin was removed out-of-band, after drift
confirmation. There is deliberately only one teardown path -- it always
runs every step it knows about, never a partial subset.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backplane.host import secrets as secrets_module
from backplane.host.hotkeys import HotkeyManager
from backplane.host.settings_store import SettingsStore
from backplane.host.tray_model import TrayModel

DEFAULT_DRIFT_RETRY_INTERVAL = 30.0  # seconds between drift re-checks
DEFAULT_DRIFT_RETRY_WINDOW = 600.0  # seconds a plugin may be missing before it's confirmed-missing


@dataclass
class RegistryEntry:
    name: str
    install_dir: str
    manifest: Dict[str, Any]
    registered_at: float
    awaiting_confirmation: bool = False


class PluginRegistry:
    """Tracks installed plugins and detects drift (files that went missing
    without going through an explicit uninstall).

    Registered-but-missing plugins are never purged on a single miss --
    that would misfire on something as ordinary as a slow cloud-sync
    folder. Only after ``drift_retry_window`` seconds of continuous
    absence does ``check_drift()`` report a plugin as newly
    confirmed-missing; the caller decides what to do next (typically:
    surface a confirmation prompt, then call ``confirm_removed`` or
    ``cancel_missing``). If files reappear before the window elapses, the
    missing state clears on its own with no confirmation ever requested.
    """

    def __init__(
        self,
        registry_path: Path,
        drift_retry_interval: float = DEFAULT_DRIFT_RETRY_INTERVAL,
        drift_retry_window: float = DEFAULT_DRIFT_RETRY_WINDOW,
    ):
        self._path = registry_path
        self._lock = threading.RLock()
        self._entries: Dict[str, RegistryEntry] = {}
        self._missing_since: Dict[str, float] = {}
        self.drift_retry_interval = drift_retry_interval
        self.drift_retry_window = drift_retry_window
        self._load()

    def register(self, name: str, install_dir: Path, manifest: Dict[str, Any]) -> None:
        with self._lock:
            self._entries[name] = RegistryEntry(
                name=name,
                install_dir=str(install_dir),
                manifest=manifest,
                registered_at=time.time(),
            )
            self._missing_since.pop(name, None)
            self._save()

    def deregister(self, name: str) -> None:
        with self._lock:
            self._entries.pop(name, None)
            self._missing_since.pop(name, None)
            self._save()

    def is_registered(self, name: str) -> bool:
        with self._lock:
            return name in self._entries

    def get(self, name: str) -> Optional[RegistryEntry]:
        with self._lock:
            return self._entries.get(name)

    def all_plugins(self) -> List[RegistryEntry]:
        with self._lock:
            return list(self._entries.values())

    def check_drift(self, now: Optional[float] = None) -> List[str]:
        """Call periodically (every ``drift_retry_interval``). Returns the
        names of plugins that crossed the confirmed-missing threshold on
        *this* call -- callers should surface a confirmation prompt for
        each rather than acting immediately."""
        now = now if now is not None else time.time()
        newly_confirmed: List[str] = []
        with self._lock:
            for name, entry in list(self._entries.items()):
                if _plugin_files_present(entry):
                    self._missing_since.pop(name, None)
                    continue
                if name not in self._missing_since:
                    self._missing_since[name] = now
                    continue
                elapsed = now - self._missing_since[name]
                if elapsed >= self.drift_retry_window and not entry.awaiting_confirmation:
                    entry.awaiting_confirmation = True
                    newly_confirmed.append(name)
            if newly_confirmed:
                self._save()
        return newly_confirmed

    def cancel_missing(self, name: str) -> None:
        """The user said 'keep waiting', or the files reappeared on their
        own -- clears the missing/awaiting-confirmation state without
        deregistering anything."""
        with self._lock:
            self._missing_since.pop(name, None)
            entry = self._entries.get(name)
            if entry is not None:
                entry.awaiting_confirmation = False
                self._save()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for name, raw in data.get("plugins", {}).items():
            self._entries[name] = RegistryEntry(
                name=raw["name"],
                install_dir=raw["install_dir"],
                manifest=raw["manifest"],
                registered_at=raw["registered_at"],
                awaiting_confirmation=raw.get("awaiting_confirmation", False),
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"plugins": {name: asdict(entry) for name, entry in self._entries.items()}}
        tmp_path = self._path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self._path)


def _plugin_files_present(entry: RegistryEntry) -> bool:
    install_dir = Path(entry.install_dir)
    return install_dir.is_dir() and (install_dir / "plugin.json").exists()


@dataclass
class UninstallContext:
    """Everything the canonical uninstall routine might need to tear
    down. Optional fields so this stays extensible without changing
    uninstall_plugin's shape or call sites."""

    tray_model: Optional[TrayModel] = None
    hotkey_manager: Optional[HotkeyManager] = None
    settings_store: Optional[SettingsStore] = None
    purge_settings: bool = True
    purge_secrets: bool = True
    remove_shell_integration: bool = True


def uninstall_plugin(registry: PluginRegistry, plugin_name: str, ctx: UninstallContext) -> None:
    """The one canonical, complete teardown -- used both for an explicit,
    user-initiated uninstall and for a plugin the registry concludes was
    removed out-of-band (after drift confirmation via
    ``PluginRegistry.check_drift``). Always runs every step it knows
    about; never a partial subset."""
    if ctx.remove_shell_integration:
        entry = registry.get(plugin_name)
        if entry is not None:
            # Local import: shell_integration lives in installer/, which
            # importing at module level here would create a host -> installer
            # dependency the rest of this package deliberately avoids.
            from backplane.installer.shell_integration import remove_shortcut, start_menu_shortcut_path

            display_name = entry.manifest.get("display_name", plugin_name)
            remove_shortcut(start_menu_shortcut_path(display_name))
    if ctx.tray_model is not None:
        ctx.tray_model.unregister_plugin(plugin_name)
    if ctx.hotkey_manager is not None:
        ctx.hotkey_manager.unregister_all_for_owner(plugin_name)
    if ctx.settings_store is not None and ctx.purge_settings:
        ctx.settings_store.delete(plugin_name)
    if ctx.purge_secrets:
        secrets_module.delete_all_secrets(plugin_name)
    registry.deregister(plugin_name)
