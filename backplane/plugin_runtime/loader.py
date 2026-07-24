"""Loads a plugin from its manifest and wires it to the host via IPC.

This runs inside the plugin's own subprocess, never in the host process.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from backplane.host.crash_log import setup_crash_logging
from backplane.host.process import default_data_dir
from backplane.host.single_instance import SingleInstanceGuard
from backplane.plugin_manifest import load_entrypoint, load_manifest
from backplane.plugin_runtime.host_rpc import HostRPC
from backplane.plugin_runtime.window_identity import set_app_user_model_id


def run_plugin(plugin_dir: Path, ipc_address: str, instance_key: Optional[str] = None) -> None:
    """``instance_key`` distinguishes concurrent named instances of the
    same plugin (e.g. two different data folders for a plugin that
    supports that) -- omit it for plugins that only ever run one instance
    per machine, which is the default for everything so far."""
    plugin_dir = plugin_dir.resolve()
    manifest = load_manifest(plugin_dir)
    plugin_name = manifest["name"]

    logger = setup_crash_logging(
        default_data_dir() / "logs" / f"plugin-{plugin_name}.log",
        logger_name=f"backplane.plugin.{plugin_name}",
    )

    guard_key = plugin_name if instance_key is None else f"{plugin_name}.{instance_key}"
    guard = SingleInstanceGuard(guard_key)
    if not guard.acquired:
        logger.warning(
            "Another instance of %s is already running (guard key %r) -- exiting without "
            "loading the plugin.",
            plugin_name,
            guard_key,
        )
        return

    try:
        set_app_user_model_id(plugin_name)
    except OSError:
        logging.getLogger(f"backplane.plugin.{plugin_name}").exception(
            "Failed to set AppUserModelID (non-fatal, taskbar grouping may be off)"
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

    try:
        plugin.on_load(host)
        # Only after on_load() has actually finished is it safe for the
        # host to start dispatching invoke calls (hotkeys, menu clicks) --
        # a bare pipe connection existing is not sufficient evidence of
        # that (on_load() may still be setting up state an invoked method
        # depends on).
        host.signal_ready()
        plugin.start()
    finally:
        guard.release()
