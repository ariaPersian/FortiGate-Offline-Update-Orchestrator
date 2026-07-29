from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agent_config import AgentConfig
from .agent_state import load_state, save_state, utc_now
from .downloader import DownloadResult, download_bundle
from .inventory import build_manifest
from .source_monitor import DiscoveredLink, discover_download_link, fetch_page
from .tls import build_tls_context


@dataclass(frozen=True)
class AgentRunResult:
    status: str
    source_page: str
    download_url: str
    archive_sha256: str | None = None
    payload_sha256: str | None = None
    archive_path: str | None = None
    manifest_id: str | None = None
    work_dir: str | None = None
    planned_packages: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "source_page": self.source_page,
            "download_url": self.download_url,
            "archive_sha256": self.archive_sha256,
            "payload_sha256": self.payload_sha256,
            "archive_path": self.archive_path,
            "manifest_id": self.manifest_id,
            "work_dir": self.work_dir,
            "planned_packages": list(self.planned_packages),
            "message": self.message,
        }


PageFetcher = Callable[..., str]
BundleDownloader = Callable[..., DownloadResult]


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _payload_sha256(packages: list[dict[str, object]], payload_kinds: set[str]) -> str | None:
    selected: list[tuple[str, str]] = []
    for item in packages:
        kind = str(item.get("kind") or "")
        package_hash = str(item.get("sha256") or "")
        if kind in payload_kinds and package_hash:
            selected.append((kind, package_hash))
    if not selected or {kind for kind, _package_hash in selected} != payload_kinds:
        return None
    material = "\n".join(f"{kind}:{package_hash}" for kind, package_hash in sorted(selected))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _entry_payload_sha256(entry: dict[str, object], payload_kinds: set[str]) -> str | None:
    recorded = entry.get("payload_sha256")
    recorded_kinds_raw = entry.get("payload_kinds") or entry.get("planned_packages") or []
    recorded_kinds = {str(item) for item in recorded_kinds_raw} if isinstance(
        recorded_kinds_raw, list
    ) else set()
    if recorded and recorded_kinds == payload_kinds:
        return str(recorded)

    work_dir = entry.get("work_dir")
    if not work_dir:
        return None
    manifest_path = Path(str(work_dir)) / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    packages = raw.get("packages") if isinstance(raw, dict) else None
    if not isinstance(packages, list):
        return None
    normalized = [item for item in packages if isinstance(item, dict)]
    return _payload_sha256(normalized, payload_kinds)


def _find_applied_payload(
    state,
    *,
    payload_sha256: str,
    payload_kinds: set[str],
    exclude_archive_sha256: str,
) -> tuple[str, dict[str, object]] | None:
    for archive_hash, entry in state.archives.items():
        if archive_hash == exclude_archive_sha256:
            continue
        if entry.get("status") not in {"APPLIED", "CONTENT_DUPLICATE"}:
            continue
        candidate = _entry_payload_sha256(entry, payload_kinds)
        if candidate:
            entry["payload_sha256"] = candidate
            entry["payload_kinds"] = sorted(payload_kinds)
        if candidate == payload_sha256:
            return archive_hash, entry
    return None


def run_agent_once(
    config: AgentConfig,
    *,
    dry_run: bool = False,
    page_fetcher: PageFetcher = fetch_page,
    bundle_downloader: BundleDownloader = download_bundle,
) -> AgentRunResult:
    config.storage.create_directories()
    state = load_state(config.storage.state_file)
    state.last_run_at = utc_now()
    state.last_error = None

    try:
        ssl_context = build_tls_context(config.source.tls_mode, config.source.ca_file)
        page_html = page_fetcher(
            config.source.page_url,
            timeout_seconds=config.source.timeout_seconds,
            user_agent=config.source.user_agent,
            ssl_context=ssl_context,
        )
        discovered: DiscoveredLink = discover_download_link(
            page_html,
            config.source.page_url,
            config.source.link_text_regex,
        )
        downloaded = bundle_downloader(
            discovered.url,
            config.storage.incoming,
            timeout_seconds=config.source.timeout_seconds,
            max_download_bytes=config.source.max_download_bytes,
            user_agent=config.source.user_agent,
            ssl_context=ssl_context,
        )

        if state.has_successful_archive(downloaded.sha256):
            entry = state.archives.get(downloaded.sha256) or {}
            resumable_unattended = (
                config.execution.mode == "unattended"
                and not dry_run
                and entry.get("status") == "PREPARED"
                and bool(entry.get("manifest_id"))
                and bool(entry.get("work_dir"))
            )
            if resumable_unattended:
                state.last_result = "PREPARED"
                save_state(config.storage.state_file, state)
                return AgentRunResult(
                    status="PREPARED",
                    source_page=config.source.page_url,
                    download_url=downloaded.source_url,
                    archive_sha256=downloaded.sha256,
                    payload_sha256=(
                        str(entry.get("payload_sha256")) if entry.get("payload_sha256") else None
                    ),
                    archive_path=str(entry.get("archive_path") or downloaded.path),
                    manifest_id=str(entry["manifest_id"]),
                    work_dir=str(entry["work_dir"]),
                    planned_packages=tuple(
                        str(item) for item in entry.get("planned_packages", [])
                    ),
                    message=(
                        "Resuming a previously prepared archive for unattended controlled apply."
                    ),
                )

            state.last_result = "NO_CHANGE"
            save_state(config.storage.state_file, state)
            return AgentRunResult(
                status="NO_CHANGE",
                source_page=config.source.page_url,
                download_url=downloaded.source_url,
                archive_sha256=downloaded.sha256,
                payload_sha256=(
                    str(entry.get("payload_sha256")) if entry.get("payload_sha256") else None
                ),
                archive_path=str(downloaded.path),
                manifest_id=str(entry.get("manifest_id")) if entry.get("manifest_id") else None,
                work_dir=str(entry.get("work_dir")) if entry.get("work_dir") else None,
                planned_packages=tuple(str(item) for item in entry.get("planned_packages", [])),
                message="The archive hash was already handled successfully.",
            )

        work_dir = config.storage.quarantine / downloaded.sha256[:16]
        manifest = build_manifest(downloaded.path, work_dir, config.package_map)
        unknown = [item.filename for item in manifest.packages if item.kind.value == "UNKNOWN"]
        if unknown and config.execution.reject_unknown_packages:
            raise ValueError(f"Unknown package types were found: {', '.join(unknown)}")

        enabled = set(config.execution.enabled_packages)
        planned = tuple(
            item.kind.value
            for item in manifest.packages
            if item.kind.value != "UNKNOWN" and item.kind.value in enabled
        )
        if not planned:
            raise ValueError("The bundle contains no enabled package type.")
        payload_kinds = set(planned)

        manifest_packages = [item.to_dict() for item in manifest.packages]
        payload_sha256 = _payload_sha256(manifest_packages, payload_kinds)
        if payload_sha256 is None:
            raise ValueError("Unable to calculate enabled package payload SHA-256.")

        duplicate = _find_applied_payload(
            state,
            payload_sha256=payload_sha256,
            payload_kinds=payload_kinds,
            exclude_archive_sha256=downloaded.sha256,
        )
        if duplicate is not None:
            original_archive_hash, original_entry = duplicate
            state.archives[downloaded.sha256] = {
                "status": "CONTENT_DUPLICATE",
                "prepared_at": utc_now(),
                "source_url": downloaded.source_url,
                "archive_path": str(downloaded.path),
                "payload_sha256": payload_sha256,
                "payload_kinds": sorted(payload_kinds),
                "duplicate_of_archive_sha256": original_archive_hash,
                "duplicate_of_manifest_id": original_entry.get("manifest_id"),
                "planned_packages": list(planned),
                "notification_status": "DISABLED",
            }
            state.last_result = "NO_CONTENT_CHANGE"
            save_state(config.storage.state_file, state)
            shutil.rmtree(work_dir, ignore_errors=True)
            return AgentRunResult(
                status="NO_CONTENT_CHANGE",
                source_page=config.source.page_url,
                download_url=downloaded.source_url,
                archive_sha256=downloaded.sha256,
                payload_sha256=payload_sha256,
                archive_path=str(downloaded.path),
                manifest_id=(
                    str(original_entry.get("manifest_id"))
                    if original_entry.get("manifest_id")
                    else None
                ),
                work_dir=None,
                planned_packages=planned,
                message=(
                    "The ZIP archive bytes changed, but the enabled package payload is identical "
                    "to a previously applied payload. SSH, backup, TFTP, and restore were skipped."
                ),
            )

        plan = {
            "schema_version": 1,
            "generated_at": utc_now(),
            "dry_run": dry_run,
            "execution_mode": config.execution.mode,
            "source": {
                "page_url": config.source.page_url,
                "download_url": downloaded.source_url,
                "link_text": discovered.text,
                "link_context": discovered.context,
                "tls_mode": config.source.tls_mode,
            },
            "archive": {
                "path": str(downloaded.path),
                "sha256": downloaded.sha256,
                "size": downloaded.size,
                "content_type": downloaded.content_type,
            },
            "payload_sha256": payload_sha256,
            "payload_kinds": sorted(payload_kinds),
            "manifest_id": manifest.manifest_id,
            "planned_packages": list(planned),
            "device_execution_enabled": False,
            "safety_note": (
                "Preparation never changes the FortiGate. The separate cycle/apply command "
                "enforces execution policy, pinned SSH, mandatory backup, and temporary TFTP."
            ),
        }
        _write_json(work_dir / "agent-plan.json", plan)

        state.archives[downloaded.sha256] = {
            "status": "PREPARED",
            "prepared_at": utc_now(),
            "source_url": downloaded.source_url,
            "archive_path": str(downloaded.path),
            "payload_sha256": payload_sha256,
            "payload_kinds": sorted(payload_kinds),
            "manifest_id": manifest.manifest_id,
            "work_dir": str(work_dir),
            "planned_packages": list(planned),
            "notification_status": None,
        }
        state.last_result = "PREPARED"
        save_state(config.storage.state_file, state)

        if dry_run:
            message = "Bundle prepared successfully; dry-run performed no device changes."
        elif config.execution.mode == "prepare_only":
            message = "Bundle prepared successfully; prepare_only performed no device changes."
        elif config.execution.mode == "approval":
            message = "Bundle prepared successfully and is awaiting explicit manifest approval."
        else:
            message = "Bundle prepared successfully and is eligible for unattended controlled apply."
        return AgentRunResult(
            status="PREPARED",
            source_page=config.source.page_url,
            download_url=downloaded.source_url,
            archive_sha256=downloaded.sha256,
            payload_sha256=payload_sha256,
            archive_path=str(downloaded.path),
            manifest_id=manifest.manifest_id,
            work_dir=str(work_dir),
            planned_packages=planned,
            message=message,
        )
    except Exception as exc:
        state.last_result = "FAILED"
        state.last_error = str(exc)
        save_state(config.storage.state_file, state)
        raise
