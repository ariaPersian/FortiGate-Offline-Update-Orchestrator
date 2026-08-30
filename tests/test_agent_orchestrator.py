from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from urllib.error import URLError

import pytest

from fgops.agent_config import AgentConfig, ExecutionConfig, SourceConfig, StorageConfig
from fgops.agent_orchestrator import run_agent_once
from fgops.agent_state import load_state, save_state
from fgops.downloader import DownloadResult


def _package_map(path: Path) -> Path:
    path.write_text(
        """
packages:
  - pattern: '(?i)AV\\.pkg$'
    kind: AV
    restore_family: av
    safe_for_deferred_apply: true
    expected_objects: [Virus Definitions]
  - pattern: '(?i)Botnet-Domain\\.pkg$'
    kind: BOTNET
    restore_family: other-objects
    safe_for_deferred_apply: false
    expected_objects: [Botnet Domain Database]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _bundle(
    path: Path,
    filename: str = "vendor-AV.pkg",
    *,
    payload: bytes = b"signed-package-placeholder",
    archive_comment: bytes = b"",
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(filename, payload)
        archive.comment = archive_comment
    return path


def _config(tmp_path: Path) -> AgentConfig:
    root = tmp_path / "runtime"
    return AgentConfig(
        config_path=tmp_path / "config.yml",
        package_map=_package_map(tmp_path / "package-map.yml"),
        source=SourceConfig(
            page_url="https://example.test/updates/",
            link_text_regex=r"(?i)Fortigate\s+V6\.4",
        ),
        storage=StorageConfig(
            root=root,
            incoming=root / "incoming",
            quarantine=root / "quarantine",
            reports=root / "reports",
            state_file=root / "state" / "agent-state.json",
        ),
        execution=ExecutionConfig(mode="prepare_only", enabled_packages=("AV",)),
    )


def _fake_fetch(*args, **kwargs) -> str:
    return '<li>Fortigate V6.4 – <a href="/bundle.zip">دانلود</a></li>'


def _downloader_for(source: Path):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    def fake_download(url: str, destination_dir: Path, **kwargs) -> DownloadResult:
        destination_dir.mkdir(parents=True, exist_ok=True)
        target = destination_dir / f"{digest[:16]}-bundle.zip"
        if not target.exists():
            shutil.copy2(source, target)
        return DownloadResult(
            path=target,
            sha256=digest,
            size=target.stat().st_size,
            source_url="https://example.test/bundle.zip",
            content_type="application/zip",
        )

    return fake_download


def test_prepares_new_bundle_then_reports_no_change(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "source.zip")
    config = _config(tmp_path)

    first = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=_fake_fetch,
        bundle_downloader=_downloader_for(source),
    )
    assert first.status == "PREPARED"
    assert first.planned_packages == ("AV",)
    assert first.payload_sha256 is not None
    assert (Path(first.work_dir) / "manifest.json").is_file()
    assert (Path(first.work_dir) / "agent-plan.json").is_file()

    second = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=_fake_fetch,
        bundle_downloader=_downloader_for(source),
    )
    assert second.status == "NO_CHANGE"
    state = load_state(config.storage.state_file)
    assert state.last_result == "NO_CHANGE"


def test_new_zip_with_identical_enabled_packages_skips_device_path(tmp_path: Path) -> None:
    first_source = _bundle(tmp_path / "first.zip", archive_comment=b"publisher-build-one")
    second_source = _bundle(tmp_path / "second.zip", archive_comment=b"publisher-build-two")
    assert hashlib.sha256(first_source.read_bytes()).hexdigest() != hashlib.sha256(
        second_source.read_bytes()
    ).hexdigest()

    config = _config(tmp_path)
    first = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=_fake_fetch,
        bundle_downloader=_downloader_for(first_source),
    )
    assert first.status == "PREPARED"
    assert first.archive_sha256 is not None
    assert first.payload_sha256 is not None

    state = load_state(config.storage.state_file)
    state.archives[first.archive_sha256]["status"] = "APPLIED"
    state.archives[first.archive_sha256]["apply_status"] = "SUCCESS"
    save_state(config.storage.state_file, state)

    second = run_agent_once(
        config,
        dry_run=False,
        page_fetcher=_fake_fetch,
        bundle_downloader=_downloader_for(second_source),
    )

    assert second.status == "NO_CONTENT_CHANGE"
    assert second.payload_sha256 == first.payload_sha256
    assert second.work_dir is None
    assert "SSH, backup, TFTP, and restore were skipped" in second.message

    updated = load_state(config.storage.state_file)
    assert second.archive_sha256 is not None
    duplicate = updated.archives[second.archive_sha256]
    assert duplicate["status"] == "CONTENT_DUPLICATE"
    assert duplicate["duplicate_of_archive_sha256"] == first.archive_sha256
    assert duplicate["payload_sha256"] == first.payload_sha256
    assert updated.last_result == "NO_CONTENT_CHANGE"


def test_changed_enabled_package_payload_is_prepared(tmp_path: Path) -> None:
    first_source = _bundle(tmp_path / "first.zip", payload=b"package-version-one")
    second_source = _bundle(tmp_path / "second.zip", payload=b"package-version-two")
    config = _config(tmp_path)

    first = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=_fake_fetch,
        bundle_downloader=_downloader_for(first_source),
    )
    assert first.archive_sha256 is not None
    state = load_state(config.storage.state_file)
    state.archives[first.archive_sha256]["status"] = "APPLIED"
    save_state(config.storage.state_file, state)

    second = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=_fake_fetch,
        bundle_downloader=_downloader_for(second_source),
    )
    assert second.status == "PREPARED"
    assert second.payload_sha256 != first.payload_sha256


def test_unknown_package_fails_closed(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "unknown.zip", filename="mystery.pkg")
    config = _config(tmp_path)

    with pytest.raises(ValueError, match="Unknown package"):
        run_agent_once(
            config,
            dry_run=True,
            page_fetcher=_fake_fetch,
            bundle_downloader=_downloader_for(source),
        )
    state = load_state(config.storage.state_file)
    assert state.last_result == "FAILED"


def test_duplicate_disabled_kind_does_not_block_enabled_payload(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("vendor-AV.pkg", b"av")
        archive.writestr("first-Botnet-Domain.pkg", b"botnet-one")
        archive.writestr("second-Botnet-Domain.pkg", b"botnet-two")
    config = _config(tmp_path)

    result = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=_fake_fetch,
        bundle_downloader=_downloader_for(source),
    )

    assert result.status == "PREPARED"
    assert result.planned_packages == ("AV",)
    manifest = Path(result.work_dir) / "manifest.json"
    assert "disabled kind BOTNET" in manifest.read_text(encoding="utf-8")


def test_transient_source_timeout_is_retried(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "source.zip")
    config = _config(tmp_path)
    attempts = 0
    delays: list[float] = []

    def flaky_fetch(*args, **kwargs) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise URLError(TimeoutError("timed out"))
        return _fake_fetch(*args, **kwargs)

    result = run_agent_once(
        config,
        dry_run=True,
        page_fetcher=flaky_fetch,
        bundle_downloader=_downloader_for(source),
        retry_sleeper=delays.append,
    )

    assert result.status == "PREPARED"
    assert attempts == 2
    assert delays == [2.0]
