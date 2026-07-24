"""Secret storage via Windows Credential Manager -- direct ctypes against
CredWriteW/CredReadW/CredDeleteW, not ``keyring``.

~100 lines against one stable Win32 API beats pulling in keyring's much
larger dependency surface (multi-backend abstraction, backend
auto-detection) for a problem Backplane only ever needs to solve on one
platform. Only the host process calls these -- plugins reach secrets
exclusively through host.get_secret()/set_secret() over IPC.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from typing import Optional

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", wintypes.LPVOID),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)

advapi32.CredWriteW.argtypes = [_PCREDENTIALW, wintypes.DWORD]
advapi32.CredWriteW.restype = wintypes.BOOL

advapi32.CredReadW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(_PCREDENTIALW),
]
advapi32.CredReadW.restype = wintypes.BOOL

advapi32.CredFree.argtypes = [wintypes.LPVOID]
advapi32.CredFree.restype = None

advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
advapi32.CredDeleteW.restype = wintypes.BOOL


class SecretError(Exception):
    """A Credential Manager operation failed for a reason other than
    'not found' (which is represented as None/no-op instead)."""


def _target_name(namespace: str, key: str) -> str:
    return f"Sunlit Labs/Backplane/{namespace}/{key}"


def set_secret(namespace: str, key: str, value: str) -> None:
    target = _target_name(namespace, key)
    blob = value.encode("utf-16-le")
    blob_buf = ctypes.create_string_buffer(blob)  # +1 byte null terminator, unused; size below is exact

    cred = _CREDENTIALW()
    cred.Flags = 0
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = None
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = None

    ctypes.set_last_error(0)
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise SecretError(f"CredWriteW failed for {key!r} (Win32 error {ctypes.get_last_error()})")


def get_secret(namespace: str, key: str) -> Optional[str]:
    target = _target_name(namespace, key)
    pcred = _PCREDENTIALW()
    ctypes.set_last_error(0)
    if not advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        error_code = ctypes.get_last_error()
        if error_code == ERROR_NOT_FOUND:
            return None
        raise SecretError(f"CredReadW failed for {key!r} (Win32 error {error_code})")
    try:
        cred = pcred.contents
        size = cred.CredentialBlobSize
        if size == 0:
            return ""
        raw = ctypes.string_at(cred.CredentialBlob, size)
        return raw.decode("utf-16-le")
    finally:
        advapi32.CredFree(pcred)


def delete_secret(namespace: str, key: str) -> None:
    target = _target_name(namespace, key)
    ctypes.set_last_error(0)
    if not advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        error_code = ctypes.get_last_error()
        if error_code == ERROR_NOT_FOUND:
            return
        raise SecretError(f"CredDeleteW failed for {key!r} (Win32 error {error_code})")
