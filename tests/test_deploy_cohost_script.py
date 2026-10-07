from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "deploy_cohost.sh"


def _bash_executable() -> str | None:
    if os.name == "nt":
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _fixture_repo(root: Path) -> tuple[Path, Path, Path]:
    (root / "scripts").mkdir(parents=True)
    (root / "deployment").mkdir()
    script = root / "scripts" / "deploy_cohost.sh"
    shutil.copy2(SCRIPT, script)
    (root / "scripts" / "prepare_traefik_ingress.py").write_text("", encoding="utf-8")
    (root / "scripts" / "container_smoke.py").write_text("synthetic container smoke source\n", encoding="utf-8")
    (root / "scripts" / "release_http_smoke.py").write_text("", encoding="utf-8")
    example = root / "deployment" / ".env.traefik.example"
    example.write_text(
        "\n".join(
            (
                "RAPPORT_AUDITOR_PUBLIC_DOMAIN=rapport.chames.tn",
                "RAPPORT_AUDITOR_INGRESS_NETWORK=rapport-auditor-ingress",
                "RAPPORT_AUDITOR_TRUSTED_PROXY=172.27.0.2",
                "RAPPORT_AUDITOR_SECRET_FILE=./secrets/rapport_secret_key",
                "RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS=2",
                "RAPPORT_AUDITOR_APP_MEMORY_LIMIT=2g",
                "RAPPORT_AUDITOR_APP_CPU_LIMIT=2.0",
                "",
            )
        ),
        encoding="utf-8",
    )
    log = root / "events.log"
    bin_dir = root / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "python3",
        """#!/bin/sh
printf 'python %s\\n' "$1" >> "$EVENT_LOG"
case "$1" in
  scripts/prepare_traefik_ingress.py|scripts/release_http_smoke.py) exit 0 ;;
  -|-c) exec "$REAL_PYTHON" "$@" ;;
  *) exit 97 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/bin/sh
printf 'docker %s\\n' "$*" >> "$EVENT_LOG"
if [ "$1" = compose ]; then
  case "$*" in
    *"exec -T app sh -c"*) cat > "$SMOKE_CAPTURE" ;;
  esac
  if [ "${RAPPORT_AUDITOR_PUBLIC_DOMAIN+x}" = x ] ||
     [ "${RAPPORT_AUDITOR_INGRESS_NETWORK+x}" = x ] ||
     [ "${RAPPORT_AUDITOR_TRUSTED_PROXY+x}" = x ] ||
     [ "${RAPPORT_AUDITOR_APP_MEMORY_LIMIT+x}" = x ] ||
     [ "${RAPPORT_AUDITOR_APP_CPU_LIMIT+x}" = x ]; then
    printf 'leaked\\n' > "$LEAK_FILE"
  fi
  case "$*" in *"ps -q app"*) printf 'a%.0s' $(seq 1 64); printf '\\n' ;; esac
elif [ "$1" = inspect ]; then
  printf 'healthy\\n'
fi
""",
    )
    _write_executable(
        bin_dir / "sudo",
        """#!/bin/sh
printf 'sudo %s\\n' "$*" >> "$EVENT_LOG"
case "$1" in
  chown) exit 0 ;;
  chmod) shift; exec chmod "$@" ;;
  python3) shift; exec "$REAL_PYTHON" "$@" ;;
  *) exit 98 ;;
esac
""",
    )
    _write_executable(bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
    return script, log, bin_dir


def _run_wrapper(script: Path, log: Path, bin_dir: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    bash = _bash_executable()
    if not bash:
        pytest.skip("A Bash runtime is required for the wrapper contract test.")
    environment = os.environ.copy()
    environment.pop("COMPOSE_FILE", None)
    environment.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "EVENT_LOG": str(log),
            "LEAK_FILE": str(log.parent / "compose-env-leak"),
            "SMOKE_CAPTURE": str(log.parent / "container-smoke-input.py"),
            "REAL_PYTHON": sys.executable,
            **extra_env,
        }
    )
    return subprocess.run(
        [bash, str(script)],
        text=True,
        capture_output=True,
        env=environment,
        timeout=30,
        check=False,
    )


def test_wrapper_validates_private_values_and_unsets_shell_overrides(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("The end-to-end wrapper check requires the target Linux shell and file modes.")
    repo = tmp_path / "repo"
    script, log, bin_dir = _fixture_repo(repo)

    result = _run_wrapper(
        script,
        log,
        bin_dir,
        RAPPORT_AUDITOR_PUBLIC_DOMAIN="wrong.example",
        RAPPORT_AUDITOR_TRUSTED_PROXY="172.27.0.99",
        RAPPORT_AUDITOR_APP_MEMORY_LIMIT="99g",
    )

    assert result.returncode == 0, result.stderr
    assert not (log.parent / "compose-env-leak").exists()
    events = log.read_text(encoding="utf-8").splitlines()
    assert events[0] == "python scripts/prepare_traefik_ingress.py"
    assert any("config --quiet" in event for event in events)
    assert any("build app" in event for event in events)
    assert any("up -d" in event for event in events)
    assert any("exec -T app sh -c cat > /tmp/rapport-container-smoke.py" in event for event in events)
    assert not any(" compose cp " in f" {event} " for event in events)
    assert (log.parent / "container-smoke-input.py").read_text(encoding="utf-8") == "synthetic container smoke source\n"
    assert events[-1] == "python scripts/release_http_smoke.py"
    env_file = repo / "deployment" / ".env.traefik"
    secret_file = repo / "deployment" / "secrets" / "rapport_secret_key"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o400
    assert len(secret_file.read_bytes()) >= 32
    source = script.read_text(encoding="utf-8")
    assert "RAPPORT_AUDITOR_RELEASE_BASE_URL=https://rapport.chames.tn" in source
    assert "RAPPORT_AUDITOR_RELEASE_BASE_URL=https://rapport.chames.tn" not in result.stdout
    assert "quota" in result.stdout and "signoff remains outstanding" in result.stdout


def test_wrapper_rejects_wrong_private_peer_without_compose_or_value_echo(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("The end-to-end wrapper check runs in its target Linux shell.")
    repo = tmp_path / "repo"
    script, log, bin_dir = _fixture_repo(repo)
    env_file = repo / "deployment" / ".env.traefik"
    example = repo / "deployment" / ".env.traefik.example"
    env_file.write_text(
        example.read_text(encoding="utf-8").replace("172.27.0.2", "172.27.0.99"),
        encoding="utf-8",
    )

    result = _run_wrapper(script, log, bin_dir)

    assert result.returncode != 0
    assert "172.27.0.99" not in result.stdout + result.stderr
    events = log.read_text(encoding="utf-8").splitlines()
    assert events == ["python scripts/prepare_traefik_ingress.py", "python -"]
    assert not (repo / "deployment" / "secrets").exists()


def test_wrapper_bash_syntax_and_safe_command_order():
    bash = _bash_executable()
    if not bash:
        pytest.skip("bash is unavailable")
    result = subprocess.run([bash, "-n", str(SCRIPT)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr

    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index("python3 scripts/prepare_traefik_ingress.py") < source.index('"${COMPOSE[@]}" config --quiet')
    assert source.index('"${COMPOSE[@]}" config --quiet') < source.index('"${COMPOSE[@]}" build app')
    assert source.index('"${COMPOSE[@]}" build app') < source.index('"${COMPOSE[@]}" up -d')
    assert "RAPPORT_AUDITOR_APP_MEMORY_LIMIT\": \"2g\"" in source
    assert "RAPPORT_AUDITOR_APP_CPU_LIMIT\": \"2.0\"" in source
    assert "exec -T app sh -c 'cat > /tmp/rapport-container-smoke.py && exec python /tmp/rapport-container-smoke.py'" in source
    assert " < scripts/container_smoke.py" in source
    assert '"${COMPOSE[@]}" cp scripts/container_smoke.py' not in source
    assert "docker compose config\n" not in source
    assert not any(token in source for token in ("down --volumes", "system prune", "volume prune"))


def test_standalone_release_gate_streams_smoke_into_readonly_container_tmpfs():
    bash = _bash_executable()
    if not bash:
        pytest.skip("bash is unavailable")
    release_script = REPO / "scripts" / "verify_release.sh"
    syntax = subprocess.run([bash, "-n", str(release_script)], text=True, capture_output=True, check=False)
    assert syntax.returncode == 0, syntax.stderr

    source = release_script.read_text(encoding="utf-8")
    stream_command = "exec -T app sh -c 'cat > /tmp/rapport-container-smoke.py && exec python /tmp/rapport-container-smoke.py'"
    assert stream_command in source
    assert "< scripts/container_smoke.py" in source
    assert '"${COMPOSE[@]}" cp scripts/container_smoke.py' not in source
    assert source.index("build app") < source.index(stream_command)
    assert source.index(stream_command) < source.index('"${COMPOSE[@]}" stop redis')
    assert source.index('"${COMPOSE[@]}" stop redis') < source.index("--expect-redis-outage")
