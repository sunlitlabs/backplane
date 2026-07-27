"""The smart-launcher decision logic.

The same idempotent chain runs whether this is a plugin's very first
launch on a fresh machine or the thousandth: is a host already running?
(ask it to show the plugin.) Is Backplane installed but not running?
(launch it, then ask.) Is Backplane missing entirely? (bootstrap it.) Is
the plugin itself not registered yet? (register it.) There is no separate
one-time installer distinct from the everyday run action -- each plugin's
own one-file install/launch script is a thin shell wrapper that ensures
Python itself is present, then calls ``launch_plugin`` below every single
time it runs.

Every side-effecting step is injected via ``LauncherActions`` so this
decision logic -- the part that's actually novel here -- can be tested
without touching the network/filesystem/process table in every test.
Production code wires these to the real implementations built in earlier
phases (VersionedInstall, PluginRegistry, fetch_latest_release, etc.).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from backplane.host.control_server import ping_host, request_show_plugin


class LaunchFailedError(Exception):
    """The chain ran to its end without successfully showing the plugin --
    e.g. the host never became reachable after being launched."""


@dataclass
class LauncherActions:
    is_backplane_installed: Callable[[], bool]
    bootstrap_backplane: Callable[[], None]
    is_plugin_registered: Callable[[str], bool]
    install_plugin: Callable[[str, str], None]  # (plugin_name, repo) -> None
    launch_host: Callable[[], None]
    ping_host: Callable[[], bool] = ping_host
    request_show_plugin: Callable[[str], bool] = request_show_plugin
    host_startup_timeout: float = 20.0
    host_poll_interval: float = 0.5


def launch_plugin(
    plugin_name: str,
    plugin_repo: str,
    actions: LauncherActions,
    on_status: Callable[[str], None] = lambda msg: None,
) -> None:
    if actions.ping_host():
        on_status(f"Backplane is running -- asking it to show {plugin_name}.")
        if actions.request_show_plugin(plugin_name):
            return

        on_status(f"Host doesn't know {plugin_name} yet -- registering it.")
        actions.install_plugin(plugin_name, plugin_repo)
        if actions.request_show_plugin(plugin_name):
            return

        raise LaunchFailedError(
            f"Host is running but still couldn't show {plugin_name!r} after registering it"
        )

    if not actions.is_backplane_installed():
        on_status("Setting up shared components (Backplane)...")
        actions.bootstrap_backplane()

    if not actions.is_plugin_registered(plugin_name):
        on_status(f"Registering {plugin_name}...")
        actions.install_plugin(plugin_name, plugin_repo)

    on_status("Starting Backplane...")
    actions.launch_host()

    deadline = time.monotonic() + actions.host_startup_timeout
    while time.monotonic() < deadline:
        if actions.ping_host():
            if actions.request_show_plugin(plugin_name):
                return
            break
        time.sleep(actions.host_poll_interval)

    raise LaunchFailedError(f"Backplane started but never became reachable to show {plugin_name!r}")
