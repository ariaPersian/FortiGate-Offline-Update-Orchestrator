from __future__ import annotations

from dataclasses import dataclass

from .agent_config import AgentConfig
from .agent_orchestrator import AgentRunResult, run_agent_once
from .agent_state import load_state, save_state, utc_now
from .controlled_apply import ControlledApplyResult, run_controlled_apply
from .notifications import NotificationResult, send_telegram_message
from .runtime_policy import RuntimePolicy, load_runtime_policy
from .secret_store import get_secret, secret_environment
from .tls import build_tls_context


@dataclass(frozen=True)
class CycleResult:
    status: str
    monitor: AgentRunResult
    apply: ControlledApplyResult | None
    notifications: tuple[NotificationResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "monitor": self.monitor.to_dict(),
            "apply": self.apply.to_dict() if self.apply else None,
            "notifications": [item.to_dict() for item in self.notifications],
        }


def _apply_secret_names(config: AgentConfig) -> tuple[str, ...]:
    if config.device is None or config.apply is None:
        raise ValueError("device and apply configuration blocks are required for package apply.")
    names: list[str] = []
    if config.device.key_file is None:
        names.append(config.device.password_env)
    elif config.device.key_passphrase_env:
        names.append(config.device.key_passphrase_env)
    if config.apply.require_backup:
        names.append(config.apply.backup_password_env)
    return tuple(dict.fromkeys(name for name in names if name))


def _prepared_message(config: AgentConfig, result: AgentRunResult) -> str:
    packages = ", ".join(result.planned_packages) or "none"
    lines = [
        "FGOps discovered and prepared a new FortiGate V6.4 bundle.",
        f"Target: {config.device.expected_hostname if config.device else 'not configured'}",
        f"Manifest: {result.manifest_id}",
        f"Archive SHA-256: {result.archive_sha256}",
        f"Packages: {packages}",
        f"Execution mode: {config.execution.mode}",
    ]
    if config.execution.mode == "approval" and result.manifest_id:
        lines.extend(
            [
                "No device changes were made.",
                "Approve on the VM with:",
                (
                    "fgops-agent --config C:\\ProgramData\\FGOps\\config.yml "
                    f"approve --manifest-id {result.manifest_id}"
                ),
            ]
        )
    elif config.execution.mode == "prepare_only":
        lines.append("No device changes were made; prepare_only is active.")
    elif config.execution.mode == "unattended":
        lines.append("The unattended controlled-apply gate will run now.")
    return "\n".join(lines)


def _apply_message(config: AgentConfig, result: ControlledApplyResult) -> str:
    packages = ", ".join(
        f"{item.kind}={item.status.value}" for item in result.package_results
    )
    return "\n".join(
        [
            f"FGOps controlled apply completed: {result.status}",
            f"Target: {config.device.expected_hostname if config.device else 'unknown'}",
            f"Manifest: {result.manifest_id}",
            f"Packages: {packages or 'none'}",
            f"Backup: {result.backup_path or 'not created'}",
            f"Report: {result.report_json}",
        ]
    )


def _send_notification(
    config: AgentConfig,
    policy: RuntimePolicy,
    *,
    status: str,
    text: str,
) -> NotificationResult | None:
    telegram = policy.telegram
    if not telegram.enabled or status not in telegram.notify_on:
        return None
    token = get_secret(policy.secret_store, telegram.token_secret_name)
    ssl_context = build_tls_context(config.source.tls_mode, config.source.ca_file)
    return send_telegram_message(
        bot_token=token,
        chat_id=telegram.chat_id,
        text=text,
        timeout_seconds=telegram.timeout_seconds,
        ssl_context=ssl_context,
    )


def _record_notification(
    config: AgentConfig,
    *,
    archive_sha256: str | None,
    result: NotificationResult | None,
    error: str | None = None,
) -> None:
    if not archive_sha256:
        return
    state = load_state(config.storage.state_file)
    entry = state.archives.get(archive_sha256)
    if entry is None:
        return
    entry["notification_status"] = result.status if result else ("FAILED" if error else "DISABLED")
    entry["notification_at"] = utc_now()
    entry["notification_error"] = error
    if result and result.message_id is not None:
        entry["notification_message_id"] = result.message_id
    save_state(config.storage.state_file, state)


def _notify_best_effort(
    config: AgentConfig,
    policy: RuntimePolicy,
    *,
    status: str,
    text: str,
    archive_sha256: str | None,
) -> NotificationResult | None:
    try:
        result = _send_notification(config, policy, status=status, text=text)
    except Exception as exc:
        _record_notification(
            config,
            archive_sha256=archive_sha256,
            result=None,
            error=str(exc),
        )
        return NotificationResult(provider="telegram", status="FAILED", error=str(exc))
    _record_notification(config, archive_sha256=archive_sha256, result=result)
    return result


def _retry_pending_prepared_notification(
    config: AgentConfig,
    policy: RuntimePolicy,
    monitor: AgentRunResult,
) -> NotificationResult | None:
    if not monitor.archive_sha256 or not policy.telegram.enabled:
        return None
    state = load_state(config.storage.state_file)
    entry = state.archives.get(monitor.archive_sha256) or {}
    if entry.get("notification_status") not in {None, "FAILED"}:
        return None
    manifest_id = entry.get("manifest_id")
    if not manifest_id:
        return None
    retry_result = AgentRunResult(
        status="PREPARED",
        source_page=monitor.source_page,
        download_url=monitor.download_url,
        archive_sha256=monitor.archive_sha256,
        archive_path=monitor.archive_path,
        manifest_id=str(manifest_id),
        work_dir=str(entry.get("work_dir")) if entry.get("work_dir") else None,
        planned_packages=tuple(str(item) for item in entry.get("planned_packages", [])),
        message="Prepared notification retry.",
    )
    return _notify_best_effort(
        config,
        policy,
        status="PREPARED",
        text=_prepared_message(config, retry_result),
        archive_sha256=monitor.archive_sha256,
    )


def run_cycle(config: AgentConfig) -> CycleResult:
    policy = load_runtime_policy(config.config_path, config.storage.root)
    notifications: list[NotificationResult] = []
    try:
        monitor = run_agent_once(config, dry_run=False)
    except Exception as exc:
        failed = AgentRunResult(
            status="FAILED",
            source_page=config.source.page_url,
            download_url="",
            message=str(exc),
        )
        notification = _notify_best_effort(
            config,
            policy,
            status="FAILED",
            text=f"FGOps monitor failed for {config.source.page_url}: {exc}",
            archive_sha256=None,
        )
        if notification:
            notifications.append(notification)
        raise

    if monitor.status == "NO_CHANGE":
        retry = _retry_pending_prepared_notification(config, policy, monitor)
        if retry:
            notifications.append(retry)
        overall = "WARNING" if any(item.status == "FAILED" for item in notifications) else "NO_CHANGE"
        return CycleResult(overall, monitor, None, tuple(notifications))

    if monitor.status != "PREPARED" or not monitor.manifest_id:
        return CycleResult(monitor.status, monitor, None, tuple(notifications))

    prepared_notification = _notify_best_effort(
        config,
        policy,
        status="PREPARED",
        text=_prepared_message(config, monitor),
        archive_sha256=monitor.archive_sha256,
    )
    if prepared_notification:
        notifications.append(prepared_notification)

    apply_result: ControlledApplyResult | None = None
    if config.execution.mode == "unattended":
        with secret_environment(policy.secret_store, _apply_secret_names(config)):
            apply_result = run_controlled_apply(config, manifest_id=monitor.manifest_id)
        final_notification = _notify_best_effort(
            config,
            policy,
            status=apply_result.status,
            text=_apply_message(config, apply_result),
            archive_sha256=monitor.archive_sha256,
        )
        if final_notification:
            notifications.append(final_notification)

    if apply_result is not None:
        overall = apply_result.status
    elif any(item.status == "FAILED" for item in notifications):
        overall = "PREPARED_WITH_NOTIFICATION_ERROR"
    else:
        overall = "PREPARED"
    return CycleResult(overall, monitor, apply_result, tuple(notifications))


def approve_manifest(config: AgentConfig, manifest_id: str) -> CycleResult:
    if config.execution.mode != "approval":
        raise ValueError("The approve command requires execution.mode=approval.")
    policy = load_runtime_policy(config.config_path, config.storage.root)
    with secret_environment(policy.secret_store, _apply_secret_names(config)):
        apply_result = run_controlled_apply(
            config,
            manifest_id=manifest_id,
            approval_manifest=manifest_id,
        )
    state = load_state(config.storage.state_file)
    archive_sha256 = next(
        (
            archive_hash
            for archive_hash, entry in state.archives.items()
            if entry.get("manifest_id") == manifest_id
        ),
        None,
    )
    notification = _notify_best_effort(
        config,
        policy,
        status=apply_result.status,
        text=_apply_message(config, apply_result),
        archive_sha256=archive_sha256,
    )
    placeholder = AgentRunResult(
        status="NO_CHANGE",
        source_page=config.source.page_url,
        download_url="",
        archive_sha256=archive_sha256,
        manifest_id=manifest_id,
        message="Manual approval apply.",
    )
    return CycleResult(
        apply_result.status,
        placeholder,
        apply_result,
        (notification,) if notification else (),
    )


def send_notification_test(config: AgentConfig) -> NotificationResult:
    policy = load_runtime_policy(config.config_path, config.storage.root)
    if not policy.telegram.enabled:
        raise ValueError("Telegram notifications are not enabled in config.yml.")
    result = _send_notification(
        config,
        policy,
        status="PREPARED",
        text="FGOps Telegram notification test succeeded.",
    )
    if result is None:
        raise ValueError("PREPARED is not included in notifications.telegram.notify_on.")
    return result
