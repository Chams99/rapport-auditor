# Security and privacy

Rapport Auditor has two run profiles. **Local mode** is a personal writing aid that binds to loopback by default. **Server mode** is an anonymous document-processing service: when someone hosts it, pasted text and uploaded files are transmitted to that server over HTTPS. A co-hosted instance at `https://rapport.chames.tn` was reachable and passed limited synthetic route checks on 2026-10-07. The route was associated with the VPS the user identified as OVH, but account-level provider configuration, upstream/CDN presence, log and backup retention, and an operational privacy notice have not been verified. The test results are not a security certification or a guarantee about hosting infrastructure.

These controls describe application behavior. They do not make a browser, host operating system, container runtime, or hosting provider a secure document vault, and they are not a security certification.

## Document handling

- The application passes the submitted text through deterministic analysis/revision code. It does not call an external writing, AI, plagiarism, citation, URL, DOI, or fact-checking service. It does not execute TeX, compile documents, follow `\\input`, or resolve bibliography keys.
- The web request parser uses bounded `BytesIO` streams. Server mode places analysis in a spawned child process; only an operation name, shared-memory name/length, and numeric limits are passed in the process arguments. The parent unlinks the shared-memory block in its `finally` cleanup. Results return through size-bounded JSON frames. This is transient processing, not secure erasure: the operating system can page memory, retain crash dumps, or expose process memory to privileged software.
- The app has no draft database or draft volume. A public host can still retain data outside the application's control through memory/swap, crash dumps, snapshots/backups, support diagnostics, proxy logs, and infrastructure telemetry. Before soliciting non-synthetic reports, publish a privacy notice for the actual provider and retention configuration.
- The browser holds the text while the page is open. Device swap/hibernation, clipboard history, browser extensions, malware, backups, and other software running as the same user are outside the app's control.

## Local profile

The local CLI binds to `127.0.0.1` by default and creates a random signing secret when none is configured. It uses a bounded in-memory, per-process rolling-window limiter; restart clears this local throttle. Do not change `RAPPORT_AUDITOR_HOST` from loopback unless the server profile and the entire exposure boundary have been deliberately configured. The unauthenticated local app is not intended for a shared network.

The local request parser accepts UTF-8 `.txt` and `.tex` only. It rejects invalid encodings, binary signatures, NUL and unsupported control characters, mismatched extensions/MIME types, and requests exceeding configured character, byte, line, upload, or whole-body limits. Oversized input is rejected, not silently truncated.

## Public server profile

Server mode fails closed unless it has an explicit secret of at least 32 UTF-8 bytes, exact trusted hosts, exact HTTPS origins, Redis, one exact trusted proxy IP, POSIX resource-limit support, and bounded numeric settings. The provided Compose topology is intended to expose only Caddy on ports 80/443; app and Redis have no host-published ports. Caddy is the only path to the app. Do not run the public profile on Windows or use Flask's development server.

The co-hosted profile in `deployment/compose.traefik.yaml` reuses an existing Traefik instance and does not start Caddy or publish app/Redis ports. It attaches to a dedicated internal ingress network shared only with Traefik; the network must remain present and Traefik's fixed address on it must survive container recreation. `RAPPORT_AUDITOR_TRUSTED_PROXY` must match that exact address. Waitress honors `X-Forwarded-For` and `X-Forwarded-Proto` only when the connecting peer matches it. If the peer does not match, Waitress clears those headers; public write requests then fail the server-mode HTTPS/origin checks with `403`, while safe `GET` requests, including `/api/v1/health/ready`, may still return `200`. The limiter will see the proxy socket address when `X-Forwarded-For` is cleared, so clients share one quota. Readiness alone does not verify proxy trust or client-IP handling. The initial public route test on 2026-10-07 verified a synthetic write and a same-client forged-`X-Forwarded-For` quota control. After every Traefik recreation, recheck the network's `Internal` flag and Traefik membership/address without printing environment or secret values, then repeat a synthetic public HTTPS write and quota control. If a CDN or other load balancer precedes Traefik, configure Traefik to trust forwarded headers only from that provider's documented IP ranges and verify the full forwarding chain; never enable insecure forwarded-header trust.

The intended app boundary enforces:

- exact Host and same-origin/HTTPS checks; no acceptance of opaque `Origin: null`;
- signed CSRF form/header token plus matching `HttpOnly; SameSite=Strict; Secure` cookie;
- trusted forwarding from the exact proxy peer only; untrusted forwarding headers do not set the quota identity;
- Redis atomic shared rolling-window limits, with HMAC-derived client identities, bounded active-client cardinality, short key expiries, and fail-closed `503` if Redis is unavailable or its active-client cap is full;
- at most two analysis children by default, a 10-second wall deadline, 8 CPU seconds and 512 MB address-space per worker on supported Linux hosts, child kill/reaping, and generic `503`/`504` on capacity/failure/timeout;
- input byte/character/line limits, bounded in-memory upload parsing, capped findings/citations/revisions/diffs, response-byte cap, and separate Caddy/Waitress request body limits;
- no draft body, upload name, source, URL query, IP, secret, CSRF token, or traceback in application log records. App logs contain a random request ID, endpoint, method, status, duration, and exception type for failures. The Caddy config deletes its nested request log object and IP fields.

The public Compose configuration enables Redis AOF persistence on a named volume. Redis contains rate-limit timestamps and HMAC-derived client identifiers, not report text. TTL governs logical key expiry; it does not guarantee immediate erasure of previous commands from the AOF file or old volume backups. `appendfsync everysec` can lose recent writes after a crash (Redis documents up to roughly the latest second). Operators must secure and retain the Redis volume/backups appropriately, monitor size, and define AOF rewrite and volume-reset procedures. Deleting/replacing the volume clears the limiter history but also removes the recorded quota state. The Redis container is isolated on a private app network; its current local Compose URL is unencrypted `redis://` inside that boundary. A remote Redis service needs an explicitly reviewed private network, authentication, and TLS configuration.

The application itself does not store documents. A public hosting provider may still have different logging, backup, memory, swap, and support retention. Explain that boundary in the public privacy notice rather than promising absolute deletion.

## API and content limits

POST API input requires a JSON object with string `text`, optional `source_format` (`txt`/`tex`), and optional `content_language` (`en`/`fr`). Unknown fields and implicit type coercion are rejected. Current defaults: 250,000 Unicode code points, 1,000,000 UTF-8 bytes, 10,000 lines, 1,000,000 file bytes, and 1,100,000 request bytes. The output caps are documented in [the API guide](API.md). `audit` has no dedicated full-source field but may return bounded sentence/citation excerpts as review evidence; `revise` returns the revised text by design. Error responses are generic and localized.

Analysis results are editing prompts, not verified claims. Visible citation keys and URLs are not resolved or fetched. No authorship, plagiarism, academic-integrity, truth, citation relevance, or factual support is determined. See [language cue evaluation](EVALUATION.md) for what the small synthetic conformance suite does—and does not—establish.

## Verification and references

Run focused tests with:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_api.py tests\test_security.py tests\test_security_unit.py tests\test_public_profile.py tests\test_uploads.py tests\test_cli.py tests\test_worker_boundaries.py
```

Ordinary unit runs use Redis mocks and test HTTP policy through Flask's test client. Separately, the Linux co-host gate passed 194 tests with a disposable live Redis and Linux resource limits on 2026-10-07; that does not test the live app's Redis outage behavior or production capacity. External synthetic checks on the deployed route tested TLS, health, form/API behavior, Origin/CSRF rejection, body-size rejection, and quota behavior when a client varied forged `X-Forwarded-For` values. They are not a penetration test, complete upstream/CDN-chain review, access-log or retention audit, load test, or guarantee about hosting infrastructure. See the [test record](TESTING.md), [co-hosting runbook](COHOSTING.md), and [production runbook](PRODUCTION.md) for scope and remaining checks.

The design follows the intent of the [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) and [Denial of Service Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html): allowlist formats, validate content, cap request sizes and avoid input-controlled unbounded resource use. Flask recommends a production WSGI server and limits across the proxy/server/application/host ([deployment](https://flask.palletsprojects.com/en/stable/deploying/), [web security](https://flask.palletsprojects.com/en/stable/web-security/)); the service uses Waitress and configures its body/buffer controls ([Waitress 3.0.2 arguments](https://docs.pylonsproject.org/projects/waitress/en/v3.0.2/arguments.html)). The Redis limiter uses an atomic Lua operation rather than a split counter/expiry sequence ([Redis `INCR`](https://redis.io/docs/latest/commands/incr/)); persistence semantics are documented in [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/). Caddy's configurable field filtering is documented in its [log directive](https://caddyserver.com/docs/caddyfile/directives/log). Docker Compose's file-backed secrets use a per-service mounted file ([Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)); configure host-side secret file ownership and permissions for the non-root app UID as described by the runbook.
