from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import re
import secrets
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit

from flask import Request


class BoundedMemoryRequest(Request):
    """Keep parsed uploads in bounded memory instead of Werkzeug's temp files."""

    def _get_file_stream(
        self,
        total_content_length: int | None,
        content_type: str | None,
        filename: str | None = None,
        content_length: int | None = None,
    ) -> io.BytesIO:
        # MAX_CONTENT_LENGTH is checked by Werkzeug while parsing the enclosing
        # request. The endpoint applies a smaller per-file byte limit as well.
        return io.BytesIO()


@dataclass(frozen=True)
class AuditInput:
    text: str
    source_name: str
    source_format: str
    content_language: str = "en"


class AuditInputError(Exception):
    def __init__(self, code: str, status_code: int, field: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.field = field


_CONTROL_EXCEPTIONS = {"\t", "\n", "\r", "\f"}
_BINARY_SIGNATURES = (
    b"%PDF-",
    b"\x89PNG\r\n\x1a\n",
    b"GIF87a",
    b"GIF89a",
    b"\xff\xd8\xff",
    b"PK\x03\x04",
    b"\x1f\x8b\x08",
    b"MZ",
    b"\x7fELF",
)
_TEX_MIME_TYPES = {"text/x-tex", "application/x-tex"}
_BASE_MIME_TYPES = {"", "text/plain", "application/octet-stream"}


def normalize_source_format(value: object, *, default: str = "txt") -> str:
    if not isinstance(value, str):
        raise AuditInputError("invalid_source_format", 400, "source_format")
    normalized = value.strip().lower()
    if normalized.startswith("."):
        normalized = normalized[1:]
    if normalized not in {"txt", "tex"}:
        raise AuditInputError("invalid_source_format", 400, "source_format")
    return normalized


def sanitize_filename(value: str) -> str:
    # Browser-provided paths are never retained or used on disk.
    basename = re.split(r"[/\\]", value.strip())[-1]
    safe = re.sub(r"[^A-Za-z0-9._ -]", "", basename).strip(" .")
    return safe[:120] or "uploaded document"


def _validate_text(text: object, *, max_chars: int, max_bytes: int, max_lines: int) -> str:
    if not isinstance(text, str):
        raise AuditInputError("invalid_text", 400, "text")
    if len(text) > max_chars:
        raise AuditInputError("input_too_large", 413, "text")
    try:
        encoded = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise AuditInputError("invalid_text_encoding", 400, "text") from exc
    if len(encoded) > max_bytes:
        raise AuditInputError("input_too_large", 413, "text")
    if max(1, len(text.splitlines())) > max_lines:
        raise AuditInputError("too_many_lines", 413, "text")
    if any(
        ord(char) == 0
        or (
            char not in _CONTROL_EXCEPTIONS
            and char.isprintable() is False
            and unicodedata.category(char) != "Zs"
        )
        for char in text
    ):
        raise AuditInputError("binary_or_control_text", 400, "text")
    return text


def decode_uploaded_text(
    *,
    filename: str,
    mimetype: str | None,
    raw: bytes,
    max_chars: int,
    max_bytes: int,
    max_lines: int,
) -> AuditInput:
    source_name = sanitize_filename(filename)
    suffix = source_name.rsplit(".", 1)[-1].lower() if "." in source_name else ""
    if suffix not in {"txt", "tex"}:
        raise AuditInputError("unsupported_file_type", 415, "file")
    if len(raw) > max_bytes:
        raise AuditInputError("upload_too_large", 413, "file")
    content_type = (mimetype or "").strip().lower().split(";", 1)[0]
    if content_type not in _BASE_MIME_TYPES and not (suffix == "tex" and content_type in _TEX_MIME_TYPES):
        raise AuditInputError("mismatched_file_type", 415, "file")
    if any(raw.startswith(signature) for signature in _BINARY_SIGNATURES) or b"\x00" in raw:
        raise AuditInputError("binary_file", 415, "file")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise AuditInputError("invalid_text_encoding", 400, "file") from exc
    text = _validate_text(text, max_chars=max_chars, max_bytes=max_bytes, max_lines=max_lines)
    return AuditInput(text=text, source_name=source_name, source_format=suffix)


def normalize_client_address(remote_addr: str | None) -> str:
    if not remote_addr:
        return "unknown"
    try:
        return str(ipaddress.ip_address(remote_addr))
    except ValueError:
        return "unknown"


class InMemoryRateLimiter:
    """Bounded single-process rolling-window limiter keyed by the socket peer."""

    def __init__(self, *, limit: int, window_seconds: int, max_clients: int) -> None:
        from threading import Lock

        if limit < 1 or window_seconds < 1 or max_clients < 1:
            raise ValueError("rate limiter settings must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clients: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, identity: str, *, now: float | None = None) -> tuple[bool, int, int]:
        """Return (allowed, retry_after_seconds, remaining_requests)."""
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            timestamps = self._clients.pop(identity, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                retry_after = max(1, int(timestamps[0] + self.window_seconds - current + 0.999))
                self._clients[identity] = timestamps
                return False, retry_after, 0

            timestamps.append(current)
            self._clients[identity] = timestamps
            while len(self._clients) > self.max_clients:
                self._clients.popitem(last=False)
            reset_after = max(1, int(timestamps[0] + self.window_seconds - current + 0.999))
            return True, reset_after, self.limit - len(timestamps)


def issue_csrf_token(secret_key: str | bytes, existing: str | None, *, now: int | None = None, max_age: int = 1800) -> str:
    current = int(time.time() if now is None else now)
    if existing and verify_csrf_token(secret_key, existing, existing, now=current, max_age=max_age):
        return existing
    key = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
    payload = f"{current}.{secrets.token_urlsafe(24)}"
    signature = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_csrf_token(
    secret_key: str | bytes,
    submitted: str | None,
    cookie: str | None,
    *,
    now: int | None = None,
    max_age: int = 1800,
) -> bool:
    if (
        not isinstance(submitted, str)
        or not isinstance(cookie, str)
        or not submitted
        or not cookie
        or len(submitted) > 256
        or len(cookie) > 256
        or not submitted.isascii()
        or not cookie.isascii()
    ):
        return False
    if not hmac.compare_digest(submitted, cookie):
        return False
    pieces = submitted.split(".")
    if len(pieces) != 3:
        return False
    timestamp_text, nonce, signature = pieces
    if (
        not re.fullmatch(r"[0-9]{1,12}", timestamp_text)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", nonce)
        or not re.fullmatch(r"[0-9a-f]{64}", signature)
    ):
        return False
    try:
        timestamp = int(timestamp_text)
    except ValueError:
        return False
    current = int(time.time() if now is None else now)
    if timestamp > current + 60 or current - timestamp > max_age:
        return False
    key = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
    payload = f"{timestamp_text}.{nonce}"
    expected = hmac.new(key, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def is_trusted_host(host_header: str | None, trusted_hosts: Iterable[str]) -> bool:
    if not host_header:
        return False
    try:
        parsed = urlsplit(f"//{host_header}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (
        not hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
    ):
        return False
    if port is not None and not 1 <= port <= 65535:
        return False
    normalized = hostname.rstrip(".").lower()
    allowed = {value.rstrip(".").lower() for value in trusted_hosts}
    return normalized in allowed


def origin_matches(origin: str, expected_scheme: str, host_header: str) -> bool:
    try:
        parsed = urlsplit(origin)
        expected = urlsplit(f"{expected_scheme}://{host_header}")
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not expected.hostname
        ):
            return False
        actual_port = parsed.port
        expected_port = expected.port
        if actual_port == (443 if parsed.scheme.lower() == "https" else 80):
            actual_port = None
        if expected_port == (443 if expected_scheme.lower() == "https" else 80):
            expected_port = None
        return (
            parsed.scheme.lower() == expected.scheme.lower()
            and parsed.hostname.lower() == (expected.hostname or "").lower()
            and actual_port == expected_port
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False
