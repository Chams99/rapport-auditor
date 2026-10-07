from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import prepare_traefik_ingress as helper


class FakeDocker:
    def __init__(self, owner_dir: Path):
        self.owner_dir = owner_dir
        self.owner_compose = owner_dir / "docker-compose.yml"
        self.owner_compose.write_text("services: {}\n", encoding="utf-8")
        self.container_id = "a" * 64
        self.image_id = "sha256:" + "b" * 64
        self.container = {
            "Id": self.container_id,
            "Name": "/traefik",
            "Image": self.image_id,
            "State": {"Running": True},
            "Config": {
                "Image": "traefik:latest",
                "Entrypoint": ["traefik"],
                "Cmd": ["--providers.docker.network=traefik", "--entrypoints.websecure.address=:443"],
                "Env": [],
                "Labels": {
                    "com.docker.compose.project": "traefik",
                    "com.docker.compose.service": "traefik",
                    "com.docker.compose.project.working_dir": str(owner_dir),
                    "com.docker.compose.project.config_files": str(self.owner_compose),
                },
            },
            "NetworkSettings": {"Networks": {"traefik": {"IPAddress": "172.18.0.3"}}},
        }
        self.base = {
            "services": {"traefik": {"image": "traefik:latest", "networks": {"traefik": {}}}},
            "networks": {"traefik": {"name": "traefik", "external": True}},
        }
        self.networks = {
            "traefik": {
                "Name": "traefik",
                "Driver": "bridge",
                "Internal": False,
                "IPAM": {"Config": [{"Subnet": "172.18.0.0/16"}]},
                "Containers": {},
            }
        }
        self.implicit_config = "none"
        self.overlap = False
        self.extra_merged_change = False
        self.digests = [helper.IMAGE_DIGEST]
        self.fail_network_create_once = False
        self.commands: list[list[str]] = []

    def _result(self, args, stdout="", returncode=0):
        return subprocess.CompletedProcess(args, returncode, stdout, "synthetic secret stderr")

    def __call__(self, args, **kwargs):
        args = list(args)
        self.commands.append(args)
        if args[:3] == ["docker", "inspect", "traefik"]:
            return self._result(args, json.dumps([self.container]))
        if args[:3] == ["docker", "image", "inspect"]:
            return self._result(args, json.dumps([{"RepoDigests": self.digests}]))
        if args[:3] == ["docker", "exec", "traefik"]:
            return self._result(args, self.implicit_config)
        if args[:3] == ["docker", "compose", "--project-name"]:
            files = [Path(args[index + 1]) for index, value in enumerate(args[:-1]) if value == "-f"]
            model = self.base if files[-1] == self.owner_compose else helper._expected_merged(self.base)
            if self.extra_merged_change and files[-1] != self.owner_compose:
                model = json.loads(json.dumps(model))
                model["services"]["other"] = {"image": "unreviewed"}
            return self._result(args, json.dumps(model))
        if args[:3] == ["docker", "network", "ls"]:
            return self._result(args, "\n".join(self.networks) + "\n")
        if args[:3] == ["docker", "network", "inspect"]:
            network = self.networks.get(args[3])
            if network is None:
                return self._result(args, "", 1)
            return self._result(args, json.dumps([network]))
        if args[:3] == ["docker", "network", "create"]:
            if self.fail_network_create_once:
                self.fail_network_create_once = False
                return self._result(args, "", 1)
            self.networks[helper.NETWORK] = {
                "Name": helper.NETWORK,
                "Driver": "bridge",
                "Internal": True,
                "IPAM": {"Config": [{"Subnet": str(helper.SUBNET), "IPRange": str(helper.IP_RANGE)}]},
                "Containers": {},
            }
            return self._result(args, "new-network-id")
        if args[:3] == ["docker", "network", "connect"]:
            self.networks[helper.NETWORK]["Containers"][self.container_id] = {
                "Name": "traefik",
                "IPv4Address": f"{helper.PEER}/24",
            }
            self.container["NetworkSettings"]["Networks"][helper.NETWORK] = {
                "IPAddress": str(helper.PEER)
            }
            return self._result(args)
        if args[:3] == ["docker", "inspect", self.container_id]:
            return self._result(args, json.dumps([self.container]))
        if args == ["ip", "-4", "route", "show", "table", "all"]:
            if self.overlap:
                route = "172.27.0.0/24 dev vpn0 table 100 scope link\n"
            elif helper.NETWORK in self.networks:
                route = f"{helper.SUBNET} dev br-rapport table main scope link\n"
            else:
                route = "10.0.0.0/8 dev vpn0 table 100 scope link\n"
            return self._result(args, "default via 192.0.2.1 dev eth0\n" + route)
        raise AssertionError(f"unexpected command: {args[:4]}")


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    owner_dir = tmp_path / "traefik-owner"
    owner_dir.mkdir()
    fake = FakeDocker(owner_dir)
    monkeypatch.setattr(helper, "OWNER_DIR", owner_dir)
    monkeypatch.setattr(helper, "OWNER_COMPOSE", owner_dir / "docker-compose.yml")
    monkeypatch.setattr(helper, "OVERRIDE", owner_dir / "docker-compose.override.yml")
    monkeypatch.delenv("COMPOSE_FILE", raising=False)
    return fake


def test_prepare_writes_only_additive_override_and_connects_exact_peer(fake_docker):
    report = helper.prepare(fake_docker)

    assert helper.OVERRIDE.read_text(encoding="utf-8") == helper.OVERRIDE_TEXT
    assert f"traefik_peer={helper.PEER}" in report
    assert "traefik_restarted=false" in report
    assert any(command[:3] == ["docker", "network", "create"] for command in fake_docker.commands)
    assert any(command[:3] == ["docker", "network", "connect"] for command in fake_docker.commands)
    assert not any(command[-1:] == ["up"] or "restart" in command for command in fake_docker.commands)
    assert "synthetic secret stderr" not in report


def test_prepare_is_idempotent_when_exact_override_and_network_already_exist(fake_docker):
    helper.prepare(fake_docker)
    fake_docker.commands.clear()

    report = helper.prepare(fake_docker)

    assert "traefik_restarted=false" in report
    assert not any(command[:3] == ["docker", "network", "create"] for command in fake_docker.commands)
    assert not any(command[:3] == ["docker", "network", "connect"] for command in fake_docker.commands)


def test_prepare_aborts_before_persistent_change_on_implicit_static_config(fake_docker, monkeypatch):
    fake_docker.implicit_config = "present"

    with pytest.raises(helper.PreflightError, match="implicit Traefik static config"):
        helper.prepare(fake_docker)

    assert not helper.OVERRIDE.exists()
    assert helper.NETWORK not in fake_docker.networks


def test_prepare_aborts_if_merged_compose_has_any_other_delta(fake_docker):
    fake_docker.extra_merged_change = True

    with pytest.raises(helper.PreflightError, match="changes more than"):
        helper.prepare(fake_docker)

    assert not helper.OVERRIDE.exists()
    assert helper.NETWORK not in fake_docker.networks


def test_prepare_aborts_on_route_overlap_before_writing_override(fake_docker):
    fake_docker.overlap = True

    with pytest.raises(helper.PreflightError, match="overlaps an IPv4 route"):
        helper.prepare(fake_docker)

    assert not helper.OVERRIDE.exists()
    assert helper.NETWORK not in fake_docker.networks


def test_prepare_leaves_conflicting_owner_override_untouched(fake_docker):
    helper.OVERRIDE.write_text("services: {}\n", encoding="utf-8")

    with pytest.raises(helper.PreflightError, match="different Compose override"):
        helper.prepare(fake_docker)

    assert helper.OVERRIDE.read_text(encoding="utf-8") == "services: {}\n"
    assert helper.NETWORK not in fake_docker.networks


def test_prepare_aborts_on_owner_identity_or_digest_mismatch(fake_docker):
    fake_docker.container["Config"]["Labels"]["com.docker.compose.project"] = "other-stack"
    with pytest.raises(helper.PreflightError, match="owner Compose stack"):
        helper.prepare(fake_docker)
    assert not helper.OVERRIDE.exists()
    assert helper.NETWORK not in fake_docker.networks

    fake_docker.container["Config"]["Labels"]["com.docker.compose.project"] = helper.PROJECT
    fake_docker.digests = ["traefik@sha256:" + "c" * 64]
    with pytest.raises(helper.PreflightError, match="image digest"):
        helper.prepare(fake_docker)
    assert not helper.OVERRIDE.exists()
    assert helper.NETWORK not in fake_docker.networks


def test_prepare_aborts_on_existing_network_with_wrong_pool_or_peer(fake_docker):
    fake_docker.networks[helper.NETWORK] = {
        "Name": helper.NETWORK,
        "Driver": "bridge",
        "Internal": True,
        "IPAM": {"Config": [{"Subnet": str(helper.SUBNET), "IPRange": "172.27.0.0/25"}]},
        "Containers": {},
    }
    with pytest.raises(helper.PreflightError, match="dynamic pool"):
        helper.prepare(fake_docker)
    assert not helper.OVERRIDE.exists()

    fake_docker.networks[helper.NETWORK]["IPAM"]["Config"][0]["IPRange"] = str(helper.IP_RANGE)
    fake_docker.networks[helper.NETWORK]["Containers"][fake_docker.container_id] = {
        "Name": "traefik",
        "IPv4Address": "172.27.0.3/24",
    }
    with pytest.raises(helper.PreflightError, match="stale or unexpected peer"):
        helper.prepare(fake_docker)
    assert not helper.OVERRIDE.exists()


def test_prepare_can_resume_after_network_create_fails(fake_docker):
    fake_docker.fail_network_create_once = True

    with pytest.raises(helper.PreflightError, match="Docker or network check failed"):
        helper.prepare(fake_docker)

    assert helper.OVERRIDE.read_text(encoding="utf-8") == helper.OVERRIDE_TEXT
    assert helper.NETWORK not in fake_docker.networks

    report = helper.prepare(fake_docker)
    assert f"traefik_peer={helper.PEER}" in report
    assert "traefik_restarted=false" in report


def test_merge_validator_rejects_removed_existing_network(fake_docker):
    expected = helper._expected_merged(fake_docker.base)
    del expected["services"]["traefik"]["networks"]["traefik"]

    with pytest.raises(helper.PreflightError, match="changes more than"):
        helper._validate_merge(fake_docker.base, expected)
