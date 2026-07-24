"""The Backplane host process: owns the Tk mainloop, tray icon, and crash
logging.

Phase 0 scope only: a withdrawn Tk root, one tray icon with an Exit item,
and crash logging wired to both. Later phases add hotkeys (Phase 1), plugin
subprocesses/IPC (Phase 2), settings (Phase 3), the registry (Phase 6), and
the updater (Phase 7) on top of this skeleton -- nothing here should need to
change shape as those land, only grow.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tkinter as tk
from pathlib import Path
from typing import Optional

from backplane.host.crash_log import setup_crash_logging, tk_report_callback_exception
from backplane.host.tray_model import PluginTrayInfo, TrayModel

APP_NAME = "Backplane"
PUBLISHER = "Sunlit Labs"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / PUBLISHER / APP_NAME


def default_log_path() -> Path:
    return default_data_dir() / "logs" / "backplane.log"


class HostProcess:
    """Owns the process's Tk mainloop and tray icon.

    ``auto_exit_after`` exists purely for smoke-testing this phase from a
    non-interactive shell -- never set it in real operation.
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        auto_exit_after: Optional[float] = None,
        tray_mode: str = "separate",
    ):
        self.logger: logging.Logger = setup_crash_logging(log_path or default_log_path())
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = tk_report_callback_exception(  # type: ignore[assignment]
            self.logger
        )

        # TrayModel governs every registered plugin's tray presence (Phase 6's
        # registry registers real plugins into it); Backplane registers
        # itself as a baseline entry so there's always at least one icon
        # (with an Exit item) even before any plugin is registered.
        self.tray_model = TrayModel(mode=tray_mode, on_exit=self.shutdown)
        self.tray_model.register_plugin(PluginTrayInfo(name="__host__", display_name=APP_NAME))

        self._auto_exit_after = auto_exit_after
        self._shutting_down = False

    def start(self) -> None:
        self.logger.info("Backplane host starting (pid=%s)", os.getpid())
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
        try:
            self.tray_model.stop()
        except Exception:
            self.logger.exception("Error stopping tray icon(s) during shutdown")

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
    args = parser.parse_args(argv)

    host = HostProcess(log_path=args.log_path, auto_exit_after=args.self_test, tray_mode=args.tray_mode)
    host.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
