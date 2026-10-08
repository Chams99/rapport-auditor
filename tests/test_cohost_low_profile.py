from __future__ import annotations

import importlib.util
import os
import re
import stat
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "set_cohost_low_profile.py"
SPEC = importlib.util.spec_from_file_location("set_cohost_low_profile", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
profile_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile_module)


def _private_env(path: Path, profile: tuple[str, str, str] = ("2", "2g", "2.0")) -> bytes:
    text = "\n".join(
        (
            "# Synthetic test configuration",
            "RAPPORT_AUDITOR_PUBLIC_DOMAIN=rapport.chames.tn",
            "RAPPORT_AUDITOR_INGRESS_NETWORK=rapport-auditor-ingress",
            "RAPPORT_AUDITOR_TRUSTED_PROXY=172.27.0.2",
            "RAPPORT_AUDITOR_SECRET_FILE=./secrets/rapport_secret_key",
            f"RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS={profile[0]}",
            f"RAPPORT_AUDITOR_APP_MEMORY_LIMIT={profile[1]}",
            f"RAPPORT_AUDITOR_APP_CPU_LIMIT={profile[2]}",
            "SYNTHETIC_SECRET=must-not-be-printed",
            "",
        )
    ).encode("utf-8")
    path.write_bytes(text)
    path.chmod(0o600)
    return text


def test_low_profile_update_preserves_other_values_and_creates_private_backup(tmp_path: Path):
    env_file = tmp_path / ".env.traefik"
    original = _private_env(env_file)

    changed = profile_module.apply_low_profile(env_file)

    updated = env_file.read_bytes()
    backup_files = list(tmp_path.glob(".env.traefik.backup-*"))
    assert changed
    assert b"RAPPORT_AUDITOR_PUBLIC_DOMAIN=rapport.chames.tn" in updated
    assert b"RAPPORT_AUDITOR_INGRESS_NETWORK=rapport-auditor-ingress" in updated
    assert b"RAPPORT_AUDITOR_TRUSTED_PROXY=172.27.0.2" in updated
    assert b"RAPPORT_AUDITOR_SECRET_FILE=./secrets/rapport_secret_key" in updated
    assert b"RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS=1" in updated
    assert b"RAPPORT_AUDITOR_APP_MEMORY_LIMIT=1g" in updated
    assert b"RAPPORT_AUDITOR_APP_CPU_LIMIT=1.0" in updated
    assert b"SYNTHETIC_SECRET=must-not-be-printed" in updated
    assert len(backup_files) == 1
    assert backup_files[0].read_bytes() == original
    if os.name == "posix":
        assert stat.S_IMODE(backup_files[0].stat().st_mode) == 0o600
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_low_profile_update_is_idempotent_and_does_not_create_another_backup(tmp_path: Path):
    env_file = tmp_path / ".env.traefik"
    _private_env(env_file, profile=("1", "1g", "1.0"))
    before = env_file.read_bytes()

    assert not profile_module.apply_low_profile(env_file)
    assert env_file.read_bytes() == before
    assert list(tmp_path.glob(".env.traefik.backup-*")) == []


def test_low_profile_failed_atomic_replace_keeps_original_and_private_backup(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env.traefik"
    original = _private_env(env_file)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("synthetic atomic replace failure")

    monkeypatch.setattr(profile_module.os, "replace", fail_replace)
    with pytest.raises(OSError):
        profile_module.apply_low_profile(env_file)

    backup_files = list(tmp_path.glob(".env.traefik.backup-*"))
    assert env_file.read_bytes() == original
    assert len(backup_files) == 1
    assert backup_files[0].read_bytes() == original
    assert list(tmp_path.glob(".env.traefik.tmp-*")) == []
    if os.name == "posix":
        assert stat.S_IMODE(backup_files[0].stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("profile", "extra_line"),
    [
        (("3", "3g", "3.0"), None),
        (("2", "1g", "1.0"), None),
        (("2", "2g", "2.0"), "RAPPORT_AUDITOR_APP_CPU_LIMIT=1.0"),
        (("2", "2g", "2.0"), "not-an-env-setting"),
    ],
)
def test_low_profile_refuses_unreviewed_or_malformed_env_without_changes(
    tmp_path: Path,
    profile: tuple[str, str, str],
    extra_line: str | None,
):
    env_file = tmp_path / ".env.traefik"
    original = _private_env(env_file, profile)
    if extra_line:
        env_file.write_bytes(original + extra_line.encode("utf-8") + b"\n")
    before = env_file.read_bytes()

    with pytest.raises(ValueError):
        profile_module.apply_low_profile(env_file)

    assert env_file.read_bytes() == before
    assert list(tmp_path.glob(".env.traefik.backup-*")) == []


def test_low_profile_refuses_symlinked_env_path(tmp_path: Path):
    target = tmp_path / "real.env"
    _private_env(target)
    link = tmp_path / ".env.traefik"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this host.")

    with pytest.raises(ValueError):
        profile_module.apply_low_profile(link)

    assert target.read_bytes().startswith(b"# Synthetic test configuration")
    assert list(tmp_path.glob(".env.traefik.backup-*")) == []


def test_low_profile_refuses_symlinked_env_directory(tmp_path: Path):
    real_directory = tmp_path / "real-deployment"
    real_directory.mkdir()
    target = real_directory / ".env.traefik"
    original = _private_env(target)
    directory_link = tmp_path / "deployment-link"
    try:
        directory_link.symlink_to(real_directory, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlink creation is unavailable on this host.")

    with pytest.raises(ValueError):
        profile_module.apply_low_profile(directory_link / ".env.traefik")

    assert target.read_bytes() == original
    assert list(real_directory.glob(".env.traefik.backup-*")) == []


def test_low_profile_refuses_changed_domain_without_rewriting_or_backup(tmp_path: Path):
    env_file = tmp_path / ".env.traefik"
    original = _private_env(env_file)
    env_file.write_bytes(original.replace(b"rapport.chames.tn", b"attacker.invalid"))
    before = env_file.read_bytes()

    with pytest.raises(ValueError):
        profile_module.apply_low_profile(env_file)

    assert env_file.read_bytes() == before
    assert list(tmp_path.glob(".env.traefik.backup-*")) == []


def test_cli_output_never_echoes_private_env_values(tmp_path: Path, monkeypatch, capsys):
    env_file = tmp_path / ".env.traefik"
    _private_env(env_file)
    monkeypatch.setattr(profile_module, "ENV_FILE", env_file)

    assert profile_module.main() == 0
    captured = capsys.readouterr()
    assert "must-not-be-printed" not in captured.out + captured.err
    assert "rapport.chames.tn" not in captured.out + captured.err
    assert "private backup" in captured.out


def test_shared_vps_app_profile_sets_matching_memory_and_swap_caps():
    compose = (SCRIPT.parents[1] / "deployment" / "compose.traefik.yaml").read_text(encoding="utf-8")
    example = (SCRIPT.parents[1] / "deployment" / ".env.traefik.example").read_text(encoding="utf-8")

    assert 'RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS=1' in example
    assert 'RAPPORT_AUDITOR_APP_MEMORY_LIMIT=1g' in example
    assert 'RAPPORT_AUDITOR_APP_CPU_LIMIT=1.0' in example
    assert 'RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS: "${RAPPORT_AUDITOR_ANALYSIS_MAX_WORKERS:-1}"' in compose
    app_caps = re.search(
        r"(?m)^    mem_limit: (\$\{RAPPORT_AUDITOR_APP_MEMORY_LIMIT[^\n]+\})\n"
        r"    memswap_limit: (\$\{RAPPORT_AUDITOR_APP_MEMORY_LIMIT[^\n]+\})$",
        compose,
    )
    assert app_caps is not None and app_caps.group(1) == app_caps.group(2)
