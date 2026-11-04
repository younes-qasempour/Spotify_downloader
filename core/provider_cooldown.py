"""Process-wide provider cooldown coordination shared by concurrent workers."""
import threading
import time
import math
from email.utils import parsedate_to_datetime
from typing import Callable, Optional


def retry_after_seconds(value, default: float = 30.0) -> float:
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = parsedate_to_datetime(str(value)).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            delay = default
    return max(0.0, delay) if math.isfinite(delay) else default


class ProviderCooldowns:
    def __init__(self):
        self._lock = threading.Lock()
        self._deadlines: dict[str, float] = {}
        self._waiter = threading.Event()

    def defer(self, provider: str, seconds: float) -> float:
        if not math.isfinite(seconds):
            raise ValueError("Provider cooldown must be finite.")
        deadline = time.monotonic() + max(0.0, seconds)
        with self._lock:
            self._deadlines[provider] = max(deadline, self._deadlines.get(provider, 0.0))
            return self._deadlines[provider]

    def remaining(self, provider: str) -> float:
        with self._lock:
            deadline = self._deadlines.get(provider, 0.0)
        return max(0.0, deadline - time.monotonic())

    def is_available(self, provider: str) -> bool:
        """Returns True if the provider is currently available and not in cooldown."""
        return self.remaining(provider) <= 0.0

    def wait(self, provider: str, cancel_check: Optional[Callable[[], bool]] = None) -> bool:
        while True:
            if cancel_check and cancel_check():
                return False
            delay = self.remaining(provider)
            if delay <= 0:
                return True
            self._waiter.wait(min(delay, 0.1))


provider_cooldowns = ProviderCooldowns()