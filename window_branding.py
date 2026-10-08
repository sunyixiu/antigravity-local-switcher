"""Use the bundled icon for this local page's Windows Edge app window."""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import time


# Shared LoadImage handles are intentionally retained for the lifetime of this process.
_icons = []


def brand_edge_window(url, icon_path):
    try:
        if os.name != "nt" or not icon_path.is_file():
            return
        root = Path(os.environ["SystemRoot"]) / "System32"
        user = C.WinDLL(str(root / "user32.dll"), use_last_error=True)
        kernel = C.WinDLL(str(root / "kernel32.dll"), use_last_error=True)
        callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        user.EnumWindows.argtypes = [callback_type, W.LPARAM]
        user.EnumWindows.restype = W.BOOL
        user.GetWindowTextLengthW.argtypes = [W.HWND]
        user.GetWindowTextLengthW.restype = C.c_int
        user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        user.GetWindowTextW.restype = C.c_int
        user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        user.GetWindowThreadProcessId.restype = W.DWORD
        user.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
        user.LoadImageW.restype = W.HANDLE
        user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, C.POINTER(C.c_size_t)]
        user.SendMessageTimeoutW.restype = C.c_ssize_t
        kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        kernel.OpenProcess.restype = W.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = W.BOOL
        kernel.CloseHandle.argtypes = [W.HANDLE]
        kernel.CloseHandle.restype = W.BOOL
        handles = [user.LoadImageW(None, str(icon_path.resolve()), 1, size, size, 0x10 | 0x8000) for size in (32, 256)]
        if not all(handles):
            return
        _icons.extend(handles)
        # The local page puts its ephemeral port in the title. Other Edge tabs with
        # the same product name are not selected, and only verified Edge processes qualify.
        port = url.rsplit(":", 1)[-1].strip("/")
        marker = "AGLOCAL:" + port
        matched = set()

        @callback_type
        def visit(hwnd, _):
            length = user.GetWindowTextLengthW(hwnd)
            if not 0 < length <= 2048 or hwnd in matched:
                return True
            title = C.create_unicode_buffer(length + 1)
            user.GetWindowTextW(hwnd, title, length + 1)
            if marker not in title.value or "本地账号切换器" not in title.value:
                return True
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            process = kernel.OpenProcess(0x1000, False, pid.value)
            if not process:
                return True
            try:
                path = C.create_unicode_buffer(32768)
                size = W.DWORD(len(path))
                if not kernel.QueryFullProcessImageNameW(process, 0, path, C.byref(size)) or Path(path.value).name.casefold() != "msedge.exe":
                    return True
            finally:
                kernel.CloseHandle(process)
            for kind, handle in enumerate(handles):
                output = C.c_size_t()
                user.SendMessageTimeoutW(hwnd, 0x0080, kind, int(handle), 2, 500, C.byref(output))  # WM_SETICON
            matched.add(hwnd)
            return True

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            user.EnumWindows(visit, 0)
            if matched:
                return
            time.sleep(.5)
    except (OSError, ValueError, TypeError, AttributeError):
        # Optional window decoration must never block account operations.
        return
