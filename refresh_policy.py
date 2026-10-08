"""Serialize and pace quota requests; ordinary rate limiting, not identity masking."""
import math
import threading
import time

import quota

REQUEST_INTERVAL = 2.0
ACCOUNT_INTERVAL = 5.0
ACCOUNT_COOLDOWN = 30.0
RATE_LIMIT_COOLDOWN = 60.0


class RequestGate:
    def __init__(self, sender=None, clock=None, wait=None):
        self.sender = sender if sender is not None else quota.post
        self.clock = clock if clock is not None else time.monotonic
        self.wait = wait if wait is not None else time.sleep
        self.lock = threading.Lock()
        self.last_started = None
        self.cooldown_until = 0.0

    def remaining(self):
        return max(0, math.ceil(self.cooldown_until - self.clock()))

    def send(self, url, payload, **options):
        with self.lock:
            remaining = self.remaining()
            if remaining:
                raise quota.QuotaError(f"Google 查询正在冷却，请 {remaining} 秒后再试。", 429, remaining)
            if self.last_started is not None:
                gap = REQUEST_INTERVAL - (self.clock() - self.last_started)
                if gap > 0:
                    self.wait(gap)
            self.last_started = self.clock()
            try:
                return self.sender(url, payload, **options)
            except quota.QuotaError as error:
                if error.status == 429:
                    duration = max(RATE_LIMIT_COOLDOWN, error.retry_after or 0)
                    self.cooldown_until = self.clock() + duration
                raise
