from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cohost_acceptance.py"
SPEC = importlib.util.spec_from_file_location("cohost_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


def test_synthetic_bilingual_fixtures_are_exactly_max_chars_with_bounded_lines() -> None:
    for language in ("en", "fr"):
        marker = f"RABODY_{language}_synthetic"
        text = acceptance._synthetic_text(language, marker)

        assert len(text) == acceptance.MAX_CHARS == 250_000
        assert 500 <= len(text.splitlines()) <= 1000
        assert len(text.encode("utf-8")) < 1_000_000
        assert text.count(marker) == 1
        assert "fictional" in text.lower() or "fictif" in text.lower()


def test_audit_response_acceptance_checks_language_and_bounded_schema(monkeypatch) -> None:
    payload = {
        "content_language": "fr",
        "source_format": "txt",
        "summary": {"word_count": 10, "sentence_count": 2, "finding_count": 1},
        "findings": [],
        "citation_cues": [],
    }
    encoded = json.dumps(payload).encode()
    assert acceptance._valid_audit(encoded, "fr", "application/json")
    assert not acceptance._valid_audit(encoded, "en", "application/json")
    assert not acceptance._valid_audit(encoded, "fr", "text/plain")

    payload["summary"]["word_count"] = "10"
    assert not acceptance._valid_audit(json.dumps(payload).encode(), "fr", "application/json")

    monkeypatch.setattr(acceptance, "MAX_RESPONSE", 8)
    assert not acceptance._valid_audit(b" " * 9, "fr", "application/json")


def test_log_scan_classifies_only_canaries_and_fails_closed_on_caps() -> None:
    markers = {"query": "RAQUERY_fixture", "body": "RABODY_fixture"}
    scanned = acceptance._classify_logs(
        b"container stdout: request completed RAQUERY_fixture\ncontainer stderr: RABODY_fixture\n",
        markers,
    )

    assert scanned == {"query": True, "body": True}
    assert acceptance._classify_logs(b"\n" * acceptance.MAX_LOG_LINES, markers) is None
    assert acceptance._classify_logs(b"x" * (acceptance.MAX_LOG_BYTES + 1), markers) is None


def test_container_log_scan_combines_stdout_and_stderr_without_printing(monkeypatch, capsys) -> None:
    markers = {"query": "RAQUERY_fixture", "body": "RABODY_fixture"}
    chunks = iter(
        (
            b"stdout: RAQUERY_fixture\n",
            b"stderr: RABODY_fixture\n",
            b"",
        )
    )
    calls = {}

    class FakeStream:
        def fileno(self):
            return 123

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeProcess:
        stdout = FakeStream()

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    class FakeSelector:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def register(self, *_args):
            return None

        def select(self, _timeout):
            return [(None, None)]

    def fake_popen(_args, **kwargs):
        calls.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(acceptance.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(acceptance.selectors, "DefaultSelector", FakeSelector)
    monkeypatch.setattr(acceptance.os, "read", lambda _fd, _size: next(chunks))

    assert acceptance._logs("a" * 64, "start", "end", markers) == {
        "query": True,
        "body": True,
    }
    assert calls["stdout"] == subprocess.PIPE
    assert calls["stderr"] == subprocess.STDOUT
    assert capsys.readouterr().out == ""


def test_redirect_handler_does_not_forward_cookies_or_csrf_to_another_origin() -> None:
    handler = acceptance.NoRedirect()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.invalid/") is None


def test_container_metadata_uses_only_worker_sentinel_and_preserves_restart_baseline(monkeypatch, capsys) -> None:
    records = {
        "app-id": "running|healthy|false|5|2147483648|2000000000|workers2",
        "redis-id": "running|healthy|false|3|268435456|500000000|",
        "traefik-id": "running|none|false|7|536870912|1000000000|",
    }
    formats = []

    def fake_run(args):
        formats.append(args[3])
        return records[args[-1]]

    monkeypatch.setattr(acceptance, "_run", fake_run)

    states = acceptance._states({"app": "app-id", "redis": "redis-id", "traefik": "traefik-id"})

    # Docker's typed inspect model spells this Go field NanoCPUs. A casing
    # mismatch falls back to raw JSON, where Traefik's omitted Health field
    # fails under the CLI's strict missing-key template mode.
    assert all(".HostConfig.NanoCPUs" in fmt for fmt in formats)
    assert all("{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" in fmt for fmt in formats)
    assert states["app"][3:] == (5, 2147483648, 2000000000, True)
    assert states["redis"][3] == 3
    assert states["traefik"][1] == "none"  # no healthcheck is valid
    assert capsys.readouterr().out == ""

    records["app-id"] = "running|healthy|false|5|2147483648|2000000000|not-worker2"
    states = acceptance._states({"app": "app-id", "redis": "redis-id", "traefik": "traefik-id"})
    assert states["app"][6] is False


@pytest.mark.parametrize(
    ("value", "reason"),
    (
        (None, "inspect_failed"),
        ("private-field-value", "field_count"),
        ("running|none|unknown|0|1|1|", "invalid_boolean"),
        ("running|none|false|unknown|1|1|", "invalid_numeric_metadata"),
    ),
)
def test_state_diagnostics_report_only_role_and_constant_reason(monkeypatch, value, reason) -> None:
    monkeypatch.setattr(acceptance, "_run", lambda _args: value)

    with pytest.raises(RuntimeError) as error:
        acceptance._states({"traefik": "synthetic-id"})

    assert str(error.value) == f"traefik: {reason}"
    assert "private-field-value" not in str(error.value)
