from __future__ import annotations

import json
import subprocess

from scripts.vps_preflight import (
    _safe_address,
    _safe_identifier,
    _safe_names,
    _summarize_arguments,
    _summarize_environment,
    collect_report,
)


def test_argument_summary_keeps_only_typed_proxy_metadata_and_flags_config_file():
    output = "\n".join(
        _summarize_arguments(
            [
                "--entrypoints.websecure.address=:443",
                "--entrypoints.websecure.http.tls=true",
                "--entrypoints.websecure.http.middlewares=default-chain@file",
                "--entrypoints.websecure.forwardedheaders.insecure=false",
                "--entrypoints.websecure.forwardedheaders.trustedips=172.27.0.2/32",
                "--entrypoints.websecure.transport.respondingtimeouts.readtimeout=30s",
                "--entrypoints.websecure.transport.respondingtimeouts.writetimeout=bad-token",
                "--entrypoints.web.http.redirections.entrypoint.to=websecure",
                "--certificatesresolvers.myresolver.acme.httpchallenge.entrypoint=web",
                "--certificatesresolvers.myresolver.acme.email=user:password@example.test",
                "--providers.docker.network=traefik",
                "--providers.file.directory=/dynamic",
                "--configFile=/etc/traefik/traefik.yml",
                "--log.level=INFO",
                "--accesslog.filepath=https://user:password@example.test/access?token=hidden",
            ]
        )
    )
    assert "entrypoints.websecure.address=:443" in output
    assert "entrypoints.websecure.forwardedheaders.trustedips=172.27.0.2/32" in output
    assert "readtimeout=30s" in output
    assert "writetimeout" not in output
    assert "resolver=myresolver challenge=http entrypoint=web" in output
    assert "static_config_file=/etc/traefik/traefik.yml" in output
    for secret in ("password", "example.test", "bad-token", "hidden"):
        assert secret not in output


def test_environment_summary_ignores_credentials_and_rejects_unsafe_allowlisted_values():
    output = "\n".join(
        _summarize_environment(
            [
                "TRAEFIK_ENTRYPOINTS_WEBSECURE_ADDRESS=:443",
                "TRAEFIK_ENTRYPOINTS_WEBSECURE_FORWARDEDHEADERS_TRUSTEDIPS=10.0.0.0/8,172.27.0.2/32",
                "TRAEFIK_CERTIFICATESRESOLVERS_LETSENCRYPT_ACME_HTTPCHALLENGE_ENTRYPOINT=web",
                "TRAEFIK_CERTIFICATESRESOLVERS_LETSENCRYPT_ACME_EMAIL=user:password@example.test",
                "TRAEFIK_PROVIDERS_DOCKER_NETWORK=https://user:token@example.test/network",
                "TRAEFIK_CONFIGFILE=/private/token-config.yaml",
                "UNRELATED_TOKEN=do-not-print",
            ]
        )
    )
    assert "entrypoints.websecure.address=:443" in output
    assert "10.0.0.0/8,172.27.0.2/32" in output
    assert "resolver=letsencrypt challenge=http entrypoint=web" in output
    assert "static_config_file=configured (path omitted; contents not read" in output
    for secret in ("password", "example.test", "token", "do-not-print"):
        assert secret not in output


def test_token_shaped_identifiers_names_hosts_and_paths_are_omitted():
    sentinel = "ghp_" + ("A" * 36)
    assert not _safe_identifier(sentinel)
    assert _safe_names(f"audit@{sentinel}") is None
    assert _safe_names(f"{sentinel}@file") is None
    assert _safe_address(f"{sentinel}:443") is None
    assert _safe_address(f"proxy-{sentinel}.invalid:443") is None

    output = "\n".join(
        _summarize_arguments(
            [
                f"--providers.docker.network={sentinel}",
                f"--entrypoints.websecure.address={sentinel}:443",
                f"--entrypoints.websecure.http.middlewares=auth@{sentinel}",
                f"--providers.file.directory=/run/{sentinel}",
            ]
        )
    )
    assert sentinel not in output


def test_report_prints_digest_routes_and_network_metadata_without_config_secrets():
    image_id = "sha256:" + "a" * 64
    good_digest = "docker.io/library/traefik@sha256:" + "b" * 64
    secret_digest = "registry.example/token@sha256:" + "c" * 64
    container = {
        "Image": image_id,
        "Config": {
            "Image": "traefik:latest",
            "Entrypoint": [
                "/entrypoint.sh",
                "--entrypoints.websecure.address=:443",
                "--entrypoints.websecure.http.middlewares=default-chain@file",
                "--certificatesresolvers.myresolver.acme.httpchallenge.entrypoint=web",
                "--providers.docker.network=traefik",
                "--log.level=INFO",
            ],
            "Cmd": [],
            "Env": [
                "TRAEFIK_ENTRYPOINTS_WEBSECURE_FORWARDEDHEADERS_INSECURE=false",
                "TRAEFIK_ENTRYPOINTS_WEBSECURE_FORWARDEDHEADERS_TRUSTEDIPS=172.27.0.2/32",
                "TRAEFIK_CERTIFICATESRESOLVERS_MYRESOLVER_ACME_EMAIL=user:password@example.test",
                "API_TOKEN=https://user:secret@example.test/?token=do-not-print",
            ],
            "Labels": {
                "traefik.http.middlewares.auth.basicauth.users": "admin:$apr1$private-hash-value",
                "com.docker.compose.project.working_dir": "/home/ubuntu/traefik",
            },
        },
        "NetworkSettings": {"Networks": {"traefik": {"IPAddress": "172.18.0.3"}}},
    }
    network = {
        "Name": "traefik",
        "Internal": False,
        "IPAM": {"Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}]},
    }

    def fake_runner(args, **kwargs):
        args = list(args)
        if args == ["docker", "inspect", "traefik"]:
            stdout = json.dumps([container])
        elif args == ["docker", "image", "inspect", image_id]:
            stdout = json.dumps([{"RepoDigests": [good_digest, secret_digest]}])
        elif args[:3] == ["docker", "info", "--format"]:
            stdout = json.dumps([{"Base": "172.16.0.0/12", "Size": 24}])
        elif args == ["docker", "network", "ls", "-q"]:
            stdout = "0123456789ab\n"
        elif args == ["docker", "network", "inspect", "0123456789ab"]:
            stdout = json.dumps([network])
        elif args == ["ip", "-4", "rule", "show"]:
            stdout = "0: from all lookup local\n100: from 10.0.0.0/8 lookup 100\n32766: from all lookup main\n"
        elif args == ["ip", "-4", "route", "show", "table", "all"]:
            stdout = (
                "default via 51.255.192.1 dev ens3 proto dhcp src 51.255.195.217 metric 100\n"
                "172.18.0.0/16 dev br-0123456789ab proto kernel scope link src 172.18.0.1\n"
                "10.0.0.0/8 dev vpn0 table 100 scope link\n"
                "local 127.0.0.0/8 dev lo table local proto kernel scope host src 127.0.0.1\n"
            )
        else:
            raise AssertionError(f"unexpected command shape: {args[:3]}")
        return subprocess.CompletedProcess(args, 0, stdout, "stderr secret must stay hidden")

    output = collect_report(fake_runner)
    assert good_digest in output
    assert "172.18.0.0/16" in output
    assert "10.0.0.0/8" in output
    assert "type=local dest=127.0.0.0/8" in output
    assert "static_config_file=not specified by selected CLI/environment flags" in output
    assert "entrypoints.websecure.http.middlewares=default-chain@file" in output
    for secret in (
        "password",
        "example.test",
        "private-hash-value",
        "do-not-print",
        "stderr secret",
        secret_digest,
    ):
        assert secret not in output


def test_failed_commands_report_only_generic_failure_text():
    def failing_runner(args, **kwargs):
        raise OSError("https://user:credential@example.test/?token=private")

    output = collect_report(failing_runner)
    assert "traefik_container=unavailable (details withheld)" in output
    assert "docker_default_address_pools=unavailable (details withheld)" in output
    assert "private" not in output
    assert "credential" not in output
    assert "example.test" not in output
