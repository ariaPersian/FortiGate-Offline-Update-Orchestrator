# Operator checklist logging

FGOps v0.5.8 writes a separate daily UTF-8 journal for operators and now also provides a consolidated read-only health report for routine production monitoring.

The normal operator workflow is:

```text
run scripts\health_report.py
  -> read OverallHealth
  -> copy Operator values into the RTL Word checklist
  -> investigate WARN/FAIL rows only when required
  -> use operator/technical journals and evidence for deeper review
```

The health report reduces repetitive manual checks. It does not replace the operator journal, technical journal, apply reports, manifests, lifecycle state, preflight evidence, or encrypted backups.

See [Operator health report](operator-health-report.md) for the complete health-check contract.

## Files and responsibilities

Runtime logs are written below the configured storage root:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

Health-report evidence is written to:

```text
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.txt
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.json
```

| Artifact | Audience | Purpose |
|---|---|---|
| `fgops-health-*.txt` | Operator / support | Consolidated health result and suggested actions |
| `fgops-health-*.json` | Support / automation | Machine-readable health result and all check values |
| `fgops-operator-YYYY-MM-DD.log` | Operations staff | Per-run ToDo checklist, final status, exit code, suggested action |
| `fgops-YYYY-MM-DD.log` | Technical support | Structured JSON events, result payloads, exceptions, tracebacks |

The health report is the first routine review point. The operator journal is the first per-run troubleshooting view. Open the technical journal when the health report or operator journal contains a warning/failure that needs deeper evidence.

## Daily operator command

Run PowerShell as Administrator:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

The script prints a summary and an `Operator values` section. Record those values in the approved Word checklist.

For local-only diagnostics without a FortiGate SSH preflight:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py" `
  --skip-preflight
```

`--skip-preflight` is not a complete production health check and must not be used as a substitute for device verification.

## Health result decision table

| Overall health | Exit code | Normal operator response |
|---|---:|---|
| `HEALTHY` | `0` | Record values, sign the checklist, continue monitoring |
| `WARNING` | `1` | Review each `WARN` row and its action; do not repeat a completed apply automatically |
| `CRITICAL` | `2` | Do not start a new apply; investigate failed checks and preserve evidence |

The health report is intended for normal production state. If the Scheduled Task is deliberately disabled for an authorized maintenance window, `HC-09` will be a failed check by design. Record the maintenance reason and run the full health report again after normal scheduling is restored.

## Word checklist mapping

The Word checklist should copy values from the `Operator values` section rather than asking the operator to derive them manually.

Recommended fields include:

- `ReportTime`;
- `OverallHealth`;
- `TaskState`;
- `TaskLastResult`;
- `TaskLastRunTime`;
- `TaskNextRunTime`;
- `SourceVersion`;
- `InstalledVersion`;
- `ExecutionMode`;
- `EnabledPackages`;
- `StateLastResult`;
- `UnresolvedStateCount`;
- `LatestCycleResult`;
- `LatestCycleAction`;
- `LatestBackup`;
- `LatestBackupAgeDays`;
- `LatestApplyStatus`;
- `LatestManifestId`;
- `FortiGatePreflight`;
- `FortiGateIdentity`;
- `VersionVerification`;
- `HealthReportText`;
- `HealthReportJson`.

The generated report path should be recorded so technical staff can open the exact machine-generated evidence for that checklist entry.

## Operator journal status symbols

The per-run operator journal keeps the existing fixed symbols:

| Symbol | Meaning | Normal response |
|---|---|---|
| `⬜` | Planned and not yet completed | Wait for the run to finish |
| `🔄` | Currently being processed | Do not start another run |
| `✅` | Completed successfully | No action unless another row warns |
| `⚠️` | Warning or attention required | Read the detail and suggested action |
| `❌` | Failed | Stop retries and investigate |
| `⏭️` | Safely skipped because not required | No action |

The journal is plain UTF-8 text and does not depend on terminal colors.

## Run identifier

Every installed `fgops-agent` invocation has a unique run identifier similar to:

```text
20260728T111500+0400-pid4216
```

Every operator line contains `run=<identifier>`. Use it to isolate one run when a daily file contains multiple scheduled or foreground executions.

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "20260728T111500\+0400-pid4216"
```

## Expected cycle outcomes

| Final result | Meaning | Required action |
|---|---|---|
| `NO_CHANGE` | No new archive bytes require processing | None |
| `NO_CONTENT_CHANGE` | ZIP bytes changed but enabled payload was already applied | None; device-changing steps were skipped |
| `NO_UPDATE` | Controlled apply confirmed enabled packages were already current | None; do not repeat the apply |
| `SUCCESS` | Apply and verification completed | Retain evidence and continue monitoring |
| `SUCCESS_WITH_WARNING` | Safe completion with package/FortiOS warning or already-current package | Review warning rows; usually no retry |
| `PREPARED` | New manifest is waiting for explicit approval | Review manifest and maintenance authorization |
| `SUCCESS_WITH_NOTIFICATION_ERROR` | Main operation succeeded but notification failed | Check notification configuration only |
| `PREPARED_WITH_NOTIFICATION_ERROR` | Manifest prepared but notification failed | Review manifest and notification issue |
| `FAILED` | Mandatory gate, backup, package, or verification failed | Disable/keep scheduling disabled and investigate |
| No final line and last row `🔄` | Run may still be active or terminated unexpectedly | Check process, Task, TFTP, state and technical log before retry |

`PREPARED` is an expected waiting state in approval mode. It is not an apply failure.

## Package-level rows

Controlled apply and approval runs add one row per package result.

Interpretation:

- `✅` means the expected FortiGuard object version increased;
- `⚠️` can mean an already-current package or a non-blocking warning;
- `❌` means activation failed or could not be confirmed;
- an explicit already-current classification must not be converted into a manual retry.

A successful TFTP transfer alone is not proof of database activation. The apply report and before/after `diagnose autoupdate versions` evidence remain authoritative.

## When to open the operator journal manually

The health report already reads the latest scheduled cycle. Manual log review is normally needed when:

- `OverallHealth=WARNING` or `CRITICAL`;
- `LatestCycleResult` is warning, failed, prepared, incomplete, or unexpected;
- `LatestCycleAction` requests review;
- an incident requires the exact per-run sequence;
- technical support asks for one run identifier.

Useful commands:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"
Get-Content $OperatorLog -Tail 150
```

Display final results and actions:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "نتیجه نهایی:|اقدام پیشنهادی اپراتور:"
```

Display warnings and failures:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "⚠️|❌"
```

## Failure response

When `OverallHealth=CRITICAL`, a cycle result is `FAILED`, or a run ends without a final result:

1. Do not start a new `cycle`, `approve`, or `apply`.
2. If scheduling is not already disabled and the failure can affect device-changing operations, disable the Scheduled Task.
3. Preserve the generated health TXT/JSON report.
4. Record the failed `HC-xx` rows.
5. Record the latest cycle run identifier, manifest ID, and package name when available.
6. Open the matching operator journal and identify the first `❌` row.
7. Open the technical journal for the same execution period.
8. Preserve the related apply report, preflight/postflight evidence, encrypted backup, state file, quarantine directory, and retained TFTP evidence.
9. Escalate the evidence for technical review before retrying.
10. Restore normal scheduling only after the issue is reviewed and a normal-state health check is accepted.

Disable scheduling when required:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Technical-log fallback:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log" -Tail 200
```

## Incomplete run

If the latest operator row remains `🔄` and there is no final result, do not launch another run until the previous execution is resolved.

```powershell
Get-Process -Name "fgops-agent","python" -ErrorAction SilentlyContinue
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor"
```

An incomplete run is not safe to clear by deleting state, manifest, archives, or evidence.

## Upgrade validation

After source/package upgrade, validate the installed version and runtime before normal scheduling is restored. The current documentation baseline remains `0.5.8`.

Because a deliberately disabled Task is classified as unhealthy, perform maintenance checks while the Task is disabled, then restore the Task and run the normal-state health report.

After re-enabling scheduling:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

Confirm:

- source and installed versions match;
- the private Git origin is correct;
- Scheduled Task action invokes the production `cycle` command;
- there are no unresolved `APPLY_FAILED` / `REVIEW_REQUIRED` entries;
- the latest cycle is complete;
- FortiGate read-only preflight passes;
- current FortiGuard versions do not regress below the latest apply evidence.

See [Private repository synchronization](private-repository-sync.md) for production repository alignment.

## Retention

The operator and technical daily logs use `FGOPS_LOG_RETENTION_DAYS`.

Health reports under `C:\ProgramData\FGOps\reports\health` are timestamped evidence and are **not** deleted by the daily-log retention setting. Apply an approved retention policy to that directory and preserve incident/upgrade reports as required.

## Security boundary

Operator logs and health reports can contain device identity, source/repository metadata, manifest IDs, archive hashes, package names, backup/report paths, FortiGuard versions, notification status, and failure messages. They do not intentionally contain plaintext secret values.

Treat them as sensitive operational records:

- keep them outside Git;
- restrict access to the runtime host;
- retain only according to policy;
- sanitize before sharing outside the authorized operations team;
- never attach unsanitized production health reports or logs to a public issue.

## Related documentation

- [Operator health report](operator-health-report.md)
- [Daily runtime logging](daily-runtime-logging.md)
- [Production operations](operations.md)
- [Read-only preflight](read-only-preflight.md)
- [Controlled apply](controlled-apply.md)
- [Private repository synchronization](private-repository-sync.md)
