from __future__ import annotations

import os
import re
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / "deployment" / ".env.traefik"
IMMUTABLE_VALUES = {
    "RAPPORT_AUDITOR_PUBLIC_DOMAIN": "rapport.chames.tn",
    "RAPPORT_AUDITOR_INGRESS_NETWORK": "rapport-auditor-ingress",
    "RAPPORT_AUDITOR_TRUSTED_PROXY": "172.27.0.2",
    "RAPPORT_AUDITOR_SECRET_FILE": "./secrets/rapport_secret_key",
}
PROFILE_KEYS = (
    "RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS",
    "RAPPORT_AUDITOR_APP_MEMORY_LIMIT",
    "RAPPORT_AUDITOR_APP_CPU_LIMIT",
)
APPROVED_PROFILES = {
    ("1", "1g", "1.0"),
    ("2", "2g", "2.0"),
}
LOW_PROFILE = ("1", "1g", "1.0")
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    if os.name == "posix":
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
    return info.st_dev, info.st_ino, info.st_size


def _read_private_env(path: Path) -> tuple[bytes, dict[str, str], tuple[int, ...]]:
    parent_info = path.parent.lstat()
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise ValueError("The deployment env directory must be a real directory.")
    try:
        before = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("The private deployment env file does not exist.") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("The deployment env path must be a regular file, not a symlink.")
    if os.name == "posix" and stat.S_IMODE(before.st_mode) & 0o077:
        raise ValueError("The deployment env file must be private (owner-only permissions).")
    if os.name == "posix" and hasattr(os, "geteuid") and before.st_uid != os.geteuid():
        raise ValueError("Run this profile command as the deployment env file owner, without sudo.")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        identity = _file_identity(opened)
        if not stat.S_ISREG(opened.st_mode) or identity != _file_identity(before):
            raise ValueError("The deployment env file changed while it was being read.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            original = stream.read()
        if _file_identity(os.fstat(descriptor)) != identity:
            raise ValueError("The deployment env file changed while it was being read.")
    finally:
        os.close(descriptor)

    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("The deployment env file is not valid UTF-8.") from exc

    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not _KEY_RE.fullmatch(key) or key in values:
            raise ValueError("The deployment env file is malformed or has duplicate keys.")
        value = raw_value.strip()
        if value.startswith(("'", '"')) or value.endswith(("'", '"')):
            if len(value) < 2 or value[0] != value[-1] or value[0] not in {"'", '"'}:
                raise ValueError("The deployment env file contains malformed quoting.")
            value = value[1:-1]
        values[key] = value

    required = set(IMMUTABLE_VALUES) | set(PROFILE_KEYS)
    if not required.issubset(values):
        raise ValueError("The deployment env file is missing required co-hosting settings.")
    if any(values[key] != value for key, value in IMMUTABLE_VALUES.items()):
        raise ValueError("The deployment env file does not match the reviewed Rapport host settings.")
    profile = tuple(values[key] for key in PROFILE_KEYS)
    if profile not in APPROVED_PROFILES:
        raise ValueError("The deployment env file uses an unreviewed resource profile.")
    return original, values, identity


def apply_low_profile(path: Path) -> bool:
    """Atomically select the reviewed low profile without deploying services."""
    original, values, identity = _read_private_env(path)
    if tuple(values[key] for key in PROFILE_KEYS) == LOW_PROFILE:
        return False

    text = original.decode("utf-8")
    replacements = dict(zip(PROFILE_KEYS, LOW_PROFILE, strict=True))
    updated_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if body.strip() and not body.lstrip().startswith("#"):
            key, _separator, _value = body.partition("=")
            normalized_key = key.strip()
            if normalized_key in replacements:
                prefix = body[: body.index("=") + 1]
                updated_lines.append(f"{prefix}{replacements[normalized_key]}{ending}")
                continue
        updated_lines.append(line)
    updated = "".join(updated_lines).encode("utf-8")

    path = Path(path)
    parent = path.parent
    parent_stat = parent.lstat()
    parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
    token = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = parent / f".env.traefik.backup-{timestamp}-{token[:8]}"
    temp = parent / f".env.traefik.tmp-{token}"
    create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)

    backup_fd = os.open(backup, create_flags, 0o600)
    try:
        with os.fdopen(backup_fd, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())

        temp_fd = os.open(temp, create_flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(temp_fd, "wb") as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise

        current = path.lstat()
        current_parent = parent.lstat()
        if (
            stat.S_ISLNK(current_parent.st_mode)
            or not stat.S_ISDIR(current_parent.st_mode)
            or (current_parent.st_dev, current_parent.st_ino) != parent_identity
            or stat.S_ISLNK(current.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or _file_identity(current) != identity
            or (os.name == "posix" and stat.S_IMODE(current.st_mode) & 0o077)
        ):
            raise ValueError("The deployment env path changed before the update.")
        os.replace(temp, path)
        try:
            directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    # The atomic replace has already succeeded; keep the CLI
                    # result consistent with the file state if dir fsync is unsupported.
                    pass
            finally:
                os.close(directory_fd)
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise
    return True


def main() -> int:
    try:
        changed = apply_low_profile(ENV_FILE)
    except (OSError, ValueError):
        print("Could not safely select the low resource profile; no services were changed.", file=sys.stderr)
        return 1
    if changed:
        print("Low resource profile selected; a private backup was created. No services were changed.")
    else:
        print("Low resource profile is already selected. No services were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
