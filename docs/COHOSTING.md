# Co-hosting on the portfolio VPS

This runbook is for the separate Rapport Auditor project on the VPS that serves the portfolio. It does not change the portfolio Compose project. The dedicated profile is `deployment/compose.traefik.yaml`, with its operator-managed settings in `deployment/.env.traefik` copied from `deployment/.env.traefik.example`. Its Compose project is `rapport-auditor-traefik`.

## What is known

The portfolio repository routes its blue and green containers through an external Docker network named `traefik`; its labels use the `websecure` entrypoint and certificate resolver `myresolver`. The portfolio containers do not publish host ports. A read-only VPS inventory on 2026-10-07 identified Traefik 3.6.8 (`traefik:latest`, repo digest `sha256:90099f8948c828ecf0ababd711a4359a2443eba12261c1df2f548a3b1d815938`), its owner Compose file at `/home/ubuntu/traefik/docker-compose.yml`, and its current address `172.18.0.3` on `traefik` (`172.18.0.0/16`). The inspected provider uses `traefik` as its default Docker network, disables automatic exposure, watches `/dynamic`, redirects `web` to HTTPS `websecure`, and uses the `myresolver` TLS challenge. The preflight did not inspect dynamic-file contents, global access-log settings, timeouts, or provider/CDN retention. The ingress preparation helper rechecks the owner stack and declines to proceed if a static config or `websecure` entrypoint middleware needs manual review. This profile's route labels were reviewed against Traefik 3.6.8; compatibility with other unverified versions is not claimed.

The chosen Rapport hostname is `rapport.chames.tn`. On 2026-10-07, its A record resolved to the same IPv4 address as `chames.tn` and the supplied OVH VPS hostname; it had no AAAA answer. That is consistent with direct DNS to the VPS, but it does not rule out a CDN or another upstream proxy. A normal certificate-validating HTTPS GET from the workstation failed before an HTTP response because Windows Schannel reported `SEC_E_UNTRUSTED_ROOT`. This is not proof that other clients reject the certificate. The live route, certificate chain, forwarded-header trust, access logs, upstream proxies, and provider retention remain unverified. Do not announce public availability until the operator checks them on the VPS and from a normal external client.

## Why this profile uses its own Redis

Another Redis container on the same VPS is not inherently a problem. This profile gives Rapport its own Redis container, private app-to-Redis network, and persistent quota-only volume. Redis is not published on a host port and does not share state with the portfolio. The profile's Redis cap is 256 MiB and 0.5 CPU; host headroom still matters. Reusing an unknown Redis would couple version, authentication, ACL, capacity, maintenance, and rate-limit state, so it is not the selected setup. Redis holds rate-limit metadata, not uploaded report text.

## Read-only VPS inventory

Use the existing login in a terminal the operator controls. These commands report only container status, image, port, network, and resource fields; they do not print container environment variables or rendered Compose configuration.

~~~sh
ssh my-vps

# Identify running services and host-published ports.
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

# Confirm the portfolio's external network and attached addresses.
docker network inspect traefik --format 'name={{.Name}} driver={{.Driver}} internal={{.Internal}}{{range .IPAM.Config}} subnet={{.Subnet}} gateway={{.Gateway}}{{end}}'
docker network inspect traefik --format '{{range .Containers}}{{println .Name .IPv4Address}}{{end}}'

# Set this to the exact Traefik container name shown by docker ps.
TRAEFIK_CONTAINER=replace-with-traefik-container-name
docker inspect --format 'name={{.Name}} image={{.Config.Image}} state={{.State.Status}} ports={{json .NetworkSettings.Ports}} networks={{range $name,$net := .NetworkSettings.Networks}}{{$name}}={{$net.IPAddress}} {{end}} memory_bytes={{.HostConfig.Memory}} cpu_quota={{.HostConfig.CpuQuota}} cpu_period={{.HostConfig.CpuPeriod}}' "$TRAEFIK_CONTAINER"
docker exec "$TRAEFIK_CONTAINER" traefik version

# Host capacity and Docker disk location/free space.
free -h
nproc
uptime
DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}')
df -h "$DOCKER_ROOT"

# Current usage and configured limits for running containers, without env or labels.
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}'
for id in $(docker ps -q); do
  docker inspect --format 'name={{.Name}} state={{.State.Status}} memory_bytes={{.HostConfig.Memory}} nano_cpus={{.HostConfig.NanoCpus}} cpu_quota={{.HostConfig.CpuQuota}} cpu_period={{.HostConfig.CpuPeriod}} pids_limit={{.HostConfig.PidsLimit}}' "$id"
done
~~~

Inspect the actual Traefik owner configuration through its existing review process to confirm the router entrypoint, `myresolver`, forwarded-header trust, access-log fields and retention, body handling, and request/response timeouts. Rapport's router intentionally does not depend on the unverified shared `default-chain@file`; the app supplies its own security headers, CSRF, origin, and host checks. Its router disables route access logs, tracing, and metrics, and uses only its own in-flight and request-cap middlewares. EntryPoint middleware runs before router middleware, so verify the `websecure` entrypoint has no authentication/IP gate, conflicting security headers, or stricter body limit. Also confirm whether entrypoint-level logging or observability settings affect this route. The Traefik profile replaces Caddy, so Caddy's standalone body, timeout, health-check, and log-filter settings do not apply. The profile supplies a 1,100,000-byte body cap with an equal in-memory threshold and an app readiness check; global Traefik timeout and logging behavior still need live verification. Do not paste unfiltered `docker inspect`, `docker compose config`, or secret-bearing configuration into logs or messages. If a CDN/upstream proxy exists, configure Traefik to trust only that provider's documented `trustedIPs`; never enable insecure forwarded headers. If there is no upstream proxy, verify that direct clients cannot spoof the address used by Rapport's limiter.

## Required ingress and capacity setup

Keep Traefik on its current public `traefik` network. The 2026-10-07 inventory showed Docker networks/routes using `172.17.0.0/16` through `172.26.0.0/16`; `172.27.0.0/24` is the candidate based on that snapshot, subject to the helper's live overlap checks against Docker networks and host routes. Docker rejects network creation that overlaps an existing Docker subnet. The reviewed `scripts/prepare_traefik_ingress.py` adds a separate persistent `rapport-auditor-ingress` bridge with `internal: true` and Traefik fixed at `172.27.0.2`, outside the dynamic allocation range `172.27.0.128/25`. It writes only an additive `/home/ubuntu/traefik/docker-compose.override.yml`, pins the already-running Traefik digest for its next Compose recreation, creates the internal network if needed, and connects the existing Traefik container without restarting it. It aborts on mismatched owner files/configuration or unexpected network state. The Rapport app is the only other member of this network; Redis stays on the separate internal Redis network. The Rapport container's `traefik.docker.network` label selects `rapport-auditor-ingress` for this router; the global `providers.docker.network=traefik` setting remains unchanged for existing apps. Set `RAPPORT_AUDITOR_TRUSTED_PROXY=172.27.0.2`, exactly matching the fixed Traefik address. Future Traefik Compose operations must retain the override: default file discovery auto-loads it, while commands that explicitly pass `-f docker-compose.yml` must also pass `-f docker-compose.override.yml`. Do not replace this with a one-time network attachment.

Waitress honors forwarded-for/protocol headers only from the exact configured peer and uses one trusted proxy hop. Verify the fixed address reported for the live Traefik container on `rapport-auditor-ingress` and compare it exactly with `RAPPORT_AUDITOR_TRUSTED_PROXY` before the first start and after every Traefik recreation; do this without printing the environment file. If the peer is wrong, Waitress strips those headers: HTTPS write requests can return 403 `origin_rejected`, while safe GET, CSRF bootstrap, and readiness requests may still return 200 and the limiter can collapse all clients to the proxy/socket identity. A successful health GET alone does not validate forwarded-proxy trust.

After the operator-owned Traefik stack creates this network, inspect only its network fields and members:

~~~sh
docker network inspect rapport-auditor-ingress --format 'name={{.Name}} driver={{.Driver}} internal={{.Internal}}{{range .IPAM.Config}} subnet={{.Subnet}} gateway={{.Gateway}}{{end}}'
docker network inspect rapport-auditor-ingress --format '{{range .Containers}}{{println .Name .IPv4Address}}{{end}}'
~~~

The 2026-10-07 inventory reported 4 CPUs, 7.6 GiB RAM, 4.0 GiB MemAvailable in an earlier snapshot, and about 1,377 MiB across 32 containers in a later `docker stats` sample. Several services had no configured cgroup memory limit. The Docker root filesystem had 8.5 GB free (89% used). These are point-in-time measurements, not peak or load-test results. The initial bounded envelope in `deployment/.env.traefik.example` is 2 GiB/2 CPU for the app and 256 MiB/0.5 CPU for its dedicated Redis, with two analysis workers. This is a starting configuration based on the observed snapshot, not a capacity guarantee. Each worker has a 512 MiB address-space cap and 8 CPU seconds with a 10-second wall deadline; address-space limits are not a resident-memory guarantee. `RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS` is tunable, defaulting to 2. Before start, recheck current free memory and disk, container usage and configured limits, and establish a host safety reserve. Count all other container limits, including both portfolio blue/green instances during a rollout (each 256 MiB and 0.25 CPU), Traefik, and host services. After start, check memory/CPU and disk under representative activity; run a synthetic maximum-body/two-worker check before treating the envelope as validated. Ensure free Docker disk can hold the candidate image, prior image for rollback, bounded logs, and Redis AOF volume. Stop if current inventory leaves inadequate reserve.

Before routing public traffic, confirm all of the following in the live Traefik/host setup:

- TCP 80/443 are owned by the existing ingress; the Rapport profile publishes no host ports and starts no Caddy.
- The dedicated internal network and fixed Traefik peer are persistent in the Traefik owner configuration, use a non-overlapping subnet, and contain only Traefik and the Rapport app. The app's Redis network is separate.
- DNS A/AAAA records point only to intended ingress addresses. The configured resolver can issue the certificate for `rapport.chames.tn`; a normal validating client accepts it, and HTTP redirects to HTTPS as intended.
- Forwarded-header trust matches the real proxy chain. From an external client, a forged `X-Forwarded-For` must not let the same client evade the shared Redis rate limit. If a CDN is present, validate the CDN-to-Traefik trust configuration and origin exposure.
- From a normal HTTPS external client, bootstrap CSRF and submit one synthetic audit POST with a valid token and the expected HTTPS Origin. Confirm it succeeds and an invalid origin is rejected. Check that the app sees the expected sanitized forwarded protocol/client address, then verify bounded requests from distinct known client IPs and a same-client forged-`X-Forwarded-For` sequence through the actual final proxy/CDN chain enforce the intended shared quota and do not allow evasion. Do not infer these behaviors from liveness, readiness, CSRF bootstrap, or the home page GET.
- The request body limit is 1,100,000 bytes, matching the app. Traefik's deadlines allow the 10-second worker deadline plus response margin, and its in-flight limit of 8 is active. Access logs omit bodies, query strings, sensitive headers, and unnecessary client identifiers, with bounded retention/rotation.
- The host has the chosen memory/CPU headroom under a synthetic maximum-size and two-worker load check, and disk/log/AOF monitoring is in place. Record latency and resource use; these checks do not establish capacity for arbitrary public traffic.
- The privacy notice identifies the selected host and the actual host, proxy, backup, and telemetry retention practices. Application non-retention does not establish those infrastructure practices.

## Prepare and start Rapport

Before starting, use the reviewed Rapport checkout, not the portfolio directory. Confirm the worktree is clean and `git rev-parse HEAD` matches the release SHA. Use recent `python3 scripts/vps_preflight.py` output; rerun it if the VPS has changed since the 2026-10-07 inventory. Stop if current free memory/disk or measured container usage no longer leaves a safety reserve for the initial app 2 GiB/2 CPU and Redis 256 MiB/0.5 CPU limits. The worker baseline is two; it has not been load-validated.

The single deploy script prepares the ingress first, then builds and starts only the Rapport Compose project and runs its initial smokes. From the repository root:

~~~sh
bash scripts/deploy_cohost.sh
~~~

The script runs `scripts/prepare_traefik_ingress.py` with no arguments. That helper validates the current Traefik owner stack and available subnet, writes the additive `/home/ubuntu/traefik/docker-compose.override.yml`, and creates or verifies the internal `rapport-auditor-ingress` network at `172.27.0.0/24`. Its allocator range is `172.27.0.128/25`, leaving Traefik's static `172.27.0.2` outside that range. It connects the running Traefik container without restarting it; success output must include `traefik_restarted=false`. Future explicit Traefik Compose commands must include both `-f docker-compose.yml` and `-f docker-compose.override.yml`; default file discovery loads the override automatically.

The script copies `deployment/.env.traefik.example` only when the ignored env file is absent. It never overwrites an existing file or prints its values. It accepts only the reviewed domain, network, peer, two-worker baseline, and initial app limits (`2g` memory/`2.0` CPU). It clears shell-exported Compose interpolation values so Compose uses the validated env file. The dedicated Redis is capped at 256 MiB/0.5 CPU. The script creates a 32-byte random secret only if absent, checks silently that it contains at least 32 bytes, then sets the file owner to container UID/GID `10001:10001` and mode `0400`. Existing secret contents are preserved. If an existing env value does not match the verified profile, the script stops without showing it; inspect and correct it locally before rerunning.

After `docker compose config --quiet`, the script builds `app`, runs `up -d` and `ps` for project `rapport-auditor-traefik`, waits up to 40 seconds for the app health check, then runs `scripts/container_smoke.py` inside the app container and `scripts/release_http_smoke.py` from the host. The first uses the actual app/Redis but Flask's test client, bypassing Waitress and Traefik; it covers readiness and synthetic French audit, English revision, and native form submission. The HTTPS smoke uses normal certificate validation, checks health/security headers, and submits synthetic bilingual API/native-form requests. It does not test invalid-origin rejection, forwarded-IP quota enforcement, log omission, max-body concurrency, or capacity.

The profile publishes no host ports and starts no Caddy. Do not use the standalone `scripts/verify_release.sh`, which assumes the Caddy profile and host ports 80/443. If the script fails after `up -d`, containers may remain running; do not treat the deployment as signed off. Share the non-secret error/status output for diagnosis.

Before announcing the URL, complete the outstanding live checks above: confirm HTTP redirects to valid HTTPS; test valid and invalid origins from an external client; verify the real proxy chain and that forged `X-Forwarded-For` cannot evade the shared Redis quota; confirm the synthetic canary and sensitive request data do not appear in app/Traefik logs; verify the 1,100,000-byte cap, in-flight limit, timeouts, and observability behavior; and measure resource use under a synthetic maximum-body/two-worker test. Do not stop a shared Redis service to simulate failure. Do not upload personal reports for acceptance testing.

## Rapport-only rollback

To remove the Rapport route and stop its containers while leaving the portfolio, Traefik, external ingress network, and Rapport Redis quota volume untouched, run this from the Rapport checkout:

~~~sh
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml down
~~~

Do not add `--volumes` or run `docker system prune`. Compose `down` removes only this Rapport project and its project network; the named `redis_rate_state` volume and the external Traefik ingress network remain. To restore service later, use the reviewed candidate and the normal start commands above. Do not run the portfolio's deploy script as part of a Rapport rollback.
