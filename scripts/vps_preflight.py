"""Read-only, secret-filtered VPS facts for the Rapport Auditor proxy preflight."""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import Any

Runner = Callable[..., subprocess.CompletedProcess[str]]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SENSITIVE = re.compile(r"(?i)(password|passwd|token|secret|credential|private.?key|api.?key)")
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:\bgh[pousr]_[A-Za-z0-9_]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bya29\.[A-Za-z0-9_-]{20,}\b)"
)


class _Unavailable(Exception):
    """A command failed; its stderr must never be shown to the caller."""


def _run(args: Sequence[str], runner: Runner) -> str:
    try:
        result = runner(args, capture_output=True, text=True, check=False)
    except Exception as exc:  # subprocess errors may contain private paths
        raise _Unavailable from exc
    if result.returncode != 0:
        raise _Unavailable
    return result.stdout


def _json(args: Sequence[str], runner: Runner) -> Any:
    try:
        return json.loads(_run(args, runner))
    except (json.JSONDecodeError, TypeError) as exc:
        raise _Unavailable from exc


def _safe_identifier(value: str) -> bool:
    return (
        bool(_IDENTIFIER.fullmatch(value))
        and not _SENSITIVE.search(value)
        and not _CREDENTIAL_PATTERN.search(value)
    )


def _safe_path(value: str) -> str | None:
    if not value.startswith("/") or _SENSITIVE.search(value) or _CREDENTIAL_PATTERN.search(value):
        return None
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
        return None
    if ".." in PurePosixPath(value).parts:
        return None
    return value


def _safe_address(value: str) -> str | None:
    if len(value) > 300 or _SENSITIVE.search(value) or _CREDENTIAL_PATTERN.search(value):
        return None
    match = re.fullmatch(r"(?:\[([0-9A-Fa-f:]+)\]|([A-Za-z0-9_.-]*)):(\d{1,5})(?:/(tcp|udp))?", value)
    if not match or not 1 <= int(match.group(3)) <= 65535:
        return None
    host = match.group(1) or match.group(2)
    if len(host) > 253 or _CREDENTIAL_PATTERN.search(host):
        return None
    if match.group(1):
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return None
    return value


def _safe_cidrs(value: str) -> str | None:
    try:
        return ",".join(str(ipaddress.ip_network(item.strip(), strict=False)) for item in value.split(","))
    except ValueError:
        return None


def _safe_names(value: str) -> str | None:
    if len(value) > 1024:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items or len(items) > 32:
        return None
    for item in items:
        parts = item.split("@")
        if len(parts) > 2 or any(not _safe_identifier(part) for part in parts):
            return None
    return ",".join(items)


def _safe_duration(value: str) -> str | None:
    # Keep this conservative: Go durations such as 30s or 250ms only.
    if value in {"-1", "0"} or re.fullmatch(r"(?:\d+(?:\.\d+)?(?:ns|us|µs|ms|s|m|h))+", value):
        return value
    return None


def _safe_setting(key: str, value: str) -> str | None:
    key = key.lower()
    if key == "configfile":
        return _safe_path(value)
    if key in {
        "entrypoints.websecure.forwardedheaders.insecure",
        "entrypoints.websecure.http.tls",
        "entrypoints.web.http.redirections.entrypoint.permanent",
        "providers.docker.exposedbydefault",
        "providers.docker.watch",
        "providers.docker.usebindportip",
        "providers.file.watch",
        "log",
        "accesslog",
    }:
        return value.lower() if value.lower() in {"true", "false"} else None
    if key in {"entrypoints.web.address", "entrypoints.websecure.address"}:
        return _safe_address(value)
    if key == "entrypoints.websecure.forwardedheaders.trustedips":
        return _safe_cidrs(value)
    if key in {
        "entrypoints.websecure.transport.respondingtimeouts.readtimeout",
        "entrypoints.websecure.transport.respondingtimeouts.writetimeout",
        "entrypoints.websecure.transport.respondingtimeouts.idletimeout",
    }:
        return _safe_duration(value)
    if key == "entrypoints.websecure.http.middlewares":
        return _safe_names(value)
    if key == "entrypoints.websecure.http.tls.certresolver":
        return value if _safe_identifier(value) else None
    if key == "entrypoints.web.http.redirections.entrypoint.to":
        return value if _safe_identifier(value) else None
    if key == "entrypoints.web.http.redirections.entrypoint.scheme":
        return value.lower() if value.lower() in {"http", "https"} else None
    if key in {"providers.docker.network", "providers.file.directory", "providers.file.filename"}:
        return _safe_path(value) if key.startswith("providers.file.") else (value if _safe_identifier(value) else None)
    if key == "log.level":
        return value.lower() if value.lower() in {"trace", "debug", "info", "warn", "error", "fatal", "panic"} else None
    if key in {"log.filepath", "accesslog.filepath"}:
        return _safe_path(value)
    if key == "accesslog.format":
        return value.lower() if value.lower() in {"common", "json"} else None
    if key in {"accesslog.fields.defaultmode", "accesslog.fields.headers.defaultmode"}:
        return value.lower() if value.lower() in {"keep", "drop"} else None
    return None


def _flag_pairs(arguments: Sequence[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if not item.startswith("--"):
            index += 1
            continue
        body = item[2:]
        if "=" in body:
            key, value = body.split("=", 1)
        else:
            key = body
            value = "true"
            if index + 1 < len(arguments) and not arguments[index + 1].startswith("--"):
                index += 1
                value = arguments[index]
        pairs.append((key.lower(), value))
        index += 1
    return pairs


def _summarize_arguments(arguments: Sequence[str]) -> list[str]:
    lines: list[str] = []
    resolvers: dict[str, set[str]] = {}
    for key, value in _flag_pairs(arguments):
        match = re.fullmatch(
            r"certificatesresolvers\.([a-z0-9_.-]+)\.acme\.(httpchallenge|tlschallenge|dnschallenge)(?:\.entrypoint|\.provider)?",
            key,
        )
        if match and _safe_identifier(match.group(1)):
            resolvers.setdefault(match.group(1), set()).add(match.group(2).removesuffix("challenge"))
            if match.group(2) == "httpchallenge" and key.endswith(".entrypoint") and _safe_identifier(value):
                lines.append(f"resolver={match.group(1)} challenge=http entrypoint={value}")
            continue
        if key == "configfile":
            safe_path = _safe_path(value)
            if safe_path:
                lines.append(f"static_config_file={safe_path} (contents not read; needs operator-safe inspection)")
            else:
                lines.append("static_config_file=configured (path omitted; contents not read; needs operator-safe inspection)")
            continue
        safe = _safe_setting(key, value)
        if safe is not None:
            if key == "configfile":
                lines.append(f"static_config_file={safe} (contents not read; needs operator-safe inspection)")
            else:
                lines.append(f"{key}={safe}")
    for name, challenges in sorted(resolvers.items()):
        for challenge in sorted(challenges):
            if challenge != "http":
                lines.append(f"resolver={name} challenge={challenge} configured")
    return lines


def _summarize_environment(entries: Sequence[str]) -> list[str]:
    pairs: list[str] = []
    for entry in entries:
        key, sep, value = entry.partition("=")
        if not sep or not key.startswith("TRAEFIK_"):
            continue
        normalized = key[len("TRAEFIK_") :].lower().replace("_", ".")
        if normalized == "configfile":
            safe_path = _safe_path(value)
            if safe_path:
                pairs.append(f"static_config_file={safe_path} (contents not read; needs operator-safe inspection)")
            else:
                pairs.append("static_config_file=configured (path omitted; contents not read; needs operator-safe inspection)")
            continue
        safe = _safe_setting(normalized, value)
        if safe is not None:
            if normalized == "configfile":
                pairs.append(f"static_config_file={safe} (contents not read; needs operator-safe inspection)")
            else:
                pairs.append(f"{normalized}={safe}")
            continue
        match = re.fullmatch(
            r"certificatesresolvers\.([a-z0-9_.-]+)\.acme\.(httpchallenge|tlschallenge|dnschallenge)(?:\.(entrypoint|provider))?",
            normalized,
        )
        if match and _safe_identifier(match.group(1)):
            challenge = match.group(2).removesuffix("challenge")
            if challenge == "http" and match.group(3) == "entrypoint" and _safe_identifier(value):
                pairs.append(f"resolver={match.group(1)} challenge=http entrypoint={value}")
            else:
                pairs.append(f"resolver={match.group(1)} challenge={challenge} configured")
    return pairs


def _format_pools(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["docker_default_address_pools=not reported"]
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            base = str(ipaddress.ip_network(item.get("Base", ""), strict=False))
            size = int(item.get("Size"))
        except (TypeError, ValueError):
            continue
        if 0 <= size <= 128:
            lines.append(f"docker_default_address_pool base={base} size={size}")
    return lines or ["docker_default_address_pools=not reported"]


def _format_routes(output: str, kind: str) -> list[str]:
    lines: list[str] = []
    for raw in output.splitlines():
        fields = raw.split()
        safe: list[str] = []
        if kind == "route":
            route_types = {"unicast", "local", "broadcast", "blackhole", "throw", "unreachable", "prohibit", "multicast", "nat"}
            route_type = fields[0] if fields and fields[0] in route_types else "unicast"
            start = 1 if fields and fields[0] in route_types else 0
            if len(fields) > start and (fields[start] == "default" or _valid_network(fields[start])):
                safe.append(f"type={route_type}" if route_type != "unicast" else "type=unicast")
                safe.append(f"dest={fields[start]}")
                index = start + 1
                while index + 1 < len(fields):
                    key, value = fields[index], fields[index + 1]
                    if key in {"via", "src"}:
                        try:
                            value = str(ipaddress.ip_address(value))
                        except ValueError:
                            index += 2
                            continue
                    elif key == "dev":
                        if not _safe_identifier(value):
                            index += 2
                            continue
                    elif key in {"proto", "scope", "table", "dev"}:
                        if not _safe_identifier(value):
                            index += 2
                            continue
                    elif key in {"metric", "mtu"}:
                        if not value.isdigit():
                            index += 2
                            continue
                    else:
                        index += 1
                        continue
                    safe.append(f"{key}={value}")
                    index += 2
        else:
            safe = _format_rule(fields)
        if safe:
            lines.append(f"ipv4_{kind} " + " ".join(safe))
    return lines or [f"ipv4_{kind}=none or unavailable"]


def _valid_network(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


def _format_rule(fields: Sequence[str]) -> list[str]:
    result: list[str] = []
    if fields and fields[0].endswith(":") and fields[0][:-1].isdigit():
        result.append(f"priority={fields[0][:-1]}")
        fields = fields[1:]
    index = 0
    while index < len(fields):
        key = fields[index]
        if key == "not":
            result.append("not")
            index += 1
            continue
        if index + 1 >= len(fields):
            break
        value = fields[index + 1]
        if key in {"from", "to"} and (value == "all" or _valid_network(value)):
            result.append(f"{key}={value}")
        elif key in {"lookup", "table", "iif", "oif"} and _safe_identifier(value):
            result.append(f"{key}={value}")
        elif key in {"fwmark", "uidrange", "ipproto", "sport", "dport"} and re.fullmatch(r"[A-Za-z0-9_.,:/-]+", value) and not _SENSITIVE.search(value):
            result.append(f"{key}={value}")
        index += 2
    return result


def _safe_networks(runner: Runner, errors: list[str]) -> list[str]:
    try:
        ids = _run(["docker", "network", "ls", "-q"], runner).split()
    except _Unavailable:
        return ["docker_networks=unavailable (details withheld)"]
    lines: list[str] = []
    for network_id in ids:
        if not re.fullmatch(r"[0-9a-f]{12,64}", network_id):
            continue
        try:
            items = _json(["docker", "network", "inspect", network_id], runner)
        except _Unavailable:
            errors.append("docker_network_inspect_failed (details withheld)")
            continue
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            continue
        network = items[0]
        name = network.get("Name")
        name = name if isinstance(name, str) and _safe_identifier(name) else "(name omitted)"
        internal = network.get("Internal")
        internal_text = str(internal).lower() if isinstance(internal, bool) else "unknown"
        subnets = []
        ipam = network.get("IPAM")
        configs = ipam.get("Config", []) if isinstance(ipam, dict) else []
        for config in configs if isinstance(configs, list) else []:
            if isinstance(config, dict) and isinstance(config.get("Subnet"), str) and _valid_network(config["Subnet"]):
                subnets.append(str(ipaddress.ip_network(config["Subnet"], strict=False)))
        lines.append(f"docker_network name={name} internal={internal_text} subnets={','.join(subnets) or 'none'}")
    return lines or ["docker_networks=none or unavailable"]


def collect_report(runner: Runner = subprocess.run) -> str:
    lines = ["VPS preflight (read-only; only allowlisted fields are shown):"]
    errors: list[str] = []
    try:
        items = _json(["docker", "inspect", "traefik"], runner)
    except _Unavailable:
        items = None
    if isinstance(items, list) and items and isinstance(items[0], dict):
        container = items[0]
        config = container.get("Config", {})
        if not isinstance(config, dict):
            config = {}
        image_id = container.get("Image", "")
        image_ref = config.get("Image", "")
        lines.append(f"traefik_image_ref={image_ref if _safe_image_ref(image_ref) else 'omitted'}")
        lines.append(f"traefik_image_id={image_id if re.fullmatch(r'sha256:[0-9a-f]{64}', str(image_id)) else 'omitted'}")
        try:
            image_items = _json(["docker", "image", "inspect", image_id], runner)
        except _Unavailable:
            image_items = None
        digests = []
        if isinstance(image_items, list) and image_items and isinstance(image_items[0], dict):
            repo_digests = image_items[0].get("RepoDigests", [])
            if isinstance(repo_digests, list):
                digests = [
                    item
                    for item in repo_digests
                    if isinstance(item, str)
                    and re.fullmatch(r"[A-Za-z0-9._:/-]+@sha256:[0-9a-f]{64}", item)
                    and not _SENSITIVE.search(item)
                    and not _CREDENTIAL_PATTERN.search(item)
                ]
        lines.append(f"traefik_repo_digests={','.join(digests) or 'none reported'}")
        argument_summaries = _summarize_arguments(
            config.get("Entrypoint", []) if isinstance(config.get("Entrypoint"), list) else []
        ) + _summarize_arguments(config.get("Cmd", []) if isinstance(config.get("Cmd"), list) else [])
        lines.extend(argument_summaries)
        env = config.get("Env", [])
        environment_summaries: list[str] = []
        if isinstance(env, list):
            environment_summaries = _summarize_environment([item for item in env if isinstance(item, str)])
            lines.extend(environment_summaries)
        if not any(line.startswith("static_config_file=") for line in argument_summaries + environment_summaries):
            lines.append("static_config_file=not specified by selected CLI/environment flags")
        networks = container.get("NetworkSettings", {}).get("Networks", {})
        if isinstance(networks, dict):
            for name, details in sorted(networks.items()):
                if not _safe_identifier(name) or not isinstance(details, dict):
                    continue
                address = details.get("IPAddress", "")
                try:
                    address = str(ipaddress.ip_address(address)) if address else "none"
                except ValueError:
                    address = "omitted"
                lines.append(f"traefik_network name={name} ipv4={address}")
    else:
        lines.append("traefik_container=unavailable (details withheld)")

    try:
        pool_output = _run(["docker", "info", "--format", "{{json .DefaultAddressPools}}"], runner)
        lines.extend(_format_pools(json.loads(pool_output)))
    except (json.JSONDecodeError, _Unavailable):
        lines.append("docker_default_address_pools=unavailable (details withheld)")
    lines.extend(_safe_networks(runner, errors))
    commands = {
        "rule": ["ip", "-4", "rule", "show"],
        "route": ["ip", "-4", "route", "show", "table", "all"],
    }
    for kind, command in commands.items():
        try:
            output = _run(command, runner)
            lines.extend(_format_routes(output, kind))
        except _Unavailable:
            lines.append(f"ipv4_{kind}=unavailable (details withheld)")
    lines.extend(errors)
    return "\n".join(lines) + "\n"


def _safe_image_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*(?::[A-Za-z0-9._-]+)?", value)
    ) and not _SENSITIVE.search(value) and not _CREDENTIAL_PATTERN.search(value)


def main() -> int:
    print(collect_report(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
