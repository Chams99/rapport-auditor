# Co-hosting on the portfolio VPS

This runbook is for the separate Rapport Auditor project on the VPS that serves the portfolio. It does not change the portfolio Compose project. The dedicated profile is `deployment/compose.traefik.yaml`, with its operator-managed settings in `deployment/.env.traefik` copied from `deployment/.env.traefik.example`. Its Compose project is `rapport-auditor-traefik`.

## What is known

The portfolio repository routes its blue and green containers through an external Docker network named `traefik`; its labels use the `websecure` entrypoint and certificate resolver `myresolver`. The portfolio containers do not publish host ports. This proves the repository's intended routing convention, not the current live Traefik version, configuration, or network membership.

The chosen Rapport hostname is `rapport.chames.tn`. On 2026-10-07, its A record resolved to the same IPv4 address as `chames.tn` and the supplied OVH VPS hostname; it had no AAAA answer. That is consistent with direct DNS to the VPS, but it does not rule out a CDN or another upstream proxy. A normal certificate-validating HTTPS GET from the workstation failed before an HTTP response because Windows Schannel reported `SEC_E_UNTRUSTED_ROOT`. This is not proof that other clients reject the certificate. The live route, certificate chain, Traefik, host capacity, access logs, upstream proxies, and provider retention remain unverified. Do not announce public availability until the operator checks them on the VPS and from a normal external client.

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

Inspect the actual Traefik owner configuration through its existing review process to confirm the router entrypoint, `myresolver`, `default-chain@file`, forwarded-header trust, access-log fields and retention, body handling, and request/response timeouts. The Traefik profile replaces Caddy, so Caddy's standalone body, timeout, health-check, and log-filter settings do not apply. The profile supplies a 1,100,000-byte body cap with an equal in-memory threshold and an app readiness check; global Traefik timeout and logging behavior still need live verification. Do not paste unfiltered `docker inspect`, `docker compose config`, or secret-bearing configuration into logs or messages. If a CDN/upstream proxy exists, configure Traefik to trust only that provider's documented `trustedIPs`; never enable insecure forwarded headers. If there is no upstream proxy, verify that direct clients cannot spoof the address used by Rapport's limiter.

## Required ingress and capacity setup

Keep Traefik on its current public `traefik` network. In the operator-owned Traefik Compose configuration, define the separate `rapport-auditor-ingress` Docker bridge persistently with `internal: true` and a subnet that does not overlap the host, Docker networks, or VPNs. Attach only Traefik and the Rapport app to it; assign Traefik a fixed address there. The Rapport profile joins that network externally and routes the app through it. Set `RAPPORT_AUDITOR_TRUSTED_PROXY` to that exact fixed Traefik address, not a subnet, the public client address, or the old standalone Caddy address. Configure the Traefik Docker provider/service network to select `rapport-auditor-ingress`. Do not rely on a one-time `docker network connect`; membership and the fixed address must survive Traefik container recreation through its own Compose definition. Keep Redis only on Rapport's separate internal Redis network.

Waitress honors forwarded-for/protocol headers only from the exact configured peer and uses one trusted proxy hop. Verify the fixed address reported for the live Traefik container on `rapport-auditor-ingress` and compare it exactly with `RAPPORT_AUDITOR_TRUSTED_PROXY` before the first start and after every Traefik recreation; do this without printing the environment file. If the peer is wrong, Waitress strips those headers: HTTPS write requests can return 403 `origin_rejected`, while safe GET, CSRF bootstrap, and readiness requests may still return 200 and the limiter can collapse all clients to the proxy/socket identity. A successful health GET alone does not validate forwarded-proxy trust.

After the operator-owned Traefik stack creates this network, inspect only its network fields and members:

~~~sh
docker network inspect rapport-auditor-ingress --format 'name={{.Name}} driver={{.Driver}} internal={{.Internal}}{{range .IPAM.Config}} subnet={{.Subnet}} gateway={{.Gateway}}{{end}}'
docker network inspect rapport-auditor-ingress --format '{{range .Containers}}{{println .Name .IPv4Address}}{{end}}'
~~~

The profile requires the operator to set `RAPPORT_AUDITOR_APP_MEMORY_LIMIT` and `RAPPORT_AUDITOR_APP_CPU_LIMIT` after measuring the live host. Its analysis budget is two concurrent workers, each limited to 512 MiB address space and 8 CPU seconds with a 10-second wall deadline; address-space limits are not a resident-memory guarantee. The previously reviewed standalone app budget is 2 GiB and 2 CPUs, with Redis capped at 256 MiB and 0.5 CPU. Treat that as a starting capacity envelope, not proof that the shared VPS can carry it. Count all other container limits, including both portfolio blue/green instances during a rollout (each 256 MiB and 0.25 CPU), Traefik, and host services. Check measured memory/CPU under representative activity, define host safety reserve, and ensure free Docker disk can hold the candidate image, the prior image for rollback, bounded logs, and the Redis AOF volume. If the resource inventory or reserve is unknown, do not start the app.

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

These commands assume the reviewed candidate source and this profile already exist in the server checkout. This workstation's source tree is uncommitted; no commit or push has been made, so do not run these commands against a stale or different checkout. Transfer/update the reviewed candidate through the operator's normal source workflow, separately from the portfolio checkout, then confirm its path and status.

In the Rapport checkout on the VPS, copy the template and edit the ignored file without displaying its values. Use the confirmed hostname, the persistent network name, the exact Traefik peer IP, and limits chosen from the inventory above. The secret path in the template resolves to `deployment/secrets/rapport_secret_key`.

~~~sh
cd /path/to/rapport-auditor
git status --short
cp deployment/.env.traefik.example deployment/.env.traefik
install -d -m 0700 deployment/secrets
umask 077
openssl rand -hex 32 > deployment/secrets/rapport_secret_key
sudo chown 10001:10001 deployment/secrets/rapport_secret_key
sudo chmod 0400 deployment/secrets/rapport_secret_key

# Edit deployment/.env.traefik with a local editor; do not cat or paste it.
# Set domain, ingress network, exact trusted proxy, secret-file path,
# and the capacity-approved app memory/CPU limits.
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml config --quiet
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml build
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml up -d
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml ps
~~~

The operator-managed `.env.traefik` and secret must remain private and ignored by Git. Do not use `docker compose config` without quiet mode in shared output because it renders interpolated settings. Do not start until the dedicated network exists, the secret is readable by container UID 10001, the exact peer IP and limits are set, and the quiet config check succeeds.

After startup, check health through the public hostname with normal TLS validation; do not use `-k` or equivalent:

~~~sh
curl -fsS --max-time 10 https://rapport.chames.tn/api/v1/health/live
curl -fsS --max-time 10 https://rapport.chames.tn/api/v1/health/ready
curl -sS -D - -o /dev/null --max-time 10 https://rapport.chames.tn/
~~~

Then exercise a synthetic English and French text audit and revision from an external browser, verify CSRF and host/origin rejection, and run the forwarded-IP/rate-limit check with synthetic requests. Confirm Redis outage fails closed and readiness recovers after Redis returns. Do not upload personal reports for acceptance testing. The route, health checks, and synthetic flows must pass before the URL is announced.

## Rapport-only rollback

To remove the Rapport route and stop its containers while leaving the portfolio, Traefik, external ingress network, and Rapport Redis quota volume untouched, run this from the Rapport checkout:

~~~sh
docker compose --project-name rapport-auditor-traefik --env-file deployment/.env.traefik -f deployment/compose.traefik.yaml down
~~~

Do not add `--volumes` or run `docker system prune`. Compose `down` removes only this Rapport project and its project network; the named `redis_rate_state` volume and the external Traefik ingress network remain. To restore service later, use the reviewed candidate and the normal start commands above. Do not run the portfolio's deploy script as part of a Rapport rollback.
