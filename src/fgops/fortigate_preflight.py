from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import paramiko

from .agent_config import AgentConfig, DeviceConfig

READ_ONLY_COMMANDS = (
    "get system status",
    "diagnose autoupdate versions",
    "diagnose sys flash list",
    "diagnose debug config-error-log read",
    "diagnose autoupdate signature check-all",
)
_PROMPT_RE = re.compile(r"(?m)^([^\r\n]{1,240}[#$])\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_VERSION_RE = re.compile(
    r"^Version:\s+(?P<model>FortiGate-[^\s]+)\s+v(?P<version>\d+\.\d+\.\d+),"
    r"build(?P<build>\d+),[^\r\n]*$",
    re.MULTILINE,
)
_SECTION_RE = re.compile(r"(?m)^([^\r\n]+)\r?\n-+\r?\n")


@dataclass(frozen=True)
class HostKeyInfo:
    host: str
    port: int
    key_type: str
    bits: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "key_type": self.key_type,
            "bits": self.bits,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class SystemStatus:
    hostname: str | None
    model: str | None
    firmware_version: str | None
    build: int | None
    serial_number: str | None
    operation_mode: str | None
    current_vdom: str | None
    vdom_configuration: str | None
    ha_mode: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "hostname": self.hostname,
            "model": self.model,
            "firmware_version": self.firmware_version,
            "build": self.build,
            "serial_number": self.serial_number,
            "operation_mode": self.operation_mode,
            "current_vdom": self.current_vdom,
            "vdom_configuration": self.vdom_configuration,
            "ha_mode": self.ha_mode,
        }


@dataclass(frozen=True)
class PreflightResult:
    status: str
    evidence_json: str
    evidence_text: str
    host_key: HostKeyInfo
    system_status: SystemStatus
    autoupdate_versions: dict[str, dict[str, str]]
    validation_errors: tuple[str, ...]
    command_errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "evidence_json": self.evidence_json,
            "evidence_text": self.evidence_text,
            "host_key": self.host_key.to_dict(),
            "system_status": self.system_status.to_dict(),
            "autoupdate_versions": self.autoupdate_versions,
            "validation_errors": list(self.validation_errors),
            "command_errors": list(self.command_errors),
        }


def openssh_sha256(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


def scan_host_key(host: str, port: int = 22, timeout_seconds: int = 10) -> HostKeyInfo:
    with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
        transport = paramiko.Transport(sock)
        try:
            transport.start_client(timeout=timeout_seconds)
            key = transport.get_remote_server_key()
            return HostKeyInfo(
                host=host,
                port=port,
                key_type=key.get_name(),
                bits=key.get_bits(),
                sha256=openssh_sha256(key),
            )
        finally:
            transport.close()


class PinnedFingerprintPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected_sha256: str) -> None:
        self.expected_sha256 = expected_sha256

    def missing_host_key(
        self,
        client: paramiko.SSHClient,
        hostname: str,
        key: paramiko.PKey,
    ) -> None:
        actual = openssh_sha256(key)
        if actual != self.expected_sha256:
            raise paramiko.SSHException(
                f"SSH host-key mismatch for {hostname}: expected {self.expected_sha256}, got {actual}"
            )


def _clean_terminal(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    while "\b" in text:
        text = re.sub(r".?\x08", "", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _last_prompt(text: str) -> str | None:
    matches = list(_PROMPT_RE.finditer(_clean_terminal(text)))
    return matches[-1].group(1).strip() if matches else None


class FortiGateReadOnlySession:
    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.client: paramiko.SSHClient | None = None
        self.channel: paramiko.Channel | None = None
        self.host_key: HostKeyInfo | None = None

    def __enter__(self) -> FortiGateReadOnlySession:
        password = os.environ.get(self.config.password_env) if self.config.password_env else None
        passphrase = (
            os.environ.get(self.config.key_passphrase_env)
            if self.config.key_passphrase_env
            else None
        )
        if self.config.key_file is None and password is None:
            raise ValueError(
                f"SSH password environment variable is not set: {self.config.password_env}"
            )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(PinnedFingerprintPolicy(self.config.host_key_sha256))
        client.connect(
            hostname=self.config.host,
            port=self.config.port,
            username=self.config.username,
            password=password,
            key_filename=str(self.config.key_file) if self.config.key_file else None,
            passphrase=passphrase,
            timeout=self.config.connect_timeout_seconds,
            banner_timeout=self.config.connect_timeout_seconds,
            auth_timeout=self.config.connect_timeout_seconds,
            allow_agent=False,
            look_for_keys=False,
        )
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            client.close()
            raise RuntimeError("SSH transport did not become active.")
        key = transport.get_remote_server_key()
        self.host_key = HostKeyInfo(
            host=self.config.host,
            port=self.config.port,
            key_type=key.get_name(),
            bits=key.get_bits(),
            sha256=openssh_sha256(key),
        )
        self.client = client
        self.channel = client.invoke_shell(term="vt100", width=240, height=1000)
        self.channel.settimeout(1.0)
        banner = self._read_until_prompt(self.config.command_timeout_seconds)
        if _last_prompt(banner) is None:
            raise RuntimeError("FortiGate CLI prompt was not detected after SSH login.")
        if self.config.global_context:
            output = self.run_command("config global")
            prompt = _last_prompt(output)
            if prompt is None or "(global)" not in prompt:
                raise RuntimeError("Failed to enter FortiGate global context.")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.channel is not None:
            try:
                if self.config.global_context:
                    self.channel.send("end\n")
            except Exception:
                pass
            self.channel.close()
        if self.client is not None:
            self.client.close()

    def _read_until_prompt(self, timeout_seconds: int) -> str:
        if self.channel is None:
            raise RuntimeError("SSH channel is not open.")
        deadline = time.monotonic() + timeout_seconds
        chunks: list[str] = []
        last_data = time.monotonic()
        while time.monotonic() < deadline:
            if self.channel.recv_ready():
                data = self.channel.recv(65535).decode("utf-8", errors="replace")
                chunks.append(data)
                last_data = time.monotonic()
                combined = "".join(chunks)
                if "--More--" in combined or "Press any key to continue" in combined:
                    self.channel.send(" ")
                    chunks = [combined.replace("--More--", "").replace("Press any key to continue", "")]
                    continue
                if _last_prompt(combined) is not None and time.monotonic() - last_data >= 0.15:
                    return _clean_terminal(combined)
            else:
                combined = "".join(chunks)
                if combined and _last_prompt(combined) is not None and time.monotonic() - last_data >= 0.25:
                    return _clean_terminal(combined)
                time.sleep(0.05)
        raise TimeoutError(f"Timed out waiting for FortiGate CLI prompt after {timeout_seconds}s.")

    def run_command(self, command: str) -> str:
        if command != "config global" and command not in READ_ONLY_COMMANDS:
            raise ValueError(f"Command is not in the read-only allowlist: {command}")
        if self.channel is None:
            raise RuntimeError("SSH channel is not open.")
        self.channel.send(command + "\n")
        return self._read_until_prompt(self.config.command_timeout_seconds)


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(label)}:\s*(.*?)\s*$", text)
    return match.group(1).strip() if match else None


def parse_system_status(text: str) -> SystemStatus:
    version_match = _VERSION_RE.search(text)
    return SystemStatus(
        hostname=_field(text, "Hostname"),
        model=version_match.group("model") if version_match else None,
        firmware_version=version_match.group("version") if version_match else None,
        build=int(version_match.group("build")) if version_match else None,
        serial_number=_field(text, "Serial-Number"),
        operation_mode=_field(text, "Operation Mode"),
        current_vdom=_field(text, "Current virtual domain"),
        vdom_configuration=_field(text, "Virtual domain configuration"),
        ha_mode=_field(text, "Current HA mode"),
    )


def parse_autoupdate_versions(text: str) -> dict[str, dict[str, str]]:
    matches = list(_SECTION_RE.finditer(text))
    result: dict[str, dict[str, str]] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        values: dict[str, str] = {}
        for key in ("Version", "Contract Expiry Date", "Last Updated using manual update", "Last Update Attempt", "Result"):
            value = _field(body, key)
            if value is not None:
                values[key] = value
        if values:
            result[name] = values
    return result


def validate_observed(config: DeviceConfig, status: SystemStatus) -> list[str]:
    errors: list[str] = []
    if status.model is None or status.firmware_version is None or status.build is None:
        errors.append("Unable to parse FortiGate model, firmware version, or build from get system status.")
        return errors
    if config.expected_hostname and status.hostname != config.expected_hostname:
        errors.append(
            f"Hostname mismatch: expected {config.expected_hostname}, observed {status.hostname}."
        )
    if config.expected_model and status.model.lower() != config.expected_model.lower():
        errors.append(f"Model mismatch: expected {config.expected_model}, observed {status.model}.")
    if config.expected_firmware_branch:
        observed_branch = ".".join(status.firmware_version.split(".")[:2])
        if observed_branch != config.expected_firmware_branch:
            errors.append(
                "Firmware branch mismatch: "
                f"expected {config.expected_firmware_branch}, observed {observed_branch}."
            )
    if config.expected_build is not None and status.build != config.expected_build:
        errors.append(f"Build mismatch: expected {config.expected_build}, observed {status.build}.")
    return errors


def _strip_command_envelope(output: str, command: str) -> str:
    lines = _clean_terminal(output).splitlines()
    if lines and command.strip() in lines[0]:
        lines = lines[1:]
    if lines and _PROMPT_RE.fullmatch(lines[-1].strip()):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


SessionFactory = Callable[[DeviceConfig], FortiGateReadOnlySession]


def run_read_only_preflight(
    config: AgentConfig,
    *,
    session_factory: SessionFactory = FortiGateReadOnlySession,
) -> PreflightResult:
    if config.device is None:
        raise ValueError("A device configuration is required for preflight.")
    config.storage.create_directories()
    stamp = _utc_stamp()
    base = config.storage.evidence_dir / f"{stamp}-{config.device.host.replace(':', '_')}"
    json_path = base.with_suffix(".json")
    text_path = base.with_suffix(".txt")

    outputs: dict[str, str] = {}
    command_errors: list[str] = []
    host_key: HostKeyInfo | None = None
    with session_factory(config.device) as session:
        host_key = session.host_key
        if host_key is None:
            raise RuntimeError("SSH host key was not captured.")
        for command in READ_ONLY_COMMANDS:
            raw = session.run_command(command)
            outputs[command] = _strip_command_envelope(raw, command)
            lowered = outputs[command].lower()
            if "command fail" in lowered or "command parse error" in lowered:
                command_errors.append(f"FortiGate rejected read-only command: {command}")

    system_status = parse_system_status(outputs.get("get system status", ""))
    autoupdate = parse_autoupdate_versions(outputs.get("diagnose autoupdate versions", ""))
    validation_errors = validate_observed(config.device, system_status)
    if not autoupdate:
        validation_errors.append("No FortiGuard database sections were parsed from autoupdate output.")
    status = "PASS" if not validation_errors and not command_errors else "FAILED_VALIDATION"

    evidence = {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "status": status,
        "target": {
            "host": config.device.host,
            "port": config.device.port,
            "username": config.device.username,
        },
        "host_key": host_key.to_dict(),
        "system_status": system_status.to_dict(),
        "autoupdate_versions": autoupdate,
        "validation_errors": validation_errors,
        "command_errors": command_errors,
        "commands": {
            command: {
                "sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
                "output": output,
            }
            for command, output in outputs.items()
        },
        "device_changes_performed": False,
    }
    json_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    text_parts = [
        f"FGOps read-only FortiGate preflight: {status}",
        f"Captured: {evidence['captured_at']}",
        f"Target: {config.device.host}:{config.device.port}",
        f"Host key: {host_key.key_type} {host_key.sha256}",
        "",
    ]
    for command in READ_ONLY_COMMANDS:
        text_parts.extend((f"===== {command} =====", outputs.get(command, ""), ""))
    if validation_errors or command_errors:
        text_parts.extend(("===== VALIDATION =====", *(validation_errors + command_errors), ""))
    text_path.write_text("\n".join(text_parts), encoding="utf-8")

    return PreflightResult(
        status=status,
        evidence_json=str(json_path),
        evidence_text=str(text_path),
        host_key=host_key,
        system_status=system_status,
        autoupdate_versions=autoupdate,
        validation_errors=tuple(validation_errors),
        command_errors=tuple(command_errors),
    )
