from __future__ import annotations

import io
import json

from fgops.notifications import send_telegram_message


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self, _limit: int) -> bytes:
        return self._body.read()


def test_send_telegram_message_posts_expected_payload() -> None:
    captured = {}

    def opener(request, **kwargs):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = kwargs["timeout"]
        return _Response({"ok": True, "result": {"message_id": 77}})

    result = send_telegram_message(
        bot_token="123:token",
        chat_id="-100123",
        text="hello",
        opener=opener,
    )

    assert result.status == "SENT"
    assert result.message_id == 77
    assert captured["url"].endswith("/bot123:token/sendMessage")
    assert captured["payload"]["chat_id"] == "-100123"
    assert captured["payload"]["text"] == "hello"
    assert captured["timeout"] == 30
