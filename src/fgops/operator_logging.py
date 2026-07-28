from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .daily_logging import DailyFileHandler, LocalIsoFormatter

_OPERATOR_LOG_RE = re.compile(r"^fgops-operator-(\d{4}-\d{2}-\d{2})\.log$")

_MARKERS = {
    "TODO": "⬜",
    "RUNNING": "🔄",
    "SUCCESS": "✅",
    "WARNING": "⚠️",
    "FAILED": "❌",
    "SKIPPED": "⏭️",
}


class OperatorDailyFileHandler(DailyFileHandler):
    """Write a separate date-named UTF-8 journal for non-technical operators."""

    def path_for(self, value: date) -> Path:
        return self.logs_dir / f"fgops-operator-{value.isoformat()}.log"

    def _delete_expired_files(self, today: date) -> None:
        oldest_kept = today - timedelta(days=self.retention_days - 1)
        for path in self.logs_dir.glob("fgops-operator-*.log"):
            match = _OPERATOR_LOG_RE.fullmatch(path.name)
            if not match:
                continue
            try:
                file_date = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if file_date < oldest_kept:
                try:
                    path.unlink()
                except OSError:
                    # Operator logging must never block the update workflow.
                    continue


def configure_operator_logging(
    storage_root: Path,
    *,
    logger_name: str = "fgops.operator",
    retention_days: int = 30,
    clock=None,
) -> logging.Logger:
    """Configure the human-readable operator journal below ``<storage_root>/logs``."""

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        if isinstance(handler, OperatorDailyFileHandler):
            logger.removeHandler(handler)
            handler.close()

    handler = OperatorDailyFileHandler(
        storage_root / "logs",
        retention_days=max(1, retention_days),
        clock=clock,
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(LocalIsoFormatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    return logger


def close_operator_logging(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if isinstance(handler, OperatorDailyFileHandler):
            logger.removeHandler(handler)
            handler.close()


@dataclass
class OperatorStep:
    key: str
    label: str
    state: str = "TODO"
    detail: str | None = None


class OperatorChecklist:
    """Append a readable execution checklist without replacing the technical JSON log."""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        command: str,
        steps: Iterable[tuple[str, str]],
        run_id: str | None = None,
    ) -> None:
        self.logger = logger
        self.command = command
        self.run_id = run_id or self._new_run_id()
        self.steps = [OperatorStep(key, label) for key, label in steps]
        self._started = False
        self._finished = False

    @staticmethod
    def _new_run_id() -> str:
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        return f"{stamp}-pid{os.getpid()}"

    @staticmethod
    def _clean_detail(detail: object | None) -> str | None:
        if detail is None:
            return None
        value = " ".join(str(detail).split())
        if not value:
            return None
        return value[:500]

    def rebind_logger(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._emit("مسیر لاگ اپراتور پس از بارگذاری تنظیمات به محل اصلی منتقل شد.")

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._emit("=" * 72)
        self._emit(f"شروع اجرای جدید FGOps | فرمان: {self.command} | شناسه اجرا: {self.run_id}")
        self._emit("فهرست مراحل (ToDo):")
        for index, step in enumerate(self.steps, start=1):
            self._emit(f"  {_MARKERS['TODO']} [{index}/{len(self.steps)}] {step.label}")

    def add_step(self, key: str, label: str) -> None:
        if self._find(key) is not None:
            return
        self.steps.append(OperatorStep(key, label))
        self._emit(f"  {_MARKERS['TODO']} [جدید] {label}")

    def begin(self, key: str, detail: object | None = None) -> None:
        self._set(key, "RUNNING", detail)

    def success(self, key: str, detail: object | None = None) -> None:
        self._set(key, "SUCCESS", detail)

    def warning(self, key: str, detail: object | None = None) -> None:
        self._set(key, "WARNING", detail)

    def fail(self, key: str, detail: object | None = None) -> None:
        self._set(key, "FAILED", detail)

    def skip(self, key: str, detail: object | None = None) -> None:
        self._set(key, "SKIPPED", detail)

    def fail_first_unfinished(self, detail: object | None = None) -> None:
        step = next(
            (item for item in self.steps if item.state in {"TODO", "RUNNING"}),
            None,
        )
        if step is not None:
            self.fail(step.key, detail)

    def finish(
        self,
        *,
        exit_code: int,
        overall_status: str,
        operator_action: str | None = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        self._emit("-" * 72)
        self._emit("خلاصه نهایی مراحل:")
        for index, step in enumerate(self.steps, start=1):
            detail = f" — {step.detail}" if step.detail else ""
            self._emit(
                f"  {_MARKERS.get(step.state, _MARKERS['TODO'])} "
                f"[{index}/{len(self.steps)}] {step.label}{detail}"
            )
        final_state = "FAILED" if exit_code else "SUCCESS"
        if "WARNING" in overall_status or "NOTIFICATION_ERROR" in overall_status:
            final_state = "WARNING"
        self._emit(
            f"{_MARKERS[final_state]} نتیجه نهایی: {overall_status} | کد خروج: {exit_code}"
        )
        if operator_action:
            self._emit(f"اقدام پیشنهادی اپراتور: {self._clean_detail(operator_action)}")
        self._emit(f"پایان اجرای {self.run_id}")
        self._emit("=" * 72)

    def _find(self, key: str) -> OperatorStep | None:
        return next((item for item in self.steps if item.key == key), None)

    def _set(self, key: str, state: str, detail: object | None) -> None:
        step = self._find(key)
        if step is None:
            self.add_step(key, key)
            step = self._find(key)
        assert step is not None
        step.state = state
        step.detail = self._clean_detail(detail)
        index = self.steps.index(step) + 1
        suffix = f" — {step.detail}" if step.detail else ""
        self._emit(
            f"{_MARKERS[state]} [{index}/{len(self.steps)}] {step.label}{suffix}"
        )

    def _emit(self, message: str) -> None:
        self.logger.info("run=%s %s", self.run_id, message)


def default_operator_steps(command: str) -> tuple[tuple[str, str], ...]:
    common_start = (
        ("startup", "راه‌اندازی ربات و ایجاد شناسه اجرا"),
        ("config", "بارگذاری و اعتبارسنجی تنظیمات"),
        ("storage", "آماده‌سازی پوشه‌های کاری و لاگ"),
    )
    command_steps = {
        "cycle": (
            ("source", "بررسی منبع و شناسایی بسته به‌روزرسانی"),
            ("prepare", "دانلود، کنترل و آماده‌سازی بسته"),
            ("notification", "ارسال اعلان وضعیت"),
            ("execution_gate", "بررسی مجوز اجرای به‌روزرسانی"),
            ("backup", "تهیه نسخه پشتیبان رمزگذاری‌شده"),
            ("packages", "اعمال بسته‌ها و کنترل نتیجه"),
            ("verification", "بازبینی نهایی وضعیت FortiGate"),
            ("report", "ثبت گزارش و نتیجه نهایی"),
        ),
        "run": (
            ("source", "بررسی منبع و شناسایی بسته به‌روزرسانی"),
            ("prepare", "دانلود، کنترل و آماده‌سازی بسته"),
            ("report", "ثبت نتیجه آماده‌سازی"),
        ),
        "apply": (
            ("execution_gate", "کنترل شناسه Manifest و مجوز اجرا"),
            ("preflight", "بررسی ایمن وضعیت FortiGate پیش از اعمال"),
            ("backup", "تهیه نسخه پشتیبان رمزگذاری‌شده"),
            ("packages", "اعمال بسته‌ها و کنترل نسخه‌ها"),
            ("verification", "بازبینی نهایی وضعیت FortiGate"),
            ("report", "ثبت گزارش و نتیجه نهایی"),
        ),
        "approve": (
            ("execution_gate", "کنترل تایید اپراتور و شناسه Manifest"),
            ("preflight", "بررسی ایمن وضعیت FortiGate پیش از اعمال"),
            ("backup", "تهیه نسخه پشتیبان رمزگذاری‌شده"),
            ("packages", "اعمال بسته‌ها و کنترل نسخه‌ها"),
            ("verification", "بازبینی نهایی وضعیت FortiGate"),
            ("notification", "ارسال اعلان نتیجه"),
            ("report", "ثبت گزارش و نتیجه نهایی"),
        ),
        "preflight": (
            ("preflight", "بررسی اتصال، هویت و وضعیت FortiGate"),
            ("report", "ثبت شواهد بررسی خواندنی"),
        ),
        "backup-test": (
            ("preflight", "بررسی ایمن وضعیت FortiGate"),
            ("backup", "دریافت نسخه پشتیبان رمزگذاری‌شده"),
            ("verification", "کنترل اندازه و SHA-256 فایل پشتیبان"),
            ("report", "ثبت گزارش آزمون پشتیبان"),
        ),
        "notify-test": (
            ("notification", "ارسال پیام آزمایشی تلگرام"),
            ("report", "ثبت نتیجه آزمون اعلان"),
        ),
        "scan-host-key": (
            ("scan", "دریافت کلید میزبان SSH بدون ورود"),
            ("report", "نمایش اثرانگشت برای کنترل خارج از سامانه"),
        ),
        "validate-config": (("report", "ثبت نتیجه اعتبارسنجی تنظیمات"),),
        "status": (("report", "نمایش و ثبت آخرین وضعیت ربات"),),
        "secret": (("secret", "اجرای عملیات امن مخزن رمزها"),),
        "init": (
            ("initialize", "ایجاد تنظیمات اولیه و نقشه بسته‌ها"),
            ("report", "ثبت مسیر فایل‌های ایجادشده"),
        ),
    }
    return common_start + command_steps.get(command, (("operation", "اجرای فرمان"),))
