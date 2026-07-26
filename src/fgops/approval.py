from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .durations import parse_duration
from .models import ApprovalDecision, ApprovalState, BundleManifest, PackageKind

_COMMAND_RE = re.compile(
    r"^/fg\s+(?P<command>approve|reject|snooze|schedule|apply-safe|status|cancel)"
    r"(?:\s+(?P<argument>.+))?$",
    re.I,
)


@dataclass(frozen=True)
class ApprovalCommand:
    command: str
    argument: str | None = None


@dataclass(frozen=True)
class ApprovalPolicy:
    mode: str
    timezone_name: str
    reminders: tuple[timedelta, ...]
    repeat_every: timedelta | None
    timeout: timedelta
    on_timeout: str
    grace_period: timedelta | None
    safe_package_kinds: tuple[PackageKind, ...]


def parse_approval_command(text: str) -> ApprovalCommand:
    match = _COMMAND_RE.fullmatch(text.strip())
    if not match:
        raise ValueError(
            "Unsupported command. Expected /fg approve|reject|snooze|schedule|apply-safe|status|cancel"
        )
    command = match.group("command").lower()
    argument = match.group("argument")
    if command == "snooze":
        if not argument:
            raise ValueError("/fg snooze requires a duration such as 24h.")
        parse_duration(argument)
    elif command == "schedule":
        if not argument:
            raise ValueError("/fg schedule requires an ISO-8601 date and time.")
        scheduled = datetime.fromisoformat(argument)
        if scheduled.tzinfo is None or scheduled.utcoffset() is None:
            raise ValueError("/fg schedule requires an explicit UTC offset.")
    elif command == "reject" and not argument:
        raise ValueError("/fg reject requires a reason.")
    elif argument and command not in {"reject", "snooze", "schedule"}:
        raise ValueError(f"/fg {command} does not accept an argument.")
    return ApprovalCommand(command=command, argument=argument)


def load_policy(path: Path) -> ApprovalPolicy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    approval: dict[str, Any] = raw.get("approval") or {}
    mode = str(approval.get("mode", "manual"))
    if mode not in {"manual", "grace_period", "maintenance_window", "risk_based"}:
        raise ValueError(f"Unsupported approval mode: {mode}")
    timezone_name = str(approval.get("timezone", "UTC"))
    ZoneInfo(timezone_name)
    reminders = tuple(
        sorted({parse_duration(str(value)) for value in approval.get("reminders", [])})
    )
    repeat_every = (
        parse_duration(str(approval["repeat_every"])) if approval.get("repeat_every") else None
    )
    timeout = parse_duration(str(approval.get("timeout", "7d")))
    grace_period = (
        parse_duration(str(approval["grace_period"])) if approval.get("grace_period") else None
    )
    on_timeout = str(approval.get("on_timeout", "hold"))
    if on_timeout not in {"hold", "apply_safe_only", "expire"}:
        raise ValueError(f"Unsupported on_timeout action: {on_timeout}")
    safe_kinds = tuple(PackageKind(value) for value in approval.get("safe_package_kinds", []))
    if mode == "grace_period" and grace_period is None:
        raise ValueError("grace_period mode requires approval.grace_period.")
    return ApprovalPolicy(
        mode=mode,
        timezone_name=timezone_name,
        reminders=reminders,
        repeat_every=repeat_every,
        timeout=timeout,
        on_timeout=on_timeout,
        grace_period=grace_period,
        safe_package_kinds=safe_kinds,
    )


def evaluate_policy(
    manifest: BundleManifest,
    policy: ApprovalPolicy,
    created_at: datetime,
    now: datetime | None = None,
) -> ApprovalDecision:
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("created_at and now must be timezone-aware.")
    age = now - created_at
    safe = tuple(
        package.kind
        for package in manifest.packages
        if package.safe_for_deferred_apply and package.kind in policy.safe_package_kinds
    )
    if age >= policy.timeout:
        if policy.on_timeout == "expire":
            return ApprovalDecision(ApprovalState.EXPIRED, True, reason="Approval request expired.")
        if policy.on_timeout == "apply_safe_only" and safe:
            return ApprovalDecision(
                ApprovalState.APPROVED,
                False,
                safe,
                execute_at=now.isoformat(),
                reason="Timeout policy approved safe packages only.",
            )
        return ApprovalDecision(
            ApprovalState.AWAITING_APPROVAL,
            True,
            reason="Timeout reached; policy requires an explicit decision.",
        )
    if policy.mode == "grace_period" and policy.grace_period and age >= policy.grace_period and safe:
        return ApprovalDecision(
            ApprovalState.APPROVED,
            False,
            safe,
            execute_at=now.isoformat(),
            reason="Grace period elapsed; safe packages are eligible.",
        )
    return ApprovalDecision(
        ApprovalState.AWAITING_APPROVAL,
        True,
        reason="Waiting for an authorized approval command.",
    )
