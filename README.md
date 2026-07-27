# FGOps

**FortiGate Offline Update Orchestrator** is a Windows-based agent for discovering, preparing, backing up, applying, and auditing offline FortiGuard signature updates on FortiGate appliances that cannot retrieve updates directly from FortiGuard.

> Current milestone: `v0.5.4`. The validated deployment is a standalone Windows VM managing a FortiGate 300D running FortiOS 6.4.16 in multiple-VDOM mode. The architecture is configurable, but other models, FortiOS branches, package publishers, and database families must be validated independently before unattended use.

## What FGOps does

```text
Windows Scheduled Task (SYSTEM)
  -> poll a configured download page
  -> resolve the selected FortiGate bundle link
  -> download with TLS, size, and timeout limits
  -> identify the archive by SHA-256
  -> safely extract and inventory package files
  -> generate an immutable local manifest
  -> obey prepare_only / approval / unattended policy
  -> load encrypted local secrets when device access is required
  -> verify the pinned SSH host key and expected FortiGate identity
  -> start a temporary restricted TFTP endpoint
  -> receive an encrypted full-configuration backup
  -> apply only explicitly enabled package families
  -> compare FortiGuard object versions before and after each restore
  -> run postflight checks and write JSON/TXT evidence
  -> stop TFTP and persist the archive result
```

GitHub is the development and review system. It is not required in the production runtime path, and no self-hosted GitHub runner is required.

## Validated operational profile

| Area | Validated value |
|---|---|
| Runtime host | Windows VM, Python 3.13, Scheduled Task running as `SYSTEM` |
| Appliance | FortiGate 300D |
| FortiOS | 6.4.16 build 2098 |
| VDOM mode | Multiple VDOM, global-context execution |
| Validated package set | AV, IPS, APDB, MCDB, MMDB |
| Optional package | FFDB, only after target-specific validation |
| Out of scope | Firmware upgrade/downgrade, signature bypass, security-level reduction, Botnet automation |

The tested FortiGate rejected the third-party FFDB file with FortiOS return code `49` while its Internet-service database versions remained unchanged. FFDB is therefore not part of the recommended default allowlist. FGOps can poll FFDB versions for up to 30 minutes after code `49`, but it still fails closed unless a version change is observed.

## Core capabilities

- configurable source-page monitoring and link matching;
- native/system TLS validation, bounded downloads, and atomic file replacement;
- SHA-256 archive deduplication even when a publisher reuses the same URL;
- safe ZIP extraction and package-kind inventory;
- local manifest and state persistence outside the repository;
- SSH host-key pinning and expected device identity checks;
- encrypted full-config backup before every controlled apply;
- temporary TFTP server bound to a specified management address;
- package allowlist, deterministic order, stop-on-failure, and downgrade protection;
- before/after version verification instead of trusting transfer success alone;
- Windows DPAPI machine-scoped secret storage with restrictive NTFS ACLs;
- `prepare_only`, exact-manifest `approval`, and `unattended` policies;
- JSON/TXT preflight, backup, apply, and command-output evidence;
- optional Telegram notifications.

## Install on a Windows VM

```powershell
Set-Location C:\FGOps

py -3.13 -m venv C:\FGOps\venv
& C:\FGOps\venv\Scripts\python.exe -m pip install --upgrade pip
& C:\FGOps\venv\Scripts\python.exe -m pip install --no-user C:\FGOps

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  init `
  --package-map-source C:\FGOps\config\fortios64-package-map.yml
```

Copy and adapt [`config/agent.example.yml`](config/agent.example.yml). Keep production addresses, fingerprints, credentials, evidence, backups, and package files outside Git.

## Minimum configuration model

```yaml
execution:
  # Use approval for the first reviewed live run. Change to unattended only after
  # backup, restore, version comparison, and postflight evidence are accepted.
  mode: approval
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
  reject_unknown_packages: true
  prevent_downgrade: true

apply:
  tftp_bind_address: 192.0.2.10
  tftp_advertise_address: 192.0.2.10
  tftp_port: 69
  require_backup: true
  backup_password_env: FGOPS_BACKUP_PASSWORD
  settle_seconds: 5
  stop_on_failure: true
  package_order: [AV, IPS, APDB, MCDB, MMDB]
```

Package presence in the downloaded ZIP does not make it eligible for installation. `execution.enabled_packages` is the authoritative apply allowlist; `apply.package_order` only orders packages that already passed that filter.

## Prepare and validate the path

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

`backup-test` starts the same temporary TFTP path used by controlled apply, exports one encrypted full configuration, verifies its permanent SHA-256 copy, writes evidence, and performs no package restore.

## Windows machine secret store

Scheduled execution cannot depend on a PowerShell process environment. FGOps stores DPAPI-encrypted ciphertext in:

```text
C:\ProgramData\FGOps\secrets\secret-store.json
```

The store uses DPAPI `LocalMachine` scope and removes inherited ACLs, granting access only to `SYSTEM` and local Administrators. Machine scope is not an authorization boundary by itself; the NTFS ACL is mandatory.

Create the required secrets from an elevated shell:

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

Optional notification tokens use the same store. Secret values are never printed by the CLI and must never be committed.

## Execution policies

### `prepare_only`

Downloads, deduplicates, extracts, inventories, and records the bundle. No device-changing path is entered.

### `approval`

Prepares the bundle and waits for the exact local manifest ID:

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  approve --manifest-id FGOPS-0123456789ABCDEF
```

### `unattended`

A new or previously prepared eligible manifest runs through the same preflight, mandatory backup, hash verification, allowlist, version checks, postflight, and audit gates without interactive operator approval. Failed or review-required archives are not replayed automatically.

## Result classification

| Evidence | Result |
|---|---|
| Expected object version increased | `SUCCESS` |
| Version increased despite a FortiOS warning/non-zero code | `SUCCESS_WITH_WARNING` |
| FortiGate explicitly completed transfer and versions were already current | `SKIPPED_NO_UPDATE` |
| Expected object missing or unchanged without a trusted successful-transfer outcome | `FAILED_UNCONFIRMED` |
| Version decreased, package validation failed, backup failed, or target identity changed | `FAILED` |

A successful TFTP transfer proves delivery only. FGOps requires the corresponding FortiGuard object state to support the final classification.

## Schedule the policy cycle

```powershell
.\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6 `
  -TaskCommand cycle `
  -TaskName "FGOps Offline Update Monitor"
```

The task runs as `SYSTEM`, prevents overlapping runs, and obeys `execution.mode`. Schedule live unattended application for a maintenance window appropriate to the managed environment.

## Runtime data

```text
C:\ProgramData\FGOps\incoming\                 downloaded archives
C:\ProgramData\FGOps\quarantine\              extracted packages and manifests
C:\ProgramData\FGOps\state\agent-state.json   archive lifecycle state
C:\ProgramData\FGOps\secrets\                 encrypted local secrets
C:\ProgramData\FGOps\evidence\                preflight and backup evidence
C:\ProgramData\FGOps\evidence\backups\        encrypted full-config backups
C:\ProgramData\FGOps\reports\                 apply reports
C:\ProgramData\FGOps\tftp\                    per-run temporary TFTP roots
```

## Commands

```text
fgops-agent init
fgops-agent validate-config
fgops-agent run [--dry-run]
fgops-agent cycle
fgops-agent scan-host-key
fgops-agent preflight
fgops-agent backup-test
fgops-agent secret set|delete|status
fgops-agent notify-test
fgops-agent approve --manifest-id ...
fgops-agent apply --manifest-id ... [--approve-manifest ...]
fgops-agent status
```

## Documentation

- [Architecture and trust boundaries](docs/architecture.md)
- [Standalone Windows deployment](docs/standalone-agent.md)
- [Read-only FortiGate preflight](docs/read-only-preflight.md)
- [Backup-only validation](docs/backup-test.md)
- [Controlled apply runbook](docs/controlled-apply.md)
- [Production operations](docs/operations.md)
- [Security policy](SECURITY.md)

## Disclaimer

FGOps is independent and is not affiliated with or endorsed by Fortinet or any package publisher. A discovered or successfully downloaded package is not automatically trusted or compatible. Use only packages you are authorized to obtain and validate each package family against the exact target model and FortiOS branch before unattended deployment.
