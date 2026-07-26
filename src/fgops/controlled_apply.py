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
from .agent_state import load_state, save_state, utc_now
from .fortigate_preflight import (
    FortiGateReadOnlySession,
    PreflightResult,
    _clean_terminal,
    _last_prompt,
    _strip_command_envelope,
    parse_autoupdate_versions,
    run_read_only_preflight,
)
from .inventory import sha256_file
from .models import UpdateStatus
from .tftp_service import TemporaryTftpServer, stage_tftp_files, wait_for_uploaded_file

_CONFIRM_RE = re.compile(r"Do you want to continue\?\s*\(y/n\)", re.I)
_RETURN_CODE_RE = re.compile(r"Return code\s+(-?\d+)", re.I)
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
_DENY_PATTERNS = (
    "invalid signature",
    "signature invalid",
    "no signature for validation",
    "wrong firmware version",
    "pkg has wrong firmware version",
    "downgrade",
)
_ALLOWED_FAMILIES = {"av", "ips", "other-objects"}


@dataclass(frozen=True)
class ObjectDelta:
    name: str
    before_version: str | None
    after_version: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "before_version": self.before_version,
            "after_version": self.after_version,
        }


@dataclass(frozen=True)
class PackageApplyResult:
    kind: str
    filename: str
    status: UpdateStatus
    reason: str
    return_code: int | None
    objects: tuple[ObjectDelta, ...]
    command_output_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "filename": self.filename,
            "status": self.status.value,
            "reason": self.reason,
            "return_code": self.return_code,
            "objects": [item.to_dict() for item in self.objects],
            "command_output_sha256": self.command_output_sha256,
        }


@dataclass(frozen=True)
class ControlledApplyResult:
    status: str
    manifest_id: str
    archive_sha256: str
    report_json: str
    report_text: str
    backup_path: str | None
    package_results: tuple[PackageApplyResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "manifest_id": self.manifest_id,
            "archive_sha256": self.archive_sha256,
            "report_json": self.report_json,
            "report_text": self.report_text,
            "backup_path": self.backup_path,
            "package_results": [item.to_dict() for item in self.package_results],
        }


class FortiGateApplySession(FortiGateReadOnlySession):
    """Pinned SSH session with a very small controlled write allowlist."""

    def _run_interactive(self, command: str, *, allow_standard_confirmation: bool) -> str:
        if self.channel is None:
            raise RuntimeError("SSH channel is not open.")
        self.channel.send(command + "\n")
        deadline = time.monotonic() + self.config.command_timeout_seconds
        chunks: list[str] = []
        confirmed = False
        last_data = time.monotonic()

        while time.monotonic() < deadline:
            if self.channel.recv_ready():
                data = self.channel.recv(65535).decode("utf-8", errors="replace")
                chunks.append(data)
                last_data = time.monotonic()
                combined = _clean_terminal("".join(chunks))
                if "--More--" in combined or "Press any key to continue" in combined:
                    self.channel.send(" ")
                    chunks = [
                        combined.replace("--More--", "").replace(
                            "Press any key to continue", ""
                        )
                    ]
                    continue
                lowered = combined.lower()
                if any(pattern in lowered for pattern in _DENY_PATTERNS):
                    raise RuntimeError("FortiGate returned a blocked package validation warning.")
                if _CONFIRM_RE.search(combined) and not confirmed:
                    if not allow_standard_confirmation:
                        raise RuntimeError("Unexpected interactive confirmation from FortiGate.")
                    self.channel.send("y\n")
                    confirmed = True
                    continue
                if _last_prompt(combined) is not None and time.monotonic() - last_data >= 0.15:
                    return combined
            else:
                combined = _clean_terminal("".join(chunks))
                if combined and _last_prompt(combined) is not None and time.monotonic() - last_data >= 0.25:
                    return combined
                time.sleep(0.05)
        raise TimeoutError(f"Timed out waiting for FortiGate command completion: {command.split()[0]}")

    def run_backup(
        self,
        *,
        filename: str,
        tftp_address: str,
        backup_password: str,
    ) -> str:
        _validate_filename(filename)
        if not backup_password:
            raise ValueError("Backup encryption password cannot be empty.")
        command = f"execute backup full-config tftp {filename} {tftp_address} {backup_password}"
        raw = self._run_interactive(command, allow_standard_confirmation=False)
        return raw.replace(backup_password, "<redacted>")

    def run_restore(self, *, family: str, filename: str, tftp_address: str) -> str:
        if family not in _ALLOWED_FAMILIES:
            raise ValueError(f"Restore family is not allowed: {family}")
        _validate_filename(filename)
        command = f"execute restore {family} tftp {filename} {tftp_address}"
        return self._run_interactive(command, allow_standard_confirmation=True)


def _validate_filename(filename: str) -> None:
    if not _SAFE_FILENAME_RE.fullmatch(filename) or Path(filename).name != filename:
        raise ValueError(f"Unsafe FortiGate/TFTP filename: {filename}")


def _load_manifest(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
        raise ValueError("Unsupported or invalid bundle manifest.")
    packages = raw.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Manifest contains no packages.")
    return raw


def _select_archive(config: AgentConfig, manifest_id: str) -> tuple[str, dict[str, object]]:
    state = load_state(config.storage.state_file)
    matches = [
        (archive_hash, entry)
        for archive_hash, entry in state.archives.items()
        if entry.get("manifest_id") == manifest_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one prepared archive for manifest {manifest_id}.")
    archive_hash, entry = matches[0]
    if entry.get("status") != "PREPARED":
        raise ValueError(
            f"Manifest {manifest_id} is not eligible for apply; state is {entry.get('status')!r}."
        )
    return archive_hash, entry


def _version_tuple(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)+", value)
    if not match:
        return None
    parts = [int(item) for item in match.group(0).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _version_of(versions: dict[str, dict[str, str]], object_name: str) -> str | None:
    return (versions.get(object_name) or {}).get("Version")


def _return_code(output: str) -> int | None:
    match = _RETURN_CODE_RE.search(output)
    return int(match.group(1)) if match else None


def classify_package_result(
    *,
    kind: str,
    filename: str,
    expected_objects: tuple[str, ...],
    before: dict[str, dict[str, str]],
    after: dict[str, dict[str, str]],
    command_output: str,
    prevent_downgrade: bool,
) -> PackageApplyResult:
    deltas = tuple(
        ObjectDelta(
            name=name,
            before_version=_version_of(before, name),
            after_version=_version_of(after, name),
        )
        for name in expected_objects
    )
    return_code = _return_code(command_output)
    lowered = command_output.lower()
    changed = False
    decreased = False
    missing = False
    for delta in deltas:
        before_tuple = _version_tuple(delta.before_version)
        after_tuple = _version_tuple(delta.after_version)
        if after_tuple is None:
            missing = True
            continue
        if before_tuple is not None and after_tuple < before_tuple:
            decreased = True
        elif before_tuple is None or after_tuple > before_tuple:
            changed = True

    if decreased and prevent_downgrade:
        status = UpdateStatus.FAILED
        reason = "At least one FortiGuard object version decreased; downgrade protection stopped apply."
    elif changed:
        warning = return_code not in {None, 0} or "command fail" in lowered
        status = UpdateStatus.SUCCESS_WITH_WARNING if warning else UpdateStatus.SUCCESS
        reason = (
            "Expected object version increased despite a FortiOS warning."
            if warning
            else "Expected object version increased."
        )
    elif "no updates" in lowered and return_code in {None, -85}:
        status = UpdateStatus.SKIPPED_NO_UPDATE
        reason = "FortiOS reported that the package contained no applicable update."
    elif missing:
        status = UpdateStatus.FAILED_UNCONFIRMED
        reason = "One or more expected FortiGuard objects were missing after restore."
    else:
        status = UpdateStatus.FAILED_UNCONFIRMED
        reason = "Package transfer completed but expected object versions did not increase."

    return PackageApplyResult(
        kind=kind,
        filename=filename,
        status=status,
        reason=reason,
        return_code=return_code,
        objects=deltas,
        command_output_sha256=hashlib.sha256(command_output.encode("utf-8")).hexdigest(),
    )


def _overall_status(results: list[PackageApplyResult], postflight: PreflightResult) -> str:
    if postflight.status != "PASS" or any(
        item.status in {UpdateStatus.FAILED, UpdateStatus.FAILED_UNCONFIRMED}
        for item in results
    ):
        return "FAILED"
    if any(
        item.status in {UpdateStatus.SUCCESS_WITH_WARNING, UpdateStatus.SKIPPED_NO_UPDATE}
        for item in results
    ):
        return "SUCCESS_WITH_WARNING"
    return "SUCCESS"


def _report_paths(config: AgentConfig, manifest_id: str) -> tuple[Path, Path]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = config.storage.reports / f"{stamp}-{manifest_id}-apply"
    return base.with_suffix(".json"), base.with_suffix(".txt")


PreflightRunner = Callable[[AgentConfig], PreflightResult]
SessionFactory = Callable[[DeviceConfig], FortiGateApplySession]
TftpFactory = Callable[..., TemporaryTftpServer]


def run_controlled_apply(
    config: AgentConfig,
    *,
    manifest_id: str,
    approval_manifest: str | None = None,
    preflight_runner: PreflightRunner = run_read_only_preflight,
    session_factory: SessionFactory = FortiGateApplySession,
    tftp_factory: TftpFactory = TemporaryTftpServer,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ControlledApplyResult:
    if config.device is None or config.apply is None:
        raise ValueError("device and apply configuration blocks are required.")
    if config.execution.mode == "prepare_only":
        raise ValueError("Controlled apply is disabled while execution.mode is prepare_only.")
    if config.execution.mode == "approval" and approval_manifest != manifest_id:
        raise ValueError(
            "Approval mode requires --approve-manifest to exactly match the prepared manifest ID."
        )

    config.storage.create_directories()
    archive_hash, entry = _select_archive(config, manifest_id)
    work_dir = Path(str(entry["work_dir"])).resolve()
    manifest_path = work_dir / "manifest.json"
    manifest = _load_manifest(manifest_path)
    if manifest.get("manifest_id") != manifest_id:
        raise ValueError("Manifest ID does not match local prepared state.")
    if manifest.get("source_archive_sha256") != archive_hash:
        raise ValueError("Manifest archive hash does not match local prepared state.")

    enabled = set(config.execution.enabled_packages)
    order = {kind: index for index, kind in enumerate(config.apply.package_order)}
    selected = [
        item
        for item in manifest["packages"]
        if isinstance(item, dict)
        and str(item.get("kind")) in enabled
        and bool(item.get("safe_for_deferred_apply"))
    ]
    selected.sort(key=lambda item: order.get(str(item.get("kind")), 999))
    if not selected:
        raise ValueError("No safe enabled packages were selected for controlled apply.")

    packages_dir = work_dir / "packages"
    for item in selected:
        filename = str(item["filename"])
        package_path = packages_dir / filename
        if sha256_file(package_path) != str(item["sha256"]):
            raise ValueError(f"Prepared package hash mismatch: {filename}")

    preflight = preflight_runner(config)
    if preflight.status != "PASS":
        raise RuntimeError("Read-only preflight did not pass; controlled apply aborted.")

    run_root = config.storage.tftp_dir / f"{archive_hash[:16]}-{int(time.time())}"
    backup_filename = (
        f"{(preflight.system_status.hostname or 'fortigate')}-"
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-full.conf"
    )
    _validate_filename(backup_filename)
    staged = stage_tftp_files(
        packages_dir,
        run_root,
        [str(item["filename"]) for item in selected],
    )
    for staged_path, item in zip(staged, selected, strict=True):
        if sha256_file(staged_path) != str(item["sha256"]):
            raise ValueError(f"Staged TFTP package hash mismatch: {staged_path.name}")

    backup_password = os.environ.get(config.apply.backup_password_env)
    if config.apply.require_backup and not backup_password:
        raise ValueError(
            f"Backup password environment variable is not set: {config.apply.backup_password_env}"
        )

    command_outputs: dict[str, str] = {}
    package_results: list[PackageApplyResult] = []
    current_versions = preflight.autoupdate_versions
    backup_path: Path | None = None

    server = tftp_factory(
        run_root,
        bind_address=config.apply.tftp_bind_address,
        port=config.apply.tftp_port,
        allowed_upload_name=backup_filename if config.apply.require_backup else None,
    )
    with server:
        with session_factory(config.device) as session:
            if config.apply.require_backup:
                assert backup_password is not None
                backup_output = session.run_backup(
                    filename=backup_filename,
                    tftp_address=config.apply.tftp_advertise_address,
                    backup_password=backup_password,
                )
                command_outputs["backup"] = backup_output
                if "command fail" in backup_output.lower():
                    raise RuntimeError("FortiGate rejected the mandatory full configuration backup.")
                backup_path = wait_for_uploaded_file(
                    run_root / backup_filename,
                    timeout_seconds=config.device.command_timeout_seconds,
                )

            for item in selected:
                filename = str(item["filename"])
                family = str(item["restore_family"])
                kind = str(item["kind"])
                output = session.run_restore(
                    family=family,
                    filename=filename,
                    tftp_address=config.apply.tftp_advertise_address,
                )
                command_outputs[kind] = output
                sleep_fn(config.apply.settle_seconds)
                versions_output = session.run_command("diagnose autoupdate versions")
                parsed_after = parse_autoupdate_versions(
                    _strip_command_envelope(versions_output, "diagnose autoupdate versions")
                )
                result = classify_package_result(
                    kind=kind,
                    filename=filename,
                    expected_objects=tuple(str(name) for name in item.get("expected_objects", [])),
                    before=current_versions,
                    after=parsed_after,
                    command_output=output,
                    prevent_downgrade=config.execution.prevent_downgrade,
                )
                package_results.append(result)
                current_versions = parsed_after
                if config.apply.stop_on_failure and result.status in {
                    UpdateStatus.FAILED,
                    UpdateStatus.FAILED_UNCONFIRMED,
                }:
                    break

    if backup_path is not None:
        backup_store = config.storage.evidence_dir / "backups"
        backup_store.mkdir(parents=True, exist_ok=True)
        permanent_backup = backup_store / backup_filename
        if permanent_backup.exists():
            raise FileExistsError(f"Backup destination already exists: {permanent_backup}")
        shutil.copy2(backup_path, permanent_backup)
        if sha256_file(permanent_backup) != sha256_file(backup_path):
            raise RuntimeError("Permanent backup copy failed SHA-256 verification.")
        backup_path = permanent_backup

    postflight = preflight_runner(config)
    overall = _overall_status(package_results, postflight)
    report_json, report_text = _report_paths(config, manifest_id)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "captured_at": utc_now(),
        "status": overall,
        "manifest_id": manifest_id,
        "archive_sha256": archive_hash,
        "execution_mode": config.execution.mode,
        "target": {
            "host": config.device.host,
            "hostname": preflight.system_status.hostname,
            "model": preflight.system_status.model,
            "firmware_version": preflight.system_status.firmware_version,
            "build": preflight.system_status.build,
            "host_key_sha256": preflight.host_key.sha256,
        },
        "preflight_evidence": preflight.evidence_json,
        "postflight_evidence": postflight.evidence_json,
        "tftp": {
            "bind_address": config.apply.tftp_bind_address,
            "advertise_address": config.apply.tftp_advertise_address,
            "port": config.apply.tftp_port,
            "ephemeral_root": str(run_root),
        },
        "backup": (
            {
                "path": str(backup_path),
                "sha256": sha256_file(backup_path),
                "size": backup_path.stat().st_size,
                "encrypted": True,
            }
            if backup_path is not None
            else None
        ),
        "packages": [item.to_dict() for item in package_results],
        "command_outputs": {
            name: {
                "sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
                "output": output,
            }
            for name, output in command_outputs.items()
        },
        "device_changes_performed": bool(package_results),
    }
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    text_lines = [
        f"FGOps controlled apply: {overall}",
        f"Manifest: {manifest_id}",
        f"Archive SHA-256: {archive_hash}",
        f"Target: {config.device.host}",
        f"Backup: {backup_path or 'not created'}",
        "",
    ]
    for item in package_results:
        text_lines.append(f"{item.kind} {item.filename}: {item.status.value} - {item.reason}")
        for delta in item.objects:
            text_lines.append(
                f"  {delta.name}: {delta.before_version or '-'} -> {delta.after_version or '-'}"
            )
    report_text.write_text("\n".join(text_lines) + "\n", encoding="utf-8")

    state = load_state(config.storage.state_file)
    archive_entry = state.archives.get(archive_hash)
    if archive_entry is None:
        raise RuntimeError("Prepared archive disappeared from local state during apply.")
    archive_entry.update(
        {
            "status": "APPLIED" if overall != "FAILED" else "APPLY_FAILED",
            "applied_at": utc_now(),
            "apply_status": overall,
            "apply_report": str(report_json),
            "backup_path": str(backup_path) if backup_path else None,
        }
    )
    state.last_run_at = utc_now()
    state.last_result = overall
    state.last_error = None if overall != "FAILED" else "Controlled apply completed with failures."
    save_state(config.storage.state_file, state)

    if overall != "FAILED":
        shutil.rmtree(run_root, ignore_errors=False)

    return ControlledApplyResult(
        status=overall,
        manifest_id=manifest_id,
        archive_sha256=archive_hash,
        report_json=str(report_json),
        report_text=str(report_text),
        backup_path=str(backup_path) if backup_path else None,
        package_results=tuple(package_results),
    )
