"""Exercise frozen dependencies and bundled files using synthetic accounts only."""
import ctypes as C
import http.client
import json
from pathlib import Path
import sys
import threading


def check(destination):
    import desktop_ui
    import local_switcher
    import auto_refresh
    import instance_control
    import refresh_policy
    import window_branding
    import native_dialog

    results = {"frozen": bool(getattr(sys, "frozen", False)), "version": desktop_ui.VERSION, "checks": []}
    server = None
    worker = None
    try:
        root = Path(__file__).parent
        for name in ["ui.html", "assets/google.svg", "assets/app-icon.ico", "assets/app-icon.png", "assets/SVG-Logos-LICENSE.txt"]:
            asset = root / name
            if not asset.is_file() or asset.stat().st_size == 0:
                raise RuntimeError("Bundled file missing: " + name)
            results["checks"].append("bundled:" + name)
        results["checks"].append("native-dialog-import")
        # Validate the packaged transparent ICO with the native loader, without showing a window.
        user = local_switcher.system_dll("user32.dll")
        user.LoadImageW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_uint, C.c_int, C.c_int, C.c_uint]
        user.LoadImageW.restype = C.c_void_p
        user.DestroyIcon.argtypes = [C.c_void_p]
        handle = user.LoadImageW(None, str(root / "assets/app-icon.ico"), 1, 32, 32, 0x10)
        if not handle:
            raise RuntimeError("Native icon loading failed")
        user.DestroyIcon(handle)
        results["checks"].append("native-icon")
        server = desktop_ui.create_server(demo=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        for path in ["/", "/assets/google.svg", "/favicon.ico", "/assets/app-icon.png", "/api/state"]:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", path, headers={"Cookie": server.cookie_name + "=" + server.secret, "X-Local-Switcher": server.secret})
            response = connection.getresponse()
            body = response.read()
            connection.close()
            if response.status != 200:
                raise RuntimeError("Packaged route failed: " + path)
            if path == "/api/state":
                state = json.loads(body)
                if len(state["profiles"]) != 4 or not state["demo"] or "refresh_token" in body.decode():
                    raise RuntimeError("Synthetic state check failed")
            results["checks"].append("route:" + path)
        results["ok"] = True
    except Exception as error:
        results["ok"] = False
        results["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if worker:
            worker.join(timeout=2)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if not results["ok"]:
        raise SystemExit(2)
