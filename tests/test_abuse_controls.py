from __future__ import annotations

import pytest

import rapport_api.config as config_module
from rapport_api import create_app
from rapport_api.limiting import AnalysisBudgetExceeded, RateLimitUnavailable
from rapport_api.security import BoundedMemoryRequest
from rapport_api.workers import WorkerCapacityError, WorkerFailure, WorkerTimeoutError


PUBLIC_HOST = "auditor.example.test"
PUBLIC_ORIGIN = f"https://{PUBLIC_HOST}"
PROXY_IP = "10.89.0.2"
PUBLIC_SECRET = "test-only-server-secret-32-bytes-minimum"


class _Limiter:
    def __init__(self, *, early=(True, 60, 59), review=(True, 60, 29), early_error=None):
        self.early_result = early
        self.review_result = review
        self.early_error = early_error
        self.early_calls = []
        self.review_calls = []
        self.is_ready = True

    def check_early_attempt(self, address):
        self.early_calls.append(address)
        if self.early_error:
            raise self.early_error
        return self.early_result

    def check(self, address):
        self.review_calls.append(address)
        return self.review_result

    def ready(self):
        return self.is_ready


class _Budget:
    def __init__(self, *, blocked: bool = False, retry_after: int = 17):
        self.blocked = blocked
        self.retry_after = retry_after
        self.reservations = 0
        self.settlements = []

    def reserve(self):
        self.reservations += 1
        if self.blocked:
            raise AnalysisBudgetExceeded(self.retry_after)
        return "b" * 32

    def settle(self, lease: str, elapsed_ms: int):
        self.settlements.append((lease, elapsed_ms))


class _FailOnceBudget(_Budget):
    def settle(self, lease: str, elapsed_ms: int):
        super().settle(lease, elapsed_ms)
        if len(self.settlements) == 1:
            raise RateLimitUnavailable("synthetic transient settlement failure")


class _CapacityRunner:
    available = True

    def __init__(self):
        self.calls = 0

    def ready(self):
        return True

    def run(self, *_args):
        self.calls += 1
        raise WorkerCapacityError("synthetic occupied slot")


class _FailingRunner:
    available = True

    def __init__(self, error):
        self.error = error

    def ready(self):
        return True

    def run(self, *_args):
        raise self.error


def _server_app(monkeypatch, *, limiter: _Limiter | None = None, budget: _Budget | None = None, runner=None):
    monkeypatch.setattr(config_module, "supports_resource_limits", lambda: True)
    limiter = limiter or _Limiter()
    budget = budget or _Budget()
    app = create_app(
        {
            "TESTING": True,
            "APP_MODE": "server",
            "SECRET_KEY": PUBLIC_SECRET,
            "COOKIE_SECURE": True,
            "TRUSTED_HOSTS": (PUBLIC_HOST,),
            "TRUSTED_ORIGINS": (PUBLIC_ORIGIN,),
            "TRUSTED_PROXY": PROXY_IP,
            "REDIS_URL": "redis://redis.internal.test:6379/0",
            "RATE_LIMITER": limiter,
            "REVIEW_QUOTA": limiter,
            "EARLY_ATTEMPT_LIMITER": limiter,
            "ANALYSIS_BUDGET": budget,
            "ANALYSIS_RUNNER": runner,
        }
    )
    return app, limiter, budget


def test_early_attempt_limit_rejects_before_body_or_csrf_parsing(monkeypatch):
    limiter = _Limiter(early=(False, 23, 0))
    app, limiter, _budget = _server_app(monkeypatch, limiter=limiter)

    def forbidden_form(_self):
        raise AssertionError("early limiter must not parse request.form")

    monkeypatch.setattr(BoundedMemoryRequest, "form", property(forbidden_form))
    response = app.test_client().post(
        "/audit",
        data="synthetic draft must not be echoed",
        content_type="text/plain",
        headers={"X-Rapport-Locale": "fr", "X-Rapport-Enhanced-Request": "1"},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 429
    assert response.is_json
    assert response.json["error"]["code"] == "attempt_rate_limited"
    assert response.json["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "Trop de tentatives" in response.json["error"]["message"]
    assert response.headers["Retry-After"] == "23"
    assert b"synthetic draft" not in response.data
    assert limiter.early_calls == ["127.0.0.1"]


def test_native_html_early_rejection_is_localized_and_body_free(monkeypatch):
    limiter = _Limiter(early=(False, 19, 0))
    app, _limiter, _budget = _server_app(monkeypatch, limiter=limiter)

    def forbidden_form(_self):
        raise AssertionError("native early rejection must not parse request.form")

    monkeypatch.setattr(BoundedMemoryRequest, "form", property(forbidden_form))
    response = app.test_client().post(
        "/revise",
        data="confidential synthetic draft",
        content_type="text/plain",
        headers={"Accept": "text/html", "Accept-Language": "fr"},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 429
    assert response.mimetype == "text/html"
    assert '<html lang="fr">' in response.get_data(as_text=True)
    assert "Trop de tentatives" in response.get_data(as_text=True)
    assert "confidential synthetic draft" not in response.get_data(as_text=True)
    assert response.headers["Retry-After"] == "19"


def test_early_attempt_storage_failure_is_body_free_fail_closed_503(monkeypatch):
    limiter = _Limiter(early_error=RateLimitUnavailable("private redis detail"))
    app, _limiter, _budget = _server_app(monkeypatch, limiter=limiter)

    def forbidden_form(_self):
        raise AssertionError("early limiter outage must not parse request.form")

    monkeypatch.setattr(BoundedMemoryRequest, "form", property(forbidden_form))
    response = app.test_client().post(
        "/api/v1/audit",
        data="not JSON and must not be parsed",
        content_type="text/plain",
        headers={"Accept-Language": "fr"},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 503
    assert response.is_json
    assert response.json["error"]["code"] == "service_unavailable"
    assert "Redis" not in response.get_data(as_text=True)
    assert "Retry-After" not in response.headers
    assert b"must not be parsed" not in response.data


def test_early_attempt_counts_origin_and_csrf_failures_before_rejection(monkeypatch):
    app, limiter, _budget = _server_app(monkeypatch)
    client = app.test_client()
    wrong_origin = client.post(
        "/api/v1/audit",
        json={"text": "synthetic"},
        headers={"Origin": "https://attacker.example.test", "X-CSRF-Token": "invalid"},
        base_url=PUBLIC_ORIGIN,
    )
    missing_csrf = client.post(
        "/api/v1/audit",
        json={"text": "synthetic"},
        headers={"Origin": PUBLIC_ORIGIN},
        base_url=PUBLIC_ORIGIN,
    )

    assert wrong_origin.status_code == 403
    assert wrong_origin.json["error"]["code"] == "origin_rejected"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json["error"]["code"] == "csrf_failed"
    assert limiter.early_calls == ["127.0.0.1", "127.0.0.1"]


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "expected_code"),
    [
        ("POST", "/not-a-route", 404, "not_found"),
        ("PUT", "/api/v1/audit", 405, "method_not_allowed"),
    ],
)
def test_unrouted_mutating_requests_reject_without_parsing_or_charging(monkeypatch, method, path, expected_status, expected_code):
    app, limiter, _budget = _server_app(monkeypatch)

    def forbidden_form(_self):
        raise AssertionError("unrouted mutating request must not parse request.form")

    monkeypatch.setattr(BoundedMemoryRequest, "form", property(forbidden_form))
    response = app.test_client().open(
        path,
        method=method,
        data="malformed arbitrary content",
        content_type="text/plain",
        headers={"Accept": "application/json"},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == expected_status
    assert response.json["error"]["code"] == expected_code
    assert limiter.early_calls == []
    assert b"malformed arbitrary content" not in response.data


def test_valid_review_quota_still_runs_after_validation_and_returns_retry_after(monkeypatch):
    limiter = _Limiter(review=(False, 41, 0))
    app, limiter, budget = _server_app(monkeypatch, limiter=limiter)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN).json["csrf_token"]
    response = client.post(
        "/api/v1/audit",
        json={"text": "synthetic valid report"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 429
    assert response.json["error"]["code"] == "rate_limited"
    assert response.headers["Retry-After"] == "41"
    assert limiter.early_calls == ["127.0.0.1"]
    assert limiter.review_calls == ["127.0.0.1"]
    assert budget.reservations == 0


def test_global_work_budget_returns_retry_after_without_readiness_failure(monkeypatch):
    runner = _CapacityRunner()
    budget = _Budget(blocked=True, retry_after=17)
    app, _limiter, budget = _server_app(monkeypatch, budget=budget, runner=runner)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN).json["csrf_token"]
    response = client.post(
        "/api/v1/audit",
        json={"text": "synthetic valid report"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )
    ready = client.get("/api/v1/health/ready", base_url=PUBLIC_ORIGIN)

    assert response.status_code == 503
    assert response.json["error"]["code"] == "analysis_busy"
    assert response.headers["Retry-After"] == "17"
    assert runner.calls == 0
    assert budget.reservations == 1
    assert ready.status_code == 200
    assert ready.json == {"status": "ready"}


def test_capacity_rejection_refunds_global_work_but_keeps_attempt_quota(monkeypatch):
    runner = _CapacityRunner()
    app, limiter, budget = _server_app(monkeypatch, runner=runner)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN).json["csrf_token"]
    response = client.post(
        "/api/v1/audit",
        json={"text": "synthetic valid report"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 503
    assert response.json["error"]["code"] == "service_unavailable"
    assert runner.calls == 1
    assert budget.reservations == 1
    assert budget.settlements == [("b" * 32, 0)]
    assert limiter.early_calls == ["127.0.0.1"]
    assert limiter.review_calls == ["127.0.0.1"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (WorkerFailure("synthetic child exit"), 503, "service_unavailable"),
        (WorkerTimeoutError("synthetic deadline"), 504, "analysis_timeout"),
    ],
)
def test_worker_failure_or_timeout_consumes_full_budget_reservation(monkeypatch, error, status, code):
    budget = _Budget()
    app, _limiter, budget = _server_app(monkeypatch, budget=budget, runner=_FailingRunner(error))
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN).json["csrf_token"]
    response = client.post(
        "/api/v1/audit",
        json={"text": "synthetic valid report"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == status
    assert response.json["error"]["code"] == code
    assert budget.settlements == [("b" * 32, 11_000)]


@pytest.mark.parametrize(
    ("runner_kind", "settlement_ms"),
    [("capacity", 0), ("failure", 11_000), ("timeout", 11_000)],
)
def test_failed_budget_settlement_is_never_retried_with_a_different_charge(
    monkeypatch, runner_kind, settlement_ms
):
    budget = _FailOnceBudget()
    if runner_kind == "capacity":
        runner = _CapacityRunner()
    else:
        error = WorkerFailure("synthetic child exit") if runner_kind == "failure" else WorkerTimeoutError(
            "synthetic deadline"
        )
        runner = _FailingRunner(error)
    app, _limiter, budget = _server_app(monkeypatch, budget=budget, runner=runner)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=PUBLIC_ORIGIN).json["csrf_token"]

    response = client.post(
        "/api/v1/audit",
        json={"text": "synthetic valid report"},
        headers={"Origin": PUBLIC_ORIGIN, "X-CSRF-Token": token},
        base_url=PUBLIC_ORIGIN,
    )

    assert response.status_code == 503
    assert response.json["error"]["code"] == "service_unavailable"
    assert budget.settlements == [("b" * 32, settlement_ms)]


def test_local_profile_does_not_install_public_early_or_global_guards(monkeypatch):
    monkeypatch.setattr(config_module, "supports_resource_limits", lambda: True)
    app = create_app({"TESTING": True, "APP_MODE": "local"})

    assert app.extensions["rapport_auditor.early_attempt_limiter"] is None
    assert app.extensions["rapport_auditor.analysis_budget"] is None
