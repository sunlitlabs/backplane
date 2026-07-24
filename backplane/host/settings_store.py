"""Centralized, per-plugin settings storage.

Only the host process ever touches these files -- plugin subprocesses
read/write settings exclusively through host.get_settings()/set_settings()
over IPC, never by opening the file directly. That single-writer invariant
is what keeps this safe without any cross-process file locking.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

SCHEMA_VERSION_KEY = "_schema_version"


class SettingsStore:
    def __init__(self, settings_dir: Path):
        self.settings_dir = settings_dir
        self.settings_dir.mkdir(parents=True, exist_ok=True)

    def load(self, plugin_name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        path = self._path_for(plugin_name)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

        migrated = _apply_schema_defaults(data, schema)
        migrated[SCHEMA_VERSION_KEY] = schema.get("version", 1)

        if migrated != data:
            self.save(plugin_name, migrated)

        return migrated

    def save(self, plugin_name: str, values: Dict[str, Any]) -> None:
        path = self._path_for(plugin_name)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, path)

    def merge_and_save(
        self, plugin_name: str, schema: Dict[str, Any], updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        current = self.load(plugin_name, schema)
        current.update(updates)
        self.save(plugin_name, current)
        return current

    def delete(self, plugin_name: str) -> None:
        """Used by the canonical uninstall routine (registry.py)."""
        try:
            self._path_for(plugin_name).unlink()
        except FileNotFoundError:
            pass

    def _path_for(self, plugin_name: str) -> Path:
        return self.settings_dir / f"{plugin_name}.json"


def _apply_schema_defaults(data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Fill any field declared in the schema but missing from ``data`` with
    its declared default.

    This is deliberately the whole migration story for now: it handles the
    common case (a plugin's schema grows a new field between versions)
    without discarding or crashing on existing settings. No plugin has
    needed a renamed/restructured-key transform yet -- add an explicit
    per-schema-version hook here when one actually does, rather than
    guessing at a shape now.
    """
    result = dict(data)
    for field in schema.get("fields", []):
        if field.get("type") == "secret":
            continue  # secrets never live in the plain settings file
        key = field["key"]
        if key not in result:
            result[key] = field.get("default")
    return result
