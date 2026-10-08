from __future__ import annotations

import os
import secrets
import time
from types import SimpleNamespace

import pytest

from rapport_api.limiting import (
    AnalysisBudgetExceeded,
    RateLimitUnavailable,
    RedisAnalysisWorkBudget,
    RedisSlidingWindowRateLimiter,
)


@pytest.fixture
def abuse_redis():
    """Use a disposable real Redis when configured, with an optional Lua fake fallback."""
    redis_url = os.environ.get("RAPPORT_AUDITOR_TEST_REDIS_URL")
    clients = []
    if redis_url:
        from redis import Redis

        def make_client():
            return Redis.from_url(redis_url, decode_responses=True)

        is_real_redis = True
    else:
        fakeredis = pytest.importorskip("fakeredis", reason="Set RAPPORT_AUDITOR_TEST_REDIS_URL or install fakeredis for Lua-emulation tests.")
        pytest.importorskip("lupa", reason="fakeredis Lua emulation requires lupa.")
        server = fakeredis.FakeServer()

        def make_client():
            return fakeredis.FakeRedis(server=server, decode_responses=True)

        is_real_redis = False

    namespace = f"rapport-abuse-regression:{secrets.token_hex(8)}"

    def client_factory():
        client = make_client()
        clients.append(client)
        if is_real_redis:
            client.ping()
        return client

    yield SimpleNamespace(client=client_factory, namespace=namespace, real=is_real_redis)

    for client in clients:
        try:
            keys = list(client.scan_iter(f"{namespace}:*"))
            if keys:
                client.delete(*keys)
        finally:
            client.close()


def _limiter(client, namespace: str) -> RedisSlidingWindowRateLimiter:
    return RedisSlidingWindowRateLimiter(
        redis_url="redis://unused.test/0",
        secret_key=b"test-only-abuse-key-with-32-bytes",
        limit=2,
        window_seconds=60,
        max_clients=16,
        namespace=namespace,
        hourly_limit=2,
        hourly_window_seconds=3600,
        attempt_limit=2,
        client=client,
    )


def _budget(
    client,
    namespace: str,
    *,
    budget_seconds: int = 1,
    window_seconds: int = 60,
    reservation_seconds: int = 1,
    max_admissions: int = 8,
) -> RedisAnalysisWorkBudget:
    return RedisAnalysisWorkBudget(
        client=client,
        namespace=namespace,
        budget_seconds=budget_seconds,
        window_seconds=window_seconds,
        reservation_seconds=reservation_seconds,
        max_admissions=max_admissions,
    )


def test_ip_review_and_early_attempt_windows_are_shared_and_store_no_raw_address(abuse_redis):
    first = _limiter(abuse_redis.client(), abuse_redis.namespace)
    second = _limiter(abuse_redis.client(), abuse_redis.namespace)
    address = "198.51.100.91"

    assert first.check(address) == (True, 60, 1)
    assert second.check(address) == (True, 60, 0)
    allowed, retry_after, remaining = first.check(address)
    assert (allowed, remaining) == (False, 0)
    assert 1 <= retry_after <= 3600

    assert first.check_early_attempt(address) == (True, 60, 1)
    assert second.check_early_attempt(address) == (True, 60, 0)
    allowed, retry_after, remaining = first.check_early_attempt(address)
    assert (allowed, remaining) == (False, 0)
    assert 1 <= retry_after <= 60

    reader = abuse_redis.client()
    keys = list(reader.scan_iter(f"{abuse_redis.namespace}:*"))
    stored_values = []
    for key in keys:
        kind = reader.type(key)
        if kind == "zset":
            stored_values.extend(reader.zrange(key, 0, -1))
        elif kind == "hash":
            stored_values.extend(reader.hgetall(key).items())
        elif kind == "string":
            stored_values.append(reader.get(key))
    stored_state = " ".join([*(str(key) for key in keys), *(str(value) for value in stored_values)])
    assert address not in stored_state


def test_completed_work_is_charged_from_settlement_time_across_window_boundary(abuse_redis):
    budget = _budget(
        abuse_redis.client(),
        abuse_redis.namespace,
        budget_seconds=1,
        window_seconds=1,
        reservation_seconds=1,
    )
    lease = budget.reserve()

    # The start admission expires before completion. Its work must still count
    # in the rolling window because the cost is timestamped when it settles.
    time.sleep(1.1)
    budget.settle(lease, 1000)
    with pytest.raises(AnalysisBudgetExceeded):
        budget.reserve()

    time.sleep(1.1)
    after_expiry = budget.reserve()
    budget.settle(after_expiry, 0)


def test_work_lease_rejects_wrong_and_duplicate_settlement(abuse_redis):
    budget = _budget(abuse_redis.client(), abuse_redis.namespace)
    lease = budget.reserve()
    wrong_lease = "0" * 32 if lease != "0" * 32 else "1" * 32

    with pytest.raises(RateLimitUnavailable):
        budget.settle(wrong_lease, 0)
    with pytest.raises(AnalysisBudgetExceeded):
        budget.reserve()

    budget.settle(lease, 0)
    with pytest.raises(RateLimitUnavailable):
        budget.settle(lease, 0)


def test_failed_wrongtype_settlement_keeps_the_full_active_reservation(abuse_redis):
    client = abuse_redis.client()
    budget = _budget(client, abuse_redis.namespace, budget_seconds=1)
    lease = budget.reserve()
    completed_key = f"{abuse_redis.namespace}:analysis:completed"
    active_key = f"{abuse_redis.namespace}:analysis:active"

    client.set(completed_key, "wrong type")
    with pytest.raises(RateLimitUnavailable):
        budget.settle(lease, 0)
    assert client.zscore(active_key, lease) is not None

    # Remove only the deliberately malformed key. The original active lease
    # must continue blocking work until it can be settled successfully.
    client.delete(completed_key)
    with pytest.raises(AnalysisBudgetExceeded):
        budget.reserve()
    budget.settle(lease, 0)
    replacement = budget.reserve()
    budget.settle(replacement, 0)


def test_oversized_stale_completion_ledger_fails_closed_before_pruning(abuse_redis):
    max_admissions = 4
    client = abuse_redis.client()
    budget = _budget(
        client,
        abuse_redis.namespace,
        budget_seconds=10,
        window_seconds=1,
        reservation_seconds=1,
        max_admissions=max_admissions,
    )
    completed_key = f"{abuse_redis.namespace}:analysis:completed"
    client.zadd(
        completed_key,
        {f"{index:032x}|0": 0 for index in range(max_admissions * 2 + 1)},
    )

    with pytest.raises(RateLimitUnavailable):
        budget.reserve()
    assert client.zcard(completed_key) == max_admissions * 2 + 1


def test_global_admission_ledger_stays_bounded_under_repeated_zero_cost_work(abuse_redis):
    max_admissions = 4
    budget = _budget(
        abuse_redis.client(),
        abuse_redis.namespace,
        budget_seconds=10,
        window_seconds=60,
        reservation_seconds=1,
        max_admissions=max_admissions,
    )
    admitted = 0
    for _ in range(100):
        try:
            lease = budget.reserve()
        except AnalysisBudgetExceeded:
            break
        budget.settle(lease, 0)
        admitted += 1

    assert admitted == max_admissions
    starts_key = f"{abuse_redis.namespace}:analysis:starts"
    assert abuse_redis.client().zcard(starts_key) == max_admissions


def test_work_budget_fails_closed_on_fractional_reservation_result():
    class MalformedRedis:
        def eval(self, *_args):
            return [1.5, 0, 0]

    budget = _budget(MalformedRedis(), "rapport-abuse-malformed-result")

    with pytest.raises(RateLimitUnavailable):
        budget.reserve()
