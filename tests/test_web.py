from __future__ import annotations

import io
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from conftest import LOCAL_ORIGIN, form_csrf_token
from rapport_auditor.review import audit_text, audit_text_deep
from rapport_api.app import _static_asset_versions


class _WebMarkupProbe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls: dict[str, dict[str, str | None]] = {}
        self.textareas: dict[str, list[str]] = {}
        self.links: set[str] = set()
        self.assets: dict[str, str] = {}
        self.source_names: list[dict[str, str]] = []
        self.roles: set[str] = set()
        self._capturing_textarea: str | None = None
        self._capturing_source_name: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        identifier = values.get("id")
        if identifier in {"load-example", "remove-file", "clear-text", "character-count", "report-file", "file-chip", "copy-sample"}:
            self.controls[identifier] = values
        if tag == "textarea" and identifier:
            self.controls[identifier] = values
            self._capturing_textarea = identifier
            self.textareas[identifier] = []
        if tag == "h3" and "source-name" in (values.get("class") or "").split():
            source_name = {"text": "", "original": values.get("data-source-name", "") or ""}
            self.source_names.append(source_name)
            self._capturing_source_name = source_name
        if tag == "a" and values.get("href"):
            self.links.add(values["href"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.assets["style.css"] = values["href"]
        if tag == "script" and values.get("src"):
            filename = Path(urlsplit(values["src"]).path).name
            if filename in {"theme.js", "app.js"}:
                self.assets[filename] = values["src"]
        if values.get("role"):
            self.roles.add(values["role"])

    def handle_data(self, data):
        if self._capturing_textarea:
            self.textareas[self._capturing_textarea].append(data)
        if self._capturing_source_name is not None:
            self._capturing_source_name["text"] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self._capturing_textarea = None
        if tag == "h3":
            self._capturing_source_name = None


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


def test_static_assets_are_fingerprinted_on_home_and_error_pages(client, tmp_path):
    actual_versions = _static_asset_versions(
        Path(__file__).resolve().parents[1] / "apps" / "web" / "rapport_web" / "static"
    )
    expected_versions: dict[str, str] = {}
    for locale in ("en", "fr"):
        home = client.get(f"/?locale={locale}", base_url=LOCAL_ORIGIN)
        error = post_form(client, "/audit", {"text": "", "locale": locale})
        assert home.status_code == 200
        assert error.status_code == 400

        for response in (home, error):
            probe = _WebMarkupProbe()
            probe.feed(response.get_data(as_text=True))
            assert set(probe.assets) == {"theme.js", "style.css", "app.js"}
            for filename, url in probe.assets.items():
                parsed = urlsplit(url)
                assert parsed.scheme == "" and parsed.netloc == ""
                assert parsed.path == f"/static/{filename}"
                version = parse_qs(parsed.query).get("v", [])
                assert len(version) == 1 and len(version[0]) == 12
                assert version[0] == actual_versions[filename]
                if filename in expected_versions:
                    assert version[0] == expected_versions[filename]
                else:
                    expected_versions[filename] = version[0]

    assets_dir = tmp_path / "static"
    assets_dir.mkdir()
    (assets_dir / "style.css").write_text("body { color: black; }", encoding="utf-8")
    (assets_dir / "app.js").write_text("document.documentElement.dataset.ready = 'yes';", encoding="utf-8")
    (assets_dir / "theme.js").write_text("document.documentElement.dataset.theme = 'light';", encoding="utf-8")
    before = _static_asset_versions(assets_dir)
    (assets_dir / "style.css").write_text("body { color: navy; }", encoding="utf-8")
    (assets_dir / "app.js").write_text("document.documentElement.dataset.ready = 'changed';", encoding="utf-8")
    (assets_dir / "theme.js").write_text("document.documentElement.dataset.theme = 'dark';", encoding="utf-8")
    after = _static_asset_versions(assets_dir)
    assert after["style.css"] != before["style.css"]
    assert after["app.js"] != before["app.js"]
    assert after["theme.js"] != before["theme.js"]


def test_enhanced_controls_are_hidden_without_javascript(client):
    for locale in ("en", "fr"):
        response = client.get(f"/?locale={locale}", base_url=LOCAL_ORIGIN)

        assert response.status_code == 200
        probe = _WebMarkupProbe()
        probe.feed(response.get_data(as_text=True))
        assert "hidden" in probe.controls["load-example"]
        assert "hidden" in probe.controls["file-chip"], "the empty file summary should stay hidden without JavaScript"
        assert "hidden" not in probe.controls["copy-sample"], "manual example instructions remain available without JavaScript"
        assert "hidden" in probe.controls["clear-text"]
        assert "hidden" not in probe.controls["report-file"], "native file picker must remain available without JavaScript"
        assert "aria-live" not in probe.controls["character-count"]


def test_capped_findings_are_described_as_a_displayed_subset(client):
    text = "This is a synthetic sentence for the capped-findings template check."
    report = audit_text_deep(text, content_language="en", source_format="txt")
    report.findings_total_count = len(report.findings) + 1
    repetition = type("Repetition", (), {"repeated_starts": [], "repeated_phrases": []})()

    for locale, subset_label, global_label in (
        ("en", "Not shown among the displayed prompts:", "Also checked, no match:"),
        ("fr", "Non affichés parmi les pistes visibles :", "Aussi vérifié, sans résultat :"),
    ):
        with patch("rapport_api.app._analyze", return_value=(report, repetition, text, False)):
            response = post_form(client, "/audit", {"text": text, "locale": locale})

        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert subset_label in html
        assert global_label not in html


def test_privacy_summary_uses_the_configured_input_byte_and_line_limits(app_factory):
    app = app_factory(
        MAX_INPUT_CHARS=321,
        MAX_INPUT_BYTES=12345,
        MAX_LINES=37,
        MAX_UPLOAD_BYTES=900000,
    )
    configured_client = app.test_client()

    home = configured_client.get("/", base_url=LOCAL_ORIGIN)
    failed = post_form(configured_client, "/audit", {"text": ""})

    assert home.status_code == 200
    assert failed.status_code == 400
    for html in (home.get_data(as_text=True), failed.get_data(as_text=True)):
        assert "321 characters" in html
        assert "12345 bytes" in html
        assert "37 lines" in html
        assert "0.9 MB" in html


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


def test_french_native_audit_renders_the_localized_citation_prompt(client):
    text = "Les résultats montrent une amélioration fictive (Martin, 2024)."
    report = audit_text(text, content_language="fr", source_format="txt")
    expected_prompt = next(
        finding.prompt for finding in report.findings if finding.code == "citation_context_prompt"
    )

    response = post_form(
        client,
        "/audit",
        {
            "text": text,
            "source_format": "txt",
            "content_language": "fr",
            "locale": "fr",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert expected_prompt.encode("utf-8") in response.data
    assert "Check that the cited work supports this specific statement" not in response.get_data(as_text=True)

    smoke_script = Path(__file__).resolve().parents[1] / "scripts" / "release_http_smoke.py"
    smoke_source = smoke_script.read_text(encoding="utf-8")
    assert "Vérifiez que la source citée étaye bien cette affirmation précise" in smoke_source


def test_generic_pasted_source_display_is_localized_without_changing_original_name(client):
    for locale, expected_label in (("en", "Pasted text"), ("fr", "Texte collé")):
        response = post_form(
            client,
            "/audit",
            {
                "text": "This synthetic passage contains no research results.",
                "locale": locale,
                "content_language": "en",
            },
        )

        probe = _WebMarkupProbe()
        probe.feed(response.get_data(as_text=True))
        assert response.status_code == 200
        assert probe.source_names
        assert probe.source_names[0] == {"text": expected_label, "original": "pasted text"}


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
    probe = _WebMarkupProbe()
    probe.feed(response.get_data(as_text=True))
    assert probe.source_names[0] == {"text": "chapter.tex", "original": "chapter.tex"}


def test_tex_upload_autodetects_format_without_a_pasted_format_field(client):
    response = post_form(
        client,
        "/audit",
        {
            "file": (
                io.BytesIO(b"\\section{Intro} Synthetic text."),
                "chapter.tex",
                "application/octet-stream",
            )
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert b">TEX</span>" in response.data


def test_revision_preview_returns_diff(client):
    response = post_form(client, "/revise", {"text": "This chapter presents the platform."})

    assert response.status_code == 200, response.get_data(as_text=True)
    assert b"Unified Diff" in response.data
    assert b"revision preview" in response.data


def test_full_revision_textarea_has_a_no_javascript_copy_path(client):
    for locale in ("en", "fr"):
        sentence = "This final synthetic sentence remains visible in the proposed text."
        response = post_form(
            client,
            "/revise",
            {
                "text": "This chapter presents a fictional platform. It includes a synthetic method. "
                + sentence,
                "locale": locale,
                "content_language": "en",
            },
        )

        html = response.get_data(as_text=True)
        probe = _WebMarkupProbe()
        probe.feed(html)
        assert response.status_code == 200, html
        assert "revised-output" in probe.textareas
        assert "readonly" in probe.controls["revised-output"]
        assert 'data-download-source="revised"' in html
        assert sentence in "".join(probe.textareas["revised-output"]), "the complete suggested text should remain selectable in its textarea"
        expected_copy_help = "Without JavaScript, select the text above to copy it." if locale == "en" else "Sans JavaScript, sélectionnez le texte ci-dessus pour le copier."
        assert expected_copy_help in html


def test_short_sample_notice_uses_the_four_sentence_boundary_in_both_locales(client):
    examples = {
        "en": (
            [
                "This synthetic method describes a fictional process.",
                "It uses an example only.",
                "No real data appear here.",
                "This final note is also synthetic.",
                "It contains no research results.",
            ],
            "Short sample:",
        ),
        "fr": (
            [
                "Cette méthode fictive décrit un processus.",
                "Elle utilise un exemple seulement.",
                "Aucune donnée réelle n’apparaît ici.",
                "Cette dernière note reste fictive.",
                "Ce texte ne contient aucun résultat de recherche.",
            ],
            "Échantillon court :",
        ),
    }

    for locale, (sentences, localized_notice) in examples.items():
        for count in range(1, 4):
            short = post_form(
                client,
                "/audit",
                {"text": " ".join(sentences[:count]), "locale": locale, "content_language": locale},
            )
            assert short.status_code == 200, short.get_data(as_text=True)
            assert localized_notice in short.get_data(as_text=True)

        for count in (4, 5):
            sufficient = post_form(
                client,
                "/audit",
                {"text": " ".join(sentences[:count]), "locale": locale, "content_language": locale},
            )
            assert sufficient.status_code == 200, sufficient.get_data(as_text=True)
            assert localized_notice not in sufficient.get_data(as_text=True)


def test_upload_error_summary_links_to_file_and_preserves_pasted_text(client):
    pasted = "Synthetic pasted text remains available after an upload error."
    response = post_form(
        client,
        "/audit",
        {
            "text": pasted,
            "file": (io.BytesIO(b"synthetic only"), "unsupported.pdf", "application/pdf"),
        },
    )

    html = response.get_data(as_text=True)
    probe = _WebMarkupProbe()
    probe.feed(html)
    assert response.status_code == 415
    assert pasted in html
    assert "#report-file" in probe.links
    assert "alert" in probe.roles


def test_empty_input_returns_friendly_error_and_preserves_form_state(client):
    pasted = ""
    response = post_form(client, "/audit", {"text": pasted})

    assert response.status_code == 400
    assert b"Paste text or upload a .tex or .txt file." in response.data
    assert b'id="report-text"' in response.data
    probe = _WebMarkupProbe()
    probe.feed(response.get_data(as_text=True))
    assert "#report-text" in probe.links
