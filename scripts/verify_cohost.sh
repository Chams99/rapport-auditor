#!/usr/bin/env bash
set -Eeuo pipefail

fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ "$(uname -s)" == Linux ]] || fail "Run this verification on the Linux VPS."
command -v docker >/dev/null || fail "Docker CLI is unavailable."
command -v python3 >/dev/null || fail "python3 is unavailable."

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
suffix="$(python3 -c 'import secrets; print(secrets.token_hex(6))')"
tag="rapport-auditor-test-builder:$suffix"
network="rapport-auditor-test-$suffix"
redis_name="rapport-auditor-test-redis-$suffix"
test_name="rapport-auditor-test-runner-$suffix"
label="rapport-auditor.verification=$suffix"
iid_file="$(mktemp)"
network_created=0
redis_id=""
test_id=""

cleanup() {
  status=$?
  trap - EXIT
  [[ -z "$test_id" ]] || docker rm -f "$test_id" >/dev/null 2>&1 || true
  [[ -z "$redis_id" ]] || docker rm -f "$redis_id" >/dev/null 2>&1 || true
  [[ "$network_created" != 1 ]] || docker network rm "$network" >/dev/null 2>&1 || true
  rm -f -- "$iid_file"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' 'Building the cached Python 3.12.14 test environment from the reviewed Dockerfile.'
docker build --target wheel-builder --tag "$tag" --iidfile "$iid_file" -f deployment/Dockerfile .
builder_id="$(cat "$iid_file")"
[[ "$builder_id" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "Docker did not return a valid builder image ID."
printf 'verification_builder_image_id=%s\n' "$builder_id"

docker network create --driver bridge --internal --label "$label" "$network" >/dev/null
network_created=1
redis_id="$(docker create --name "$redis_name" --label "$label" --network "$network" \
  --network-alias redis --memory 128m --cpus 0.5 --pids-limit 64 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m --tmpfs /data:rw,noexec,nosuid,nodev,size=16m \
  redis:8.10.2-alpine@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0 \
  redis-server --save '' --appendonly no --maxmemory 64mb --maxmemory-policy noeviction)"
docker start "$redis_id" >/dev/null
ready=0
for _ in $(seq 1 30); do
  if [[ "$(docker exec "$redis_id" redis-cli ping 2>/dev/null || true)" == PONG ]]; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]] || fail "The disposable Redis test service did not become ready."

test_id="$(docker create --name "$test_name" --label "$label" --network "$network" \
  --user 65534:65534 --memory 2g --cpus 2 --pids-limit 64 --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 \
  --mount "type=bind,source=$ROOT,target=/workspace,readonly" --workdir /workspace \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env PYTHONPATH=/workspace/apps/api:/workspace/apps/web:/workspace/packages/core:/workspace/tests \
  --env RAPPORT_AUDITOR_TEST_REDIS_URL=redis://redis:6379/0 \
  "$builder_id" python -m pytest -p no:cacheprovider -q)"
start_status=0
docker start --attach "$test_id" || start_status=$?
[[ "$start_status" == 0 ]] || fail "Docker could not attach to the full pytest run."
pytest_status="$(docker inspect --format '{{.State.ExitCode}}' "$test_id")"
[[ "$pytest_status" =~ ^[0-9]+$ ]] || fail "Could not confirm the full pytest container exit status."
[[ "$pytest_status" == 0 ]] || fail "The full pytest suite failed (container exit code $pytest_status)."
printf '%s\n' 'Linux/Python 3.12.14 full pytest suite passed, including live Redis integration.'
