from __future__ import annotations

import time
from io import BytesIO

import pytest

from conftest import LOCAL_ORIGIN, TEST_SECRET, read_sample


def _audit(client, text: str, token: str, *, origin: str = LOCAL_ORIGIN, xff: str | None = None):
    headers = {"Origin": origin, "X-CSRF-Token": token}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    return client.post(
        "/api/v1/audit",
        json={"text": text},
        headers=headers,
        base_url=LOCAL_ORIGIN,
    )


def test_analysis_post_requires_csrf_token(client):
    response = client.post(
        "/api/v1/audit",
        json={"text": read_sample("baseline_en.txt")},
        headers={"Origin": LOCAL_ORIGIN},
        base_url=LOCAL_ORIGIN,
    )

    assert response.status_code in {400, 403}
    assert response.is_json
    assert response.get_json()["error"]["code"]


def test_analysis_post_rejects_forged_csrf_token(client, csrf_token):
    response = _audit(client, "Synthetic example only.", csrf_token + "x")

    assert response.status_code in {400, 403}
    assert response.get_json()["error"]["code"]


def test_analysis_post_rejects_cross_origin_submission(client, csrf_token):
    response = _audit(
        client,
        "Synthetic example only.",
        csrf_token,
        origin="https://attacker.invalid",
    )

    assert response.status_code in {400, 403}
    assert response.get_json()["error"]["code"]


def test_same_origin_referer_is_checked_when_origin_is_missing(client, csrf_token):
    response = client.post(
        "/api/v1/audit",
        json={"text": "Synthetic example only."},
        headers={
            "Referer": f"{LOCAL_ORIGIN}/?locale=en",
            "X-CSRF-Token": csrf_token,
        },
        base_url=LOCAL_ORIGIN,
    )

    assert response.status_code == 200, response.get_data(as_text=True)


@pytest.mark.parametrize("referer", ["https://attacker.invalid/", "http://["])
def test_cross_origin_or_malformed_referer_is_rejected_when_origin_is_missing(client, csrf_token, referer):
    response = client.post(
        "/api/v1/audit",
        json={"text": "Synthetic example only."},
        headers={"Referer": referer, "X-CSRF-Token": csrf_token},
        base_url=LOCAL_ORIGIN,
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "origin_rejected"


def test_untrusted_host_is_rejected_even_with_forwarded_host(client, csrf_token):
    response = client.post(
        "/api/v1/audit",
        json={"text": "Synthetic example only."},
        headers={
            "Origin": "http://attacker.invalid",
            "X-CSRF-Token": csrf_token,
            "X-Forwarded-Host": "127.0.0.1",
        },
        base_url="http://attacker.invalid",
    )

    assert response.status_code == 400


def test_forwarded_for_cannot_bypass_rate_limit(app_factory):
    app = app_factory(RATE_LIMIT_MAX_REQUESTS=1, RATE_LIMIT_WINDOW_SECONDS=60)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN).get_json()["csrf_token"]
    text = "Synthetic example only."

    first = client.post(
        "/api/v1/audit",
        json={"text": text},
        headers={
            "Origin": LOCAL_ORIGIN,
            "X-CSRF-Token": token,
            "X-Forwarded-For": "198.51.100.10",
        },
        base_url=LOCAL_ORIGIN,
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    second = client.post(
        "/api/v1/audit",
        json={"text": text},
        headers={
            "Origin": LOCAL_ORIGIN,
            "X-CSRF-Token": token,
            "X-Forwarded-For": "203.0.113.55",
        },
        base_url=LOCAL_ORIGIN,
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0


def test_equivalent_ipv6_client_forms_share_the_same_rate_bucket(app_factory):
    app = app_factory(RATE_LIMIT_MAX_REQUESTS=1, RATE_LIMIT_WINDOW_SECONDS=60)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN).get_json()["csrf_token"]

    def submit(remote_addr: str):
        return client.post(
            "/api/v1/audit",
            json={"text": "Synthetic IPv6 quota test."},
            headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": token},
            base_url=LOCAL_ORIGIN,
            environ_overrides={"REMOTE_ADDR": remote_addr},
        )

    compressed = submit("2001:db8::1")
    expanded = submit("2001:0db8:0:0:0:0:0:1")

    assert compressed.status_code == 200
    assert expanded.status_code == 429
    assert int(expanded.headers["Retry-After"]) > 0


def test_expired_csrf_token_is_rejected(app_factory):
    app = app_factory(CSRF_TOKEN_MAX_AGE=1)
    client = app.test_client()
    token_response = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN)
    token = token_response.get_json()["csrf_token"]
    time.sleep(2.05)

    response = _audit(client, "Synthetic example only.", token)

    assert response.status_code in {400, 403}
    assert response.get_json()["error"]["code"]


def test_response_headers_protect_html_and_api_from_caching_and_sniffing(client):
    for response in (
        client.get("/", base_url=LOCAL_ORIGIN),
        client.get("/api/v1/health", base_url=LOCAL_ORIGIN),
    ):
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("Content-Security-Policy")
        assert "no-store" in response.headers.get("Cache-Control", "")
        assert response.headers.get("Referrer-Policy") == "same-origin"


def test_csrf_secret_is_not_exposed_in_error_response(client, csrf_token):
    response = _audit(client, "Synthetic example only.", csrf_token + "bad")

    assert response.status_code in {400, 403}
    assert TEST_SECRET.encode() not in response.data
    assert b"Traceback" not in response.data


def test_uploaded_text_is_never_written_into_application_logs(client, csrf_token, caplog):
    marker = "SYNTHETIC-LOG-CANARY-7f9e2c"
    response = _audit(client, marker + " is a fictional test phrase.", csrf_token)

    assert response.status_code == 200
    assert marker not in caplog.text


def test_malicious_query_and_upload_filename_are_not_written_to_application_logs(client, csrf_token, caplog):
    query_marker = "QUERY-CANARY-b319f1"
    filename_marker = "filename-canary-63da.tex"
    upload = b"Synthetic upload logging test."

    response = client.post(
        f"/audit?filter={query_marker}",
        data={"csrf_token": csrf_token, "text": "", "content_language": "en", "file": (BytesIO(upload), filename_marker)},
        headers={"Origin": LOCAL_ORIGIN},
        base_url=LOCAL_ORIGIN,
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert query_marker not in caplog.text
    assert filename_marker not in caplog.text
