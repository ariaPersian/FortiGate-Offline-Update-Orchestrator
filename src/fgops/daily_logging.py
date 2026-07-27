from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

_LOG_FILE_RE = re.compile(r"^fgops-(\d{4}-\d{2}-\d{2})\.log$")
_DEFAULT_RETENTION_DAYS = 30
_DEFAULT_LEVEL = "INFO"


class LocalIsoFormatter(logging.Formatter):
    """Render log timestamps with the local UTC offset in ISO-8601 format."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        value = datetime.fromtimestamp(record.created).astimezone()
        if datefmt:
            return value.strftime(datefmt)
        return value.isoformat(timespec="seconds")


class DailyFileHandler(logging.Handler):
    """Append records to one UTF-8 file per local calendar day.

    FGOps is normally started as a short-lived Scheduled Task. A deterministic
    date-named file is therefore more reliable than relying on one long-running
    process to perform a midnight rollover.
    """

    def __init__(
        self,
        logs_dir: Path,
        *,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1.")
        self.logs_dir = logs_dir.expanduser().resolve()
        self.retention_days = retention_days
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._stream: TextIO | None = None
        self._stream_date: date | None = None
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._delete_expired_files(self._local_date())

    def _local_date(self) -> date:
        value = self._clock()
        if value.tzinfo is None:
            value = value.astimezone()
        return value.date()

    def path_for(self, value: date) -> Path:
        return self.logs_dir / f"fgops-{value.isoformat()}.log"

    @property
    def current_path(self) -> Path:
        return self.path_for(self._local_date())

    def _ensure_stream(self, value: date) -> TextIO:
        if self._stream is not None and self._stream_date == value:
            return self._stream
        if self._stream is not None:
            self._stream.close()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._stream = self.path_for(value).open("a", encoding="utf-8", newline="\n")
        self._stream_date = value
        self._delete_expired_files(value)
        return self._stream

    def _delete_expired_files(self, today: date) -> None:
        oldest_kept = today - timedelta(days=self.retention_days - 1)
        for path in self.logs_dir.glob("fgops-*.log"):
            match = _LOG_FILE_RE.fullmatch(path.name)
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
                    # Logging must never block the update workflow because an old
                    # file is temporarily locked by an operator or antivirus tool.
                    continue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            value = self._local_date()
            stream = self._ensure_stream(value)
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
                self._stream_date = None
        finally:
            super().close()


def _configured_level(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    name = str(value or os.environ.get("FGOPS_LOG_LEVEL", _DEFAULT_LEVEL)).strip().upper()
    numeric = logging.getLevelNamesMapping().get(name)
    if numeric is None:
        return logging.INFO
    return numeric


def _configured_retention(value: int | None) -> int:
    if value is not None:
        return max(1, value)
    raw = os.environ.get("FGOPS_LOG_RETENTION_DAYS")
    if raw is None:
        return _DEFAULT_RETENTION_DAYS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_RETENTION_DAYS


def configure_daily_logging(
    storage_root: Path,
    *,
    logger_name: str = "fgops",
    level: str | int | None = None,
    retention_days: int | None = None,
    clock: Callable[[], datetime] | None = None,
) -> logging.Logger:
    """Configure one daily UTF-8 log file below ``<storage_root>/logs``."""

    logger = logging.getLogger(logger_name)
    logger.setLevel(_configured_level(level))
    logger.propagate = False

    for handler in list(logger.handlers):
        if isinstance(handler, DailyFileHandler):
            logger.removeHandler(handler)
            handler.close()

    handler = DailyFileHandler(
        storage_root / "logs",
        retention_days=_configured_retention(retention_days),
        clock=clock,
    )
    handler.setLevel(logger.level)
    handler.setFormatter(
        LocalIsoFormatter("%(asctime)s %(levelname)s pid=%(process)d %(message)s")
    )
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Write one structured event without exposing Python object representations."""

    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


def close_daily_logging(logger: logging.Logger) -> None:
    """Close handlers owned by FGOps; primarily useful for tests and embedding."""

    for handler in list(logger.handlers):
        if isinstance(handler, DailyFileHandler):
            logger.removeHandler(handler)
            handler.close()
