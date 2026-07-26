from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

_DEFAULT_SOURCE_URL = (
    "https://www.cyberlogic.ir/"
    "%D8%A8%D8%B1%D9%88%D8%B2-%D8%B1%D8%B3%D8%A7%D9%86%DB%8C-"
    "%D8%A2%D9%81%D9%84%D8%A7%DB%8C%D9%86-fortigate-%D9%88-fortiweb/"
)
_HOST_KEY_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{20,}={0,2}$")
_DEFAULT_PACKAGE_ORDER = ("AV", "IPS", "APDB", "FFDB", "MCDB", "MMDB")


@dataclass(frozen=True)
class SourceConfig:
    page_url: str
    link_text_regex: str
    timeout_seconds: int = 60
    max_download_bytes: int = 512 * 1024 * 1024
    user_agent: str = "FGOps/0.4 (+offline-update-monitor)"
    tls_mode: str = "system"
    ca_file: Path | None = None

    def validate(self) -> None:
        parsed = urlparse(self.page_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source.page_url must be an absolute HTTP(S) URL.")
        re.compile(self.link_text_regex)
        if not 5 <= self.timeout_seconds <= 600:
            raise ValueError("source.timeout_seconds must be between 5 and 600.")
        if not 1024 * 1024 <= self.max_download_bytes <= 4 * 1024**3:
            raise ValueError("source.max_download_bytes must be between 1 MiB and 4 GiB.")
        if self.tls_mode not in {"system", "python", "custom"}:
            raise ValueError("source.tls_mode must be system, python, or custom.")
        if self.tls_mode == "custom":
            if self.ca_file is None:
                raise ValueError("source.ca_file is required when source.tls_mode is custom.")
            if not self.ca_file.is_file():
                raise ValueError(f"Configured source.ca_file does not exist: {self.ca_file}")


@dataclass(frozen=True)
class StorageConfig:
    root: Path
    incoming: Path
    quarantine: Path
    reports: Path
    state_file: Path
    evidence: Path | None = None
    tftp: Path | None = None

    @property
    def evidence_dir(self) -> Path:
        return self.evidence or self.root / "evidence"

    @property
    def tftp_dir(self) -> Path:
        return self.tftp or self.root / "tftp"

    def create_directories(self) -> None:
        for path in (
            self.root,
            self.incoming,
            self.quarantine,
            self.reports,
            self.evidence_dir,
            self.tftp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ExecutionConfig:
    mode: str = "prepare_only"
    enabled_packages: tuple[str, ...] = _DEFAULT_PACKAGE_ORDER
    reject_unknown_packages: bool = True
    prevent_downgrade: bool = True

    def validate(self) -> None:
        if self.mode not in {"prepare_only", "approval", "unattended"}:
            raise ValueError("execution.mode must be prepare_only, approval, or unattended.")
        if not self.enabled_packages:
            raise ValueError("execution.enabled_packages cannot be empty.")
        if len(set(self.enabled_packages)) != len(self.enabled_packages):
            raise ValueError("execution.enabled_packages must be unique.")


@dataclass(frozen=True)
class DeviceConfig:
    host: str
    username: str
    host_key_sha256: str
    port: int = 22
    password_env: str = "FGOPS_SSH_PASSWORD"
    key_file: Path | None = None
    key_passphrase_env: str | None = None
    connect_timeout_seconds: int = 20
    command_timeout_seconds: int = 120
    expected_hostname: str | None = None
    expected_model: str | None = None
    expected_firmware_branch: str | None = None
    expected_build: int | None = None
    global_context: bool = True

    def validate(self) -> None:
        if not self.host.strip():
            raise ValueError("device.host cannot be empty.")
        if not self.username.strip():
            raise ValueError("device.username cannot be empty.")
        if not 1 <= self.port <= 65535:
            raise ValueError("device.port must be between 1 and 65535.")
        if not _HOST_KEY_RE.fullmatch(self.host_key_sha256.strip()):
            raise ValueError("device.host_key_sha256 must use OpenSSH SHA256:<base64> format.")
        if not 5 <= self.connect_timeout_seconds <= 300:
            raise ValueError("device.connect_timeout_seconds must be between 5 and 300.")
        if not 10 <= self.command_timeout_seconds <= 900:
            raise ValueError("device.command_timeout_seconds must be between 10 and 900.")
        if self.key_file is not None and not self.key_file.is_file():
            raise ValueError(f"Configured device.key_file does not exist: {self.key_file}")
        if self.key_file is None and not self.password_env.strip():
            raise ValueError("device.password_env is required when device.key_file is not configured.")
        if self.expected_build is not None and self.expected_build <= 0:
            raise ValueError("device.expected_build must be a positive integer.")


@dataclass(frozen=True)
class ApplyConfig:
    tftp_bind_address: str = "0.0.0.0"
    tftp_advertise_address: str = ""
    tftp_port: int = 69
    require_backup: bool = True
    backup_password_env: str = "FGOPS_BACKUP_PASSWORD"
    settle_seconds: int = 5
    stop_on_failure: bool = True
    package_order: tuple[str, ...] = _DEFAULT_PACKAGE_ORDER

    def validate(self) -> None:
        try:
            ipaddress.ip_address(self.tftp_bind_address)
        except ValueError as exc:
            raise ValueError("apply.tftp_bind_address must be an IP address.") from exc
        try:
            advertised = ipaddress.ip_address(self.tftp_advertise_address)
        except ValueError as exc:
            raise ValueError("apply.tftp_advertise_address must be a reachable IP address.") from exc
        if advertised.is_unspecified:
            raise ValueError("apply.tftp_advertise_address cannot be an unspecified address.")
        if self.tftp_port != 69:
            raise ValueError("apply.tftp_port must be 69 because FortiOS restore syntax has no port field.")
        if self.require_backup and not self.backup_password_env.strip():
            raise ValueError("apply.backup_password_env is required when backups are mandatory.")
        if not 0 <= self.settle_seconds <= 300:
            raise ValueError("apply.settle_seconds must be between 0 and 300.")
        if not self.package_order:
            raise ValueError("apply.package_order cannot be empty.")
        if len(set(self.package_order)) != len(self.package_order):
            raise ValueError("apply.package_order must be unique.")
        forbidden = set(self.package_order) - set(_DEFAULT_PACKAGE_ORDER)
        if forbidden:
            raise ValueError(
                "apply.package_order contains packages not enabled for controlled v0.4 apply: "
                + ", ".join(sorted(forbidden))
            )


@dataclass(frozen=True)
class AgentConfig:
    config_path: Path
    package_map: Path
    source: SourceConfig
    storage: StorageConfig
    execution: ExecutionConfig
    device: DeviceConfig | None = None
    apply: ApplyConfig | None = None

    def validate(self) -> None:
        self.source.validate()
        self.execution.validate()
        if self.device is not None:
            self.device.validate()
        if self.apply is not None:
            self.apply.validate()
        if self.execution.mode != "prepare_only" and self.apply is None:
            raise ValueError("An apply block is required when execution.mode is approval or unattended.")
        if self.apply is not None and self.device is None:
            raise ValueError("A device block is required when apply is configured.")
        if not self.package_map.is_file():
            raise ValueError(f"Package map does not exist: {self.package_map}")


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_agent_config(path: Path) -> AgentConfig:
    path = path.expanduser().resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Agent configuration must be a YAML object.")

    base = path.parent
    source_raw = raw.get("source") or {}
    storage_raw = raw.get("storage") or {}
    execution_raw = raw.get("execution") or {}
    device_raw = raw.get("device")
    apply_raw = raw.get("apply")

    root = _resolve(base, storage_raw.get("root", "runtime"))
    storage = StorageConfig(
        root=root,
        incoming=_resolve(root, storage_raw.get("incoming", "incoming")),
        quarantine=_resolve(root, storage_raw.get("quarantine", "quarantine")),
        reports=_resolve(root, storage_raw.get("reports", "reports")),
        state_file=_resolve(root, storage_raw.get("state_file", "state/agent-state.json")),
        evidence=_resolve(root, storage_raw.get("evidence", "evidence")),
        tftp=_resolve(root, storage_raw.get("tftp", "tftp")),
    )
    ca_value = source_raw.get("ca_file")
    source = SourceConfig(
        page_url=str(source_raw.get("page_url", _DEFAULT_SOURCE_URL)),
        link_text_regex=str(source_raw.get("link_text_regex", r"(?i)Fortigate\s+V6\.4")),
        timeout_seconds=int(source_raw.get("timeout_seconds", 60)),
        max_download_bytes=int(source_raw.get("max_download_bytes", 512 * 1024 * 1024)),
        user_agent=str(source_raw.get("user_agent", "FGOps/0.4 (+offline-update-monitor)")),
        tls_mode=str(source_raw.get("tls_mode", "system")).strip().lower(),
        ca_file=_resolve(base, ca_value) if ca_value else None,
    )
    execution = ExecutionConfig(
        mode=str(execution_raw.get("mode", "prepare_only")).strip().lower(),
        enabled_packages=tuple(
            str(value).upper()
            for value in execution_raw.get("enabled_packages", list(_DEFAULT_PACKAGE_ORDER))
        ),
        reject_unknown_packages=bool(execution_raw.get("reject_unknown_packages", True)),
        prevent_downgrade=bool(execution_raw.get("prevent_downgrade", True)),
    )

    device: DeviceConfig | None = None
    if device_raw is not None:
        if not isinstance(device_raw, dict):
            raise ValueError("device must be a YAML object.")
        key_file_value = device_raw.get("key_file")
        expected_build_value = device_raw.get("expected_build")
        device = DeviceConfig(
            host=str(device_raw.get("host", "")),
            port=int(device_raw.get("port", 22)),
            username=str(device_raw.get("username", "")),
            host_key_sha256=str(device_raw.get("host_key_sha256", "")),
            password_env=str(device_raw.get("password_env", "FGOPS_SSH_PASSWORD")),
            key_file=_resolve(base, key_file_value) if key_file_value else None,
            key_passphrase_env=(
                str(device_raw["key_passphrase_env"])
                if device_raw.get("key_passphrase_env")
                else None
            ),
            connect_timeout_seconds=int(device_raw.get("connect_timeout_seconds", 20)),
            command_timeout_seconds=int(device_raw.get("command_timeout_seconds", 120)),
            expected_hostname=(
                str(device_raw["expected_hostname"])
                if device_raw.get("expected_hostname")
                else None
            ),
            expected_model=(
                str(device_raw["expected_model"]) if device_raw.get("expected_model") else None
            ),
            expected_firmware_branch=(
                str(device_raw["expected_firmware_branch"])
                if device_raw.get("expected_firmware_branch")
                else None
            ),
            expected_build=(int(expected_build_value) if expected_build_value is not None else None),
            global_context=bool(device_raw.get("global_context", True)),
        )

    apply: ApplyConfig | None = None
    if apply_raw is not None:
        if not isinstance(apply_raw, dict):
            raise ValueError("apply must be a YAML object.")
        apply = ApplyConfig(
            tftp_bind_address=str(apply_raw.get("tftp_bind_address", "0.0.0.0")),
            tftp_advertise_address=str(apply_raw.get("tftp_advertise_address", "")),
            tftp_port=int(apply_raw.get("tftp_port", 69)),
            require_backup=bool(apply_raw.get("require_backup", True)),
            backup_password_env=str(
                apply_raw.get("backup_password_env", "FGOPS_BACKUP_PASSWORD")
            ),
            settle_seconds=int(apply_raw.get("settle_seconds", 5)),
            stop_on_failure=bool(apply_raw.get("stop_on_failure", True)),
            package_order=tuple(
                str(value).upper()
                for value in apply_raw.get("package_order", list(_DEFAULT_PACKAGE_ORDER))
            ),
        )

    config = AgentConfig(
        config_path=path,
        package_map=_resolve(base, raw.get("package_map", "fortios64-package-map.yml")),
        source=source,
        storage=storage,
        execution=execution,
        device=device,
        apply=apply,
    )
    config.validate()
    return config


def default_config_text() -> str:
    return f'''# FGOps standalone VM agent configuration
package_map: fortios64-package-map.yml

source:
  page_url: "{_DEFAULT_SOURCE_URL}"
  link_text_regex: '(?i)Fortigate\\s+V6\\.4'
  timeout_seconds: 60
  max_download_bytes: 536870912
  tls_mode: system

storage:
  root: C:/ProgramData/FGOps
  incoming: incoming
  quarantine: quarantine
  reports: reports
  evidence: evidence
  tftp: tftp
  state_file: state/agent-state.json

execution:
  # Change to approval only after read-only preflight succeeds.
  mode: prepare_only
  enabled_packages: [AV, IPS, APDB, FFDB, MCDB, MMDB]
  reject_unknown_packages: true
  prevent_downgrade: true

# Add after verifying the SSH host key out of band.
# device:
#   host: 172.16.1.2
#   port: 22
#   username: admin
#   host_key_sha256: SHA256:REPLACE_WITH_VERIFIED_FINGERPRINT
#   password_env: FGOPS_SSH_PASSWORD
#   expected_hostname: SITEC-FW-02
#   expected_model: FortiGate-300D
#   expected_firmware_branch: "6.4"
#   expected_build: 2098
#   global_context: true

# Controlled apply remains fail-closed. TFTP uses UDP/69 because FortiOS restore syntax
# does not accept a custom port. Use a dedicated management interface/IP.
# apply:
#   tftp_bind_address: 192.168.1.179
#   tftp_advertise_address: 192.168.1.179
#   tftp_port: 69
#   require_backup: true
#   backup_password_env: FGOPS_BACKUP_PASSWORD
#   settle_seconds: 5
#   stop_on_failure: true
#   package_order: [AV, IPS, APDB, FFDB, MCDB, MMDB]
'''


def write_default_config(path: Path, *, force: bool = False) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise FileExistsError(f"Configuration already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_text(), encoding="utf-8")
    return path
