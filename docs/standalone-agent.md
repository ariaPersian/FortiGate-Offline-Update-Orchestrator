# Standalone Windows agent

FGOps v0.5.4 uses a local Windows agent as the primary deployment model for a single FortiGate management target. GitHub remains the source-code and CI system; it is not required during scheduled production execution.

## Runtime flow

```text
Scheduled Task running as SYSTEM
  -> fgops-agent cycle
  -> poll configured source page
  -> discover the matching bundle link
  -> bounded atomic ZIP download
  -> SHA-256 duplicate detection
  -> safe extraction and package inventory
  -> immutable local manifest
  -> apply execution policy
  -> load DPAPI-protected secrets when required
  -> pinned SSH preflight
  -> temporary restricted TFTP
  -> encrypted full-config backup
  -> selected package restores and version checks
  -> postflight, report, state update, cleanup
```

The source parser can match the anchor text, URL, and surrounding list-item context. This supports pages where the product/version label is outside a generic download anchor.

## Install or upgrade

From an elevated PowerShell session:

```powershell
Set-Location C:\FGOps

py -3.13 -m venv C:\FGOps\venv
& C:\FGOps\venv\Scripts\python.exe -m pip install --upgrade pip
& C:\FGOps\venv\Scripts\python.exe -m pip install --no-user C:\FGOps
```

To upgrade an existing checkout:

```powershell
Set-Location C:\FGOps
git pull --ff-only

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --no-user C:\FGOps
```

Confirm the installed version:

```powershell
& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

## Initialize runtime storage

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  init `
  --package-map-source C:\FGOps\config\fortios64-package-map.yml
```

Copy [`config/agent.example.yml`](../config/agent.example.yml) and replace all example addresses, target identity values, and host-key fingerprints. Production configuration must remain outside the repository.

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
C:\ProgramData\FGOps\tftp\
```

Archive identity is SHA-256. The agent therefore detects new bytes even if a source reuses the same URL and filename. State records the archive path, manifest ID, work directory, planned package kinds, lifecycle status, apply report, backup path, last result, and last error.

State writes are atomic. Do not delete or edit the state file to force reinstallation. A manual recovery reset should be rare, evidence-backed, scoped to one archive hash, and preceded by a backup of the state file.

## Configure secrets

Scheduled execution under `SYSTEM` cannot inherit secrets entered in an interactive PowerShell session. Store the required values in the local DPAPI machine store:

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
- does not make `prepare_only` or `approval` unattended merely by being registered.

Inspect it with:

```powershell
$Task = Get-ScheduledTask -TaskName "FGOps Offline Update Monitor"
$Task.Actions | Format-List Execute,Arguments
$Task.Triggers[0].Repetition | Format-List Interval,Duration,StopAtDurationEnd
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor"
```

Disable the task during troubleshooting or before any manual recovery operation:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Re-enable it only after the foreground cycle finishes with `SUCCESS`, `SUCCESS_WITH_WARNING`, or a clean `NO_CHANGE` state:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

## Operational package profile

The recommended validated allowlist is:

```yaml
execution:
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
```

FFDB is intentionally opt-in. Add it only after the exact FFDB package source, FortiGate model, and FortiOS branch have been validated. A TFTP `OK` line followed by `Failed to restore other objects file` and return code `49` is a failed activation, even if the file transfer completed.

## Maintenance and retention

- Schedule unattended apply during an approved maintenance window.
- Monitor available disk space under `C:\ProgramData\FGOps`.
- Retain encrypted backups and apply reports according to policy.
- Periodically test that backups are readable through an approved restore-validation process; do not test a restore on the production appliance merely to validate automation.
- Review changes to the source-page structure and package filenames after publisher changes.
- Rotate secrets and re-verify the pinned host key after authorized device replacement or key rotation.
