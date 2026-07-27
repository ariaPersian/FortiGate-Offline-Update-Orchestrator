from __future__ import annotations

from pathlib import Path

from fgops.agent_config import AgentConfig, ExecutionConfig, SourceConfig, StorageConfig
from fgops.agent_orchestrator import run_agent_once
from fgops.agent_state import AgentState, load_state, save_state
from fgops.downloader import DownloadResult


ARCHIVE_SHA = "c" * 64
MANIFEST_ID = "FGOPS-RESUME00000001"


def _config(tmp_path: Path, mode: str = "unattended") -> AgentConfig:
    package_map = tmp_path / "package-map.yml"
    package_map.write_text("packages: []\n", encoding="utf-8")
    config_path = tmp_path / "config.yml"
    config_path.write_text("execution:\n  mode: unattended\n", encoding="utf-8")
    return AgentConfig(
        config_path=config_path,
        package_map=package_map,
        source=SourceConfig(
            page_url="https://example.test/page",
            link_text_regex=r"(?i)Fortigate\s+V6\.4",
        ),
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
    )


def _save_archive(config: AgentConfig, status: str) -> None:
    save_state(
        config.storage.state_file,
        AgentState(
            archives={
                ARCHIVE_SHA: {
                    "status": status,
                    "archive_path": str(config.storage.incoming / "bundle.zip"),
                    "manifest_id": MANIFEST_ID,
                    "work_dir": str(config.storage.quarantine / ARCHIVE_SHA[:16]),
                    "planned_packages": ["AV"],
                }
            }
        ),
    )


def _page_fetcher(*_args, **_kwargs) -> str:
    return '<ul><li>Fortigate V6.4 <a href="/bundle.zip">Download</a></li></ul>'


def _bundle_downloader(*_args, **_kwargs) -> DownloadResult:
    return DownloadResult(
        path=Path("bundle.zip"),
        sha256=ARCHIVE_SHA,
        size=123,
        source_url="https://example.test/bundle.zip",
        content_type="application/zip",
    )


def test_unattended_run_resumes_prepared_archive(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_archive(config, "PREPARED")

    result = run_agent_once(
        config,
        page_fetcher=_page_fetcher,
        bundle_downloader=_bundle_downloader,
    )

    assert result.status == "PREPARED"
    assert result.manifest_id == MANIFEST_ID
    assert result.planned_packages == ("AV",)
    assert "Resuming" in result.message
    assert load_state(config.storage.state_file).last_result == "PREPARED"


def test_dry_run_does_not_resume_prepared_archive(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_archive(config, "PREPARED")

    result = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=_page_fetcher,
        bundle_downloader=_bundle_downloader,
    )

    assert result.status == "NO_CHANGE"


def test_unattended_run_does_not_resume_review_required_archive(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _save_archive(config, "REVIEW_REQUIRED")

    result = run_agent_once(
        config,
        page_fetcher=_page_fetcher,
        bundle_downloader=_bundle_downloader,
    )

    assert result.status == "NO_CHANGE"
