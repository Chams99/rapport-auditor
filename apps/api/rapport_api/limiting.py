from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry


_SLIDING_WINDOW_SCRIPT = """
local now_parts = redis.call('TIME')
local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local max_clients = tonumber(ARGV[3])
local identity = ARGV[4]
local nonce = ARGV[5]
local requests_key = KEYS[1]
local clients_key = KEYS[2]

redis.call('ZREMRANGEBYSCORE', clients_key, '-inf', now_ms)
local active = redis.call('ZSCORE', clients_key, identity)
if not active and redis.call('ZCARD', clients_key) >= max_clients then
    return {2, 1, 0}
end

redis.call('ZREMRANGEBYSCORE', requests_key, '-inf', now_ms - window_ms)
local request_count = redis.call('ZCARD', requests_key)
if request_count >= limit then
    local first = redis.call('ZRANGE', requests_key, 0, 0, 'WITHSCORES')
    local retry_ms = tonumber(first[2]) + window_ms - now_ms
    return {0, math.max(1, math.ceil(retry_ms / 1000)), 0}
end

redis.call('ZADD', requests_key, now_ms, nonce)
redis.call('PEXPIRE', requests_key, window_ms + 1000)
redis.call('ZADD', clients_key, now_ms + window_ms, identity)
redis.call('PEXPIRE', clients_key, (window_ms * 2) + 1000)
return {1, math.max(1, math.ceil(window_ms / 1000)), limit - request_count - 1}
"""


class RateLimitUnavailable(RuntimeError):
    pass


class RedisSlidingWindowRateLimiter:
    """Atomic Redis rolling-window limiter; only an HMAC of an address is stored."""

    def __init__(
        self,
        *,
        redis_url: str,
        secret_key: str | bytes,
        limit: int,
        window_seconds: int,
        max_clients: int,
        timeout_seconds: float = 0.5,
        namespace: str = "rapport-auditor:prod",
        client: Any | None = None,
    ) -> None:
        if min(limit, window_seconds, max_clients) < 1:
            raise ValueError("rate limiter settings must be positive")
        if not namespace or len(namespace) > 80 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-" for ch in namespace):
            raise ValueError("rate limit namespace must use bounded ASCII key characters")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.secret_key = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
        self.namespace = namespace
        self.client = client or Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
            health_check_interval=15,
            max_connections=16,
            retry_on_timeout=False,
            retry=Retry(NoBackoff(), retries=0),
        )

    def _identity(self, address: str) -> str:
        return hmac.new(self.secret_key, address.encode("ascii", errors="strict"), hashlib.sha256).hexdigest()

    def check(self, address: str, *, now: float | None = None) -> tuple[bool, int, int]:
        del now  # Redis TIME is authoritative across app replicas.
        identity = self._identity(address)
        requests_key = f"{self.namespace}:requests:{identity}"
        clients_key = f"{self.namespace}:active"
        nonce = secrets.token_hex(12)
        try:
            result = self.client.eval(
                _SLIDING_WINDOW_SCRIPT,
                2,
                requests_key,
                clients_key,
                self.window_seconds * 1000,
                self.limit,
                self.max_clients,
                identity,
                nonce,
            )
        except RedisError as exc:
            raise RateLimitUnavailable("rate-limit storage is unavailable") from exc
        try:
            if not isinstance(result, (list, tuple)) or len(result) != 3:
                raise ValueError("invalid result shape")
            if any(isinstance(item, bool) for item in result):
                raise ValueError("boolean result field")
            allowed_code, retry_after, remaining = (int(item) for item in result)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RateLimitUnavailable("rate-limit storage returned an invalid result") from exc
        if allowed_code == 1:
            if not 0 <= remaining < self.limit or retry_after != self.window_seconds:
                raise RateLimitUnavailable("rate-limit storage returned an invalid result")
            return True, retry_after, remaining
        if allowed_code == 0:
            if not 1 <= retry_after <= self.window_seconds or remaining != 0:
                raise RateLimitUnavailable("rate-limit storage returned an invalid result")
            return False, retry_after, 0
        if allowed_code == 2:
            if retry_after != 1 or remaining != 0:
                raise RateLimitUnavailable("rate-limit storage returned an invalid result")
            raise RateLimitUnavailable("rate-limit storage is at its client capacity")
        raise RateLimitUnavailable("rate-limit storage returned an invalid result")

    def ready(self) -> bool:
        try:
            # Exercise EVAL permission as well as connectivity: request limiting
            # relies on this command and must never silently fall back.
            return self.client.eval("return redis.call('PING')", 0) == "PONG"
        except RedisError:
            return False


__all__ = ["RateLimitUnavailable", "RedisSlidingWindowRateLimiter"]
