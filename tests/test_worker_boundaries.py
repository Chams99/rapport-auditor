from __future__ import annotations

import json
import multiprocessing
import os
import time
from multiprocessing.shared_memory import SharedMemory

import pytest

import rapport_api.workers as worker_module
from rapport_api.workers import (
    BoundedAnalysisWorkers,
    WorkerFailure,
    WorkerTimeoutError,
)


def _send_message(connection, payload: dict[str, object], *, chunk_bytes: int = 400) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("ascii")
    connection.send_bytes(b"H" + len(body).to_bytes(4, "big"))
    for offset in range(0, len(body), chunk_bytes):
        connection.send_bytes(b"D" + body[offset : offset + chunk_bytes])
    connection.close()


def _send_raw_message(connection, body: bytes) -> None:
    connection.send_bytes(b"H" + len(body).to_bytes(4, "big"))
    connection.send_bytes(b"D" + body)
    connection.close()


def _slow_test_worker(connection, operation, *worker_args):
    del operation, worker_args
    time.sleep(4)
    connection.close()


def _partial_frame_worker(connection, operation, *worker_args):
    del operation, worker_args
    connection.send_bytes(b"H" + (12).to_bytes(4, "big"))
    connection.send_bytes(b"D{\"status\":")
    time.sleep(4)
    connection.close()


def _quick_health_worker(connection, operation, *worker_args):
    del worker_args
    _send_message(connection, {"status": "ok", "operation": operation})


def _wrong_frame_worker(connection, operation, *worker_args):
    del operation, worker_args
    connection.send_bytes(b"not-a-header")
    connection.close()


def _oversized_frame_worker(connection, operation, *worker_args):
    del operation, worker_args
    # The frame itself is kept small; the declared total exceeds the receiver's
    # cap and must be rejected before the parent attempts to read a body.
    connection.send_bytes(b"H" + (7_000_001).to_bytes(4, "big"))
    connection.close()


def _invalid_json_worker(connection, operation, *worker_args):
    del operation, worker_args
    _send_raw_message(connection, b"not-json")


def _read_request_shared_memory_worker(connection, operation, memory_name, request_size, *worker_args):
    del worker_args
    request_memory = SharedMemory(name=memory_name, create=False)
    try:
        request = json.loads(bytes(request_memory.buf[:request_size]).decode("ascii"))
    finally:
        request_memory.close()
    assert request == {"values": ["fictional private draft sentinel"]}
    _send_message(connection, {"status": "ok", "operation": operation})


def _runner(timeout: float = 0.35) -> BoundedAnalysisWorkers:
    return BoundedAnalysisWorkers(
        max_workers=1,
        timeout_seconds=timeout,
        memory_mb=512,
        cpu_seconds=8,
    )


def _track_request_shared_memory(monkeypatch) -> list[str]:
    original = worker_module.SharedMemory
    names: list[str] = []

    def track(*args, **kwargs):
        shared_memory = original(*args, **kwargs)
        if kwargs.get("create"):
            names.append(shared_memory.name)
        return shared_memory

    monkeypatch.setattr(worker_module, "SharedMemory", track)
    return names


def _assert_shared_memory_unlinked(names: list[str]) -> None:
    assert names
    for name in names:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name, create=False)


def _assert_no_new_children(before: set[int]) -> None:
    lingering = [child for child in multiprocessing.active_children() if child.pid not in before]
    assert lingering == []


def test_worker_deadline_kills_and_reaps_child_then_releases_capacity(monkeypatch):
    runner = _runner(timeout=0.3)
    children_before = {child.pid for child in multiprocessing.active_children()}
    monkeypatch.setattr(worker_module, "_worker_entry", _slow_test_worker)
    started = time.monotonic()

    with pytest.raises(WorkerTimeoutError):
        runner.run("health")

    assert time.monotonic() - started < 3.5
    assert runner.available
    _assert_no_new_children(children_before)

    runner.timeout_seconds = 10
    monkeypatch.setattr(worker_module, "_worker_entry", _quick_health_worker)
    assert runner.run("health") is True
    assert runner.available


def test_worker_deadline_covers_partial_json_frame_and_recovers(monkeypatch):
    runner = _runner(timeout=0.3)
    children_before = {child.pid for child in multiprocessing.active_children()}
    monkeypatch.setattr(worker_module, "_worker_entry", _partial_frame_worker)
    started = time.monotonic()

    with pytest.raises(WorkerTimeoutError):
        runner.run("health")

    assert time.monotonic() - started < 3.5
    assert runner.available
    _assert_no_new_children(children_before)

    runner.timeout_seconds = 10
    monkeypatch.setattr(worker_module, "_worker_entry", _quick_health_worker)
    assert runner.run("health") is True
    assert runner.available


@pytest.mark.parametrize("worker", [_wrong_frame_worker, _invalid_json_worker, _oversized_frame_worker])
def test_worker_rejects_invalid_or_over_limit_frame_and_releases_slot(monkeypatch, worker):
    runner = _runner(timeout=2)
    memory_names = _track_request_shared_memory(monkeypatch)
    monkeypatch.setattr(worker_module, "_worker_entry", worker)

    with pytest.raises(WorkerFailure):
        runner.run("health")

    assert runner.available
    _assert_shared_memory_unlinked(memory_names)
    monkeypatch.setattr(worker_module, "_worker_entry", _quick_health_worker)
    assert runner.run("health") is True
    assert runner.available


@pytest.mark.parametrize("component", ["pipe", "process"])
def test_worker_construction_failures_release_capacity(monkeypatch, component):
    runner = _runner(timeout=2)
    memory_names = _track_request_shared_memory(monkeypatch)
    original = getattr(runner._context, "Pipe" if component == "pipe" else "Process")
    first_call = True

    def fail_once(*args, **kwargs):
        nonlocal first_call
        if first_call:
            first_call = False
            raise OSError("synthetic construction failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(runner._context, "Pipe" if component == "pipe" else "Process", fail_once)

    with pytest.raises(WorkerFailure):
        runner.run("health")

    assert runner.available
    _assert_shared_memory_unlinked(memory_names)
    monkeypatch.setattr(worker_module, "_worker_entry", _quick_health_worker)
    assert runner.run("health") is True
    assert runner.available


def test_worker_does_not_pickle_source_into_process_args_and_unlinks_shared_memory(monkeypatch):
    runner = _runner(timeout=2)
    original_process = runner._context.Process
    captured: dict[str, object] = {}

    def capture_process(*args, **kwargs):
        captured["args"] = kwargs.get("args", ())
        return original_process(*args, **kwargs)

    monkeypatch.setattr(runner._context, "Process", capture_process)
    monkeypatch.setattr(worker_module, "_worker_entry", _read_request_shared_memory_worker)

    assert runner.run("health", "fictional private draft sentinel") is True

    process_args = captured["args"]
    assert isinstance(process_args, tuple)
    assert "fictional private draft sentinel" not in repr(process_args)
    assert runner.available
    _assert_shared_memory_unlinked([process_args[2]])


@pytest.mark.skipif(os.name != "posix", reason="Production worker startup applies POSIX resource limits.")
def test_real_analysis_worker_starts_and_returns_bounded_structured_result():
    runner = _runner(timeout=10)
    result = runner.run(
        "audit",
        "The results show a fictional increase (Smith, 2024).",
        "synthetic.txt",
        "txt",
        "en",
    )

    report, repetition, cleaned, truncated = result
    assert report.base.content_language == "en"
    assert report.findings[0].code == "citation_context_prompt"
    assert report.citation_cues[0].syntax == "author-date"
    assert repetition.repeated_starts == []
    assert "fictional increase" in cleaned
    assert truncated is False
    assert runner.available
