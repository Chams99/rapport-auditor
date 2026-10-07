from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

import pytest

from rapport_api import create_app


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "examples" / "synthetic"
LOCAL_ORIGIN = "http://127.0.0.1"
TEST_SECRET = "tests-only-secret-not-for-runtime"


def read_sample(name: str) -> str:
    return (SYNTHETIC / name).read_text(encoding="utf-8")


class _HiddenCsrfParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        if values.get("type") != "hidden":
            return
        name = values.get("name", "") or ""
        if "csrf" in name.lower():
            self.token = values.get("value")


def form_csrf_token(html: bytes) -> str:
    parser = _HiddenCsrfParser()
    parser.feed(html.decode("utf-8"))
    assert parser.token, "The server-rendered form must contain a CSRF token."
    return parser.token


@pytest.fixture
def app_factory() -> Callable[..., object]:
    def build(**overrides: object):
        config: dict[str, object] = {
            "TESTING": True,
            "SECRET_KEY": TEST_SECRET,
            "TRUSTED_HOSTS": ["127.0.0.1", "localhost"],
        }
        config.update(overrides)
        return create_app(config)

    return build


@pytest.fixture
def app(app_factory):
    return app_factory()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_token(client) -> str:
    response = client.get("/api/v1/csrf", base_url=LOCAL_ORIGIN)
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict) and isinstance(payload.get("csrf_token"), str)
    return payload["csrf_token"]


@pytest.fixture
def api_post(client, csrf_token):
    def post(path: str, payload: object, *, headers: dict[str, str] | None = None, **kwargs):
        request_headers = {
            "Origin": LOCAL_ORIGIN,
            "X-CSRF-Token": csrf_token,
        }
        if headers:
            request_headers.update(headers)
        return client.post(
            path,
            json=payload,
            headers=request_headers,
            base_url=kwargs.pop("base_url", LOCAL_ORIGIN),
            **kwargs,
        )

    return post
