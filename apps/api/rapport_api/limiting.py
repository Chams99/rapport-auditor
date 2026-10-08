from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry


_VALID_REVIEW_SCRIPT = """
local now_parts = redis.call('TIME')
local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
local minute_ms = tonumber(ARGV[1])
local hour_ms = tonumber(ARGV[2])
local minute_limit = tonumber(ARGV[3])
local hour_limit = tonumber(ARGV[4])
local max_clients = tonumber(ARGV[5])
local nonce = ARGV[6]
local identity = ARGV[7]
local requests_key = KEYS[1]
local clients_key = KEYS[2]

if redis.call('ZCARD', requests_key) > hour_limit or redis.call('ZCARD', clients_key) > max_clients then
    return {9, 1, 0}
end
redis.call('ZREMRANGEBYSCORE', clients_key, '-inf', now_ms)
local active = redis.call('ZSCORE', clients_key, identity)
if not active and redis.call('ZCARD', clients_key) >= max_clients then
    return {2, 1, 0}
end

redis.call('ZREMRANGEBYSCORE', requests_key, '-inf', now_ms - hour_ms)
local hour_count = redis.call('ZCARD', requests_key)
local minute_cutoff = now_ms - minute_ms
local minute_count = redis.call('ZCOUNT', requests_key, '(' .. minute_cutoff, '+inf')
local retry_ms = 0

if minute_count >= minute_limit then
    local first_minute = redis.call('ZRANGEBYSCORE', requests_key, '(' .. minute_cutoff, '+inf', 'WITHSCORES', 'LIMIT', 0, 1)
    if #first_minute ~= 2 then
        return {9, 1, 0}
    end
    retry_ms = tonumber(first_minute[2]) + minute_ms - now_ms
end

if hour_count >= hour_limit then
    local first_hour = redis.call('ZRANGE', requests_key, 0, 0, 'WITHSCORES')
    if #first_hour ~= 2 then
        return {9, 1, 0}
    end
    retry_ms = math.max(retry_ms, tonumber(first_hour[2]) + hour_ms - now_ms)
end

if retry_ms > 0 then
    return {0, math.max(1, math.ceil(retry_ms / 1000)), 0}
end

redis.call('ZADD', requests_key, now_ms, nonce)
redis.call('PEXPIRE', requests_key, hour_ms + 1000)
redis.call('ZADD', clients_key, now_ms + hour_ms, identity)
redis.call('PEXPIRE', clients_key, (hour_ms * 2) + 1000)
return {1, math.max(1, math.ceil(minute_ms / 1000)), minute_limit - minute_count - 1}
"""


_EARLY_ATTEMPT_SCRIPT = """
local now_parts = redis.call('TIME')
local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
local window_ms = tonumber(ARGV[1])
local active_window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local max_clients = tonumber(ARGV[4])
local nonce = ARGV[5]
local identity = ARGV[6]
local attempts_key = KEYS[1]
local clients_key = KEYS[2]

if redis.call('ZCARD', attempts_key) > limit or redis.call('ZCARD', clients_key) > max_clients then
    return {9, 1, 0}
end
redis.call('ZREMRANGEBYSCORE', clients_key, '-inf', now_ms)
local active = redis.call('ZSCORE', clients_key, identity)
if not active and redis.call('ZCARD', clients_key) >= max_clients then
    return {2, 1, 0}
end

redis.call('ZREMRANGEBYSCORE', attempts_key, '-inf', now_ms - window_ms)
local attempt_count = redis.call('ZCARD', attempts_key)
if attempt_count >= limit then
    local first = redis.call('ZRANGE', attempts_key, 0, 0, 'WITHSCORES')
    if #first ~= 2 then
        return {9, 1, 0}
    end
    local retry_ms = tonumber(first[2]) + window_ms - now_ms
    return {0, math.max(1, math.ceil(retry_ms / 1000)), 0}
end

redis.call('ZADD', attempts_key, now_ms, nonce)
redis.call('PEXPIRE', attempts_key, window_ms + 1000)
redis.call('ZADD', clients_key, now_ms + active_window_ms, identity)
redis.call('PEXPIRE', clients_key, (active_window_ms * 2) + 1000)
return {1, math.max(1, math.ceil(window_ms / 1000)), limit - attempt_count - 1}
"""


_RESERVE_ANALYSIS_SCRIPT = """
local now_parts = redis.call('TIME')
local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
local window_ms = tonumber(ARGV[1])
local budget_ms = tonumber(ARGV[2])
local reservation_ms = tonumber(ARGV[3])
local max_admissions = tonumber(ARGV[4])
local stale_active_ms = tonumber(ARGV[5])
local token = ARGV[6]
local retry_seconds = tonumber(ARGV[7])
local starts_key = KEYS[1]
local completed_key = KEYS[2]
local active_key = KEYS[3]

if redis.call('ZCARD', starts_key) > max_admissions
    or redis.call('ZCARD', active_key) > max_admissions
    or redis.call('ZCARD', completed_key) > (max_admissions * 2) then
    return {9, 1, 7}
end
redis.call('ZREMRANGEBYSCORE', starts_key, '-inf', now_ms - window_ms)
redis.call('ZREMRANGEBYSCORE', completed_key, '-inf', now_ms - window_ms)
redis.call('ZREMRANGEBYSCORE', active_key, '-inf', now_ms - stale_active_ms)

local starts_count = redis.call('ZCARD', starts_key)
if starts_count > max_admissions then
    return {9, 1, 4}
end
if starts_count >= max_admissions then
    return {0, retry_seconds, 1}
end

local active_count = redis.call('ZCARD', active_key)
if active_count > max_admissions then
    return {9, 1, 5}
end
local completed_count = redis.call('ZCARD', completed_key)
if completed_count > (max_admissions * 2) then
    return {9, 1, 6}
end

local completed_total = 0
local completed = redis.call('ZRANGE', completed_key, 0, -1)
for _, event in ipairs(completed) do
    local cost = string.match(event, '|(%d+)$')
    if not cost then
        return {9, 1, 3}
    end
    completed_total = completed_total + tonumber(cost)
end
local reserved_total = completed_total + (active_count * reservation_ms)
if reserved_total + reservation_ms > budget_ms then
    return {0, retry_seconds, 2}
end

redis.call('ZADD', starts_key, now_ms, token)
redis.call('ZADD', active_key, now_ms, token)
redis.call('PEXPIRE', starts_key, window_ms + 1000)
redis.call('PEXPIRE', active_key, stale_active_ms + 1000)
redis.call('PEXPIRE', completed_key, window_ms + 1000)
return {1, 0, 0}
"""


_SETTLE_ANALYSIS_SCRIPT = """
local now_parts = redis.call('TIME')
local now_ms = (tonumber(now_parts[1]) * 1000) + math.floor(tonumber(now_parts[2]) / 1000)
local token = ARGV[1]
local elapsed_ms = tonumber(ARGV[2])
local completed_ttl_ms = tonumber(ARGV[3])
local active_key = KEYS[1]
local completed_key = KEYS[2]

if not redis.call('ZSCORE', active_key, token) then
    return 0
end
redis.call('ZADD', completed_key, now_ms, token .. '|' .. elapsed_ms)
redis.call('PEXPIRE', completed_key, completed_ttl_ms)
redis.call('ZREM', active_key, token)
return 1
"""


class RateLimitUnavailable(RuntimeError):
    """Raised when the shared limiter cannot safely make a decision."""


class AnalysisBudgetExceeded(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("analysis capacity is temporarily reserved")
        self.retry_after = retry_after


class RedisSlidingWindowRateLimiter:
    """Atomic Redis review/attempt quotas; only HMACs of client IPs are stored."""

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
        hourly_limit: int = 100,
        hourly_window_seconds: int = 3600,
        attempt_limit: int = 60,
        client: Any | None = None,
    ) -> None:
        if min(limit, window_seconds, max_clients, hourly_limit, hourly_window_seconds, attempt_limit) < 1:
            raise ValueError("rate limiter settings must be positive")
        if max_clients > 4096 or hourly_limit > 100 or attempt_limit > 60:
            raise ValueError("rate limiter settings exceed their bounded public profile")
        if window_seconds > hourly_window_seconds:
            raise ValueError("review minute window cannot exceed its hourly window")
        if not namespace or len(namespace) > 80 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-" for ch in namespace):
            raise ValueError("rate limit namespace must use bounded ASCII key characters")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.hourly_limit = hourly_limit
        self.hourly_window_seconds = hourly_window_seconds
        self.attempt_limit = attempt_limit
        self.secret_key = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
        self.namespace = namespace
        self.client = client if client is not None else Redis.from_url(
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

    @staticmethod
    def _parse_window_result(result: Any, *, limit: int, allowed_window: int, blocked_window: int) -> tuple[bool, int, int]:
        try:
            if not isinstance(result, (list, tuple)) or len(result) != 3:
                raise ValueError("invalid result shape")
            if any(type(item) is not int for item in result):
                raise ValueError("non-integer result field")
            code, retry_after, remaining = result
        except (TypeError, ValueError, OverflowError) as exc:
            raise RateLimitUnavailable("rate-limit storage returned an invalid result") from exc
        if code == 1:
            if not 0 <= remaining < limit or retry_after != allowed_window:
                raise RateLimitUnavailable("rate-limit storage returned an invalid result")
            return True, retry_after, remaining
        if code == 0:
            if not 1 <= retry_after <= blocked_window or remaining != 0:
                raise RateLimitUnavailable("rate-limit storage returned an invalid result")
            return False, retry_after, 0
        if code == 2:
            if retry_after != 1 or remaining != 0:
                raise RateLimitUnavailable("rate-limit storage returned an invalid result")
            raise RateLimitUnavailable("rate-limit storage is at its client capacity")
        raise RateLimitUnavailable("rate-limit storage returned an invalid result")

    def check(self, address: str, *, now: float | None = None) -> tuple[bool, int, int]:
        """Atomically apply both the per-minute and per-hour valid-review quota."""
        del now  # Redis TIME is authoritative across app replicas.
        identity = self._identity(address)
        requests_key = f"{self.namespace}:reviews:{identity}"
        clients_key = f"{self.namespace}:active:reviews"
        nonce = secrets.token_hex(12)
        try:
            result = self.client.eval(
                _VALID_REVIEW_SCRIPT,
                2,
                requests_key,
                clients_key,
                self.window_seconds * 1000,
                self.hourly_window_seconds * 1000,
                self.limit,
                self.hourly_limit,
                self.max_clients,
                nonce,
                identity,
            )
        except RedisError as exc:
            raise RateLimitUnavailable("rate-limit storage is unavailable") from exc
        return self._parse_window_result(
            result,
            limit=self.limit,
            allowed_window=self.window_seconds,
            blocked_window=self.hourly_window_seconds,
        )

    def check_early_attempt(self, address: str, *, now: float | None = None) -> tuple[bool, int, int]:
        """Count a protected POST before its content type, CSRF, or body is parsed."""
        del now
        identity = self._identity(address)
        attempts_key = f"{self.namespace}:attempts:{identity}"
        clients_key = f"{self.namespace}:active:attempts"
        nonce = secrets.token_hex(12)
        try:
            result = self.client.eval(
                _EARLY_ATTEMPT_SCRIPT,
                2,
                attempts_key,
                clients_key,
                self.window_seconds * 1000,
                self.window_seconds * 1000,
                self.attempt_limit,
                self.max_clients,
                nonce,
                identity,
            )
        except RedisError as exc:
            raise RateLimitUnavailable("rate-limit storage is unavailable") from exc
        return self._parse_window_result(
            result,
            limit=self.attempt_limit,
            allowed_window=self.window_seconds,
            blocked_window=self.window_seconds,
        )

    def ready(self) -> bool:
        try:
            # Exercise EVAL permission as well as connectivity: request limiting
            # relies on this command and must never silently fall back.
            return self.client.eval("return redis.call('PING')", 0) == "PONG"
        except RedisError:
            return False


class RedisAnalysisWorkBudget:
    """Shared rolling work budget with bounded admission and completion records."""

    def __init__(
        self,
        *,
        client: Any,
        namespace: str,
        budget_seconds: int,
        window_seconds: int,
        reservation_seconds: int,
        max_admissions: int,
    ) -> None:
        if min(budget_seconds, window_seconds, reservation_seconds, max_admissions) < 1:
            raise ValueError("analysis budget settings must be positive")
        if max_admissions > 60 or window_seconds > 60:
            raise ValueError("analysis budget settings exceed their bounded public profile")
        if reservation_seconds > budget_seconds:
            raise ValueError("analysis reservation cannot exceed the work budget")
        if not namespace or len(namespace) > 80 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:_-" for ch in namespace):
            raise ValueError("analysis budget namespace must use bounded ASCII key characters")
        self.client = client
        self.namespace = namespace
        self.budget_ms = budget_seconds * 1000
        self.window_ms = window_seconds * 1000
        self.reservation_ms = reservation_seconds * 1000
        self.window_seconds = window_seconds
        self.max_admissions = max_admissions
        self.stale_active_ms = self.window_ms + self.reservation_ms + 1000
        if window_seconds < reservation_seconds:
            raise ValueError("analysis budget window must cover one full reservation")
        self.completed_ttl_ms = self.window_ms + 1000

    def reserve(self) -> str:
        token = secrets.token_hex(16)
        starts_key = f"{self.namespace}:analysis:starts"
        completed_key = f"{self.namespace}:analysis:completed"
        active_key = f"{self.namespace}:analysis:active"
        try:
            result = self.client.eval(
                _RESERVE_ANALYSIS_SCRIPT,
                3,
                starts_key,
                completed_key,
                active_key,
                self.window_ms,
                self.budget_ms,
                self.reservation_ms,
                self.max_admissions,
                self.stale_active_ms,
                token,
                self.window_seconds,
            )
        except RedisError as exc:
            raise RateLimitUnavailable("analysis budget storage is unavailable") from exc
        try:
            if not isinstance(result, (list, tuple)) or len(result) != 3:
                raise ValueError("invalid result shape")
            if any(type(item) is not int for item in result):
                raise ValueError("non-integer result field")
            code, retry_after, reason = result
        except (TypeError, ValueError, OverflowError) as exc:
            raise RateLimitUnavailable("analysis budget storage returned an invalid result") from exc
        if code == 1 and retry_after == 0 and reason == 0:
            return token
        if code == 0 and 1 <= retry_after <= self.window_seconds and reason in {1, 2}:
            raise AnalysisBudgetExceeded(retry_after)
        raise RateLimitUnavailable("analysis budget storage returned an invalid result")

    def settle(self, lease: str, elapsed_ms: int) -> None:
        if not isinstance(lease, str) or len(lease) != 32 or any(ch not in "0123456789abcdef" for ch in lease):
            raise RateLimitUnavailable("analysis budget lease is invalid")
        if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int) or elapsed_ms < 0:
            raise RateLimitUnavailable("analysis budget duration is invalid")
        active_key = f"{self.namespace}:analysis:active"
        completed_key = f"{self.namespace}:analysis:completed"
        try:
            result = self.client.eval(
                _SETTLE_ANALYSIS_SCRIPT,
                2,
                active_key,
                completed_key,
                lease,
                elapsed_ms,
                self.completed_ttl_ms,
            )
        except RedisError as exc:
            raise RateLimitUnavailable("analysis budget storage is unavailable") from exc
        if type(result) is not int or result != 1:
            raise RateLimitUnavailable("analysis budget lease could not be settled")


__all__ = [
    "AnalysisBudgetExceeded",
    "RateLimitUnavailable",
    "RedisAnalysisWorkBudget",
    "RedisSlidingWindowRateLimiter",
]
