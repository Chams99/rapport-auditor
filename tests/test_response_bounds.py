from __future__ import annotations

import json

import pytest

from conftest import LOCAL_ORIGIN, TEST_SECRET, form_csrf_token


def _form_post(app_factory, path: str, text: str):
    app = app_factory()
    client = app.test_client()
    page = client.get("/", base_url=LOCAL_ORIGIN)
    response = client.post(
        path,
        data={"csrf_token": form_csrf_token(page.data), "text": text},
        headers={"Origin": LOCAL_ORIGIN},
        base_url=LOCAL_ORIGIN,
    )
    return app, response


def test_maximum_plain_text_review_response_fits_waitress_memory_bound(app_factory):
    text = "&" * 250_000

    app, response = _form_post(app_factory, "/audit", text)

    assert response.status_code == 200, response.get_data(as_text=True)[:1000]
    assert len(response.data) < app.config["WAITRESS_OUTBUF_OVERFLOW"]
    assert TEST_SECRET.encode() not in response.data


@pytest.mark.parametrize("special", ["&", "'", '"', "<", ">"])
def test_maximum_revised_text_response_fits_waitress_memory_bound(app_factory, special):
    prefix = "This chapter presents "
    text = prefix + (special * (250_000 - len(prefix)))

    app, response = _form_post(app_factory, "/revise", text)

    assert response.status_code == 200, response.get_data(as_text=True)[:1000]
    assert len(response.data) <= app.config["MAX_RESPONSE_BYTES"]
    assert len(response.data) < app.config["WAITRESS_OUTBUF_OVERFLOW"]
    assert TEST_SECRET.encode() not in response.data


def test_maximum_unicode_character_limit_fits_api_body_and_response(app_factory):
    app = app_factory()
    client = app.test_client()
    token_response = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN)
    token = token_response.get_json()["csrf_token"]
    text = "é" * 250_000
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    assert len(body) < app.config["MAX_CONTENT_LENGTH"]

    response = client.post(
        "/api/v1/audit",
        data=body,
        content_type="application/json",
        headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": token},
        base_url=LOCAL_ORIGIN,
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:1000]
    assert len(response.data) <= app.config["MAX_RESPONSE_BYTES"]
    assert len(response.data) < app.config["WAITRESS_OUTBUF_OVERFLOW"]
    assert response.get_json()["word_count"] >= 0
