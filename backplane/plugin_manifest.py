"""Loads and validates a plugin's plugin.json manifest, and resolves its
entrypoint class."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict

REQUIRED_FIELDS = ("name", "entrypoint")


class ManifestError(Exception):
    """The plugin.json manifest is missing, malformed, or its entrypoint
    can't be resolved."""


def load_manifest(plugin_dir: Path) -> Dict[str, Any]:
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        raise ManifestError(f"No plugin.json in {plugin_dir}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ManifestError(f"plugin.json missing required fields: {missing}")
    return data


def load_entrypoint(entrypoint: str):
    """``entrypoint`` is 'module.path:ClassName'."""
    module_path, _, class_name = entrypoint.partition(":")
    if not module_path or not class_name:
        raise ManifestError(f"Invalid entrypoint {entrypoint!r}, expected 'module:Class'")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ManifestError(f"Entrypoint module {module_path!r} has no attribute {class_name!r}")
    return cls
