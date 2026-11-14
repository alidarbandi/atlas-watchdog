"""Short-lived, read-only source handles. Never uses directory metadata.

Sharing cannot override a producer denying readers, nor prevent an exclusive
producer reopen from conflicting while our (brief) handle is open.
"""
from __future__ import annotations

import ctypes
import os
from contextlib import AbstractContextManager
from pathlib import Path

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
FILE_SHARE_DELETE = 4
OPEN_EXISTING = 3

if os.name == "nt":
    from ctypes import wintypes

    class _FileInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.GetFileSizeEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong)]
    _kernel.GetFileSizeEx.restype = wintypes.BOOL
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                        ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
    _kernel.SetFilePointerEx.restype = wintypes.BOOL
    _kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _kernel.ReadFile.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL

    def _check(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())


class SharedFile(AbstractContextManager):
    """Only OPEN_EXISTING + GENERIC_READ; no locks, writes or mmap."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.handle = None
        self.size = 0
        self.identity = ""

    def __enter__(self):
        if os.name == "nt":
            handle = _kernel.CreateFileW(self.path, GENERIC_READ,
                                        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                        None, OPEN_EXISTING, 0, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = handle
            try:
                size = ctypes.c_longlong()
                _check(_kernel.GetFileSizeEx(handle, ctypes.byref(size)))
                info = _FileInfo()
                _check(_kernel.GetFileInformationByHandle(handle, ctypes.byref(info)))
                self.size = size.value
                self.identity = f"win:{info.volume}:{info.index_high}:{info.index_low}"
            except BaseException:
                self.close()
                raise
        else:
            self.handle = open(self.path, "rb", buffering=0)
            stat = os.fstat(self.handle.fileno())
            self.size = stat.st_size
            self.identity = f"posix:{stat.st_dev}:{stat.st_ino}"
        return self

    def read_at(self, offset: int, count: int) -> bytes:
        if offset < 0 or count < 0 or count > 4 * 1024 * 1024:
            raise ValueError("invalid bounded read")
        if not count:
            return b""
        if os.name == "nt":
            _check(_kernel.SetFilePointerEx(self.handle, offset, None, 0))
            data = ctypes.create_string_buffer(count)
            done = wintypes.DWORD()
            _check(_kernel.ReadFile(self.handle, data, count, ctypes.byref(done), None))
            return data.raw[:done.value]
        self.handle.seek(offset)
        return self.handle.read(count)

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            if os.name == "nt":
                _kernel.CloseHandle(handle)
            else:
                handle.close()

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False
