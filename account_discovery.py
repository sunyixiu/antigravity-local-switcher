"""Scan the current Antigravity login; persist only after explicit naming/confirmation."""
import hashlib
import re
import time
import uuid

import local_switcher as core
import quota

USER_INFO = "https://www.googleapis.com/oauth2/v2/userinfo"


def fingerprint(record):
    core.validate_record(record)
    return hashlib.sha256(core.refresh_identity(record).encode()).digest()


def verified_profile(value):
    subject = value.get("id")
    email = value.get("email")
    name = value.get("name", "")
    if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subject):
        raise core.LocalError("Google 未返回可识别的账号身份，请在官方客户端确认登录后重新扫描。")
    if not isinstance(email, str) or not 3 <= len(email) <= 254 or "@" not in email or any(ord(c) < 33 for c in email):
        raise core.LocalError("Google 未返回有效邮箱，请在官方客户端确认登录后重新扫描。")
    return {"subject": subject, "email": email, "name": name[:80] if isinstance(name, str) and not any(ord(c) < 32 for c in name) else ""}


class Discovery:
    def __init__(self, store, vault, request, clock=None):
        self.store, self.vault, self.request = store, vault, request
        self.clock = clock or time.monotonic
        self.pending = None
        self.last_scan = None
        self.view = {"status": "idle", "message": "尚未扫描当前登录。"}
        self.completed = {}

    def scan(self):
        current = self.store.read()
        if not current:
            self.pending = None
            self.view = {"status": "signed-out", "message": "未检测到 Antigravity 登录。请先在官方客户端登录 Google 账号，再点“扫描账号”。"}
            self.last_scan = self.clock()
            return self.view
        stamp = fingerprint(current)
        if self.pending and self.pending["fingerprint"] == stamp and self.clock() - self.pending["created"] < 30:
            self.view = {"status": "new", "message": "发现新账号，尚未保存。请确认邮箱、命名后添加。", "scan_id": self.pending["scan_id"], "email": self.pending["identity"]["email"], "name": self.pending["identity"]["name"]}
            return self.view
        self.pending = None
        records = []
        unreadable = False
        for filename, _ in self.vault.profiles():
            try:
                saved = self.vault.load(filename)
                records.append((filename, saved))
            except core.LocalError:
                unreadable = True
        exact = next(((filename, saved) for filename, saved in records if fingerprint(saved["credential"]) == stamp), None)
        if exact:
            filename, saved = exact
            identity = saved.get("identity", {})
            self.view = {"status": "known", "message": "当前登录已入库：" + saved["label"], "existing_id": filename, "label": saved["label"], "email": identity.get("email", "")}
            self.last_scan = self.clock()
            return self.view
        if unreadable:
            raise core.LocalError("存在无法读取的已保存账号，请先处理快照读取问题，避免重复入库。")
        _, token, _ = quota.decode(current)
        record = current
        due = quota.expiration(token)
        refreshed = False
        if not token.get("access_token") or (due is not None and due < time.time() + 30):
            record = quota.renew(current, self.request)
            refreshed = True
        try:
            profile = self.request(USER_INFO, None, access=quota.decode(record)[1]["access_token"], method="GET")
        except quota.QuotaError as error:
            if error.status != 401 or refreshed:
                raise
            record = quota.renew(current, self.request)
            profile = self.request(USER_INFO, None, access=quota.decode(record)[1]["access_token"], method="GET")
        identity = verified_profile(profile)
        known = next(((filename, saved) for filename, saved in records if saved.get("identity", {}).get("subject") == identity["subject"]), None)
        if known:
            filename, saved = known
            self.view = {"status": "known", "message": "此 Google 账号已入库：" + saved["label"] + "。登录信息已变化，可在账号菜单更新快照。", "existing_id": filename, "label": saved["label"], "email": identity["email"]}
        else:
            scan_id = uuid.uuid4().hex
            self.pending = {"scan_id": scan_id, "fingerprint": stamp, "record": record, "identity": identity, "created": self.clock()}
            self.view = {"status": "new", "message": "发现新账号，尚未保存。请确认邮箱、命名后添加。", "scan_id": scan_id, "email": identity["email"], "name": identity["name"]}
        self.last_scan = self.clock()
        return self.view

    def confirm(self, scan_id, label, request_id):
        if not isinstance(scan_id, str) or not re.fullmatch(r"[0-9a-f]{32}", scan_id):
            raise core.LocalError("扫描结果无效，请重新扫描账号。")
        if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", request_id):
            raise core.LocalError("添加请求无效，请重新打开命名窗口。")
        if self.completed.get(request_id, (None,))[0] == scan_id:
            return self.completed[request_id][1]
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or any(ord(c) < 32 for c in label):
            raise core.LocalError("账号名称需要 1 到 80 个可见字符。")
        candidate = self.pending
        if not candidate or scan_id != candidate["scan_id"] or self.clock() - candidate["created"] > 600:
            raise core.LocalError("扫描结果已过期，请重新扫描后添加。")
        current = self.store.read()
        if not current or fingerprint(current) != candidate["fingerprint"]:
            self.pending = None
            self.view = {"status": "changed", "message": "Antigravity 当前登录已改变，请重新扫描，避免保存错误账号。"}
            raise core.LocalError(self.view["message"])
        # Recheck saved identities under the application's operation lock before writing.
        for filename, _ in self.vault.profiles():
            saved = self.vault.load(filename)
            if fingerprint(saved["credential"]) == candidate["fingerprint"] or saved.get("identity", {}).get("subject") == candidate["identity"]["subject"]:
                raise core.LocalError("这个账号已经保存，请重新扫描查看，避免重复添加。")
        filename = uuid.UUID(request_id).hex + ".agprofile"
        if (self.vault.directory / filename).exists():
            raise core.LocalError("添加请求标识已使用，请重新扫描。")
        self.vault.save(label.strip(), candidate["record"], filename, identity=candidate["identity"])
        self.completed[request_id] = (scan_id, filename)
        self.completed = dict(list(self.completed.items())[-30:])
        self.pending = None
        self.view = {"status": "known", "message": "已添加账号：" + label.strip(), "existing_id": filename, "label": label.strip(), "email": candidate["identity"]["email"]}
        return filename
