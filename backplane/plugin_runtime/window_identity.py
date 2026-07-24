"""Sets a plugin subprocess's Explicit AppUserModelID so Windows groups
every window that process opens -- one or several -- under one distinct
taskbar identity, rather than lumping them in with python.exe/pythonw.exe
or with each other's default identity.

This is the one piece of "multi-window support" that has to happen once,
centrally, regardless of how many windows a plugin ends up opening or what
toolkit it uses for them -- so it's applied automatically for every plugin
by plugin_runtime.loader rather than left for each plugin to remember.

Actual window creation, positioning, and count are entirely the plugin's
own business (it keeps whatever toolkit it already uses for its own
domain-specific windows) -- deliberately not building any host-side window
tracking/positioning here. A real multi-window plugin exercising this
during migration will tell us what, if anything, beyond taskbar identity
and the close-behavior setting (see subprocess_manager.py) is actually
needed, rather than guessing at an interface now.
"""

from __future__ import annotations

import ctypes

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long  # HRESULT


def set_app_user_model_id(plugin_name: str) -> None:
    app_id = f"SunlitLabs.Backplane.{plugin_name}"
    hresult = shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    if hresult != 0:
        raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed (HRESULT {hresult:#x})")
