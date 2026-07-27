from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .agent_config import load_agent_config, write_default_config
from .agent_orchestrator import run_agent_once
from .agent_state import load_state
from .backup_test import run_backup_test
from .controlled_apply import run_controlled_apply
from .cycle import approve_manifest, run_cycle, send_notification_test
from .daily_logging import configure_daily_logging, log_event
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


def _payload(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _emit_json(
    logger: logging.Logger,
    *,
    command: str,
    event: str,
    value: Any,
    exit_code: int = 0,
) -> int:
    payload = _payload(value)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    log_event(logger, event, command=command, exit_code=exit_code, result=payload)
    log_event(logger, "command.completed", command=command, exit_code=exit_code)
    return exit_code


def _configure_logger(config_path: Path) -> logging.Logger:
    # The configuration normally lives directly below the storage root
    # (C:\ProgramData\FGOps). This bootstrap location also captures failures that
    # occur before the YAML can be fully loaded and validated.
    return configure_daily_logging(config_path.expanduser().resolve().parent)


def _move_logger_to_storage(
    logger: logging.Logger,
    *,
    config_path: Path,
    storage_root: Path,
    command: str,
) -> logging.Logger:
    bootstrap_root = config_path.expanduser().resolve().parent
    resolved_root = storage_root.expanduser().resolve()
    if resolved_root == bootstrap_root:
        return logger
    logger = configure_daily_logging(resolved_root)
    log_event(
        logger,
        "command.logging_relocated",
        command=command,
        config=str(config_path),
        storage_root=str(resolved_root),
    )
    return logger


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = _configure_logger(args.config)
    log_event(
        logger,
        "command.started",
        command=args.command,
        config=str(args.config.expanduser().resolve()),
    )

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
            return _emit_json(
                logger,
                command=args.command,
                event="config.initialized",
                value={"config": str(config_path), "package_map": str(target_map)},
            )

        if args.command == "scan-host-key":
            info = scan_host_key(args.host, port=args.port, timeout_seconds=args.timeout)
            return _emit_json(
                logger,
                command=args.command,
                event="host_key.scanned",
                value=info,
            )

        config = load_agent_config(args.config)
        logger = _move_logger_to_storage(
            logger,
            config_path=config.config_path,
            storage_root=config.storage.root,
            command=args.command,
        )
        config.storage.create_directories()
        policy = _policy_for(config)

        if args.command == "validate-config":
            return _emit_json(
                logger,
                command=args.command,
                event="config.validated",
                value={
                    "valid": True,
                    "config": str(config.config_path),
                    "source_page": config.source.page_url,
                    "source_tls_mode": config.source.tls_mode,
                    "storage_root": str(config.storage.root),
                    "logs_dir": str(config.storage.root / "logs"),
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
            )

        if args.command == "secret":
            if args.secret_command == "status":
                values = [item.to_dict() for item in list_secrets(policy.secret_store)]
                return _emit_json(
                    logger,
                    command=args.command,
                    event="secret.status",
                    value={"secret_store": str(policy.secret_store), "secrets": values},
                )
            if args.secret_command == "delete":
                deleted = delete_secret(policy.secret_store, args.name)
                return _emit_json(
                    logger,
                    command=args.command,
                    event="secret.deleted",
                    value={"name": args.name.upper(), "deleted": deleted},
                )
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
                return _emit_json(
                    logger,
                    command=args.command,
                    event="secret.updated",
                    value={
                        "secret_store": str(policy.secret_store),
                        "secret": metadata.to_dict(),
                        "value_displayed": False,
                    },
                )

        if args.command == "status":
            state = load_state(config.storage.state_file)
            return _emit_json(
                logger,
                command=args.command,
                event="state.displayed",
                value=state,
            )

        if args.command == "run":
            result = run_agent_once(config, dry_run=args.dry_run)
            return _emit_json(
                logger,
                command=args.command,
                event="monitor.completed",
                value=result,
            )

        if args.command == "cycle":
            result = run_cycle(config)
            exit_code = (
                2
                if result.status in {"FAILED", "WARNING", "PREPARED_WITH_NOTIFICATION_ERROR"}
                else 0
            )
            return _emit_json(
                logger,
                command=args.command,
                event="cycle.completed",
                value=result,
                exit_code=exit_code,
            )

        if args.command == "approve":
            result = approve_manifest(config, args.manifest_id)
            exit_code = 0 if result.status != "FAILED" else 2
            return _emit_json(
                logger,
                command=args.command,
                event="approval.completed",
                value=result,
                exit_code=exit_code,
            )

        if args.command == "notify-test":
            result = send_notification_test(config)
            return _emit_json(
                logger,
                command=args.command,
                event="notification.test_completed",
                value=result,
            )

        if args.command == "preflight":
            result = run_read_only_preflight(config)
            exit_code = 0 if result.status == "PASS" else 2
            return _emit_json(
                logger,
                command=args.command,
                event="preflight.completed",
                value=result,
                exit_code=exit_code,
            )

        if args.command == "backup-test":
            result = run_backup_test(config)
            exit_code = 0 if result.status == "PASS" else 2
            return _emit_json(
                logger,
                command=args.command,
                event="backup_test.completed",
                value=result,
                exit_code=exit_code,
            )

        if args.command == "apply":
            result = run_controlled_apply(
                config,
                manifest_id=args.manifest_id,
                approval_manifest=args.approve_manifest,
            )
            exit_code = 0 if result.status != "FAILED" else 2
            return _emit_json(
                logger,
                command=args.command,
                event="apply.completed",
                value=result,
                exit_code=exit_code,
            )

        raise AssertionError(f"Unhandled command: {args.command}")
    except Exception as exc:
        logger.exception(
            json.dumps(
                {
                    "event": "command.failed",
                    "command": args.command,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        print(f"FGOps agent error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
