"""Lightweight in-process sliding-window rate limiter (per identity+bucket).

For multi-instance deployments set task_backend=celery / wire Redis and swap the
store — the interface stays the same.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import ApiError

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_MAX_BUCKETS = 50_000


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    with _lock:
        if len(_hits) > _MAX_BUCKETS:  # crude memory guard
            _hits.clear()
        dq = _hits[key]
        while dq and now - dq[0] > window_seconds:
            dq.popleft()
        if len(dq) >= limit:
            raise ApiError(
                code="RATE_LIMITED",
                message_uz="Juda ko'p so'rov yuborildi. Iltimos, birozdan so'ng qayta urinib ko'ring.",
                http_status=429,
            )
        dq.append(now)


def limit(request: Request, bucket: str, limit_count: int, window_seconds: int, user_id: str | None = None):
    identity = user_id or client_ip(request)
    check_rate_limit(f"{bucket}:{identity}", limit_count, window_seconds)
