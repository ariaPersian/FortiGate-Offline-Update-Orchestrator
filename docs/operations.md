# Production operations

This runbook covers routine operation of FGOps v0.5.8 on a Windows VM after installation and initial validation.

The authoritative production source repository is:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private
```

Production upgrades must not be pulled from the former public repository.

## Normal operating model

```text
Scheduled Task every configured interval
  -> fgops-agent cycle
  -> operator + technical daily journals
  -> source/package preparation
  -> approval wait or unattended controlled apply
  -> pinned preflight + mandatory encrypted backup when apply runs
  -> package restore + version verification + postflight
  -> final cycle result + reports + state + evidence

Operator once per shift/day
  -> scripts\health_report.py
  -> consolidated HEALTHY / WARNING / CRITICAL
  -> copy Operator values into the Word checklist
  -> investigate only WARN/FAIL rows when required
```

The health report replaces the long sequence of routine manual status commands. It does not replace technical evidence, maintenance controls, or explicit approval.

See [Operator health report](operator-health-report.md) for the complete health-check contract.

## Validated production profile

Recommended enabled packages:

```yaml
execution:
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
  reject_unknown_packages: true
  prevent_downgrade: true
```

For the first live run after an upgrade or material change, use `approval` mode. Move to `unattended` only after the exact target profile has a reviewed successful evidence set.

FFDB is excluded from the recommended default. On the validated FortiGate 300D / FortiOS 6.4.16 profile, the tested FFDB package transferred but failed activation with return code `49` while both expected Internet-service database versions remained unchanged.

## Routine operator health check

Run PowerShell as Administrator:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

The script checks:

- production Git origin, `main` branch, and working-tree status;
- source/installed FGOps version parity;
- configuration and fail-closed execution policy;
- required DPAPI secret metadata without displaying values;
- Scheduled Task state, last result, next run, executable, config path, and `cycle` action;
- unresolved `APPLY_FAILED` / `REVIEW_REQUIRED` archives;
- latest scheduled-cycle result from the operator journals;
- latest encrypted backup and latest apply report;
- UDP/69 listener state and runtime disk capacity;
- pinned read-only FortiGate preflight;
- current FortiGuard object versions against the latest apply report.

It writes:

```text
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.txt
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.json
```

### Health decisions

| Result | Exit | Meaning | Action |
|---|---:|---|---|
| `HEALTHY` | `0` | No failed or warning checks | Record values and continue normal monitoring |
| `WARNING` | `1` | One or more warnings require review | Review warning rows and actions; do not automatically repeat an apply |
| `CRITICAL` | `2` | At least one failed health check | Do not start a new apply; investigate failed rows and preserve evidence |

The health report is designed for **normal production state**. A deliberately disabled Scheduled Task is therefore classified as a failure. During authorized maintenance, record the intentional disabled state and use the maintenance procedure below. Run the full health report again after scheduling has been restored.

For local-only diagnostics without opening a FortiGate SSH session:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py" `
  --skip-preflight
```

`--skip-preflight` is not a complete production health result.

## Health-script safety boundary

The health script does **not** run:

```text
cycle
approve
apply
backup-test
FortiGate restore commands
```

Its only active FortiGate operation is the existing pinned read-only preflight. That path validates the configured host key and expected device identity and runs only the approved read-only commands documented in [Read-only preflight](read-only-preflight.md).

The script does not start TFTP, export a new backup, approve a manifest, restore a package, or change FortiGate configuration.

## Runtime logs and evidence

Daily journals:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

The operator journal is the first per-run troubleshooting view. Symbols:

```text
⬜ planned
🔄 running
✅ success
⚠️ warning / attention
❌ failed
⏭️ safely skipped
```

The technical journal contains structured result payloads, exceptions, and tracebacks.

The health report is the first routine monitoring view. Open the operator journal when the health report points to the latest cycle or when one exact run must be reviewed. Open the technical journal when deeper failure detail is required.

## Expected cycle outcomes

| Cycle result | Interpretation | Operator action |
|---|---|---|
| `NO_CHANGE` | Same archive already handled | None |
| `NO_CONTENT_CHANGE` | ZIP bytes changed but enabled payload was already applied | None; no device-changing path |
| `NO_UPDATE` | Controlled apply found enabled packages already current | None; do not repeat apply |
| `PREPARED` | New manifest waits for approval | Review manifest, package list, target, and maintenance authorization |
| `SUCCESS` | Apply and verification completed | Retain evidence and continue monitoring |
| `SUCCESS_WITH_WARNING` | Safe completion with warning/already-current package | Review report; usually no retry |
| `SUCCESS_WITH_NOTIFICATION_ERROR` | Main operation succeeded, notification failed | Fix notification path only |
| `PREPARED_WITH_NOTIFICATION_ERROR` | Manifest prepared, notification failed | Review manifest and notification issue |
| `FAILED` | Mandatory gate, backup, package, or verification failed | Disable/keep scheduling disabled and investigate |

A successful TFTP transfer proves file delivery only. Package activation is classified from FortiGuard object-version evidence and trusted FortiOS results.

## Approval-mode live apply

When a new archive is `PREPARED`, inspect the generated manifest and matching `agent-plan.json` before approval.

Confirm:

- the manifest belongs to the current run;
- source and target are expected;
- archive/package SHA-256 values are present;
- every enabled package kind is unique;
- no package is `UNKNOWN`;
- `IGNORED` entries are only reviewed exact exclusions;
- enabled packages are limited to the approved allowlist;
- the maintenance window is authorized.

To prevent overlap, disable the Scheduled Task before a foreground approval/apply:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Confirm no existing run is active:

```powershell
Get-Process -Name "fgops-agent","python" -ErrorAction SilentlyContinue
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
```

Approve the exact reviewed manifest:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  approve `
  --manifest-id FGOPS-0123456789ABCDEF
```

Follow the operator journal in another PowerShell window when desired:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log" -Wait
```

The controlled apply path is:

```text
manifest/policy gate
  -> package hash verification
  -> pinned read-only preflight
  -> temporary TFTP
  -> mandatory encrypted full-config backup
  -> permanent backup SHA-256 verification
  -> enabled package restore in configured order
  -> version check after each package
  -> postflight
  -> JSON/TXT apply report
  -> lifecycle state update
  -> TFTP cleanup
```

A failed mandatory backup blocks package restores.

## Verify a completed apply

The health report automatically reconciles current FortiGuard versions with the latest apply report as `HC-20`.

For manual technical verification, inspect the newest apply report:

```powershell
$Report = Get-ChildItem C:\ProgramData\FGOps\reports `
  -Filter "*-apply.json" -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Get-Content $Report.FullName -Raw | ConvertFrom-Json
```

On the FortiGate:

```text
diagnose autoupdate versions
diagnose autoupdate signature check-all
```

The report and current FortiGuard versions must agree. A changed timestamp or a historical TFTP-success message without version evidence is not sufficient proof of activation.

## Re-enable scheduling after maintenance

Do not re-enable scheduling after `FAILED`, an incomplete run, or an unresolved safety warning.

When the foreground operation is accepted:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Then run the normal-state health report:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

Record the resulting `Operator values` in the Word checklist.

## Upgrade FGOps from the private repository

Disable scheduling during source/environment changes:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

Set-Location C:\FGOps
git remote -v
git status --short
git branch --show-current
```

The production origin must be:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git
```

Pull only the reviewed private `main`:

```powershell
git fetch --prune origin
git switch main
git pull --ff-only
```

Reinstall the checked-out project into the existing virtual environment:

```powershell
& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --force-reinstall --no-deps C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

Confirm the operator-health script exists:

```powershell
Test-Path "C:\FGOps\scripts\health_report.py"
```

Validate while the Task is still disabled:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  validate-config

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  run --dry-run
```

Accept a preparation-plane result only when state has no unresolved `APPLY_FAILED` or `REVIEW_REQUIRED` entry. For `PREPARED`, inspect the manifest before any approval.

After maintenance validation is accepted, enable the Task and run the full health report. A `WARNING` must be reviewed; a `CRITICAL` must not be ignored merely to restore unattended operation.

If the private/public histories diverge, follow [Private repository synchronization](private-repository-sync.md). Do not temporarily point the production VM at the public origin to obtain the health script or documentation.

## Failure response

When a cycle is `FAILED`, the latest run is incomplete, or the health report is `CRITICAL` due to an operational safety failure:

1. do not run a new `cycle`, `approve`, or `apply`;
2. disable or keep the Scheduled Task disabled when the failure can affect device-changing operations;
3. preserve the health TXT/JSON report;
4. record failed `HC-xx` checks;
5. preserve the latest operator run identifier and first `❌` row;
6. preserve the technical journal;
7. preserve apply JSON/TXT, preflight/postflight evidence, encrypted backup, state, quarantine, and retained TFTP evidence;
8. compare current FortiGuard versions with the last known apply evidence;
9. correct the root cause before retry;
10. retry in the foreground;
11. restore scheduling only after a reviewed result and a normal-state health report.

Do not delete state, edit a manifest, rename an unknown package, broaden the package map, disable downgrade protection, or repeat an uncertain apply merely to clear the failure.

## Incomplete run

If the latest operator row remains `🔄` and there is no final result:

```powershell
Get-Process -Name "fgops-agent","python" -ErrorAction SilentlyContinue
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor"
```

Do not start another run until the previous execution is resolved.

## FFDB troubleshooting

The default production profile excludes FFDB unless independently validated.

If FFDB is enabled and FortiOS returns code `49`, allow the bounded polling behavior to finish without submitting another FFDB package. Treat unchanged expected Internet-service database versions as failure, not as an already-current success.

When compatibility cannot be established, remove FFDB from `execution.enabled_packages` and retain the evidence.

## Retention and cleanup

`FGOPS_LOG_RETENTION_DAYS` controls date-named operator and technical journals.

It does **not** rotate timestamped health reports under:

```text
C:\ProgramData\FGOps\reports\health
```

Define organizational retention for:

- incoming archives;
- quarantine manifests and package copies;
- encrypted backups;
- preflight/postflight evidence;
- apply reports;
- health reports;
- operator daily journals;
- technical daily journals;
- recovery state backups;
- manually captured FortiGate debug output.

Never delete the only known-good encrypted configuration backup during routine cleanup.

## Related documentation

- [Operator health report](operator-health-report.md)
- [Operator checklist logging](operator-checklist-logging.md)
- [Daily runtime logging](daily-runtime-logging.md)
- [Standalone Windows agent](standalone-agent.md)
- [Controlled apply](controlled-apply.md)
- [Backup test](backup-test.md)
- [Read-only preflight](read-only-preflight.md)
- [Private repository synchronization](private-repository-sync.md)
- [Source bundle ingestion](source-bundle-ingestion.md)
- [Payload-level deduplication](payload-deduplication.md)
