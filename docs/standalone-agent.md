# Standalone Windows agent

FGOps v0.5.8 uses a local Windows agent as the primary deployment model for a single FortiGate management target. The authoritative source is the private repository `ariaPersian/FortiGate-Offline-Update-Orchestrator-Private`. GitHub is not required during scheduled production execution.

## Runtime flow

```text
Scheduled Task running as SYSTEM
  -> fgops-agent cycle
  -> open or append today's operator and technical journals
  -> write the operator ToDo checklist
  -> poll configured source page
  -> discover the matching bundle link
  -> bounded atomic ZIP download with transient-error retry
  -> SHA-256 duplicate detection
  -> safe extraction, duplicate verification, and package inventory
  -> immutable local manifest
  -> apply execution policy
  -> load DPAPI-protected secrets when required
  -> pinned SSH preflight
  -> temporary restricted TFTP
  -> encrypted full-config backup
  -> selected package restores and version checks
  -> postflight, report, state update, checklist summary, and cleanup
```

The source parser can match the anchor text, URL, and surrounding list-item context. This supports pages where the product/version label is outside a generic download anchor.

## New checkout

From an elevated PowerShell session:

```powershell
git clone `
  https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git `
  C:\FGOps

Set-Location C:\FGOps

py -3.13 -m venv C:\FGOps\venv
& C:\FGOps\venv\Scripts\python.exe -m pip install --upgrade pip
& C:\FGOps\venv\Scripts\python.exe -m pip install --no-user C:\FGOps
```

Confirm the installed version:

```powershell
& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

The expected release for this document is `0.5.8`.

## Existing checkout and private remote

Before every upgrade, verify the remote:

```powershell
Set-Location C:\FGOps
git remote -v
git status
```

The fetch and push URL must be:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git
```

If the checkout still points to the former public repository, or `git fetch` reports a forced update and `git pull --ff-only` reports diverging branches, do not merge or rebase the histories into the production checkout. Follow [Private repository synchronization](private-repository-sync.md): preserve a safety branch and stash, change the remote, fetch the private branch, and align local `main` with `origin/main`.

## Upgrade to v0.5.8

Disable scheduling while source and the virtual environment are changed:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

Set-Location C:\FGOps
git fetch --prune origin
git switch main
git pull --ff-only

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --force-reinstall --no-deps C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

The forced reinstall is mandatory because a source-only pull can leave older installed modules and a generated `fgops-agent.exe` in the virtual environment. Confirm that `pip show fgops` reports `0.5.8`.

Version 0.5.8 adds bounded source retries and mixed-generation bundle handling. Add `source.retry_attempts` and `source.retry_backoff_seconds` to the production configuration when absent. Back up the production package map, then compare it with the reviewed repository map; copy it only when no approved local customizations exist, otherwise merge the exact `64...` `IGNORED` rule without discarding local policy. See [Source bundle ingestion](source-bundle-ingestion.md) for the decision rules and validation checklist.

Validate configuration and source preparation in the foreground:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  validate-config

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  run --dry-run

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Confirm both daily journals were created:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Item `
  "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log", `
  "C:\ProgramData\FGOps\logs\fgops-$Today.log"
```

Do not re-enable the Scheduled Task until all three commands have a final `نتیجه نهایی:` line, the dry run finishes as `PREPARED`, `NO_CHANGE`, or `NO_CONTENT_CHANGE`, and state contains no unresolved `APPLY_FAILED` or `REVIEW_REQUIRED` archive. If it prepares a new archive, review its manifest warnings and confirm that `planned_packages` contains only the intended enabled families.

## Initialize runtime storage

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  init `
  --package-map-source C:\FGOps\config\fortios64-package-map.yml
```

Copy [`config/agent.example.yml`](../config/agent.example.yml) and replace all example addresses, target identity values, and host-key fingerprints. Production configuration must remain outside the repository.

The `init` command also produces an operator checklist. Configuration-loading steps are marked as safely skipped because this command creates the initial configuration rather than loading an existing one.

## Local state and directories

The default runtime layout is:

```text
C:\ProgramData\FGOps\config.yml
C:\ProgramData\FGOps\fortios64-package-map.yml
C:\ProgramData\FGOps\incoming\
C:\ProgramData\FGOps\quarantine\
C:\ProgramData\FGOps\state\agent-state.json
C:\ProgramData\FGOps\secrets\secret-store.json
C:\ProgramData\FGOps\evidence\
C:\ProgramData\FGOps\evidence\backups\
C:\ProgramData\FGOps\reports\
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
C:\ProgramData\FGOps\tftp\
```

Archive identity is SHA-256. The agent detects new bytes even if a source reuses the same URL and filename. State records the archive path, manifest ID, work directory, planned package kinds, lifecycle status, apply report, backup path, last result, and last error.

Enabled payload identity is also SHA-256. If the ZIP bytes change but the enabled package payload exactly matches a previously applied payload, the result is `NO_CONTENT_CHANGE`; SSH, backup, TFTP, and restore remain skipped.

State writes are atomic. Do not delete or edit the state file to force reinstallation. A manual recovery reset should be rare, evidence-backed, scoped to one archive hash, and preceded by a backup of the state file.

## Configure secrets

Scheduled execution under `SYSTEM` cannot inherit secrets entered in an interactive PowerShell session. Store required values in the local DPAPI machine store:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  secret set FGOPS_SSH_PASSWORD

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  secret set FGOPS_BACKUP_PASSWORD

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  secret status
```

The CLI displays secret names and timestamps, never plaintext values. The secret store must have inherited ACLs removed and access limited to `SYSTEM` and local Administrators.

The operator journal records only that the secure secret-store operation completed. It does not intentionally include secret values.

## Validate preparation and management access

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  validate-config

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  run --dry-run

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  scan-host-key --host 192.0.2.1 --port 22

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  preflight

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  backup-test
```

Verify a scanned host key through an independent trusted path before storing it. `backup-test` validates the live SSH/TFTP/full-config backup path without issuing any package restore.

After each command:

1. read the operator journal and confirm the final result;
2. review any warning or failure row;
3. open the technical journal and evidence when detailed validation is required.

## Windows Firewall and TFTP

FortiOS restore commands use UDP/69. Bind FGOps to a dedicated management-facing VM address and permit inbound TFTP only from the FortiGate management source address.

```powershell
New-NetFirewallRule `
  -DisplayName "FGOps TFTP from FortiGate" `
  -Direction Inbound `
  -Action Allow `
  -Protocol UDP `
  -LocalPort 69 `
  -LocalAddress 192.0.2.10 `
  -RemoteAddress 192.0.2.1
```

Confirm UDP/69 is free before testing:

```powershell
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
```

FGOps starts the application endpoint only for an active backup/apply operation. The firewall rule is a network boundary and may be additionally constrained or enabled only during the maintenance window.

## Schedule the policy cycle

```powershell
& C:\FGOps\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6 `
  -TaskCommand cycle `
  -TaskName "FGOps Offline Update Monitor"
```

The task:

- runs as `SYSTEM`;
- prevents overlapping instances;
- starts missed runs when the VM becomes available;
- executes `cycle`, which obeys the configured policy;
- writes to both daily journals;
- does not make `prepare_only` or `approval` unattended merely by being registered.

Inspect it with:

```powershell
$Task = Get-ScheduledTask -TaskName "FGOps Offline Update Monitor"
$Task.Actions | Format-List Execute,Arguments
$Task.Triggers[0].Repetition | Format-List Interval,Duration,StopAtDurationEnd
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor"
```

Disable the task during troubleshooting, upgrades, or manual recovery:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Re-enable it only after the foreground operation finishes with `SUCCESS`, `SUCCESS_WITH_WARNING`, or a clean `NO_CHANGE` state:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

## Operator and technical journals

Operator journal:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
```

Technical journal:

```text
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

Follow the operator journal during normal monitoring:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log" -Wait
```

Open the technical journal for structured details:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log" -Wait
```

The default retention is 30 daily files for each log type. Optional machine settings are:

```powershell
[Environment]::SetEnvironmentVariable("FGOPS_LOG_RETENTION_DAYS", "30", "Machine")
[Environment]::SetEnvironmentVariable("FGOPS_LOG_LEVEL", "INFO", "Machine")
```

`FGOPS_LOG_LEVEL` controls the technical journal. The operator journal remains an INFO-level checklist.

See [Operator checklist logging](operator-checklist-logging.md) for status symbols and operator actions. See [Daily runtime logging](daily-runtime-logging.md) for technical event format, correlation, retention, and security guidance.

## Operational package profile

The recommended validated allowlist is:

```yaml
execution:
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
```

The validated live sequence completed as `SUCCESS_WITH_WARNING`: AV, IPS, APDB, and MCDB were already current; MMDB increased from `93.07607` to `93.07613`.

FFDB is intentionally excluded. Add it only after the exact FFDB package source, FortiGate model, and FortiOS branch have been validated. A TFTP `OK` line followed by `Failed to restore other objects file` and return code `49` is a failed activation, even if file transfer completed.

## Maintenance and retention

- Schedule unattended apply during an approved maintenance window.
- Monitor available disk space under `C:\ProgramData\FGOps`.
- Retain encrypted backups, apply reports, evidence, and both daily log types according to policy.
- Periodically test that backups are readable through an approved restore-validation process; do not test a restore on the production appliance merely to validate automation.
- Review changes to the source-page structure and package filenames after publisher changes.
- Rotate secrets and re-verify the pinned host key after authorized device replacement or key rotation.
- Treat an operator run without a final result as unresolved until process state, technical logs, and the FortiGate are checked.

## Related documentation

- [Production operations](operations.md)
- [Operator checklist logging](operator-checklist-logging.md)
- [Daily runtime logging](daily-runtime-logging.md)
- [Private repository synchronization](private-repository-sync.md)
- [Read-only preflight](read-only-preflight.md)
- [Backup test](backup-test.md)
- [Controlled apply](controlled-apply.md)
- [Source bundle ingestion](source-bundle-ingestion.md)
- [Payload-level deduplication](payload-deduplication.md)
