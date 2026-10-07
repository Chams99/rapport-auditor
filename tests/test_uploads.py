from __future__ import annotations

import io
import tempfile

import pytest
from flask import request
from werkzeug import formparser

from conftest import LOCAL_ORIGIN, form_csrf_token, read_sample


def _upload(client, *, filename: str, content: bytes, mimetype: str, text: str = "", path: str = "/audit"):
    page = client.get("/", base_url=LOCAL_ORIGIN)
    token = form_csrf_token(page.data)
    return client.post(
        path,
        data={
            "csrf_token": token,
            "text": text,
            "file": (io.BytesIO(content), filename, mimetype),
        },
        headers={"Origin": LOCAL_ORIGIN},
        content_type="multipart/form-data",
        base_url=LOCAL_ORIGIN,
    )


@pytest.mark.parametrize(
    ("filename", "mimetype"),
    [
        ("sample.TXT", "text/plain"),
        ("notes.tex", "text/x-tex"),
        ("chapter.tex", "application/octet-stream"),
        ("source.txt", "application/octet-stream"),
    ],
)
def test_supported_utf8_upload_types_work(client, filename, mimetype):
    response = _upload(
        client,
        filename=filename,
        content=b"Synthetic sample text. This chapter presents a fictional method.",
        mimetype=mimetype,
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert filename.encode() in response.data


@pytest.mark.parametrize(
    ("filename", "mimetype", "content"),
    [
        ("draft.pdf", "application/pdf", b"%PDF synthetic"),
        ("chapter.tex", "image/png", b"Synthetic text."),
        ("notes.txt", "text/x-tex", b"Synthetic text."),
        ("draft.docx", "application/octet-stream", b"Synthetic text."),
    ],
)
def test_extension_and_mime_mismatch_is_rejected(client, filename, mimetype, content):
    response = _upload(client, filename=filename, content=content, mimetype=mimetype)

    assert response.status_code == 415


@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        (b"\xff\xfe\x00\x00binary", 415),
        (b"valid-looking\x00text", 415),
        (b"valid\x01text", 400),
        ("paragraph\u202e text".encode("utf-8"), 400),
        ("paragraph\u200b text".encode("utf-8"), 400),
    ],
)
def test_invalid_encoding_or_binary_control_is_rejected(client, content, expected_status):
    response = _upload(
        client,
        filename="draft.txt",
        content=content,
        mimetype="text/plain",
    )

    assert response.status_code == expected_status


def test_utf8_bom_is_accepted_and_removed(client):
    response = _upload(
        client,
        filename="bom.txt",
        content=b"\xef\xbb\xbfSynthetic sample text.",
        mimetype="text/plain",
    )

    assert response.status_code == 200
    assert b"\xef\xbb\xbf" not in response.data
    assert b"Synthetic sample text." in response.data


def test_french_nbsp_and_narrow_nbsp_uploads_are_accepted_and_preserved(client):
    text = "Bonjour\u00a0: l’échantillon fictif contient 1\u202f000 valeurs."
    response = _upload(
        client,
        filename="français.txt",
        content=text.encode("utf-8"),
        mimetype="text/plain",
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert "Bonjour\u00a0:".encode("utf-8") in response.data
    assert "1\u202f000".encode("utf-8") in response.data


def test_upload_byte_limit_accepts_exact_limit_and_rejects_one_byte_more(app_factory):
    app = app_factory(MAX_UPLOAD_BYTES=4)
    client = app.test_client()

    exact = _upload(
        client,
        filename="exact.txt",
        content=b"four",
        mimetype="text/plain",
    )
    too_large = _upload(
        client,
        filename="large.txt",
        content=b"fives",
        mimetype="text/plain",
    )

    assert exact.status_code == 200, exact.get_data(as_text=True)
    assert too_large.status_code == 413


def test_failing_upload_preserves_pasted_text(client):
    pasted = "Synthetic pasted text to keep after a bad upload."
    response = _upload(
        client,
        filename="draft.pdf",
        content=b"%PDF",
        mimetype="application/pdf",
        text=pasted,
    )

    assert response.status_code == 415
    assert pasted.encode() in response.data


def test_tex_upload_with_citation_renders_visible_key_and_context(client):
    source = read_sample("citation_cues.tex").encode("utf-8")
    response = _upload(
        client,
        filename="citation_cues.tex",
        content=source,
        mimetype="text/x-tex",
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert b"synthetic-grouping-2026" in response.data
    assert b"Check that the cited work supports this specific statement" in response.data


def test_html_escapes_user_text(client):
    text = '<script>alert("draft")</script> is synthetic input.'
    page = client.get("/", base_url=LOCAL_ORIGIN)
    response = client.post(
        "/audit",
        data={"csrf_token": form_csrf_token(page.data), "text": text},
        headers={"Origin": LOCAL_ORIGIN},
        content_type="application/x-www-form-urlencoded",
        base_url=LOCAL_ORIGIN,
    )

    assert response.status_code == 200
    assert b"<script>alert" not in response.data
    assert b"&lt;script&gt;" in response.data


def test_html_sanitizes_untrusted_upload_filename(client):
    response = _upload(
        client,
        filename="<script>.txt",
        content=b"Safe synthetic upload text.",
        mimetype="text/plain",
    )

    assert response.status_code == 200
    assert b"<script>" not in response.data
    assert b"script.txt" in response.data


def test_file_stream_uses_memory_instead_of_werkzeug_tempfile(app, monkeypatch):
    def fail_if_disk_stream_is_requested(*args, **kwargs):
        raise AssertionError("The app must not ask Werkzeug to create a temporary upload file.")

    monkeypatch.setattr(formparser, "default_stream_factory", fail_if_disk_stream_is_requested)
    content = ("😀" * 150_000).encode("utf-8")  # 600 KB, below the character limit.

    response = _upload(
        app.test_client(),
        filename="large.txt",
        content=content,
        mimetype="text/plain",
    )

    assert response.status_code == 200, response.get_data(as_text=True)[:1000]


def test_temporary_directory_remains_empty_during_upload(app, monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    response = _upload(
        app.test_client(),
        filename="tiny.txt",
        content=read_sample("baseline_en.txt").encode("utf-8"),
        mimetype="text/plain",
    )

    assert response.status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_memory_request_stream_is_seekable_bytesio(app):
    with app.test_request_context("/", base_url=LOCAL_ORIGIN):
        stream = request._get_file_stream(
            total_content_length=600_000,
            content_type="text/plain",
            filename="large.txt",
            content_length=None,
        )

    assert isinstance(stream, io.BytesIO)
    assert stream.seekable()
