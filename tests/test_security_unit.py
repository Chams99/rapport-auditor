from __future__ import annotations

import pytest

from rapport_api.security import (
    InMemoryRateLimiter,
    is_trusted_host,
    issue_csrf_token,
    normalize_client_address,
    verify_csrf_token,
)
from rapport_api.limiting import (
    AnalysisBudgetExceeded,
    RateLimitUnavailable,
    RedisAnalysisWorkBudget,
    RedisSlidingWindowRateLimiter,
)
from redis.exceptions import RedisError


def test_csrf_token_is_bound_to_secret_cookie_and_age():
    token = issue_csrf_token("test-secret", None, now=100, max_age=10)

    assert verify_csrf_token("test-secret", token, token, now=110, max_age=10)
    assert not verify_csrf_token("other-secret", token, token, now=110, max_age=10)
    assert not verify_csrf_token("test-secret", token + "x", token, now=110, max_age=10)
    assert not verify_csrf_token("test-secret", token, "different-cookie", now=110, max_age=10)
    assert not verify_csrf_token("test-secret", token, token, now=111, max_age=10)


def test_csrf_token_rejects_tokens_from_too_far_in_the_future():
    token = issue_csrf_token("test-secret", None, now=200, max_age=60)

    assert not verify_csrf_token("test-secret", token, token, now=139, max_age=60)


def test_rate_limiter_uses_rolling_window_and_expires_at_boundary():
    limiter = InMemoryRateLimiter(limit=2, window_seconds=10, max_clients=4)

    assert limiter.check("127.0.0.1", now=0) == (True, 10, 1)
    assert limiter.check("127.0.0.1", now=2) == (True, 8, 0)
    assert limiter.check("127.0.0.1", now=3) == (False, 7, 0)
    assert limiter.check("127.0.0.1", now=10) == (True, 2, 0)


def test_rate_limiter_bounds_client_state_with_lru_eviction():
    limiter = InMemoryRateLimiter(limit=1, window_seconds=60, max_clients=2)

    assert limiter.check("a", now=0)[0]
    assert limiter.check("b", now=0)[0]
    assert limiter.check("c", now=0)[0]
    assert len(limiter._clients) <= 2
    # Capacity is deliberately bounded; eviction means this is an in-process
    # abuse throttle, not a durable per-client quota.
    assert limiter.check("a", now=0)[0]


def test_client_identity_normalizes_ip_and_discards_untrusted_strings():
    assert normalize_client_address("2001:0db8::1") == "2001:db8::1"
    assert normalize_client_address("2001:db8:0:0::1") == normalize_client_address("2001:0db8::1")
    assert normalize_client_address(None) == "unknown"
    assert normalize_client_address("not-an-ip") == "unknown"


def test_trusted_host_matching_is_case_and_trailing_dot_insensitive():
    assert is_trusted_host("LOCALHOST.", ["localhost"])
    assert not is_trusted_host("localhost.evil.invalid", ["localhost"])


def test_trusted_host_parser_rejects_path_in_authority():
    assert not is_trusted_host("localhost/path", ["localhost"])


class _RedisStub:
    def __init__(self, result=None, *, error: Exception | None = None, ping: object = True) -> None:
        self.result = result
        self.error = error
        self.ping_result = ping
        self.eval_args = None

    def eval(self, *args):
        self.eval_args = args
        if self.error:
            raise self.error
        return self.result

    def ping(self):
        if self.error:
            raise self.error
        return self.ping_result


def _redis_limiter(stub: _RedisStub) -> RedisSlidingWindowRateLimiter:
    return RedisSlidingWindowRateLimiter(
        redis_url="redis://unused.test/0",
        secret_key="a-test-secret-that-is-long-enough-for-the-hmac",
        limit=30,
        window_seconds=60,
        max_clients=128,
        client=stub,
    )


def test_redis_limiter_uses_window_retry_and_hmacs_identity():
    stub = _RedisStub([1, 60, 29])
    allowed, reset_after, remaining = _redis_limiter(stub).check("192.0.2.27")

    assert (allowed, reset_after, remaining) == (True, 60, 29)
    assert stub.eval_args is not None
    assert "192.0.2.27" not in repr(stub.eval_args)
    assert isinstance(stub.eval_args[-1], str)
    assert stub.eval_args[-1] != "192.0.2.27"


def test_redis_review_quota_applies_minute_and_hour_limits_in_one_script():
    stub = _RedisStub([1, 60, 29])
    limiter = RedisSlidingWindowRateLimiter(
        redis_url="redis://unused.test/0",
        secret_key="a-test-secret-that-is-long-enough-for-the-hmac",
        limit=30,
        window_seconds=60,
        hourly_limit=100,
        hourly_window_seconds=3600,
        attempt_limit=60,
        max_clients=128,
        client=stub,
    )

    assert limiter.check("192.0.2.27") == (True, 60, 29)
    assert stub.eval_args is not None
    assert "redis.call('TIME')" in stub.eval_args[0]
    assert stub.eval_args[2:9] == (
        "rapport-auditor:prod:reviews:" + limiter._identity("192.0.2.27"),
        "rapport-auditor:prod:active:reviews",
        60_000,
        3_600_000,
        30,
        100,
        128,
    )


def test_redis_early_attempt_quota_is_distinct_and_bounded_to_one_minute():
    stub = _RedisStub([0, 44, 0])
    limiter = RedisSlidingWindowRateLimiter(
        redis_url="redis://unused.test/0",
        secret_key="a-test-secret-that-is-long-enough-for-the-hmac",
        limit=30,
        window_seconds=60,
        hourly_limit=100,
        hourly_window_seconds=3600,
        attempt_limit=60,
        max_clients=128,
        client=stub,
    )

    assert limiter.check_early_attempt("192.0.2.28") == (False, 44, 0)
    assert stub.eval_args is not None
    assert "attempts:" in stub.eval_args[2]
    assert stub.eval_args[3] == "rapport-auditor:prod:active:attempts"
    assert stub.eval_args[4:9] == (60_000, 60_000, 60, 128, stub.eval_args[8])
    assert "192.0.2.28" not in repr(stub.eval_args)


class _SequenceRedisStub:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def eval(self, *args):
        self.calls.append(args)
        return self.results.pop(0)


def test_analysis_budget_reserves_settles_actual_duration_and_rejects_exhaustion():
    stub = _SequenceRedisStub([1, 0, 0], 1, [0, 60, 2])
    budget = RedisAnalysisWorkBudget(
        client=stub,
        namespace="rapport-auditor:test",
        budget_seconds=30,
        window_seconds=60,
        reservation_seconds=11,
        max_admissions=60,
    )

    lease = budget.reserve()
    budget.settle(lease, 1_234)
    with pytest.raises(AnalysisBudgetExceeded) as blocked:
        budget.reserve()

    assert blocked.value.retry_after == 60
    reserve_call, settle_call, _blocked_call = stub.calls
    assert reserve_call[1] == 3
    assert reserve_call[2:5] == (
        "rapport-auditor:test:analysis:starts",
        "rapport-auditor:test:analysis:completed",
        "rapport-auditor:test:analysis:active",
    )
    assert settle_call[1] == 2
    assert settle_call[5] == 1_234
    assert "192.0.2." not in repr(stub.calls)


def test_analysis_budget_fails_closed_when_lease_was_lost():
    budget = RedisAnalysisWorkBudget(
        client=_SequenceRedisStub([0]),
        namespace="rapport-auditor:test",
        budget_seconds=30,
        window_seconds=60,
        reservation_seconds=11,
        max_admissions=60,
    )

    with pytest.raises(RateLimitUnavailable, match="lease could not be settled"):
        budget.settle("a" * 32, 100)


def test_redis_limiter_rejects_active_client_capacity_without_bypassing():
    with pytest.raises(RateLimitUnavailable, match="client capacity"):
        _redis_limiter(_RedisStub([2, 1, 0])).check("192.0.2.28")


def test_redis_limiter_fails_closed_on_connection_error_without_echoing_it():
    limiter = _redis_limiter(_RedisStub(error=RedisError("private-redis-host:6379")))

    try:
        limiter.check("192.0.2.29")
    except RateLimitUnavailable as error:
        assert "private-redis-host" not in str(error)
    else:  # pragma: no cover - regression assertion
        raise AssertionError("Redis failure must fail closed.")


@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        ["unexpected", 1, 0],
        [1, "bad", 0],
        [9, 1, 0],  # Unknown status must fail closed rather than become an ordinary 429.
        [0, 0, 0],  # A blocked result must carry a positive reset duration.
        [0, 1, 1],  # Blocked results have no remaining quota.
        [1, 1, -1],
        [1, 1, 30],  # Remaining must be strictly below the configured limit.
        [1.5, 1, 0],
    ],
)
def test_redis_limiter_fails_closed_on_malformed_script_responses(result):
    with pytest.raises(RateLimitUnavailable):
        _redis_limiter(_RedisStub(result)).check("192.0.2.30")


def test_redis_limiter_readiness_is_false_when_ping_fails():
    assert not _redis_limiter(_RedisStub(error=RedisError("private-redis-host"))).ready()
