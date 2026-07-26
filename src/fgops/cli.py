from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .approval import evaluate_policy, load_policy, parse_approval_command
from .approval_state import (
    apply_command,
    create_approval_record,
    embed_record,
    evaluate_watchdog,
    extract_record,
    reconcile_comments,
)
from .durations import parse_duration
from .fortios import classify_outcome, parse_versions_file, render_restore_command
from .inventory import build_manifest
from .models import BundleManifest, PackageKind, PackageRecord, RestoreFamily


def _manifest_from_json(path: Path) -> BundleManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    packages = tuple(
        PackageRecord(
            filename=item["filename"],
            size=int(item["size"]),
            sha256=item["sha256"],
            kind=PackageKind(item["kind"]),
            restore_family=RestoreFamily(item["restore_family"])
            if item.get("restore_family")
            else None,
            expected_objects=tuple(item.get("expected_objects", [])),
            safe_for_deferred_apply=bool(item.get("safe_for_deferred_apply", False)),
        )
        for item in raw["packages"]
    )
    return BundleManifest(
        schema_version=int(raw["schema_version"]),
        manifest_id=raw["manifest_id"],
        source_archive=raw["source_archive"],
        source_archive_sha256=raw["source_archive_sha256"],
        generated_at=raw["generated_at"],
        packages=packages,
        warnings=tuple(raw.get("warnings", [])),
    )


def _read_key(env_name: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise ValueError(f"Required environment variable {env_name} is not set.")
    return value


def _parse_aware(value: str, name: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset.")
    return parsed


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _assert_issue_binding(record, repository: str, issue_number: int) -> None:
    if record.repository != repository or record.issue_number != issue_number:
        raise ValueError(
            "Approval-state issue binding does not match the current repository and issue."
        )


def _command_response(result) -> str:
    record = result.record
    return "\n".join(
        [
            "### FGOps command result",
            "",
            f"- Approval: `{record.approval_id}`",
            f"- State: **{record.state.value}**",
            f"- Revision: `{record.revision}`",
            f"- Changed: `{str(result.changed).lower()}`",
            f"- Result: {result.message}",
        ]
    )


def _reconcile_response(result) -> str:
    record = result.record
    details = "\n".join(f"- {message}" for message in result.messages) or "- No new commands."
    return "\n".join(
        [
            "### FGOps approval reconciliation",
            "",
            f"- Approval: `{record.approval_id}`",
            f"- State: **{record.state.value}**",
            f"- Revision: `{record.revision}`",
            f"- Changed: `{str(result.changed).lower()}`",
            "",
            details,
        ]
    )


def _watchdog_response(result) -> str:
    record = result.record
    return "\n".join(
        [
            "### FGOps watchdog",
            "",
            f"- Approval: `{record.approval_id}`",
            f"- State: **{record.state.value}**",
            f"- Revision: `{record.revision}`",
            f"- Reminder due: `{str(result.reminder_due).lower()}`",
            f"- Result: {result.message}",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fgops")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="Extract and inventory an offline bundle.")
    inventory.add_argument("archive", type=Path)
    inventory.add_argument("--output", required=True, type=Path)
    inventory.add_argument("--package-map", required=True, type=Path)

    versions = subparsers.add_parser(
        "parse-versions", help="Parse diagnose autoupdate versions output."
    )
    versions.add_argument("input", type=Path)

    approval = subparsers.add_parser("approval-command", help="Parse a /fg approval command.")
    approval.add_argument("text")

    policy = subparsers.add_parser("evaluate-policy", help="Evaluate an approval policy.")
    policy.add_argument("manifest", type=Path)
    policy.add_argument("--policy", required=True, type=Path)
    policy.add_argument("--created-at", required=True)
    policy.add_argument("--now")

    approval_init = subparsers.add_parser(
        "approval-init",
        help="Create a signed approval state bound to an exact manifest and issue.",
    )
    approval_init.add_argument("manifest", type=Path)
    approval_init.add_argument("--repository", required=True)
    approval_init.add_argument("--issue-number", required=True, type=int)
    approval_init.add_argument("--device-name", required=True)
    approval_init.add_argument("--expected-model", required=True)
    approval_init.add_argument("--expected-firmware", required=True)
    approval_init.add_argument("--approver", action="append", required=True)
    approval_init.add_argument("--expires-in", default="7d")
    approval_init.add_argument("--now")
    approval_init.add_argument("--key-env", default="FGOPS_APPROVAL_HMAC_KEY")
    approval_init.add_argument("--output-body", required=True, type=Path)

    mutate = subparsers.add_parser(
        "approval-mutate",
        help="Verify signed state and apply one idempotent approval command.",
    )
    mutate.add_argument("issue_body", type=Path)
    mutate.add_argument("--repository", required=True)
    mutate.add_argument("--issue-number", required=True, type=int)
    mutate.add_argument("--command-text", required=True)
    mutate.add_argument("--command-id", required=True)
    mutate.add_argument("--actor", required=True)
    mutate.add_argument("--comment-created-at", required=True)
    mutate.add_argument("--now")
    mutate.add_argument("--key-env", default="FGOPS_APPROVAL_HMAC_KEY")
    mutate.add_argument("--output-body", required=True, type=Path)
    mutate.add_argument("--output-response", required=True, type=Path)

    reconcile = subparsers.add_parser(
        "approval-reconcile",
        help="Replay all unprocessed /fg issue comments in deterministic order.",
    )
    reconcile.add_argument("issue_body", type=Path)
    reconcile.add_argument("comments_json", type=Path)
    reconcile.add_argument("--repository", required=True)
    reconcile.add_argument("--issue-number", required=True, type=int)
    reconcile.add_argument("--now")
    reconcile.add_argument("--key-env", default="FGOPS_APPROVAL_HMAC_KEY")
    reconcile.add_argument("--output-body", required=True, type=Path)
    reconcile.add_argument("--output-response", required=True, type=Path)

    watchdog = subparsers.add_parser(
        "approval-watchdog",
        help="Evaluate expiry, snooze, schedule, and reminder state.",
    )
    watchdog.add_argument("issue_body", type=Path)
    watchdog.add_argument("--repository", required=True)
    watchdog.add_argument("--issue-number", required=True, type=int)
    watchdog.add_argument("--policy", required=True, type=Path)
    watchdog.add_argument("--now")
    watchdog.add_argument("--key-env", default="FGOPS_APPROVAL_HMAC_KEY")
    watchdog.add_argument("--output-body", required=True, type=Path)
    watchdog.add_argument("--output-response", required=True, type=Path)

    verify = subparsers.add_parser(
        "approval-verify",
        help="Verify an issue's signed approval state and issue binding.",
    )
    verify.add_argument("issue_body", type=Path)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--issue-number", required=True, type=int)
    verify.add_argument("--key-env", default="FGOPS_APPROVAL_HMAC_KEY")

    restore = subparsers.add_parser("render-restore", help="Render a FortiOS restore command.")
    restore.add_argument(
        "kind", choices=[item.value for item in PackageKind if item != PackageKind.UNKNOWN]
    )
    restore.add_argument("filename")
    restore.add_argument("tftp_server")

    classify = subparsers.add_parser("classify", help="Classify a package result.")
    classify.add_argument("--before", required=True, type=Path)
    classify.add_argument("--after", required=True, type=Path)
    classify.add_argument("--transcript", required=True, type=Path)
    classify.add_argument("--object", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "inventory":
        manifest = build_manifest(args.archive, args.output, args.package_map)
        print(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "parse-versions":
        parsed = parse_versions_file(args.input)
        print(json.dumps({key: value.__dict__ for key, value in parsed.items()}, indent=2))
        return 0

    if args.command == "approval-command":
        command = parse_approval_command(args.text)
        print(json.dumps(command.__dict__, indent=2))
        return 0

    if args.command == "evaluate-policy":
        manifest = _manifest_from_json(args.manifest)
        policy = load_policy(args.policy)
        decision = evaluate_policy(
            manifest,
            policy,
            datetime.fromisoformat(args.created_at),
            datetime.fromisoformat(args.now) if args.now else None,
        )
        print(json.dumps(decision.to_dict(), indent=2))
        return 0

    if args.command == "approval-init":
        now = _parse_aware(args.now, "now") if args.now else datetime.now(timezone.utc)
        manifest = _manifest_from_json(args.manifest)
        record = create_approval_record(
            manifest=manifest,
            repository=args.repository,
            issue_number=args.issue_number,
            device_name=args.device_name,
            expected_model=args.expected_model,
            expected_firmware=args.expected_firmware,
            approvers=args.approver,
            expires_at=now + parse_duration(args.expires_in),
            now=now,
        )
        header = "\n".join(
            [
                f"# Offline update approval: {record.device_name}",
                "",
                "This issue is the durable audit and approval record for one immutable bundle.",
                "The hidden state is HMAC-authenticated and bound to this repository, issue, "
                "device, firmware expectation, manifest, package hashes, and package allow-list.",
            ]
        )
        body = embed_record(header, record, _read_key(args.key_env))
        _write_text(args.output_body, body)
        print(json.dumps(record.to_dict(), indent=2))
        return 0

    if args.command == "approval-mutate":
        key = _read_key(args.key_env)
        original_body = args.issue_body.read_text(encoding="utf-8")
        record = extract_record(original_body, key)
        _assert_issue_binding(record, args.repository, args.issue_number)
        result = apply_command(
            record,
            parse_approval_command(args.command_text),
            command_id=args.command_id,
            actor=args.actor,
            comment_created_at=_parse_aware(args.comment_created_at, "comment_created_at"),
            now=_parse_aware(args.now, "now") if args.now else None,
        )
        updated_body = embed_record(original_body, result.record, key) if result.changed else original_body
        _write_text(args.output_body, updated_body)
        _write_text(args.output_response, _command_response(result))
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    if args.command == "approval-reconcile":
        key = _read_key(args.key_env)
        original_body = args.issue_body.read_text(encoding="utf-8")
        record = extract_record(original_body, key)
        _assert_issue_binding(record, args.repository, args.issue_number)
        comments = json.loads(args.comments_json.read_text(encoding="utf-8"))
        if not isinstance(comments, list):
            raise ValueError("comments_json must contain a JSON array.")
        result = reconcile_comments(
            record,
            comments,
            now=_parse_aware(args.now, "now") if args.now else None,
        )
        updated_body = embed_record(original_body, result.record, key) if result.changed else original_body
        _write_text(args.output_body, updated_body)
        _write_text(args.output_response, _reconcile_response(result))
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    if args.command == "approval-watchdog":
        key = _read_key(args.key_env)
        original_body = args.issue_body.read_text(encoding="utf-8")
        record = extract_record(original_body, key)
        _assert_issue_binding(record, args.repository, args.issue_number)
        policy = load_policy(args.policy)
        result = evaluate_watchdog(
            record,
            now=_parse_aware(args.now, "now") if args.now else None,
            reminder_intervals=policy.reminders,
            repeat_every=policy.repeat_every,
        )
        updated_body = embed_record(original_body, result.record, key) if result.changed else original_body
        _write_text(args.output_body, updated_body)
        _write_text(args.output_response, _watchdog_response(result))
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    if args.command == "approval-verify":
        record = extract_record(
            args.issue_body.read_text(encoding="utf-8"),
            _read_key(args.key_env),
        )
        _assert_issue_binding(record, args.repository, args.issue_number)
        print(json.dumps(record.to_dict(), indent=2))
        return 0

    if args.command == "render-restore":
        print(render_restore_command(PackageKind(args.kind), args.filename, args.tftp_server))
        return 0

    if args.command == "classify":
        before = parse_versions_file(args.before)
        after = parse_versions_file(args.after)
        transcript = args.transcript.read_text(encoding="utf-8", errors="replace")
        outcome = classify_outcome(
            args.object,
            before.get(args.object),
            after.get(args.object),
            transcript,
        )
        payload = outcome.__dict__.copy()
        payload["status"] = outcome.status.value
        print(json.dumps(payload, indent=2))
        return 0

    raise AssertionError("unreachable")
