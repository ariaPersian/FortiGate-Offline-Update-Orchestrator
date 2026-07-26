from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .agent_config import AgentConfig, DeviceConfig
from .agent_state import utc_now
from .controlled_apply import FortiGateApplySession
from .fortigate_preflight import PreflightResult, run_read_only_preflight
from .inventory import sha256_file
from .tftp_service import TemporaryTftpServer, wait_for_uploaded_file


@dataclass(frozen=True)
class BackupTestResult:
    status: str
    backup_path: str
    backup_sha256: str
    backup_size: int
    report_json: str
    report_text: str
    preflight_evidence: str
    command_output_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "backup_path": self.backup_path,
            "backup_sha256": self.backup_sha256,
            "backup_size": self.backup_size,
            "report_json": self.report_json,
            "report_text": self.report_text,
            "preflight_evidence": self.preflight_evidence,
            "command_output_sha256": self.command_output_sha256,
            "device_changes_performed": False,
            "package_restores_performed": 0,
        }


PreflightRunner = Callable[[AgentConfig], PreflightResult]
SessionFactory = Callable[[DeviceConfig], FortiGateApplySession]
TftpFactory = Callable[..., TemporaryTftpServer]
UploadWaiter = Callable[..., Path]


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _safe_hostname(value: str | None) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "fortigate").strip())
    normalized = normalized.strip(".-_")
    return normalized[:80] or "fortigate"


def _report_paths(config: AgentConfig, stamp: str, hostname: str) -> tuple[Path, Path]:
    base = config.storage.reports / f"{stamp}-{hostname}-backup-test"
    return base.with_suffix(".json"), base.with_suffix(".txt")


def run_backup_test(
    config: AgentConfig,
    *,
    preflight_runner: PreflightRunner = run_read_only_preflight,
    session_factory: SessionFactory = FortiGateApplySession,
    tftp_factory: TftpFactory = TemporaryTftpServer,
    upload_waiter: UploadWaiter = wait_for_uploaded_file,
) -> BackupTestResult:
    """Export one encrypted full configuration backup without restoring packages."""

    if config.device is None or config.apply is None:
        raise ValueError("device and apply configuration blocks are required for backup-test.")

    backup_password = os.environ.get(config.apply.backup_password_env)
    if not backup_password:
        raise ValueError(
            f"Backup password environment variable is not set: {config.apply.backup_password_env}"
        )

    config.storage.create_directories()
    preflight = preflight_runner(config)
    if preflight.status != "PASS":
        raise RuntimeError("Read-only preflight did not pass; backup-test aborted.")

    stamp = _utc_stamp()
    hostname = _safe_hostname(preflight.system_status.hostname)
    backup_filename = f"{hostname}-{stamp}-full.conf"
    run_root = config.storage.tftp_dir / f"backup-test-{stamp}-{time.time_ns()}"
    uploaded_path = run_root / backup_filename

    backup_store = config.storage.evidence_dir / "backups"
    backup_store.mkdir(parents=True, exist_ok=True)
    permanent_backup = backup_store / backup_filename
    if permanent_backup.exists():
        raise FileExistsError(f"Backup destination already exists: {permanent_backup}")

    command_output = ""
    server = tftp_factory(
        run_root,
        bind_address=config.apply.tftp_bind_address,
        port=config.apply.tftp_port,
        allowed_upload_name=backup_filename,
    )
    with server:
        with session_factory(config.device) as session:
            command_output = session.run_backup(
                filename=backup_filename,
                tftp_address=config.apply.tftp_advertise_address,
                backup_password=backup_password,
            )
            if "command fail" in command_output.lower():
                raise RuntimeError("FortiGate rejected the encrypted full configuration backup.")
            uploaded_path = upload_waiter(
                uploaded_path,
                timeout_seconds=config.device.command_timeout_seconds,
            )

    shutil.copy2(uploaded_path, permanent_backup)
    uploaded_sha256 = sha256_file(uploaded_path)
    permanent_sha256 = sha256_file(permanent_backup)
    if permanent_sha256 != uploaded_sha256:
        raise RuntimeError("Permanent backup copy failed SHA-256 verification.")

    backup_size = permanent_backup.stat().st_size
    if backup_size <= 0:
        raise RuntimeError("FortiGate backup file is empty.")

    report_json, report_text = _report_paths(config, stamp, hostname)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    command_hash = hashlib.sha256(command_output.encode("utf-8")).hexdigest()
    report = {
        "schema_version": 1,
        "captured_at": utc_now(),
        "status": "PASS",
        "target": {
            "host": config.device.host,
            "port": config.device.port,
            "hostname": preflight.system_status.hostname,
            "model": preflight.system_status.model,
            "firmware_version": preflight.system_status.firmware_version,
            "build": preflight.system_status.build,
            "host_key_sha256": preflight.host_key.sha256,
        },
        "preflight_evidence": preflight.evidence_json,
        "tftp": {
            "bind_address": config.apply.tftp_bind_address,
            "advertise_address": config.apply.tftp_advertise_address,
            "port": config.apply.tftp_port,
            "temporary_root": str(run_root),
            "upload_allowlist": [backup_filename],
        },
        "backup": {
            "path": str(permanent_backup),
            "filename": backup_filename,
            "sha256": permanent_sha256,
            "size": backup_size,
            "encryption_requested": True,
            "password_environment_variable": config.apply.backup_password_env,
        },
        "backup_command": {
            "sha256": command_hash,
            "output": command_output,
        },
        "device_changes_performed": False,
        "package_restores_performed": 0,
    }
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_text.write_text(
        "\n".join(
            (
                "FGOps encrypted full-config backup test: PASS",
                f"Captured: {report['captured_at']}",
                f"Target: {config.device.host}:{config.device.port}",
                f"Hostname: {preflight.system_status.hostname}",
                f"Backup: {permanent_backup}",
                f"Size: {backup_size}",
                f"SHA-256: {permanent_sha256}",
                "Encryption requested: yes",
                "Device changes performed: no",
                "Package restores performed: 0",
                "",
                "===== FORTIGATE COMMAND OUTPUT =====",
                command_output,
                "",
            )
        ),
        encoding="utf-8",
    )

    shutil.rmtree(run_root, ignore_errors=False)

    return BackupTestResult(
        status="PASS",
        backup_path=str(permanent_backup),
        backup_sha256=permanent_sha256,
        backup_size=backup_size,
        report_json=str(report_json),
        report_text=str(report_text),
        preflight_evidence=preflight.evidence_json,
        command_output_sha256=command_hash,
    )
