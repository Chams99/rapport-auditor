from __future__ import annotations

import difflib
import json
import multiprocessing
from multiprocessing.connection import wait
from multiprocessing.shared_memory import SharedMemory
from threading import Lock
import time
from types import SimpleNamespace
from typing import Any


_FRAME_CHUNK_BYTES = 400
_MAX_WORKER_RESULT_BYTES = 7_000_000
_MAX_FINDINGS = 30
_MAX_CITATION_CUES = 30
_MAX_OCCURRENCES = 10
_MAX_CITATION_KEYS = 20
_MAX_EDITS = 50
_MAX_DIFF_CHARS = 150_000
_MAX_CLEANED_PREVIEW_CHARS = 10_000


class WorkerCapacityError(RuntimeError):
    pass


class WorkerTimeoutError(RuntimeError):
    pass


class WorkerFailure(RuntimeError):
    pass


def _clip(value: str, maximum: int) -> tuple[str, bool]:
    if len(value) <= maximum:
        return value, False
    return value[: maximum - 1].rstrip() + "…", True


def _revision_diff(source_name: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=source_name,
            tofile=f"{source_name} (revision preview)",
        )
    )


def _set_resource_limits(memory_mb: int, cpu_seconds: int) -> None:
    try:
        import resource
    except ImportError as exc:  # pragma: no cover - server mode rejects non-POSIX hosts
        raise RuntimeError("resource limits are unavailable") from exc
    memory_bytes = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _wire_finding(finding: Any) -> dict[str, Any]:
    sentence, sentence_truncated = _clip(finding.sentence, 500)
    reason, reason_truncated = _clip(finding.reason, 400)
    prompt, prompt_truncated = _clip(finding.prompt, 400)
    phrase = None
    phrase_truncated = False
    if finding.phrase is not None:
        phrase, phrase_truncated = _clip(finding.phrase, 160)
    occurrences = list(finding.occurrences)
    citation_keys = list(finding.citation_keys)
    return {
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
        "phrase": phrase,
        "phrase_truncated": phrase_truncated,
        "count": finding.count,
        "occurrences": [
            {"sentence_index": item.sentence_index, "line": item.line}
            for item in occurrences[:_MAX_OCCURRENCES]
        ],
        "occurrences_omitted_count": max(0, len(occurrences) - _MAX_OCCURRENCES),
        "citation_keys": [_clip(key, 120)[0] for key in citation_keys[:_MAX_CITATION_KEYS]],
        "citation_keys_omitted_count": max(0, len(citation_keys) - _MAX_CITATION_KEYS),
    }


def _wire_citation_cue(cue: Any) -> dict[str, Any]:
    syntax, syntax_truncated = _clip(cue.syntax, 120)
    excerpt, excerpt_truncated = _clip(cue.excerpt, 500)
    keys = list(cue.keys)
    return {
        "syntax": syntax,
        "syntax_truncated": syntax_truncated,
        "keys": [_clip(key, 120)[0] for key in keys[:_MAX_CITATION_KEYS]],
        "keys_omitted_count": max(0, len(keys) - _MAX_CITATION_KEYS),
        "line": cue.line,
        "sentence_index": cue.sentence_index,
        "excerpt": excerpt,
        "excerpt_truncated": excerpt_truncated,
    }


def _wire_operation_result(operation: str, result: Any) -> dict[str, Any]:
    if operation == "health":
        return {"status": "ok", "operation": "health"}
    if operation == "audit":
        report, repetition, cleaned = result
        base = report.base
        notes = [_clip(note, 400)[0] for note in base.notes[:5]]
        cleaned_preview, cleaned_truncated = _clip(cleaned, _MAX_CLEANED_PREVIEW_CHARS)
        repeated_starts = [
            {"text": _clip(value, 120)[0], "count": count}
            for value, count in repetition.repeated_starts[:15]
        ]
        repeated_phrases = [
            {"text": _clip(value, 120)[0], "count": count}
            for value, count in repetition.repeated_phrases[:15]
        ]
        return {
            "status": "ok",
            "operation": "audit",
            "data": {
                "base": {
                    "sentence_count": base.sentence_count,
                    "word_count": base.word_count,
                    "content_language": base.content_language,
                    "flagged_sentence_count": base.flagged_sentence_count,
                    "notes": notes,
                },
                "findings": [_wire_finding(item) for item in report.findings[:_MAX_FINDINGS]],
                "findings_total_count": len(report.findings),
                "citation_cues": [
                    _wire_citation_cue(item) for item in report.citation_cues[:_MAX_CITATION_CUES]
                ],
                "citation_cues_total_count": len(report.citation_cues),
                "repetition": {
                    "repeated_starts": repeated_starts,
                    "repeated_phrases": repeated_phrases,
                },
                "cleaned_preview": cleaned_preview,
                "cleaned_preview_truncated": cleaned_truncated,
            },
        }
    if operation == "revise":
        revised, edits, diff = result
        public_edits = []
        for item in edits[:_MAX_EDITS]:
            before, before_truncated = _clip(item.before, 400)
            after, after_truncated = _clip(item.after, 400)
            reason, reason_truncated = _clip(item.reason, 300)
            public_edits.append(
                {
                    "line": item.line,
                    "before": before,
                    "before_truncated": before_truncated,
                    "after": after,
                    "after_truncated": after_truncated,
                    "reason": reason,
                    "reason_truncated": reason_truncated,
                }
            )
        public_diff, diff_truncated = _clip(diff, _MAX_DIFF_CHARS)
        return {
            "status": "ok",
            "operation": "revise",
            "data": {
                "revised_text": revised,
                "edits": public_edits,
                "edits_total_count": len(edits),
                "diff": public_diff,
                "diff_truncated": diff_truncated,
            },
        }
    raise ValueError("unknown operation")


def _send_wire_message(connection: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(body) > _MAX_WORKER_RESULT_BYTES:
        body = b'{"status":"error","error_type":"result_too_large"}'
    connection.send_bytes(b"H" + len(body).to_bytes(4, "big"))
    for offset in range(0, len(body), _FRAME_CHUNK_BYTES):
        chunk = body[offset : offset + _FRAME_CHUNK_BYTES]
        connection.send_bytes(b"D" + chunk)


def _worker_entry(
    connection: Any,
    operation: str,
    request_memory_name: str,
    request_size: int,
    memory_mb: int,
    cpu_seconds: int,
) -> None:
    request_memory = None
    try:
        _set_resource_limits(memory_mb, cpu_seconds)
        request_memory = SharedMemory(name=request_memory_name, create=False)
        request_payload = json.loads(bytes(request_memory.buf[:request_size]).decode("ascii"))
        if not isinstance(request_payload, dict):
            raise ValueError("invalid worker request")
        values = request_payload.get("values")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError("invalid worker request")
        from rapport_auditor.audit import audit_text_deep, strip_latex, strip_pdf_artifacts
        from rapport_auditor.repetition import analyze_repetition
        from rapport_auditor.revise import revise_text

        if operation == "health":
            result = True
        elif operation == "audit":
            text, source_name, source_format, content_language = values
            report = audit_text_deep(
                text,
                source_name,
                content_language=content_language,
                source_format=source_format,
            )
            repetition = analyze_repetition(
                text,
                content_language=content_language,
                source_format=source_format,
            )
            cleaned = strip_pdf_artifacts(text)
            if source_format == "tex":
                cleaned = strip_latex(cleaned)
            result = (report, repetition, cleaned)
        elif operation == "revise":
            text, source_name, source_format, content_language = values
            revised, edits = revise_text(
                text,
                content_language=content_language,
                source_format=source_format,
            )
            result = revised, edits, _revision_diff(source_name, text, revised)
        else:  # pragma: no cover - operation names are internal constants
            raise ValueError("unknown operation")
        _send_wire_message(connection, _wire_operation_result(operation, result))
    except BaseException as exc:  # only the exception type crosses the worker boundary
        try:
            _send_wire_message(connection, {"status": "error", "error_type": type(exc).__name__})
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        if request_memory is not None:
            request_memory.close()
        connection.close()


def _read_wire_frame(connection: Any, process: Any, deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WorkerTimeoutError("analysis exceeded its deadline")
    ready = wait((connection, process.sentinel), timeout=remaining)
    if connection not in ready:
        if process.sentinel in ready:
            raise WorkerFailure("analysis worker exited without a complete result")
        raise WorkerTimeoutError("analysis exceeded its deadline")
    try:
        return connection.recv_bytes(maxlength=_FRAME_CHUNK_BYTES + 16)
    except (EOFError, OSError, ValueError) as exc:
        raise WorkerFailure("analysis worker returned an invalid frame") from exc


def _receive_wire_message(connection: Any, process: Any, deadline: float) -> dict[str, Any]:
    header = _read_wire_frame(connection, process, deadline)
    if len(header) != 5 or header[:1] != b"H":
        raise WorkerFailure("analysis worker returned an invalid header")
    expected_length = int.from_bytes(header[1:], "big")
    if not 0 < expected_length <= _MAX_WORKER_RESULT_BYTES:
        raise WorkerFailure("analysis worker returned an invalid result size")
    body = bytearray()
    while len(body) < expected_length:
        frame = _read_wire_frame(connection, process, deadline)
        if not frame.startswith(b"D") or len(frame) == 1:
            raise WorkerFailure("analysis worker returned an invalid data frame")
        chunk = frame[1:]
        if len(body) + len(chunk) > expected_length:
            raise WorkerFailure("analysis worker returned excess result data")
        body.extend(chunk)
    try:
        payload = json.loads(body.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerFailure("analysis worker returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise WorkerFailure("analysis worker returned an invalid result")
    return payload


def _namespace(value: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(**value)


def _restore_audit_result(data: dict[str, Any]) -> tuple[Any, Any, str, bool]:
    base = _namespace(data["base"])
    findings = []
    for item in data["findings"]:
        occurrences = [_namespace(value) for value in item.pop("occurrences")]
        item["occurrences"] = occurrences
        findings.append(_namespace(item))
    cues = [_namespace(item) for item in data["citation_cues"]]
    report = SimpleNamespace(
        base=base,
        findings=findings,
        citation_cues=cues,
        findings_total_count=data["findings_total_count"],
        citation_cues_total_count=data["citation_cues_total_count"],
    )
    repetition = SimpleNamespace(
        repeated_starts=[tuple(item.values()) for item in data["repetition"]["repeated_starts"]],
        repeated_phrases=[tuple(item.values()) for item in data["repetition"]["repeated_phrases"]],
    )
    return report, repetition, data["cleaned_preview"], bool(data["cleaned_preview_truncated"])


def _restore_revision_result(data: dict[str, Any]) -> tuple[str, list[Any], str, bool, int]:
    edits = [_namespace(item) for item in data["edits"]]
    return (
        data["revised_text"],
        edits,
        data["diff"],
        bool(data["diff_truncated"]),
        int(data["edits_total_count"]),
    )


class BoundedAnalysisWorkers:
    """Spawn one bounded process per task and cap the entire worker IPC deadline."""

    def __init__(self, *, max_workers: int, timeout_seconds: float, memory_mb: int, cpu_seconds: int) -> None:
        if max_workers < 1 or timeout_seconds <= 0 or memory_mb < 128 or cpu_seconds < 1:
            raise ValueError("analysis worker limits must be positive and bounded")
        self.max_workers = max_workers
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb
        self.cpu_seconds = cpu_seconds
        self._context = multiprocessing.get_context("spawn")
        self._lock = Lock()
        self._ready_lock = Lock()
        self._active = 0
        self._startup_ok = False
        self._startup_checked = False
        self._startup_retry_after = 0.0

    @property
    def available(self) -> bool:
        with self._lock:
            return self._active < self.max_workers

    def ready(self) -> bool:
        with self._ready_lock:
            if self._startup_checked:
                if self._startup_ok:
                    # A ready worker subsystem remains ready while its bounded
                    # request slot is occupied; capacity is enforced by run().
                    return True
                if time.monotonic() < self._startup_retry_after:
                    return False
            if not self.available:
                return False
            try:
                self._startup_ok = self.run("health") is True
            except (WorkerCapacityError, WorkerTimeoutError, WorkerFailure):
                self._startup_checked = True
                self._startup_retry_after = time.monotonic() + 5.0
                return False
            self._startup_checked = True
            if not self._startup_ok:
                self._startup_retry_after = time.monotonic() + 5.0
            return self._startup_ok

    def run(self, operation: str, *values: Any) -> Any:
        with self._lock:
            if self._active >= self.max_workers:
                raise WorkerCapacityError("analysis capacity is full")
            self._active += 1

        parent = None
        child = None
        process = None
        request_memory = None
        started = False
        deadline = time.monotonic() + self.timeout_seconds
        try:
            request_body = json.dumps(
                {"values": list(values)},
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
            if len(request_body) > 6_100_000:
                raise WorkerFailure("analysis request exceeds worker transport bounds")
            request_memory = SharedMemory(create=True, size=max(1, len(request_body)))
            request_memory.buf[: len(request_body)] = request_body
            parent, child = self._context.Pipe(duplex=False)
            process = self._context.Process(
                target=_worker_entry,
                args=(
                    child,
                    operation,
                    request_memory.name,
                    len(request_body),
                    self.memory_mb,
                    self.cpu_seconds,
                ),
                daemon=True,
            )
            process.start()
            started = True
            child.close()

            payload = _receive_wire_message(parent, process, deadline)
            remaining = max(0.0, deadline - time.monotonic())
            process.join(timeout=remaining)
            if process.is_alive():
                raise WorkerTimeoutError("analysis exceeded its deadline")
            if process.exitcode != 0:
                raise WorkerFailure("analysis worker exited unsuccessfully")
            if payload.get("status") != "ok":
                raise WorkerFailure("analysis worker failed")
            if payload.get("operation") != operation:
                raise WorkerFailure("analysis worker returned the wrong result type")
            if operation == "health":
                return True
            data = payload.get("data")
            if not isinstance(data, dict):
                raise WorkerFailure("analysis worker returned an invalid result")
            if operation == "audit":
                return _restore_audit_result(data)
            if operation == "revise":
                return _restore_revision_result(data)
            raise WorkerFailure("unknown analysis operation")
        except WorkerTimeoutError:
            self._startup_ok = False
            self._startup_checked = True
            self._startup_retry_after = time.monotonic() + 5.0
            raise
        except WorkerFailure:
            self._startup_ok = False
            self._startup_checked = True
            self._startup_retry_after = time.monotonic() + 5.0
            raise
        except BaseException as exc:
            self._startup_ok = False
            self._startup_checked = True
            self._startup_retry_after = time.monotonic() + 5.0
            raise WorkerFailure("analysis worker could not start or complete") from exc
        finally:
            if parent is not None:
                parent.close()
            if child is not None:
                child.close()
            if request_memory is not None:
                request_memory.close()
                try:
                    request_memory.unlink()
                except FileNotFoundError:
                    pass
            if process is not None and started:
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.1)
                try:
                    process.close()
                except ValueError:
                    pass
            with self._lock:
                self._active -= 1


class LocalAnalysisRunner:
    """Synchronous implementation used by the explicitly local profile."""

    available = True

    def __init__(self, *, max_workers: int = 1) -> None:
        self.max_workers = max_workers

    def ready(self) -> bool:
        return True

    def run(self, operation: str, *values: Any) -> Any:
        from rapport_auditor.audit import audit_text_deep, strip_latex, strip_pdf_artifacts
        from rapport_auditor.repetition import analyze_repetition
        from rapport_auditor.revise import revise_text

        if operation == "audit":
            text, source_name, source_format, content_language = values
            report = audit_text_deep(
                text,
                source_name,
                content_language=content_language,
                source_format=source_format,
            )
            repetition = analyze_repetition(
                text,
                content_language=content_language,
                source_format=source_format,
            )
            cleaned = strip_pdf_artifacts(text)
            if source_format == "tex":
                cleaned = strip_latex(cleaned)
            return report, repetition, cleaned
        if operation == "revise":
            text, source_name, source_format, content_language = values
            revised, edits = revise_text(
                text,
                content_language=content_language,
                source_format=source_format,
            )
            return revised, edits, _revision_diff(source_name, text, revised)
        raise ValueError("unknown analysis operation")
