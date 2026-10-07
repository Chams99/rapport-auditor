#!/usr/bin/env bash
# Candidate-release acceptance gate. It does not start the public Compose Caddy
# service or publish ports. An isolated no-network Caddy runtime smoke is run;
# the operator must already have selected an HTTPS staging URL.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() { printf 'release gate: %s\n' "$1" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"; }

[[ "$(uname -s)" == Linux ]] || fail "run this gate on Linux; POSIX worker limits are required"
[[ "${RAPPORT_AUDITOR_RELEASE_CONFIRM:-}" == "RUN_SYNTHETIC_STAGING_ACCEPTANCE" ]] \
  || fail "set RAPPORT_AUDITOR_RELEASE_CONFIRM=RUN_SYNTHETIC_STAGING_ACCEPTANCE after selecting a staging target"
[[ -n "${RAPPORT_AUDITOR_RELEASE_BASE_URL:-}" ]] \
  || fail "set RAPPORT_AUDITOR_RELEASE_BASE_URL to the selected HTTPS staging origin"
[[ -f deployment/.env ]] || fail "create the operator-managed deployment/.env first"

PYTHON="${PYTHON:-python3.12}"
need "$PYTHON"
need docker
need npm
need timeout
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 12):
    raise SystemExit("release gate requires Python 3.12 or newer")
PY
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"

# One-off project name ensures the temporary app/Redis smoke stack gets its own
# quota volume and cannot collide with another Compose project.
PROJECT="rapport-auditor-verify-$("$PYTHON" -c 'import secrets; print(secrets.token_hex(5))')"
COMPOSE=(docker compose --project-name "$PROJECT" --env-file deployment/.env -f deployment/compose.yaml)
REDIS_NAME="$PROJECT-test-redis"
DEV_ROOT="$(mktemp -d)"
DEV_VENV="$DEV_ROOT/dev"
DEV_PY="$DEV_VENV/bin/python"
WHEEL_DIR=""
VENV_DIR=""
BROWSER_DIR=""
CADDY_SMOKEFILE=""
cleanup_redis() { docker stop "$REDIS_NAME" >/dev/null 2>&1 || true; }
cleanup() {
  cleanup_redis
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$DEV_ROOT"
  [[ -z "$WHEEL_DIR" ]] || rm -rf -- "$WHEEL_DIR"
  [[ -z "$VENV_DIR" ]] || rm -rf -- "$VENV_DIR"
  [[ -z "$BROWSER_DIR" ]] || rm -rf -- "$BROWSER_DIR"
  [[ -z "$CADDY_SMOKEFILE" ]] || rm -f -- "$CADDY_SMOKEFILE"
}
trap cleanup EXIT INT TERM

printf '%s\n' '[1/8] Python dependencies, lint, tests, and real Redis integration'
"$PYTHON" -m venv "$DEV_VENV"
"$DEV_PY" -m pip install -r requirements-dev.lock
"$DEV_PY" -m pip install setuptools==84.0.0
"$DEV_PY" -m pip install --no-deps --no-build-isolation .
"$DEV_PY" -m pip check
"$DEV_PY" -m pip_audit -r requirements-runtime.lock
"$DEV_PY" -m pip_audit -r requirements-dev.lock
"$DEV_PY" -m ruff check .

REDIS_IMAGE="redis:8.10.2-alpine@sha256:3811787313eba226a2ef38658c6ccb91cd5e110edc89c37767de373120a0e5a0"
REDIS_PORT="$("$PYTHON" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
docker run --detach --rm --name "$REDIS_NAME" \
  --publish "127.0.0.1:$REDIS_PORT:6379" \
  "$REDIS_IMAGE" redis-server --save '' --appendonly no >/dev/null
ready=0
for _ in $(seq 1 40); do
  if docker exec "$REDIS_NAME" redis-cli ping 2>/dev/null | grep -qx PONG; then ready=1; break; fi
  sleep 0.25
done
[[ "$ready" == 1 ]] || fail "disposable Redis did not become ready"
RAPPORT_AUDITOR_TEST_REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0" \
  "$DEV_PY" -m pytest -q tests/test_redis_integration.py
RAPPORT_AUDITOR_TEST_REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0" \
  "$DEV_PY" -m pytest -q

printf '%s\n' '[2/8] Browser dependency audit and production wheel smoke'
npm ci --prefix scripts --ignore-scripts
npm audit --prefix scripts
 BROWSER_DIR="$(mktemp -d)"
PLAYWRIGHT_BROWSERS_PATH="$BROWSER_DIR" npm run --prefix scripts install:browsers
WHEEL_DIR="$(mktemp -d)"
VENV_DIR="$(mktemp -d)"
"$DEV_PY" -m pip wheel --no-deps --no-build-isolation --wheel-dir "$WHEEL_DIR" .
"$PYTHON" -m venv "$VENV_DIR/runtime"
RUNTIME_PY="$VENV_DIR/runtime/bin/python"
"$RUNTIME_PY" -m pip install -r requirements-runtime.lock
"$RUNTIME_PY" -m pip install --no-deps "$WHEEL_DIR"/*.whl
"$RUNTIME_PY" - <<'PY'
from importlib.resources import files
from rapport_api import create_app

app = create_app({"TESTING": True, "SECRET_KEY": "wheel-smoke-secret-key-0123456789"})
client = app.test_client()
assert client.get("/").status_code == 200
assert files("rapport_web").joinpath("static/style.css").is_file()
assert files("rapport_web").joinpath("static/app.js").is_file()
print("installed wheel and packaged web assets passed")
PY

printf '%s\n' '[3/8] Compose model and Caddy configuration validation'
"${COMPOSE[@]}" config --quiet
CADDY_IMAGE="caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f"
"${COMPOSE[@]}" run --rm --no-deps caddy-storage-init
"${COMPOSE[@]}" run --rm --no-deps --entrypoint sh caddy \
  -c 'test -w /data && test -w /config'
"${COMPOSE[@]}" run --rm --no-deps --entrypoint caddy caddy \
  validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null
CADDY_SMOKEFILE="$(mktemp)"
cat >"$CADDY_SMOKEFILE" <<'CADDY'
http://example.invalid:18080 {
  respond "ok" 200
}
CADDY
set +e
timeout --signal=TERM --kill-after=2s 3s docker run --rm --network none \
  --user 1000:1000 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777 \
  --tmpfs /data:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --tmpfs /config:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --volume "$CADDY_SMOKEFILE:/etc/caddy/Caddyfile:ro" \
  "$CADDY_IMAGE" run --config /etc/caddy/Caddyfile >/dev/null 2>&1
caddy_smoke_status=$?
set -e
[[ "$caddy_smoke_status" == 124 ]] || fail "isolated Caddy runtime smoke did not stay running until its timeout"

printf '%s\n' '[4/8] Build the exact app image and run its private Redis-backed smoke'
"${COMPOSE[@]}" build app
"${COMPOSE[@]}" up -d redis app
healthy=0
for _ in $(seq 1 100); do
  if "${COMPOSE[@]}" exec -T app python -c \
    'import os,urllib.request; h=os.environ["RAPPORT_AUDITOR_TRUSTED_HOSTS"].split(",")[0].strip(); r=urllib.request.Request("http://127.0.0.1:5000/api/v1/health/ready",headers={"Host":h}); urllib.request.urlopen(r,timeout=2).read()' \
    >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done
[[ "$healthy" == 1 ]] || { "${COMPOSE[@]}" logs --no-color app redis >&2; fail "private app/Redis stack did not become healthy"; }
"${COMPOSE[@]}" cp scripts/container_smoke.py app:/tmp/rapport-container-smoke.py
"${COMPOSE[@]}" exec -T app python /tmp/rapport-container-smoke.py
"${COMPOSE[@]}" stop redis
"${COMPOSE[@]}" exec -T app python /tmp/rapport-container-smoke.py --expect-redis-outage
"${COMPOSE[@]}" up -d redis
healthy=0
for _ in $(seq 1 40); do
  if "${COMPOSE[@]}" exec -T app python -c \
    'import os,urllib.request; h=os.environ["RAPPORT_AUDITOR_TRUSTED_HOSTS"].split(",")[0].strip(); r=urllib.request.Request("http://127.0.0.1:5000/api/v1/health/ready",headers={"Host":h}); urllib.request.urlopen(r,timeout=2).read()' \
    >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done
[[ "$healthy" == 1 ]] || fail "app did not recover after Redis returned"

printf '%s\n' '[5/8] Synthetic HTTPS smoke against the selected staging URL'
export RAPPORT_AUDITOR_LOG_CANARY="release-check-$("$PYTHON" -c 'import secrets; print(secrets.token_hex(8))')"
"$PYTHON" scripts/release_http_smoke.py

printf '%s\n' '[6/8] Browser and accessibility smoke against the selected HTTPS origin'
export RAPPORT_AUDITOR_BASE_URL="$RAPPORT_AUDITOR_RELEASE_BASE_URL"
export RAPPORT_AUDITOR_BROWSER_ARTIFACT_DIR="$BROWSER_DIR/artifacts"
mkdir -p -- "$RAPPORT_AUDITOR_BROWSER_ARTIFACT_DIR"
PLAYWRIGHT_BROWSERS_PATH="$BROWSER_DIR" npm run --prefix scripts test:browser

printf '%s\n' '[7/8] Confirm stack cleanup'
cleanup_redis
"${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null

printf '%s\n' '[8/8] Candidate gate complete; retain logs and build provenance without retaining any synthetic document text.'
