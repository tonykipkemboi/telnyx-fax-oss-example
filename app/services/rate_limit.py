from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock


class SlidingWindowRateLimiter:
    def __init__(self):
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, max_events: int, window_seconds: int) -> bool:
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=window_seconds)

        with self._lock:
            queue = self._events[key]
            while queue and queue[0] < cutoff:
                queue.popleft()

            if len(queue) >= max_events:
                return False

            queue.append(now)
            return True
