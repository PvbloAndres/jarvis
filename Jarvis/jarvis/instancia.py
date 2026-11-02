"""Evita que haya dos Jarvis a la vez (dos micrófonos escuchando, dos bots de Telegram...)."""
from __future__ import annotations

import sys

_handles: list = []


def single_instance(name: str) -> bool:
    """True si somos la única instancia con ese nombre. El candado dura mientras viva el proceso."""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    handle = k32.CreateMutexW(None, False, f"Local\\JARVIS_{name}")
    if ctypes.get_last_error() == 183:        # ERROR_ALREADY_EXISTS
        k32.CloseHandle(handle)
        return False
    _handles.append(handle)
    return True
