from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_cohost.sh"


def _bash() -> str | None:
    if os.name == "nt":
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


def test_linux_cohost_gate_has_valid_bash_syntax():
    bash = _bash()
    if not bash:
        pytest.skip("bash is unavailable")
    result = subprocess.run([bash, "-n", str(SCRIPT)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_linux_cohost_gate_isolated_bounded_and_cleans_only_owned_resources():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--target wheel-builder" in source and "--iidfile \"$iid_file\"" in source
    assert 'docker network create --driver bridge --internal --label "$label" "$network"' in source
    assert "redis:8.10.2-alpine@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0" in source
    assert '--memory 128m --cpus 0.5 --pids-limit 64 --read-only' in source
    assert '--user 65534:65534 --memory 2g --cpus 2 --pids-limit 64 --read-only --cap-drop ALL' in source
    assert "--tmpfs /tmp:rw,exec,nosuid,nodev,size=128m,mode=1777" in source
    assert '--mount "type=bind,source=$ROOT,target=/workspace,readonly"' in source
    assert "RAPPORT_AUDITOR_TEST_REDIS_URL=redis://redis:6379/0" in source
    assert 'docker inspect --format \'{{.State.Running}} {{.State.ExitCode}}\' "$test_id"' in source
    assert '[[ "$pytest_status" == 0 ]]' in source
    assert 'docker rm -f "$test_id"' in source
    assert 'docker rm -f "$redis_id"' in source
    assert 'docker network rm "$network"' in source
    for forbidden in ("docker compose", "docker volume", "docker image rm", "system prune", "caddy"):
        assert forbidden not in source


@pytest.mark.skipif(os.name == "nt", reason="The Docker CLI mock exercises Linux Bash and trap cleanup semantics.")
@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [("", 0), ("redis", 1), ("pytest", 1), ("pytest_cli", 1), ("running", 1)],
)
def test_linux_cohost_gate_cleans_only_created_resources_on_exit(tmp_path: Path, failure: str, expected_status: int):
    bash = _bash()
    if not bash:
        pytest.skip("bash is unavailable")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
if [ "$1" = build ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --iidfile ]; then shift; printf 'sha256:%064d\\n' 1 > "$1"; fi
    shift
  done
elif [ "$1" = network ] && [ "$2" = create ]; then
  printf 'network-id\\n'
elif [ "$1" = create ]; then
  case "$*" in *redis-server*) printf 'a%.0s' $(seq 1 64);; *) printf 'b%.0s' $(seq 1 64);; esac
  printf '\\n'
elif [ "$1" = exec ]; then
  [ "$DOCKER_FAILURE" = redis ] || printf 'PONG\\n'
elif [ "$1" = start ] && [ "$2" = --attach ] && [ "$DOCKER_FAILURE" = pytest_cli ]; then
  exit 42
elif [ "$1" = inspect ]; then
  case "$DOCKER_FAILURE" in
    pytest|pytest_cli) printf 'false 42\\n' ;;
    running) printf 'true 0\\n' ;;
    *) printf 'false 0\\n' ;;
  esac
fi
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    log = tmp_path / "docker.log"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "DOCKER_LOG": str(log),
            "DOCKER_FAILURE": failure,
        }
    )

    result = subprocess.run([bash, str(SCRIPT)], text=True, capture_output=True, env=env, timeout=60)

    assert result.returncode == expected_status, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any(call.startswith("network create ") for call in calls)
    assert any(call.startswith("rm -f a") for call in calls)
    assert any(call.startswith("network rm rapport-auditor-test-") for call in calls)
    assert not any(call.startswith("compose ") or call.startswith("volume ") or call.startswith("image rm") for call in calls)
    if failure in {"pytest", "pytest_cli"}:
        assert any(call.startswith("inspect --format {{.State.Running}} {{.State.ExitCode}}") for call in calls)
        assert "full pytest suite passed" not in result.stdout
        assert "container exit code 42" in result.stderr
    if failure == "pytest_cli":
        assert "Docker could not attach" not in result.stderr
    if failure == "running":
        assert "still running" in result.stderr
        assert "full pytest suite passed" not in result.stdout
    if failure == "redis":
        assert not any(call.startswith("create ") and "pytest" in call for call in calls)
        assert not any(call.startswith("rm -f b") for call in calls)
    else:
        assert any(call.startswith("rm -f b") for call in calls)
