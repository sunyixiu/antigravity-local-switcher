"""Identify and gracefully retire only this user's registered local tool instance."""
from dataclasses import dataclass
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from pathlib import Path
import hmac
import http.client
import json
import re
import os
import time

from local_switcher import LocalError
from native_dialog import UpgradeProgress


@dataclass(frozen=True)
class Instance:
    port: int
    owner: str
    version: str

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"


def identity(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/api/identity")
        response = connection.getresponse()
        body = response.read(4097)
        if response.status != 200 or len(body) > 4096:
            return None
        value = json.loads(body)
        return value if isinstance(value, dict) else None
    finally:
        connection.close()


def probe(path):
    try:
        if path.stat().st_size > 4096:
            return None
        info = json.loads(path.read_text(encoding="utf-8"))
        port, owner = info.get("port"), info.get("instance")
        if type(port) is not int or not 1024 <= port <= 65535:
            return None
        if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{32}", owner):
            return None
        value = identity(port)
        if not value or value.get("app") != "AntigravityLocalSwitcher" or value.get("instance") != owner:
            return None
        version = value.get("version")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version):
            return None
        return Instance(port, owner, version)
    except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
        return None


class TokenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attributes):
        value = dict(attributes)
        if tag == "meta" and value.get("name") == "local-token":
            self.token = value.get("content")


def retire(instance):
    """Return stopped/busy/gone. Never terminate a process or access Google credentials."""
    connection = None
    try:
        value = identity(instance.port)
        if not value or value.get("app") != "AntigravityLocalSwitcher" or value.get("instance") != instance.owner:
            return "gone"
        connection = http.client.HTTPConnection("127.0.0.1", instance.port, timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read(200001)
        if response.status != 200 or len(body) > 200000:
            raise LocalError("无法读取旧工具的本地控制页面，请重新运行启动器。")
        parser = TokenParser()
        parser.feed(body.decode("utf-8"))
        token = parser.token
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
            raise LocalError("旧工具控制会话格式无效，未执行退出操作。")
        cookies = SimpleCookie()
        cookies.load(response.getheader("Set-Cookie", ""))
        name = "aglocal_" + str(instance.port)
        cookie = cookies.get(name)
        if cookie is None or not hmac.compare_digest(cookie.value.encode(), token.encode()):
            raise LocalError("旧工具会话校验失败，未执行退出操作。")
        # Recheck affinity after obtaining the cookie; an unrelated replacement must not be stopped.
        value = identity(instance.port)
        if not value or value.get("app") != "AntigravityLocalSwitcher" or value.get("instance") != instance.owner:
            return "gone"
        connection.request("POST", "/api/quit", body="{}", headers={
            "Origin": instance.origin, "Content-Type": "application/json",
            "Cookie": name + "=" + cookie.value, "X-Local-Switcher": token,
        })
        response = connection.getresponse()
        body = response.read(4097)
        value = json.loads(body)
        if response.status == 200:
            return "stopped"
        if response.status == 400 and isinstance(value, dict) and "当前操作" in value.get("error", ""):
            return "busy"
        raise LocalError("旧工具暂时无法正常退出，请稍候再运行新版启动器。")
    except (OSError, ValueError, UnicodeError, http.client.HTTPException):
        return "gone"
    finally:
        if connection:
            connection.close()


def stop_registered(timeout=600):
    """Installer helper: gracefully stop only the registered tool, never Antigravity."""
    path = Path(os.environ["LOCALAPPDATA"]) / "AntigravityLocalSwitcher" / "instance.json"
    deadline = time.monotonic() + timeout
    progress = None
    acknowledged = False
    try:
        while True:
            instance = probe(path)
            if instance is None:
                return
            if not acknowledged:
                result = retire(instance)
                if result == "stopped":
                    acknowledged = True
                    deadline = time.monotonic() + 15
                elif result == "busy" and progress is None:
                    progress = UpgradeProgress()
            if progress:
                progress.pump()
            if time.monotonic() >= deadline:
                raise LocalError("账号工具尚未完成退出，请稍后再安装或卸载。")
            time.sleep(.4)
    finally:
        if progress:
            progress.close()
