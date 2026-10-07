from __future__ import annotations

import sys

from rapport_api import cli


def test_waitress_body_buffer_and_request_caps_match_flask_limit(app, monkeypatch):
    captured: dict[str, object] = {}

    def capture_serve(application, **options):
        assert application is app
        captured.update(options)

    monkeypatch.setattr(cli, "create_app", lambda: app)
    monkeypatch.setattr(cli, "serve", capture_serve)
    monkeypatch.setattr(sys, "argv", ["rapport-auditor", "--port", "5051", "--threads", "2"])
    monkeypatch.delenv("RAPPORT_AUDITOR_HOST", raising=False)

    cli.main()

    body_limit = app.config["MAX_CONTENT_LENGTH"]
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 5051
    assert captured["max_request_body_size"] == body_limit
    assert captured["inbuf_overflow"] >= body_limit
    assert captured["connection_limit"] <= 16
    # Flask may echo a draft into the textarea and cleaned-text preview. Keep
    # Waitress's in-memory output threshold comfortably above the request cap.
    assert captured["outbuf_overflow"] >= body_limit * 4
