#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() {
  printf '%s\n' "$1" >&2
  exit 1
}

ENV_FILE=deployment/.env.traefik
ENV_EXAMPLE=deployment/.env.traefik.example
SECRET_DIR=deployment/secrets
SECRET_FILE="$SECRET_DIR/rapport_secret_key"
COMPOSE=(docker compose --project-name rapport-auditor-traefik --env-file "$ENV_FILE" -f deployment/compose.traefik.yaml)

python3 scripts/prepare_traefik_ingress.py

if [ -L "$ENV_FILE" ]; then
  die "Refusing a symlinked deployment/.env.traefik."
elif [ ! -e "$ENV_FILE" ]; then
  (umask 077; set -C; cat "$ENV_EXAMPLE" > "$ENV_FILE")
elif [ ! -f "$ENV_FILE" ]; then
  die "deployment/.env.traefik exists but is not a regular file."
fi
chmod 0600 "$ENV_FILE"

python3 - "$ENV_FILE" <<'PY'
import sys
from pathlib import Path
values = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        key, sep, value = line.partition("=")
        if not sep or key.strip() in values:
            raise SystemExit("Private Rapport env file is malformed or has duplicate keys.")
        values[key.strip()] = value.strip().strip("\"'")
expected = {
    "RAPPORT_AUDITOR_PUBLIC_DOMAIN": "rapport.chames.tn",
    "RAPPORT_AUDITOR_INGRESS_NETWORK": "rapport-auditor-ingress",
    "RAPPORT_AUDITOR_TRUSTED_PROXY": "172.27.0.2",
    "RAPPORT_AUDITOR_SECRET_FILE": "./secrets/rapport_secret_key",
    "RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS": "2",
    "RAPPORT_AUDITOR_APP_MEMORY_LIMIT": "2g",
    "RAPPORT_AUDITOR_APP_CPU_LIMIT": "2.0",
}
if any(values.get(key) != value for key, value in expected.items()):
    raise SystemExit("Private env does not match the reviewed co-hosting profile; edit it locally and rerun.")
PY

if [ -L "$SECRET_DIR" ]; then
  die "Refusing a symlinked deployment/secrets directory."
elif [ ! -e "$SECRET_DIR" ]; then
  install -d -m 0700 "$SECRET_DIR"
elif [ ! -d "$SECRET_DIR" ]; then
  die "deployment/secrets exists but is not a directory."
fi
chmod 0700 "$SECRET_DIR"

if [ -L "$SECRET_FILE" ]; then
  die "Refusing a symlinked Rapport secret."
elif [ ! -e "$SECRET_FILE" ]; then
  (umask 077; set -C; python3 -c 'import secrets,sys; sys.stdout.write(secrets.token_hex(32))' > "$SECRET_FILE")
elif [ ! -f "$SECRET_FILE" ]; then
  die "The Rapport secret path exists but is not a regular file."
fi
sudo chown 10001:10001 "$SECRET_FILE"
sudo chmod 0400 "$SECRET_FILE"
sudo python3 -c 'from pathlib import Path; import sys; s=Path(sys.argv[1]).read_text(encoding="utf-8").strip(); sys.exit(0 if len(s.encode()) >= 32 else "Rapport secret is too short.")' "$SECRET_FILE"

# Keep Compose interpolation bound to the validated private file, not shell exports.
unset RAPPORT_AUDITOR_PUBLIC_DOMAIN RAPPORT_AUDITOR_INGRESS_NETWORK \
  RAPPORT_AUDITOR_TRUSTED_PROXY RAPPORT_AUDITOR_SECRET_FILE \
  RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS RAPPORT_AUDITOR_APP_MEMORY_LIMIT \
  RAPPORT_AUDITOR_APP_CPU_LIMIT
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build app
"${COMPOSE[@]}" up -d
"${COMPOSE[@]}" ps

APP_ID="$("${COMPOSE[@]}" ps -q app)"
[ -n "$APP_ID" ] || die "The Rapport app container was not created."
health=starting
for attempt in {1..20}; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$APP_ID")"
  [ "$health" = healthy ] && break
  [ "$health" != unhealthy ] || die "The Rapport app health check failed."
  sleep 2
done
[ "$health" = healthy ] || die "The Rapport app did not become healthy within 40 seconds."

"${COMPOSE[@]}" exec -T app sh -c 'cat > /tmp/rapport-container-smoke.py && exec python /tmp/rapport-container-smoke.py' \
  < scripts/container_smoke.py
RAPPORT_AUDITOR_RELEASE_BASE_URL=https://rapport.chames.tn \
RAPPORT_AUDITOR_LOG_CANARY="rapport-smoke-$(date +%s)-$$" \
  python3 scripts/release_http_smoke.py

printf '%s\n' "Rapport container and synthetic HTTPS smokes passed. Public quota, invalid-origin, log-retention, maximum-body concurrency, and capacity signoff remains outstanding."
