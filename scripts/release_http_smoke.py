"""Same-origin synthetic HTTPS smoke for a deliberately selected release URL."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import urlsplit


base = os.environ["RAPPORT_AUDITOR_RELEASE_BASE_URL"].rstrip("/")
parsed = urlsplit(base)
if (
    parsed.scheme != "https"
    or not parsed.hostname
    or parsed.path not in {"", "/"}
    or parsed.query
    or parsed.fragment
    or parsed.username
    or parsed.password
):
    raise SystemExit("RAPPORT_AUDITOR_RELEASE_BASE_URL must be an HTTPS origin without a path.")
origin = f"https://{parsed.netloc}"
canary = os.environ["RAPPORT_AUDITOR_LOG_CANARY"]
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def request(path: str, *, data: bytes | None = None, headers: dict[str, str] | None = None):
    req = urllib.request.Request(f"{base}{path}", data=data, headers=headers or {})
    try:
        return opener.open(req, timeout=12)
    except urllib.error.HTTPError as exc:
        return exc


def get_json(path: str) -> tuple[int, dict, dict]:
    response = request(path)
    body = json.loads(response.read().decode("utf-8"))
    return response.status, body, dict(response.headers.items())


home_response = request(f"/?probe={urllib.parse.quote(canary)}")
home = home_response.read().decode("utf-8")
assert home_response.status == 200
headers = {name.lower(): value for name, value in home_response.headers.items()}
assert "max-age=" in headers.get("strict-transport-security", "").lower()
set_cookie = headers.get("set-cookie", "")
assert "secure" in set_cookie.lower() and "httponly" in set_cookie.lower()
assert "samesite=strict" in set_cookie.lower()
token_match = re.search(
    r'<input\b(?=[^>]*\bname="csrf_token")(?=[^>]*\bvalue="([^"]+)")[^>]*>',
    home,
)
assert token_match, "The home page did not provide its native-form CSRF token."
token = token_match.group(1)

for path, expected in (("/api/v1/health/live", "live"), ("/api/v1/health/ready", "ready")):
    status, health, _headers = get_json(path)
    assert status == 200 and health.get("status") == expected, f"{path} did not pass."

audit_text = f"Les résultats montrent une amélioration fictive (Martin, 2024). {canary}"
api_headers = {"Origin": origin, "X-CSRF-Token": token, "Content-Type": "application/json"}
audit_body = json.dumps(
    {"text": audit_text, "source_format": "txt", "content_language": "fr"},
    ensure_ascii=False,
).encode("utf-8")
response = request("/api/v1/audit", data=audit_body, headers=api_headers)
audit_result = json.loads(response.read().decode("utf-8"))
assert response.status == 200
assert audit_result.get("content_language") == "fr"
assert any(item.get("code") == "citation_context_prompt" for item in audit_result.get("findings", []))
assert "confidence" not in audit_result and "truth_score" not in audit_result

revision_body = json.dumps(
    {"text": "This chapter presents a fictional method.", "content_language": "en"}
).encode("utf-8")
response = request("/api/v1/revise", data=revision_body, headers=api_headers)
revision_result = json.loads(response.read().decode("utf-8"))
assert response.status == 200
assert "This chapter describes a fictional method." in revision_result.get("revised_text", "")

form = urllib.parse.urlencode(
    {
        "csrf_token": token,
        "text": audit_text,
        "source_format": "txt",
        "content_language": "fr",
        "locale": "fr",
    }
).encode("utf-8")
response = request(
    "/audit",
    data=form,
    headers={"Origin": origin, "Content-Type": "application/x-www-form-urlencoded"},
)
native_result = response.read().decode("utf-8")
assert response.status == 200
assert 'id="results-heading"' in native_result
assert "Vérifiez que la source citée étaye bien cette affirmation précise" in native_result

print("Verified HTTPS origin, security headers, health/readiness, and synthetic bilingual API/native-form flows.")
