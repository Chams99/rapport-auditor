from __future__ import annotations

import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from rapport_api.limiting import RedisSlidingWindowRateLimiter


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
        assert all(client.exists(f"{namespace}:active") for client in clients)

        time.sleep(2.2)
        assert limiters[0].check(address)[0] is True
    finally:
        for client in clients:
            keys = list(client.scan_iter(f"{namespace}:*"))
            if keys:
                client.delete(*keys)
            client.close()
