#!/usr/bin/env python3
"""Read-only operator health report for the Windows FGOps runtime.

The script does not execute cycle, approve, apply, backup-test, or any FortiGate
restore command. Its only active FortiGate operation is the existing pinned
read-only preflight. Reports are written under
C:\\ProgramData\\FGOps\\reports\\health.

Exit codes: 0=HEALTHY, 1=WARNING, 2=CRITICAL.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from fgops.agent_config import load_agent_config
from fgops.agent_state import load_state
from fgops.fortigate_preflight import run_read_only_preflight
from fgops.runtime_policy import load_runtime_policy
from fgops.secret_store import list_secrets, secret_environment

RECOMMENDED_PACKAGES = {"AV", "IPS", "APDB", "MCDB", "MMDB"}
UNRESOLVED_STATES = {"APPLY_FAILED", "REVIEW_REQUIRED"}


@dataclass
class Check:
    id: str
    name: str
    status: str
    value: str
    action: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only FGOps operator health report.")
    parser.add_argument("--project-root", type=Path, default=Path(r"C:\FGOps"))
    parser.add_argument("--runtime-root", type=Path, default=Path(r"C:\ProgramData\FGOps"))
    parser.add_argument("--config", type=Path, default=Path(r"C:\ProgramData\FGOps\config.yml"))
    parser.add_argument("--task-name", default="FGOps Offline Update Monitor")
    parser.add_argument(
        "--expected-remote",
        default="https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git",
    )
    parser.add_argument("--max-backup-age-days", type=float, default=30.0)
    parser.add_argument("--min-free-space-gb", type=float, default=2.0)
    parser.add_argument("--skip-preflight", action="store_true")
    return parser.parse_args()


def run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return 127, str(exc)
    text = (completed.stdout or completed.stderr or "").strip()
    return completed.returncode, text


def powershell_json(script: str) -> tuple[bool, Any, str]:
    code, text = run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "$ErrorActionPreference='Stop';" + script,
        ]
    )
    if code != 0:
        return False, None, text
    try:
        return True, json.loads(text) if text else None, text
    except json.JSONDecodeError:
        return False, None, f"Invalid PowerShell JSON output: {text}"


def git_value(project_root: Path, *args: str) -> tuple[int, str]:
    return run(["git", "-C", str(project_root), *args])


def latest_cycle_result(log_dir: Path) -> dict[str, Any] | None:
    files = sorted(log_dir.glob("fgops-operator-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:7]
    if not files:
        return None
    lines: list[str] = []
    for path in reversed(files):
        try:
            lines.extend(path.read_text(encoding="utf-8-sig", errors="replace").splitlines())
        except OSError:
            continue
    starts = [line for line in lines if re.search(r"فرمان:\s*cycle", line)]
    if not starts:
        return None
    match = re.search(r"run=([^\s]+)", starts[-1])
    if not match:
        return None
    run_id = match.group(1)
    run_re = re.compile(rf"run={re.escape(run_id)}(?:\s|$)")
    run_lines = [line for line in lines if run_re.search(line)]
    finals = [line for line in run_lines if "نتیجه نهایی:" in line]
    actions = [line for line in run_lines if "اقدام پیشنهادی اپراتور:" in line]
    status = None
    if finals:
        result_match = re.search(r"نتیجه نهایی:\s*([A-Z0-9_]+)", finals[-1])
        status = result_match.group(1) if result_match else None
    action = "-"
    if actions:
        action = actions[-1].split("اقدام پیشنهادی اپراتور:", 1)[-1].strip()
    return {"run_id": run_id, "has_final": bool(finals), "status": status, "action": action}


def version_parts(value: str) -> tuple[int, ...] | None:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(item) for item in parts) if parts else None


def compare_versions(current: str, expected: str) -> int | None:
    if current == expected:
        return 0
    left = version_parts(current)
    right = version_parts(expected)
    if left is None or right is None:
        return None
    count = max(len(left), len(right))
    a = left + (0,) * (count - len(left))
    b = right + (0,) * (count - len(right))
    return (a > b) - (a < b)


def main() -> int:
    args = parse_args()
    checks: list[Check] = []

    values: dict[str, Any] = {
        "ReportTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "OverallHealth": "UNKNOWN",
        "TaskState": "-",
        "TaskLastResult": "-",
        "TaskLastRunTime": "-",
        "TaskNextRunTime": "-",
        "SourceVersion": "-",
        "InstalledVersion": "-",
        "ExecutionMode": "-",
        "EnabledPackages": "-",
        "StateLastResult": "-",
        "UnresolvedStateCount": 0,
        "LatestCycleResult": "-",
        "LatestCycleAction": "-",
        "LatestBackup": "-",
        "LatestBackupAgeDays": "-",
        "LatestApplyStatus": "-",
        "LatestManifestId": "-",
        "FortiGatePreflight": "SKIPPED" if args.skip_preflight else "-",
        "FortiGateIdentity": "-",
        "VersionVerification": "SKIPPED" if args.skip_preflight else "-",
        "HealthReportText": "-",
        "HealthReportJson": "-",
    }

    def add(check_id: str, name: str, status: str, value: Any, action: str = "") -> None:
        checks.append(Check(check_id, name, status, str(value), action))

    # Checkout and installed package.
    if args.project_root.is_dir():
        add("HC-01", "Project root", "PASS", args.project_root)
        code, origin = git_value(args.project_root, "remote", "get-url", "origin")
        if code == 0 and origin.rstrip("/").lower() == args.expected_remote.rstrip("/").lower():
            add("HC-02", "Git origin", "PASS", origin)
        else:
            add("HC-02", "Git origin", "FAIL", origin or "unavailable", "Production must use the reviewed private remote.")
        code, branch = git_value(args.project_root, "branch", "--show-current")
        add("HC-03", "Git branch", "PASS" if code == 0 and branch == "main" else "WARN", branch or "unavailable")
        code, dirty = git_value(args.project_root, "status", "--porcelain")
        add("HC-04", "Git working tree", "PASS" if code == 0 and not dirty else "WARN", "Clean" if not dirty else dirty[:600])
    else:
        add("HC-01", "Project root", "FAIL", f"Missing: {args.project_root}")
        add("HC-02", "Git origin", "FAIL", "Unavailable")
        add("HC-03", "Git branch", "WARN", "Unavailable")
        add("HC-04", "Git working tree", "WARN", "Unavailable")

    pyproject = args.project_root / "pyproject.toml"
    try:
        values["SourceVersion"] = str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
    except Exception as exc:
        add("HC-05", "Installed/source version", "FAIL", f"Cannot read source version: {exc}")
    try:
        values["InstalledVersion"] = metadata.version("fgops")
        if values["SourceVersion"] != "-":
            if values["InstalledVersion"] == values["SourceVersion"]:
                add("HC-05", "Installed/source version", "PASS", values["InstalledVersion"])
            else:
                add(
                    "HC-05",
                    "Installed/source version",
                    "FAIL",
                    f"installed={values['InstalledVersion']}; source={values['SourceVersion']}",
                    "Reinstall the checked-out source into the venv.",
                )
    except Exception as exc:
        if not any(c.id == "HC-05" for c in checks):
            add("HC-05", "Installed/source version", "FAIL", str(exc))

    # Config, safety policy, and secret metadata.
    config = None
    policy = None
    try:
        config = load_agent_config(args.config)
        policy = load_runtime_policy(config.config_path, config.storage.root)
        values["ExecutionMode"] = config.execution.mode
        values["EnabledPackages"] = ",".join(config.execution.enabled_packages)
        add("HC-06", "Configuration validation", "PASS", f"mode={config.execution.mode}; root={config.storage.root}")

        extras = set(config.execution.enabled_packages) - RECOMMENDED_PACKAGES
        if config.execution.reject_unknown_packages and config.execution.prevent_downgrade and not extras:
            add("HC-07", "Execution safety policy", "PASS", f"packages={values['EnabledPackages']}")
        else:
            add(
                "HC-07",
                "Execution safety policy",
                "WARN",
                f"packages={values['EnabledPackages']}; reject_unknown={config.execution.reject_unknown_packages}; prevent_downgrade={config.execution.prevent_downgrade}",
                "Review the package allowlist and fail-closed policy.",
            )

        configured_secrets = {item.name for item in list_secrets(policy.secret_store)}
        required: set[str] = set()
        if config.device is not None:
            if config.device.key_file is None and config.device.password_env:
                required.add(config.device.password_env.upper())
            elif config.device.key_file is not None and config.device.key_passphrase_env:
                required.add(config.device.key_passphrase_env.upper())
        if config.apply is not None and config.apply.require_backup and config.apply.backup_password_env:
            required.add(config.apply.backup_password_env.upper())
        missing = sorted(required - configured_secrets)
        if missing:
            add("HC-08", "Secret store readiness", "FAIL", "missing=" + ",".join(missing))
        else:
            add("HC-08", "Secret store readiness", "PASS", "required=" + ",".join(sorted(required)))
    except Exception as exc:
        add("HC-06", "Configuration validation", "FAIL", str(exc), "Fix config.yml before any apply.")
        add("HC-07", "Execution safety policy", "INFO", "Unavailable")
        add("HC-08", "Secret store readiness", "INFO", "Unavailable")

    # Scheduled Task.
    task_name = args.task_name.replace("'", "''")
    task_script = f"""
$task=Get-ScheduledTask -TaskName '{task_name}';
$info=Get-ScheduledTaskInfo -TaskName '{task_name}';
$action=@($task.Actions)[0];
[pscustomobject]@{{state=[string]$task.State;last_result=[int64]$info.LastTaskResult;last_run=if($info.LastRunTime){{$info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss')}}else{{'-'}};next_run=if($info.NextRunTime){{$info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss')}}else{{'-'}};execute=[string]$action.Execute;arguments=[string]$action.Arguments}}|ConvertTo-Json -Compress
"""
    ok, task, task_text = powershell_json(task_script)
    if ok and isinstance(task, dict):
        values["TaskState"] = task.get("state", "-")
        values["TaskLastResult"] = str(task.get("last_result", "-"))
        values["TaskLastRunTime"] = task.get("last_run", "-")
        values["TaskNextRunTime"] = task.get("next_run", "-")
        add("HC-09", "Scheduled Task state", "PASS" if values["TaskState"] in {"Ready", "Running"} else "FAIL", values["TaskState"])
        add("HC-10", "Scheduled Task last result", "PASS" if task.get("last_result") == 0 else "WARN", values["TaskLastResult"])
        expected_agent = str(args.project_root / "venv" / "Scripts" / "fgops-agent.exe")
        action_ok = (
            str(task.get("execute", "")).lower() == expected_agent.lower()
            and str(args.config).lower() in str(task.get("arguments", "")).lower()
            and re.search(r"(?:^|\s)cycle(?:\s|$)", str(task.get("arguments", ""))) is not None
        )
        add("HC-11", "Scheduled Task action", "PASS" if action_ok else "FAIL", f"{task.get('execute','')} {task.get('arguments','')}")
    else:
        add("HC-09", "Scheduled Task state", "FAIL", task_text or "Unavailable")
        add("HC-10", "Scheduled Task last result", "INFO", "Unavailable")
        add("HC-11", "Scheduled Task action", "INFO", "Unavailable")

    # Local state and latest scheduled cycle.
    if config is not None:
        try:
            state = load_state(config.storage.state_file)
            values["StateLastResult"] = state.last_result or "-"
            unresolved = [f"{entry.get('status')}:{sha[:12]}" for sha, entry in state.archives.items() if entry.get("status") in UNRESOLVED_STATES]
            values["UnresolvedStateCount"] = len(unresolved)
            add("HC-12", "Unresolved archive state", "PASS" if not unresolved else "FAIL", "; ".join(unresolved) if unresolved else "0")
            last = values["StateLastResult"]
            if last == "FAILED":
                last_status = "FAIL"
            elif re.search(r"WARNING|ERROR|PREPARED", str(last)):
                last_status = "WARN"
            else:
                last_status = "PASS"
            add("HC-13", "Agent last result", last_status, last)
        except Exception as exc:
            add("HC-12", "Unresolved archive state", "FAIL", str(exc))
            add("HC-13", "Agent last result", "FAIL", "Unavailable")
    else:
        add("HC-12", "Unresolved archive state", "FAIL", "Config unavailable")
        add("HC-13", "Agent last result", "FAIL", "Unavailable")

    cycle = latest_cycle_result(args.runtime_root / "logs")
    if cycle is None:
        add("HC-14", "Latest cycle result", "WARN", "No recent scheduled cycle result found")
    elif not cycle["has_final"]:
        values["LatestCycleResult"] = "INCOMPLETE"
        add("HC-14", "Latest cycle result", "FAIL", f"run={cycle['run_id']}; incomplete", "Do not retry until process/Task/TFTP state is checked.")
    else:
        values["LatestCycleResult"] = cycle["status"] or "UNKNOWN"
        values["LatestCycleAction"] = cycle["action"]
        result = values["LatestCycleResult"]
        status = "FAIL" if result == "FAILED" else "WARN" if re.search(r"WARNING|ERROR|PREPARED", result) else "PASS"
        add("HC-14", "Latest cycle result", status, f"run={cycle['run_id']}; result={result}", cycle["action"] if status != "PASS" else "")

    # Backup and latest apply report.
    backups = sorted((args.runtime_root / "evidence" / "backups").glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest_backup = next((p for p in backups if p.is_file()), None)
    if latest_backup is None:
        add("HC-15", "Latest encrypted backup", "WARN", "No backup found", "Run backup-test in an authorized maintenance window before the next live apply.")
    else:
        age_days = round((datetime.now().timestamp() - latest_backup.stat().st_mtime) / 86400, 1)
        values["LatestBackup"] = str(latest_backup)
        values["LatestBackupAgeDays"] = age_days
        if latest_backup.stat().st_size <= 0:
            add("HC-15", "Latest encrypted backup", "FAIL", f"{latest_backup}; size=0")
        elif age_days > args.max_backup_age_days:
            add("HC-15", "Latest encrypted backup", "WARN", f"{latest_backup.name}; ageDays={age_days}")
        else:
            add("HC-15", "Latest encrypted backup", "PASS", f"{latest_backup.name}; size={latest_backup.stat().st_size}; ageDays={age_days}")

    apply_files = sorted((args.runtime_root / "reports").glob("*-apply.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest_apply: dict[str, Any] | None = None
    if not apply_files:
        add("HC-16", "Latest apply report", "INFO", "No apply report found yet")
    else:
        try:
            latest_apply = json.loads(apply_files[0].read_text(encoding="utf-8-sig"))
            values["LatestApplyStatus"] = str(latest_apply.get("status", "-"))
            values["LatestManifestId"] = str(latest_apply.get("manifest_id", "-"))
            packages = latest_apply.get("packages") or []
            package_summary = ",".join(f"{p.get('kind')}={p.get('status')}" for p in packages)
            failed_packages = [p for p in packages if p.get("status") in {"FAILED", "FAILED_UNCONFIRMED"}]
            if values["LatestApplyStatus"] == "FAILED" or failed_packages:
                apply_status = "FAIL"
            elif values["LatestApplyStatus"] == "SUCCESS_WITH_WARNING":
                apply_status = "WARN"
            else:
                apply_status = "PASS"
            add("HC-16", "Latest apply report", apply_status, f"status={values['LatestApplyStatus']}; manifest={values['LatestManifestId']}; {package_summary}")
        except Exception as exc:
            add("HC-16", "Latest apply report", "FAIL", str(exc))

    # UDP/69 and disk.
    ok, udp, udp_text = powershell_json("@((Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue)|Select-Object LocalAddress,LocalPort,OwningProcess)|ConvertTo-Json -Compress")
    if ok:
        listeners = [] if udp is None else udp if isinstance(udp, list) else [udp]
        add("HC-17", "UDP/69 idle", "PASS" if not listeners else "WARN", "No listener detected" if not listeners else json.dumps(listeners, ensure_ascii=False))
    else:
        add("HC-17", "UDP/69 idle", "WARN", udp_text or "Unavailable")

    try:
        free_gb = round(shutil.disk_usage(args.runtime_root).free / (1024**3), 2)
        disk_status = "FAIL" if free_gb < 1 else "WARN" if free_gb < args.min_free_space_gb else "PASS"
        add("HC-18", "Runtime free disk space", disk_status, f"{free_gb} GB")
    except Exception as exc:
        add("HC-18", "Runtime free disk space", "WARN", str(exc))

    # Read-only FortiGate preflight and reconciliation with latest apply evidence.
    preflight = None
    if args.skip_preflight:
        add("HC-19", "FortiGate read-only preflight", "INFO", "Skipped by --skip-preflight")
        add("HC-20", "Apply/current version verification", "INFO", "Skipped")
    elif config is None or policy is None or config.device is None:
        values["FortiGatePreflight"] = "UNAVAILABLE"
        values["VersionVerification"] = "UNAVAILABLE"
        add("HC-19", "FortiGate read-only preflight", "WARN", "Device/config unavailable")
        add("HC-20", "Apply/current version verification", "INFO", "Unavailable")
    else:
        secret_names: list[str] = []
        if config.device.key_file is None and config.device.password_env:
            secret_names.append(config.device.password_env)
        elif config.device.key_file is not None and config.device.key_passphrase_env:
            secret_names.append(config.device.key_passphrase_env)
        try:
            with secret_environment(policy.secret_store, tuple(secret_names)):
                preflight = run_read_only_preflight(config)
            values["FortiGatePreflight"] = preflight.status
            ss = preflight.system_status
            values["FortiGateIdentity"] = f"{ss.hostname} | {ss.model} | v{ss.firmware_version} build{ss.build}"
            add("HC-19", "FortiGate read-only preflight", "PASS" if preflight.status == "PASS" else "FAIL", values["FortiGateIdentity"] if preflight.status == "PASS" else "; ".join((*preflight.validation_errors, *preflight.command_errors)))
        except Exception as exc:
            values["FortiGatePreflight"] = "FAILED"
            add("HC-19", "FortiGate read-only preflight", "FAIL", str(exc), "Check pinned host key, SSH credential, target identity, and management path.")

        if latest_apply is None:
            values["VersionVerification"] = "NO_APPLY_REPORT"
            add("HC-20", "Apply/current version verification", "INFO", "No previous apply report to compare")
        elif preflight is None or preflight.status != "PASS":
            values["VersionVerification"] = "UNAVAILABLE"
            add("HC-20", "Apply/current version verification", "WARN", "Unavailable because preflight did not pass")
        else:
            older: list[str] = []
            unknown: list[str] = []
            verified = 0
            for package in latest_apply.get("packages") or []:
                for obj in package.get("objects") or []:
                    expected = str(obj.get("after_version") or "")
                    if not expected:
                        continue
                    observed = preflight.autoupdate_versions.get(str(obj.get("name")))
                    if not observed or not observed.get("Version"):
                        unknown.append(f"{obj.get('name')}=missing")
                        continue
                    current = str(observed["Version"])
                    comparison = compare_versions(current, expected)
                    if comparison is None:
                        if current == expected:
                            verified += 1
                        else:
                            unknown.append(f"{obj.get('name')}:{current}!={expected}")
                    elif comparison >= 0:
                        verified += 1
                    else:
                        older.append(f"{obj.get('name')}:{current}<{expected}")
            if older:
                values["VersionVerification"] = "FAILED"
                add("HC-20", "Apply/current version verification", "FAIL", "; ".join(older))
            elif unknown:
                values["VersionVerification"] = "WARNING"
                add("HC-20", "Apply/current version verification", "WARN", f"verified={verified}; unresolved=" + "; ".join(unknown))
            else:
                values["VersionVerification"] = "PASS"
                add("HC-20", "Apply/current version verification", "PASS", f"Verified objects: {verified}")

    fail_count = sum(1 for item in checks if item.status == "FAIL")
    warning_count = sum(1 for item in checks if item.status == "WARN")
    if fail_count:
        values["OverallHealth"] = "CRITICAL"
        exit_code = 2
    elif warning_count:
        values["OverallHealth"] = "WARNING"
        exit_code = 1
    else:
        values["OverallHealth"] = "HEALTHY"
        exit_code = 0

    health_dir = args.runtime_root / "reports" / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    text_path = health_dir / f"fgops-health-{stamp}.txt"
    json_path = health_dir / f"fgops-health-{stamp}.json"
    values["HealthReportText"] = str(text_path)
    values["HealthReportJson"] = str(json_path)

    payload = {
        "schema_version": 1,
        "captured_at": datetime.now().astimezone().isoformat(),
        "overall_health": values["OverallHealth"],
        "fail_count": fail_count,
        "warning_count": warning_count,
        "operator_values": values,
        "checks": [asdict(item) for item in checks],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    text_lines = [
        "FGOps HEALTH REPORT",
        f"Generated : {values['ReportTime']}",
        f"Overall   : {values['OverallHealth']}",
        f"Failures  : {fail_count}",
        f"Warnings  : {warning_count}",
        "",
        "OPERATOR VALUES",
    ]
    text_lines.extend(f"{key:24}: {value}" for key, value in values.items())
    text_lines.extend(["", "CHECKS"])
    for item in checks:
        text_lines.append(f"[{item.status}] {item.id} {item.name} - {item.value}")
        if item.action:
            text_lines.append(f"       Action: {item.action}")
    text_path.write_text("\n".join(text_lines) + "\n", encoding="utf-8-sig")

    print("\n============================================================")
    print(" FGOps Health Report")
    print("============================================================")
    print(f" Overall Health : {values['OverallHealth']}")
    print(f" Failures       : {fail_count}")
    print(f" Warnings       : {warning_count}\n")
    for item in checks:
        print(f" [{item.status:4}] {item.id:5} {item.name}: {item.value}")
    print("\nOperator values:")
    for key, value in values.items():
        print(f"  {key:24}: {value}")
    print(f"\nText report : {text_path}")
    print(f"JSON report : {json_path}\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
