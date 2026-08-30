# Operator health report

FGOps provides a read-only operator health script at:

```text
C:\FGOps\scripts\health_report.py
```

The script consolidates the routine checks that previously required several PowerShell and `fgops-agent` commands. It is intended for normal production-state health monitoring and for filling the operator Word checklist with a consistent set of values.

## Run the health report

Run PowerShell as Administrator and execute:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

The script prints a check-by-check summary followed by an `Operator values` section. Copy those values into the operator checklist rather than re-running each low-level command manually.

For local-only diagnostics that must not open an SSH session to the FortiGate, use:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py" `
  --skip-preflight
```

`--skip-preflight` is a diagnostic shortcut only. It does not provide full device-health verification and must not be treated as equivalent to a complete production health report.

## Safety boundary

The health script is observational. It does **not** execute:

- `cycle`;
- `approve`;
- `apply`;
- `backup-test`;
- any FortiGate restore command.

Its only active FortiGate operation is the existing pinned read-only preflight. That preflight uses the same independently verified SSH host-key pin and target-identity checks as the controlled apply path, and its command allowlist remains limited to:

```text
get system status
diagnose autoupdate versions
diagnose sys flash list
diagnose debug config-error-log read
diagnose autoupdate signature check-all
```

The script can therefore create new read-only preflight evidence, but it does not start TFTP, create a configuration backup, restore a package, approve a manifest, or change FortiGate configuration.

## Overall health and exit codes

| Overall result | Exit code | Meaning | Operator action |
|---|---:|---|---|
| `HEALTHY` | `0` | No failed or warning health checks | Record the values and continue normal monitoring |
| `WARNING` | `1` | No failed checks, but one or more warnings need review | Read the warning rows and their action text before closing the checklist |
| `CRITICAL` | `2` | At least one health check failed | Do not start a new apply; investigate the failed rows and follow the failure runbook |

`INFO` rows do not by themselves change the overall result.

The script is designed for the **normal production state**. A deliberately disabled Scheduled Task is therefore reported as a failed health check. During an authorized maintenance or upgrade window, record that the Task is intentionally disabled and use the maintenance validation procedure. Run the full health report again after normal scheduling has been restored.

## Checks performed

The current script performs 20 checks:

| ID | Check | Main evidence |
|---|---|---|
| `HC-01` | Project root | `C:\FGOps` exists |
| `HC-02` | Git origin | Production checkout points to the reviewed private repository |
| `HC-03` | Git branch | Expected branch is `main` |
| `HC-04` | Git working tree | Detects uncommitted or untracked source changes |
| `HC-05` | Installed/source version | Installed `fgops` version equals `pyproject.toml` |
| `HC-06` | Configuration validation | Production YAML loads successfully |
| `HC-07` | Execution safety policy | Unknown rejection, downgrade prevention, and package allowlist |
| `HC-08` | Secret-store readiness | Required secret names exist without exposing values |
| `HC-09` | Scheduled Task state | Task is normally `Ready` or `Running` |
| `HC-10` | Scheduled Task last result | Previous Task exit result |
| `HC-11` | Scheduled Task action | Expected executable, production config path, and `cycle` command |
| `HC-12` | Unresolved archive state | Detects `APPLY_FAILED` or `REVIEW_REQUIRED` |
| `HC-13` | Agent last result | Last persisted agent result |
| `HC-14` | Latest cycle result | Reads the latest scheduled `cycle` from operator journals |
| `HC-15` | Latest encrypted backup | Presence, size, and age of the newest retained backup |
| `HC-16` | Latest apply report | Overall and package-level status of the newest apply report |
| `HC-17` | UDP/69 idle | Detects an unexpected TFTP listener outside an active run |
| `HC-18` | Runtime free disk space | Free space on the runtime volume |
| `HC-19` | FortiGate read-only preflight | Pinned SSH, identity, FortiOS and read-only command results |
| `HC-20` | Apply/current version verification | Reconciles current FortiGuard versions with the latest apply evidence |

The default policy values are:

```text
Expected private origin:
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git

Recommended enabled packages:
AV, IPS, APDB, MCDB, MMDB

Maximum backup age before warning:
30 days

Minimum free disk space before warning:
2 GB
```

These can be overridden for controlled diagnostic use with command-line parameters, but production policy changes must be reviewed rather than hidden by parameter overrides.

## Operator values

The console, TXT report, and JSON report expose the same `Operator values` fields. The Word checklist should use these keys directly:

| Key | What the operator records |
|---|---|
| `ReportTime` | Health-report execution time |
| `OverallHealth` | `HEALTHY`, `WARNING`, or `CRITICAL` |
| `TaskState` | Current Scheduled Task state |
| `TaskLastResult` | Previous Task result code |
| `TaskLastRunTime` | Previous Task execution time |
| `TaskNextRunTime` | Next scheduled execution |
| `SourceVersion` | Version declared by the checked-out source |
| `InstalledVersion` | Version installed in the active Python environment |
| `ExecutionMode` | `prepare_only`, `approval`, or `unattended` |
| `EnabledPackages` | Current package allowlist |
| `StateLastResult` | Last persisted FGOps result |
| `UnresolvedStateCount` | Count of unresolved `APPLY_FAILED` / `REVIEW_REQUIRED` entries |
| `LatestCycleResult` | Latest scheduled cycle result |
| `LatestCycleAction` | Suggested operator action from that cycle |
| `LatestBackup` | Newest retained encrypted backup path |
| `LatestBackupAgeDays` | Age of the newest retained backup |
| `LatestApplyStatus` | Newest apply-report status |
| `LatestManifestId` | Manifest ID associated with the newest apply report |
| `FortiGatePreflight` | Read-only preflight status |
| `FortiGateIdentity` | Observed hostname, model, FortiOS version, and build |
| `VersionVerification` | Current-vs-latest-apply version reconciliation |
| `HealthReportText` | Generated TXT report path |
| `HealthReportJson` | Generated JSON report path |

The Word checklist is an operator record; the generated JSON/TXT files remain the machine-generated evidence for the same execution.

## Report files

Every invocation creates timestamped files below:

```text
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.txt
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.json
```

The JSON file contains:

- capture time;
- overall health;
- failure and warning counts;
- the complete `operator_values` object;
- all check IDs, names, statuses, values, and suggested actions.

The TXT file is intended for direct operator or support review and contains the same information in a readable format.

Health reports are **not** rotated by `FGOPS_LOG_RETENTION_DAYS`; that setting applies to the date-named operator and technical journals. Define an organizational retention policy for `reports\health` and preserve reports associated with incidents, upgrades, or maintenance approvals.

## Daily operator procedure

For the normal production state:

1. Open an elevated PowerShell session.
2. Run `scripts\health_report.py` once.
3. Record `ReportTime`, `OverallHealth`, Task values, current FGOps version, latest cycle/apply/backup values, FortiGate identity, preflight, and version verification in the Word checklist.
4. If the result is `HEALTHY`, close the checklist after the normal sign-off.
5. If the result is `WARNING`, review every `WARN` row and its `Action:` line; do not repeat a completed apply merely because a warning exists.
6. If the result is `CRITICAL`, do not start a new apply. Review the failed check IDs, operator journal, technical journal, state, and related evidence.
7. Preserve the generated TXT/JSON report with the shift or incident record when organizational policy requires it.

The health report reduces routine operator work; it does not replace the operator journal, technical journal, apply report, manifest, state, backup, or FortiGate evidence. Those artifacts remain authoritative for incident investigation and package-activation proof.

## Interpreting common results

### `HC-02 Git origin = FAIL`

The production checkout does not point to the authoritative private repository. Do not upgrade by pulling the former public history. Follow [Private repository synchronization](private-repository-sync.md).

### `HC-05 Installed/source version = FAIL`

The checked-out source and active virtual environment differ. Disable scheduling during the maintenance correction, reinstall the checked-out project into `C:\FGOps\venv`, validate the runtime, restore scheduling, and run the health report again.

### `HC-09 Scheduled Task state = FAIL`

If the Task was intentionally disabled for an authorized maintenance window, record that reason. Otherwise investigate why normal scheduling is not `Ready`/`Running`.

### `HC-12 Unresolved archive state = FAIL`

Do not run `cycle`, `approve`, or `apply` merely to clear the state. Preserve the evidence and investigate the exact archive and manifest first.

### `HC-14 Latest cycle result = FAIL`

A `FAILED` cycle or a run without a final line requires investigation before retry. Correlate the run identifier with the operator and technical journals.

### `HC-15 Latest encrypted backup = WARN`

This does not create a backup automatically. `backup-test` remains a separate maintenance operation because it starts temporary TFTP and causes the FortiGate to export an encrypted full configuration. Run it only in an authorized maintenance check.

### `HC-17 UDP/69 idle = WARN`

Confirm that no third-party or stale TFTP process is listening. An active FGOps backup/apply run can legitimately own the port; do not start another overlapping operation.

### `HC-19 FortiGate read-only preflight = FAIL`

Check the pinned host key, credential availability, management path, expected hostname/model/FortiOS branch/build, and read-only command results. Do not bypass host-key or identity checks.

### `HC-20 Apply/current version verification = FAIL`

At least one currently observed FortiGuard object is older than the version recorded after the latest apply. Treat this as a device/evidence inconsistency that requires technical review. A successful historical TFTP transfer is not sufficient proof of current activation.

## Development and public checkout note

By default, `HC-02` expects the authoritative private production remote. Running the script directly in the former public development checkout will therefore report a Git-origin failure unless `--expected-remote` is deliberately overridden. That override is useful for development diagnostics only and must not be used to make a public production checkout appear healthy.

Before relying on the script in production, confirm that the reviewed private `main` branch contains:

```text
scripts/health_report.py
```

Then pull the private repository on the production VM according to the normal upgrade procedure.

## Related documentation

- [Operator checklist logging](operator-checklist-logging.md)
- [Daily runtime logging](daily-runtime-logging.md)
- [Production operations](operations.md)
- [Read-only FortiGate preflight](read-only-preflight.md)
- [Backup test](backup-test.md)
- [Controlled apply](controlled-apply.md)
- [Private repository synchronization](private-repository-sync.md)
