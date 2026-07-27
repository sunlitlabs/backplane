"""Global hotkey registration via raw Win32 RegisterHotKey.

Deliberately NOT built on ``keyboard``/``pynput``: both implement hotkeys
via a low-level keyboard hook (SetWindowsHookEx(WH_KEYBOARD_LL)), which
never actually "registers" anything with Windows -- two apps hooking the
same combo simply both receive every keystroke and pattern-match locally,
with no OS-level conflict signal at all. RegisterHotKey is the only
mechanism that gives a synchronous, reliable answer to "is this combo
already taken," which is exactly what Backplane's conflict-detection
requirement needs -- and it fails the same way (ERROR_HOTKEY_ALREADY_
REGISTERED) whether the other owner is another Backplane-hosted plugin or a
completely unrelated application, since Windows tracks a registered combo
system-wide, not per-window.

All RegisterHotKey/UnregisterHotKey calls happen on one dedicated
message-pump thread, since a hotkey registration is thread-affine to the
thread that made it and WM_HOTKEY is delivered to that same thread's queue.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODIFIER_NAMES = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
}

_VK_NAMES: Dict[str, int] = {}
for _i, _ch in enumerate("0123456789"):
    _VK_NAMES[_ch] = 0x30 + _i
for _i, _ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _VK_NAMES[_ch] = 0x41 + _i
for _i in range(1, 25):
    _VK_NAMES[f"f{_i}"] = 0x70 + (_i - 1)
_VK_NAMES.update(
    {
        "space": 0x20,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "esc": 0x1B,
        "escape": 0x1B,
        "backspace": 0x08,
        "delete": 0x2E,
        "del": 0x2E,
        "insert": 0x2D,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
    }
)

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


# Explicit argtypes/restype on every function that returns or takes a
# handle/pointer -- ctypes defaults to c_int for undeclared return types,
# which silently truncates 64-bit HWNDs on 64-bit Windows. Getting this
# wrong here would be a real, hard-to-notice corruption bug.
user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND

user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_long

user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL

user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_long

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wintypes.BOOL

user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class HotkeyError(Exception):
    """Base class for hotkey registration problems."""


class HotkeyConflictError(HotkeyError):
    """A combo is already registered -- either in-process (``owner`` names
    the existing claimant) or by some other application on the system
    (``owner`` is ``None``, discovered via Win32's own registration
    failure)."""

    def __init__(self, combo: str, owner: Optional[str] = None):
        self.combo = combo
        self.owner = owner
        if owner:
            super().__init__(f"Hotkey {combo!r} is already registered to {owner!r}")
        else:
            super().__init__(f"Hotkey {combo!r} is already registered by another application")


class HotkeyParseError(HotkeyError):
    """A combo string couldn't be parsed into modifiers + a key."""


def parse_combo(combo: str) -> Tuple[int, int]:
    """Parse a combo like 'ctrl+alt+t' into (modifiers, virtual_key).
    Requires at least one modifier and exactly one non-modifier key."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if len(parts) < 2:
        raise HotkeyParseError(f"Hotkey {combo!r} needs at least one modifier and one key")

    modifiers = 0
    key_parts = []
    for part in parts:
        if part in _MODIFIER_NAMES:
            modifiers |= _MODIFIER_NAMES[part]
        else:
            key_parts.append(part)

    if modifiers == 0:
        raise HotkeyParseError(f"Hotkey {combo!r} needs at least one modifier")
    if len(key_parts) != 1:
        raise HotkeyParseError(f"Hotkey {combo!r} needs exactly one non-modifier key")

    key_name = key_parts[0]
    if key_name not in _VK_NAMES:
        raise HotkeyParseError(f"Unknown key {key_name!r} in hotkey {combo!r}")

    return modifiers | MOD_NOREPEAT, _VK_NAMES[key_name]


def normalize_combo(combo: str) -> str:
    parts = sorted(p.strip().lower() for p in combo.split("+") if p.strip())
    return "+".join(parts)


@dataclass
class _Registration:
    hotkey_id: int
    combo: str
    owner: str
    callback: Callable[[], None]


class HotkeyManager:
    """Owns a hidden window + dedicated message-pump thread.

    Hotkey callbacks (and the internal register/unregister marshaling) run
    on that thread. Callers that need to touch Tk or another
    single-threaded resource from a callback must marshal onto their own
    thread themselves (e.g. via ``root.after(0, ...)``) -- this class never
    assumes what's on the other end of a callback.
    """

    def __init__(self) -> None:
        # Unique per instance: window classes are registered process-wide,
        # so a fixed name would collide (RegisterClassW error 1410) if more
        # than one HotkeyManager is ever created in the same process -- as
        # every test in this file that spins up its own manager does, and
        # as a future restart-after-stop of the production instance would.
        self._class_name = f"BackplaneHotkeyWindow-{uuid.uuid4().hex[:12]}"
        self._registrations: Dict[int, _Registration] = {}
        self._combo_to_id: Dict[str, int] = {}
        self._next_id = 1
        self._lock = threading.Lock()

        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._wndproc_ref = WNDPROC(self._wndproc)  # keep alive: ctypes holds no reference
        self._command_queue: "queue.Queue" = queue.Queue()
        self._pending_results: Dict[int, "queue.Queue"] = {}
        self._pending_lock = threading.Lock()
        self._pending_counter = 0

    # -- public API -------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="backplane-hotkeys", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise HotkeyError("Hotkey message-pump thread failed to start")

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=5)

    def register(self, combo: str, owner: str, callback: Callable[[], None]) -> int:
        """Register ``combo`` for ``owner`` (a plugin name, used only for a
        clear conflict message). Raises HotkeyConflictError if the combo is
        already claimed -- in-process or by the OS. Returns an opaque id
        usable with unregister()."""
        modifiers, vk = parse_combo(combo)
        normalized = normalize_combo(combo)

        with self._lock:
            if normalized in self._combo_to_id:
                existing = self._registrations[self._combo_to_id[normalized]]
                raise HotkeyConflictError(combo, owner=existing.owner)
            hotkey_id = self._next_id
            self._next_id += 1

        ok, error_code = self._call_on_pump_thread("register", hotkey_id, modifiers, vk)
        if not ok:
            if error_code == ERROR_HOTKEY_ALREADY_REGISTERED:
                raise HotkeyConflictError(combo, owner=None)
            raise HotkeyError(f"RegisterHotKey failed for {combo!r} (Win32 error {error_code})")

        with self._lock:
            self._registrations[hotkey_id] = _Registration(hotkey_id, normalized, owner, callback)
            self._combo_to_id[normalized] = hotkey_id
        return hotkey_id

    def unregister(self, hotkey_id: int) -> None:
        with self._lock:
            reg = self._registrations.pop(hotkey_id, None)
            if reg is not None:
                self._combo_to_id.pop(reg.combo, None)
        self._call_on_pump_thread("unregister", hotkey_id)

    def unregister_all_for_owner(self, owner: str) -> None:
        """Used by the canonical uninstall routine (registry.py) -- a
        plugin being uninstalled must not leave any of its hotkeys
        registered, freeing those combos for reuse immediately."""
        with self._lock:
            ids = [hid for hid, reg in self._registrations.items() if reg.owner == owner]
        for hotkey_id in ids:
            self.unregister(hotkey_id)

    def get_owner_of(self, combo: str) -> Optional[str]:
        """Used for live conflict feedback in a settings/capture UI --
        checking without attempting a real registration. Returns None if
        the combo is free (as far as in-process bookkeeping knows; an
        OS-level conflict with another application is only ever caught by
        actually registering)."""
        normalized = normalize_combo(combo)
        with self._lock:
            hotkey_id = self._combo_to_id.get(normalized)
            if hotkey_id is None:
                return None
            reg = self._registrations.get(hotkey_id)
            return reg.owner if reg else None

    # -- internals --------------------------------------------------------

    def _call_on_pump_thread(self, action: str, *args) -> tuple:
        """Marshal a register/unregister call onto the message-pump thread
        (RegisterHotKey's registration is thread-affine) and block for the
        result."""
        with self._pending_lock:
            self._pending_counter += 1
            token = self._pending_counter
            result_q: "queue.Queue" = queue.Queue(maxsize=1)
            self._pending_results[token] = result_q

        self._command_queue.put((token, action, args))
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_APP, token, 0)

        result = result_q.get(timeout=5)
        with self._pending_lock:
            self._pending_results.pop(token, None)
        return result

    def _run(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)

        wc = _WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinstance
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self._class_name

        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise HotkeyError(f"RegisterClassW failed (Win32 error {ctypes.get_last_error()})")

        self._hwnd = user32.CreateWindowExW(
            0, self._class_name, "Backplane Hotkey Window", 0, 0, 0, 0, 0, None, None, hinstance, None
        )
        if not self._hwnd:
            raise HotkeyError(f"CreateWindowExW failed (Win32 error {ctypes.get_last_error()})")

        self._ready.set()

        msg = wintypes.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_APP:
            token = wparam
            _, action, args = self._command_queue.get()
            result = self._handle_command(action, args)
            with self._pending_lock:
                result_q = self._pending_results.get(token)
            if result_q:
                result_q.put(result)
            return 0
        if msg == WM_HOTKEY:
            hotkey_id = wparam
            with self._lock:
                reg = self._registrations.get(hotkey_id)
            if reg:
                # Enqueue-and-return-immediately: never block the message
                # pump on the callback itself, so a slow/hung callback for
                # one plugin can never delay another plugin's hotkey.
                threading.Thread(target=reg.callback, daemon=True).start()
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _handle_command(self, action: str, args: tuple) -> tuple:
        if action == "register":
            hotkey_id, modifiers, vk = args
            ctypes.set_last_error(0)
            ok = bool(user32.RegisterHotKey(self._hwnd, hotkey_id, modifiers, vk))
            error_code = 0 if ok else ctypes.get_last_error()
            return (ok, error_code)
        if action == "unregister":
            (hotkey_id,) = args
            user32.UnregisterHotKey(self._hwnd, hotkey_id)
            return (True, 0)
        return (False, -1)
