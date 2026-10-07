# Public deployment runbook

This runbook describes the standalone Caddy topology; it does not describe the separately deployed Traefik co-hosted instance. On 2026-10-07, that co-hosted instance passed a limited external synthetic HTTPS acceptance check, while host capacity, upstream/CDN configuration, infrastructure logging and retention, backup policy, and operational ownership remain unverified. See the [co-hosting runbook](COHOSTING.md) for the recorded results. For the shared portfolio VPS, do not start this standalone Caddy profile because it publishes ports 80 and 443.

The app is a public document-processing service when hosted: browser text and uploads travel to the service server over HTTPS and are processed there. The application is designed not to retain source text, but that does not control host memory, crash dumps, provider backups, proxy/server logs, or infrastructure telemetry. Before soliciting non-synthetic reports, the privacy notice must name the selected hosting arrangement and explain its verified retention practices.

The topology, proxy settings, and Caddy-specific acceptance steps below apply to the standalone `deployment/compose.yaml`. The optional shared-host profile is `deployment/compose.traefik.yaml`; its separate network, proxy-trust, host-capacity, and live Traefik checks are documented in `docs/COHOSTING.md`.

## Intended trust boundaries

```text
Public browser
    │ HTTPS :443 (HTTP :80 only for redirect / certificate challenge)
    ▼
Caddy edge ───── persistent certificate/config state; request log fields filtered
    │ private app network; fixed trusted peer 10.89.0.2
    ▼
Flask + Waitress ───── bounded request parsing and isolated analysis workers
    │ private data network only
    ▼
Redis ───── persistent AOF quota metadata only; no public port or draft content
```

Caddy should be the only service publishing host ports. The application must have no host-published port. Use separate internal networks so Caddy can reach the app but not Redis, and the app can reach Redis but has no general outbound route. Do not mount the Docker socket or user document directories into the app. Keep Redis and the app private to the Compose network.

## Configuration contract

Server mode must fail startup when required public-security configuration is absent or malformed. Use the exact environment names validated by `rapport_api`; this list describes the current contract and should be rechecked against code before release.

| Setting | Public deployment value |
| --- | --- |
| `RAPPORT_AUDITOR_MODE` | `server` |
| `RAPPORT_AUDITOR_SECRET_KEY` | At least 32 UTF-8 bytes, unique and generated for this deployment; provide through an approved secret mechanism. |
| `RAPPORT_AUDITOR_TRUSTED_HOSTS` | Comma-separated hostnames only, such as the chosen public domain; no scheme, path, or wildcard. |
| `RAPPORT_AUDITOR_TRUSTED_ORIGINS` | Exact HTTPS origins for the public site; no path or wildcard. |
| `RAPPORT_AUDITOR_REDIS_URL` | Private Redis address; credentials must not be committed or embedded in an image. |
| `RAPPORT_AUDITOR_TRUSTED_PROXY` | The exact Caddy peer IP `10.89.0.2` on the private app network; the current app accepts one exact IP, not a CIDR or wildcard. |
| `RAPPORT_AUDITOR_HOST` | `0.0.0.0` inside the isolated application container only. |
| `RAPPORT_AUDITOR_COOKIE_SECURE` | Forced on in server mode. |
| `RAPPORT_AUDITOR_THREADS` | Bounded positive integer sized for the deployment’s memory and worker model. |
| `RAPPORT_AUDITOR_RATE_LIMIT_MAX_REQUESTS` | Default `30`. |
| `RAPPORT_AUDITOR_RATE_LIMIT_WINDOW_SECONDS` | Default `60`. |
| `RAPPORT_AUDITOR_RATE_LIMIT_MAX_CLIENTS` | Default `4096`; capacity overflow fails closed. |
| `RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS` | Default `2`; hard upper bound on concurrent analysis subprocesses. |
| `RAPPORT_AUDITOR_ANALYSIS_TIMEOUT_SECONDS` | Default `10` seconds wall time. |
| `RAPPORT_AUDITOR_WORKER_MEMORY_MB` | Default `512` MB per worker on supported Linux hosts. |
| `RAPPORT_AUDITOR_WORKER_CPU_SECONDS` | Default `8` CPU seconds per worker on supported Linux hosts. |

Public limits must agree at every layer: Caddy request body, Waitress `max_request_body_size`, Flask `MAX_CONTENT_LENGTH` (1,100,000 bytes); app text (250,000 characters, 1,000,000 UTF-8 bytes, 10,000 lines); and file (1,000,000 bytes). The request must also fit multipart form overhead. Keep Waitress input spill above the whole body limit and output spill above the app’s 8,000,000-byte response cap; use a bounded temporary filesystem as a final containment layer, not as an alternate draft store.

The analysis process boundary should enforce the worker count, 10-second deadline, 8-CPU-second limit, and 512-MB Linux memory limit; kill and reap timed-out children. Saturation and infrastructure failures return a generic `503`; a worker deadline returns a generic `504`. No request body, filename, IP address, secret, query value, or traceback belongs in application logs. Correlation IDs may identify endpoint, status, and duration without linking back to submitted content.

## Host preparation and startup

1. Choose a supported Linux server and a public domain. Set DNS `A`/`AAAA` records to the host and allow inbound TCP 80 and 443. Caddy needs a writable persistent data directory to maintain certificates. Exact HTTPS setup depends on the selected hosting provider and its firewall/network rules.
2. Review the deployment files and replace all example domains, secrets, and network assumptions. Do not put real secrets in Git, Docker build arguments, image layers, screenshots, or shell history. The Compose secret is a host file mounted for the app's non-root UID `10001:10001`; protect the host path and set ownership/permissions so this UID can read it without broad host access. Validate file-backed secret behavior on the exact Compose version before use.
3. Confirm the service networks have the intended separation and fixed Caddy peer address. Verify with the rendered Compose configuration that only Caddy publishes ports, the app has no general outbound route, and Redis is only on the private app/Redis network. Redis uses the persistent `redis_rate_state` volume for short-lived quota metadata, not documents.
4. Build the application from the pinned Python dependency locks. Pin production base images to reviewed versions/digests and schedule controlled updates; a fixed digest needs a documented update process. Run the app non-root with a read-only root filesystem, dropped capabilities, `no-new-privileges`, bounded CPU/memory/process counts, and bounded `/tmp`.
5. Validate configuration before starting. The app should refuse server mode with a missing/short secret, empty host/origin allowlists, HTTP origin, absent Redis, wildcard proxy trust, or malformed numeric limits. Server mode forces the secure-cookie setting on; a local-only `RAPPORT_AUDITOR_COOKIE_SECURE=0` value is not used to weaken it.
6. Start Redis and verify its health, then start the app, then Caddy. Do not make the app or Redis reachable from the host or public network. Caddy should obtain and retain a valid certificate before announcing the URL.

Use only the actual Compose file and supported variables created in `deployment/`; the command shape is:

```sh
docker compose --env-file deployment/.env -f deployment/compose.yaml config
docker compose --env-file deployment/.env -f deployment/compose.yaml build
docker compose --env-file deployment/.env -f deployment/compose.yaml up -d
docker compose --env-file deployment/.env -f deployment/compose.yaml ps
```

These commands are a template, not a recorded deployment. Check that the Compose version, file-backed secret permissions, and service names match the implementation. Use a disposable dummy secret when validating or capturing Compose output; never print secret values or host secret paths into CI logs. The `--env-file` should be operator-managed and ignored by Git.

## Candidate-release gate

For a release candidate, run `scripts/verify_release.sh` from the application root on Linux with Python 3.12+, Docker Engine plus Compose v2, npm, and GNU `timeout`. The script creates disposable Python environments and a uniquely named Compose project, runs the locked test/dependency checks and real Redis integration tests, builds and smoke-tests the wheel, validates Compose/Caddy configuration, checks Caddy storage ownership and a no-network isolated Caddy runtime, and boots the private app/Redis stack to test readiness, native/API flows, Redis outage fail-closed behavior, and recovery. It runs only synthetic report text and cleans up its temporary services and volumes on exit.

After preparing the operator-managed `deployment/.env` and selecting an HTTPS staging origin, an operator explicitly opts into the external synthetic smoke with:

```sh
RAPPORT_AUDITOR_RELEASE_CONFIRM=RUN_SYNTHETIC_STAGING_ACCEPTANCE \
RAPPORT_AUDITOR_RELEASE_BASE_URL=https://staging.example.org \
scripts/verify_release.sh
```

Replace the example origin with the actual staging origin before running. The script fails early unless the explicit confirmation, staging URL, local Compose environment, and required tools are present. Never use a production URL for this test unless synthetic submissions are authorized there.

The script does not start the public Compose Caddy service, publish host ports, request a certificate, or perform ACME. It separately sends synthetic smoke traffic and runs the browser suite against the operator-selected HTTPS staging URL. The operator must ensure that URL serves the candidate revision and that its privacy, log-retention, provider, and external-monitoring behavior are acceptable; the script cannot establish those facts. Browser artifacts go to a temporary directory and are deleted at cleanup. A successful run is candidate-specific evidence, not a promise about arbitrary traffic or a substitute for an agreed service envelope and operational owner. This gate was not run in the recorded Windows environment because Docker/Linux/real Redis are unavailable here.

## Public acceptance checks

Run these against the exact candidate image, Caddy config, and Redis version on Linux before inviting public uploads:

- Start server mode with each required variable missing or invalid, one at a time; startup must fail with a concise configuration name and must not echo secret contents.
- From an outside client, confirm HTTPS certificate/hostname and HTTP→HTTPS behavior. A valid form receives a `Secure`, `HttpOnly`, `SameSite=Strict` CSRF cookie; cross-origin/opaque-origin posts, forged hosts, forged forwarding headers, and absent/invalid CSRF are rejected.
- Verify `/api/v1/health/live` stays generic and quick. Verify `/api/v1/health/ready` returns generic `503` if Redis or worker capacity is unavailable, then returns `200` after recovery. No dependency details should be exposed.
- Exercise supported UTF-8 `.txt` and `.tex`, BOM, malformed encoding, binary signatures, NUL, wrong extension/MIME, empty input, and exact size/line boundaries through the real Caddy→Waitress→Flask chain. Oversized submissions return `413`; they are rejected rather than truncated.
- Send simultaneous allowed and over-limit requests from one true client IP through Caddy; the shared Redis limiter must enforce the same window across multiple app instances and return `429` with `Retry-After`. Forged `X-Forwarded-For` from outside must not create a new identity. Redis outage and client-capacity exhaustion must fail closed with generic `503`.
- Saturate both worker slots, force a deterministic slow worker through a test-only harness (never a public route), and force one child failure. Confirm bounded worker count, timely `503`/`504`, child kill/reaping, recovery, and continued service health.
- Exercise maximum-size benign text, sentence-heavy adversarial text, repeated submissions, and concurrent uploads. Record p50/p95/p99 latency, CPU, memory, worker count, Redis key count, Caddy/Waitress buffering, and rejection behavior. Pick an expected public concurrency/service envelope before load testing; do not claim capacity from one local timing run.
- Stop Redis while an analysis request is active. Confirm no draft is logged or returned in an infrastructure error; restore Redis and confirm readiness and retry behavior recover.
- Confirm the application has no external writing/source lookup, no persistent draft volume, no worker temp files containing source, and no access/error log body, query-string, filename, or unredacted client-IP fields. The isolated app networks block general outbound access; Caddy needs outbound access for certificates. Keep Caddy certificate state separate from Redis quota state and application state.
- Run English and French browser checks, the explicit content-language selector, JavaScript-off form submissions, error retention, keyboard/focus flows, and the defined public privacy notice on the served HTTPS origin.

## Health and operations

`/api/v1/health/live` is a liveness check only. `/api/v1/health/ready` is the traffic-readiness check and should not expose Redis errors or internal worker details. Health checks do not replace external uptime monitoring, alerting, backups of Caddy certificate state, a patch schedule, or an abuse/incident contact.

Keep application logs structured and content-free. Configure container log rotation or a bounded external sink. The Caddy log encoder deletes the nested `request` object (which carries URI/query, request headers, and peer/client IP fields); verify adapted configuration and provider-level logs separately. Never log uploaded file names, text, findings, CSRF values, Redis URL, secret key, or worker tracebacks. Redis stores HMAC-derived pseudonymous client identifiers and rate-window timestamps with TTLs; a pseudonymous identifier is operational data and must be covered by a retention statement.

TTL means Redis no longer treats an expired key as live; it is not immediate physical deletion from the AOF or old volume backups. With `appendfsync everysec`, Redis documents that a crash may lose approximately the latest second of writes. Define access and retention for the volume/backups, monitor volume growth, schedule and inspect AOF rewrites, and document how to remove/replace the volume to reset quota history. The AOF contains Redis commands for quota state, not report content.

When Redis is unavailable, the service rejects analysis rather than bypassing the shared limiter. When worker capacity is exhausted, return a generic retryable response. For suspected abuse, first pause public analysis or remove the Caddy route; do not dump in-memory documents or logs for diagnosis. Rotate the server secret if exposed, rotate Redis credentials, invalidate active sessions/tokens, deploy a reviewed image, and confirm recovery through readiness and synthetic smoke requests.

## Current verification status

On 2026-10-06, this workstation had no Docker, Podman, Redis server, Docker-compatible Linux runtime, or local Redis listener. Windows Application Control blocked execution of the project-local Compose CLI, so the standalone Caddy Compose profile was not started here. An official Caddy 2.11.7 Windows binary was checksum-verified and used for offline `adapt --validate` with the synthetic `example.invalid` domain; it did not bind a listener or attempt ACME. That check covers Caddy syntax/config adaptation only.

The separate Traefik co-hosted profile was deployed and tested on 2026-10-07. At commit `30aa43e7d07552ee6a8cae109b255a7102c0ddb2`, the Linux gate passed **194 tests in 29.04 seconds with no skips** using Python 3.12.14 and an isolated disposable Redis. The public `https://rapport.chames.tn` route passed normal certificate validation and synthetic health, API, native-form, Origin/CSRF rejection, oversized-body, and forged-forwarding-header quota checks. A Windows Schannel request on the same date reported `SEC_E_UNTRUSTED_ROOT`; later normal external TLS validation succeeded, so the Windows result is recorded as client-specific rather than a universal certificate failure. Detailed results are in [TESTING.md](TESTING.md) and [COHOSTING.md](COHOSTING.md).

No production load/soak or host capacity result is claimed. Complete CDN/upstream trust, effective Traefik access logging and timeout behavior, backup and provider retention, privacy notice, operational owner, and incident contact remain unverified. The isolated Linux gate used a disposable Redis and did not outage-test the live app's Redis. The Linux suite and public synthetic checks do not establish privacy or capacity guarantees.

Flask recommends a production WSGI server rather than the development server and says limits must also be enforced by the WSGI server, proxy, container, and host ([production deployment](https://flask.palletsprojects.com/en/stable/deploying/), [resource use](https://flask.palletsprojects.com/en/stable/web-security/)). For the pinned Waitress 3.0.2 release, request size, input/output overflow, thread count, and explicitly trusted proxy headers are deployment arguments ([Waitress 3.0.2 arguments](https://docs.pylonsproject.org/projects/waitress/en/v3.0.2/arguments.html)). OWASP recommends allowlisted file types, server-side content checks, file-size limits, filename handling, and least privilege ([File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)); this service handles text only and never executes TeX. Redis documents why a counter and expiry need an atomic operation/script to avoid a race ([Redis `INCR`](https://redis.io/docs/latest/commands/incr/)). Caddy documents body caps and `413` behavior ([request body](https://caddyserver.com/docs/caddyfile/directives/request_body)), certificate prerequisites ([Automatic HTTPS](https://caddyserver.com/docs/automatic-https)), and proxy trusted-IP configuration ([global options](https://caddyserver.com/docs/caddyfile/options)). Docker recommends non-root users, digest-pinned images, resource controls, and secrets instead of environment values for sensitive settings ([build best practices](https://docs.docker.com/build/building/best-practices/), [resource constraints](https://docs.docker.com/engine/containers/resource_constraints/), [Compose environment guidance](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)).
