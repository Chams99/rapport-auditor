"""Prepare Rapport's persistent, isolated Traefik ingress without restarting Traefik."""

from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

Runner = Callable[..., subprocess.CompletedProcess[str]]

OWNER_DIR = Path("/home/ubuntu/traefik")
OWNER_COMPOSE = OWNER_DIR / "docker-compose.yml"
OVERRIDE = OWNER_DIR / "docker-compose.override.yml"
PROJECT = "traefik"
CONTAINER = "traefik"
NETWORK = "rapport-auditor-ingress"
SUBNET = ipaddress.ip_network("172.27.0.0/24")
IP_RANGE = ipaddress.ip_network("172.27.0.128/25")
PEER = ipaddress.ip_address("172.27.0.2")
IMAGE_DIGEST = (
    "traefik@sha256:90099f8948c828ecf0ababd711a4359a2443eba12261c1df2f548a3b1d815938"
)

OVERRIDE_TEXT = f"""services:
  traefik:
    image: {IMAGE_DIGEST}
    networks:
      {NETWORK}:
        ipv4_address: {PEER}

networks:
  {NETWORK}:
    name: {NETWORK}
    external: true
"""

class PreflightError(Exception):
    """A failed precondition; messages are fixed strings with no command output."""


def _run(args: Sequence[str], runner: Runner, *, cwd: Path | None = None) -> str:
    try:
        result = runner(args, capture_output=True, text=True, check=False, cwd=cwd)
    except Exception as exc:
        raise PreflightError("A required local Docker or network command was unavailable.") from exc
    if result.returncode != 0:
        raise PreflightError("A required local Docker or network check failed; details were withheld.")
    return result.stdout


def _json(args: Sequence[str], runner: Runner, *, cwd: Path | None = None) -> Any:
    try:
        return json.loads(_run(args, runner, cwd=cwd))
    except (json.JSONDecodeError, TypeError) as exc:
        raise PreflightError("A Docker metadata response was invalid; details were withheld.") from exc


def _one_inspect(args: Sequence[str], runner: Runner) -> dict[str, Any]:
    result = _json(args, runner)
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise PreflightError("A requested Docker object was missing or ambiguous.")
    return result[0]


def _container_labels(container: dict[str, Any]) -> dict[str, str]:
    config = container.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        return {}
    return {key: value for key, value in labels.items() if isinstance(key, str) and isinstance(value, str)}


def _validate_owner_container(container: dict[str, Any], runner: Runner) -> str:
    labels = _container_labels(container)
    expected_labels = {
        "com.docker.compose.project": PROJECT,
        "com.docker.compose.service": CONTAINER,
        "com.docker.compose.project.working_dir": str(OWNER_DIR),
        "com.docker.compose.project.config_files": str(OWNER_COMPOSE),
    }
    if any(labels.get(key) != value for key, value in expected_labels.items()):
        raise PreflightError("The running Traefik container does not match the expected owner Compose stack.")
    state = container.get("State")
    if (
        container.get("Name") != f"/{CONTAINER}"
        or not isinstance(state, dict)
        or state.get("Running") is not True
    ):
        raise PreflightError("The expected Traefik container is not running under its verified name.")
    container_id = container.get("Id")
    if not isinstance(container_id, str) or not re.fullmatch(r"[0-9a-f]{64}", container_id):
        raise PreflightError("The running Traefik container ID could not be validated.")
    config = container.get("Config", {})
    if not isinstance(config, dict) or config.get("Image") != "traefik:latest":
        raise PreflightError("The running Traefik image reference differs from the inspected release.")
    image_id = container.get("Image")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise PreflightError("The running Traefik image ID could not be validated.")
    image = _one_inspect(["docker", "image", "inspect", image_id], runner)
    digests = image.get("RepoDigests")
    if not isinstance(digests, list) or IMAGE_DIGEST not in digests:
        raise PreflightError("The running Traefik image digest differs from the verified VPS snapshot.")

    entrypoint = config.get("Entrypoint", [])
    command = config.get("Cmd", [])
    if (
        not isinstance(entrypoint, list)
        or not isinstance(command, list)
        or any(not isinstance(item, str) for item in entrypoint + command)
    ):
        raise PreflightError("The running Traefik arguments could not be safely checked.")
    arguments = entrypoint + command
    for argument in arguments:
        key, separator, _value = argument.lstrip("-").partition("=")
        if key.lower() in {"configfile", "entrypoints.websecure.http.middlewares"}:
            raise PreflightError("Traefik has a static config or EntryPoint middleware requiring operator review.")
        if separator == "" and argument.lower() in {"--configfile", "--entrypoints.websecure.http.middlewares"}:
            raise PreflightError("Traefik has a static config or EntryPoint middleware requiring operator review.")
    environment = config.get("Env", [])
    if not isinstance(environment, list):
        raise PreflightError("Traefik environment metadata could not be safely checked.")
    forbidden_env_keys = {
        "TRAEFIK_CONFIGFILE",
        "TRAEFIK_ENTRYPOINTS_WEBSECURE_HTTP_MIDDLEWARES",
    }
    for entry in environment:
        if isinstance(entry, str) and entry.partition("=")[0].upper() in forbidden_env_keys:
            raise PreflightError("Traefik has a static config or EntryPoint middleware requiring operator review.")
    return container_id


def _check_implicit_config(runner: Runner) -> None:
    probe = (
        "found=0; "
        "for d in /etc/traefik \"${XDG_CONFIG_HOME:-}\" \"${HOME:+$HOME/.config}\" \"$PWD\"; do "
        "[ -n \"$d\" ] || continue; "
        "for f in traefik.yml traefik.yaml traefik.toml; do "
        "[ ! -f \"$d/$f\" ] || found=1; done; done; "
        "if [ \"$found\" = 1 ]; then printf present; else printf none; fi"
    )
    status = _run(["docker", "exec", CONTAINER, "sh", "-c", probe], runner).strip()
    if status != "none":
        raise PreflightError("An implicit Traefik static config may exist; inspect it before changing the stack.")


def _check_owner_files() -> None:
    if not OWNER_DIR.is_dir() or OWNER_DIR.resolve() != OWNER_DIR:
        raise PreflightError("The verified Traefik owner directory is unavailable or redirected.")
    if not OWNER_COMPOSE.is_file() or OWNER_COMPOSE.is_symlink():
        raise PreflightError("The verified Traefik Compose file is unavailable or redirected.")
    unexpected = (
        OWNER_DIR / "compose.yaml",
        OWNER_DIR / "compose.yml",
        OWNER_DIR / "compose.override.yaml",
        OWNER_DIR / "compose.override.yml",
        OWNER_DIR / "docker-compose.override.yaml",
    )
    if any(path.exists() or path.is_symlink() for path in unexpected):
        raise PreflightError("An alternate/default Compose file exists; the owner stack needs manual review.")
    if os.environ.get("COMPOSE_FILE"):
        raise PreflightError("COMPOSE_FILE is set; run this helper from a clean operator shell.")
    if OVERRIDE.exists() or OVERRIDE.is_symlink():
        if OVERRIDE.is_symlink() or not OVERRIDE.is_file() or OVERRIDE.read_text(encoding="utf-8") != OVERRIDE_TEXT:
            raise PreflightError("A different Compose override already exists; it was left untouched.")


def _compose_model(files: Sequence[Path], runner: Runner, *, directory: Path) -> dict[str, Any]:
    args = ["docker", "compose", "--project-name", PROJECT, "--project-directory", str(directory)]
    for file in files:
        args.extend(["-f", str(file)])
    args.extend(["config", "--format", "json"])
    model = _json(args, runner, cwd=directory)
    if not isinstance(model, dict):
        raise PreflightError("The owner Compose model was not an object; details were withheld.")
    return model


def _expected_merged(base: dict[str, Any]) -> dict[str, Any]:
    expected = copy.deepcopy(base)
    services = expected.get("services")
    networks = expected.get("networks")
    if not isinstance(services, dict) or not isinstance(networks, dict):
        raise PreflightError("The owner Compose model has an unexpected shape; no change was made.")
    service = services.get(CONTAINER)
    if not isinstance(service, dict) or service.get("image") != "traefik:latest":
        raise PreflightError("The owner Compose service differs from the inspected Traefik release.")
    service_networks = service.get("networks")
    if not isinstance(service_networks, dict) or "traefik" not in service_networks:
        raise PreflightError("The owner Traefik service does not use its expected existing network.")
    if NETWORK in networks or NETWORK in service_networks:
        raise PreflightError("The dedicated Rapport network already appears in the owner Compose model.")
    service["image"] = IMAGE_DIGEST
    service_networks[NETWORK] = {"ipv4_address": str(PEER)}
    networks[NETWORK] = {"name": NETWORK, "external": True}
    return expected


def _validate_merge(base: dict[str, Any], merged: dict[str, Any]) -> None:
    if merged != _expected_merged(base):
        raise PreflightError("The proposed override changes more than the Traefik image pin and Rapport network.")


def _network_model(name: str, runner: Runner) -> dict[str, Any]:
    return _one_inspect(["docker", "network", "inspect", name], runner)


def _network_config(network: dict[str, Any]) -> list[dict[str, Any]]:
    ipam = network.get("IPAM")
    configs = ipam.get("Config", []) if isinstance(ipam, dict) else []
    if not isinstance(configs, list):
        raise PreflightError("A Docker network IPAM record was invalid.")
    if any(not isinstance(item, dict) or not isinstance(item.get("Subnet"), str) for item in configs):
        raise PreflightError("A Docker network subnet was invalid.")
    return configs


def _network_subnets(network: dict[str, Any]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    try:
        return [ipaddress.ip_network(item["Subnet"], strict=False) for item in _network_config(network)]
    except (ValueError, TypeError) as exc:
        raise PreflightError("A Docker network subnet was invalid.") from exc


def _candidate_network_state(runner: Runner) -> tuple[dict[str, Any] | None, bool]:
    names = _run(["docker", "network", "ls", "--format", "{{.Name}}"], runner).splitlines()
    target = None
    for name in names:
        if name == NETWORK:
            target = _network_model(name, runner)
            continue
        model = _network_model(name, runner)
        if any(SUBNET.overlaps(subnet) for subnet in _network_subnets(model) if subnet.version == 4):
            raise PreflightError("The candidate subnet overlaps an existing Docker network.")
    routes = _run(["ip", "-4", "route", "show", "table", "all"], runner)
    for line in routes.splitlines():
        fields = line.split()
        if not fields:
            continue
        destination = fields[1] if fields[0] in {"local", "broadcast", "blackhole", "unreachable", "prohibit", "multicast", "nat", "throw"} and len(fields) > 1 else fields[0]
        if destination == "default":
            continue
        try:
            route = ipaddress.ip_network(destination, strict=False)
        except ValueError:
            continue
        if route.version == 4 and SUBNET.overlaps(route) and not (target is not None and route == SUBNET):
            raise PreflightError("The candidate subnet overlaps an IPv4 route on the host.")
    if target is None:
        return None, False
    if target.get("Name") != NETWORK or target.get("Driver") != "bridge" or target.get("Internal") is not True:
        raise PreflightError("The existing Rapport network has the wrong name, driver, or internal setting.")
    subnets = _network_subnets(target)
    if subnets != [SUBNET]:
        raise PreflightError("The existing Rapport network does not use the verified dedicated subnet.")
    configs = _network_config(target)
    try:
        ip_ranges = [ipaddress.ip_network(config.get("IPRange", ""), strict=False) for config in configs]
    except (ValueError, TypeError) as exc:
        raise PreflightError("The existing Rapport network address reservation is invalid.") from exc
    if ip_ranges != [IP_RANGE] or PEER in IP_RANGE:
        raise PreflightError("The existing Rapport network does not reserve its dynamic pool away from Traefik.")
    return target, True


def _member_role(container_id: str, runner: Runner) -> tuple[str, str]:
    container = _one_inspect(["docker", "inspect", container_id], runner)
    if container.get("Name") == f"/{CONTAINER}":
        return "traefik", container_id
    labels = _container_labels(container)
    if (
        labels.get("com.docker.compose.project") == "rapport-auditor-traefik"
        and labels.get("com.docker.compose.service") == "app"
    ):
        return "app", container_id
    raise PreflightError("The dedicated network has an unexpected attached container.")


def _validate_members(network: dict[str, Any], runner: Runner) -> tuple[bool, str | None]:
    containers = network.get("Containers")
    if containers is None:
        containers = {}
    if not isinstance(containers, dict) or len(containers) > 2:
        raise PreflightError("The dedicated network has unexpected members.")
    traefik_attached = False
    traefik_address = None
    roles: set[str] = set()
    for container_id, endpoint in containers.items():
        if not isinstance(container_id, str) or not re.fullmatch(r"[0-9a-f]{12,64}", container_id) or not isinstance(endpoint, dict):
            raise PreflightError("A dedicated network endpoint could not be validated.")
        role, _ = _member_role(container_id, runner)
        if role in roles:
            raise PreflightError("The dedicated network contains duplicate service members.")
        roles.add(role)
        if role == "traefik":
            traefik_attached = True
            raw_address = endpoint.get("IPv4Address", "")
            try:
                traefik_address = ipaddress.ip_interface(raw_address).ip if raw_address else None
            except ValueError as exc:
                raise PreflightError("The Traefik network address could not be validated.") from exc
    if traefik_attached and traefik_address != PEER:
        raise PreflightError("Traefik is attached with a stale or unexpected peer address.")
    return traefik_attached, str(traefik_address) if traefik_address else None


def _write_override() -> None:
    if OVERRIDE.exists():
        if not OVERRIDE.is_file() or OVERRIDE.is_symlink() or OVERRIDE.read_text(encoding="utf-8") != OVERRIDE_TEXT:
            raise PreflightError("A different Compose override already exists; it was left untouched.")
        return
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=OWNER_DIR, prefix=".rapport-override-", delete=False
        ) as temp_file:
            temp_name = temp_file.name
            os.chmod(temp_name, 0o600)
            temp_file.write(OVERRIDE_TEXT)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        try:
            os.link(temp_name, OVERRIDE)
        except FileExistsError:
            if OVERRIDE.is_symlink() or not OVERRIDE.is_file() or OVERRIDE.read_text(encoding="utf-8") != OVERRIDE_TEXT:
                raise PreflightError(
                    "A different Compose override appeared concurrently; it was left untouched."
                ) from None
        os.unlink(temp_name)
        temp_name = None
    except PreflightError:
        raise
    except OSError as exc:
        raise PreflightError("The persistent additive Compose override could not be written.") from exc
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def prepare(runner: Runner = subprocess.run) -> str:
    _check_owner_files()
    owner_container = _one_inspect(["docker", "inspect", CONTAINER], runner)
    owner_id = _validate_owner_container(owner_container, runner)
    _check_implicit_config(runner)

    base_model = _compose_model([OWNER_COMPOSE], runner, directory=OWNER_DIR)
    expected_model = _expected_merged(base_model)
    with tempfile.TemporaryDirectory(prefix="rapport-traefik-override-") as temporary_directory:
        temporary_override = Path(temporary_directory) / "override.yml"
        temporary_override.write_text(OVERRIDE_TEXT, encoding="utf-8")
        merged_model = _compose_model([OWNER_COMPOSE, temporary_override], runner, directory=OWNER_DIR)
    _validate_merge(base_model, merged_model)
    if expected_model != merged_model:
        raise PreflightError("The private Compose model check did not match the reviewed change.")

    network, exists = _candidate_network_state(runner)
    attached = False
    if exists and network is not None:
        attached, _address = _validate_members(network, runner)

    # Do not alter persistent files until owner, merged model, routes, and current membership pass.
    _write_override()
    if not exists:
        _run(
            [
                "docker", "network", "create", "--driver", "bridge", "--internal",
                "--subnet", str(SUBNET), "--ip-range", str(IP_RANGE), NETWORK,
            ],
            runner,
        )
        network = _network_model(NETWORK, runner)
        configs = _network_config(network)
        try:
            ip_ranges = [ipaddress.ip_network(config.get("IPRange", ""), strict=False) for config in configs]
        except (ValueError, TypeError) as exc:
            raise PreflightError("The newly created network address reservation was invalid.") from exc
        if (
            network.get("Driver") != "bridge"
            or network.get("Internal") is not True
            or _network_subnets(network) != [SUBNET]
            or ip_ranges != [IP_RANGE]
            or PEER in IP_RANGE
        ):
            raise PreflightError("The newly created dedicated network failed its immediate verification.")
        attached, _address = _validate_members(network, runner)
    if not attached:
        current_container = _one_inspect(["docker", "inspect", CONTAINER], runner)
        if _validate_owner_container(current_container, runner) != owner_id:
            raise PreflightError("Traefik changed during preparation; no attachment was attempted.")
        _run(["docker", "network", "connect", "--ip", str(PEER), NETWORK, owner_id], runner)
    final_network = _network_model(NETWORK, runner)
    final_attached, address = _validate_members(final_network, runner)
    if not final_attached or address != str(PEER):
        raise PreflightError("The final Traefik network peer did not match the pinned trusted-proxy address.")
    final_container = _one_inspect(["docker", "inspect", CONTAINER], runner)
    if _validate_owner_container(final_container, runner) != owner_id:
        raise PreflightError("Traefik changed during preparation; review the network before continuing.")
    return (
        "Prepared persistent Rapport ingress safely.\n"
        f"owner_override={OVERRIDE}\n"
        f"network={NETWORK} subnet={SUBNET} internal=true\n"
        f"traefik_peer={address}\n"
        f"traefik_image_pinned={IMAGE_DIGEST}\n"
        "traefik_restarted=false\n"
        "Next: deploy only the Rapport Compose project after setting its private env file and capacity limits."
    )


def main() -> int:
    try:
        print(prepare(), flush=True)
    except PreflightError as exc:
        print(f"Aborted: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
