"""Persistent low-frequency queries and confirmation of reported reset times."""
from datetime import datetime
import json
import math
import re

from local_switcher import atomic_write, LocalError

RESET_GRACE = 30
RESET_RETRY = 1800


def reset_epoch(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def pending_resets(cache, now, grace=0):
    updated = cache.get("updated", 0)
    if isinstance(updated, bool) or not isinstance(updated, (float, int)) or not math.isfinite(updated):
        updated = 0
    result = []
    for row in cache.get("groups", []):
        if row.get("family") not in ("gemini", "thirdparty") or row.get("window") not in ("weekly", "5h"):
            continue
        epoch = reset_epoch(row.get("reset"))
        if epoch is not None and epoch > 0 and updated < epoch and now >= epoch + grace:
            result.append(epoch)
    return sorted(set(result))


class Plan:
    def __init__(self, directory, wall_clock):
        self.path = directory / "refresh-settings.json"
        self.wall_clock = wall_clock
        self.hours = 4
        self.next_run = wall_clock() + 4 * 3600
        self.reset_attempts = {}
        self.cooldown_until = 0
        self.error = None
        if self.path.exists():
            try:
                if self.path.stat().st_size > 100_000:
                    raise ValueError()
                value = json.loads(self.path.read_text(encoding="utf-8"))
                hours = value["hours"]
                next_run = value["next_run"]
                attempts = value.get("reset_attempts", {})
                cooldown = value.get("cooldown_until", 0)
                if type(hours) is not int or hours not in (0, 3, 4):
                    raise ValueError()
                if hours and (type(next_run) not in (int, float) or not math.isfinite(next_run) or next_run <= 0):
                    raise ValueError()
                if not isinstance(attempts, dict) or len(attempts) > 500:
                    raise ValueError()
                if type(cooldown) not in (int, float) or not math.isfinite(cooldown) or cooldown < 0:
                    raise ValueError()
                for key, timestamp in attempts.items():
                    if not re.fullmatch(r"[0-9a-f]{32}\.agprofile:[0-9]{1,14}", key) or type(timestamp) not in (float, int) or not math.isfinite(timestamp):
                        raise ValueError()
                self.hours = hours
                self.next_run = next_run if hours else None
                self.reset_attempts = attempts
                self.cooldown_until = cooldown
            except (ValueError, KeyError, TypeError, OSError):
                # Corrupt preferences must not silently re-enable previously disabled queries.
                self.hours = 0
                self.next_run = None
                self.error = "自动查询设置无法读取，请重新选择查询间隔。"
        else:
            self.save()

    def save(self):
        cutoff = self.wall_clock() - 7 * 86400
        self.reset_attempts = dict(sorted(((k, v) for k, v in self.reset_attempts.items() if v >= cutoff), key=lambda item: item[1])[-500:])
        value = {"hours": self.hours, "next_run": self.next_run, "reset_attempts": self.reset_attempts, "cooldown_until": self.cooldown_until}
        try:
            atomic_write(self.path, json.dumps(value).encode("utf-8"))
        except OSError:
            raise LocalError("无法保存本地自动查询设置，请检查工具数据目录权限。") from None

    def configure(self, hours):
        if type(hours) is not int or hours not in (0, 3, 4):
            raise LocalError("自动查询间隔只能选择关闭、3 小时或 4 小时。")
        previous = self.hours, self.next_run, self.error
        self.hours = hours
        self.next_run = self.wall_clock() + hours * 3600 if hours else None
        self.error = None
        try:
            self.save()
        except LocalError:
            self.hours, self.next_run, self.error = previous
            raise

    def due_keys(self, filename, cache):
        now = self.wall_clock()
        keys = [filename + ":" + str(int(epoch)) for epoch in pending_resets(cache, now, RESET_GRACE)]
        return [key for key in keys if key not in self.reset_attempts or now - self.reset_attempts[key] >= RESET_RETRY]

    def mark_attempt(self, filename, cache):
        for epoch in pending_resets(cache, self.wall_clock()):
            self.reset_attempts[filename + ":" + str(int(epoch))] = self.wall_clock()
        self.save()
