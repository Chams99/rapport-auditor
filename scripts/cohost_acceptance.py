#!/usr/bin/env python3
"""Run one bounded synthetic acceptance sample against the cohosted Rapport app."""

from __future__ import annotations

import concurrent.futures
import http.cookiejar
import json
import os
import re
import selectors
import secrets
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


URL = "https://rapport.chames.tn"
MAX_CHARS, MAX_RESPONSE, MAX_LOG_BYTES, MAX_LOG_LINES = 250_000, 8_000_000, 4 * 1024**2, 1001
REQUEST_TIMEOUT, LOG_TIMEOUT = 40, 8
START_MEM, FINAL_MEM, DOCKER_DISK = 3 * 1024**3, 1 * 1024**3, 4 * 1024**3
ID_RE = re.compile(r"^[0-9a-f]{12,64}$")
CPU_RE = re.compile(r"^\d+(?:\.\d+)?%$")
MEM_RE = re.compile(r"^\d+(?:\.\d+)?(?:B|kB|MB|GB|TB|KiB|MiB|GiB|TiB) / \d+(?:\.\d+)?(?:B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )


def _request(opener, path, data=None, headers=None):
    req = urllib.request.Request(URL + path, data=data, headers=headers or {})
    try:
        response = opener.open(req, timeout=REQUEST_TIMEOUT)
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, b"", ""
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("HTTPS request failed") from exc
    with response:
        parsed = urllib.parse.urlsplit(response.geturl())
        if parsed.scheme != "https" or parsed.hostname != "rapport.chames.tn" or parsed.port not in {None, 443}:
            raise RuntimeError("HTTPS response changed origin")
        try:
            body = response.read(MAX_RESPONSE + 1)
        except OSError as exc:
            raise RuntimeError("HTTPS response could not be read") from exc
        if len(body) > MAX_RESPONSE:
            raise RuntimeError("HTTPS response exceeded the 8 MB read bound")
        return response.status, body, response.headers.get_content_type()


def _json(body):
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _synthetic_text(language, canary):
    if language == "en":
        prefix = f"Synthetic marker {canary} belongs to this fictional methods document. "
        sentences = (
            "Fictional preparation cycle {n:05d} assigns synthetic specimen {k:03d} to a neutral station and follows a documented setup sequence.",
            "The fictional procedure places instrument {k:03d} at a controlled station before the next planned workflow step.",
            "A methods note records the synthetic material, the neutral setting, and the planned handling sequence for cycle {n:05d}.",
            "This fictional workflow describes a measured setup and a neutral procedural transition for specimen {k:03d}.",
        )
    else:
        prefix = f"Le marqueur synthétique {canary} figure dans cette note de méthode fictive. "
        sentences = (
            "Le cycle fictif {n:05d} affecte le spécimen synthétique {k:03d} à un poste neutre et suit une séquence de préparation documentée.",
            "La procédure fictive place l’instrument {k:03d} à un poste contrôlé avant l’étape planifiée suivante.",
            "Une note de méthode décrit le matériau synthétique, le cadre neutre et la séquence prévue pour le cycle {n:05d}.",
            "Ce parcours fictif décrit un dispositif mesuré et une transition procédurale neutre pour le spécimen {k:03d}.",
        )
    parts, size, cycle = [prefix], len(prefix), 1
    while size < MAX_CHARS:
        line = " ".join(s.format(n=cycle, k=(cycle * 37) % 997) for s in sentences) + "\n"
        line = line[: MAX_CHARS - size]
        parts.append(line)
        size += len(line)
        cycle += 1
    text = "".join(parts)
    if len(text) != MAX_CHARS or len(text.splitlines()) > 10_000 or len(text.encode("utf-8")) > 1_000_000:
        raise RuntimeError("synthetic fixture exceeded the app input bounds")
    return text


def _valid_audit(body, language, content_type):
    payload = _json(body)
    if content_type != "application/json" or payload is None or payload.get("content_language") != language or payload.get("source_format") != "txt":
        return False
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        return False
    counts = (summary.get("word_count"), summary.get("sentence_count"), summary.get("finding_count"))
    return (
        type(counts[0]) is int and counts[0] > 0
        and type(counts[1]) is int and counts[1] > 0
        and type(counts[2]) is int and counts[2] >= 0
        and isinstance(payload.get("findings"), list)
        and isinstance(payload.get("citation_cues"), list)
    )


def _ids():
    compose = ["docker", "compose", "--project-name", "rapport-auditor-traefik", "--env-file", "deployment/.env.traefik", "-f", "deployment/compose.traefik.yaml"]
    result = {}
    for role in ("app", "redis"):
        value = _run(compose + ["ps", "-q", role])
        ids = value.splitlines() if value is not None else []
        if len(ids) != 1 or not ID_RE.fullmatch(ids[0]):
            raise RuntimeError(f"expected one Rapport {role} container")
        result[role] = ids[0]
    traefik = _run(["docker", "inspect", "--format", "{{.Id}}", "traefik"])
    if traefik is None or not ID_RE.fullmatch(traefik):
        raise RuntimeError("could not identify Traefik")
    result["traefik"] = traefik
    return result


def _run(args, timeout=8):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _states(ids):
    fmt = (
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.OOMKilled}}|"
        "{{.RestartCount}}|{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|"
        '{{range .Config.Env}}{{if eq . "RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS=2"}}workers2{{end}}{{end}}'
    )
    states = {}
    for role, container_id in ids.items():
        value = _run(["docker", "inspect", "--format", fmt, container_id])
        fields = value.split("|") if value else []
        if len(fields) != 7 or fields[2] not in {"true", "false"}:
            raise RuntimeError("selected container metadata was unavailable")
        try:
            restarts, memory, cpus = map(int, fields[3:6])
        except ValueError as exc:
            raise RuntimeError("selected container limits were unavailable") from exc
        states[role] = (fields[0], fields[1], fields[2] == "true", restarts, memory, cpus, fields[6] == "workers2")
    return states


def _host(docker_root):
    available = next((int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")), None)
    load = tuple(float(v) for v in Path("/proc/loadavg").read_text().split()[:3])
    return available, load, shutil.disk_usage(docker_root).free


def _stats(ids):
    fmt = "{{.ID}}|{{.CPUPerc}}|{{.MemUsage}}|{{.PIDs}}"
    out = _run(["docker", "stats", "--no-stream", "--format", fmt, *ids.values()], timeout=12)
    stats = {}
    for line in out.splitlines() if out is not None else ():
        fields = line.split("|")
        if len(fields) != 4 or not ID_RE.fullmatch(fields[0]) or not CPU_RE.fullmatch(fields[1]) or not MEM_RE.fullmatch(fields[2]) or not fields[3].isdigit():
            raise RuntimeError("selected container statistics were malformed")
        roles = [name for name, value in ids.items() if value.startswith(fields[0])]
        if len(roles) != 1:
            raise RuntimeError("selected container statistics did not match")
        stats[roles[0]] = f"cpu={fields[1]} memory={fields[2]} pids={fields[3]}"
    if set(stats) != set(ids):
        raise RuntimeError("selected container statistics were incomplete")
    return stats


def _sample(label, ids, docker_root):
    available, load, free = _host(docker_root)
    stats = _stats(ids)
    print(f"sample={label} mem_available_mib={available // 2**20} docker_free_gib={free / 2**30:.2f} load={load[0]:.2f},{load[1]:.2f},{load[2]:.2f}")
    for role in ("app", "redis", "traefik"):
        print(f"container_sample={role} {stats[role]}")
    return available, free


def _ready():
    status, body, content_type = _request(_opener(), "/api/v1/health/ready")
    value = _json(body)
    return status == 200 and content_type == "application/json" and value is not None and value.get("status") == "ready"


def _bootstrap(language, query_canary, body_canary):
    opener = _opener()
    path = "/api/v1/csrf?" + urllib.parse.urlencode({"probe": query_canary})
    status, body, content_type = _request(opener, path)
    value = _json(body)
    token = value.get("csrf_token") if value else None
    if status != 200 or content_type != "application/json" or not isinstance(token, str) or not token or len(token) > 4096:
        raise RuntimeError(f"{language} CSRF bootstrap failed")
    return opener, token, language, body_canary, _synthetic_text(language, body_canary)


def _post(session):
    opener, token, language, _canary, text = session
    data = json.dumps({"text": text, "source_format": "txt", "content_language": language}, separators=(",", ":")).encode()
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Origin": URL, "X-CSRF-Token": token}
    start = time.monotonic()
    status, body, content_type = _request(opener, "/api/v1/audit", data, headers)
    return status, time.monotonic() - start, _valid_audit(body, language, content_type)


def _classify_logs(data, markers):
    lines = data.count(b"\n") + bool(data and not data.endswith(b"\n"))
    if len(data) > MAX_LOG_BYTES or lines >= MAX_LOG_LINES:
        return None
    return {name: marker.encode("ascii") in data for name, marker in markers.items()}


def _logs(container_id, since, until, markers):
    try:
        proc = subprocess.Popen(
            ["docker", "logs", "--since", since, "--until", until, "--tail", str(MAX_LOG_LINES), container_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError:
        return None
    data, deadline = bytearray(), time.monotonic() + LOG_TIMEOUT

    def kill_and_reap():
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    try:
        with proc.stdout, selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    kill_and_reap()
                    return None
                events = selector.select(min(remaining, 1))
                if not events:
                    if proc.poll() is not None:
                        break
                    continue
                chunk = os.read(proc.stdout.fileno(), min(65536, MAX_LOG_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_LOG_BYTES:
                    kill_and_reap()
                    return None
        if proc.wait(timeout=max(0.1, deadline - time.monotonic())) != 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        kill_and_reap()
        return None
    return _classify_logs(bytes(data), markers)


def _utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    try:
        if os.name != "posix" or not Path("/proc/meminfo").is_file():
            raise RuntimeError("run this check on the Linux VPS")
        ids = _ids()
        docker_root = Path(_run(["docker", "info", "--format", "{{.DockerRootDir}}"]) or "")
        if not docker_root.is_absolute():
            raise RuntimeError("Docker storage path was unavailable")
        states = _states(ids)
        expected = {"app": (2 * 2**30, 2_000_000_000), "redis": (256 * 2**20, 500_000_000)}
        for role in ("app", "redis", "traefik"):
            state = states[role]
            if state[0] != "running" or state[2] or role in expected and state[1] != "healthy":
                raise RuntimeError("selected container is not healthy and running")
        for role, values in expected.items():
            if states[role][4:6] != values:
                raise RuntimeError("Rapport limits do not match the reviewed profile")
        if not states["app"][6]:
            raise RuntimeError("the configured analysis worker count is not two")
        before, free = _sample("before", ids, docker_root)
        if before < START_MEM or free < DOCKER_DISK:
            raise RuntimeError("host headroom is below the preflight stop threshold")
        if not _ready():
            raise RuntimeError("public HTTPS readiness check failed")

        query = {lang: "RAQUERY_" + secrets.token_hex(16) for lang in ("en", "fr")}
        body = {lang: "RABODY_" + secrets.token_hex(16) for lang in ("en", "fr")}
        since = _utc()
        sessions = [_bootstrap(lang, query[lang], body[lang]) for lang in ("en", "fr")]
        low_mem, started = False, time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_post, session) for session in sessions]
            while True:
                available, _ = _sample("during", ids, docker_root)
                low_mem |= available < FINAL_MEM
                if all(f.done() for f in futures):
                    break
                if time.monotonic() - started > REQUEST_TIMEOUT + 10:
                    raise RuntimeError("request window exceeded its bound")
                time.sleep(1)
            results = [f.result() for f in futures]

        time.sleep(2)
        until = _utc()
        after, free = _sample("after", ids, docker_root)
        final = _states(ids)
        ready = _ready()
        unchanged = all(final[r][0] == "running" and not final[r][2] and final[r][3] == states[r][3] and (r == "traefik" or final[r][1] == "healthy") for r in ids)
        markers = {f"{lang}_query": query[lang] for lang in query} | {f"{lang}_body": body[lang] for lang in body}
        logs_ok = True
        for role in ("app", "traefik"):
            result = _logs(ids[role], since, until, markers)
            if result is None:
                print(f"log_canary={role} unavailable")
                logs_ok = False
            else:
                print(f"log_canary={role} " + " ".join(f"{key}={'present' if found else 'absent'}" for key, found in result.items()))
                logs_ok &= not any(result.values())
        requests_ok = True
        for lang, (status, elapsed, valid) in zip(("en", "fr"), results):
            print(f"audit={lang} status={status} seconds={elapsed:.2f} schema={'ok' if valid else 'failed'}")
            requests_ok &= status == 200 and valid
        print(f"readiness_after={'healthy' if ready else 'failed'} container_restart_oom_check={'ok' if unchanged else 'failed'}")
        if low_mem or after < FINAL_MEM or free < DOCKER_DISK:
            print("resource_guard=failed")
            return 1
        print("resource_guard=ok")
        passed = requests_ok and ready and unchanged and logs_ok
        print("ACCEPTANCE=passed (sampled representative load; not a capacity guarantee)" if passed else "ACCEPTANCE=failed")
        return 0 if passed else 1
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else "unexpected check error"
        print(f"ACCEPTANCE=stopped ({message}; no containers were started, stopped, or reconfigured)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
