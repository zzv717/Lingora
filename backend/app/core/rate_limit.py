"""Sliding-window rate limiter: in-process (default) with optional Redis backend for production.
Also provides secure client IP detection that does NOT blindly trust X-Forwarded-For.
"""
import ipaddress
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings
from app.core.errors import ApiError

log = logging.getLogger("lingora.rate_limit")

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_MAX_BUCKETS = 50_000

# Optional Redis client cached
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None and settings.redis_url:
        try:
            import redis

            _redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            _redis_client.ping()
        except Exception as e:
            log.warning("Redis rate limiter connection failed (%s); falling back to in-memory", e)
            _redis_client = False
    return _redis_client if _redis_client is not False else None


def client_ip(request: Request) -> str:
    """Extract client IP, trusting X-Forwarded-For ONLY if coming from a trusted proxy."""
    direct_ip = request.client.host if request.client else "127.0.0.1"

    trusted_raw = [p.strip() for p in settings.trusted_proxies.split(",") if p.strip()]
    if not trusted_raw:
        # No trusted proxy configured -> NEVER trust X-Forwarded-For
        return direct_ip

    if "*" in trusted_raw:
        # Trust any proxy header (e.g. cloud provider ingress)
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return direct_ip

    # Verify if direct_ip matches any trusted proxy IP or subnet
    is_trusted = False
    try:
        direct_obj = ipaddress.ip_address(direct_ip)
        for t in trusted_raw:
            if "/" in t:
                if direct_obj in ipaddress.ip_network(t, strict=False):
                    is_trusted = True
                    break
            elif direct_ip == t:
                is_trusted = True
                break
    except ValueError:
        is_trusted = False

    if is_trusted:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            # take first non-trusted client IP from right or simple leftmost
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if parts:
                return parts[0]

    return direct_ip


def check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    r = _get_redis()
    if r is not None:
        try:
            now = time.time()
            pipe = r.pipeline()
            redis_key = f"rl:{key}"
            pipe.zremrangebyscore(redis_key, 0, now - window_seconds)
            pipe.zadd(redis_key, {f"{now}": now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds + 5)
            _, _, count, _ = pipe.execute()
            if count > limit:
                raise ApiError(
                    code="RATE_LIMITED",
                    message_uz="Juda ko'p so'rov yuborildi. Iltimos, birozdan so'ng qayta urinib ko'ring.",
                    http_status=429,
                )
            return
        except ApiError:
            raise
        except Exception as e:
            log.warning("Redis rate limit failed (%s); falling back to in-memory", e)

    # In-memory fallback
    now = time.monotonic()
    with _lock:
        if len(_hits) > _MAX_BUCKETS:
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
