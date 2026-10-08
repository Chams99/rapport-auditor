from __future__ import annotations

import json
import hashlib
import html
import logging
import secrets
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, abort, g, jsonify, make_response, render_template, request, send_from_directory
from werkzeug.exceptions import BadRequest, HTTPException, RequestEntityTooLarge

from rapport_web import WEB_PACKAGE_DIR

from .config import (
    ConfigurationError,
    load_environment,
    normalize_host,
    normalize_https_origin,
    validate_config,
)
from .limiting import (
    AnalysisBudgetExceeded,
    RateLimitUnavailable,
    RedisAnalysisWorkBudget,
    RedisSlidingWindowRateLimiter,
)
from .security import (
    AuditInput,
    AuditInputError,
    BoundedMemoryRequest,
    decode_uploaded_text,
    is_trusted_host,
    issue_csrf_token,
    normalize_client_address,
    normalize_source_format,
    origin_matches,
    sanitize_filename,
    verify_csrf_token,
    _validate_text,
)
from .workers import (
    BoundedAnalysisWorkers,
    LocalAnalysisRunner,
    WorkerCapacityError,
    WorkerFailure,
    WorkerTimeoutError,
)


_ERROR_MESSAGES = {
    "en": {
        "malformed_json": "The JSON request body could not be read.",
        "invalid_json_body": "Send a JSON object with a text field.",
        "unknown_json_field": "The request contains an unsupported field.",
        "unsupported_media_type": "Use a JSON request for this API endpoint.",
        "missing_text": "Add report text before continuing.",
        "invalid_text": "Report text must be a string.",
        "invalid_text_encoding": "Use valid UTF-8 text.",
        "binary_or_control_text": "The input contains binary or unsupported control characters.",
        "input_too_large": "The text is over the input size limit.",
        "upload_too_large": "The uploaded file is over the file size limit.",
        "too_many_lines": "The input has too many lines to review safely.",
        "empty_text": "Paste text or upload a .tex or .txt file.",
        "invalid_source_format": "Choose plain text (.txt) or LaTeX (.tex).",
        "unsupported_file_type": "Please upload a .tex or .txt file.",
        "mismatched_file_type": "The file type does not match its .tex or .txt extension.",
        "binary_file": "Upload a UTF-8 text file, not a binary document.",
        "invalid_form": "The form fields could not be read.",
        "csrf_failed": "This form expired or could not be verified. Reload the page and try again.",
        "origin_rejected": "The request origin could not be verified.",
        "host_rejected": "This host is not allowed to access the local app.",
        "rate_limited": "Too many reviews were started from this address. Wait a moment and retry.",
        "attempt_rate_limited": "Too many submissions have come from this address. Wait before trying again.",
        "analysis_busy": "The review service is busy. Wait before trying again.",
        "method_not_allowed": "This request method is not supported here.",
        "request_too_large": "The request is over the maximum size limit.",
        "not_found": "That page could not be found.",
        "server_error": "The request could not be completed. Try again.",
        "service_unavailable": "The review service is temporarily unavailable. Try again shortly.",
        "analysis_timeout": "The text could not be reviewed within the time limit. Try a shorter document.",
        "invalid_content_language": "Choose English or French as the report language.",
    },
    "fr": {
        "malformed_json": "Le corps JSON de la requête est illisible.",
        "invalid_json_body": "Envoyez un objet JSON contenant un champ text.",
        "unknown_json_field": "La requête contient un champ non pris en charge.",
        "unsupported_media_type": "Utilisez une requête JSON pour ce point d’accès API.",
        "missing_text": "Ajoutez le texte du rapport avant de continuer.",
        "invalid_text": "Le texte du rapport doit être une chaîne de caractères.",
        "invalid_text_encoding": "Utilisez un texte UTF-8 valide.",
        "binary_or_control_text": "Le texte contient des données binaires ou des caractères de contrôle non pris en charge.",
        "input_too_large": "Le texte dépasse la limite de taille.",
        "upload_too_large": "Le fichier dépasse la limite de taille.",
        "too_many_lines": "Le texte contient trop de lignes pour être analysé en toute sécurité.",
        "empty_text": "Collez du texte ou importez un fichier .tex ou .txt.",
        "invalid_source_format": "Choisissez du texte brut (.txt) ou du LaTeX (.tex).",
        "unsupported_file_type": "Importez un fichier .tex ou .txt.",
        "mismatched_file_type": "Le type de fichier ne correspond pas à son extension .tex ou .txt.",
        "binary_file": "Importez un fichier texte UTF-8, et non un document binaire.",
        "invalid_form": "Les champs du formulaire sont illisibles.",
        "csrf_failed": "Ce formulaire a expiré ou n’a pas pu être vérifié. Rechargez la page puis réessayez.",
        "origin_rejected": "L’origine de la requête n’a pas pu être vérifiée.",
        "host_rejected": "Cet hôte n’est pas autorisé à accéder à l’application locale.",
        "rate_limited": "Trop d’analyses ont été lancées depuis cette adresse. Attendez un instant puis réessayez.",
        "attempt_rate_limited": "Trop de tentatives proviennent de cette adresse. Attendez avant de réessayer.",
        "analysis_busy": "Le service de révision est occupé. Attendez avant de réessayer.",
        "method_not_allowed": "Cette méthode de requête n’est pas prise en charge ici.",
        "request_too_large": "La requête dépasse la taille maximale autorisée.",
        "not_found": "Cette page est introuvable.",
        "server_error": "La requête n’a pas abouti. Réessayez.",
        "service_unavailable": "Le service de révision est temporairement indisponible. Réessayez bientôt.",
        "analysis_timeout": "Le texte n’a pas pu être révisé dans le délai prévu. Essayez un document plus court.",
        "invalid_content_language": "Choisissez l’anglais ou le français comme langue du rapport.",
    },
}

_PUBLIC_FINDING_LIMIT = 30
_PUBLIC_CITATION_CUE_LIMIT = 30
_PUBLIC_OCCURRENCE_LIMIT = 10
_PUBLIC_KEY_LIMIT = 20
_PUBLIC_EDIT_LIMIT = 50
_PUBLIC_DIFF_LIMIT = 150_000
_REVIEW_POST_PATHS = frozenset({"/audit", "/revise", "/api/v1/audit", "/api/v1/revise"})


class _ApplicationError(Exception):
    def __init__(
        self,
        code: str,
        status_code: int,
        field: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.field = field
        self.retry_after = retry_after


def _localized_review_note(locale: str | None = None) -> str:
    if (locale or _locale()) == "fr":
        return "Les indications reposent sur le texte et les marqueurs visibles ; aucune source externe n’est consultée."
    return "Prompts use visible text and citation markers; no external sources are looked up."


def _normalize_content_language(value: object) -> str:
    if not isinstance(value, str) or value.strip().lower() not in {"en", "fr"}:
        raise AuditInputError("invalid_content_language", 400, "content_language")
    return value.strip().lower()


def _excerpt(value: str, limit: int = 500) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[: limit - 1].rstrip() + "…", True


def _public_findings(report: Any, *, limit: int = _PUBLIC_FINDING_LIMIT) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for finding in report.findings[:limit]:
        sentence, sentence_truncated = _excerpt(finding.sentence)
        sentence_truncated = sentence_truncated or bool(getattr(finding, "sentence_truncated", False))
        reason, reason_truncated = _excerpt(finding.reason, 400)
        reason_truncated = reason_truncated or bool(getattr(finding, "reason_truncated", False))
        prompt, prompt_truncated = _excerpt(finding.prompt, 400)
        prompt_truncated = prompt_truncated or bool(getattr(finding, "prompt_truncated", False))
        phrase = None
        phrase_truncated = False
        if finding.phrase is not None:
            phrase, phrase_truncated = _excerpt(finding.phrase, 160)
            phrase_truncated = phrase_truncated or bool(getattr(finding, "phrase_truncated", False))
        raw_occurrences = list(finding.occurrences)
        keys = list(finding.citation_keys)
        result.append(
            {
                "code": finding.code,
                "category": finding.category,
                "sentence": sentence,
                "sentence_truncated": sentence_truncated,
                "sentence_index": finding.sentence_index,
                "line": finding.line,
                "reason": reason,
                "reason_truncated": reason_truncated,
                "prompt": prompt,
                "prompt_truncated": prompt_truncated,
                "reasons": [reason, prompt],
                "phrase": phrase,
                "phrase_truncated": phrase_truncated,
                "count": finding.count,
                "occurrences": [
                    {"sentence_index": item.sentence_index, "line": item.line}
                    for item in raw_occurrences[:_PUBLIC_OCCURRENCE_LIMIT]
                ],
                "occurrences_omitted_count": max(0, len(raw_occurrences) - _PUBLIC_OCCURRENCE_LIMIT)
                + int(getattr(finding, "occurrences_omitted_count", 0)),
                "citation_keys": [_excerpt(key, 120)[0] for key in keys[:_PUBLIC_KEY_LIMIT]],
                "citation_keys_omitted_count": max(0, len(keys) - _PUBLIC_KEY_LIMIT)
                + int(getattr(finding, "citation_keys_omitted_count", 0)),
            }
        )
    return result


def _public_citation_cues(report: Any, *, limit: int = _PUBLIC_CITATION_CUE_LIMIT) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for cue in report.citation_cues[:limit]:
        excerpt, excerpt_truncated = _excerpt(cue.excerpt)
        excerpt_truncated = excerpt_truncated or bool(getattr(cue, "excerpt_truncated", False))
        keys = list(cue.keys)
        syntax, syntax_truncated = _excerpt(cue.syntax, 120)
        syntax_truncated = syntax_truncated or bool(getattr(cue, "syntax_truncated", False))
        result.append(
            {
                "syntax": syntax,
                "syntax_truncated": syntax_truncated,
                "keys": [_excerpt(key, 120)[0] for key in keys[:_PUBLIC_KEY_LIMIT]],
                "keys_omitted_count": max(0, len(keys) - _PUBLIC_KEY_LIMIT)
                + int(getattr(cue, "keys_omitted_count", 0)),
                "line": cue.line,
                "sentence_index": cue.sentence_index,
                "excerpt": excerpt,
                "excerpt_truncated": excerpt_truncated,
            }
        )
    return result


def _public_report_dict(report: Any, locale: str | None = None) -> dict[str, Any]:
    base = report.base
    findings = _public_findings(report)
    cues = _public_citation_cues(report)
    notes = [_localized_review_note(base.content_language)]
    notes_total = 1
    cue_note = (
        "Repère de citation visible ; la source et l’affirmation n’ont pas été vérifiées."
        if (locale or "en") == "fr"
        else "Visible citation cue; the source and claim have not been checked."
    )
    cue_compat = [
        {
            "line": cue["line"],
            "citation_keys": cue["keys"],
            "reasons": [cue_note],
            "excerpt": cue["excerpt"],
            **{key: value for key, value in cue.items() if key not in {"line", "keys", "excerpt"}},
        }
        for cue in cues
    ]
    return {
        "base": {
            "sentence_count": base.sentence_count,
            "word_count": base.word_count,
            "content_language": base.content_language,
            "flagged_sentence_count": base.flagged_sentence_count,
            "notes": notes,
            "review_note": _localized_review_note(locale),
        },
        "content_language": base.content_language,
        "findings": findings,
        "findings_total_count": int(getattr(report, "findings_total_count", len(report.findings))),
        "findings_displayed_count": len(findings),
        "findings_omitted_count": max(
            0,
            int(getattr(report, "findings_total_count", len(report.findings))) - len(findings),
        ),
        "findings_limit": _PUBLIC_FINDING_LIMIT,
        "citation_cues": cues,
        "citation_cues_total_count": int(
            getattr(report, "citation_cues_total_count", len(report.citation_cues))
        ),
        "citation_cues_displayed_count": len(cues),
        "citation_cues_omitted_count": max(
            0,
            int(getattr(report, "citation_cues_total_count", len(report.citation_cues))) - len(cues),
        ),
        "citation_cues_limit": _PUBLIC_CITATION_CUE_LIMIT,
        "citation_findings": cue_compat,
        "citation_findings_total_count": int(
            getattr(report, "citation_cues_total_count", len(report.citation_cues))
        ),
        "citation_findings_displayed_count": len(cue_compat),
        "notes_omitted_count": max(0, notes_total - len(notes)),
    }


def _report_view(public_data: dict[str, Any]) -> SimpleNamespace:
    base_data = dict(public_data["base"])
    # `sample_sufficiency` is a legacy template alias for a neutral copy label,
    # not a score or estimate of correctness.
    base_data["sample_sufficiency"] = "review prompts"
    base_data["sample_sufficiency_note"] = base_data["review_note"]
    base_data["flagged_sentence_limit"] = _PUBLIC_FINDING_LIMIT
    base_data["flagged_sentence_displayed_count"] = public_data["findings_displayed_count"]
    base_data["flagged_sentence_omitted_count"] = public_data["findings_omitted_count"]
    base_data["flagged_sentences"] = public_data["findings"]
    base = SimpleNamespace(**base_data)
    fields = {key: value for key, value in public_data.items() if key != "base"}
    return SimpleNamespace(base=base, **fields)


def _bounded_diff(value: str) -> tuple[str, bool]:
    return _excerpt(value, _PUBLIC_DIFF_LIMIT)


def _public_edits(edits: Any) -> tuple[list[dict[str, Any]], int]:
    values = list(edits)
    public = []
    for edit in values[:_PUBLIC_EDIT_LIMIT]:
        before, before_truncated = _excerpt(edit.before, 400)
        before_truncated = before_truncated or bool(getattr(edit, "before_truncated", False))
        after, after_truncated = _excerpt(edit.after, 400)
        after_truncated = after_truncated or bool(getattr(edit, "after_truncated", False))
        reason, reason_truncated = _excerpt(edit.reason, 300)
        reason_truncated = reason_truncated or bool(getattr(edit, "reason_truncated", False))
        public.append(
            {
                "line": edit.line,
                "before": before,
                "before_truncated": before_truncated,
                "after": after,
                "after_truncated": after_truncated,
                "reason": reason,
                "reason_truncated": reason_truncated,
            }
        )
    return public, max(0, len(values) - len(public))


def _public_api_audit(
    report: Any,
    repetition: Any,
    _cleaned_text: str,
    source_format: str,
    content_language: str,
) -> dict[str, Any]:
    public = _public_report_dict(report)
    repeated_starts = [
        {"text": _excerpt(value, 120)[0], "count": count}
        for value, count in repetition.repeated_starts[:15]
    ]
    repeated_phrases = [
        {"text": _excerpt(value, 120)[0], "count": count}
        for value, count in repetition.repeated_phrases[:15]
    ]
    return {
        "source_format": source_format,
        "content_language": content_language,
        "summary": {
            "word_count": report.base.word_count,
            "sentence_count": report.base.sentence_count,
            "finding_count": public["findings_total_count"],
            "citation_cue_count": public["citation_cues_total_count"],
        },
        "word_count": report.base.word_count,
        "sentence_count": report.base.sentence_count,
        "notes": public["base"]["notes"],
        "findings": public["findings"],
        "findings_summary": {
            "total_count": public["findings_total_count"],
            "displayed_count": public["findings_displayed_count"],
            "omitted_count": public["findings_omitted_count"],
            "limit": _PUBLIC_FINDING_LIMIT,
        },
        "citation_cues": public["citation_cues"],
        "citation_cues_summary": {
            "total_count": public["citation_cues_total_count"],
            "displayed_count": public["citation_cues_displayed_count"],
            "omitted_count": public["citation_cues_omitted_count"],
            "limit": _PUBLIC_CITATION_CUE_LIMIT,
        },
        "repetition": {
            "repeated_starts": repeated_starts,
            "repeated_phrases": repeated_phrases,
        },
    }


def _locale() -> str:
    candidate = request.args.get("locale")
    if candidate is None and request.method == "POST" and request.mimetype in {"multipart/form-data", "application/x-www-form-urlencoded"}:
        try:
            candidate = request.form.get("locale")
        except (BadRequest, RequestEntityTooLarge):
            candidate = None
    if candidate is None:
        candidate = request.accept_languages.best_match(["fr", "en"])
    return "fr" if isinstance(candidate, str) and candidate.lower().startswith("fr") else "en"


def _message(code: str, locale: str | None = None) -> str:
    lang = locale or _locale()
    return _ERROR_MESSAGES.get(lang, _ERROR_MESSAGES["en"]).get(code, _ERROR_MESSAGES["en"]["server_error"])


def _bodyless_locale() -> str:
    """Select an error language using metadata only; this is safe before body parsing."""
    candidate = request.headers.get("X-Rapport-Locale") or request.args.get("locale")
    if candidate is None:
        candidate = request.accept_languages.best_match(["fr", "en"])
    return "fr" if isinstance(candidate, str) and candidate.lower().startswith("fr") else "en"


def _page_state() -> dict[str, str]:
    state = getattr(g, "form_state", None)
    if isinstance(state, dict):
        return state
    try:
        if request.mimetype not in {"multipart/form-data", "application/x-www-form-urlencoded"}:
            return {"text": "", "source_name": "pasted text", "source_format": "txt", "content_language": "en"}
        text_values = request.form.getlist("text")
        text = text_values[0] if text_values else ""
        if len(text) > int(current_app_value("MAX_CONTENT_LENGTH")):
            text = ""
        source_name = "pasted text"
        upload = request.files.get("file")
        if upload and upload.filename:
            source_name = sanitize_filename(upload.filename)
        raw_format = request.form.get("source_format", "txt")
        try:
            source_format = normalize_source_format(raw_format)
        except AuditInputError:
            source_format = "txt"
        raw_language = request.form.get("content_language", "en")
        try:
            content_language = _normalize_content_language(raw_language)
        except AuditInputError:
            content_language = "en"
        return {
            "text": text,
            "source_name": source_name,
            "source_format": source_format,
            "content_language": content_language,
        }
    except (BadRequest, RequestEntityTooLarge, AuditInputError):
        return {"text": "", "source_name": "pasted text", "source_format": "txt", "content_language": "en"}


def current_app_value(name: str) -> Any:
    # Keep this helper tiny so error handlers can avoid importing another proxy.
    from flask import current_app

    return current_app.config[name]


def _new_csrf_token(app: Flask) -> str:
    return issue_csrf_token(
        app.config["SECRET_KEY"],
        request.cookies.get(app.config["CSRF_COOKIE_NAME"]),
        max_age=app.config["CSRF_TOKEN_MAX_AGE"],
    )


def _set_csrf_cookie(response: Response, app: Flask, token: str) -> None:
    response.set_cookie(
        app.config["CSRF_COOKIE_NAME"],
        token,
        max_age=app.config["CSRF_TOKEN_MAX_AGE"],
        secure=app.config["COOKIE_SECURE"],
        httponly=True,
        samesite="Strict",
        path="/",
    )


def _error_response(app: Flask, code: str, status_code: int, field: str | None = None) -> Response:
    locale = _locale()
    message = _message(code, locale)
    if request.path.startswith("/api/"):
        error: dict[str, str] = {"code": code, "message": message}
        if field:
            error["field"] = field
        request_id = getattr(g, "request_id", None)
        if request_id:
            error["request_id"] = request_id
        response = jsonify({"error": error})
        response.status_code = status_code
        return response

    state = _page_state()
    token = _new_csrf_token(app)
    response = make_response(
        render_template(
            "index.html",
            locale=locale,
            csrf_token=token,
            is_public_service=app.config["APP_MODE"] == "server",
            limits={
                "max_input_chars": app.config["MAX_INPUT_CHARS"],
                "max_input_bytes": app.config["MAX_INPUT_BYTES"],
                "max_lines": app.config["MAX_LINES"],
                "max_upload_bytes": app.config["MAX_UPLOAD_BYTES"],
            },
            error=message,
            error_code=code,
            errors={field: message} if field else {},
            mode=None,
            report=None,
            report_dict=None,
            public_notes=[],
            public_findings=[],
            repetition=None,
            cleaned_text="",
            edits=[],
            diff="",
            revised_text="",
            **state,
        ),
        status_code,
    )
    _set_csrf_cookie(response, app, token)
    return response


def _early_rejection_response(
    app: Flask,
    *,
    code: str,
    status_code: int,
    retry_after: int | None = None,
) -> Response:
    """Return a localized error without parsing or echoing a rejected request body."""
    locale = _bodyless_locale()
    message = _message(code, locale)
    request_id = getattr(g, "request_id", "")
    enhanced = request.headers.get("X-Rapport-Enhanced-Request") == "1"
    wants_json = request.path.startswith("/api/") or enhanced or request.accept_mimetypes.best == "application/json"
    if wants_json:
        response = jsonify(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                }
            }
        )
    else:
        if locale == "fr":
            title = "Réessayez plus tard" if status_code in {429, 503} else "Requête refusée"
            link = "Retourner à l’application"
        else:
            title = "Try again later" if status_code in {429, 503} else "Request rejected"
            link = "Return to the application"
        response = make_response(
            "<!doctype html><html lang=\""
            + locale
            + "\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>"
            + html.escape(title)
            + "</title></head><body><main><h1>"
            + html.escape(title)
            + "</h1><p>"
            + html.escape(message)
            + "</p><a href=\"/\">"
            + html.escape(link)
            + "</a></main></body></html>",
            status_code,
        )
        response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.status_code = status_code
    if retry_after is not None:
        response.headers["Retry-After"] = str(max(1, int(retry_after)))
    return response


def _read_html_input(app: Flask) -> AuditInput:
    if request.mimetype not in {"multipart/form-data", "application/x-www-form-urlencoded"}:
        raise AuditInputError("invalid_form", 400)
    try:
        text_values = request.form.getlist("text")
        source_name_values = request.form.getlist("source_name")
        format_values = request.form.getlist("source_format")
        locale_values = request.form.getlist("locale")
        language_values = request.form.getlist("content_language")
        files = request.files.getlist("file")
    except RequestEntityTooLarge:
        raise
    except BadRequest as exc:
        raise AuditInputError("invalid_form", 400) from exc

    if len(text_values) > 1 or len(format_values) > 1 or len(locale_values) > 1 or len(language_values) > 1:
        raise AuditInputError("invalid_form", 400)
    text = text_values[0] if text_values else ""
    raw_format = format_values[0] if format_values else "txt"
    try:
        source_format = normalize_source_format(raw_format)
    except AuditInputError:
        source_format = "txt"
    source_name = "pasted text"
    if len(source_name_values) == 1:
        # This is informational form state only; never trust it as a path.
        source_name = sanitize_filename(source_name_values[0])[:120]
    content_language = _normalize_content_language(language_values[0] if language_values else "en")
    g.form_state = {
        "text": text,
        "source_name": source_name,
        "source_format": source_format,
        "content_language": content_language,
    }

    if files and len(files) > 1:
        raise AuditInputError("invalid_form", 400, "file")
    uploaded = files[0] if files else None
    if uploaded and uploaded.filename:
        filename = uploaded.filename
        safe_name = sanitize_filename(filename if isinstance(filename, str) else "")
        g.form_state["source_name"] = safe_name
        file_format = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if file_format in {"txt", "tex"}:
            g.form_state["source_format"] = file_format
        data = uploaded.stream.read(int(app.config["MAX_UPLOAD_BYTES"]) + 1)
        decoded = decode_uploaded_text(
            filename=filename,
            mimetype=uploaded.mimetype,
            raw=data,
            max_chars=app.config["MAX_INPUT_CHARS"],
            max_bytes=app.config["MAX_UPLOAD_BYTES"],
            max_lines=app.config["MAX_LINES"],
        )
        return AuditInput(decoded.text, decoded.source_name, decoded.source_format, content_language)

    if format_values and raw_format.strip().lower().lstrip(".") not in {"txt", "tex"}:
        raise AuditInputError("invalid_source_format", 400, "source_format")
    text = _validate_text(
        text,
        max_chars=app.config["MAX_INPUT_CHARS"],
        max_bytes=app.config["MAX_INPUT_BYTES"],
        max_lines=app.config["MAX_LINES"],
    )
    return AuditInput(text=text, source_name="pasted text", source_format=source_format, content_language=content_language)


def _read_api_input(app: Flask) -> AuditInput:
    if not request.is_json:
        raise AuditInputError("unsupported_media_type", 415)
    try:
        payload = request.get_json(silent=False, cache=False)
    except (BadRequest, RecursionError) as exc:
        raise AuditInputError("malformed_json", 400) from exc
    if not isinstance(payload, dict):
        raise AuditInputError("invalid_json_body", 400)
    unexpected = set(payload) - {"text", "source_format", "content_language"}
    if unexpected:
        raise AuditInputError("unknown_json_field", 400, "field")
    if "text" not in payload:
        raise AuditInputError("missing_text", 400, "text")
    source_format = normalize_source_format(payload.get("source_format", "txt"))
    content_language = _normalize_content_language(payload.get("content_language", "en"))
    text = _validate_text(
        payload["text"],
        max_chars=app.config["MAX_INPUT_CHARS"],
        max_bytes=app.config["MAX_INPUT_BYTES"],
        max_lines=app.config["MAX_LINES"],
    )
    if not text.strip():
        raise AuditInputError("empty_text", 400, "text")
    return AuditInput(text=text, source_name=f"pasted.{source_format}", source_format=source_format, content_language=content_language)


def _too_many_requests(app: Flask) -> Response | None:
    address = normalize_client_address(request.remote_addr)
    try:
        allowed, reset_after, remaining = app.extensions["rapport_auditor.review_quota"].check(address)
    except RateLimitUnavailable as exc:
        raise _ApplicationError("service_unavailable", 503) from exc
    g.rate_limit = (app.config["RATE_LIMIT_MAX_REQUESTS"], remaining, reset_after)
    if allowed:
        return None
    response = _error_response(app, "rate_limited", 429)
    response.headers["Retry-After"] = str(reset_after)
    return response


def _run_with_budget(app: Flask, operation: str, document: AuditInput) -> Any:
    runner = app.extensions["rapport_auditor.analysis_runner"]
    budget = app.extensions.get("rapport_auditor.analysis_budget")
    lease: str | None = None
    if budget is not None:
        try:
            lease = budget.reserve()
        except AnalysisBudgetExceeded as exc:
            raise _ApplicationError("analysis_busy", 503, retry_after=exc.retry_after) from exc
        except RateLimitUnavailable as exc:
            raise _ApplicationError("service_unavailable", 503) from exc

    def settle_once(elapsed_ms: int) -> None:
        nonlocal lease
        if lease is None:
            return
        settled_lease, lease = lease, None
        if budget is None:  # A lease cannot exist without its budget.
            raise _ApplicationError("service_unavailable", 503)
        budget.settle(settled_lease, elapsed_ms)

    started = time.monotonic()
    try:
        return runner.run(
            operation,
            document.text,
            document.source_name,
            document.source_format,
            document.content_language,
        )
    except WorkerCapacityError:
        if lease is not None:
            try:
                settle_once(0)
            except RateLimitUnavailable as exc:
                raise _ApplicationError("service_unavailable", 503) from exc
        raise
    except (WorkerFailure, WorkerTimeoutError):
        if lease is not None:
            reservation_ms = app.config["ANALYSIS_BUDGET_RESERVATION_SECONDS"] * 1000
            try:
                settle_once(reservation_ms)
            except RateLimitUnavailable as exc:
                raise _ApplicationError("service_unavailable", 503) from exc
        raise
    finally:
        if lease is not None:
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000 + 0.999))
            try:
                settle_once(elapsed_ms)
            except RateLimitUnavailable as exc:
                raise _ApplicationError("service_unavailable", 503) from exc


def _analyze(app: Flask, document: AuditInput) -> tuple[Any, Any, str, bool]:
    try:
        result = _run_with_budget(app, "audit", document)
        if len(result) == 4:
            return result
        report, repetition, cleaned_text = result
        cleaned_preview, cleaned_truncated = _excerpt(cleaned_text, 10_000)
        return report, repetition, cleaned_preview, cleaned_truncated
    except WorkerCapacityError as exc:
        raise _ApplicationError("service_unavailable", 503) from exc
    except WorkerTimeoutError as exc:
        raise _ApplicationError("analysis_timeout", 504) from exc
    except WorkerFailure as exc:
        raise _ApplicationError("service_unavailable", 503) from exc


def _revise(app: Flask, document: AuditInput) -> tuple[str, Any, str, bool, int]:
    try:
        result = _run_with_budget(app, "revise", document)
        if len(result) == 5:
            return result
        revised, edits, diff = result
        _preview, diff_truncated = _bounded_diff(diff)
        return revised, edits, _preview, diff_truncated, len(edits)
    except WorkerCapacityError as exc:
        raise _ApplicationError("service_unavailable", 503) from exc
    except WorkerTimeoutError as exc:
        raise _ApplicationError("analysis_timeout", 504) from exc
    except WorkerFailure as exc:
        raise _ApplicationError("service_unavailable", 503) from exc


def _localized_template_context(app: Flask, **values: Any) -> dict[str, Any]:
    context = {
        "locale": _locale(),
        "csrf_token": _new_csrf_token(app),
        "is_public_service": app.config["APP_MODE"] == "server",
        "limits": {
            "max_input_chars": app.config["MAX_INPUT_CHARS"],
            "max_input_bytes": app.config["MAX_INPUT_BYTES"],
            "max_lines": app.config["MAX_LINES"],
            "max_upload_bytes": app.config["MAX_UPLOAD_BYTES"],
        },
        "text": "",
        "source_name": "pasted text",
        "source_format": "txt",
        "content_language": "en",
        "error": None,
        "errors": {},
        "mode": None,
        "report": None,
        "report_dict": None,
        "public_notes": [],
        "public_findings": [],
        "repetition": None,
        "cleaned_text": "",
        "edits": [],
        "diff": "",
        "revised_text": "",
    }
    context.update(values)
    return context


def _static_asset_versions(static_dir: Path) -> dict[str, str]:
    """Fingerprint the small set of package-owned assets used by the page."""
    return {
        filename: hashlib.sha256((static_dir / filename).read_bytes()).hexdigest()[:12]
        for filename in ("style.css", "app.js", "theme.js")
    }


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Create a local app by default or validate the explicit public server profile."""
    package_templates = WEB_PACKAGE_DIR / "templates"
    package_static = WEB_PACKAGE_DIR / "static"
    app = Flask(
        __name__,
        template_folder=str(package_templates),
        static_folder=None,
    )
    asset_versions = _static_asset_versions(package_static)

    @app.context_processor
    def provide_asset_versions() -> dict[str, dict[str, str]]:
        return {"asset_versions": asset_versions}

    app.request_class = BoundedMemoryRequest
    try:
        app.config.update(load_environment())
    except ConfigurationError:
        raise
    if config is not None:
        app.config.update(config)
    if app.config.get("APP_MODE") == "server":
        app.config["TRUSTED_HOSTS"] = tuple(normalize_host(host) for host in app.config["TRUSTED_HOSTS"])
        app.config["TRUSTED_ORIGINS"] = tuple(
            normalize_https_origin(origin) for origin in app.config["TRUSTED_ORIGINS"]
        )
    if app.config.get("APP_MODE") == "local" and not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_urlsafe(48)
    app.config.setdefault("THREADS", 4)
    app.config.setdefault("TRUSTED_ORIGINS", ())
    app.config.setdefault("TRUSTED_PROXY", "")
    app.config.setdefault("ANALYSIS_MAX_WORKERS", 2)
    app.config.setdefault("ANALYSIS_TIMEOUT_SECONDS", 10.0)
    app.config.setdefault("WORKER_MEMORY_MB", 512)
    app.config.setdefault("WORKER_CPU_SECONDS", 8)
    app.config.setdefault("REDIS_TIMEOUT_SECONDS", 0.5)
    app.config.setdefault("RATE_LIMIT_NAMESPACE", "rapport-auditor:prod")
    validate_config(app.config)
    app.debug = False

    configured_limiter = app.config.get("RATE_LIMITER")
    if configured_limiter is not None:
        rate_limiter = configured_limiter
    elif app.config["APP_MODE"] == "server":
        rate_limiter = RedisSlidingWindowRateLimiter(
            redis_url=app.config["REDIS_URL"],
            secret_key=app.config["SECRET_KEY"],
            limit=app.config["RATE_LIMIT_MAX_REQUESTS"],
            window_seconds=app.config["RATE_LIMIT_WINDOW_SECONDS"],
            max_clients=app.config["RATE_LIMIT_MAX_CLIENTS"],
            timeout_seconds=app.config["REDIS_TIMEOUT_SECONDS"],
            namespace=app.config["RATE_LIMIT_NAMESPACE"],
            hourly_limit=app.config["RATE_LIMIT_HOURLY_MAX_REQUESTS"],
            hourly_window_seconds=app.config["RATE_LIMIT_HOURLY_WINDOW_SECONDS"],
            attempt_limit=app.config["REVIEW_ATTEMPT_MAX_REQUESTS"],
        )
    else:
        from .security import InMemoryRateLimiter

        rate_limiter = InMemoryRateLimiter(
            limit=app.config["RATE_LIMIT_MAX_REQUESTS"],
            window_seconds=app.config["RATE_LIMIT_WINDOW_SECONDS"],
            max_clients=app.config["RATE_LIMIT_MAX_CLIENTS"],
        )
    review_quota = rate_limiter
    early_attempt_limiter = None
    analysis_budget = None
    if app.config["APP_MODE"] == "server":
        injected_guards = (
            app.config.get("REVIEW_QUOTA"),
            app.config.get("EARLY_ATTEMPT_LIMITER"),
            app.config.get("ANALYSIS_BUDGET"),
        )
        if configured_limiter is None:
            review_quota = rate_limiter
            early_attempt_limiter = rate_limiter
            analysis_budget = RedisAnalysisWorkBudget(
                client=rate_limiter.client,
                namespace=app.config["RATE_LIMIT_NAMESPACE"],
                budget_seconds=app.config["ANALYSIS_BUDGET_SECONDS"],
                window_seconds=app.config["ANALYSIS_BUDGET_WINDOW_SECONDS"],
                reservation_seconds=app.config["ANALYSIS_BUDGET_RESERVATION_SECONDS"],
                max_admissions=app.config["ANALYSIS_BUDGET_MAX_ADMISSIONS"],
            )
        else:
            if any(guard is None for guard in injected_guards):
                raise ConfigurationError(
                    "A server RATE_LIMITER test override must explicitly inject REVIEW_QUOTA, "
                    "EARLY_ATTEMPT_LIMITER, and ANALYSIS_BUDGET"
                )
            review_quota, early_attempt_limiter, analysis_budget = injected_guards
        if not callable(getattr(review_quota, "check", None)):
            raise ConfigurationError("REVIEW_QUOTA must provide check(address)")
        if not callable(getattr(early_attempt_limiter, "check_early_attempt", None)):
            raise ConfigurationError("EARLY_ATTEMPT_LIMITER must provide check_early_attempt(address)")
        if not callable(getattr(analysis_budget, "reserve", None)) or not callable(
            getattr(analysis_budget, "settle", None)
        ):
            raise ConfigurationError("ANALYSIS_BUDGET must provide reserve() and settle(lease, elapsed_ms)")
    app.extensions["rapport_auditor.rate_limiter"] = rate_limiter
    app.extensions["rapport_auditor.review_quota"] = review_quota
    app.extensions["rapport_auditor.early_attempt_limiter"] = early_attempt_limiter
    app.extensions["rapport_auditor.analysis_budget"] = analysis_budget
    configured_runner = app.config.get("ANALYSIS_RUNNER")
    if configured_runner is not None:
        analysis_runner = configured_runner
    elif app.config["APP_MODE"] == "server":
        analysis_runner = BoundedAnalysisWorkers(
            max_workers=app.config["ANALYSIS_MAX_WORKERS"],
            timeout_seconds=app.config["ANALYSIS_TIMEOUT_SECONDS"],
            memory_mb=app.config["WORKER_MEMORY_MB"],
            cpu_seconds=app.config["WORKER_CPU_SECONDS"],
        )
    else:
        analysis_runner = LocalAnalysisRunner(max_workers=app.config["ANALYSIS_MAX_WORKERS"])
    app.extensions["rapport_auditor.analysis_runner"] = analysis_runner
    app.extensions["rapport_auditor.upload_storage"] = "bounded-memory"

    @app.before_request
    def enforce_host_origin_and_csrf() -> Response | None:
        g.request_id = uuid.uuid4().hex
        g.request_started = time.monotonic()
        if not is_trusted_host(request.host, app.config["TRUSTED_HOSTS"]):
            return Response("Bad Request", status=400, content_type="text/plain; charset=utf-8")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and isinstance(
            request.routing_exception, HTTPException
        ):
            status = request.routing_exception.code or 400
            code = "not_found" if status == 404 else "method_not_allowed" if status == 405 else "server_error"
            return _early_rejection_response(app, code=code, status_code=status)
        if (
            app.config["APP_MODE"] == "server"
            and request.method == "POST"
            and request.path in _REVIEW_POST_PATHS
        ):
            address = normalize_client_address(request.remote_addr)
            try:
                allowed, retry_after, remaining = app.extensions[
                    "rapport_auditor.early_attempt_limiter"
                ].check_early_attempt(address)
            except RateLimitUnavailable:
                return _early_rejection_response(app, code="service_unavailable", status_code=503)
            except Exception as exc:
                logging.getLogger("rapport_api").warning(
                    json.dumps(
                        {"event": "early_limiter_failure", "reason": type(exc).__name__},
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
                return _early_rejection_response(app, code="service_unavailable", status_code=503)
            g.rate_limit = (app.config["REVIEW_ATTEMPT_MAX_REQUESTS"], remaining, retry_after)
            if not allowed:
                return _early_rejection_response(
                    app,
                    code="attempt_rate_limited",
                    status_code=429,
                    retry_after=retry_after,
                )
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None

        if request.path.startswith("/api/") and request.mimetype != "application/json":
            return _error_response(app, "unsupported_media_type", 415)
        if not request.path.startswith("/api/") and request.mimetype not in {"multipart/form-data", "application/x-www-form-urlencoded"}:
            return _error_response(app, "invalid_form", 415)

        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site == "cross-site":
            return _error_response(app, "origin_rejected", 403)
        if app.config["APP_MODE"] == "server" and request.scheme != "https":
            return _error_response(app, "origin_rejected", 403)
        if origin:
            try:
                canonical_origin = normalize_https_origin(origin) if app.config["APP_MODE"] == "server" else origin
            except ConfigurationError:
                return _error_response(app, "origin_rejected", 403)
            if not origin_matches(origin, request.scheme, request.host) or (
                app.config["APP_MODE"] == "server" and canonical_origin not in app.config["TRUSTED_ORIGINS"]
            ):
                return _error_response(app, "origin_rejected", 403)
        if not origin and referer:
            try:
                referer_origin = f"{urlsplit(referer).scheme}://{urlsplit(referer).netloc}"
            except ValueError:
                referer_origin = ""
            if (
                not referer_origin
                or not origin_matches(referer_origin, request.scheme, request.host)
                or (app.config["APP_MODE"] == "server" and referer_origin not in app.config["TRUSTED_ORIGINS"])
            ):
                return _error_response(app, "origin_rejected", 403)
        elif app.config["APP_MODE"] == "server" and not origin:
            return _error_response(app, "origin_rejected", 403)

        submitted = request.headers.get("X-CSRF-Token") if request.path.startswith("/api/") else None
        if not request.path.startswith("/api/"):
            try:
                values = request.form.getlist("csrf_token") if request.mimetype in {"multipart/form-data", "application/x-www-form-urlencoded"} else []
                submitted = values[0] if len(values) == 1 else None
            except (BadRequest, RequestEntityTooLarge):
                return _error_response(app, "request_too_large", 413)
        if not verify_csrf_token(
            app.config["SECRET_KEY"],
            submitted,
            request.cookies.get(app.config["CSRF_COOKIE_NAME"]),
            max_age=app.config["CSRF_TOKEN_MAX_AGE"],
        ):
            return _error_response(app, "csrf_failed", 403)
        return None

    @app.after_request
    def set_security_headers(response: Response) -> Response:
        if response.content_length and response.content_length > app.config["MAX_RESPONSE_BYTES"]:
            response = _error_response(app, "server_error", 500)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Keep same-origin native form submissions' Origin intact. `no-referrer`
        # can cause browsers to serialize their Origin as the opaque `null` value.
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "font-src 'self'; connect-src 'self'",
        )
        if request.endpoint in {"static", "favicon"}:
            response.headers["Cache-Control"] = "public, max-age=300, must-revalidate"
        else:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        if app.config["APP_MODE"] == "server":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers["X-Request-ID"] = request_id
            started = getattr(g, "request_started", time.monotonic())
            logging.getLogger("rapport_api").info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "endpoint": request.endpoint or "unknown",
                        "method": request.method,
                        "status": response.status_code,
                        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        if getattr(g, "rate_limit", None):
            limit, remaining, reset_after = g.rate_limit
            response.headers["RateLimit-Limit"] = str(limit)
            response.headers["RateLimit-Remaining"] = str(remaining)
            response.headers["RateLimit-Reset"] = str(reset_after)
        return response

    @app.errorhandler(AuditInputError)
    def handle_input_error(error: AuditInputError) -> Response:
        return _error_response(app, error.code, error.status_code, error.field)

    @app.errorhandler(_ApplicationError)
    def handle_application_error(error: _ApplicationError) -> Response:
        response = _error_response(app, error.code, error.status_code, error.field)
        if error.retry_after is not None:
            response.headers["Retry-After"] = str(max(1, int(error.retry_after)))
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_error: RequestEntityTooLarge) -> Response:
        return _error_response(app, "request_too_large", 413)

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException) -> Response:
        if error.code == 404:
            return _error_response(app, "not_found", 404)
        if error.code == 413:
            return _error_response(app, "request_too_large", 413)
        return _error_response(app, "server_error", error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception) -> Response:
        # Logs contain only exception type and endpoint, never input, headers,
        # filenames, CSRF values, or provider data.
        logging.getLogger("rapport_api").warning(
            json.dumps(
                {
                    "event": "request_failure",
                    "request_id": getattr(g, "request_id", "unknown"),
                    "exception_type": type(error).__name__,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return _error_response(app, "server_error", 500)

    def static_file(filename: str) -> Response:
        candidate = package_static / filename
        if candidate.is_file():
            return send_from_directory(package_static, filename)
        abort(404)

    app.add_url_rule("/static/<path:filename>", endpoint="static", view_func=static_file, methods=["GET"])

    @app.get("/")
    def index() -> Response:
        context = _localized_template_context(app)
        response = make_response(render_template("index.html", **context))
        _set_csrf_cookie(response, app, context["csrf_token"])
        return response

    @app.get("/about")
    def about() -> Response:
        context = _localized_template_context(app, page_path="/about")
        return make_response(render_template("about.html", **context))

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return static_file("favicon.ico")

    @app.get("/api/v1/health")
    def api_health() -> Response:
        return jsonify({"status": "ok", "api_version": "v1"})

    @app.get("/api/v1/health/live")
    def api_health_live() -> Response:
        return jsonify({"status": "live"})

    @app.get("/api/v1/health/ready")
    def api_health_ready() -> Response:
        limiter = app.extensions["rapport_auditor.rate_limiter"]
        runner = app.extensions["rapport_auditor.analysis_runner"]
        ready = True
        if hasattr(limiter, "ready"):
            ready = bool(limiter.ready())
        if ready:
            worker_ready = getattr(runner, "ready", None)
            if callable(worker_ready):
                ready = bool(worker_ready())
            else:
                available = getattr(runner, "available", True)
                if callable(available):
                    available = available()
                ready = bool(available)
        if not ready:
            response = jsonify({"status": "not_ready"})
            response.status_code = 503
            return response
        return jsonify({"status": "ready"})

    @app.get("/api/v1/csrf")
    def api_csrf() -> Response:
        token = _new_csrf_token(app)
        response = jsonify({"csrf_token": token})
        _set_csrf_cookie(response, app, token)
        return response

    def audit_json() -> Response:
        document = _read_api_input(app)
        if not document.text.strip():
            raise AuditInputError("empty_text", 400, "text")
        limited = _too_many_requests(app)
        if limited:
            return limited
        report, repetition, cleaned_text, _cleaned_truncated = _analyze(app, document)
        return jsonify(
            _public_api_audit(
                report,
                repetition,
                cleaned_text,
                document.source_format,
                document.content_language,
            )
        )

    def revise_json() -> Response:
        document = _read_api_input(app)
        limited = _too_many_requests(app)
        if limited:
            return limited
        revised, edits, diff, diff_truncated_from_worker, total_edits = _revise(app, document)
        public_edits, omitted_edits = _public_edits(edits)
        public_diff, diff_truncated = _bounded_diff(diff)
        diff_truncated = diff_truncated or diff_truncated_from_worker
        omitted_edits = max(omitted_edits, total_edits - len(public_edits))
        return jsonify(
            {
                "source_format": document.source_format,
                "content_language": document.content_language,
                "edits": public_edits,
                "edits_summary": {
                    "total_count": total_edits,
                    "displayed_count": len(public_edits),
                    "omitted_count": omitted_edits,
                    "limit": _PUBLIC_EDIT_LIMIT,
                },
                "diff": public_diff,
                "diff_truncated": diff_truncated,
                "revised_text": revised,
            }
        )

    def audit_html() -> Response:
        document = _read_html_input(app)
        if not document.text.strip():
            raise AuditInputError("empty_text", 400, "text")
        limited = _too_many_requests(app)
        if limited:
            return limited
        report, repetition, cleaned_text, cleaned_truncated = _analyze(app, document)
        public = _public_report_dict(report, _locale())
        context = _localized_template_context(
            app,
            mode="audit",
            text=document.text,
            source_name=document.source_name,
            source_format=document.source_format,
            content_language=document.content_language,
            report=_report_view(public),
            report_dict=public,
            public_notes=public["base"]["notes"],
            public_findings=public["findings"],
            repetition=repetition,
            cleaned_text=cleaned_text,
            cleaned_text_truncated=cleaned_truncated,
            findings_total=public["findings_total_count"],
            findings_displayed=public["findings_displayed_count"],
            findings_omitted=public["findings_omitted_count"],
            citation_cues=public["citation_cues"],
            citation_cues_total=public["citation_cues_total_count"],
            citation_cues_displayed=public["citation_cues_displayed_count"],
            citation_cues_omitted=public["citation_cues_omitted_count"],
        )
        response = make_response(render_template("index.html", **context))
        _set_csrf_cookie(response, app, context["csrf_token"])
        return response

    def revise_html() -> Response:
        document = _read_html_input(app)
        if not document.text.strip():
            raise AuditInputError("empty_text", 400, "text")
        limited = _too_many_requests(app)
        if limited:
            return limited
        revised, edits, diff, diff_truncated_from_worker, total_edits = _revise(app, document)
        public_edits, omitted_edits = _public_edits(edits)
        public_diff, diff_truncated = _bounded_diff(diff)
        diff_truncated = diff_truncated or diff_truncated_from_worker
        omitted_edits = max(omitted_edits, total_edits - len(public_edits))
        context = _localized_template_context(
            app,
            mode="revise",
            text=document.text,
            source_name=document.source_name,
            source_format=document.source_format,
            content_language=document.content_language,
            edits=public_edits,
            edits_total=total_edits,
            edits_omitted=omitted_edits,
            diff=public_diff,
            diff_truncated=diff_truncated,
            revised_text=revised,
        )
        response = make_response(render_template("index.html", **context))
        _set_csrf_cookie(response, app, context["csrf_token"])
        return response

    @app.post("/api/v1/audit")
    def api_audit() -> Response:
        return audit_json()

    @app.post("/api/v1/revise")
    def api_revise() -> Response:
        return revise_json()

    @app.post("/audit")
    def audit() -> Response:
        return audit_html()

    @app.post("/revise")
    def revise() -> Response:
        return revise_html()

    return app
