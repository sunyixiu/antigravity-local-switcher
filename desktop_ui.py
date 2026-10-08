"""Loopback-only desktop UI; credentials remain in the native Python backend."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import faulthandler
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
import uuid
import webbrowser

import local_switcher as core
import quota
import refresh_policy
import auto_refresh
import instance_control
import account_discovery

VERSION = "0.7"


def demo_state():
    now = time.time()
    entries = []
    for index, (label, values) in enumerate([
        ("工作账号", [6, 28, 16, 100]), ("备用账号 A", [82, 100, 65, 100]),
        ("备用账号 B", [45, 71, 0, 12]), ("备用账号 C", [100, 100, 100, 100]),
    ]):
        groups = []
        for (family, window), percentage in zip([("gemini", "weekly"), ("gemini", "5h"), ("thirdparty", "weekly"), ("thirdparty", "5h")], values):
            duration = (172800 if family == "gemini" else 302400) if window == "weekly" else 6240
            groups.append({"family": family, "window": window, "percentage": percentage, "reset": quota.datetime.fromtimestamp(now + duration, quota.timezone.utc).isoformat(), "group": family, "id": family + window, "name": window})
        entries.append({"id": f"{index + 1:032x}.agprofile", "label": label, "recent": index == 0,
                        "quota": {"groups": groups, "models": [], "updated": now, "status": "已更新"}})
    # One expired demo window illustrates pending confirmation, without claiming a full reset.
    entries[0]["quota"]["updated"] = now - 120
    entries[0]["quota"]["groups"][1]["reset"] = quota.datetime.fromtimestamp(now - 30, quota.timezone.utc).isoformat()
    return {"version": VERSION, "demo": True, "busy": False, "progress": "", "profiles": entries,
            "auto_refresh_hours": 4, "next_auto_at": now + 4 * 3600, "cooldown_remaining": 0}


class Application:
    def __init__(self, demo=False, directory=None, store=None, request_sender=None, clock=None, wait=None, wall_clock=None):
        self.demo = demo
        self.lock = threading.RLock()
        self.busy = False
        self.progress = ""
        self.last_seen = time.monotonic()
        self.shutdown_requested = False
        self.server = None
        self.preview = demo_state() if demo else None
        self.clock = clock if clock is not None else time.monotonic
        self.wait = wait if wait is not None else time.sleep
        self.wall_clock = wall_clock if wall_clock is not None else time.time
        self.requests = refresh_policy.RequestGate(request_sender, self.clock, self.wait)
        self.last_attempt = {}
        self.refreshing_ids = []
        self.active_refresh_id = None
        if not demo:
            self.directory = Path(directory) if directory is not None else Path(os.environ["LOCALAPPDATA"]) / "AntigravityLocalSwitcher"
            self.vault = core.Vault(self.directory)
            self.store = store if store is not None else core.NativeStore()
            self.switcher = core.Switcher(self.store, self.vault)
            self.discovery = account_discovery.Discovery(self.store, self.vault, self.requests.send, self.clock)
            self.auto = auto_refresh.Plan(self.directory, self.wall_clock)
            self.requests.cooldown_until = self.clock() + max(0, self.auto.cooldown_until - self.wall_clock())
            if self.auto.error:
                self.progress = self.auto.error

    def seen(self):
        with self.lock:
            self.last_seen = time.monotonic()

    def should_stop(self):
        with self.lock:
            return self.shutdown_requested and not self.busy

    def diagnose(self, event, error=None):
        if self.demo:
            return
        # Intentionally omit labels, IDs, tokens, request bodies and error messages.
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
        if error is not None:
            row["kind"] = type(error).__name__
            if isinstance(error, core.NativeError):
                row["system_code"] = error.code
        try:
            path = self.directory / "diagnostics.log"
            if not path.exists() or path.stat().st_size < 1_000_000:
                with path.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(row) + "\n")
        except OSError:
            pass

    def state(self):
        with self.lock:
            if self.demo:
                return self.preview
            profiles = []
            for filename, label in self.vault.profiles():
                if not re.fullmatch(r"[0-9a-f]{32}\.agprofile", filename):
                    continue
                cache = self.cached(filename)
                profiles.append({"id": filename, "label": label, "recent": self.switcher.active == filename, "quota": cache,
                                 "refresh_after": self.account_cooldown(filename)})
            return {"version": VERSION, "demo": False, "busy": self.busy, "progress": self.progress, "profiles": profiles,
                    "refreshing_ids": list(self.refreshing_ids), "active_refresh_id": self.active_refresh_id,
                    "cooldown_remaining": self.requests.remaining(), "auto_refresh_hours": self.auto.hours,
                    "next_auto_at": self.auto.next_run, "scan": dict(self.discovery.view)}

    def account_cooldown(self, filename):
        attempted = self.last_attempt.get(filename)
        return max(0, math.ceil(refresh_policy.ACCOUNT_COOLDOWN - (self.clock() - attempted))) if attempted is not None else 0

    def cached(self, filename):
        try:
            value = self.vault.read(filename + ".quota")
            return value if isinstance(value, dict) else {}
        except (core.LocalError, OSError):
            return {}

    def selected(self, filename):
        if not isinstance(filename, str) or not re.fullmatch(r"[0-9a-f]{32}\.agprofile", filename):
            raise core.LocalError("请先选择一个有效账号。")
        return self.vault.load(filename)

    def action(self, action, payload):
        with self.lock:
            if action == "quit":
                if self.busy:
                    raise core.LocalError("当前操作尚未完成，请完成后再退出工具。")
                self.shutdown_requested = True
                self.diagnose("app.quit_requested")
                return "工具已退出。需要使用时重新打开 Start.cmd。"
            if self.demo:
                raise core.LocalError("这是界面预览，未接入真实账号。")
            if self.busy:
                raise core.LocalError("当前操作尚未完成，请稍候。")
            if action == "scan":
                if self.requests.remaining():
                    raise core.LocalError("Google 查询正在冷却，请稍后再扫描。")
                self.busy = True
                self.progress = "正在扫描 Antigravity 当前登录账号…"
                self.discovery.view = {"status": "scanning", "message": self.progress}
                threading.Thread(target=self.scan_current, daemon=True).start()
                return "已开始扫描当前登录。"
            if action == "add-discovered":
                filename = self.discovery.confirm(payload.get("scan_id"), payload.get("label"), payload.get("request_id"))
                self.switcher.active = filename
                self.progress = self.discovery.view["message"]
                self.diagnose("account.discovery_saved")
                return "新账号已命名入库。"
            if action == "rename":
                filename = payload.get("id")
                saved = self.selected(filename)
                label = payload.get("label")
                if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or any(ord(char) < 32 for char in label):
                    raise core.LocalError("账号名称需要 1 到 80 个可见字符。")
                label = label.strip()
                if label == saved["label"]:
                    return "账号名称未改变。"
                self.vault.save(label, saved["credential"], filename)
                self.diagnose("account.renamed")
                return "账号已重命名，登录快照和额度记录已保留。"
            if action == "auto-refresh":
                self.auto.configure(payload.get("hours"))
                return "自动查询已关闭；仍可手动刷新。" if not self.auto.hours else f"已设置每 {self.auto.hours} 小时自动查询，重置到期后也会排队确认。"
            if action in ("refresh", "refresh-one"):
                cooldown = self.requests.remaining()
                if cooldown:
                    raise core.LocalError(f"Google 查询正在冷却，请 {cooldown} 秒后再刷新。")
                if action == "refresh-one":
                    self.selected(payload.get("id"))
                    filenames = [payload["id"]]
                else:
                    filenames = [filename for filename, _ in self.vault.profiles() if re.fullmatch(r"[0-9a-f]{32}\.agprofile", filename)]
                if not filenames:
                    raise core.LocalError("请先保存至少一个账号。")
                eligible = [filename for filename in filenames if self.account_cooldown(filename) == 0]
                skipped = len(filenames) - len(eligible)
                if not eligible:
                    remaining = min(self.account_cooldown(filename) for filename in filenames)
                    raise core.LocalError(f"这些账号刚刷新过，请 {remaining} 秒后再刷新。")
                self.start_refresh(eligible, skipped)
                return "已开始刷新这个账号的额度。" if action == "refresh-one" else "已开始逐个刷新账号；近期已查询的账号保留缓存。"
            if action in ("save", "update"):
                filename = payload.get("id") if action == "update" else None
                request_id = payload.get("request_id") if action == "save" else None
                if request_id is not None:
                    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", request_id):
                        raise core.LocalError("保存请求标识无效，请重新打开保存窗口。")
                    filename = uuid.UUID(request_id).hex + ".agprofile"
                    if (self.directory / filename).exists():
                        self.selected(filename)
                        return "这次保存已完成，账号快照已经在列表中。"
                saved = self.selected(filename) if action == "update" else None
                label = saved["label"] if saved else payload.get("label")
                if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
                    raise core.LocalError("账号名称需要 1 到 80 个字符。")
                self.diagnose("account.capture_started")
                try:
                    record = self.store.read()
                    self.diagnose("account.native_read_complete")
                    if not record:
                        raise core.LocalError("请先在 Antigravity 官方客户端完成 Google 登录。")
                    self.switcher.active = self.vault.save(label.strip(), record, filename)
                    self.diagnose("account.capture_complete")
                except Exception as error:
                    self.diagnose("account.capture_failed", error)
                    raise
                if filename:
                    (self.directory / (filename + ".quota")).unlink(missing_ok=True)
                return "当前登录账号已加密保存。"
            if action not in ("switch", "restore"):
                raise core.LocalError("不支持的操作。")
            if action == "switch":
                self.selected(payload.get("id"))
            self.busy = True
            self.progress = "正在请求 Antigravity 正常退出并切换账号…"
        try:
            if action == "switch":
                self.switcher.switch(payload["id"])
            else:
                if not (self.directory / "before-switch.agrecovery").exists():
                    raise core.LocalError("还没有切换前的恢复快照。")
                self.switcher.restore()
            return "本地凭据已切换，Antigravity 已启动。请在客户端确认账号。"
        finally:
            with self.lock:
                self.busy = False
                self.progress = ""

    def start_refresh(self, filenames, skipped=0, reason="手动刷新"):
        # Caller owns self.lock; every source shares one serialized refresh job.
        self.busy = True
        self.refreshing_ids = list(filenames)
        self.progress = reason + "：正在按顺序查询额度…"
        threading.Thread(target=self.refresh_all, args=(filenames, skipped), daemon=True).start()

    def scan_current(self):
        try:
            # Keep native credentials and network responses in the backend; the UI
            # receives only a bounded identity view and a short-lived scan ID.
            self.discovery.scan()
        except (core.LocalError, quota.QuotaError) as error:
            self.discovery.pending = None
            self.discovery.view = {"status": "error", "message": str(error)}
            self.discovery.last_scan = self.clock()
            self.diagnose("account.scan_failed", error)
        except Exception as error:
            self.discovery.pending = None
            self.discovery.view = {"status": "error", "message": "无法确认当前登录，请检查 Antigravity 登录状态后重新扫描。"}
            self.discovery.last_scan = self.clock()
            self.diagnose("account.scan_failed", error)
        finally:
            with self.lock:
                self.busy = False
                self.progress = self.discovery.view.get("message", "扫描完成。")

    def scheduler_tick(self):
        with self.lock:
            if self.demo or self.shutdown_requested or self.busy or not self.auto.hours or self.requests.remaining():
                return
            filenames = [filename for filename, _ in self.vault.profiles() if re.fullmatch(r"[0-9a-f]{32}\.agprofile", filename)
                         and not self.cached(filename).get("auto_paused")]
            periodic = self.wall_clock() >= self.auto.next_run
            if periodic:
                # Sleep/resume or a restart catches up once, rather than replaying every missed interval.
                self.auto.next_run = self.wall_clock() + self.auto.hours * 3600
                self.auto.save()
                wanted = filenames
            else:
                wanted = [filename for filename in filenames if self.auto.due_keys(filename, self.cached(filename))]
            eligible = [filename for filename in wanted if self.account_cooldown(filename) == 0]
            if eligible:
                self.start_refresh(eligible, len(wanted) - len(eligible), "定时自动查询" if periodic else "重置到期确认")

    def refresh_all(self, filenames, skipped=0):
        completed = 0
        throttled = False
        try:
            for index, filename in enumerate(filenames):
                if index:
                    with self.lock:
                        self.active_refresh_id = None
                        self.progress = f"账号之间间隔 {int(refresh_policy.ACCOUNT_INTERVAL)} 秒，稍后查询下一个…"
                    self.wait(refresh_policy.ACCOUNT_INTERVAL)
                with self.lock:
                    self.progress = f"正在查询账号 {index + 1} / {len(filenames)}…"
                    self.active_refresh_id = filename
                    self.last_attempt[filename] = self.clock()
                    try:
                        self.auto.mark_attempt(filename, self.cached(filename))
                    except core.LocalError:
                        self.diagnose("schedule.preference_write_failed")
                try:
                    with self.lock:
                        saved = self.selected(filename)
                    def renewed(record):
                        with self.lock:
                            self.vault.save(saved["label"], record, filename, identity=saved.get("identity"))
                    result = quota.query(saved["credential"], request=self.requests.send, on_renew=renewed)
                    with self.lock:
                        self.vault.write(filename + ".quota", result)
                    completed += 1
                except (core.LocalError, quota.QuotaError, OSError) as error:
                    with self.lock:
                        previous = self.cached(filename)
                        previous["status"] = "查询失败；旧数据" if previous.get("models") or previous.get("groups") else "查询失败"
                        previous["error"] = str(error) if isinstance(error, (core.LocalError, quota.QuotaError)) else "本地快照读写失败。"
                        if isinstance(error, (core.LocalError, OSError)) or (isinstance(error, quota.QuotaError) and error.status in (400, 401, 403)):
                            previous["auto_paused"] = True
                        self.vault.write(filename + ".quota", previous)
                with self.lock:
                    self.refreshing_ids.remove(filename)
                    self.active_refresh_id = None
                    if self.requests.remaining():
                        throttled = True
                        self.auto.cooldown_until = self.wall_clock() + self.requests.remaining()
                        try:
                            self.auto.save()
                        except core.LocalError:
                            self.diagnose("schedule.cooldown_write_failed")
                        self.progress = f"Google 提示查询限流，本轮已暂停；{self.requests.remaining()} 秒后可再刷新。"
                        break
            if not throttled:
                with self.lock:
                    self.progress = f"本轮已完成：成功刷新 {completed} / {len(filenames)} 个账号" + (f"，跳过 {skipped} 个近期已查询账号。" if skipped else "。")
        except Exception:
            with self.lock:
                self.progress = "本地查询未完成，请检查快照或稍后重试。"
        finally:
            with self.lock:
                self.busy = False
                self.refreshing_ids = []
                self.active_refresh_id = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log request bodies or credential-bearing exception objects.

    def send(self, code, body, kind="application/json; charset=utf-8", cookie=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if cookie:
            self.send_header("Set-Cookie", self.server.cookie_name + "=" + self.server.secret + "; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        return self.headers.get("Host") == self.server.host_header

    def authenticated(self, token=None):
        cookie = self.headers.get("Cookie", "")
        cookies = dict(part.strip().split("=", 1) for part in cookie.split(";") if "=" in part)
        return hmac.compare_digest(cookies.get(self.server.cookie_name, "").encode("utf-8"), self.server.secret.encode()) and hmac.compare_digest((token or self.headers.get("X-Local-Switcher", "")).encode("utf-8"), self.server.secret.encode())

    def do_GET(self):
        if not self.host_ok():
            self.send(403, {"error": "Invalid local host."})
            return
        if self.path == "/":
            self.server.application.seen()
            html = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
            self.send(200, html.replace("__LOCAL_TOKEN__", self.server.secret), "text/html; charset=utf-8", cookie=True)
        elif self.path in ("/favicon.ico", "/assets/app-icon.ico", "/assets/app-icon.png", "/assets/google.svg"):
            name = "app-icon.ico" if self.path == "/favicon.ico" else self.path.rsplit("/", 1)[1]
            kind = {"app-icon.ico": "image/x-icon", "app-icon.png": "image/png", "google.svg": "image/svg+xml"}[name]
            self.send(200, (Path(__file__).parent / "assets" / name).read_bytes(), kind)
        elif self.path == "/api/state" and self.authenticated():
            self.server.application.seen()
            self.send(200, self.server.application.state())
        elif self.path == "/api/identity":
            self.send(200, {"app": "AntigravityLocalSwitcher", "instance": self.server.instance, "version": VERSION})
        else:
            self.send(404, {"error": "Not found."})

    def do_POST(self):
        # Consume bounded request bodies before rejecting a request. Closing with an
        # unread POST body can reset a Windows TCP connection before the JSON error arrives.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError()
            self.connection.settimeout(5)
            raw_body = self.rfile.read(length)
            if length > 4096:
                raise ValueError()
        except (ValueError, OSError):
            self.send(400, {"error": "Invalid request."})
            return
        if not self.host_ok() or self.headers.get("Origin") != self.server.origin:
            self.send(403, {"error": "Invalid local origin."})
            return
        try:
            payload = json.loads(raw_body)
            if not isinstance(payload, dict) or set(payload) - {"label", "id", "token", "request_id", "hours", "scan_id"}:
                raise ValueError()
        except (ValueError, TypeError):
            self.send(400, {"error": "Invalid request."})
            return
        token = payload.get("token") if self.path == "/api/close" else None
        if token is not None and not isinstance(token, str):
            self.send(403, {"error": "Invalid local token."})
            return
        if not self.authenticated(token):
            self.send(403, {"error": "Invalid local session."})
            return
        if self.path == "/api/close":
            # Compatibility with v0.2 pages: pagehide must never stop the backend.
            self.send(200, {"ok": True})
            return
        try:
            if not self.path.startswith("/api/"):
                raise core.LocalError("不支持的操作。")
            message = self.server.application.action(self.path[5:], payload)
            self.send(200, {"message": message})
        except core.LocalError as error:
            self.send(400, {"error": str(error)})
        except Exception:
            self.send(500, {"error": "本地操作未完成；请检查客户端状态或目录权限。"})


def create_server(demo=False, application=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.secret = secrets.token_urlsafe(32)
    server.cookie_name = "aglocal_" + str(server.server_port)
    server.instance = secrets.token_hex(16)
    server.host_header = f"127.0.0.1:{server.server_port}"
    server.origin = "http://" + server.host_header
    server.application = application if application is not None else Application(demo)
    server.application.server = server
    return server


def open_window(url):
    candidates = [Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
                  Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe"]
    for executable in candidates:
        if executable.is_file():
            subprocess.Popen([str(executable), "--app=" + url, "--window-size=1220,850"], close_fds=True)
            # Browser app mode can keep the default globe even after loading a favicon.
            # Brand only the owned local page's Edge window, without changing other windows.
            from window_branding import brand_edge_window
            threading.Thread(target=brand_edge_window, args=(url, Path(__file__).parent / "assets" / "app-icon.ico"), daemon=True).start()
            return
    webbrowser.open(url)


def existing_url(instance_path, expected_version=VERSION):
    """Validate one owned instance file and one exact loopback endpoint; no port scanning."""
    connection = None
    try:
        if instance_path.stat().st_size > 4096:
            return None
        info = json.loads(instance_path.read_text(encoding="utf-8"))
        port, owner = info.get("port"), info.get("instance")
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            return None
        if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{32}", owner):
            return None
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
        connection.request("GET", "/api/identity")
        response = connection.getresponse()
        value = json.loads(response.read(4097))
        if response.status == 200 and value.get("app") == "AntigravityLocalSwitcher" and value.get("instance") == owner:
            if value.get("version") != expected_version:
                raise core.LocalError("后台仍在运行旧版。请在旧窗口点“退出工具”，再重新运行新版 Start.cmd。")
            return f"http://127.0.0.1:{port}/"
    except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
        pass
    finally:
        if connection:
            connection.close()
    return None


def run(demo=False, open_browser=True):
    mutex = kernel = None
    legacy_mutex = None
    upgrade_progress = None
    instance_path = Path(os.environ["LOCALAPPDATA"]) / "AntigravityLocalSwitcher" / "instance.json"
    if not demo:
        kernel = core.system_dll("kernel32.dll")
        kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
        kernel.CreateMutexW.restype = W.HANDLE
        kernel.CloseHandle.argtypes = [W.HANDLE]
        deadline = time.monotonic() + 6
        upgrading = False
        quit_requested = False
        while True:
            # Legacy error dialogs can retain the old named handle after their
            # backend exits. Check the registered service before using our new lock.
            instance = instance_control.probe(instance_path)
            if instance and instance.version == VERSION:
                if open_browser:
                    open_window(instance.origin + "/")
                if upgrade_progress:
                    upgrade_progress.close()
                return
            if instance and not quit_requested:
                if not upgrading:
                    upgrading = True
                    deadline = time.monotonic() + 600
                result = instance_control.retire(instance)
                if result == "stopped":
                    quit_requested = True
                    deadline = time.monotonic() + 15
                elif result == "busy" and upgrade_progress is None:
                    upgrade_progress = instance_control.UpgradeProgress()
            if not instance:
                mutex = kernel.CreateMutexW(None, False, "Local\\AntigravityLocalSwitcher-Managed")
                if not mutex:
                    raise core.LocalError("无法创建本地实例锁。")
                if C.get_last_error() != 183:
                    # Keep legacy launchers from starting a second older backend.
                    legacy_mutex = kernel.CreateMutexW(None, False, "Local\\AntigravityLocalSwitcher-Modern")
                    if not legacy_mutex:
                        kernel.CloseHandle(mutex)
                        raise core.LocalError("无法创建兼容实例锁。")
                    break
                kernel.CloseHandle(mutex)
                mutex = None
            if upgrade_progress:
                upgrade_progress.pump()
            if time.monotonic() >= deadline:
                if upgrade_progress:
                    upgrade_progress.close()
                raise core.LocalError("旧后台暂时没有完成退出，请稍后再启动；账号快照已保留。")
            time.sleep(0.4)
        if upgrade_progress:
            upgrade_progress.close()
    server = None
    fault_log = None
    try:
        server = create_server(demo)
        if not demo:
            metadata = {"version": VERSION, "pid": os.getpid(), "port": server.server_port, "instance": server.instance}
            core.atomic_write(instance_path, json.dumps(metadata).encode("utf-8"))
            fault_log = (server.application.directory / "native-fault.log").open("a", encoding="utf-8")
            faulthandler.enable(file=fault_log, all_threads=True)
            server.application.diagnose("app.started")
        def lifecycle():
            while True:
                time.sleep(1)
                if server.application.should_stop():
                    break
            server.shutdown()
        threading.Thread(target=lifecycle, daemon=True).start()
        if not demo:
            def scheduled_queries():
                while not server.application.should_stop():
                    try:
                        server.application.scheduler_tick()
                    except Exception:
                        server.application.diagnose("schedule.tick_failed")
                    time.sleep(15)
            threading.Thread(target=scheduled_queries, daemon=True).start()
        if open_browser:
            open_window(server.origin + "/")
        else:
            print(server.origin + "/", flush=True)
        server.serve_forever()
    finally:
        if server:
            server.server_close()
        if fault_log:
            faulthandler.disable()
            fault_log.close()
        if not demo and server:
            try:
                info = json.loads(instance_path.read_text(encoding="utf-8"))
                if info.get("instance") == server.instance:
                    instance_path.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        if mutex:
            kernel.CloseHandle(mutex)
        if legacy_mutex:
            kernel.CloseHandle(legacy_mutex)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run(args.demo, not args.no_browser)
