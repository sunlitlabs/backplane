"""Start Menu shortcut and run-on-startup registration.

.lnk creation itself is delegated to CreateShortcut.ps1 (a COM object,
not something Python's stdlib can write directly -- the same reasoning
already established across this tool ecosystem) via subprocess, always
invoked with -File on a real script on disk, never inline code. Startup
registration uses the HKCU Run key directly via stdlib winreg -- no
pywin32 dependency needed for a single registry value write/delete.
"""

from __future__ import annotations

import subprocess
import sys
import winreg
from pathlib import Path
from typing import Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"
_CREATE_SHORTCUT_SCRIPT = _SCRIPTS_DIR / "CreateShortcut.ps1"

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


class ShellIntegrationError(Exception):
    pass


def create_shortcut(
    shortcut_path: Path,
    target_path: str,
    arguments: str = "",
    working_directory: str = "",
    icon_location: str = "",
) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(_CREATE_SHORTCUT_SCRIPT),
        "-ShortcutPath",
        str(shortcut_path),
        "-TargetPath",
        target_path,
    ]
    if arguments:
        cmd += ["-Arguments", arguments]
    if working_directory:
        cmd += ["-WorkingDirectory", working_directory]
    if icon_location:
        cmd += ["-IconLocation", icon_location]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ShellIntegrationError(
            f"CreateShortcut.ps1 failed for {shortcut_path}: {result.stderr or result.stdout}"
        )


def remove_shortcut(shortcut_path: Path) -> None:
    try:
        shortcut_path.unlink()
    except FileNotFoundError:
        pass


def set_run_on_startup(name: str, command: str, enabled: bool) -> None:
    """Registers (or removes) a per-user HKCU Run key entry. Per-user, not
    HKLM -- consistent with the no-admin-rights rule everywhere else in
    this project; HKCU\\...\\Run needs no elevation."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def is_registered_for_startup(name: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, name)
            return True
    except FileNotFoundError:
        return False
