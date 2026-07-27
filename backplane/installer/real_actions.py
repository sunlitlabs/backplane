"""Wires the smart-launcher decision chain (bootstrap.py) to the real
Backplane/plugin install machinery built in earlier phases -- kept
separate from bootstrap.py itself so that module's decision logic stays
testable via plain fakes without pulling in real network/filesystem/
process dependencies at import time.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backplane.host.process import default_data_dir
from backplane.host.registry import PluginRegistry
from backplane.host.updater import (
    VersionedInstall,
    fetch_latest_release,
    fetch_manifest,
    fetch_release_files,
)
from backplane.installer.bootstrap import LauncherActions

BACKPLANE_REPO = "sunlitlabs/backplane"


def install_component(repo: str, install_root: Path) -> str:
    """Fetches the latest release of ``repo`` and installs it under
    ``install_root`` (a versions/ + current layout, per updater.py).
    Returns the installed version string. Module-level so tests can
    monkeypatch fetch_latest_release/fetch_manifest/fetch_release_files
    here rather than hitting live GitHub."""
    release = fetch_latest_release(repo)
    if release is None:
        raise RuntimeError(f"No releases found for {repo}")
    manifest = fetch_manifest(release)
    files = fetch_release_files(repo, release.tag, manifest["files"])

    versioned = VersionedInstall(install_root)
    version = release.tag.lstrip("v")
    versioned.install_version(version, files)
    versioned.set_current(version)
    return version


def build_real_actions(backplane_root: Path = None) -> LauncherActions:
    backplane_root = backplane_root or default_data_dir()
    registry = PluginRegistry(backplane_root / "registry.json")

    def is_backplane_installed() -> bool:
        return VersionedInstall(backplane_root).current_version() is not None

    def bootstrap_backplane() -> None:
        install_component(BACKPLANE_REPO, backplane_root)

    def is_plugin_registered(name: str) -> bool:
        return registry.is_registered(name)

    def install_plugin(name: str, repo: str) -> None:
        plugin_root = backplane_root / "plugins" / name
        version = install_component(repo, plugin_root)
        install_dir = plugin_root / "versions" / version
        manifest = json.loads((install_dir / "plugin.json").read_text(encoding="utf-8"))
        registry.register(name, install_dir, manifest)

    def launch_host() -> None:
        # DETACHED_PROCESS + CREATE_NO_WINDOW: the host must outlive this
        # short-lived launcher process and never inherit a console it
        # would otherwise flash briefly.
        subprocess.Popen(
            [sys.executable, "-B", "-m", "backplane.host.process"],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )

    return LauncherActions(
        is_backplane_installed=is_backplane_installed,
        bootstrap_backplane=bootstrap_backplane,
        is_plugin_registered=is_plugin_registered,
        install_plugin=install_plugin,
        launch_host=launch_host,
    )
