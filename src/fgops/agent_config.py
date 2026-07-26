from __future__ import annotations

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


@dataclass(frozen=True)
class SourceConfig:
    page_url: str
    link_text_regex: str
    timeout_seconds: int = 60
    max_download_bytes: int = 512 * 1024 * 1024
    user_agent: str = "FGOps/0.2 (+offline-update-monitor)"

    def validate(self) -> None:
        parsed = urlparse(self.page_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source.page_url must be an absolute HTTP(S) URL.")
        re.compile(self.link_text_regex)
        if not 5 <= self.timeout_seconds <= 600:
            raise ValueError("source.timeout_seconds must be between 5 and 600.")
        if not 1024 * 1024 <= self.max_download_bytes <= 4 * 1024**3:
            raise ValueError("source.max_download_bytes must be between 1 MiB and 4 GiB.")


@dataclass(frozen=True)
class StorageConfig:
    root: Path
    incoming: Path
    quarantine: Path
    reports: Path
    state_file: Path

    def create_directories(self) -> None:
        for path in (self.root, self.incoming, self.quarantine, self.reports):
            path.mkdir(parents=True, exist_ok=True)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ExecutionConfig:
    mode: str = "prepare_only"
    enabled_packages: tuple[str, ...] = ("AV", "IPS", "APDB", "FFDB", "MCDB", "MMDB")
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
class AgentConfig:
    config_path: Path
    package_map: Path
    source: SourceConfig
    storage: StorageConfig
    execution: ExecutionConfig

    def validate(self) -> None:
        self.source.validate()
        self.execution.validate()
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

    root = _resolve(base, storage_raw.get("root", "runtime"))
    storage = StorageConfig(
        root=root,
        incoming=_resolve(root, storage_raw.get("incoming", "incoming")),
        quarantine=_resolve(root, storage_raw.get("quarantine", "quarantine")),
        reports=_resolve(root, storage_raw.get("reports", "reports")),
        state_file=_resolve(root, storage_raw.get("state_file", "state/agent-state.json")),
    )
    source = SourceConfig(
        page_url=str(source_raw.get("page_url", _DEFAULT_SOURCE_URL)),
        link_text_regex=str(source_raw.get("link_text_regex", r"(?i)Fortigate\s+V6\.4")),
        timeout_seconds=int(source_raw.get("timeout_seconds", 60)),
        max_download_bytes=int(source_raw.get("max_download_bytes", 512 * 1024 * 1024)),
        user_agent=str(source_raw.get("user_agent", "FGOps/0.2 (+offline-update-monitor)")),
    )
    execution = ExecutionConfig(
        mode=str(execution_raw.get("mode", "prepare_only")),
        enabled_packages=tuple(str(value).upper() for value in execution_raw.get(
            "enabled_packages", ["AV", "IPS", "APDB", "FFDB", "MCDB", "MMDB"]
        )),
        reject_unknown_packages=bool(execution_raw.get("reject_unknown_packages", True)),
        prevent_downgrade=bool(execution_raw.get("prevent_downgrade", True)),
    )
    config = AgentConfig(
        config_path=path,
        package_map=_resolve(base, raw.get("package_map", "fortios64-package-map.yml")),
        source=source,
        storage=storage,
        execution=execution,
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

storage:
  root: C:/ProgramData/FGOps
  incoming: incoming
  quarantine: quarantine
  reports: reports
  state_file: state/agent-state.json

execution:
  # Device-changing execution is introduced in a later gated milestone.
  mode: prepare_only
  enabled_packages: [AV, IPS, APDB, FFDB, MCDB, MMDB]
  reject_unknown_packages: true
  prevent_downgrade: true
'''


def write_default_config(path: Path, *, force: bool = False) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise FileExistsError(f"Configuration already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_text(), encoding="utf-8")
    return path
