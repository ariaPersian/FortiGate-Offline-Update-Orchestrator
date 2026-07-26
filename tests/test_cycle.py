from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from fgops.agent_config import (
    AgentConfig,
    ApplyConfig,
    DeviceConfig,
    ExecutionConfig,
    SourceConfig,
    StorageConfig,
)
from fgops.agent_orchestrator import AgentRunResult
from fgops.controlled_apply import ControlledApplyResult
from fgops.cycle import run_cycle
from fgops.runtime_policy import RuntimePolicy, TelegramConfig


def _config(tmp_path: Path, mode: str) -> AgentConfig:
    package_map = tmp_path / "package-map.yml"
    package_map.write_text("packages: []\n", encoding="utf-8")
    config_path = tmp_path / "config.yml"
    config_path.write_text("notifications: {}\n", encoding="utf-8")
    return AgentConfig(
        config_path=config_path,
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
        execution=ExecutionConfig(mode=mode, enabled_packages=("AV",)),
        device=DeviceConfig(
            host="127.0.0.1",
            username="admin",
            host_key_sha256="SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        ),
        apply=ApplyConfig(
            tftp_bind_address="127.0.0.1",
            tftp_advertise_address="127.0.0.1",
            package_order=("AV",),
        ),
    )


def _prepared() -> AgentRunResult:
    return AgentRunResult(
        status="PREPARED",
        source_page="https://example.test",
        download_url="https://example.test/bundle.zip",
        archive_sha256="a" * 64,
        archive_path="bundle.zip",
        manifest_id="FGOPS-TEST000000000001",
        work_dir="work",
        planned_packages=("AV",),
    )


def test_approval_cycle_never_applies_without_approve_command(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, "approval")
    monkeypatch.setattr("fgops.cycle.run_agent_once", lambda _config, dry_run=False: _prepared())
    monkeypatch.setattr(
        "fgops.cycle.load_runtime_policy",
        lambda *_args: RuntimePolicy(tmp_path / "secrets.json", TelegramConfig(enabled=False)),
    )
    monkeypatch.setattr("fgops.cycle._notify_best_effort", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "fgops.cycle.run_controlled_apply",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("apply must not run")),
    )

    result = run_cycle(config)

    assert result.status == "PREPARED"
    assert result.apply is None


def test_unattended_cycle_loads_secrets_and_runs_controlled_apply(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path, "unattended")
    monkeypatch.setattr("fgops.cycle.run_agent_once", lambda _config, dry_run=False: _prepared())
    monkeypatch.setattr(
        "fgops.cycle.load_runtime_policy",
        lambda *_args: RuntimePolicy(tmp_path / "secrets.json", TelegramConfig(enabled=False)),
    )
    monkeypatch.setattr("fgops.cycle._notify_best_effort", lambda *args, **kwargs: None)
    captured = {}

    def fake_secret_environment(path, names):
        captured["path"] = path
        captured["names"] = names
        return nullcontext()

    monkeypatch.setattr("fgops.cycle.secret_environment", fake_secret_environment)
    monkeypatch.setattr(
        "fgops.cycle.run_controlled_apply",
        lambda _config, manifest_id: ControlledApplyResult(
            status="SUCCESS",
            manifest_id=manifest_id,
            archive_sha256="a" * 64,
            report_json="report.json",
            report_text="report.txt",
            backup_path="backup.conf",
            package_results=(),
        ),
    )

    result = run_cycle(config)

    assert result.status == "SUCCESS"
    assert result.apply is not None
    assert captured["path"] == tmp_path / "secrets.json"
    assert captured["names"] == ("FGOPS_SSH_PASSWORD", "FGOPS_BACKUP_PASSWORD")
