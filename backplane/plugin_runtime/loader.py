"""Loads a plugin from its manifest and wires it to the host via IPC.

This runs inside the plugin's own subprocess, never in the host process.
"""

from __future__ import annotations

import sys
from pathlib import Path

from backplane.host.crash_log import setup_crash_logging
from backplane.host.process import default_data_dir
from backplane.plugin_manifest import load_entrypoint, load_manifest
from backplane.plugin_runtime.host_rpc import HostRPC


def run_plugin(plugin_dir: Path, ipc_address: str) -> None:
    plugin_dir = plugin_dir.resolve()
    manifest = load_manifest(plugin_dir)
    plugin_name = manifest["name"]

    setup_crash_logging(
        default_data_dir() / "logs" / f"plugin-{plugin_name}.log",
        logger_name=f"backplane.plugin.{plugin_name}",
    )

    # The manifest's entrypoint is a dotted path resolved against the
    # plugin's own package, which sits at plugin_dir -- so plugin_dir's
    # *parent* needs to be importable, exactly like any other Python
    # package layout.
    sys.path.insert(0, str(plugin_dir.parent))

    plugin_cls = load_entrypoint(manifest["entrypoint"])
    plugin = plugin_cls()

    host = HostRPC(ipc_address)
    host.set_invoke_target(plugin)
    host.start()

    plugin.on_load(host)
    # Only after on_load() has actually finished is it safe for the host to
    # start dispatching invoke calls (hotkeys, menu clicks) -- a bare pipe
    # connection existing is not sufficient evidence of that (on_load() may
    # still be setting up state an invoked method depends on).
    host.signal_ready()
    plugin.start()
