"""The Backplane host process: owns the Tk mainloop, tray icon(s), crash
logging, and every registered plugin's lifecycle.

This is the assembly point -- every other module (hotkeys, tray_model,
registry, updater, plugin_supervisor, control_server, the chrome dialogs)
is built and tested independently; this class wires them into one running
host.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from typing import Dict, Optional

from backplane import __version__
from backplane.host import secrets as secrets_module
from backplane.host.chrome.about import AboutWindow
from backplane.host.chrome.confirm_removal_dialog import ask_confirm_removal
from backplane.host.chrome.settings_shell import SettingsWindow
from backplane.host.chrome.toast_window import ToastManager
from backplane.host.chrome.update_dialog import ProgressDialog, ask_restart_action, ask_update_action
from backplane.host.control_server import ControlServer
from backplane.host.crash_log import setup_crash_logging, tk_report_callback_exception
from backplane.host.hotkeys import HotkeyManager
from backplane.host.plugin_supervisor import PluginSupervisor
from backplane.host.registry import PluginRegistry, RegistryEntry, UninstallContext, uninstall_plugin
from backplane.host.settings_store import SettingsStore
from backplane.host.subprocess_manager import PluginProcess
from backplane.host.tray import TrayItem
from backplane.host.tray_model import PluginTrayInfo, TrayModel
from backplane.host.updater import (
    ReleaseInfo,
    VersionedInstall,
    fetch_latest_release,
    fetch_manifest,
    fetch_release_files,
    format_semver,
    parse_semver,
)

APP_NAME = "Backplane"
PUBLISHER = "Sunlit Labs"
BACKPLANE_REPO = "sunlitlabs/backplane"

UPDATE_CHECK_STARTUP_DELAY_SECONDS = 10.0
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60.0


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / PUBLISHER / APP_NAME


def default_log_path() -> Path:
    return default_data_dir() / "logs" / "backplane.log"


class HostProcess:
    """Owns the process's Tk mainloop, tray icon(s), and every registered
    plugin's subprocess lifecycle.

    ``auto_exit_after`` exists purely for smoke-testing from a
    non-interactive shell -- never set it in real operation. ``data_dir``
    is overridable for the same reason (tests point it at a temp
    directory rather than the real per-user install location).
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        auto_exit_after: Optional[float] = None,
        tray_mode: str = "separate",
        data_dir: Optional[Path] = None,
        control_pipe_address: Optional[str] = None,
        root: Optional[tk.Tk] = None,
    ):
        # ``root`` is injectable so tests can share one Tk() across many
        # constructed-and-torn-down HostProcess instances -- repeatedly
        # creating/destroying Tk() within one process is fragile (real
        # Tcl-library-path errors surfaced by doing exactly that), the same
        # reasoning already applied to every other chrome component's tests.
        self._owns_root = root is None
        self.data_dir = data_dir or default_data_dir()
        self.logger: logging.Logger = setup_crash_logging(log_path or default_log_path())
        self.root = root or tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = tk_report_callback_exception(  # type: ignore[assignment]
            self.logger
        )

        self.registry = PluginRegistry(self.data_dir / "registry.json")
        self.settings_store = SettingsStore(self.data_dir / "settings")
        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.start()
        self.toast_manager = ToastManager(self.root)

        self.tray_model = TrayModel(mode=tray_mode, on_exit=self.shutdown)
        self.tray_model.register_plugin(PluginTrayInfo(name="__host__", display_name=APP_NAME))
        self.tray_model.update_plugin_menu(
            "__host__",
            [
                TrayItem("About", self._show_about),
                TrayItem("Check for Updates...", self._check_for_updates_interactive),
            ],
        )

        # Every registered plugin is loaded *before* the control server ever
        # starts accepting connections -- a caller polling ping_host() is
        # relying on "the host answered" as a signal that it's actually
        # ready to be asked about a plugin, not just that its listener
        # thread happens to exist yet while plugin loading is still under
        # way. Starting the control server first would let a request race
        # ahead of self._supervisors being populated (caught by testing:
        # request_show_plugin failed with an empty supervisor map even
        # though the plugin went on to start up successfully a moment later).
        self._supervisors: Dict[str, PluginSupervisor] = {}
        for entry in self.registry.all_plugins():
            if entry.manifest.get("run_on_startup_default", True):
                self._start_plugin(entry)

        control_kwargs = {"on_show_plugin": self._handle_show_plugin}
        if control_pipe_address is not None:
            control_kwargs["address"] = control_pipe_address
        self.control_server = ControlServer(**control_kwargs)
        self.control_server.start()

        self._auto_exit_after = auto_exit_after
        self._shutting_down = False

    # -- plugin lifecycle -------------------------------------------------

    def _load_settings_schema(self, entry: RegistryEntry) -> Optional[dict]:
        schema_rel_path = entry.manifest.get("settings_schema")
        if not schema_rel_path:
            return None
        schema_path = Path(entry.install_dir) / schema_rel_path
        if not schema_path.exists():
            return None
        try:
            return json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.logger.exception("Malformed settings schema for %s", entry.name)
            return None

    def _start_plugin(self, entry: RegistryEntry) -> None:
        schema = self._load_settings_schema(entry)
        process = PluginProcess(
            entry.name,
            Path(entry.install_dir),
            settings_store=self.settings_store,
            settings_schema=schema,
            close_behavior=entry.manifest.get("close_behavior_default", "quit"),
            hotkey_manager=self.hotkey_manager,
            tray_model=self.tray_model,
            display_name=entry.manifest.get("display_name", entry.name),
            open_settings_callback=self._open_settings if schema else None,
        )
        supervisor = PluginSupervisor(process, on_crash_loop=self._handle_crash_loop)
        supervisor.start()
        self._supervisors[entry.name] = supervisor

    def _handle_show_plugin(self, plugin_name: str) -> None:
        # Called on the control server's own thread, not the Tk thread --
        # this only ever reads self._supervisors, never mutates it, so no
        # marshaling is needed here.
        if plugin_name not in self._supervisors:
            raise RuntimeError(f"Plugin {plugin_name!r} is not registered with this host")
        # Already running under this always-on host -- nothing further to
        # do for "launch" purposes. Bringing a specific plugin window to
        # the front would need its own IPC call; no plugin has needed that
        # yet, so it isn't built speculatively here.

    def _handle_crash_loop(self, plugin_name: str) -> None:
        # Called on the supervisor's watcher thread -- marshal to Tk.
        self.root.after(
            0,
            lambda: self.toast_manager.show(
                f"{plugin_name} keeps crashing", "It has been stopped after repeated failures."
            ),
        )

    def _open_settings(self, plugin_name: str) -> None:
        entry = self.registry.get(plugin_name)
        if entry is None:
            return
        schema = self._load_settings_schema(entry)
        if schema is None:
            return
        values = self.settings_store.load(plugin_name, schema)

        def _on_save(new_values: dict, new_secrets: dict) -> None:
            self.settings_store.merge_and_save(plugin_name, schema, new_values)
            for key, value in new_secrets.items():
                secrets_module.set_secret(plugin_name, key, value)

        SettingsWindow(
            self.root,
            entry.manifest.get("display_name", plugin_name),
            schema,
            values,
            _on_save,
            get_secret=lambda key: secrets_module.get_secret(plugin_name, key),
        )

    def _show_about(self) -> None:
        AboutWindow(self.root, app_name=APP_NAME, version=__version__)

    # -- drift detection ----------------------------------------------------

    def _run_drift_check(self) -> None:
        if self._shutting_down:
            return
        self._run_drift_check_body()
        interval_ms = int(self.registry.drift_retry_interval * 1000)
        self.root.after(interval_ms, self._run_drift_check)

    def _run_drift_check_body(self, now: Optional[float] = None) -> None:
        """The actual check, separated from the reschedule-via-root.after
        wrapper above so it's directly callable (with an injectable
        ``now``) without needing a running mainloop."""
        newly_missing = self.registry.check_drift(now=now)
        for plugin_name in newly_missing:
            self._confirm_plugin_removal(plugin_name)

    def _confirm_plugin_removal(self, plugin_name: str) -> None:
        confirmed = ask_confirm_removal(self.root, plugin_name)
        if confirmed:
            supervisor = self._supervisors.pop(plugin_name, None)
            if supervisor is not None:
                supervisor.stop()
            ctx = UninstallContext(
                tray_model=self.tray_model,
                hotkey_manager=self.hotkey_manager,
                settings_store=self.settings_store,
            )
            uninstall_plugin(self.registry, plugin_name, ctx)
        else:
            self.registry.cancel_missing(plugin_name)

    # -- self-update ----------------------------------------------------

    def _check_for_updates_interactive(self) -> None:
        self._check_for_self_update(interactive=True)

    def _run_scheduled_update_check(self) -> None:
        if self._shutting_down:
            return
        try:
            self._check_for_self_update(interactive=False)
        except Exception:
            self.logger.exception("Background update check failed")
        self.root.after(int(UPDATE_CHECK_INTERVAL_SECONDS * 1000), self._run_scheduled_update_check)

    def _check_for_self_update(self, interactive: bool) -> None:
        try:
            release = fetch_latest_release(BACKPLANE_REPO)
        except Exception:
            self.logger.exception("Failed to check for updates")
            if interactive:
                self.toast_manager.show(APP_NAME, "Couldn't check for updates -- see the log for details.")
            return

        current_version = parse_semver(__version__)
        if release is None or release.version <= current_version:
            if interactive:
                self.toast_manager.show(APP_NAME, "You're up to date.")
            return

        self._apply_self_update(release)

    def _apply_self_update(self, release: ReleaseInfo) -> None:
        action = ask_update_action(self.root, format_semver(release.version))
        if action in ("skip", "wait"):
            return

        progress = ProgressDialog(self.root, title=f"Updating {APP_NAME}...")
        try:
            manifest = fetch_manifest(release)
            files = manifest["files"]
            downloaded = {}
            for i, rel_path in enumerate(files):
                progress.set_progress(i, len(files), f"Downloading {rel_path}...")
                downloaded.update(fetch_release_files(release.repo, release.tag, [rel_path]))

            versioned = VersionedInstall(self.data_dir)
            version_str = release.tag.lstrip("v")
            versioned.install_version(version_str, downloaded)
            versioned.set_current(version_str)
        finally:
            progress.close()

        if ask_restart_action(self.root) == "now":
            self._restart_host()

    def _restart_host(self) -> None:
        current_dir = str(self.data_dir / "current")
        env = dict(os.environ)
        env["PYTHONPATH"] = current_dir + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.Popen([sys.executable, "-B", "-m", "backplane.host.process"], env=env, cwd=current_dir)
        self.shutdown()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self.logger.info("Backplane host starting (pid=%s)", os.getpid())

        drift_interval_ms = int(self.registry.drift_retry_interval * 1000)
        self.root.after(drift_interval_ms, self._run_drift_check)
        self.root.after(int(UPDATE_CHECK_STARTUP_DELAY_SECONDS * 1000), self._run_scheduled_update_check)

        if self._auto_exit_after is not None:
            self.root.after(int(self._auto_exit_after * 1000), self.shutdown)
        try:
            self.root.mainloop()
        finally:
            self.logger.info("Backplane host mainloop exited")

    def shutdown(self, *_args) -> None:
        # May be called from the tray's own callback thread (a menu click)
        # or from the Tk thread (the self-test timer) -- guard against
        # double-invocation and never touch the Tk root except via after().
        if self._shutting_down:
            return
        self._shutting_down = True

        self.logger.info("Backplane host shutting down")
        for supervisor in self._supervisors.values():
            try:
                supervisor.stop()
            except Exception:
                self.logger.exception("Error stopping a plugin supervisor during shutdown")
        try:
            self.control_server.stop()
        except Exception:
            self.logger.exception("Error stopping control server during shutdown")
        try:
            self.hotkey_manager.stop()
        except Exception:
            self.logger.exception("Error stopping hotkey manager during shutdown")
        try:
            self.tray_model.stop()
        except Exception:
            self.logger.exception("Error stopping tray icon(s) during shutdown")

        if self._owns_root:
            self.root.after(0, self.root.destroy)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="backplane")
    parser.add_argument(
        "--self-test",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Auto-exit after N seconds. For smoke testing only.",
    )
    parser.add_argument("--log-path", type=Path, default=None)
    parser.add_argument("--tray-mode", choices=("separate", "combined"), default="separate")
    parser.add_argument("--data-dir", type=Path, default=None, help="Override the data directory (for testing).")
    parser.add_argument(
        "--control-pipe-address", default=None, help="Override the control pipe address (for testing)."
    )
    args = parser.parse_args(argv)

    host = HostProcess(
        log_path=args.log_path,
        auto_exit_after=args.self_test,
        tray_mode=args.tray_mode,
        data_dir=args.data_dir,
        control_pipe_address=args.control_pipe_address,
    )
    host.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
