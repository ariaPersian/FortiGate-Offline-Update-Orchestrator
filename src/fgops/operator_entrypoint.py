from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import agent_cli
from . import entrypoint as _runtime_guards  # noqa: F401
from .operator_logging import (
    OperatorChecklist,
    configure_operator_logging,
    default_operator_steps,
)

_FAILED_PACKAGE_STATES = {"FAILED", "FAILED_UNCONFIRMED"}
_WARNING_PACKAGE_STATES = {"SUCCESS_WITH_WARNING", "SKIPPED_NO_UPDATE"}


def _payload(value: Any) -> dict[str, Any]:
    raw = agent_cli._payload(value)
    return raw if isinstance(raw, dict) else {"value": raw}


def _mark_by_status(
    checklist: OperatorChecklist,
    key: str,
    status: str,
    detail: object | None = None,
) -> None:
    normalized = status.upper()
    if "FAILED" in normalized:
        checklist.fail(key, detail or status)
    elif "WARNING" in normalized or "ERROR" in normalized:
        checklist.warning(key, detail or status)
    else:
        checklist.success(key, detail or status)


def _record_packages(checklist: OperatorChecklist, package_results: list[dict[str, Any]]) -> None:
    if not package_results:
        checklist.warning("packages", "هیچ نتیجه‌ای برای بسته‌ها ثبت نشد.")
        return

    states: list[str] = []
    descriptions: list[str] = []
    for item in package_results:
        kind = str(item.get("kind") or "UNKNOWN")
        filename = str(item.get("filename") or "-")
        status = str(item.get("status") or "UNKNOWN").upper()
        reason = str(item.get("reason") or "")
        states.append(status)
        descriptions.append(f"{kind}={status}")
        key = f"package:{kind}:{filename}"
        checklist.add_step(key, f"بسته {kind}: {filename}")
        if status in _FAILED_PACKAGE_STATES:
            checklist.fail(key, reason or status)
        elif status in _WARNING_PACKAGE_STATES:
            checklist.warning(key, reason or status)
        else:
            checklist.success(key, reason or status)

    summary = ", ".join(descriptions)
    if any(state in _FAILED_PACKAGE_STATES for state in states):
        checklist.fail("packages", summary)
    elif any(state in _WARNING_PACKAGE_STATES for state in states):
        checklist.warning("packages", summary)
    else:
        checklist.success("packages", summary)


def _record_apply(
    checklist: OperatorChecklist,
    apply_result: dict[str, Any] | None,
    *,
    require_backup: bool,
) -> None:
    if not apply_result:
        checklist.skip("preflight", "عملیات اعمال اجرا نشد.")
        checklist.skip("backup", "عملیات اعمال اجرا نشد.")
        checklist.skip("packages", "عملیات اعمال اجرا نشد.")
        checklist.skip("verification", "عملیات اعمال اجرا نشد.")
        return

    status = str(apply_result.get("status") or "UNKNOWN")
    checklist.success("preflight", "بررسی پیش از اعمال با موفقیت عبور کرده است.")

    backup_path = apply_result.get("backup_path")
    if backup_path:
        checklist.success("backup", backup_path)
    elif require_backup:
        checklist.fail("backup", "پشتیبان الزامی است اما مسیر فایل ثبت نشده است.")
    else:
        checklist.skip("backup", "طبق تنظیمات، پشتیبان الزامی نبود.")

    raw_packages = apply_result.get("package_results")
    packages = [item for item in raw_packages if isinstance(item, dict)] if isinstance(raw_packages, list) else []
    _record_packages(checklist, packages)

    _mark_by_status(checklist, "verification", status, f"نتیجه اعمال: {status}")
    report_json = apply_result.get("report_json")
    report_text = apply_result.get("report_text")
    if report_json or report_text:
        checklist.success("report", f"JSON={report_json or '-'} | TEXT={report_text or '-'}")
    else:
        checklist.warning("report", "مسیر گزارش نهایی در نتیجه ثبت نشده است.")


def _record_monitor(checklist: OperatorChecklist, monitor: dict[str, Any]) -> str:
    status = str(monitor.get("status") or "UNKNOWN")
    archive_sha256 = monitor.get("archive_sha256")
    source_detail = monitor.get("download_url") or monitor.get("source_page")
    checklist.success("source", source_detail)

    if status == "PREPARED":
        manifest_id = monitor.get("manifest_id")
        packages = ", ".join(str(item) for item in monitor.get("planned_packages", []))
        checklist.success(
            "prepare",
            f"Manifest={manifest_id or '-'} | SHA-256={archive_sha256 or '-'} | بسته‌ها={packages or '-'}",
        )
    elif status == "NO_CHANGE":
        checklist.skip("prepare", "بسته از قبل آماده شده و تغییر جدیدی وجود ندارد.")
    else:
        _mark_by_status(checklist, "prepare", status, monitor.get("message") or status)
    return status


def _record_notifications(
    checklist: OperatorChecklist,
    notifications: list[dict[str, Any]],
) -> None:
    if not notifications:
        checklist.skip("notification", "طبق سیاست فعلی اعلانی ارسال نشد.")
        return
    states = [str(item.get("status") or "UNKNOWN").upper() for item in notifications]
    detail = ", ".join(
        f"{item.get('provider', 'provider')}={item.get('status', 'UNKNOWN')}"
        for item in notifications
    )
    if any(state == "FAILED" for state in states):
        checklist.warning("notification", detail)
    else:
        checklist.success("notification", detail)


def _record_result(
    checklist: OperatorChecklist,
    *,
    command: str,
    payload: dict[str, Any],
    exit_code: int,
    config: Any | None,
) -> tuple[str, str | None]:
    status = str(payload.get("status") or ("SUCCESS" if exit_code == 0 else "FAILED"))
    execution_mode = getattr(getattr(config, "execution", None), "mode", None)
    apply_config = getattr(config, "apply", None)
    require_backup = bool(getattr(apply_config, "require_backup", False))
    operator_action: str | None = None

    if command == "run":
        _record_monitor(checklist, payload)
        checklist.success("report", payload.get("message") or status)

    elif command == "cycle":
        monitor = payload.get("monitor") if isinstance(payload.get("monitor"), dict) else {}
        monitor_status = _record_monitor(checklist, monitor)
        raw_notifications = payload.get("notifications")
        notifications = (
            [item for item in raw_notifications if isinstance(item, dict)]
            if isinstance(raw_notifications, list)
            else []
        )
        _record_notifications(checklist, notifications)
        apply_result = payload.get("apply") if isinstance(payload.get("apply"), dict) else None

        if monitor_status == "NO_CHANGE":
            checklist.skip("execution_gate", "نسخه جدیدی برای اعمال وجود ندارد.")
            _record_apply(checklist, None, require_backup=require_backup)
        elif apply_result:
            checklist.success("execution_gate", f"حالت اجرا: {execution_mode or '-'}")
            _record_apply(checklist, apply_result, require_backup=require_backup)
        elif execution_mode == "approval":
            checklist.warning("execution_gate", "بسته آماده است و در انتظار تایید اپراتور قرار دارد.")
            _record_apply(checklist, None, require_backup=require_backup)
            checklist.success("report", monitor.get("message") or status)
            operator_action = "Manifest آماده‌شده را بررسی و فقط در صورت تایید، فرمان approve را اجرا کنید."
        elif execution_mode == "prepare_only":
            checklist.skip("execution_gate", "حالت prepare_only فعال است؛ تغییری روی دستگاه انجام نشد.")
            _record_apply(checklist, None, require_backup=require_backup)
            checklist.success("report", monitor.get("message") or status)
        else:
            _mark_by_status(checklist, "execution_gate", status, status)
            _record_apply(checklist, None, require_backup=require_backup)
            checklist.success("report", monitor.get("message") or status)

    elif command == "apply":
        checklist.success("execution_gate", f"Manifest={payload.get('manifest_id', '-')}")
        _record_apply(checklist, payload, require_backup=require_backup)

    elif command == "approve":
        checklist.success("execution_gate", "تایید Manifest پذیرفته شد.")
        apply_result = payload.get("apply") if isinstance(payload.get("apply"), dict) else None
        _record_apply(checklist, apply_result, require_backup=require_backup)
        raw_notifications = payload.get("notifications")
        notifications = (
            [item for item in raw_notifications if isinstance(item, dict)]
            if isinstance(raw_notifications, list)
            else []
        )
        _record_notifications(checklist, notifications)

    elif command == "preflight":
        _mark_by_status(checklist, "preflight", status, status)
        evidence = payload.get("evidence_json") or payload.get("report_json")
        checklist.success("report", evidence or "شواهد بررسی ثبت شد.")

    elif command == "backup-test":
        checklist.success("preflight", payload.get("preflight_evidence"))
        backup_path = payload.get("backup_path")
        if backup_path:
            checklist.success("backup", backup_path)
        else:
            checklist.fail("backup", "مسیر فایل پشتیبان ثبت نشده است.")
        backup_size = int(payload.get("backup_size") or 0)
        backup_sha256 = payload.get("backup_sha256")
        if backup_size > 0 and backup_sha256:
            checklist.success("verification", f"Size={backup_size} | SHA-256={backup_sha256}")
        else:
            checklist.fail("verification", "اندازه یا SHA-256 معتبر ثبت نشده است.")
        checklist.success("report", payload.get("report_json") or payload.get("report_text"))

    elif command == "notify-test":
        _mark_by_status(checklist, "notification", status, status)
        checklist.success("report", "نتیجه آزمون اعلان ثبت شد.")

    elif command == "scan-host-key":
        checklist.skip("config", "این فرمان بدون بارگذاری config.yml اجرا می‌شود.")
        checklist.skip("storage", "این فرمان به فضای ذخیره‌سازی اصلی نیاز ندارد.")
        checklist.success("scan", payload.get("sha256") or payload.get("fingerprint"))
        checklist.success("report", "اثرانگشت کلید میزبان نمایش داده شد.")

    elif command == "init":
        checklist.skip("config", "این فرمان فایل تنظیمات را ایجاد می‌کند.")
        checklist.success("storage", Path(str(payload.get("config", "."))).parent)
        checklist.success("initialize", payload.get("config"))
        checklist.success("report", payload.get("package_map"))

    elif command == "validate-config":
        checklist.success("report", payload.get("config") or "تنظیمات معتبر است.")

    elif command == "status":
        checklist.success("report", f"آخرین وضعیت: {payload.get('last_result', status)}")

    elif command == "secret":
        checklist.success("secret", "عملیات مخزن رمزها بدون نمایش مقدار محرمانه انجام شد.")

    else:
        _mark_by_status(checklist, "operation", status, status)

    if exit_code != 0 and operator_action is None:
        operator_action = (
            "مراحل دارای ❌ یا ⚠️ را بررسی کنید و برای جزئیات فنی به فایل "
            "fgops-YYYY-MM-DD.log در همین پوشه مراجعه کنید."
        )
    elif status == "NO_CHANGE":
        operator_action = "اقدامی لازم نیست؛ بسته جدیدی شناسایی نشده است."
    elif "NOTIFICATION_ERROR" in status:
        operator_action = "تنظیمات و دسترسی Telegram را بررسی کنید؛ عملیات اصلی ثبت شده است."
    return status, operator_action


def main() -> int:
    argv = sys.argv[1:]
    args = agent_cli.build_parser().parse_args(argv)
    bootstrap_root = args.config.expanduser().resolve().parent
    operator_logger = configure_operator_logging(bootstrap_root)
    checklist = OperatorChecklist(
        operator_logger,
        command=args.command,
        steps=default_operator_steps(args.command),
    )
    checklist.start()
    checklist.success("startup", f"config={args.config.expanduser().resolve()}")

    original_emit_json = agent_cli._emit_json
    original_load_config = agent_cli.load_agent_config
    loaded_config: Any | None = None
    observed_status = "FAILED"
    operator_action: str | None = None

    def load_config_with_operator_log(path):
        nonlocal loaded_config, operator_logger
        checklist.begin("config")
        try:
            loaded_config = original_load_config(path)
        except Exception as exc:
            checklist.fail("config", exc)
            raise
        checklist.success("config", loaded_config.config_path)
        operator_logger = configure_operator_logging(loaded_config.storage.root)
        checklist.rebind_logger(operator_logger)
        checklist.begin("storage")
        try:
            loaded_config.storage.create_directories()
        except Exception as exc:
            checklist.fail("storage", exc)
            raise
        checklist.success("storage", loaded_config.storage.root)
        return loaded_config

    def emit_json_with_operator_log(
        logger,
        *,
        command: str,
        event: str,
        value: Any,
        exit_code: int = 0,
    ) -> int:
        nonlocal observed_status, operator_action
        result_payload = _payload(value)
        observed_status, operator_action = _record_result(
            checklist,
            command=command,
            payload=result_payload,
            exit_code=exit_code,
            config=loaded_config,
        )
        return original_emit_json(
            logger,
            command=command,
            event=event,
            value=value,
            exit_code=exit_code,
        )

    agent_cli.load_agent_config = load_config_with_operator_log
    agent_cli._emit_json = emit_json_with_operator_log
    try:
        exit_code = int(agent_cli.main(argv))
        if exit_code != 0 and observed_status == "FAILED":
            checklist.fail_first_unfinished(
                "عملیات پیش از تولید نتیجه متوقف شد؛ جزئیات در لاگ فنی ثبت شده است."
            )
        elif exit_code == 0 and observed_status == "FAILED":
            observed_status = "SUCCESS"
        checklist.finish(
            exit_code=exit_code,
            overall_status=observed_status,
            operator_action=operator_action,
        )
        return exit_code
    finally:
        agent_cli.load_agent_config = original_load_config
        agent_cli._emit_json = original_emit_json


if __name__ == "__main__":
    raise SystemExit(main())
