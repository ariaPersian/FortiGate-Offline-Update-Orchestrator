from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from .agent_config import load_agent_config, write_default_config
from .agent_orchestrator import run_agent_once
from .agent_state import load_state
from .fortigate_preflight import run_read_only_preflight, scan_host_key


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
    subparsers.add_parser("status", help="Display local standalone-agent state.")
    subparsers.add_parser("validate-config", help="Validate configuration and paths.")
    return parser


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
                        "execution_mode": config.execution.mode,
                        "device_configured": config.device is not None,
                        "device_host": config.device.host if config.device else None,
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

        if args.command == "preflight":
            result = run_read_only_preflight(config)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.status == "PASS" else 2

        raise AssertionError(f"Unhandled command: {args.command}")
    except Exception as exc:
        print(f"FGOps agent error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
