from __future__ import annotations

import os

import pytest
import rapport_api.config as config_module

from rapport_api import create_app
from rapport_api.config import ConfigurationError, load_environment
from rapport_api.limiting import RateLimitUnavailable
from rapport_api.workers import LocalAnalysisRunner, WorkerCapacityError


PUBLIC_HOST = "auditor.example.test"
PUBLIC_ORIGIN = f"https://{PUBLIC_HOST}"
PROXY_IP = "10.89.0.2"
TEST_PUBLIC_SECRET = "test-only-server-secret-32-bytes-minimum"


@pytest.fixture
def mock_posix_capability(monkeypatch):
    """HTTP-policy unit tests only; this does not exercise Linux resource limits."""
    monkeypatch.setattr(config_module, "supports_resource_limits", lambda: True)


class _ReadinessLimiter:
    def __init__(self, ready: bool = True) -> None:
        self._ready = ready

    def check(self, _identity: str):
        return True, 60, 29

    def ready(self) -> bool:
        return self._ready


class _UnavailableLimiter:
    def check(self, _identity: str):
        raise RateLimitUnavailable("synthetic private Redis detail")

    def ready(self) -> bool:
        return False


class _BusyHealthyRunner:
    available = False

    def ready(self) -> bool:
        return True

    def run(self, *_args):
        raise WorkerCapacityError("synthetic full worker slot")


def _valid_server_env() -> dict[str, str]:
    return {
        "RAPPORT_AUDITOR_MODE": "server",
        "RAPPORT_AUDITOR_SECRET_KEY": TEST_PUBLIC_SECRET,
        "RAPPORT_AUDITOR_TRUSTED_HOSTS": PUBLIC_HOST,
        "RAPPORT_AUDITOR_TRUSTED_ORIGINS": PUBLIC_ORIGIN,
        "RAPPORT_AUDITOR_REDIS_URL": "redis://redis.internal.test:6379/0",
        "RAPPORT_AUDITOR_TRUSTED_PROXY": PROXY_IP,
        "RAPPORT_AUDITOR_HOST": "0.0.0.0",
    }


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("RAPPORT_AUDITOR_SECRET_KEY", None, "SECRET_KEY"),
        ("RAPPORT_AUDITOR_SECRET_KEY", "short", "32 UTF-8 bytes"),
        ("RAPPORT_AUDITOR_REDIS_URL", None, "REDIS_URL"),
        ("RAPPORT_AUDITOR_REDIS_URL", "https://redis.invalid", "redis://"),
        ("RAPPORT_AUDITOR_TRUSTED_HOSTS", "", "TRUSTED_HOSTS"),
        ("RAPPORT_AUDITOR_TRUSTED_HOSTS", "*", "unsupported value"),
        ("RAPPORT_AUDITOR_TRUSTED_HOSTS", "https://auditor.example.test", "hostname"),
        ("RAPPORT_AUDITOR_TRUSTED_ORIGINS", "http://auditor.example.test", "HTTPS"),
        ("RAPPORT_AUDITOR_TRUSTED_ORIGINS", "https://auditor.example.test/path", "HTTPS origins"),
        ("RAPPORT_AUDITOR_TRUSTED_PROXY", "", "exact proxy IP"),
        ("RAPPORT_AUDITOR_TRUSTED_PROXY", "10.89.0.0/24", "exact proxy IP"),
        ("RAPPORT_AUDITOR_HOST", "attacker-host", "IP bind address"),
        ("RAPPORT_AUDITOR_RATE_LIMIT_MAX_REQUESTS", "0", "supported range"),
        ("RAPPORT_AUDITOR_WORKER_CPU_SECONDS", "10", "CPU limit"),
    ],
)
def test_server_profile_rejects_missing_or_unsafe_configuration(name, value, message):
    env = _valid_server_env()
    if value is None:
        env.pop(name)
    else:
        env[name] = value

    with pytest.raises(ConfigurationError, match=message):
        load_environment(env)


@pytest.mark.skipif(os.name != "posix", reason="Server startup deliberately requires POSIX worker resource limits.")
def test_server_profile_accepts_complete_linux_configuration_and_canonicalizes_origin():
    loaded = load_environment(_valid_server_env())

    assert loaded["APP_MODE"] == "server"
    assert loaded["HOST"] == "0.0.0.0"
    assert loaded["COOKIE_SECURE"] is True
    assert loaded["TRUSTED_ORIGINS"] == (PUBLIC_ORIGIN,)
    assert loaded["TRUSTED_PROXY"] == PROXY_IP


def _server_test_app(*, limiter_ready: bool = True):
    app = create_app(
        {
            "TESTING": True,
            "APP_MODE": "server",
            "SECRET_KEY": TEST_PUBLIC_SECRET,
            "COOKIE_SECURE": True,
            "TRUSTED_HOSTS": (PUBLIC_HOST,),
            "TRUSTED_ORIGINS": (PUBLIC_ORIGIN,),
            "TRUSTED_PROXY": PROXY_IP,
            "REDIS_URL": "redis://redis.internal.test:6379/0",
            "RATE_LIMITER": _ReadinessLimiter(limiter_ready),
            "ANALYSIS_RUNNER": LocalAnalysisRunner(),
        }
    )
    return app


def test_server_profile_sets_secure_cookie_hsts_request_id_and_no_store(mock_posix_capability):
    client = _server_test_app().test_client()
    response = client.get("/", base_url=PUBLIC_ORIGIN)

    assert response.status_code == 200
    cookie = response.headers["Set-Cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
    assert response.headers["X-Request-ID"]
    assert "no-store" in response.headers["Cache-Control"]


def test_server_live_stays_healthy_while_readiness_fails_closed_on_limiter_outage(mock_posix_capability):
    client = _server_test_app(limiter_ready=False).test_client()

    live = client.get("/api/v1/health/live", base_url=PUBLIC_ORIGIN)
    ready = client.get("/api/v1/health/ready", base_url=PUBLIC_ORIGIN)

    assert live.status_code == 200
    assert live.get_json() == {"status": "live"}
    assert ready.status_code == 503
    assert ready.get_json() == {"status": "not_ready"}
    assert "redis" not in ready.get_data(as_text=True).lower()


def test_server_readiness_stays_healthy_when_worker_is_busy_but_new_work_is_rejected(mock_posix_capability):
    app = _server_test_app()
    app.extensions["rapport_auditor.analysis_runner"] = _BusyHealthyRunner()
    client = app.test_client()
    bootstrap = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN)
    token = bootstrap.get_json()["csrf_token"]

    ready = client.get("/api/v1/health/ready", base_url=PUBLIC_ORIGIN)
    audit = client.post(
        "/api/v1/audit",
        json={"text": "Synthetic capacity check.", "content_language": "en"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )

    assert ready.status_code == 200
    assert ready.get_json() == {"status": "ready"}
    assert audit.status_code == 503
    assert audit.get_json()["error"]["code"] == "service_unavailable"


def test_server_origin_rejection_has_non_content_request_id_and_no_secret(mock_posix_capability):
    client = _server_test_app().test_client()
    token = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN).get_json()["csrf_token"]
    response = client.post(
        "/api/v1/audit",
        json={"text": "Synthetic request only."},
        headers={"Origin": "https://attacker.example.test", "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "origin_rejected"
    assert response.get_json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert TEST_PUBLIC_SECRET.encode() not in response.data


def test_server_origin_allowlist_rejects_opaque_and_cross_origin_posts(mock_posix_capability):
    client = _server_test_app().test_client()
    bootstrap = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN)
    token = bootstrap.get_json()["csrf_token"]
    headers = {"X-CSRF-Token": token}

    for origin in ("null", "https://attacker.example.test"):
        response = client.post(
            "/api/v1/audit",
            json={"text": "Synthetic request only."},
            headers={**headers, "Origin": origin},
            base_url=PUBLIC_ORIGIN,
        )
        assert response.status_code == 403
        assert response.get_json()["error"]["code"] == "origin_rejected"
        assert response.get_json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_server_profile_ignores_forged_forwarded_host_for_host_validation(mock_posix_capability):
    client = _server_test_app().test_client()
    response = client.get(
        "/api/v1/health/live",
        base_url="https://attacker.example.test",
        headers={"X-Forwarded-Host": PUBLIC_HOST, "X-Forwarded-Proto": "https"},
    )

    assert response.status_code == 400


def test_server_profile_returns_generic_503_when_shared_limiter_is_unavailable(mock_posix_capability):
    app = _server_test_app()
    app.extensions["rapport_auditor.rate_limiter"] = _UnavailableLimiter()
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN).get_json()["csrf_token"]

    response = client.post(
        "/api/v1/audit",
        json={"text": "Synthetic outage test.", "content_language": "en"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "service_unavailable"
    assert "synthetic private Redis detail" not in response.get_data(as_text=True)
