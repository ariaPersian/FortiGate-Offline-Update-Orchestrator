from __future__ import annotations

import json
from pathlib import Path

import pytest

from fgops.agent_config import (
    AgentConfig,
    ApplyConfig,
    DeviceConfig,
    ExecutionConfig,
    SourceConfig,
    StorageConfig,
)
from fgops.backup_test import run_backup_test
from fgops.fortigate_preflight import HostKeyInfo, PreflightResult, SystemStatus
from fgops.inventory import sha256_file


class _NoopTftp:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _BackupOnlySession:
    restore_called = False

    def __init__(self, _config: DeviceConfig) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run_backup(self, *, filename: str, tftp_address: str, backup_password: str) -> str:
        assert filename.endswith("-full.conf")
        assert tftp_address == "127.0.0.1"
        assert backup_password == "backup-secret"
        return "Send config file to tftp server OK."

    def run_restore(self, **_kwargs):
        type(self).restore_called = True
        raise AssertionError("backup-test must not restore a package")


def _config(tmp_path: Path) -> AgentConfig:
    package_map = tmp_path / "package-map.yml"
    package_map.write_text("packages: []\n", encoding="utf-8")
    return AgentConfig(
        config_path=tmp_path / "config.yml",
        package_map=package_map,
        source=SourceConfig("https://example.test", "x"),
        storage=StorageConfig(
            root=tmp_path,
            incoming=tmp_path / "incoming",
            quarantine=tmp_path / "quarantine",
            reports=tmp_path / "reports",
            state_file=tmp_path / "state.json",
            evidence=tmp_path / "evidence",
            tftp=tmp_path / "tftp",
        ),
        execution=ExecutionConfig(mode="approval"),
        device=DeviceConfig(
            host="127.0.0.1",
            username="admin",
            host_key_sha256="SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        ),
        apply=ApplyConfig(
            tftp_bind_address="127.0.0.1",
            tftp_advertise_address="127.0.0.1",
        ),
    )


def _preflight(tmp_path: Path, *, status: str = "PASS") -> PreflightResult:
    return PreflightResult(
        status=status,
        evidence_json=str(tmp_path / "preflight.json"),
        evidence_text=str(tmp_path / "preflight.txt"),
        host_key=HostKeyInfo(
            host="127.0.0.1",
            port=22,
            key_type="ssh-ed25519",
            bits=256,
            sha256="SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        ),
        system_status=SystemStatus(
            hostname="SITEC-FW-02",
            model="FortiGate-300D",
            firmware_version="6.4.16",
            build=2098,
            serial_number="SERIAL",
            operation_mode="NAT",
            current_vdom="Management",
            vdom_configuration="multiple",
            ha_mode="standalone",
        ),
        autoupdate_versions={"Virus Definitions": {"Version": "93.07607"}},
        validation_errors=() if status == "PASS" else ("validation failed",),
        command_errors=(),
    )


def test_backup_test_requires_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FGOPS_BACKUP_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="FGOPS_BACKUP_PASSWORD"):
        run_backup_test(_config(tmp_path))


def test_backup_test_aborts_when_preflight_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FGOPS_BACKUP_PASSWORD", "backup-secret")
    with pytest.raises(RuntimeError, match="preflight"):
        run_backup_test(
            _config(tmp_path),
            preflight_runner=lambda _config: _preflight(tmp_path, status="FAILED_VALIDATION"),
        )


def test_backup_test_persists_verified_backup_without_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    monkeypatch.setenv("FGOPS_BACKUP_PASSWORD", "backup-secret")
    _BackupOnlySession.restore_called = False

    def fake_tftp(*_args, **_kwargs):
        return _NoopTftp()

    def fake_wait(path: Path, *, timeout_seconds: int, stable_seconds: float = 0.5) -> Path:
        assert timeout_seconds == config.device.command_timeout_seconds
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"encrypted-full-config-backup")
        return path

    result = run_backup_test(
        config,
        preflight_runner=lambda _config: _preflight(tmp_path),
        session_factory=_BackupOnlySession,
        tftp_factory=fake_tftp,
        upload_waiter=fake_wait,
    )

    backup = Path(result.backup_path)
    assert result.status == "PASS"
    assert backup.is_file()
    assert result.backup_sha256 == sha256_file(backup)
    assert result.backup_size == backup.stat().st_size
    assert _BackupOnlySession.restore_called is False
    assert not any(config.storage.tftp_dir.iterdir())

    report = json.loads(Path(result.report_json).read_text(encoding="utf-8"))
    assert report["backup"]["encryption_requested"] is True
    assert report["device_changes_performed"] is False
    assert report["package_restores_performed"] == 0
    assert "backup-secret" not in Path(result.report_json).read_text(encoding="utf-8")
    assert "backup-secret" not in Path(result.report_text).read_text(encoding="utf-8")
