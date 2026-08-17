"""单实例保护：通过 Windows 命名互斥锁阻止重复启动 App。"""
from __future__ import annotations

import os

_MUTEX_NAME = "Local\\HabitCheckin.SingleInstance"
_HANDLE = None


def acquire():
    """尝试获得单实例互斥锁；已存在实例时返回 False。"""
    global _HANDLE
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return True  # 无法创建时放行，避免误伤正常启动
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _HANDLE = handle
        return True
    except Exception:
        return True


def release():
    """关闭互斥锁句柄（进程退出时系统也会自动清理）。"""
    global _HANDLE
    if _HANDLE:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_HANDLE)
        except Exception:
            pass
        _HANDLE = None
