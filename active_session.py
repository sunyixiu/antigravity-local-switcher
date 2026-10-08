"""Observe and synchronize the official local login without OAuth renewal."""
import hashlib
import time

import account_discovery
import local_switcher as core
import quota

LOGIN_SETTLE_SECONDS = 5.0


class ActiveSession:
    def __init__(self, store, vault, matcher, running_check, clock):
        self.store, self.vault, self.matcher = store, vault, matcher
        self.running_check, self.clock = running_check, clock
        self.signature = None
        self.pending = None
        self.record = None
        self.view = {"status": "unknown", "running": False, "quota_eligible": False}
        self.blocked_token = None

    @staticmethod
    def token_stamp(record):
        return hashlib.sha256(record["blob"].encode("ascii")).digest()

    def observe(self, verified_binding=None):
        try:
            current = self.store.read()
            running = bool(self.running_check())
            names = [name for name, _ in self.vault.profiles()]
            view = self.matcher.resolve_record(current, self.vault, names, verified_binding)
            view.update(running=running, quota_eligible=running and view["status"] == "matched")
            self.record = current
            if view["status"] == "matched":
                name = view["id"]
                saved = self.vault.load(name)
                if saved["credential"] != current:
                    self.vault.save(saved["label"], current, name, identity=saved.get("identity"))
                stamp = account_discovery.fingerprint(current)
                self.matcher.bind(stamp, name, stamp)
                view["label"] = saved["label"]
            else:
                name = None
                stamp = None
            signature = (running, name, stamp)
            token_stamp = self.token_stamp(current) if current else None
            if signature != self.signature:
                self.pending = (name, self.clock() + LOGIN_SETTLE_SECONDS) if view["quota_eligible"] else None
            elif self.blocked_token is not None and token_stamp != self.blocked_token and view["quota_eligible"]:
                self.pending = (name, self.clock() + LOGIN_SETTLE_SECONDS)
            if self.blocked_token is not None and token_stamp != self.blocked_token:
                self.blocked_token = None
            self.signature = signature
            self.view = view
        except (core.LocalError, OSError, ValueError, TypeError, KeyError):
            self.record = None
            self.pending = None
            self.signature = None
            self.view = {"status": "error", "message": "无法核对或同步当前登录快照，请检查本地客户端和数据目录。",
                         "running": False, "quota_eligible": False}
        return dict(self.view)

    def guard(self, filename, verified_binding=None):
        view = self.observe(verified_binding)
        if not view["quota_eligible"] or view.get("id") != filename:
            raise quota.QueryStopped("当前登录已改变或 Antigravity 已关闭，停止查询；其他账号保留本地缓存。")
        _, token, _ = quota.decode(self.record)
        access = token.get("access_token")
        due = quota.expiration(token)
        if not isinstance(access, str) or not access or (due is not None and due <= time.time() + 30):
            self.blocked_token = self.token_stamp(self.record)
            raise quota.OfficialRefreshRequired("等待 Antigravity 更新登录授权；工具不自行刷新令牌。", 401)
        return {"access": access}
