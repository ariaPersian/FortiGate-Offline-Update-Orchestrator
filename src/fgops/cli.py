from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .approval import evaluate_policy, load_policy, parse_approval_command
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
    if args.command == "render-restore":
        print(render_restore_command(PackageKind(args.kind), args.filename, args.tftp_server))
        return 0
    if args.command == "classify":
        before = parse_versions_file(args.before)
        after = parse_versions_file(args.after)
        transcript = args.transcript.read_text(encoding="utf-8", errors="replace")
        outcome = classify_outcome(
            args.object, before.get(args.object), after.get(args.object), transcript
        )
        payload = outcome.__dict__.copy()
        payload["status"] = outcome.status.value
        print(json.dumps(payload, indent=2))
        return 0
    raise AssertionError("unreachable")
