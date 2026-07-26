from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .approval import ApprovalCommand, parse_approval_command
from .durations import parse_duration
from .models import ApprovalState, BundleManifest, PackageKind

STATE_BEGIN = "<!-- FGOPS_APPROVAL_STATE_V1\n"
STATE_END = "\nFGOPS_APPROVAL_STATE_END -->"
STATUS_BEGIN = "<!-- FGOPS_APPROVAL_STATUS_V1 -->"
STATUS_END = "<!-- FGOPS_APPROVAL_STATUS_END -->"
_FINAL_STATES = {
    ApprovalState.REJECTED,
    ApprovalState.EXPIRED,
    ApprovalState.CANCELLED,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_time(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _require_aware(datetime.fromisoformat(value), field_name)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _validate_key(key: str | bytes) -> bytes:
    raw = key.encode("utf-8") if isinstance(key, str) else key
    if len(raw) < 32:
        raise ValueError("Approval HMAC key must contain at least 32 bytes.")
    return raw


@dataclass(frozen=True)
class ApprovalRecord:
    schema_version: int
    approval_id: str
    repository: str
    issue_number: int
    device_name: str
    expected_model: str
    expected_firmware: str
    source_archive_sha256: str
    manifest_id: str
    package_hashes: tuple[tuple[str, str], ...]
    allowed_packages: tuple[PackageKind, ...]
    safe_packages: tuple[PackageKind, ...]
    approvers: tuple[str, ...]
    state: ApprovalState
    created_at: str
    updated_at: str
    expires_at: str
    execute_at: str | None = None
    snoozed_until: str | None = None
    approved_packages: tuple[PackageKind, ...] = ()
    actor: str | None = None
    reason: str = ""
    revision: int = 0
    processed_command_ids: tuple[str, ...] = ()
    last_reminded_at: str | None = None
    reminder_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "approval_id": self.approval_id,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "device_name": self.device_name,
            "expected_model": self.expected_model,
            "expected_firmware": self.expected_firmware,
            "source_archive_sha256": self.source_archive_sha256,
            "manifest_id": self.manifest_id,
            "package_hashes": {name: digest for name, digest in self.package_hashes},
            "allowed_packages": [item.value for item in self.allowed_packages],
            "safe_packages": [item.value for item in self.safe_packages],
            "approvers": list(self.approvers),
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "execute_at": self.execute_at,
            "snoozed_until": self.snoozed_until,
            "approved_packages": [item.value for item in self.approved_packages],
            "actor": self.actor,
            "reason": self.reason,
            "revision": self.revision,
            "processed_command_ids": list(self.processed_command_ids),
            "last_reminded_at": self.last_reminded_at,
            "reminder_count": self.reminder_count,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ApprovalRecord":
        if int(raw.get("schema_version", 0)) != 1:
            raise ValueError("Unsupported approval-state schema version.")
        package_hashes = raw.get("package_hashes") or {}
        if not isinstance(package_hashes, dict):
            raise ValueError("package_hashes must be an object.")
        record = cls(
            schema_version=1,
            approval_id=str(raw["approval_id"]),
            repository=str(raw["repository"]),
            issue_number=int(raw["issue_number"]),
            device_name=str(raw["device_name"]),
            expected_model=str(raw["expected_model"]),
            expected_firmware=str(raw["expected_firmware"]),
            source_archive_sha256=str(raw["source_archive_sha256"]),
            manifest_id=str(raw["manifest_id"]),
            package_hashes=tuple(sorted((str(k), str(v)) for k, v in package_hashes.items())),
            allowed_packages=tuple(PackageKind(value) for value in raw["allowed_packages"]),
            safe_packages=tuple(PackageKind(value) for value in raw.get("safe_packages", [])),
            approvers=tuple(str(value) for value in raw["approvers"]),
            state=ApprovalState(raw["state"]),
            created_at=str(raw["created_at"]),
            updated_at=str(raw["updated_at"]),
            expires_at=str(raw["expires_at"]),
            execute_at=raw.get("execute_at"),
            snoozed_until=raw.get("snoozed_until"),
            approved_packages=tuple(
                PackageKind(value) for value in raw.get("approved_packages", [])
            ),
            actor=raw.get("actor"),
            reason=str(raw.get("reason", "")),
            revision=int(raw.get("revision", 0)),
            processed_command_ids=tuple(str(value) for value in raw.get("processed_command_ids", [])),
            last_reminded_at=raw.get("last_reminded_at"),
            reminder_count=int(raw.get("reminder_count", 0)),
        )
        record.validate()
        return record

    def validate(self) -> None:
        if not self.repository or "/" not in self.repository:
            raise ValueError("repository must use owner/name format.")
        if self.issue_number <= 0:
            raise ValueError("issue_number must be positive.")
        if not self.approvers:
            raise ValueError("At least one approver is required.")
        if len({value.lower() for value in self.approvers}) != len(self.approvers):
            raise ValueError("Approvers must be unique, case-insensitively.")
        if not self.allowed_packages:
            raise ValueError("At least one allowed package is required.")
        if not set(self.safe_packages).issubset(self.allowed_packages):
            raise ValueError("safe_packages must be a subset of allowed_packages.")
        if not set(self.approved_packages).issubset(self.allowed_packages):
            raise ValueError("approved_packages must be a subset of allowed_packages.")
        if len(dict(self.package_hashes)) != len(self.package_hashes):
            raise ValueError("Package filenames must be unique.")
        for filename, digest in self.package_hashes:
            if not filename or len(digest) != 64:
                raise ValueError("Each package must have a filename and SHA-256 digest.")
            int(digest, 16)
        created = _parse_time(self.created_at, "created_at")
        updated = _parse_time(self.updated_at, "updated_at")
        expires = _parse_time(self.expires_at, "expires_at")
        execute = _parse_time(self.execute_at, "execute_at")
        snooze = _parse_time(self.snoozed_until, "snoozed_until")
        reminded = _parse_time(self.last_reminded_at, "last_reminded_at")
        assert created and updated and expires
        if updated < created:
            raise ValueError("updated_at cannot precede created_at.")
        if expires <= created:
            raise ValueError("expires_at must be later than created_at.")
        if execute and execute < created:
            raise ValueError("execute_at cannot precede created_at.")
        if snooze and snooze < created:
            raise ValueError("snoozed_until cannot precede created_at.")
        if reminded and reminded < created:
            raise ValueError("last_reminded_at cannot precede created_at.")
        if self.revision < 0 or self.reminder_count < 0:
            raise ValueError("revision and reminder_count cannot be negative.")


@dataclass(frozen=True)
class MutationResult:
    record: ApprovalRecord
    changed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "message": self.message,
            "record": self.record.to_dict(),
        }


@dataclass(frozen=True)
class ReconcileResult:
    record: ApprovalRecord
    changed: bool
    messages: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "messages": list(self.messages),
            "record": self.record.to_dict(),
        }


@dataclass(frozen=True)
class WatchdogResult:
    record: ApprovalRecord
    changed: bool
    reminder_due: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "reminder_due": self.reminder_due,
            "message": self.message,
            "record": self.record.to_dict(),
        }


def create_approval_record(
    *,
    manifest: BundleManifest,
    repository: str,
    issue_number: int,
    device_name: str,
    expected_model: str,
    expected_firmware: str,
    approvers: Iterable[str],
    expires_at: datetime,
    now: datetime | None = None,
) -> ApprovalRecord:
    now = _require_aware(now or _utc_now(), "now")
    expires_at = _require_aware(expires_at, "expires_at")
    if expires_at <= now:
        raise ValueError("expires_at must be in the future.")
    known_packages = tuple(
        package for package in manifest.packages if package.kind != PackageKind.UNKNOWN
    )
    if not known_packages:
        raise ValueError("Manifest does not contain an approvable package.")
    package_hashes = tuple(sorted((package.filename, package.sha256) for package in known_packages))
    allowed = tuple(package.kind for package in known_packages)
    safe = tuple(package.kind for package in known_packages if package.safe_for_deferred_apply)
    approver_values = tuple(dict.fromkeys(value.strip() for value in approvers if value.strip()))
    binding = {
        "repository": repository,
        "issue_number": issue_number,
        "device_name": device_name,
        "expected_model": expected_model,
        "expected_firmware": expected_firmware,
        "source_archive_sha256": manifest.source_archive_sha256,
        "manifest_id": manifest.manifest_id,
        "package_hashes": dict(package_hashes),
        "allowed_packages": [item.value for item in allowed],
    }
    approval_id = "FGOPS-A-" + hashlib.sha256(_canonical_json(binding)).hexdigest()[:20].upper()
    record = ApprovalRecord(
        schema_version=1,
        approval_id=approval_id,
        repository=repository,
        issue_number=issue_number,
        device_name=device_name,
        expected_model=expected_model,
        expected_firmware=expected_firmware,
        source_archive_sha256=manifest.source_archive_sha256,
        manifest_id=manifest.manifest_id,
        package_hashes=package_hashes,
        allowed_packages=allowed,
        safe_packages=safe,
        approvers=approver_values,
        state=ApprovalState.AWAITING_APPROVAL,
        created_at=_iso(now) or "",
        updated_at=_iso(now) or "",
        expires_at=_iso(expires_at) or "",
        reason="Waiting for an authorized approval command.",
    )
    record.validate()
    return record


def sign_record(record: ApprovalRecord, key: str | bytes) -> dict[str, Any]:
    record.validate()
    payload = record.to_dict()
    digest = hmac.new(_validate_key(key), _canonical_json(payload), hashlib.sha256).hexdigest()
    return {
        "payload": payload,
        "signature": {
            "algorithm": "HMAC-SHA256",
            "value": digest,
        },
    }


def verify_envelope(envelope: dict[str, Any], key: str | bytes) -> ApprovalRecord:
    signature = envelope.get("signature") or {}
    if signature.get("algorithm") != "HMAC-SHA256":
        raise ValueError("Unsupported or missing approval-state signature algorithm.")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Approval-state payload is missing.")
    supplied = str(signature.get("value", ""))
    expected = hmac.new(_validate_key(key), _canonical_json(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("Approval-state signature verification failed.")
    return ApprovalRecord.from_dict(payload)


def encode_envelope(envelope: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(_canonical_json(envelope)).decode("ascii")


def decode_envelope(encoded: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
        value = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Approval-state envelope is malformed.") from exc
    if not isinstance(value, dict):
        raise ValueError("Approval-state envelope must be an object.")
    return value


def extract_envelope(issue_body: str) -> dict[str, Any]:
    start = issue_body.find(STATE_BEGIN)
    if start < 0:
        raise ValueError("Issue does not contain an FGOps approval-state block.")
    end = issue_body.find(STATE_END, start)
    if end < 0:
        raise ValueError("Issue approval-state block is incomplete.")
    if issue_body.find(STATE_BEGIN, start + len(STATE_BEGIN)) >= 0:
        raise ValueError("Issue contains more than one approval-state block.")
    encoded = issue_body[start + len(STATE_BEGIN) : end].strip()
    return decode_envelope(encoded)


def extract_record(issue_body: str, key: str | bytes) -> ApprovalRecord:
    return verify_envelope(extract_envelope(issue_body), key)


def render_status(record: ApprovalRecord) -> str:
    approved = ", ".join(item.value for item in record.approved_packages) or "—"
    allowed = ", ".join(item.value for item in record.allowed_packages)
    execute_at = record.execute_at or "—"
    snoozed_until = record.snoozed_until or "—"
    reason = record.reason or "—"
    return "\n".join(
        [
            STATUS_BEGIN,
            "## FGOps approval status",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Approval ID | `{record.approval_id}` |",
            f"| State | **{record.state.value}** |",
            f"| Device | `{record.device_name}` |",
            f"| Expected model | `{record.expected_model}` |",
            f"| Expected firmware | `{record.expected_firmware}` |",
            f"| Manifest | `{record.manifest_id}` |",
            f"| Allowed packages | `{allowed}` |",
            f"| Approved packages | `{approved}` |",
            f"| Execute at | `{execute_at}` |",
            f"| Snoozed until | `{snoozed_until}` |",
            f"| Expires at | `{record.expires_at}` |",
            f"| Revision | `{record.revision}` |",
            f"| Reminders sent | `{record.reminder_count}` |",
            f"| Last actor | `{record.actor or '—'}` |",
            f"| Reason | {reason} |",
            "",
            "Commands: `/fg approve`, `/fg reject <reason>`, `/fg snooze <duration>`, "
            "`/fg schedule <ISO-8601>`, `/fg apply-safe`, `/fg status`, `/fg cancel`.",
            STATUS_END,
        ]
    )


def _replace_block(body: str, begin: str, end: str, replacement: str) -> str:
    start = body.find(begin)
    if start < 0:
        return body.rstrip() + "\n\n" + replacement + "\n"
    stop = body.find(end, start)
    if stop < 0:
        raise ValueError(f"Issue contains an incomplete block beginning with {begin!r}.")
    stop += len(end)
    return body[:start] + replacement + body[stop:]


def embed_record(issue_body: str, record: ApprovalRecord, key: str | bytes) -> str:
    envelope = sign_record(record, key)
    state_block = STATE_BEGIN + encode_envelope(envelope) + STATE_END
    body = _replace_block(issue_body, STATUS_BEGIN, STATUS_END, render_status(record))
    body = _replace_block(body, STATE_BEGIN, STATE_END, state_block)
    return body.rstrip() + "\n"


def _check_actor(record: ApprovalRecord, actor: str) -> None:
    allowed = {value.lower() for value in record.approvers}
    if actor.lower() not in allowed:
        raise PermissionError(f"Actor '{actor}' is not an authorized approver.")


def _next_record(
    record: ApprovalRecord,
    *,
    event_time: datetime,
    command_id: str,
    actor: str,
    state: ApprovalState | None = None,
    approved_packages: tuple[PackageKind, ...] | None = None,
    execute_at: datetime | None = None,
    snoozed_until: datetime | None = None,
    reason: str,
) -> ApprovalRecord:
    return replace(
        record,
        state=state or record.state,
        approved_packages=approved_packages
        if approved_packages is not None
        else record.approved_packages,
        execute_at=_iso(execute_at),
        snoozed_until=_iso(snoozed_until),
        actor=actor,
        reason=reason,
        updated_at=_iso(event_time) or "",
        revision=record.revision + 1,
        processed_command_ids=record.processed_command_ids + (command_id,),
    )


def apply_command(
    record: ApprovalRecord,
    command: ApprovalCommand,
    *,
    command_id: str,
    actor: str,
    comment_created_at: datetime,
    now: datetime | None = None,
) -> MutationResult:
    record.validate()
    now = _require_aware(now or _utc_now(), "now")
    comment_created_at = _require_aware(comment_created_at, "comment_created_at")
    _check_actor(record, actor)
    if command_id in record.processed_command_ids:
        return MutationResult(record, False, "Command was already processed.")
    updated_at = _parse_time(record.updated_at, "updated_at")
    expires_at = _parse_time(record.expires_at, "expires_at")
    assert updated_at and expires_at
    if comment_created_at < updated_at:
        raise ValueError("Command is stale relative to the current approval revision.")
    if now >= expires_at:
        expired = _next_record(
            record,
            event_time=comment_created_at,
            command_id=command_id,
            actor=actor,
            state=ApprovalState.EXPIRED,
            approved_packages=(),
            reason="Approval expired before the command was processed.",
        )
        return MutationResult(expired, True, expired.reason)
    if command.command == "status":
        return MutationResult(record, False, "Status request does not mutate approval state.")
    if record.state in _FINAL_STATES:
        raise ValueError(f"Approval is terminal in state {record.state.value}.")
    if record.state == ApprovalState.APPROVED and command.command != "cancel":
        raise ValueError("Approval is already approved; only /fg cancel is accepted.")
    if command.command == "approve":
        updated = _next_record(
            record,
            event_time=comment_created_at,
            command_id=command_id,
            actor=actor,
            state=ApprovalState.APPROVED,
            approved_packages=record.allowed_packages,
            reason="Explicit approval granted for the bound package allow-list.",
        )
    elif command.command == "apply-safe":
        if not record.safe_packages:
            raise ValueError("No package in this approval is eligible for safe deferred apply.")
        updated = _next_record(
            record,
            event_time=comment_created_at,
            command_id=command_id,
            actor=actor,
            state=ApprovalState.APPROVED,
            approved_packages=record.safe_packages,
            reason="Explicit approval granted for safe packages only.",
        )
    elif command.command == "reject":
        updated = _next_record(
            record,
            event_time=comment_created_at,
            command_id=command_id,
            actor=actor,
            state=ApprovalState.REJECTED,
            approved_packages=(),
            reason=command.argument or "Rejected.",
        )
    elif command.command == "cancel":
        updated = _next_record(
            record,
            event_time=comment_created_at,
            command_id=command_id,
            actor=actor,
            state=ApprovalState.CANCELLED,
            approved_packages=(),
            reason="Approval request cancelled.",
        )
    elif command.command == "snooze":
        assert command.argument
        until = comment_created_at + parse_duration(command.argument)
        if until >= expires_at:
            raise ValueError("Snooze would extend beyond approval expiry.")
        updated = _next_record(
            record,
            event_time=comment_created_at,
            command_id=command_id,
            actor=actor,
            state=ApprovalState.SNOOZED,
            approved_packages=(),
            snoozed_until=until,
            reason=f"Approval snoozed until {_iso(until)}.",
        )
    elif command.command == "schedule":
        assert command.argument
        execute_at = _require_aware(datetime.fromisoformat(command.argument), "schedule")
        if execute_at <= now:
            raise ValueError("Scheduled execution must be in the future.")
        if execute_at >= expires_at:
            raise ValueError("Scheduled execution must occur before approval expiry.")
        updated = _next_record(
            record,
            event_time=comment_created_at,
            command_id=command_id,
            actor=actor,
            state=ApprovalState.SCHEDULED,
            approved_packages=record.allowed_packages,
            execute_at=execute_at,
            reason=f"Approved package allow-list scheduled for {_iso(execute_at)}.",
        )
    else:
        raise ValueError(f"Unsupported approval command: {command.command}")
    updated.validate()
    return MutationResult(updated, True, updated.reason)


def _mark_processed(
    record: ApprovalRecord,
    *,
    command_id: str,
    actor: str,
    event_time: datetime,
    reason: str,
) -> ApprovalRecord:
    if command_id in record.processed_command_ids:
        return record
    effective_time = max(
        event_time,
        _parse_time(record.updated_at, "updated_at") or event_time,
    )
    updated = replace(
        record,
        actor=actor,
        reason=reason,
        updated_at=_iso(effective_time) or "",
        revision=record.revision + 1,
        processed_command_ids=record.processed_command_ids + (command_id,),
    )
    updated.validate()
    return updated


def reconcile_comments(
    record: ApprovalRecord,
    comments: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    allowed_associations: tuple[str, ...] = ("OWNER", "MEMBER", "COLLABORATOR"),
) -> ReconcileResult:
    record.validate()
    now = _require_aware(now or _utc_now(), "now")
    current = record
    messages: list[str] = []
    changed = False
    normalized: list[tuple[datetime, int, dict[str, Any]]] = []

    for raw in comments:
        body = str(raw.get("body", "")).strip()
        if not body.lower().startswith("/fg "):
            continue
        comment_id = int(raw["id"])
        created_at = _require_aware(
            datetime.fromisoformat(str(raw["created_at"]).replace("Z", "+00:00")),
            "comment_created_at",
        )
        normalized.append((created_at, comment_id, raw))

    for created_at, numeric_id, raw in sorted(normalized, key=lambda item: (item[0], item[1])):
        command_id = str(numeric_id)
        if command_id in current.processed_command_ids:
            continue
        actor = str((raw.get("user") or {}).get("login", ""))
        association = str(raw.get("author_association", "")).upper()
        body = str(raw.get("body", "")).strip()

        if association not in allowed_associations:
            current = _mark_processed(
                current,
                command_id=command_id,
                actor=actor or "unknown",
                event_time=created_at,
                reason=f"Command {command_id} rejected: unauthorized association.",
            )
            messages.append(current.reason)
            changed = True
            continue

        try:
            command = parse_approval_command(body)
            result = apply_command(
                current,
                command,
                command_id=command_id,
                actor=actor,
                comment_created_at=created_at,
                now=now,
            )
            if result.changed:
                current = result.record
                changed = True
            else:
                current = _mark_processed(
                    current,
                    command_id=command_id,
                    actor=actor,
                    event_time=created_at,
                    reason=result.message,
                )
                changed = True
            messages.append(f"Command {command_id}: {result.message}")
        except (PermissionError, ValueError) as exc:
            current = _mark_processed(
                current,
                command_id=command_id,
                actor=actor or "unknown",
                event_time=created_at,
                reason=f"Command {command_id} rejected: {exc}",
            )
            messages.append(current.reason)
            changed = True

    return ReconcileResult(current, changed, tuple(messages))


def evaluate_watchdog(
    record: ApprovalRecord,
    *,
    now: datetime | None = None,
    reminder_intervals: tuple[timedelta, ...] = (),
    repeat_every: timedelta | None = None,
) -> WatchdogResult:
    record.validate()
    now = _require_aware(now or _utc_now(), "now")
    expires_at = _parse_time(record.expires_at, "expires_at")
    updated_at = _parse_time(record.updated_at, "updated_at")
    created_at = _parse_time(record.created_at, "created_at")
    assert expires_at and updated_at and created_at

    if record.state in {
        ApprovalState.REJECTED,
        ApprovalState.EXPIRED,
        ApprovalState.CANCELLED,
    }:
        return WatchdogResult(record, False, False, "Approval is terminal.")

    if now >= expires_at and record.state != ApprovalState.APPROVED:
        updated = replace(
            record,
            state=ApprovalState.EXPIRED,
            approved_packages=(),
            actor="fgops-watchdog",
            reason="Approval expired.",
            updated_at=_iso(now) or "",
            revision=record.revision + 1,
        )
        return WatchdogResult(updated, True, False, updated.reason)

    if record.state == ApprovalState.SNOOZED:
        until = _parse_time(record.snoozed_until, "snoozed_until")
        if until and now >= until:
            updated = replace(
                record,
                state=ApprovalState.AWAITING_APPROVAL,
                snoozed_until=None,
                actor="fgops-watchdog",
                reason="Snooze period elapsed; approval is pending again.",
                updated_at=_iso(now) or "",
                revision=record.revision + 1,
            )
            return WatchdogResult(updated, True, True, updated.reason)
        return WatchdogResult(record, False, False, "Approval remains snoozed.")

    if record.state == ApprovalState.SCHEDULED:
        execute_at = _parse_time(record.execute_at, "execute_at")
        if execute_at and now >= execute_at:
            updated = replace(
                record,
                state=ApprovalState.APPROVED,
                actor="fgops-watchdog",
                reason="Scheduled execution time reached.",
                updated_at=_iso(now) or "",
                revision=record.revision + 1,
            )
            return WatchdogResult(updated, True, False, updated.reason)
        return WatchdogResult(record, False, False, "Approval remains scheduled.")

    if record.state == ApprovalState.APPROVED:
        return WatchdogResult(
            record,
            False,
            False,
            "Approval is ready for a separate apply workflow.",
        )

    intervals = tuple(sorted(reminder_intervals))
    last_reminded = _parse_time(record.last_reminded_at, "last_reminded_at")
    reminder_due = False
    for interval in intervals:
        threshold = created_at + interval
        if now >= threshold and (last_reminded is None or last_reminded < threshold):
            reminder_due = True
            break

    if (
        not reminder_due
        and repeat_every
        and intervals
        and now >= created_at + intervals[-1]
        and last_reminded is not None
        and now - last_reminded >= repeat_every
    ):
        reminder_due = True

    if not reminder_due:
        return WatchdogResult(record, False, False, "Approval remains pending.")

    updated = replace(
        record,
        actor="fgops-watchdog",
        reason="Approval reminder is due.",
        updated_at=_iso(now) or "",
        revision=record.revision + 1,
        last_reminded_at=_iso(now),
        reminder_count=record.reminder_count + 1,
    )
    return WatchdogResult(updated, True, True, updated.reason)
