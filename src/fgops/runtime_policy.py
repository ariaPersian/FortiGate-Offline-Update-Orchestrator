from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    chat_id: str = ""
    token_secret_name: str = "FGOPS_TELEGRAM_BOT_TOKEN"
    timeout_seconds: int = 30
    notify_on: tuple[str, ...] = (
        "PREPARED",
        "FAILED",
        "SUCCESS",
        "SUCCESS_WITH_WARNING",
    )

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.chat_id.strip():
            raise ValueError("notifications.telegram.chat_id is required when Telegram is enabled.")
        if not self.token_secret_name.strip():
            raise ValueError("notifications.telegram.token_secret_name cannot be empty.")
        if not 5 <= self.timeout_seconds <= 120:
            raise ValueError("notifications.telegram.timeout_seconds must be between 5 and 120.")
        allowed = {
            "PREPARED",
            "NO_CHANGE",
            "FAILED",
            "SUCCESS",
            "SUCCESS_WITH_WARNING",
        }
        unknown = set(self.notify_on) - allowed
        if unknown:
            raise ValueError(
                "notifications.telegram.notify_on contains unsupported statuses: "
                + ", ".join(sorted(unknown))
            )


@dataclass(frozen=True)
class RuntimePolicy:
    secret_store: Path
    telegram: TelegramConfig

    def validate(self) -> None:
        self.telegram.validate()


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_runtime_policy(config_path: Path, storage_root: Path) -> RuntimePolicy:
    config_path = config_path.expanduser().resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Agent configuration must be a YAML object.")

    storage_raw = raw.get("storage") or {}
    notifications_raw = raw.get("notifications") or {}
    telegram_raw = notifications_raw.get("telegram") or {}
    if not isinstance(storage_raw, dict):
        raise ValueError("storage must be a YAML object.")
    if not isinstance(notifications_raw, dict):
        raise ValueError("notifications must be a YAML object.")
    if not isinstance(telegram_raw, dict):
        raise ValueError("notifications.telegram must be a YAML object.")

    notify_values = telegram_raw.get(
        "notify_on", ["PREPARED", "FAILED", "SUCCESS", "SUCCESS_WITH_WARNING"]
    )
    if not isinstance(notify_values, list):
        raise ValueError("notifications.telegram.notify_on must be a YAML list.")

    policy = RuntimePolicy(
        secret_store=_resolve(
            storage_root,
            storage_raw.get("secret_store", "secrets/secret-store.json"),
        ),
        telegram=TelegramConfig(
            enabled=bool(telegram_raw.get("enabled", False)),
            chat_id=str(telegram_raw.get("chat_id", "")),
            token_secret_name=str(
                telegram_raw.get("token_secret_name", "FGOPS_TELEGRAM_BOT_TOKEN")
            ).strip().upper(),
            timeout_seconds=int(telegram_raw.get("timeout_seconds", 30)),
            notify_on=tuple(str(item).strip().upper() for item in notify_values),
        ),
    )
    policy.validate()
    return policy
