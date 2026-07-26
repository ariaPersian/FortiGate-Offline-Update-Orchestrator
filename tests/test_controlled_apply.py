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
from fgops.agent_state import AgentState, save_state
from fgops.controlled_apply import classify_package_result, run_controlled_apply
from fgops.fortigate_preflight import HostKeyInfo, PreflightResult, SystemStatus
from fgops.inventory import sha256_file
from fgops.models import UpdateStatus
from fgops.tftp_service import stage_tftp_files


def _versions(value: str) -> dict[str, dict[str, str]]:
    return {"Virus Definitions": {"Version": value}}


def test_classifies_version_increase() -> None:
    result = classify_package_result(
        kind="AV",
        filename="av.pkg",
        expected_objects=("Virus Definitions",),
        before=_versions("1.00000"),
        after=_versions("2.00000"),
        command_output="Get antivirus database from tftp server OK.",
        prevent_downgrade=True,
    )
    assert result.status is UpdateStatus.SUCCESS


def test_classifies_version_increase_with_return_code_as_warning() -> None:
    result = classify_package_result(
        kind="FFDB",
        filename="ffdb.pkg",
        expected_objects=("Virus Definitions",),
        before=_versions("1.00000"),
        after=_versions("2.00000"),
        command_output="Command fail. Return code 49",
        prevent_downgrade=True,
    )
    assert result.status is UpdateStatus.SUCCESS_WITH_WARNING
    assert result.return_code == 49


def test_classifies_no_update() -> None:
    result = classify_package_result(
        kind="ISDB",
        filename="isdb.pkg",
        expected_objects=("Virus Definitions",),
        before=_versions("1.00000"),
        after=_versions("1.00000"),
        command_output="Updating misc objects\nNo updates\nCommand fail. Return code -85",
        prevent_downgrade=True,
    )
    assert result.status is UpdateStatus.SKIPPED_NO_UPDATE


def test_blocks_version_decrease() -> None:
    result = classify_package_result(
        kind="AV",
        filename="av.pkg",
        expected_objects=("Virus Definitions",),
        before=_versions("2.00000"),
        after=_versions("1.00000"),
        command_output="OK",
        prevent_downgrade=True,
    )
    assert result.status is UpdateStatus.FAILED


def test_apply_config_requires_standard_tftp_port() -> None:
    with pytest.raises(ValueError, match="must be 69"):
        ApplyConfig(
            tftp_bind_address="127.0.0.1",
            tftp_advertise_address="127.0.0.1",
            tftp_port=1069,
        ).validate()


def test_stage_tftp_files_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsafe"):
        stage_tftp_files(tmp_path, tmp_path / "out", ["../av.pkg"])


class _NoopTftp:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _FakeSession:
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

    def run_restore(self, *, family: str, filename: str, tftp_address: str) -> str:
        assert family == "av"
        assert filename == "cyberlogic.ir-AV.pkg"
        assert tftp_address == "127.0.0.1"
        return "Get antivirus database from tftp server OK."

    def run_command(self, command: str) -> str:
        assert command == "diagnose autoupdate versions"
        return (
            "diagnose autoupdate versions\n"
            "Virus Definitions\n---------\nVersion: 2.00000\n\n"
            "FG (global) #\n"
        )


def _preflight(tmp_path: Path, version: str) -> PreflightResult:
    return PreflightResult(
        status="PASS",
        evidence_json=str(tmp_path / f"{version}.json"),
        evidence_text=str(tmp_path / f"{version}.txt"),
        host_key=HostKeyInfo(
            host="127.0.0.1",
            port=22,
            key_type="ssh-ed25519",
            bits=256,
            sha256="SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        ),
        system_status=SystemStatus(
            hostname="FG",
            model="FortiGate-300D",
            firmware_version="6.4.16",
            build=2098,
            serial_number="SERIAL",
            operation_mode="NAT",
            current_vdom="root",
            vdom_configuration="multiple",
            ha_mode="standalone",
        ),
        autoupdate_versions=_versions(version),
        validation_errors=(),
        command_errors=(),
    )


def test_controlled_apply_requires_exact_approval_and_persists_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_map = tmp_path / "package-map.yml"
    package_map.write_text("packages: []\n", encoding="utf-8")
    work_dir = tmp_path / "quarantine" / "bundle"
    packages_dir = work_dir / "packages"
    packages_dir.mkdir(parents=True)
    package = packages_dir / "cyberlogic.ir-AV.pkg"
    package.write_bytes(b"package")
    archive_hash = "a" * 64
    manifest_id = "FGOPS-TEST000000000001"
    manifest = {
        "schema_version": 1,
        "manifest_id": manifest_id,
        "source_archive": "bundle.zip",
        "source_archive_sha256": archive_hash,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "packages": [
            {
                "filename": package.name,
                "size": package.stat().st_size,
                "sha256": sha256_file(package),
                "kind": "AV",
                "restore_family": "av",
                "expected_objects": ["Virus Definitions"],
                "safe_for_deferred_apply": True,
            }
        ],
        "warnings": [],
    }
    (work_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    storage = StorageConfig(
        root=tmp_path,
        incoming=tmp_path / "incoming",
        quarantine=tmp_path / "quarantine",
        reports=tmp_path / "reports",
        state_file=tmp_path / "state.json",
        evidence=tmp_path / "evidence",
        tftp=tmp_path / "tftp",
    )
    save_state(
        storage.state_file,
        AgentState(
            archives={
                archive_hash: {
                    "status": "PREPARED",
                    "manifest_id": manifest_id,
                    "work_dir": str(work_dir),
                }
            }
        ),
    )
    config = AgentConfig(
        config_path=tmp_path / "config.yml",
        package_map=package_map,
        source=SourceConfig("https://example.test", "x"),
        storage=storage,
        execution=ExecutionConfig(mode="approval", enabled_packages=("AV",)),
        device=DeviceConfig(
            host="127.0.0.1",
            username="admin",
            host_key_sha256="SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        ),
        apply=ApplyConfig(
            tftp_bind_address="127.0.0.1",
            tftp_advertise_address="127.0.0.1",
            settle_seconds=0,
            package_order=("AV",),
        ),
    )
    monkeypatch.setenv("FGOPS_SSH_PASSWORD", "ssh-secret")
    monkeypatch.setenv("FGOPS_BACKUP_PASSWORD", "backup-secret")

    with pytest.raises(ValueError, match="exactly match"):
        run_controlled_apply(config, manifest_id=manifest_id, approval_manifest=None)

    calls = iter((_preflight(tmp_path, "1.00000"), _preflight(tmp_path, "2.00000")))

    def fake_preflight(_config: AgentConfig) -> PreflightResult:
        return next(calls)

    def fake_tftp(*args, **kwargs):
        return _NoopTftp()

    def fake_wait(path: Path, *, timeout_seconds: int, stable_seconds: float = 0.5) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"encrypted-backup")
        return path

    monkeypatch.setattr("fgops.controlled_apply.wait_for_uploaded_file", fake_wait)
    result = run_controlled_apply(
        config,
        manifest_id=manifest_id,
        approval_manifest=manifest_id,
        preflight_runner=fake_preflight,
        session_factory=_FakeSession,
        tftp_factory=fake_tftp,
        sleep_fn=lambda _seconds: None,
    )
    assert result.status == "SUCCESS"
    assert result.package_results[0].status is UpdateStatus.SUCCESS
    assert result.backup_path is not None
    assert Path(result.backup_path).is_file()
