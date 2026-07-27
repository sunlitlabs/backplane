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

from backplane.host.process import APP_NAME, default_data_dir
from backplane.host.registry import PluginRegistry
from backplane.host.updater import (
    VersionedInstall,
    fetch_latest_release,
    fetch_manifest,
    fetch_release_files,
)
from backplane.installer.bootstrap import LauncherActions
from backplane.installer.shell_integration import (
    create_shortcut,
    pythonw_executable,
    set_run_on_startup,
    start_menu_shortcut_path,
)

BACKPLANE_REPO = "sunlitlabs/backplane"


def _locate_plugin_package_dir(version_dir: Path) -> Path:
    """A plugin's release files are expected to be rooted at a package-named
    subdirectory (e.g. "py_sensor/plugin.json", "py_sensor/__init__.py") --
    the same convention Backplane uses for its own self-update, where
    ``_restart_host`` points PYTHONPATH at ``current`` and imports
    "backplane" as the package living directly inside it. This matters
    because run_plugin() resolves a plugin's dotted entrypoint by adding
    its *parent* directory to sys.path, which only works if the plugin's
    own directory is named after the importable package -- never true for
    ``version_dir`` itself, since that's named after the SemVer version
    (e.g. "1.0.0", not a valid Python identifier).

    Falls back to ``version_dir`` itself for a plugin.json placed directly
    at the top (a flat, single-module plugin with no subpackage)."""
    if (version_dir / "plugin.json").exists():
        return version_dir
    candidates = [d for d in version_dir.iterdir() if d.is_dir() and (d / "plugin.json").exists()]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one package directory containing plugin.json under "
            f"{version_dir}, found {len(candidates)}"
        )
    return candidates[0]


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
        # The host itself needs exactly one startup registration, made
        # once here (bootstrap only ever runs when Backplane isn't already
        # installed) -- not a per-plugin concern. Per-plugin
        # run_on_startup_default instead controls whether HostProcess
        # auto-starts that plugin's own supervisor once the host is up
        # (see process.py), since with one always-running host, "does this
        # plugin start automatically" and "does a Windows Run key exist"
        # are different questions.
        set_run_on_startup(APP_NAME, f'"{pythonw_executable()}" -B -m backplane.host.process', enabled=True)

    def is_plugin_registered(name: str) -> bool:
        return registry.is_registered(name)

    def install_plugin(name: str, repo: str) -> None:
        plugin_root = backplane_root / "plugins" / name
        version = install_component(repo, plugin_root)
        version_dir = plugin_root / "versions" / version
        install_dir = _locate_plugin_package_dir(version_dir)
        manifest = json.loads((install_dir / "plugin.json").read_text(encoding="utf-8"))
        registry.register(name, install_dir, manifest)

        if manifest.get("create_start_menu_entry_default", True):
            display_name = manifest.get("display_name", name)
            create_shortcut(
                start_menu_shortcut_path(display_name),
                pythonw_executable(),
                arguments=f"-B -m backplane.installer.launch_cli {name} {repo}",
                icon_location=str(install_dir / manifest["icon"]) if manifest.get("icon") else "",
            )

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
