# FGOps — FortiGate Offline Update Orchestrator

[![CI](https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private/actions/workflows/ci.yml/badge.svg)](https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**FGOps** is a policy-driven Windows agent for discovering, preparing, backing up, applying, logging, and auditing offline FortiGuard signature updates on FortiGate appliances that cannot retrieve updates directly from FortiGuard.

> **Current release:** `v0.5.6`  
> **Authoritative repository:** `ariaPersian/FortiGate-Offline-Update-Orchestrator-Private`  
> **Maturity:** pre-1.0 operational tooling with a validated reference deployment, not a universal compatibility claim.

The former public repository is not the production source of truth. Existing checkouts that still point to it must follow the [private repository synchronization guide](docs/private-repository-sync.md) before upgrading.

FGOps does **not** distribute FortiGuard packages, firmware, licenses, or credentials. Operators are responsible for obtaining authorized packages, complying with applicable vendor terms, and validating every package family against the exact FortiGate model and FortiOS build before unattended use.

## Why FGOps exists

Offline or restricted FortiGate environments require more than copying a package to a TFTP server. A controlled update workflow must establish content identity, validate the target appliance, preserve a recoverable configuration backup, apply only approved package families, verify the resulting FortiGuard object versions, retain auditable evidence, and provide logs that can be reviewed by both operations staff and technical support.

FGOps implements that workflow as a standalone Windows agent. GitHub is used for private source control, review, and CI; it is not required in the production runtime path.

## End-to-end workflow

```text
Windows Scheduled Task (SYSTEM)
  -> start technical and operator daily journals
  -> write the operator ToDo checklist for this run
  -> poll the configured source page
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
  -> mark every operator checklist step as success, warning, failure, or skipped
  -> persist the final status, exit code, suggested action, state, and reports
  -> stop TFTP and retain the required evidence
```

## Operator-friendly monitoring

Every installed `fgops-agent` command now produces two complementary daily log files:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

| File | Intended reader | Content |
|---|---|---|
| `fgops-operator-YYYY-MM-DD.log` | Non-technical operator | ToDo list, readable step results, final status, exit code, and suggested action |
| `fgops-YYYY-MM-DD.log` | Technical support | Structured JSON events, complete result payloads, exceptions, and tracebacks |

The operator journal uses fixed status symbols:

| Symbol | Meaning |
|---|---|
| `⬜` | Planned and not yet completed |
| `🔄` | In progress |
| `✅` | Completed successfully |
| `⚠️` | Completed with a warning or requires attention |
| `❌` | Failed |
| `⏭️` | Safely skipped because the step was not required |

Each run has a unique run identifier. Controlled apply results also add one checklist row per FortiGuard package, so the operator can see which package succeeded, was already current, produced a warning, or failed.

Follow the operator journal:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log" -Wait
```

Show warnings and failures only:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "⚠️|❌"
```

See [Operator checklist logging](docs/operator-checklist-logging.md) for the operator procedure and [Daily runtime logging](docs/daily-runtime-logging.md) for the technical event format.

## Validated reference profile

| Area | Validated value |
|---|---|
| Runtime host | Windows VM, Python 3.13, Scheduled Task running as `SYSTEM` |
| Appliance | FortiGate 300D |
| FortiOS | 6.4.16 build 2098 |
| VDOM mode | Multiple VDOM, global-context execution |
| Validated package set | AV, IPS, APDB, MCDB, MMDB |
| Excluded by default | FFDB after repeated return code `49` with unchanged ISDB versions |
| Validated live outcome | AV/IPS/APDB/MCDB already current; MMDB increased from `93.07607` to `93.07613`; overall `SUCCESS_WITH_WARNING` |
| Out of scope | Firmware upgrade/downgrade, signature bypass, security-level reduction, Botnet automation |

The tested third-party FFDB file transferred to FortiOS but failed activation with return code `49`; `Internet-service Database Apps` and `Internet-service Full Database Maps` remained unchanged. FFDB is therefore excluded from the recommended default allowlist. FGOps retains bounded FFDB polling support for controlled diagnostics, but it fails closed unless the expected version changes.

Other FortiGate models, FortiOS branches, package publishers, database families, authentication methods, and network topologies require independent validation. Do not interpret the reference profile as a vendor certification.

## Core capabilities

- Configurable source-page monitoring and link matching.
- Native/system TLS validation, bounded downloads, and atomic file replacement.
- SHA-256 archive deduplication even when a publisher reuses the same URL.
- Safe ZIP extraction and package-kind inventory.
- Immutable local manifests and atomic lifecycle state.
- SSH host-key pinning and expected target identity checks.
- Encrypted `full-config` backup before every controlled apply.
- Temporary TFTP server bound to a specified management interface.
- Explicit package allowlist, deterministic order, stop-on-failure, and downgrade protection.
- Before/after object-version verification instead of trusting transfer success alone.
- Windows DPAPI `LocalMachine` secret storage with restrictive NTFS ACLs.
- `prepare_only`, exact-manifest `approval`, and `unattended` execution policies.
- JSON/TXT evidence for preflight, backup, apply, and command output.
- Separate technical and operator UTF-8 daily journals.
- Per-run ToDo checklist, package-level result rows, final status, and operator guidance.
- Configurable daily-log retention and technical log level.
- Optional Telegram notifications with tokens kept out of YAML.

## Safety model

FGOps is designed to fail closed. A controlled apply is blocked when any mandatory gate fails, including:

- changed or unverified SSH host key;
- hostname, model, firmware branch, or build mismatch;
- unknown or disabled package family;
- package or archive SHA-256 mismatch;
- missing or empty encrypted backup;
- downgrade detection;
- invalid-signature or wrong-firmware responses;
- missing expected FortiGuard object after restore;
- unconfirmed package outcome;
- failed postflight validation.

A successful TFTP transfer proves delivery only. FGOps requires object-version evidence to classify package activation. Both logging layers are observational and must never weaken package selection, target validation, backup, or result-classification gates.

## Requirements

- Windows 10/11 or Windows Server suitable for a dedicated management VM.
- Python `3.11` or newer.
- Access to the authoritative private repository for installation and upgrades.
- Network reachability from the FGOps VM to the FortiGate management interface.
- SSH access with permissions appropriate to the selected operation.
- UDP/69 reachability from the FortiGate to the temporary FGOps TFTP endpoint.
- Independently verified FortiGate SSH host-key fingerprint.
- Authorized offline signature packages compatible with the target system.

## Repository checkout and upgrades

Clone the private repository for a new installation:

```powershell
git clone `
  https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git `
  C:\FGOps
```

Verify an existing checkout before pulling:

```powershell
Set-Location C:\FGOps
git remote -v
git status
```

Both fetch and push URLs must point to the private repository. A checkout that reports a forced update, branch divergence, or a remote URL for the former public repository must follow [`docs/private-repository-sync.md`](docs/private-repository-sync.md). Do not merge unrelated public/private histories into the production checkout merely to make `git pull` succeed.

## Installation

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

Copy and adapt [`config/agent.example.yml`](config/agent.example.yml). Keep production addresses, fingerprints, credentials, evidence, backups, downloaded archives, logs, and package files outside Git.

Confirm the installed version:

```powershell
& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

The expected version for this documentation is `0.5.6`.

### Upgrade from v0.5.5

The `fgops-agent` console entry point changed in v0.5.6 so the operator journal can wrap every command. Pulling the source alone is not sufficient; reinstall the package into the existing virtual environment:

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

Validate the new entry point with a harmless command before re-enabling the task:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status

$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log" -Tail 50
```

## Minimum configuration model

The following addresses are documentation-only examples from the TEST-NET ranges and must be replaced locally.

```yaml
execution:
  # Keep the first reviewed live operation in approval mode. Enable unattended
  # only after backup, restore, version comparison, and postflight evidence pass.
  mode: approval
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
  reject_unknown_packages: true
  prevent_downgrade: true

device:
  host: 192.0.2.1
  port: 22
  username: fgops-operator
  host_key_sha256: SHA256:REPLACE_WITH_INDEPENDENTLY_VERIFIED_FINGERPRINT
  password_env: FGOPS_SSH_PASSWORD
  expected_hostname: REPLACE_WITH_EXPECTED_HOSTNAME
  expected_model: REPLACE_WITH_EXPECTED_MODEL
  expected_firmware_branch: "6.4"
  expected_build: 2098
  global_context: true

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

Package presence in a downloaded archive does not make it eligible for installation. `execution.enabled_packages` is the authoritative apply allowlist; `apply.package_order` only orders packages that already passed that filter. FFDB may remain visible in a manifest inventory while being excluded from the actual apply sequence.

## Validate before the first live restore

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

`scan-host-key` reports the key presented by the network endpoint; it does not prove identity by itself. Verify the fingerprint through a separate trusted administrative path before saving it in configuration.

`backup-test` exercises the same pinned SSH and temporary TFTP path used by controlled apply, exports one encrypted full configuration, verifies the permanent SHA-256 copy, writes evidence, and performs no package restore.

After every validation command, inspect the operator journal first. Open the technical journal only when a checklist row contains `⚠️` or `❌`, or when detailed evidence is required.

## Windows machine secret store

Scheduled execution must not depend on a PowerShell process environment that disappears after the interactive session. FGOps stores DPAPI-encrypted ciphertext in:

```text
C:\ProgramData\FGOps\secrets\secret-store.json
```

The store uses DPAPI `LocalMachine` scope and removes inherited ACLs, granting access only to `SYSTEM` and local Administrators. Machine scope is not an authorization boundary by itself; the restrictive NTFS ACL is mandatory.

Create secrets from an elevated shell:

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

Optional notification tokens use the same store. Secret values are never printed by the CLI and must never be committed.

## Execution policies

### `prepare_only`

Downloads, deduplicates, extracts, inventories, and records the bundle. No device-changing path is entered. The operator checklist marks apply-only steps as safely skipped.

### `approval`

Prepares the bundle and waits for the exact local manifest ID:

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  approve --manifest-id FGOPS-0123456789ABCDEF
```

The operator log shows `⚠️` on the execution gate and records the suggested approval action. This is an expected waiting state, not an apply failure.

### `unattended`

An eligible manifest runs through the same preflight, mandatory backup, package-hash verification, allowlist, version checks, postflight, logging, and audit gates without interactive approval. Failed or review-required archives are not replayed automatically.

Enable unattended execution only after at least one complete approval-mode evidence set has been reviewed and accepted for the exact target profile.

## Result classification

| Evidence | Result | Operator interpretation |
|---|---|---|
| Expected object version increased | `SUCCESS` | `✅` |
| Version increased despite a FortiOS warning or non-zero code | `SUCCESS_WITH_WARNING` | `⚠️`, review the package row |
| FortiGate explicitly completed transfer and versions were already current | `SKIPPED_NO_UPDATE` | `⚠️` at package level; safe no-op |
| No new archive bytes were found | `NO_CHANGE` | `✅` final result with apply steps `⏭️` |
| Expected object missing or unchanged without a trusted successful-transfer outcome | `FAILED_UNCONFIRMED` | `❌` |
| Version decreased, validation failed, backup failed, or target identity changed | `FAILED` | `❌` and do not retry until investigated |

A cycle with one or more `SKIPPED_NO_UPDATE` package results can finish as `SUCCESS_WITH_WARNING`; this is a completed safe cycle, not a failed apply.

## Schedule the policy cycle

```powershell
.\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6 `
  -TaskCommand cycle `
  -TaskName "FGOps Offline Update Monitor"
```

The task runs as `SYSTEM`, prevents overlapping runs, and obeys `execution.mode`. Schedule live application within a maintenance window appropriate to the managed environment.

## Daily log retention

Both journals use the same retention period. The default is 30 date-named files for each log type.

```powershell
[Environment]::SetEnvironmentVariable("FGOPS_LOG_RETENTION_DAYS", "30", "Machine")
[Environment]::SetEnvironmentVariable("FGOPS_LOG_LEVEL", "INFO", "Machine")
```

`FGOPS_LOG_LEVEL` controls the technical journal. The operator journal remains an INFO-level operational checklist.

## Runtime data

Runtime files belong outside the repository:

```text
C:\ProgramData\FGOps\incoming\                         downloaded archives
C:\ProgramData\FGOps\quarantine\                      extracted packages and manifests
C:\ProgramData\FGOps\state\agent-state.json           archive lifecycle state
C:\ProgramData\FGOps\secrets\                         encrypted local secrets
C:\ProgramData\FGOps\evidence\                        preflight and backup evidence
C:\ProgramData\FGOps\evidence\backups\                encrypted full-config backups
C:\ProgramData\FGOps\reports\                         apply reports
C:\ProgramData\FGOps\logs\fgops-operator-*.log       operator checklists
C:\ProgramData\FGOps\logs\fgops-*.log                technical runtime journals
C:\ProgramData\FGOps\tftp\                            per-run temporary TFTP roots
```

## Command reference

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

## Project layout

```text
config/                 package map and sanitized example configuration
docs/                   architecture, deployment, operations, and runbooks
scripts/                Windows deployment and Scheduled Task helpers
src/fgops/               application source
tests/                   automated test suite
.github/workflows/       continuous integration
```

## Documentation

- [Architecture and trust boundaries](docs/architecture.md)
- [Standalone Windows deployment](docs/standalone-agent.md)
- [Private repository synchronization](docs/private-repository-sync.md)
- [Read-only FortiGate preflight](docs/read-only-preflight.md)
- [Backup-only validation](docs/backup-test.md)
- [Controlled apply runbook](docs/controlled-apply.md)
- [Operator checklist logging](docs/operator-checklist-logging.md)
- [Daily runtime logging](docs/daily-runtime-logging.md)
- [Production operations and recovery](docs/operations.md)
- [Security policy and private vulnerability reporting](SECURITY.md)
- [Contribution guidelines](CONTRIBUTING.md)

## Contributing

Issues and pull requests are welcome when they include a clear scope, tests for behavioral changes, and documentation aligned with produced evidence. Do not submit credentials, private keys, production IP addresses, FortiGate backups, package files, bot tokens, or unsanitized operational logs.

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

## Security

Do not report vulnerabilities or operational secrets in issue threads. Follow [`SECURITY.md`](SECURITY.md) for the supported reporting process and the repository's mandatory security controls.

## License

FGOps is licensed under the [MIT License](LICENSE).

The FGOps license applies to this repository's original source code and documentation. It does not grant rights to Fortinet software, FortiGuard content, third-party update packages, trademarks, or other externally supplied materials.

## Disclaimer

FGOps is an independent project and is not affiliated with, maintained by, sponsored by, or endorsed by Fortinet or any package publisher. A discovered or successfully downloaded package is not automatically trusted or compatible. Use only packages you are authorized to obtain, preserve an independent recovery path, and validate every package family against the exact target model and FortiOS branch before unattended deployment.
