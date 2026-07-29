from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentState:
    schema_version: int = 1
    archives: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_run_at: str | None = None
    last_result: str | None = None
    last_error: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AgentState":
        if int(raw.get("schema_version", 0)) != 1:
            raise ValueError("Unsupported standalone-agent state schema.")
        archives = raw.get("archives") or {}
        if not isinstance(archives, dict):
            raise ValueError("State archives must be an object.")
        return cls(
            schema_version=1,
            archives={str(key): dict(value) for key, value in archives.items()},
            last_run_at=raw.get("last_run_at"),
            last_result=raw.get("last_result"),
            last_error=raw.get("last_error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "archives": self.archives,
            "last_run_at": self.last_run_at,
            "last_result": self.last_result,
            "last_error": self.last_error,
        }

    def has_successful_archive(self, sha256: str) -> bool:
        # APPLY_FAILED/REVIEW_REQUIRED are intentionally treated as already handled.
        # Re-downloading the same hash must never cause an unattended replay after an
        # uncertain or partially completed device-changing operation. CONTENT_DUPLICATE
        # means the ZIP bytes differed while the enabled package payload matched an
        # already applied payload, so it is also terminal for that exact archive hash.
        return (self.archives.get(sha256) or {}).get("status") in {
            "PREPARED",
            "APPLIED",
            "APPLY_FAILED",
            "REVIEW_REQUIRED",
            "CONTENT_DUPLICATE",
        }


def load_state(path: Path) -> AgentState:
    if not path.exists():
        return AgentState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Standalone-agent state must be a JSON object.")
    return AgentState.from_dict(raw)


def save_state(path: Path, state: AgentState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
