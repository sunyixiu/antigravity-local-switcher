"""Local Windows Antigravity 2.x snapshots, with optional Google-only quota queries."""
from __future__ import annotations

import argparse
import base64
import csv
import ctypes as C
from ctypes import wintypes as W
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

TARGET = "gemini:antigravity"
MAGIC = b"AGLOCAL1\x00"
ENTROPY = b"AntigravityLocalSwitcher/v1"
MAX_FILE = 100_000
MAX_NATIVE_BLOB = 2560


class LocalError(Exception):
    pass


class NativeError(LocalError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class FILETIME(C.Structure):
    _fields_ = [("low", W.DWORD), ("high", W.DWORD)]


class CREDENTIAL(C.Structure):
    _fields_ = [
        ("flags", W.DWORD), ("type", W.DWORD), ("target", W.LPWSTR),
        ("comment", W.LPWSTR), ("written", FILETIME), ("size", W.DWORD),
        ("blob", C.POINTER(C.c_ubyte)), ("persist", W.DWORD),
        ("attribute_count", W.DWORD), ("attributes", C.c_void_p),
        ("alias", W.LPWSTR), ("username", W.LPWSTR),
    ]


class DATA_BLOB(C.Structure):
    _fields_ = [("size", W.DWORD), ("data", C.POINTER(C.c_ubyte))]


def system_dll(name):
    # Resolve Windows DLLs from the OS directory, rather than the working directory.
    return C.WinDLL(str(Path(os.environ["SystemRoot"]) / "System32" / name), use_last_error=True)


class NativeStore:
    def __init__(self, target=TARGET):
        if target != TARGET and not target.startswith("AntigravityLocalSwitcher-Test-"):
            raise LocalError("不支持的凭据目标。")
        self.target = target
        self.api = system_dll("advapi32.dll")
        self.api.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.POINTER(CREDENTIAL))]
        self.api.CredReadW.restype = W.BOOL
        self.api.CredWriteW.argtypes = [C.POINTER(CREDENTIAL), W.DWORD]
        self.api.CredWriteW.restype = W.BOOL
        self.api.CredFree.argtypes = [C.c_void_p]
        self.api.CredFree.restype = None
        self.api.CredDeleteW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD]
        self.api.CredDeleteW.restype = W.BOOL

    def read(self):
        pointer = C.POINTER(CREDENTIAL)()
        if not self.api.CredReadW(self.target, 1, 0, C.byref(pointer)):
            code = C.get_last_error()
            if code == 1168:
                return None
            raise NativeError(f"Windows 凭据读取失败（系统错误 {code}）。", code)
        try:
            item = pointer.contents
            if item.target != self.target or item.type != 1 or not 0 < item.size <= 5120:
                raise LocalError("凭据格式不受支持，未做修改。")
            if item.attribute_count or item.alias or item.flags:
                raise LocalError("凭据含额外属性，当前工具拒绝覆盖。")
            return {
                "blob": base64.b64encode(C.string_at(item.blob, item.size)).decode("ascii"),
                "username": item.username or "",
                "comment": item.comment,
                "persist": int(item.persist),
            }
        finally:
            self.api.CredFree(pointer)

    def write(self, record):
        validate_record(record)
        payload = base64.b64decode(record["blob"], validate=True)
        if len(payload) > MAX_NATIVE_BLOB:
            raise LocalError("登录数据超过 Windows 凭据的 2560 字节限制，未执行写入。")
        buffer = (C.c_ubyte * len(payload)).from_buffer_copy(payload)
        item = CREDENTIAL()
        item.type = 1
        item.target = self.target
        item.username = record["username"]
        item.comment = record["comment"]
        item.persist = record["persist"]
        item.size = len(payload)
        item.blob = C.cast(buffer, C.POINTER(C.c_ubyte))
        try:
            if not self.api.CredWriteW(C.byref(item), 0):
                code = C.get_last_error()
                raise NativeError(f"Windows 凭据写入失败（系统错误 {code}）。", code)
        finally:
            C.memset(buffer, 0, len(payload))

    def delete(self):
        if not self.api.CredDeleteW(self.target, 1, 0) and C.get_last_error() != 1168:
            raise LocalError("无法恢复此前未登录的状态。")


def validate_record(record):
    try:
        if not isinstance(record, dict) or set(record) != {"blob", "username", "comment", "persist"}:
            raise ValueError()
        blob = base64.b64decode(record["blob"], validate=True)
        if not 0 < len(blob) <= 5120 or record["persist"] not in (1, 2, 3):
            raise ValueError()
        if not isinstance(record["username"], str) or len(record["username"]) > 256:
            raise ValueError()
        if record["comment"] is not None and not isinstance(record["comment"], str):
            raise ValueError()
        text = blob.decode("utf-8")
        if text.startswith("go-keyring-base64:"):
            text = base64.b64decode(text.split(":", 1)[1], validate=True).decode("utf-8")
        parsed = json.loads(text)
        token = parsed.get("token", parsed)
        if not isinstance(token, dict) or not isinstance(token.get("refresh_token"), str):
            raise ValueError()
        if not token["refresh_token"].strip():
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        raise LocalError("快照没有可用的 Google 刷新令牌，或格式不受支持；未做修改。") from None


def prepare_native_record(record):
    """Adapt oversized legacy quota snapshots without changing access/refresh grants.

    The official OAuth token format does not require id_token, which quota refresh
    previously added. Keep the encrypted snapshot intact; normalize only the
    record destined for the Windows vault, before closing the official client.
    """
    validate_record(record)
    raw = base64.b64decode(record["blob"], validate=True)
    if len(raw) <= MAX_NATIVE_BLOB:
        return record
    text = raw.decode("utf-8")
    wrapped = text.startswith("go-keyring-base64:")
    if wrapped:
        text = base64.b64decode(text.split(":", 1)[1], validate=True).decode("utf-8")
    value = json.loads(text)
    token = value.get("token", value)
    def encode():
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return b"go-keyring-base64:" + base64.b64encode(data) if wrapped else data
    raw = encode()
    if len(raw) > MAX_NATIVE_BLOB:
        token.pop("id_token", None)
        raw = encode()
    if len(raw) > MAX_NATIVE_BLOB:
        raise LocalError("登录数据仍超过 Windows 凭据容量，未关闭客户端或修改登录。请在官方客户端重新登录并更新快照。")
    return dict(record, blob=base64.b64encode(raw).decode("ascii"))


def refresh_identity(record):
    # Used only to recognize the previously saved session; never logged or displayed.
    text = base64.b64decode(record["blob"]).decode("utf-8")
    if text.startswith("go-keyring-base64:"):
        text = base64.b64decode(text.split(":", 1)[1]).decode("utf-8")
    parsed = json.loads(text)
    return parsed.get("token", parsed)["refresh_token"]


class Protector:
    def __init__(self):
        self.crypto = system_dll("crypt32.dll")
        self.kernel = system_dll("kernel32.dll")
        self.crypto.CryptProtectData.argtypes = [C.POINTER(DATA_BLOB), W.LPCWSTR, C.POINTER(DATA_BLOB), C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(DATA_BLOB)]
        self.crypto.CryptProtectData.restype = W.BOOL
        self.crypto.CryptUnprotectData.argtypes = [C.POINTER(DATA_BLOB), C.c_void_p, C.POINTER(DATA_BLOB), C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(DATA_BLOB)]
        self.crypto.CryptUnprotectData.restype = W.BOOL
        self.kernel.LocalFree.argtypes = [C.c_void_p]
        self.kernel.LocalFree.restype = C.c_void_p

    def transform(self, data, encrypt):
        buf = (C.c_ubyte * len(data)).from_buffer_copy(data)
        entropy_buf = (C.c_ubyte * len(ENTROPY)).from_buffer_copy(ENTROPY)
        source = DATA_BLOB(len(data), C.cast(buf, C.POINTER(C.c_ubyte)))
        entropy = DATA_BLOB(len(ENTROPY), C.cast(entropy_buf, C.POINTER(C.c_ubyte)))
        output = DATA_BLOB()
        fn = self.crypto.CryptProtectData if encrypt else self.crypto.CryptUnprotectData
        try:
            # Flag 1 disables UI; LOCAL_MACHINE is intentionally absent (current user binding).
            if not fn(C.byref(source), None, C.byref(entropy), None, None, 1, C.byref(output)):
                raise LocalError("Windows 用户加密失败，或当前用户无法解密这份快照。")
            return C.string_at(output.data, output.size)
        finally:
            C.memset(buf, 0, len(data))
            if output.data:
                C.memset(output.data, 0, output.size)
                self.kernel.LocalFree(output.data)


def atomic_write(path, data):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Vault:
    def __init__(self, directory):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.protector = Protector()

    def write(self, filename, value):
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        atomic_write(self.directory / filename, MAGIC + self.protector.transform(encoded, True))

    def read(self, filename):
        path = self.directory / filename
        if path.stat().st_size > MAX_FILE:
            raise LocalError("快照文件大小异常。")
        raw = path.read_bytes()
        if not raw.startswith(MAGIC):
            raise LocalError("不是受支持的加密快照。")
        try:
            return json.loads(self.protector.transform(raw[len(MAGIC):], False))
        except (ValueError, UnicodeError):
            raise LocalError("快照内容无效，未做修改。") from None

    def save(self, label, record, filename=None, identity=None):
        validate_record(record)
        filename = filename or uuid.uuid4().hex + ".agprofile"
        value = {"version": 1, "label": label, "credential": record}
        if identity is None and (self.directory / filename).exists():
            old = self.load(filename)
            if refresh_identity(old["credential"]) == refresh_identity(record):
                identity = old.get("identity")
        if identity is not None:
            if not isinstance(identity, dict) or set(identity) != {"subject", "email", "name"} or any(not isinstance(v, str) for v in identity.values()):
                raise LocalError("账号身份信息格式无效。")
            value["identity"] = identity
        self.write(filename, value)
        return filename

    def load(self, filename):
        if Path(filename).name != filename:
            raise LocalError("快照路径无效。")
        value = self.read(filename)
        if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("label"), str):
            raise LocalError("快照版本或名称无效。")
        validate_record(value.get("credential"))
        return value

    def delete_profile(self, filename):
        saved = self.load(filename)
        paths = [self.directory / filename, self.directory / (filename + ".quota")]
        recovery = self.directory / "before-switch.agrecovery"
        if recovery.exists():
            value = self.read(recovery.name)
            record = value.get("credential") if isinstance(value, dict) else None
            if record is not None:
                validate_record(record)
                if refresh_identity(record) == refresh_identity(saved["credential"]):
                    paths.append(recovery)
        originals = {path: path.read_bytes() for path in paths if path.exists()}
        removed = []
        try:
            for path in originals:
                path.unlink()
                removed.append(path)
        except OSError:
            for path in removed:
                atomic_write(path, originals[path])
            raise LocalError("删除失败，已恢复此前文件。请检查账号数据目录权限。") from None

    def profiles(self):
        result = []
        for path in sorted(self.directory.glob("*.agprofile")):
            try:
                value = self.load(path.name)
                result.append((path.name, value["label"]))
            except LocalError:
                result.append((path.name, "[无法解密或格式无效]"))
        return result


def capture_matching_snapshot(vault, current):
    """Capture the final official credential only for a unique matching grant."""
    if current is None:
        return None
    validate_record(current)
    identity = refresh_identity(current)
    matches = []
    for filename, _ in vault.profiles():
        saved = vault.load(filename)
        if refresh_identity(saved["credential"]) == identity:
            matches.append((filename, saved))
    if len(matches) != 1:
        return None
    filename, saved = matches[0]
    if saved["credential"] != current:
        vault.save(saved["label"], current, filename, identity=saved.get("identity"))
    return filename


def antigravity_pids():
    command = Path(os.environ["SystemRoot"]) / "System32" / "tasklist.exe"
    result = subprocess.run([str(command), "/FI", "IMAGENAME eq Antigravity.exe", "/FO", "CSV", "/NH"], capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise LocalError("无法确认 Antigravity 是否已退出；未切换。")
    text = result.stdout.decode("mbcs", errors="replace")
    return {int(row[1]) for row in csv.reader(io.StringIO(text)) if len(row) >= 2 and row[0].casefold() == "antigravity.exe"}


def close_antigravity():
    pids = antigravity_pids()
    if not pids:
        return
    user = system_dll("user32.dll")
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user.EnumWindows.restype = W.BOOL
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    user.GetWindowThreadProcessId.restype = W.DWORD
    user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    user.PostMessageW.restype = W.BOOL

    @callback_type
    def visit(hwnd, _):
        pid = W.DWORD()
        user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value in pids:
            user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: ordinary close, never force-kill.
        return True

    user.EnumWindows(visit, 0)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not antigravity_pids():
            return
        time.sleep(0.4)
    raise LocalError("Antigravity 尚未完全退出（可能在等待保存确认）。请正常退出后再切换；凭据未修改。")


def replace_verified(store, target, previous):
    try:
        if target is None:
            store.delete()
        else:
            store.write(target)
        if store.read() != target:
            raise LocalError("切换后的凭据校验失败。")
    except Exception as error:
        try:
            if previous is None:
                store.delete()
            else:
                store.write(previous)
            if store.read() != previous:
                raise LocalError("恢复校验失败。")
        except Exception:
            raise LocalError("切换失败，自动恢复也未成功。请保持 Antigravity 关闭，使用“恢复切换前账号”；加密恢复文件仍保留。") from None
        message = "切换失败，已恢复切换前的凭据。"
        if isinstance(error, NativeError):
            raise NativeError(message + f" Windows 凭据操作错误 {error.code}。", error.code) from None
        if isinstance(error, LocalError):
            message += " " + str(error)
        else:
            message += " 本地凭据操作发生异常。"
        raise LocalError(message) from None


def executable_path():
    candidates = [Path(os.environ["LOCALAPPDATA"]) / "Programs/Antigravity/Antigravity.exe", Path(os.environ["ProgramFiles"]) / "Antigravity/Antigravity.exe"]
    for path in candidates:
        if path.is_file():
            return path
    raise LocalError("没有找到标准位置的 Antigravity.exe。")


def launch(executable):
    try:
        subprocess.Popen([str(executable)], cwd=str(executable.parent), close_fds=True)
    except OSError:
        raise LocalError("凭据操作已完成，但 Antigravity 启动失败。请手动打开。") from None


class Switcher:
    def __init__(self, store, vault):
        self.store = store
        self.vault = vault
        self.active = None

    def switch(self, filename):
        selected = self.vault.load(filename)  # Decrypt/validate before closing or writing anything.
        selected["credential"] = prepare_native_record(selected["credential"])
        executable = executable_path()
        close_antigravity()
        current = self.store.read()
        if current is not None:
            validate_record(current)
        self.vault.write("before-switch.agrecovery", {"version": 1, "credential": current})
        matched = capture_matching_snapshot(self.vault, current)
        if filename == matched:
            selected["credential"] = prepare_native_record(current)
        replace_verified(self.store, selected["credential"], current)
        self.active = filename
        launch(executable)

    def restore(self):
        saved = self.vault.read("before-switch.agrecovery")
        if not isinstance(saved, dict) or saved.get("version") != 1 or "credential" not in saved:
            raise LocalError("恢复文件格式无效。")
        target = saved["credential"]
        if target is not None:
            target = prepare_native_record(target)
        executable = executable_path()
        close_antigravity()
        current = self.store.read()
        capture_matching_snapshot(self.vault, current)
        replace_verified(self.store, target, current)
        self.active = None
        launch(executable)


def self_test(directory):
    """Uses only a unique synthetic credential target. Never reads TARGET or closes apps."""
    target = "AntigravityLocalSwitcher-Test-" + uuid.uuid4().hex
    store = NativeStore(target)
    first = {"blob": base64.b64encode(json.dumps({"token": {"refresh_token": "synthetic-A", "access_token": "fake-A"}}).encode()).decode(), "username": "test", "comment": "Synthetic local test", "persist": 2}
    second = dict(first, blob=base64.b64encode(json.dumps({"token": {"refresh_token": "synthetic-B", "access_token": "fake-B"}}).encode()).decode())
    vault = Vault(directory)
    try:
        filename = vault.save("Synthetic A", first)
        raw = (directory / filename).read_bytes()
        assert b"synthetic-A" not in raw and b"fake-A" not in raw
        assert vault.load(filename)["credential"] == first
        tampered = bytearray(raw)
        tampered[-1] ^= 1
        atomic_write(directory / "tampered.agprofile", bytes(tampered))
        try:
            vault.load("tampered.agprofile")
            raise AssertionError("Tampered snapshot was accepted")
        except LocalError:
            pass
        class FailedVerification:
            def __init__(self):
                self.value = first
                self.once = True
            def write(self, value):
                self.value = value
            def read(self):
                if self.once and self.value == second:
                    self.once = False
                    return None
                return self.value
            def delete(self):
                self.value = None

        fake = FailedVerification()
        try:
            replace_verified(fake, second, first)
            raise AssertionError("Failed verification did not abort")
        except LocalError:
            assert fake.value == first
        print("PASS: current-user DPAPI encryption, tamper rejection and failed-write verification rollback.")
        assert store.read() is None
        try:
            store.write(first)
        except NativeError as error:
            if error.code != 1312:
                raise
            print("SKIP: native credential write requires an interactive Windows logon session (1312).")
            return
        assert store.read() == first
        replace_verified(store, second, first)
        assert store.read() == second
        print("PASS: synthetic Win32 credential read/write and verified replacement.")
    finally:
        store.delete()
        assert store.read() is None
        print("PASS: synthetic credential target removed. No real Antigravity credentials accessed.")


def main():
    if sys.platform != "win32":
        raise LocalError("这个版本用于 Windows Antigravity 桌面客户端。")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", type=Path)
    parser.add_argument("--demo", action="store_true", help="Open sample accounts without reading credentials")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop-running", action="store_true", help="Gracefully stop the registered account tool")
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.stop_running:
        from instance_control import stop_registered
        stop_registered()
    elif args.smoke_test:
        from package_check import check
        check(args.smoke_test)
    elif args.self_test:
        self_test(args.self_test.resolve())
    else:
        from desktop_ui import run
        run(demo=args.demo, open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.modules.setdefault("local_switcher", sys.modules[__name__])
    try:
        main()
    except LocalError as error:
        if "--self-test" in sys.argv:
            print(str(error), file=sys.stderr)
        else:
            from native_dialog import show_error
            show_error(str(error))
        sys.exit(1)
