from __future__ import annotations

from datetime import datetime, timezone

from fgops.operator_logging import (
    OperatorChecklist,
    close_operator_logging,
    configure_operator_logging,
    default_operator_steps,
)


def test_operator_checklist_writes_utf8_todo_success_and_failure(tmp_path):
    now = datetime(2026, 7, 28, 8, 30, tzinfo=timezone.utc)
    logger = configure_operator_logging(
        tmp_path,
        logger_name="fgops.test.operator.checklist",
        clock=lambda: now,
    )
    checklist = OperatorChecklist(
        logger,
        command="cycle",
        steps=(
            ("source", "بررسی منبع به‌روزرسانی"),
            ("backup", "تهیه نسخه پشتیبان"),
        ),
        run_id="test-run-001",
    )

    checklist.start()
    checklist.success("source", "بسته شناسایی شد")
    checklist.fail("backup", "فایل پشتیبان دریافت نشد")
    checklist.finish(
        exit_code=2,
        overall_status="FAILED",
        operator_action="اتصال TFTP را بررسی کنید.",
    )
    close_operator_logging(logger)

    path = tmp_path / "logs" / "fgops-operator-2026-07-28.log"
    text = path.read_text(encoding="utf-8")
    assert "فهرست مراحل (ToDo)" in text
    assert "⬜ [1/2] بررسی منبع به‌روزرسانی" in text
    assert "✅ [1/2] بررسی منبع به‌روزرسانی" in text
    assert "❌ [2/2] تهیه نسخه پشتیبان" in text
    assert "❌ نتیجه نهایی: FAILED | کد خروج: 2" in text
    assert "اقدام پیشنهادی اپراتور" in text


def test_operator_retention_does_not_remove_technical_logs(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    expired_operator = logs_dir / "fgops-operator-2026-07-24.log"
    retained_operator = logs_dir / "fgops-operator-2026-07-27.log"
    technical_log = logs_dir / "fgops-2026-07-24.log"
    expired_operator.write_text("expired\n", encoding="utf-8")
    retained_operator.write_text("retained\n", encoding="utf-8")
    technical_log.write_text("technical\n", encoding="utf-8")

    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    logger = configure_operator_logging(
        tmp_path,
        logger_name="fgops.test.operator.retention",
        retention_days=2,
        clock=lambda: now,
    )
    checklist = OperatorChecklist(
        logger,
        command="status",
        steps=(("report", "ثبت وضعیت"),),
        run_id="test-run-002",
    )
    checklist.start()
    checklist.success("report")
    checklist.finish(exit_code=0, overall_status="SUCCESS")
    close_operator_logging(logger)

    assert not expired_operator.exists()
    assert retained_operator.exists()
    assert technical_log.exists()
    assert (logs_dir / "fgops-operator-2026-07-28.log").exists()


def test_cycle_operator_plan_contains_safety_and_apply_stages():
    keys = {key for key, _label in default_operator_steps("cycle")}

    assert {
        "startup",
        "config",
        "storage",
        "source",
        "prepare",
        "notification",
        "execution_gate",
        "preflight",
        "backup",
        "packages",
        "verification",
        "report",
    } <= keys
