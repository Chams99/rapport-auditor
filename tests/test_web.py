from __future__ import annotations

import io

from conftest import LOCAL_ORIGIN, form_csrf_token


def post_form(client, path: str, values: dict[str, object]):
    page = client.get("/", base_url=LOCAL_ORIGIN)
    payload = {"csrf_token": form_csrf_token(page.data), **values}
    return client.post(
        path,
        data=payload,
        headers={"Origin": LOCAL_ORIGIN},
        base_url=LOCAL_ORIGIN,
    )


def test_home_page_loads_and_exposes_localized_native_form(client):
    response = client.get("/", base_url=LOCAL_ORIGIN)

    assert response.status_code == 200
    assert b"Rapport Auditor" in response.data
    assert b'id="report-text"' in response.data
    assert b'name="csrf_token"' in response.data
    assert b"English" in response.data or b"EN" in response.data


def test_paste_audit_returns_metrics(client):
    response = post_form(
        client,
        "/audit",
        {"text": "This chapter presents the platform. The system provides validation and orchestration."},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert b"Words" in response.data
    assert b"Writing patterns" in response.data
    assert b"does not check factual claims, bibliography entries or source contents" in response.data


def test_tex_upload_audit_works(client):
    payload = {
        "file": (
            io.BytesIO(b"\\section{Intro} This chapter presents the platform."),
            "chapter.tex",
            "application/octet-stream",
        )
    }

    response = post_form(client, "/audit", payload)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert b"chapter.tex" in response.data


def test_revision_preview_returns_diff(client):
    response = post_form(client, "/revise", {"text": "This chapter presents the platform."})

    assert response.status_code == 200, response.get_data(as_text=True)
    assert b"Unified Diff" in response.data
    assert b"revision preview" in response.data


def test_empty_input_returns_friendly_error_and_preserves_form_state(client):
    pasted = ""
    response = post_form(client, "/audit", {"text": pasted})

    assert response.status_code == 400
    assert b"Paste text or upload a .tex or .txt file." in response.data
    assert b'id="report-text"' in response.data
