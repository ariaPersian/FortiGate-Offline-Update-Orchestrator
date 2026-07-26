from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

from .agent_config import load_agent_config, write_default_config
from .agent_orchestrator import run_agent_once
from .agent_state import load_state
from .backup_test import run_backup_test
from .controlled_apply import run_controlled_apply
from .cycle import approve_manifest, run_cycle, send_notification_test
from .fortigate_preflight import run_read_only_preflight, scan_host_key
from .runtime_policy import load_runtime_policy
from .secret_store import delete_secret, list_secrets, set_secret


def default_config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return root / "FGOps" / "config.yml"
    return Path.home() / ".config" / "fgops" / "config.yml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fgops-agent",
        description="Standalone scheduled monitor for offline FortiGate signature bundles.",
    )
    parser.add_argument("--config", type=Path, default=default_config_path())
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a local agent configuration.")
    init.add_argument(
        "--package-map-source",
        type=Path,
        default=Path("config/fortios64-package-map.yml"),
        help="Package map copied next to the generated configuration.",
    )
    init.add_argument("--force", action="store_true")

    run = subparsers.add_parser("run", help="Poll, download, extract, and prepare a bundle.")
    run.add_argument("--dry-run", action="store_true")

    subparsers.add_parser(
        "cycle",
        help="Run the scheduled policy cycle: prepare, notify, and optionally unattended apply.",
    )

    approve = subparsers.add_parser(
        "approve",
        help="Apply one prepared manifest in approval mode using the local machine secret store.",
    )
    approve.add_argument("--manifest-id", required=True)

    scan = subparsers.add_parser(
        "scan-host-key",
        help="Read an SSH server host key without authenticating; verify it out of band before use.",
    )
    scan.add_argument("--host", required=True)
    scan.add_argument("--port", type=int, default=22)
    scan.add_argument("--timeout", type=int, default=10)

    subparsers.add_parser(
        "preflight",
        help="Run pinned, read-only FortiGate SSH commands and write before-state evidence.",
    )
    subparsers.add_parser(
        "backup-test",
        help=(
            "Start temporary TFTP, export one encrypted full configuration backup, "
            "verify it, and perform no package restore."
        ),
    )
    apply = subparsers.add_parser(
        "apply",
        help="Back up and apply one prepared manifest through temporary TFTP and pinned SSH.",
    )
    apply.add_argument("--manifest-id", required=True)
    apply.add_argument(
        "--approve-manifest",
        help="Required in approval mode and must exactly equal --manifest-id.",
    )

    secret = subparsers.add_parser(
        "secret",
        help="Manage the Windows DPAPI LocalMachine secret store used by scheduled execution.",
    )
    secret_subparsers = secret.add_subparsers(dest="secret_command", required=True)
    secret_set = secret_subparsers.add_parser("set", help="Create or replace one encrypted secret.")
    secret_set.add_argument("name")
    secret_set.add_argument(
        "--value-env",
        help="Read the plaintext from this process environment variable instead of prompting.",
    )
    secret_delete = secret_subparsers.add_parser("delete", help="Delete one encrypted secret.")
    secret_delete.add_argument("name")
    secret_subparsers.add_parser("status", help="List configured secret names without values.")

    subparsers.add_parser("notify-test", help="Send one Telegram test message.")
    subparsers.add_parser("status", help="Display local standalone-agent state.")
    subparsers.add_parser("validate-config", help="Validate configuration and paths.")
    return parser


def _policy_for(config):
    return load_runtime_policy(config.config_path, config.storage.root)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            config_path = args.config.expanduser().resolve()
            source_map = args.package_map_source.expanduser().resolve()
            if not source_map.is_file():
                raise FileNotFoundError(f"Package map source does not exist: {source_map}")
            write_default_config(config_path, force=args.force)
            target_map = config_path.parent / "fortios64-package-map.yml"
            if target_map.exists() and not args.force:
                raise FileExistsError(f"Package map already exists: {target_map}")
            shutil.copy2(source_map, target_map)
            print(json.dumps({"config": str(config_path), "package_map": str(target_map)}, indent=2))
            return 0

        if args.command == "scan-host-key":
            info = scan_host_key(args.host, port=args.port, timeout_seconds=args.timeout)
            print(json.dumps(info.to_dict(), indent=2))
            return 0

        config = load_agent_config(args.config)
        policy = _policy_for(config)

        if args.command == "validate-config":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "config": str(config.config_path),
                        "source_page": config.source.page_url,
                        "source_tls_mode": config.source.tls_mode,
                        "storage_root": str(config.storage.root),
                        "evidence_dir": str(config.storage.evidence_dir),
                        "tftp_dir": str(config.storage.tftp_dir),
                        "secret_store": str(policy.secret_store),
                        "execution_mode": config.execution.mode,
                        "device_configured": config.device is not None,
                        "device_host": config.device.host if config.device else None,
                        "apply_configured": config.apply is not None,
                        "tftp_advertise_address": (
                            config.apply.tftp_advertise_address if config.apply else None
                        ),
                        "telegram_enabled": policy.telegram.enabled,
                        "telegram_chat_id_configured": bool(policy.telegram.chat_id),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "secret":
            if args.secret_command == "status":
                values = [item.to_dict() for item in list_secrets(policy.secret_store)]
                print(
                    json.dumps(
                        {"secret_store": str(policy.secret_store), "secrets": values},
                        indent=2,
                    )
                )
                return 0
            if args.secret_command == "delete":
                deleted = delete_secret(policy.secret_store, args.name)
                print(json.dumps({"name": args.name.upper(), "deleted": deleted}, indent=2))
                return 0
            if args.secret_command == "set":
                if args.value_env:
                    value = os.environ.get(args.value_env)
                    if not value:
                        raise ValueError(f"Environment variable is empty or unset: {args.value_env}")
                else:
                    first = getpass.getpass(f"Secret value for {args.name}: ")
                    second = getpass.getpass("Confirm secret value: ")
                    if first != second:
                        raise ValueError("Secret confirmation did not match.")
                    value = first
                metadata = set_secret(policy.secret_store, args.name, value)
                print(
                    json.dumps(
                        {
                            "secret_store": str(policy.secret_store),
                            "secret": metadata.to_dict(),
                            "value_displayed": False,
                        },
                        indent=2,
                    )
                )
                return 0

        if args.command == "status":
            state = load_state(config.storage.state_file)
            print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "run":
            result = run_agent_once(config, dry_run=args.dry_run)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "cycle":
            result = run_cycle(config)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 2 if result.status in {"FAILED", "WARNING", "PREPARED_WITH_NOTIFICATION_ERROR"} else 0

        if args.command == "approve":
            result = approve_manifest(config, args.manifest_id)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.status != "FAILED" else 2

        if args.command == "notify-test":
            result = send_notification_test(config)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "preflight":
            result = run_read_only_preflight(config)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.status == "PASS" else 2

        if args.command == "backup-test":
            result = run_backup_test(config)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.status == "PASS" else 2

        if args.command == "apply":
            result = run_controlled_apply(
                config,
                manifest_id=args.manifest_id,
                approval_manifest=args.approve_manifest,
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.status != "FAILED" else 2

        raise AssertionError(f"Unhandled command: {args.command}")
    except Exception as exc:
        print(f"FGOps agent error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
