# Production operations

This runbook covers routine operation of FGOps v0.5.4 on a Windows VM after installation and initial validation.

## Normal operating model

```text
Scheduled Task every configured interval
  -> cycle
  -> NO_CHANGE when the downloaded SHA-256 is already processed
  -> PREPARED when new archive bytes are discovered
  -> policy-controlled apply
  -> SUCCESS / SUCCESS_WITH_WARNING / FAILED
```

For the validated unattended profile, enable only:

```yaml
execution:
  mode: unattended
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
```

FFDB is not part of the recommended default. Enable it only after the exact package source, FortiGate model, and FortiOS branch have been validated.

## Daily and weekly checks

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

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

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

## Upgrade FGOps

Disable the Scheduled Task during upgrade:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

Set-Location C:\FGOps
git status
git pull --ff-only

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --no-user C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

Run a foreground `NO_CHANGE`, `preflight`, or `backup-test` as appropriate before re-enabling the Task.

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
- preserve both the original and recovered reports.

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
4. allow the bounded v0.5.4 polling window to complete;
5. treat unchanged versions as failure, not as `SKIPPED_NO_UPDATE`;
6. remove FFDB from `execution.enabled_packages` if compatibility cannot be established.

The package may remain visible in `planned_packages` because the manifest inventories the ZIP. It is not restored unless it is also present in `execution.enabled_packages`.

## Retention and cleanup

Define an organizational retention policy for:

- incoming archives;
- quarantine manifests and package copies;
- encrypted backups;
- preflight/postflight evidence;
- apply reports;
- state backups made during recovery;
- logs generated during troubleshooting.

Never delete the only known-good encrypted configuration backup during routine cleanup. Verify that the backup password is retained through an approved secret-recovery process separate from the backup file.
