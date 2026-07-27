# Production operations

This runbook covers routine operation of FGOps v0.5.5 on a Windows VM after installation and initial validation.

The authoritative source repository is:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private
```

Production upgrades must not be pulled from the former public repository.

## Normal operating model

```text
Scheduled Task every configured interval
  -> cycle
  -> daily runtime log append
  -> NO_CHANGE when the downloaded SHA-256 is already processed
  -> PREPARED when new archive bytes are discovered
  -> policy-controlled apply
  -> SUCCESS / SUCCESS_WITH_WARNING / FAILED
  -> state, report, evidence, and exit-code persistence
```

For the validated unattended profile, enable only:

```yaml
execution:
  mode: unattended
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
```

The validated live run completed as `SUCCESS_WITH_WARNING`: AV, IPS, APDB, and MCDB were already current; MMDB increased from `93.07607` to `93.07613`.

FFDB is not part of the recommended default. The tested package transferred but failed activation with return code `49` while both Internet-service database versions remained unchanged.

## Daily checks

Inspect the Scheduled Task:

```powershell
Get-ScheduledTask -TaskName "FGOps Offline Update Monitor" |
  Select-Object TaskName,State

Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor" |
  Format-List LastRunTime,LastTaskResult,NextRunTime
```

A successful Task Scheduler invocation normally reports:

```text
LastTaskResult : 0
```

Inspect agent state:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Inspect today's runtime log:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log"
```

Search recent logs for failed commands or failed cycle results:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-*.log" `
  -Pattern '"event": "command.failed"|"status": "FAILED"'
```

Review the latest reports:

```powershell
Get-ChildItem C:\ProgramData\FGOps\reports -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 10 FullName,Length,LastWriteTime
```

Review disk usage:

```powershell
Get-ChildItem C:\ProgramData\FGOps -Recurse -File |
  Measure-Object Length -Sum
```

## Weekly checks

- Confirm the checkout remote still points to the private repository.
- Confirm the installed package version matches the reviewed repository release.
- Review the previous seven daily log files for failures and repeated warnings.
- Confirm a recent encrypted backup exists and has a non-zero size.
- Confirm apply reports and FortiGate object versions agree.
- Confirm the Scheduled Task action still invokes `cycle` with the production configuration path.
- Review disk use under `incoming`, `quarantine`, `evidence`, `reports`, and `logs`.

```powershell
Set-Location C:\FGOps
git remote -v
& C:\FGOps\venv\Scripts\python.exe -m pip show fgops

(Get-ScheduledTask -TaskName "FGOps Offline Update Monitor").Actions |
  Format-List Execute,Arguments
```

## Expected cycle outcomes

### `NO_CHANGE`

The configured source was reachable and the downloaded archive SHA-256 was already known. No package restore is performed.

### `SUCCESS`

All applied packages produced the expected version increase and postflight passed.

### `SUCCESS_WITH_WARNING`

The cycle completed safely, but at least one package was already current or FortiOS produced a non-blocking warning while the expected version still increased. Review the per-package results, but this outcome does not imply a failed cycle.

### `FAILED`

At least one mandatory gate or package result failed. The remaining sequence may have stopped. Disable scheduling and investigate before any retry.

## Maintenance-window procedure

1. Confirm console or alternate management access is available.
2. Confirm the Windows VM and FortiGate management path are reachable.
3. Confirm UDP/69 is not used by another service.
4. Confirm the Scheduled Task is not already running.
5. Confirm recent encrypted backups and evidence are retained.
6. Review `execution.enabled_packages`.
7. Run the cycle in the foreground when testing a new package family or source.
8. Follow the daily log while the foreground cycle runs.

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

$Today = Get-Date -Format "yyyy-MM-dd"
Start-Job {
  param($Path)
  Get-Content $Path -Wait
} -ArgumentList "C:\ProgramData\FGOps\logs\fgops-$Today.log"

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  cycle
```

Re-enable scheduling only after reviewing the foreground result:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

## Verify a completed apply

Read the latest apply report:

```powershell
$Report = Get-ChildItem C:\ProgramData\FGOps\reports `
  -Filter "*-apply.json" -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Get-Content $Report.FullName -Raw | ConvertFrom-Json
```

On the FortiGate, compare with:

```text
diagnose autoupdate versions
diagnose autoupdate signature check-all
```

The report should agree with the target's current FortiGuard object versions. A changed `Last Updated` timestamp without a version change and with an explicit restore failure is not sufficient evidence of activation.

## Upgrade FGOps from the private repository

Disable the Scheduled Task during upgrade:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

Set-Location C:\FGOps
git remote -v
git status
```

The remote must point to:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git
```

For an already-correct private checkout:

```powershell
git fetch --prune origin
git switch main
git pull --ff-only

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --no-user C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

If fetch reports a forced update or pull reports diverging branches, do not merge or rebase the former public history into production. Follow [Private repository synchronization](private-repository-sync.md), which preserves a safety branch and stash before aligning local `main` to private `origin/main`.

Run a foreground `status`, clean `NO_CHANGE`, `preflight`, or `backup-test` as appropriate, then inspect the daily log before re-enabling the Task.

## Rotate secrets

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

After SSH credential or host-key rotation, run `scan-host-key`, independently verify the new fingerprint, update configuration, and run `preflight` before restoring scheduled operation.

## Failure-response procedure

1. Disable the Scheduled Task.
2. Do not run `cycle` again immediately.
3. Preserve:
   - the failed apply JSON/TXT report;
   - the relevant daily runtime log;
   - preflight and postflight evidence;
   - the encrypted full-config backup;
   - `agent-state.json`;
   - the relevant quarantine directory;
   - the failed per-run TFTP directory if retained;
   - FortiGate CLI/debug output.
4. Determine the last package result and compare before/after versions on the FortiGate.
5. Distinguish transfer from activation. `Get ... from tftp server OK.` proves transfer, not successful database activation.
6. Correct the package allowlist, source compatibility, target configuration, or code before retrying.
7. Perform the retry in the foreground.
8. Re-enable scheduling only after a successful reviewed result.

## State recovery

FGOps intentionally does not replay `APPLY_FAILED` archives automatically. Do not delete the state file or archive entry merely to force a retry.

When an exceptional recovery reset is justified:

- back up `agent-state.json` first;
- target one exact archive SHA-256 and manifest ID;
- verify the current FortiGate versions before reset;
- record the root cause and recovery reason;
- change only the intended archive from `APPLY_FAILED` to `PREPARED`;
- run the recovery cycle in the foreground;
- preserve both the original and recovered reports and daily logs.

A state reset authorizes another attempt; it does not prove that repeating a package is safe.

## FFDB troubleshooting

The recommended production profile excludes FFDB unless independently validated.

If FFDB is enabled and FortiOS returns code `49`:

```text
Get other objects from tftp server OK.
Failed to restore other objects file.
Command fail. Return code 49
```

then:

1. keep scheduling disabled;
2. do not submit a second FFDB package while FortiOS may still be parsing;
3. inspect `Internet-service Database Apps` and `Internet-service Full Database Maps`;
4. allow the bounded polling window to complete;
5. treat unchanged versions as failure, not as `SKIPPED_NO_UPDATE`;
6. remove FFDB from `execution.enabled_packages` when compatibility cannot be established.

The package may remain visible in `planned_packages` because the manifest inventories the ZIP. It is not restored unless it is also present in `execution.enabled_packages`.

## Retention and cleanup

The default daily-log retention is 30 date-named files. Configure a machine-wide value when organizational policy requires a different period:

```powershell
[Environment]::SetEnvironmentVariable(
  "FGOPS_LOG_RETENTION_DAYS",
  "30",
  "Machine"
)
```

Define an organizational retention policy for:

- incoming archives;
- quarantine manifests and package copies;
- encrypted backups;
- preflight/postflight evidence;
- apply reports;
- daily runtime logs;
- state backups made during recovery;
- manually captured FortiGate debug output.

Never delete the only known-good encrypted configuration backup during routine cleanup. Verify that the backup password is retained through an approved secret-recovery process separate from the backup file.
