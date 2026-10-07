"""Exercise the public app profile from inside its production container."""

from __future__ import annotations

import argparse
import os
from html.parser import HTMLParser


class _CsrfTokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        if values.get("type") == "hidden" and values.get("name") == "csrf_token":
            self.token = values.get("value")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--expect-redis-outage",
        action="store_true",
        help="assert that readiness and analysis fail closed while Redis is stopped",
    )
    args = parser.parse_args()

    from rapport_api import create_app

    domain = os.environ["RAPPORT_AUDITOR_TRUSTED_HOSTS"].split(",", 1)[0].strip()
    origin = f"https://{domain}"
    app = create_app()
    client = app.test_client()

    home = client.get("/", base_url=origin)
    assert home.status_code == 200
    cookie = home.headers.get("Set-Cookie", "")
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    token_parser = _CsrfTokenParser()
    token_parser.feed(home.get_data(as_text=True))
    token = token_parser.token
    assert token

    ready = client.get("/api/v1/health/ready", base_url=origin)
    if args.expect_redis_outage:
        assert ready.status_code == 503, ready.get_data(as_text=True)
        audit = client.post(
            "/api/v1/audit",
            json={"text": "Synthetic outage probe.", "content_language": "en"},
            headers={"Origin": origin, "X-CSRF-Token": token},
            base_url=origin,
        )
        assert audit.status_code == 503, audit.get_data(as_text=True)
        assert "Synthetic outage probe" not in audit.get_data(as_text=True)
        print("Server container outage smoke passed: readiness and audit fail closed on Redis loss.")
        return

    assert ready.status_code == 200, ready.get_data(as_text=True)

    source = "Les résultats montrent une amélioration fictive (Martin, 2024)."
    audit = client.post(
        "/api/v1/audit",
        json={"text": source, "source_format": "txt", "content_language": "fr"},
        headers={"Origin": origin, "X-CSRF-Token": token},
        base_url=origin,
    )
    assert audit.status_code == 200, audit.get_data(as_text=True)
    audit_result = audit.get_json()
    assert audit_result["content_language"] == "fr"
    assert any(item["code"] == "citation_context_prompt" for item in audit_result["findings"])
    assert "confidence" not in audit_result and "truth_score" not in audit_result

    revision = client.post(
        "/api/v1/revise",
        json={"text": "This chapter presents a fictional method.", "content_language": "en"},
        headers={"Origin": origin, "X-CSRF-Token": token},
        base_url=origin,
    )
    assert revision.status_code == 200, revision.get_data(as_text=True)
    assert "This chapter describes a fictional method." in revision.get_json()["revised_text"]

    native_audit = client.post(
        "/audit",
        data={
            "csrf_token": token,
            "text": source,
            "source_format": "txt",
            "content_language": "fr",
            "locale": "fr",
        },
        headers={"Origin": origin},
        base_url=origin,
    )
    assert native_audit.status_code == 200, native_audit.get_data(as_text=True)
    assert b'id="results-heading"' in native_audit.data
    print("Server container smoke passed: readiness, secure CSRF, JSON audit/revision, and native form audit.")


if __name__ == "__main__":
    main()
