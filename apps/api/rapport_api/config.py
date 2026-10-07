from __future__ import annotations

import ipaddress
import importlib.util
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


class ConfigurationError(ValueError):
    """A deployment setting is missing or invalid."""


def supports_resource_limits() -> bool:
    return os.name == "posix" and importlib.util.find_spec("resource") is not None


def _positive_int(name: str, value: str | int, *, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if isinstance(value, bool) or parsed < 1 or parsed > maximum:
        raise ConfigurationError(f"{name} is outside its supported range")
    return parsed


def _bounded_float(name: str, value: str | float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(f"{name} is outside its supported range")
    return parsed


def _csv(name: str, raw: str | None, *, required: bool = False) -> tuple[str, ...]:
    values = tuple(item.strip() for item in (raw or "").split(",") if item.strip())
    if required and not values:
        raise ConfigurationError(f"{name} must contain at least one value")
    if any("*" in item or "\x00" in item for item in values):
        raise ConfigurationError(f"{name} contains an unsupported value")
    return values


def normalize_host(value: str) -> str:
    candidate = value.strip()
    if ":" in candidate and not candidate.startswith("["):
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    try:
        parsed = urlsplit(f"//{candidate}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_HOSTS contains an invalid host") from exc
    if (
        not hostname
        or port is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or candidate.startswith(".")
        or not candidate.isascii()
    ):
        raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_HOSTS accepts exact hostnames or IP literals only")
    normalized = hostname.lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(normalized))
    except ValueError:
        labels = normalized.split(".")
        if len(normalized) > 253 or not labels or any(
            not label
            or len(label) > 63
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            for label in labels
        ):
            raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_HOSTS contains an invalid DNS hostname") from None
        return normalized


def _secret(environ: Mapping[str, str], name: str, *, required: bool) -> str | None:
    direct_name = f"RAPPORT_AUDITOR_{name}"
    file_name = f"{direct_name}_FILE"
    direct = environ.get(direct_name)
    filename = environ.get(file_name)
    if direct and filename:
        raise ConfigurationError(f"Set only one of {direct_name} and {file_name}")
    if filename:
        try:
            path = Path(filename)
            if not path.is_file() or path.stat().st_size > 16_384:
                raise ConfigurationError(f"{file_name} must name a small regular file")
            value = path.read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError) as exc:
            raise ConfigurationError(f"Could not read {file_name}") from exc
    else:
        value = direct
    if required and value is None:
        raise ConfigurationError(f"{direct_name} or {file_name} is required")
    if value is not None and len(value.encode("utf-8")) > 16_384:
        raise ConfigurationError(f"{direct_name} is too large")
    return value


def normalize_https_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_ORIGINS contains an invalid origin") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.netloc.endswith(":")
    ):
        raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_ORIGINS must contain HTTPS origins only")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_ORIGINS contains an invalid port")
    host = normalize_host(parsed.hostname)
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != 443:
        authority += f":{port}"
    return urlunsplit(("https", authority, "", "", ""))


def load_environment(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    mode = env.get("RAPPORT_AUDITOR_MODE", "local").strip().lower()
    if mode not in {"local", "server"}:
        raise ConfigurationError("RAPPORT_AUDITOR_MODE must be local or server")
    server = mode == "server"
    defaults: dict[str, Any] = {
        "APP_MODE": mode,
        "MAX_CONTENT_LENGTH": 1_100_000,
        "MAX_FORM_MEMORY_SIZE": 1_050_000,
        "MAX_FORM_PARTS": 8,
        "MAX_INPUT_CHARS": 250_000,
        "MAX_INPUT_BYTES": 1_000_000,
        "MAX_UPLOAD_BYTES": 1_000_000,
        "MAX_LINES": 10_000,
        "MAX_RESPONSE_BYTES": 8_000_000,
        "WAITRESS_OUTBUF_OVERFLOW": 8_500_000,
        "CSRF_COOKIE_NAME": "ra_csrf",
        "CSRF_TOKEN_MAX_AGE": 1800,
        "COOKIE_SECURE": False,
        "RATE_LIMIT_MAX_REQUESTS": _positive_int(
            "RAPPORT_AUDITOR_RATE_LIMIT_MAX_REQUESTS", env.get("RAPPORT_AUDITOR_RATE_LIMIT_MAX_REQUESTS", "30"), maximum=10_000
        ),
        "RATE_LIMIT_WINDOW_SECONDS": _positive_int(
            "RAPPORT_AUDITOR_RATE_LIMIT_WINDOW_SECONDS", env.get("RAPPORT_AUDITOR_RATE_LIMIT_WINDOW_SECONDS", "60"), maximum=3600
        ),
        "RATE_LIMIT_MAX_CLIENTS": _positive_int(
            "RAPPORT_AUDITOR_RATE_LIMIT_MAX_CLIENTS", env.get("RAPPORT_AUDITOR_RATE_LIMIT_MAX_CLIENTS", "4096"), maximum=100_000
        ),
        "RATE_LIMIT_NAMESPACE": env.get("RAPPORT_AUDITOR_RATE_LIMIT_NAMESPACE", "rapport-auditor:prod"),
        "REDIS_TIMEOUT_SECONDS": _bounded_float(
            "RAPPORT_AUDITOR_REDIS_TIMEOUT_SECONDS",
            env.get("RAPPORT_AUDITOR_REDIS_TIMEOUT_SECONDS", "0.5"),
            minimum=0.1,
            maximum=2.0,
        ),
        "ANALYSIS_MAX_WORKERS": _positive_int(
            "RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS", env.get("RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS", "2"), maximum=8
        ),
        "ANALYSIS_TIMEOUT_SECONDS": _bounded_float(
            "RAPPORT_AUDITOR_ANALYSIS_TIMEOUT_SECONDS",
            env.get("RAPPORT_AUDITOR_ANALYSIS_TIMEOUT_SECONDS", "10"),
            minimum=1.0,
            maximum=30.0,
        ),
        "WORKER_MEMORY_MB": _positive_int(
            "RAPPORT_AUDITOR_WORKER_MEMORY_MB", env.get("RAPPORT_AUDITOR_WORKER_MEMORY_MB", "512"), maximum=2048
        ),
        "WORKER_CPU_SECONDS": _positive_int(
            "RAPPORT_AUDITOR_WORKER_CPU_SECONDS", env.get("RAPPORT_AUDITOR_WORKER_CPU_SECONDS", "8"), maximum=30
        ),
        "HOST": env.get("RAPPORT_AUDITOR_HOST", "0.0.0.0" if server else "127.0.0.1"),
        "PORT": _positive_int("RAPPORT_AUDITOR_PORT", env.get("RAPPORT_AUDITOR_PORT", "5000"), maximum=65535),
        "THREADS": _positive_int("RAPPORT_AUDITOR_THREADS", env.get("RAPPORT_AUDITOR_THREADS", "4"), maximum=32),
        "TRUSTED_HOSTS": tuple(
            normalize_host(host)
            for host in _csv("RAPPORT_AUDITOR_TRUSTED_HOSTS", env.get("RAPPORT_AUDITOR_TRUSTED_HOSTS"))
        ),
        "TRUSTED_ORIGINS": tuple(
            normalize_https_origin(value)
            for value in _csv("RAPPORT_AUDITOR_TRUSTED_ORIGINS", env.get("RAPPORT_AUDITOR_TRUSTED_ORIGINS"))
        ),
        "TRUSTED_PROXY": env.get("RAPPORT_AUDITOR_TRUSTED_PROXY", "").strip(),
        "SECRET_KEY": _secret(env, "SECRET_KEY", required=server),
        "REDIS_URL": _secret(env, "REDIS_URL", required=server),
    }
    if server:
        raw_hosts = _csv("RAPPORT_AUDITOR_TRUSTED_HOSTS", env.get("RAPPORT_AUDITOR_TRUSTED_HOSTS"), required=True)
        raw_origins = _csv("RAPPORT_AUDITOR_TRUSTED_ORIGINS", env.get("RAPPORT_AUDITOR_TRUSTED_ORIGINS"), required=True)
        if len(defaults["TRUSTED_HOSTS"]) != len(raw_hosts):
            raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_HOSTS contains duplicate hostnames")
        if len(defaults["TRUSTED_ORIGINS"]) != len(set(defaults["TRUSTED_ORIGINS"])):
            raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_ORIGINS contains duplicate origins")
        origin_hosts = {urlsplit(origin).hostname for origin in defaults["TRUSTED_ORIGINS"]}
        if not origin_hosts.issubset(set(defaults["TRUSTED_HOSTS"])):
            raise ConfigurationError("Every trusted HTTPS origin must use an allowed host")
        if any(urlsplit(origin).port not in {None, 443} for origin in raw_origins):
            raise ConfigurationError("Public HTTPS origins must use the standard HTTPS port")
        if not defaults["TRUSTED_PROXY"]:
            raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_PROXY must be an exact proxy IP address")
        try:
            ipaddress.ip_address(defaults["TRUSTED_PROXY"])
        except ValueError as exc:
            raise ConfigurationError("RAPPORT_AUDITOR_TRUSTED_PROXY must be an exact proxy IP address") from exc
        if defaults["SECRET_KEY"] is None or len(defaults["SECRET_KEY"].encode("utf-8")) < 32:
            raise ConfigurationError("The server secret must contain at least 32 UTF-8 bytes")
        if not defaults["REDIS_URL"] or not defaults["REDIS_URL"].startswith(("redis://", "rediss://")):
            raise ConfigurationError("RAPPORT_AUDITOR_REDIS_URL must use redis:// or rediss://")
        if defaults["HOST"] not in {"0.0.0.0", "127.0.0.1", "::1"}:
            raise ConfigurationError("RAPPORT_AUDITOR_HOST must be an IP bind address")
        if defaults["WORKER_CPU_SECONDS"] >= defaults["ANALYSIS_TIMEOUT_SECONDS"]:
            raise ConfigurationError("Worker CPU limit must be below its wall-clock timeout")
        if not supports_resource_limits():
            raise ConfigurationError("The server profile requires POSIX process resource limits")
        defaults["COOKIE_SECURE"] = True
    else:
        secure = env.get("RAPPORT_AUDITOR_COOKIE_SECURE", "").strip().lower()
        if secure not in {"", "0", "1", "false", "true", "no", "yes"}:
            raise ConfigurationError("RAPPORT_AUDITOR_COOKIE_SECURE must be a boolean")
        defaults["COOKIE_SECURE"] = secure in {"1", "true", "yes"}
        if not defaults["TRUSTED_HOSTS"]:
            defaults["TRUSTED_HOSTS"] = ("localhost", "127.0.0.1", "::1")
        if defaults["HOST"] not in {"127.0.0.1", "::1", "localhost"}:
            raise ConfigurationError("Non-loopback binding requires RAPPORT_AUDITOR_MODE=server")
    return defaults


def validate_config(config: Mapping[str, Any]) -> None:
    positive_limits = {
        "MAX_CONTENT_LENGTH": 2_000_000,
        "MAX_FORM_MEMORY_SIZE": 2_000_000,
        "MAX_FORM_PARTS": 32,
        "MAX_INPUT_CHARS": 500_000,
        "MAX_INPUT_BYTES": 2_000_000,
        "MAX_UPLOAD_BYTES": 2_000_000,
        "MAX_LINES": 20_000,
        "MAX_RESPONSE_BYTES": 16_000_000,
        "WAITRESS_OUTBUF_OVERFLOW": 24_000_000,
        "CSRF_TOKEN_MAX_AGE": 3600,
        "RATE_LIMIT_MAX_REQUESTS": 10_000,
        "RATE_LIMIT_WINDOW_SECONDS": 3600,
        "RATE_LIMIT_MAX_CLIENTS": 100_000,
        "ANALYSIS_MAX_WORKERS": 8,
        "WORKER_MEMORY_MB": 2048,
        "WORKER_CPU_SECONDS": 30,
        "THREADS": 32,
    }
    for name, maximum in positive_limits.items():
        value = config[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ConfigurationError(f"{name} is outside its supported range")
    timeout = config["ANALYSIS_TIMEOUT_SECONDS"]
    redis_timeout = config["REDIS_TIMEOUT_SECONDS"]
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30:
        raise ConfigurationError("ANALYSIS_TIMEOUT_SECONDS is outside its supported range")
    if not isinstance(redis_timeout, (int, float)) or not 0.1 <= redis_timeout <= 2:
        raise ConfigurationError("REDIS_TIMEOUT_SECONDS is outside its supported range")
    numeric_pairs = (
        ("MAX_CONTENT_LENGTH", "MAX_INPUT_BYTES"),
        ("MAX_CONTENT_LENGTH", "MAX_UPLOAD_BYTES"),
        ("MAX_INPUT_CHARS", "MAX_INPUT_BYTES"),
        ("WAITRESS_OUTBUF_OVERFLOW", "MAX_RESPONSE_BYTES"),
    )
    for left, right in numeric_pairs:
        a, b = config[left], config[right]
        if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, int) or not isinstance(b, int):
            raise ConfigurationError(f"{left} and {right} must be integer limits")
        if left == "MAX_INPUT_CHARS" and a > b:
            continue  # Unicode code points may exceed UTF-8 bytes; both are independent ceilings.
        if left != "MAX_INPUT_CHARS" and a < b:
            raise ConfigurationError(f"{left} must be at least {right}")
    if config["WAITRESS_OUTBUF_OVERFLOW"] <= config["MAX_RESPONSE_BYTES"]:
        raise ConfigurationError("WAITRESS_OUTBUF_OVERFLOW must exceed MAX_RESPONSE_BYTES")
    if config["MAX_FORM_MEMORY_SIZE"] > config["MAX_CONTENT_LENGTH"]:
        raise ConfigurationError("MAX_FORM_MEMORY_SIZE cannot exceed MAX_CONTENT_LENGTH")
    if config["MAX_FORM_MEMORY_SIZE"] < min(config["MAX_INPUT_BYTES"], config["MAX_CONTENT_LENGTH"]):
        raise ConfigurationError("MAX_FORM_MEMORY_SIZE is too small for accepted text input")
    overhead = 32_768
    if config["MAX_CONTENT_LENGTH"] < max(config["MAX_INPUT_BYTES"], config["MAX_UPLOAD_BYTES"]) + overhead:
        raise ConfigurationError("MAX_CONTENT_LENGTH must reserve space for request framing")
    if config.get("APP_MODE") == "server":
        if not config["COOKIE_SECURE"]:
            raise ConfigurationError("Secure cookies are mandatory in server mode")
        if not config.get("TRUSTED_HOSTS") or not config.get("TRUSTED_ORIGINS"):
            raise ConfigurationError("Server mode requires trusted hosts and HTTPS origins")
        if len(str(config["SECRET_KEY"]).encode("utf-8")) < 32:
            raise ConfigurationError("The server secret must contain at least 32 UTF-8 bytes")
        if not config.get("REDIS_URL"):
            raise ConfigurationError("Server mode requires Redis")
        try:
            ipaddress.ip_address(config["TRUSTED_PROXY"])
        except (KeyError, ValueError) as exc:
            raise ConfigurationError("Server mode requires one exact trusted proxy IP") from exc
        if not supports_resource_limits():
            raise ConfigurationError("The server profile requires POSIX process resource limits")
        if config["HOST"] not in {"0.0.0.0", "127.0.0.1", "::1"}:
            raise ConfigurationError("The server bind host must be an IP address")
        if config["WORKER_CPU_SECONDS"] >= config["ANALYSIS_TIMEOUT_SECONDS"]:
            raise ConfigurationError("Worker CPU limit must be below its wall-clock timeout")
        try:
            normalized_hosts = tuple(normalize_host(host) for host in config["TRUSTED_HOSTS"])
            normalized_origins = tuple(normalize_https_origin(origin) for origin in config["TRUSTED_ORIGINS"])
        except (TypeError, ConfigurationError) as exc:
            raise ConfigurationError("Server trusted host/origin configuration is invalid") from exc
        if len(set(normalized_hosts)) != len(normalized_hosts) or len(set(normalized_origins)) != len(normalized_origins):
            raise ConfigurationError("Server trusted host/origin entries must be unique")
        if any(urlsplit(origin).port not in {None, 443} for origin in config["TRUSTED_ORIGINS"]):
            raise ConfigurationError("Public HTTPS origins must use the standard HTTPS port")
        if not {urlsplit(origin).hostname for origin in normalized_origins}.issubset(set(normalized_hosts)):
            raise ConfigurationError("Each trusted HTTPS origin must use an allowed host")
        if not config.get("REDIS_URL") or not str(config["REDIS_URL"]).startswith(("redis://", "rediss://")):
            raise ConfigurationError("Server mode requires a redis:// or rediss:// URL")
