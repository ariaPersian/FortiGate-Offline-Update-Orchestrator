from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from fgops.approval import ApprovalCommand
from fgops.approval_state import (
    apply_command,
    create_approval_record,
    embed_record,
    evaluate_watchdog,
    extract_record,
    reconcile_comments,
    sign_record,
    verify_envelope,
)
from fgops.models import BundleManifest, PackageKind, PackageRecord, RestoreFamily

KEY = "k" * 32
NOW = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)


def _manifest() -> BundleManifest:
    return BundleManifest(
        schema_version=1,
        manifest_id="FGOPS-MANIFEST-1",
        source_archive="bundle.zip",
        source_archive_sha256="a" * 64,
        generated_at=NOW.isoformat(),
        packages=(
            PackageRecord(
                filename="cyberlogic.ir-AV.pkg",
                size=10,
                sha256="b" * 64,
                kind=PackageKind.AV,
                restore_family=RestoreFamily.AV,
                expected_objects=("Virus Definitions",),
                safe_for_deferred_apply=True,
            ),
            PackageRecord(
                filename="cyberlogic.ir-isdb.pkg",
                size=20,
                sha256="c" * 64,
                kind=PackageKind.ISDB,
                restore_family=RestoreFamily.OTHER_OBJECTS,
                expected_objects=("Industrial Attack Definitions",),
                safe_for_deferred_apply=False,
            ),
            PackageRecord(
                filename="64Antivirus.pkg",
                size=30,
                sha256="d" * 64,
                kind=PackageKind.IGNORED,
                restore_family=None,
                safe_for_deferred_apply=False,
            ),
        ),
    )


def _record():
    return create_approval_record(
        manifest=_manifest(),
        repository="ariaPersian/FortiGate-Offline-Update-Orchestrator",
        issue_number=10,
        device_name="SITEC-FW-02",
        expected_model="FortiGate-300D",
        expected_firmware="6.4.16-build2098",
        approvers=("ariaPersian",),
        expires_at=NOW + timedelta(days=7),
        now=NOW,
    )


def test_signed_issue_state_round_trip() -> None:
    record = _record()
    body = embed_record("operator notes", record, KEY)
    restored = extract_record(body, KEY)
    assert restored == record
    assert "operator notes" in body
    assert record.manifest_id in body


def test_tampering_is_rejected() -> None:
    envelope = sign_record(_record(), KEY)
    envelope["payload"]["expected_firmware"] = "unexpected-build"
    with pytest.raises(ValueError, match="signature verification failed"):
        verify_envelope(envelope, KEY)


def test_approval_binds_exact_package_hashes_and_allow_list() -> None:
    record = _record()
    assert dict(record.package_hashes) == {
        "cyberlogic.ir-AV.pkg": "b" * 64,
        "cyberlogic.ir-isdb.pkg": "c" * 64,
    }
    assert record.allowed_packages == (PackageKind.AV, PackageKind.ISDB)
    assert record.safe_packages == (PackageKind.AV,)


def test_command_is_idempotent_by_comment_id() -> None:
    record = _record()
    first = apply_command(
        record,
        ApprovalCommand("snooze", "1h"),
        command_id="123",
        actor="ariaPersian",
        comment_created_at=NOW + timedelta(minutes=1),
        now=NOW + timedelta(minutes=1),
    )
    second = apply_command(
        first.record,
        ApprovalCommand("snooze", "1h"),
        command_id="123",
        actor="ariaPersian",
        comment_created_at=NOW + timedelta(minutes=1),
        now=NOW + timedelta(minutes=2),
    )
    assert first.changed is True
    assert second.changed is False
    assert second.record.revision == first.record.revision


def test_unauthorized_actor_and_stale_comment_fail_closed() -> None:
    record = _record()
    with pytest.raises(PermissionError):
        apply_command(
            record,
            ApprovalCommand("approve"),
            command_id="1",
            actor="intruder",
            comment_created_at=NOW + timedelta(minutes=1),
            now=NOW + timedelta(minutes=1),
        )

    updated = replace(
        record,
        updated_at=(NOW + timedelta(hours=2)).isoformat(),
        revision=1,
    )
    with pytest.raises(ValueError, match="stale"):
        apply_command(
            updated,
            ApprovalCommand("approve"),
            command_id="2",
            actor="ariaPersian",
            comment_created_at=NOW + timedelta(hours=1),
            now=NOW + timedelta(hours=2),
        )


def test_apply_safe_approves_only_safe_packages() -> None:
    result = apply_command(
        _record(),
        ApprovalCommand("apply-safe"),
        command_id="safe-1",
        actor="ariaPersian",
        comment_created_at=NOW + timedelta(minutes=1),
        now=NOW + timedelta(minutes=1),
    )
    assert result.record.state.value == "APPROVED"
    assert result.record.approved_packages == (PackageKind.AV,)


def test_schedule_requires_timezone_and_watchdog_releases_at_due_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_command(
            _record(),
            ApprovalCommand("schedule", "2026-07-27T02:00:00"),
            command_id="schedule-naive",
            actor="ariaPersian",
            comment_created_at=NOW + timedelta(minutes=1),
            now=NOW + timedelta(minutes=1),
        )

    execute_at = NOW + timedelta(hours=2)
    scheduled = apply_command(
        _record(),
        ApprovalCommand("schedule", execute_at.isoformat()),
        command_id="schedule-1",
        actor="ariaPersian",
        comment_created_at=NOW + timedelta(minutes=1),
        now=NOW + timedelta(minutes=1),
    )
    before = evaluate_watchdog(scheduled.record, now=NOW + timedelta(hours=1))
    due = evaluate_watchdog(scheduled.record, now=NOW + timedelta(hours=2))
    assert before.changed is False
    assert due.changed is True
    assert due.record.state.value == "APPROVED"
    assert due.record.approved_packages == scheduled.record.allowed_packages


def test_watchdog_persists_reminder_and_does_not_repeat_early() -> None:
    first = evaluate_watchdog(
        _record(),
        now=NOW + timedelta(hours=1),
        reminder_intervals=(timedelta(hours=1), timedelta(hours=6)),
        repeat_every=timedelta(hours=24),
    )
    assert first.changed is True
    assert first.reminder_due is True
    assert first.record.reminder_count == 1

    second = evaluate_watchdog(
        first.record,
        now=NOW + timedelta(hours=2),
        reminder_intervals=(timedelta(hours=1), timedelta(hours=6)),
        repeat_every=timedelta(hours=24),
    )
    assert second.changed is False
    assert second.reminder_due is False


def test_expired_approval_cannot_be_approved() -> None:
    record = replace(
        _record(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )
    result = apply_command(
        record,
        ApprovalCommand("approve"),
        command_id="expired-1",
        actor="ariaPersian",
        comment_created_at=NOW + timedelta(hours=2),
        now=NOW + timedelta(hours=2),
    )
    assert result.record.state.value == "EXPIRED"
    assert not result.record.approved_packages


def test_reconcile_comments_recovers_commands_if_a_workflow_is_dropped() -> None:
    comments = [
        {
            "id": 101,
            "body": "/fg snooze 1h",
            "created_at": "2026-07-26T08:01:00Z",
            "author_association": "OWNER",
            "user": {"login": "ariaPersian"},
        },
        {
            "id": 102,
            "body": "/fg schedule 2026-07-26T12:00:00+00:00",
            "created_at": "2026-07-26T08:02:00Z",
            "author_association": "OWNER",
            "user": {"login": "ariaPersian"},
        },
    ]
    result = reconcile_comments(
        _record(),
        comments,
        now=NOW + timedelta(minutes=3),
    )
    assert result.changed is True
    assert result.record.state.value == "SCHEDULED"
    assert result.record.processed_command_ids == ("101", "102")
    assert result.record.revision == 2


def test_reconcile_marks_invalid_or_unauthorized_commands_processed() -> None:
    comments = [
        {
            "id": 201,
            "body": "/fg approve",
            "created_at": "2026-07-26T08:01:00Z",
            "author_association": "NONE",
            "user": {"login": "intruder"},
        },
        {
            "id": 202,
            "body": "/fg nonsense",
            "created_at": "2026-07-26T08:02:00Z",
            "author_association": "OWNER",
            "user": {"login": "ariaPersian"},
        },
    ]
    result = reconcile_comments(
        _record(),
        comments,
        now=NOW + timedelta(minutes=3),
    )
    assert result.record.state.value == "AWAITING_APPROVAL"
    assert result.record.processed_command_ids == ("201", "202")
    assert len(result.messages) == 2
