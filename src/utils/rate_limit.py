"""线程安全的请求速率限制工具。"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """以固定 RPM 匀速发放令牌，初始只允许立即发送一个请求。"""

    def __init__(self, rpm: float) -> None:
        rate = float(rpm)
        if rate <= 0:
            raise ValueError("Token bucket RPM must be positive")
        self.capacity = max(1, int(rate))
        self.refill_interval = 60.0 / rate
        self.tokens = 1.0
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        """阻塞直到取得一枚令牌。"""

        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                if elapsed >= self.refill_interval:
                    minted = int(elapsed / self.refill_interval)
                    self.tokens = min(self.capacity, self.tokens + minted)
                    self.last_refill += minted * self.refill_interval
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            time.sleep(min(self.refill_interval, 0.5))
