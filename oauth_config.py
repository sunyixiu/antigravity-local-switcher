"""Read compatible OAuth configuration from the locally installed official client.

No client configuration or user grant is embedded or downloaded by this module.
The fingerprint selects the verified Antigravity pair rather than Gemini CLI's
other OAuth configuration in the same binary. Unknown versions fail closed.
"""
from functools import lru_cache
import hashlib
import mmap
import os
from pathlib import Path
import re

COMPATIBLE_PAIR_SHA256 = "0eba362d53c81721da20f4ab53266802b2e39aa8dad0af58956abd1b7c72e3ce"
ID_PATTERN = rb"[0-9]{8,20}-[a-z0-9]{20,50}\.apps\.googleusercontent\.com"
SECRET_PATTERN = rb"GOCSPX-[A-Za-z0-9_-]{28}"


class ConfigurationError(Exception):
    pass


def extract_config(data):
    ids = {m.group() for m in re.finditer(ID_PATTERN, data)}
    secrets = {m.group() for m in re.finditer(SECRET_PATTERN, data)}
    if len(ids) > 16 or len(secrets) > 16:
        raise ConfigurationError("官方客户端 OAuth 配置格式不兼容，请更新工具。")
    for client_id in ids:
        for secret in secrets:
            digest = hashlib.sha256(client_id + b"\0" + secret).hexdigest()
            if digest == COMPATIBLE_PAIR_SHA256:
                return client_id.decode("ascii"), secret.decode("ascii")
    raise ConfigurationError("未识别到兼容的官方客户端 OAuth 配置，请更新工具或在官方客户端重新登录。")


@lru_cache(maxsize=2)
def _read_config(path, size, modified):
    try:
        with open(path, "rb") as source:
            with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
                return extract_config(data)
    except (OSError, ValueError):
        raise ConfigurationError("无法读取官方客户端配置，请确认已安装 Antigravity。") from None


def local_client_config():
    for variable, suffix in (("LOCALAPPDATA", "Programs/Antigravity"),
                             ("ProgramFiles", "Antigravity")):
        base = os.environ.get(variable)
        if not base:
            continue
        path = Path(base) / suffix / "resources/bin/language_server.exe"
        try:
            stat = path.stat()
        except OSError:
            continue
        return _read_config(str(path), stat.st_size, stat.st_mtime_ns)
    raise ConfigurationError("未找到官方 Antigravity 客户端，无法刷新授权；请先安装客户端。")
