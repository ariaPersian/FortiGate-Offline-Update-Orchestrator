from __future__ import annotations

from datetime import datetime, timezone

from fgops.daily_logging import close_daily_logging, configure_daily_logging, log_event


def test_daily_logging_creates_utf8_date_named_file(tmp_path):
    now = datetime(2026, 7, 27, 8, 30, tzinfo=timezone.utc)
    logger = configure_daily_logging(
        tmp_path,
        logger_name="fgops.test.daily.create",
        clock=lambda: now,
    )

    log_event(logger, "cycle.completed", status="SUCCESS_WITH_WARNING", message="آزمون")
    close_daily_logging(logger)

    path = tmp_path / "logs" / "fgops-2026-07-27.log"
    text = path.read_text(encoding="utf-8")
    assert '"event": "cycle.completed"' in text
    assert '"status": "SUCCESS_WITH_WARNING"' in text
    assert "آزمون" in text


def test_daily_logging_switches_files_when_local_date_changes(tmp_path):
    current = [datetime(2026, 7, 27, 23, 59, tzinfo=timezone.utc)]
    logger = configure_daily_logging(
        tmp_path,
        logger_name="fgops.test.daily.rollover",
        clock=lambda: current[0],
    )

    log_event(logger, "before_midnight")
    current[0] = datetime(2026, 7, 28, 0, 1, tzinfo=timezone.utc)
    log_event(logger, "after_midnight")
    close_daily_logging(logger)

    first = (tmp_path / "logs" / "fgops-2026-07-27.log").read_text(encoding="utf-8")
    second = (tmp_path / "logs" / "fgops-2026-07-28.log").read_text(encoding="utf-8")
    assert '"event": "before_midnight"' in first
    assert '"event": "after_midnight"' in second


def test_daily_logging_removes_files_outside_retention_window(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    expired = logs_dir / "fgops-2026-07-24.log"
    retained = logs_dir / "fgops-2026-07-25.log"
    expired.write_text("expired\n", encoding="utf-8")
    retained.write_text("retained\n", encoding="utf-8")

    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    logger = configure_daily_logging(
        tmp_path,
        logger_name="fgops.test.daily.retention",
        retention_days=3,
        clock=lambda: now,
    )
    log_event(logger, "retention.checked")
    close_daily_logging(logger)

    assert not expired.exists()
    assert retained.exists()
    assert (logs_dir / "fgops-2026-07-27.log").exists()
