"""Toolkit-agnostic single-instance guard via a named Win32 mutex.

Independent of whatever GUI toolkit a plugin uses (Tk, Qt, none at all),
and independent of the host's own process-tracking bookkeeping -- a second
real launch attempt (an orphaned subprocess surviving a host crash/restart,
a user double-clicking a smart-launcher stub twice) is caught at the OS
level rather than relying on Backplane's own state being perfectly
accurate.

Session-local (no "Global\\" namespace prefix): every target scenario here
is a single interactive desktop user, not a multi-session terminal-services
host, and the plain session namespace needs no special privilege --
"Global\\" mutexes can fail under SeCreateGlobalPrivilege restrictions in a
locked-down environment for no benefit we actually need.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE

kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard:
    """Acquire with a unique key (typically a plugin name, optionally
    suffixed with an instance identifier such as a data-folder hash for a
    plugin that supports multiple concurrent named instances).

    ``acquired`` is True only if this call is the first to successfully
    claim the key anywhere on the system; a second acquire attempt with the
    same key -- from this process or another -- sees ``acquired is False``
    and should not proceed with whatever it was guarding.
    """

    def __init__(self, key: str):
        self._mutex_name = f"SunlitLabs.Backplane.{key}"
        self._handle: int = 0
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, True, self._mutex_name)
        if not handle:
            raise OSError(f"CreateMutexW failed (Win32 error {ctypes.get_last_error()})")
        self._handle = handle
        self.acquired = ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            try:
                kernel32.ReleaseMutex(self._handle)
            except Exception:
                pass
            kernel32.CloseHandle(self._handle)
            self._handle = 0

    def __enter__(self) -> "SingleInstanceGuard":
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
