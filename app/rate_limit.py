from __future__ import annotations

from collections import defaultdict
from threading import Lock
from time import time

MAX_FAILED_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60


class LoginRateLimiter:
    """In-process limiter: 5 failed logins per IP, then a 15-minute cool-down."""

    def __init__(self, max_failed: int = MAX_FAILED_ATTEMPTS, window_seconds: int = WINDOW_SECONDS):
        self.max_failed = max_failed
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._fails: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}

    def _prune(self, ip: str, now: float) -> None:
        self._fails[ip] = [t for t in self._fails[ip] if now - t < self.window_seconds]
        until = self._locked_until.get(ip)
        if until is not None and until <= now:
            self._locked_until.pop(ip, None)

    def retry_after(self, ip: str) -> int:
        now = time()
        with self._lock:
            self._prune(ip, now)
            until = self._locked_until.get(ip, 0)
            return max(0, int(until - now))

    def is_blocked(self, ip: str) -> bool:
        return self.retry_after(ip) > 0

    def record_failure(self, ip: str) -> int:
        now = time()
        with self._lock:
            self._prune(ip, now)
            self._fails[ip].append(now)
            if len(self._fails[ip]) >= self.max_failed:
                self._locked_until[ip] = now + self.window_seconds
                return int(self.window_seconds)
            return 0

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)
            self._locked_until.pop(ip, None)


login_limiter = LoginRateLimiter()
