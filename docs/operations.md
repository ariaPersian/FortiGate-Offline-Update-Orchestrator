# Production operations

This runbook covers routine operation of FGOps v0.5.6 on a Windows VM after installation and initial validation.

The authoritative source repository is:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private
```

Production upgrades must not be pulled from the former public repository.

## Normal operating model

```text
Scheduled Task every configured interval
  -> fgops-agent cycle
  -> operator ToDo checklist and technical JSON journal append
  -> NO_CHANGE when the downloaded SHA-256 is already processed
  -> PREPARED when new archive bytes are discovered
  -> approval wait or policy-controlled apply
  -> mandatory preflight and encrypted backup when apply runs
  -> package-level restore and version verification
  -> SUCCESS / SUCCESS_WITH_WARNING / FAILED
  -> operator final status, exit code, suggested action
  -> state, report, evidence, and technical event persistence
```

For the validated unattended profile, enable only:

```yaml
execution:
  mode: unattended
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
```

The validated live run completed as `SUCCESS_WITH_WARNING`: AV, IPS, APDB, and MCDB were already current; MMDB increased from `93.07607` to `93.07613`.

FFDB is not part of the recommended default. The tested package transferred but failed activation with return code `49` while both Internet-service database versions remained unchanged.

## Logging model

Every installed `fgops-agent` command writes two daily files:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

The operator journal is the primary monitoring view. It shows the planned ToDo list and marks each step with:

```text
⬜ planned
🔄 running
✅ success
⚠️ warning or attention required
❌ failed
⏭️ safely skipped
```

The technical journal remains the source for structured result payloads, exceptions, and tracebacks.

Operational sequence:

1. Check Task Scheduler status.
2. Read the latest final result in the operator journal.
3. Review any `⚠️` or `❌` rows within the same run identifier.
4. Follow the suggested operator action.
5. Open the technical journal and evidence only when deeper investigation is required.

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

Inspect today's operator journal:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"
Get-Content $OperatorLog -Tail 150
```

Display only final results and suggested actions:

```powershell
Select-String `
  -Path $OperatorLog `
  -Pattern "نتیجه نهایی:|اقدام پیشنهادی اپراتور:"
```

Display warnings and failures:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "⚠️|❌"
```

Inspect agent state:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Inspect the technical journal when required:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log" -Tail 200
```

Search technical logs for failed commands or failed cycle results:

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
- Confirm the installed package version is `0.5.6` or the currently reviewed release.
- Review the previous seven operator journals for repeated warnings or failures.
- Confirm every scheduled run has a final operator result; investigate incomplete `🔄` runs.
- Review the related technical logs for repeated exceptions or notification failures.
- Confirm a recent encrypted backup exists and has a non-zero size.
- Confirm apply reports and FortiGate object versions agree.
- Confirm the Scheduled Task action still invokes `cycle` with the production configuration path.
- Review disk use under `incoming`, `quarantine`, `evidence`, `reports`, `logs`, and `tftp`.

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

Operator view:

- source check: `✅`;
- prepare/apply-only steps: `⏭️`;
- final result: `✅ NO_CHANGE`;
- suggested action: no action required.

### `PREPARED`

A new archive was discovered and prepared. In `approval` mode it waits for explicit manifest approval. This is an expected controlled state.

Operator view:

- preparation: `✅`;
- execution gate: `⚠️` waiting for approval;
- device-changing steps: `⏭️`;
- final result: `⚠️ PREPARED` with approval guidance.

### `SUCCESS`

All applied packages produced the expected version increase and postflight passed.

Operator view: final `✅`, with successful backup, package, verification, and report rows.

### `SUCCESS_WITH_WARNING`

The cycle completed safely, but at least one package was already current or FortiOS produced a non-blocking warning while the expected version still increased.

Operator view: final `⚠️`; review each warning package row and the apply report. This outcome does not imply a failed cycle.

### `SUCCESS_WITH_NOTIFICATION_ERROR` or `PREPARED_WITH_NOTIFICATION_ERROR`

The principal workflow completed or prepared successfully, but Telegram delivery failed.

Operator view: final `⚠️`; check notification configuration without repeating an already-completed apply.

### `FAILED`

At least one mandatory gate, backup operation, package result, or postflight check failed. The remaining sequence may have stopped.

Operator view: final `❌`; disable scheduling and investigate before any retry.

## Maintenance-window procedure

1. Confirm console or alternate management access is available.
2. Confirm the Windows VM and FortiGate management path are reachable.
3. Confirm UDP/69 is not used by another service.
4. Confirm the Scheduled Task is not already running.
5. Confirm recent encrypted backups and evidence are retained.
6. Review `execution.enabled_packages` and execution mode.
7. Disable scheduling for foreground testing.
8. Follow the operator journal while the cycle runs.
9. Open the technical journal in a second window only when needed.

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"

Start-Job {
  param($Path)
  while (-not (Test-Path $Path)) { Start-Sleep -Seconds 1 }
  Get-Content $Path -Wait
} -ArgumentList $OperatorLog

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  cycle
```

Re-enable scheduling only after reviewing the foreground result:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Do not re-enable after `FAILED`, an incomplete run, or an unresolved warning that affects safety.

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

The operator package row is a summary. The apply report and before/after version evidence remain authoritative.

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
  -m pip install --upgrade --force-reinstall --no-deps C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

The forced local reinstall is important for v0.5.6 because the installed `fgops-agent` console entry point now starts the operator checklist wrapper.

Validate the entry point:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status

$Today = Get-Date -Format "yyyy-MM-dd"
Get-Item `
  "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log", `
  "C:\ProgramData\FGOps\logs\fgops-$Today.log"
```

If the operator file is missing while the technical file exists, do not re-enable scheduling until the package has been reinstalled and the wrapper is confirmed.

If fetch reports a forced update or pull reports diverging branches, do not merge or rebase the former public history into production. Follow [Private repository synchronization](private-repository-sync.md), which preserves a safety branch and stash before aligning local `main` to private `origin/main`.

## Rotate secrets

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

After SSH credential or host-key rotation, run `scan-host-key`, independently verify the new fingerprint, update configuration, and run `preflight` before restoring scheduled operation.

The operator journal confirms that the secret operation completed without displaying the secret value.

## Failure-response procedure

1. Disable the Scheduled Task.
2. Do not run `cycle`, `approve`, or `apply` again immediately.
3. Preserve the failed operator run identifier and every `❌` row.
4. Preserve:
   - the operator daily journal;
   - the technical daily journal;
   - the failed apply JSON/TXT report;
   - preflight and postflight evidence;
   - the encrypted full-config backup;
   - `agent-state.json`;
   - the relevant quarantine directory;
   - the failed per-run TFTP directory if retained;
   - FortiGate CLI/debug output.
5. Determine the first failed checklist step and the last package result.
6. Compare before/after versions on the FortiGate.
7. Distinguish transfer from activation. `Get ... from tftp server OK.` proves transfer, not successful database activation.
8. Correct the package allowlist, source compatibility, target configuration, credentials, network path, or code before retrying.
9. Perform the retry in the foreground.
10. Re-enable scheduling only after a successful reviewed result.

## Incomplete operator run

A run may end without `نتیجه نهایی:` if the process is terminated externally, the VM reboots, or the process is killed before normal cleanup.

When the last row remains `🔄`:

1. check whether the Scheduled Task or process is still active;
2. do not start an overlapping run;
3. inspect the technical journal for `command.failed` or abrupt termination timing;
4. inspect Windows Event Viewer and Task Scheduler history;
5. confirm temporary TFTP is not still listening;
6. treat the run as unresolved until the state and FortiGate are checked.

```powershell
Get-Process -Name "fgops-agent","python" -ErrorAction SilentlyContinue
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor"
```

## State recovery

FGOps intentionally does not replay `APPLY_FAILED` archives automatically. Do not delete the state file or archive entry merely to force a retry.

When an exceptional recovery reset is justified:

- back up `agent-state.json` first;
- target one exact archive SHA-256 and manifest ID;
- verify the current FortiGate versions before reset;
- record the root cause and recovery reason;
- change only the intended archive from `APPLY_FAILED` to `PREPARED`;
- run the recovery cycle in the foreground;
- preserve both the original and recovered reports and both daily log types.

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

The default retention is 30 date-named files for each log type. Configure a machine-wide value when organizational policy requires a different period:

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
- operator daily journals;
- technical daily journals;
- state backups made during recovery;
- manually captured FortiGate debug output.

Never delete the only known-good encrypted configuration backup during routine cleanup. Verify that the backup password is retained through an approved secret-recovery process separate from the backup file.

## Related documentation

- [Operator checklist logging](operator-checklist-logging.md)
- [Daily runtime logging](daily-runtime-logging.md)
- [Standalone Windows agent](standalone-agent.md)
- [Controlled apply](controlled-apply.md)
- [Backup test](backup-test.md)
- [Private repository synchronization](private-repository-sync.md)
