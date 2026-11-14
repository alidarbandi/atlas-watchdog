"""Windows-backed, per-user Credential Manager secrets, or explicit session use.

Config contains references only. Generic credentials are limited to this app's
namespace, use CRED_PERSIST_LOCAL_MACHINE (same user on this PC), and are freed
deterministically. Session fallback never writes plaintext to disk.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
import threading


_PREFIX = "ATLASWatchdog/"
_TYPE_GENERIC = 1
_PERSIST_LOCAL_MACHINE = 2


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class SecretStore:
    def __init__(self):
        self._session: dict[str, str] = {}
        self._lock = threading.RLock()
        self._api = None
        self.available = False
        if os.name == "nt":
            try:
                self._api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
                credential_pointer = ctypes.POINTER(_Credential)
                self._api.CredWriteW.argtypes = [credential_pointer, wintypes.DWORD]
                self._api.CredWriteW.restype = wintypes.BOOL
                self._api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(credential_pointer)]
                self._api.CredReadW.restype = wintypes.BOOL
                self._api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
                self._api.CredDeleteW.restype = wintypes.BOOL
                self._api.CredFree.argtypes = [ctypes.c_void_p]
                self._api.CredFree.restype = None
                self.available = True
            except (OSError, AttributeError):
                self._api = None

    @staticmethod
    def _name(name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
            raise ValueError("Invalid app credential name.")
        return name

    def set(self, name: str, value: str, persistent: bool = True) -> str:
        name = self._name(name)
        if not value:
            raise ValueError("Credential cannot be empty; use Remove instead.")
        with self._lock:
            if persistent and self.available:
                data = value.encode("utf-16-le")
                # Documented Windows generic credential blob size limit.
                if len(data) > 2560:
                    raise ValueError("Credential exceeds Windows secure-store size limit.")
                buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
                credential = _Credential()
                credential.Type = _TYPE_GENERIC
                credential.TargetName = _PREFIX + name
                credential.UserName = "ATLAS Watchdog"
                credential.Persist = _PERSIST_LOCAL_MACHINE
                credential.CredentialBlobSize = len(data)
                credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
                if self._api.CredWriteW(ctypes.byref(credential), 0):
                    self._session.pop(name, None)
                    return "wincred:" + name
                # No secret or Windows error message is exposed. The returned
                # reference requires the UI to disclose session-only storage.
            self._session[name] = value
            return "session:" + name

    def get(self, reference: str) -> str:
        if not reference:
            return ""
        kind, _, name = reference.partition(":")
        self._name(name)
        with self._lock:
            if kind == "session":
                return self._session.get(name, "")
            if kind != "wincred" or not self.available:
                return ""
            pointer = ctypes.POINTER(_Credential)()
            if not self._api.CredReadW(_PREFIX + name, _TYPE_GENERIC, 0, ctypes.byref(pointer)):
                return ""
            try:
                credential = pointer.contents
                if credential.CredentialBlobSize > 2560:
                    return ""
                return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize).decode("utf-16-le")
            finally:
                self._api.CredFree(pointer)

    def delete(self, reference: str) -> None:
        if not reference:
            return
        kind, _, name = reference.partition(":")
        self._name(name)
        with self._lock:
            self._session.pop(name, None)
            if kind == "wincred" and self.available:
                if not self._api.CredDeleteW(_PREFIX + name, _TYPE_GENERIC, 0):
                    # Missing references are already removed. Other failures
                    # need a visible action and must not claim deletion worked.
                    code = ctypes.get_last_error()
                    if code != 1168:
                        raise RuntimeError("Windows could not remove this credential; use Credential Manager.")
