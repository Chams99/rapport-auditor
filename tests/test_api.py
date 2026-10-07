from __future__ import annotations

import pytest
from flask.wrappers import Request as FlaskRequest

from conftest import LOCAL_ORIGIN, TEST_SECRET, read_sample


def assert_error(response, status: int) -> dict:
    assert response.status_code == status, response.get_data(as_text=True)
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert isinstance(payload.get("error"), dict)
    assert isinstance(payload["error"].get("code"), str)
    assert isinstance(payload["error"].get("message"), str)
    return payload["error"]


def test_health_is_available_without_csrf_or_document_data(client):
    response = client.get("/api/v1/health", base_url=LOCAL_ORIGIN)

    assert response.status_code == 200
    assert response.is_json
    assert isinstance(response.get_json(), dict)
    assert "text" not in response.get_json()


def test_csrf_endpoint_returns_a_token_and_cookie(client):
    response = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN)

    assert response.status_code == 200
    assert response.get_json()["csrf_token"]
    assert "ra_csrf=" in response.headers["Set-Cookie"]


def test_audit_returns_public_human_review_cues_without_scores_or_source_echo(api_post):
    response = api_post(
        "/api/v1/audit",
        {"text": read_sample("baseline_en.txt"), "source_format": "txt"},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    report = response.get_json()
    assert report["source_format"] == "txt"
    assert report["content_language"] == "en"
    assert report["summary"]["word_count"] == report["word_count"]
    assert isinstance(report["word_count"], int)
    assert isinstance(report["sentence_count"], int)
    assert isinstance(report["citation_cues"], list)
    assert isinstance(report["findings"], list)
    assert isinstance(report["repetition"], dict)
    assert not {
        "confidence",
        "ai_style_risk",
        "hallucination_risk",
        "style_signal",
        "support_signal",
        "sample_sufficiency",
        "cleaned_text",
        "text",
    } & report.keys()


def test_revision_preview_is_reversible_and_preserves_latex(api_post):
    source = r"This chapter presents a fictional method with \cite{synthetic-key} and \textbf{fixed notation}."

    response = api_post(
        "/api/v1/revise",
        {"text": source, "source_format": "tex"},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    result = response.get_json()
    assert result["source_format"] == "tex"
    assert r"\cite{synthetic-key}" in result["revised_text"]
    assert r"\textbf{fixed notation}" in result["revised_text"]
    assert "This chapter presents a fictional method" in source


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({}, 400),
        ({"text": None}, 400),
        ({"text": 17}, 400),
        ({"text": ["not", "text"]}, 400),
        ({"text": "   \n\t"}, 400),
        ({"text": "Some text.", "unknown": "value"}, 400),
        ({"text": "Some text.", "source_format": "pdf"}, 400),
    ],
)
def test_input_shape_and_unknown_fields_are_rejected(api_post, payload, expected_status):
    assert_error(api_post("/api/v1/audit", payload), expected_status)


def test_malformed_json_is_a_client_error(client, csrf_token):
    response = client.post(
        "/api/v1/audit",
        data="{",
        content_type="application/json",
        headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": csrf_token},
        base_url=LOCAL_ORIGIN,
    )

    assert_error(response, 400)


def test_french_nonbreaking_spacing_is_accepted_and_content_language_is_preserved(api_post):
    text = "Bonjour\u00a0: l’échantillon fictif contient 1\u202f000 valeurs."

    response = api_post(
        "/api/v1/audit",
        {"text": text, "content_language": "fr", "source_format": "txt"},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    report = response.get_json()
    assert report["content_language"] == "fr"
    assert report["summary"]["word_count"] > 0
    assert text not in response.get_data(as_text=True)  # audit JSON does not echo the submitted document


def test_deeply_nested_malformed_json_is_safe(client, csrf_token, caplog):
    # Keep this malformed on every supported runtime: one array remains open
    # when the object closes. Python versions may differ on whether their JSON
    # decoder reaches the syntax error or raises RecursionError first.
    nested_value = "[" * 5000 + "0" + "]" * 4999
    body = '{"text":"syntheti","unknown":' + nested_value + "}"
    assert len(body.encode("utf-8")) < 11_000

    response = client.post(
        "/api/v1/audit",
        data=body,
        content_type="application/json",
        headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": csrf_token},
        base_url=LOCAL_ORIGIN,
    )

    error = assert_error(response, 400)
    assert error["code"] == "malformed_json"
    assert body.encode() not in response.data
    assert body not in caplog.text
    assert TEST_SECRET.encode() not in response.data


def test_deeply_nested_unknown_json_is_safely_rejected(client, csrf_token, caplog):
    # A valid deeply nested value may be decoded or hit the runtime's recursion
    # guard. Both outcomes must stay a safe client error across Python versions.
    nested_value = "[" * 5000 + "0" + "]" * 5000
    body = '{"text":"syntheti","unknown":' + nested_value + "}"
    assert len(body.encode("utf-8")) < 11_000

    response = client.post(
        "/api/v1/audit",
        data=body,
        content_type="application/json",
        headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": csrf_token},
        base_url=LOCAL_ORIGIN,
    )

    error = assert_error(response, 400)
    assert error["code"] in {"malformed_json", "unknown_json_field"}
    assert body.encode() not in response.data
    assert body not in caplog.text
    assert TEST_SECRET.encode() not in response.data


def test_json_decoder_recursion_error_is_a_malformed_client_error(client, csrf_token, caplog, monkeypatch):
    def raise_recursion_error(_request, *args, **kwargs):
        raise RecursionError("synthetic decoder depth")

    monkeypatch.setattr(FlaskRequest, "get_json", raise_recursion_error)
    body = '{"text":"synthetic"}'
    response = client.post(
        "/api/v1/audit",
        data=body,
        content_type="application/json",
        headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": csrf_token},
        base_url=LOCAL_ORIGIN,
    )

    error = assert_error(response, 400)
    assert error["code"] == "malformed_json"
    assert "synthetic decoder depth" not in response.get_data(as_text=True)
    assert "synthetic decoder depth" not in caplog.text
    assert TEST_SECRET.encode() not in response.data


def test_form_encoded_body_is_rejected_by_json_api(client, csrf_token):
    response = client.post(
        "/api/v1/audit",
        data={"text": "Synthetic sample."},
        content_type="application/x-www-form-urlencoded",
        headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": csrf_token},
        base_url=LOCAL_ORIGIN,
    )

    assert_error(response, 415)


def test_character_limit_accepts_exact_boundary_and_rejects_one_more(app_factory):
    app = app_factory(MAX_INPUT_CHARS=64)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN).get_json()["csrf_token"]
    headers = {"Origin": LOCAL_ORIGIN, "X-CSRF-Token": token}

    exact = client.post(
        "/api/v1/audit",
        json={"text": "a." * 32},
        headers=headers,
        base_url=LOCAL_ORIGIN,
    )
    too_long = client.post(
        "/api/v1/audit",
        json={"text": "a." * 32 + "a"},
        headers=headers,
        base_url=LOCAL_ORIGIN,
    )

    assert exact.status_code == 200, exact.get_data(as_text=True)
    assert_error(too_long, 413)


def test_http_body_limit_returns_413_as_json(app_factory):
    app = app_factory(
        MAX_CONTENT_LENGTH=33_000,
        MAX_FORM_MEMORY_SIZE=33_000,
        MAX_INPUT_BYTES=128,
        MAX_UPLOAD_BYTES=128,
    )
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN).get_json()["csrf_token"]

    response = client.post(
        "/api/v1/audit",
        json={"text": "x" * 33_000},
        headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": token},
        base_url=LOCAL_ORIGIN,
    )

    assert_error(response, 413)


def test_line_limit_rejects_a_sentence_storm_before_analysis(app_factory):
    app = app_factory(MAX_LINES=3)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN).get_json()["csrf_token"]
    headers = {"Origin": LOCAL_ORIGIN, "X-CSRF-Token": token}

    within_limit = client.post(
        "/api/v1/audit",
        json={"text": "One line.\nTwo lines.\nThree lines."},
        headers=headers,
        base_url=LOCAL_ORIGIN,
    )
    too_many = client.post(
        "/api/v1/audit",
        json={"text": "One line.\nTwo lines.\nThree lines.\nFour lines."},
        headers=headers,
        base_url=LOCAL_ORIGIN,
    )

    assert within_limit.status_code == 200, within_limit.get_data(as_text=True)
    assert_error(too_many, 413)


def test_line_limit_also_counts_carriage_return_separators(app_factory):
    app = app_factory(MAX_LINES=2)
    client = app.test_client()
    token = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN).get_json()["csrf_token"]
    headers = {"Origin": LOCAL_ORIGIN, "X-CSRF-Token": token}

    response = client.post(
        "/api/v1/audit",
        json={"text": "First line.\rSecond line.\rThird line."},
        headers=headers,
        base_url=LOCAL_ORIGIN,
    )

    assert_error(response, 413)
