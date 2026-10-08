from __future__ import annotations

import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from rapport_api.limiting import AnalysisBudgetExceeded, RedisAnalysisWorkBudget, RedisSlidingWindowRateLimiter


@pytest.fixture
def real_redis_url() -> str:
    value = os.environ.get("RAPPORT_AUDITOR_TEST_REDIS_URL")
    if not value:
        pytest.skip("Set RAPPORT_AUDITOR_TEST_REDIS_URL to a disposable Redis database for live integration.")
    return value


def test_real_redis_enforces_one_atomic_window_across_limiter_instances(real_redis_url):
    from redis import Redis

    namespace = "rapport-auditor-test:" + secrets.token_hex(8)
    secret = secrets.token_bytes(32)
    clients = [Redis.from_url(real_redis_url, decode_responses=True) for _ in range(4)]
    limiters = [
        RedisSlidingWindowRateLimiter(
            redis_url=real_redis_url,
            secret_key=secret,
            limit=5,
            window_seconds=2,
            max_clients=64,
            timeout_seconds=0.5,
            namespace=namespace,
        )
        for _ in clients
    ]
    address = "198.51.100.27"
    identities = {limiter._identity(address) for limiter in limiters}
    assert len(identities) == 1

    try:
        def submit(index: int):
            return limiters[index % len(limiters)].check(address)

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(submit, range(20)))

        assert sum(1 for allowed, _retry, _remaining in results if allowed) == 5
        assert all(retry >= 1 for _allowed, retry, _remaining in results)
        assert all("198.51.100.27" not in key for client in clients for key in client.scan_iter(f"{namespace}:*"))
        assert all(client.exists(f"{namespace}:active:reviews") for client in clients)

        time.sleep(2.2)
        assert limiters[0].check(address)[0] is True
    finally:
        for client in clients:
            keys = list(client.scan_iter(f"{namespace}:*"))
            if keys:
                client.delete(*keys)
            client.close()


def test_real_redis_applies_minute_and_hour_review_quotas_atomically(real_redis_url):
    from redis import Redis

    namespace = "rapport-auditor-hour-test:" + secrets.token_hex(8)
    clients = [Redis.from_url(real_redis_url, decode_responses=True) for _ in range(4)]
    limiters = [
        RedisSlidingWindowRateLimiter(
            redis_url=real_redis_url,
            secret_key=b"hourly-review-test-secret-32-bytes",
            limit=10,
            window_seconds=2,
            hourly_limit=3,
            hourly_window_seconds=6,
            attempt_limit=8,
            max_clients=64,
            namespace=namespace,
            client=clients[index],
        )
        for index in range(len(clients))
    ]

    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            first_window = list(executor.map(lambda i: limiters[i % 4].check("198.51.100.38"), range(12)))
        assert sum(allowed for allowed, _retry, _remaining in first_window) == 3
        assert all(retry >= 1 for _allowed, retry, _remaining in first_window)

        time.sleep(2.2)
        hourly_block = limiters[0].check("198.51.100.38")
        assert hourly_block[0] is False
        assert 1 <= hourly_block[1] <= 6

        time.sleep(4.1)
        assert limiters[1].check("198.51.100.38")[0] is True
        assert all(
            "198.51.100.38" not in key
            for client in clients
            for key in client.scan_iter(f"{namespace}:*")
        )
    finally:
        for client in clients:
            keys = list(client.scan_iter(f"{namespace}:*"))
            if keys:
                client.delete(*keys)
            client.close()


def test_real_redis_bounds_unvalidated_post_attempts_separately(real_redis_url):
    from redis import Redis

    namespace = "rapport-auditor-attempt-test:" + secrets.token_hex(8)
    client = Redis.from_url(real_redis_url, decode_responses=True)
    limiter = RedisSlidingWindowRateLimiter(
        redis_url=real_redis_url,
        secret_key=b"attempt-window-test-secret-32-bytes",
        limit=30,
        window_seconds=2,
        hourly_limit=100,
        hourly_window_seconds=8,
        attempt_limit=3,
        max_clients=64,
        namespace=namespace,
        client=client,
    )

    try:
        assert [limiter.check_early_attempt("198.51.100.41")[0] for _ in range(3)] == [True, True, True]
        blocked = limiter.check_early_attempt("198.51.100.41")
        assert blocked[0] is False and 1 <= blocked[1] <= 2
        # Attempt throttling and valid-review quotas use different bounded sets.
        assert limiter.check("198.51.100.41")[0] is True
        time.sleep(2.2)
        assert limiter.check_early_attempt("198.51.100.41")[0] is True
    finally:
        keys = list(client.scan_iter(f"{namespace}:*"))
        if keys:
            client.delete(*keys)
        client.close()


def test_real_redis_global_work_budget_is_atomic_and_reflects_settled_wall_time(real_redis_url):
    from redis import Redis

    namespace = "rapport-auditor-budget-test:" + secrets.token_hex(8)
    clients = [Redis.from_url(real_redis_url, decode_responses=True) for _ in range(4)]
    budgets = [
        RedisAnalysisWorkBudget(
            client=client,
            namespace=namespace,
            budget_seconds=4,
            window_seconds=2,
            reservation_seconds=2,
            max_admissions=10,
        )
        for client in clients
    ]

    try:
        def reserve(index: int):
            try:
                return budgets[index % len(budgets)].reserve()
            except AnalysisBudgetExceeded:
                return None

        with ThreadPoolExecutor(max_workers=12) as executor:
            leases = list(executor.map(reserve, range(12)))
        accepted = [lease for lease in leases if lease is not None]
        assert len(accepted) == 2
        assert all("198.51.100." not in key for client in clients for key in client.scan_iter(f"{namespace}:*"))

        for index, lease in enumerate(accepted):
            budgets[index].settle(lease, 1_500)
        with pytest.raises(AnalysisBudgetExceeded):
            budgets[2].reserve()
        time.sleep(2.2)
        replacement = budgets[3].reserve()
        budgets[3].settle(replacement, 0)
    finally:
        for client in clients:
            keys = list(client.scan_iter(f"{namespace}:*"))
            if keys:
                client.delete(*keys)
            client.close()
