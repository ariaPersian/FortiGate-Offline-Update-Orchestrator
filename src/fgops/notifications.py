from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class NotificationResult:
    provider: str
    status: str
    message_id: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "status": self.status,
            "message_id": self.message_id,
            "error": self.error,
        }


UrlOpener = Callable[..., object]


def send_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    timeout_seconds: int = 30,
    ssl_context: ssl.SSLContext | None = None,
    opener: UrlOpener = urllib.request.urlopen,
) -> NotificationResult:
    if not bot_token.strip():
        raise ValueError("Telegram bot token cannot be empty.")
    if not chat_id.strip():
        raise ValueError("Telegram chat_id cannot be empty.")
    if not text.strip():
        raise ValueError("Telegram message cannot be empty.")
    if len(text) > 4096:
        text = text[:4076] + "\n… message truncated"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "FGOps/0.5"},
    )
    try:
        response = opener(request, timeout=timeout_seconds, context=ssl_context)
        with response:
            body = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API returned HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram API connection failed: {exc.reason}") from None

    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Telegram API returned an invalid JSON response.") from exc
    if not isinstance(decoded, dict) or decoded.get("ok") is not True:
        description = decoded.get("description") if isinstance(decoded, dict) else None
        raise RuntimeError(f"Telegram API rejected sendMessage: {description or 'unknown error'}")
    result = decoded.get("result") or {}
    message_id = result.get("message_id") if isinstance(result, dict) else None
    return NotificationResult(
        provider="telegram",
        status="SENT",
        message_id=int(message_id) if isinstance(message_id, int) else None,
    )
