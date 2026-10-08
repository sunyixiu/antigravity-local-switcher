"""Small Windows-native dialogs; no Python GUI runtime required."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path

from local_switcher import system_dll


def show_error(message):
    user = system_dll("user32.dll")
    user.MessageBoxW.argtypes = [W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT]
    user.MessageBoxW.restype = C.c_int
    user.MessageBoxW(None, message, "Antigravity 本地账号切换器", 0x10)


class UpgradeProgress:
    def __init__(self):
        self.user = system_dll("user32.dll")
        api = self.user
        api.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
        api.CreateWindowExW.restype = W.HWND
        api.GetSystemMetrics.argtypes = [C.c_int]
        api.GetSystemMetrics.restype = C.c_int
        api.DestroyWindow.argtypes = [W.HWND]
        api.DestroyWindow.restype = W.BOOL
        api.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
        api.PeekMessageW.restype = W.BOOL
        api.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
        api.TranslateMessage.restype = W.BOOL
        api.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
        api.DispatchMessageW.restype = C.c_ssize_t
        api.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        api.SendMessageW.restype = C.c_ssize_t
        api.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
        api.LoadImageW.restype = W.HANDLE
        width, height = 490, 155
        x = max(0, (api.GetSystemMetrics(0) - width) // 2)
        y = max(0, (api.GetSystemMetrics(1) - height) // 2)
        self.hwnd = api.CreateWindowExW(0x00040000, "STATIC", "正在更新本地账号工具", 0x10C00000, x, y, width, height, None, None, None, None)
        if not self.hwnd:
            return
        gdi = system_dll("gdi32.dll")
        gdi.GetStockObject.argtypes = [C.c_int]
        gdi.GetStockObject.restype = W.HANDLE
        font = gdi.GetStockObject(17)
        for text, top in [("旧后台正在完成操作，完成后会自动更新。", 24), ("账号快照会保留；Antigravity 客户端继续运行。", 57)]:
            child = api.CreateWindowExW(0, "STATIC", text, 0x50000000, 24, top, 440, 28, self.hwnd, None, None, None)
            if child:
                api.SendMessageW(child, 0x0030, int(font or 0), 1)
        self.icons = []
        icon_path = Path(__file__).parent / "assets" / "app-icon.ico"
        for kind, size in [(0, 32), (1, 256)]:
            handle = api.LoadImageW(None, str(icon_path), 1, size, size, 0x10)
            if handle:
                self.icons.append(handle)
                api.SendMessageW(self.hwnd, 0x0080, kind, int(handle))
        self.pump()

    def pump(self):
        if not self.hwnd:
            return
        message = W.MSG()
        while self.user.PeekMessageW(C.byref(message), self.hwnd, 0, 0, 1):
            self.user.TranslateMessage(C.byref(message))
            self.user.DispatchMessageW(C.byref(message))

    def close(self):
        if self.hwnd:
            self.user.DestroyWindow(self.hwnd)
            self.hwnd = None
            self.user.DestroyIcon.argtypes = [W.HANDLE]
            self.user.DestroyIcon.restype = W.BOOL
            for icon in self.icons:
                self.user.DestroyIcon(icon)
