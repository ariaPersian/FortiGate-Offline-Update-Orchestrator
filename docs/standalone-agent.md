# Standalone Windows agent

FGOps v0.5.8 uses a local Windows agent as the primary deployment model for a single FortiGate management target. The authoritative production source is the private repository `ariaPersian/FortiGate-Offline-Update-Orchestrator-Private`. GitHub is not required during scheduled production execution.

The current deployment model also includes an on-demand operator health report at `scripts\health_report.py`.

## Runtime flow

```text
Scheduled Task running as SYSTEM
  -> fgops-agent cycle
  -> operator + technical journals
  -> source discovery and bounded download
  -> SHA-256 archive/payload identity
  -> safe extraction and package inventory
  -> immutable manifest
  -> policy gate
  -> DPAPI-protected secrets when required
  -> pinned SSH preflight
  -> temporary restricted TFTP
  -> encrypted full-config backup
  -> selected package restores and version checks
  -> postflight, report, state update, checklist summary, cleanup

Operator routine
  -> scripts\health_report.py
  -> checkout/runtime/Task/state/evidence/device health
  -> HEALTHY / WARNING / CRITICAL
  -> Operator values copied into the approved Word checklist
```

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

The documentation baseline remains `0.5.8`.

## Existing checkout and private remote

Before every production upgrade:

```powershell
Set-Location C:\FGOps
git remote -v
git status --short
git branch --show-current
```

The expected origin is:

```text
https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git
```

If the checkout still points to the former public repository, or private/public histories diverge, follow [Private repository synchronization](private-repository-sync.md). Do not merge unrelated histories simply to make `git pull` succeed.

The operator health report also checks the production origin as `HC-02`.

## Upgrade the installed agent

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

Confirm the private checkout contains:

```powershell
Test-Path "C:\FGOps\scripts\health_report.py"
```

Expected:

```text
True
```

The forced reinstall is important because a source-only pull can leave older installed modules or a generated `fgops-agent.exe` in the virtual environment.

Version 0.5.8 requires reviewed source-retry and mixed-generation bundle policy. Back up the production package map before replacing or merging repository changes. Keep `execution.reject_unknown_packages: true` and `execution.prevent_downgrade: true`.

## Maintenance validation while Task is disabled

Run:

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

Confirm both daily journals exist:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Item `
  "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log", `
  "C:\ProgramData\FGOps\logs\fgops-$Today.log"
```

Do not re-enable scheduling when state contains unresolved `APPLY_FAILED` or `REVIEW_REQUIRED`, when the dry run fails, or when a prepared manifest contains unexpected/ambiguous package policy results.

A deliberately disabled Scheduled Task is classified as unhealthy by the normal-state health report, so do not use `OverallHealth` as the pre-enable maintenance gate.

## Restore scheduling and run the health report

After maintenance validation is accepted:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Then run:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

The report produces:

```text
HEALTHY  exit 0
WARNING  exit 1
CRITICAL exit 2
```

It also prints `Operator values` for the Word checklist and writes TXT/JSON evidence under:

```text
C:\ProgramData\FGOps\reports\health
```

See [Operator health report](operator-health-report.md) for all checks and interpretation rules.

## Initialize runtime storage

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  init `
  --package-map-source C:\FGOps\config\fortios64-package-map.yml
```

Copy [`config/agent.example.yml`](../config/agent.example.yml) and replace all example addresses, target identity values, and host-key fingerprints. Production configuration must remain outside the repository.

## Local state and directories

Default runtime layout:

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
C:\ProgramData\FGOps\reports\health\
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
C:\ProgramData\FGOps\tftp\
```

Archive identity and enabled-payload identity use SHA-256. If ZIP bytes change while the enabled package payload exactly matches a previously applied payload, the result is `NO_CONTENT_CHANGE`; SSH, backup, TFTP, and restore remain skipped.

State writes are atomic. Do not delete or edit `agent-state.json` merely to force reinstallation or replay.

## Configure secrets

Scheduled execution under `SYSTEM` cannot depend on values entered only into an interactive PowerShell process. Store required values in the local DPAPI machine store:

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

The CLI and health report expose secret metadata only, never plaintext values.

## Validate preparation and management access

Before the first live restore or after material target/network/credential changes:

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

Verify a scanned host key through an independent trusted path before storing it.

`backup-test` validates the live SSH/TFTP/full-config backup path without issuing any package restore. The operator health report intentionally does not run `backup-test` because backup-test is a device interaction that starts temporary TFTP and requests an encrypted configuration export.

## Windows Firewall and TFTP

FortiOS restore/backup commands use UDP/69. Bind FGOps to a dedicated management-facing address and permit inbound TFTP only from the FortiGate management source.

Example:

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

Check the port before maintenance:

```powershell
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
```

The health report performs the same idle-port observation as `HC-17`; an unexpected listener produces a warning.

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
- obeys `execution.mode`;
- writes to both daily journals;
- keeps approval mode approval-controlled.

The health report checks Task state, last result, next run, executable, config path, and `cycle` action.

## Operator and technical evidence

Routine health command:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

Operator journal:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
```

Technical journal:

```text
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

The health report is the first routine monitoring view. The operator journal is the first per-run troubleshooting view. Open the technical journal and exact evidence when deeper investigation is required.

`FGOPS_LOG_RETENTION_DAYS` controls date-named daily logs only. Health reports under `reports\health` require a separate retention policy.

## Operational package profile

Recommended validated allowlist:

```yaml
execution:
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
```

The validated live sequence completed as `SUCCESS_WITH_WARNING`: AV, IPS, APDB, and MCDB were already current; MMDB increased from `93.07607` to `93.07613`.

FFDB is intentionally excluded by default. A TFTP `OK` line followed by `Failed to restore other objects file` and return code `49` is a failed activation when the expected object versions do not change.

## Maintenance and retention

- Schedule unattended apply only inside an approved maintenance window.
- Monitor disk space under `C:\ProgramData\FGOps`.
- Retain encrypted backups, apply reports, health reports, evidence, and both daily logs according to policy.
- Periodically validate backup recoverability through an approved process.
- Review source-page/package-name changes when the publisher changes format.
- Rotate secrets and re-verify the pinned host key after authorized replacement or key rotation.
- Treat an operator run without a final result as unresolved until process state, logs, state, TFTP, and the FortiGate are checked.

## Related documentation

- [Operator health report](operator-health-report.md)
- [Production operations](operations.md)
- [Operator checklist logging](operator-checklist-logging.md)
- [Daily runtime logging](daily-runtime-logging.md)
- [Private repository synchronization](private-repository-sync.md)
- [Read-only preflight](read-only-preflight.md)
- [Backup test](backup-test.md)
- [Controlled apply](controlled-apply.md)
- [Source bundle ingestion](source-bundle-ingestion.md)
- [Payload-level deduplication](payload-deduplication.md)
