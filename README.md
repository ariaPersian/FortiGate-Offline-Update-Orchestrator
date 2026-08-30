# FGOps — FortiGate Offline Update Orchestrator

[![CI](https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private/actions/workflows/ci.yml/badge.svg)](https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**FGOps** is a policy-driven Windows agent for discovering, preparing, backing up, applying, verifying, logging, and auditing offline FortiGuard signature updates on FortiGate appliances that cannot retrieve updates directly from FortiGuard.

> **Current release:** `v0.5.8`  
> **Authoritative production repository:** `ariaPersian/FortiGate-Offline-Update-Orchestrator-Private`  
> **Maturity:** pre-1.0 operational tooling with a validated reference deployment, not a universal compatibility claim.

The former public repository is not the production source of truth. Production checkouts must follow the [private repository synchronization guide](docs/private-repository-sync.md) before upgrades.

FGOps does **not** distribute FortiGuard packages, firmware, licenses, or credentials. Operators are responsible for obtaining authorized packages and validating package compatibility against the exact FortiGate model and FortiOS build.

## Why FGOps exists

Offline FortiGate updates require more than copying a package to TFTP. A controlled workflow must establish package identity, validate the target, preserve a recoverable encrypted configuration backup, restrict package families, verify resulting FortiGuard object versions, retain auditable evidence, and give operators a clear health view.

FGOps implements that workflow as a standalone Windows agent. GitHub is used for source control, review, and CI; it is not required in the production runtime path.

## End-to-end workflow

```text
Windows Scheduled Task (SYSTEM)
  -> fgops-agent cycle
  -> operator + technical daily journals
  -> source-page discovery and bounded download
  -> SHA-256 archive identity
  -> safe extraction and package inventory
  -> immutable manifest
  -> prepare_only / approval / unattended policy
  -> pinned SSH target verification
  -> temporary restricted TFTP when device-changing work is required
  -> encrypted full-config backup
  -> enabled package restore in deterministic order
  -> object-version verification after each package
  -> postflight
  -> JSON/TXT apply report + state + evidence
  -> TFTP cleanup

Operator routine
  -> scripts\health_report.py
  -> HEALTHY / WARNING / CRITICAL
  -> Operator values copied into the RTL checklist
```

## One-command operator health report

Routine operator monitoring no longer requires running each status command manually.

Run PowerShell as Administrator:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

The report checks the production checkout and runtime across:

- Git origin, branch, and working tree;
- source/installed FGOps version parity;
- configuration and fail-closed execution policy;
- required DPAPI secret metadata;
- Scheduled Task state, result, next run, and action;
- unresolved `APPLY_FAILED` / `REVIEW_REQUIRED` state;
- latest scheduled-cycle result;
- latest encrypted backup and apply report;
- UDP/69 listener state and runtime free space;
- pinned read-only FortiGate preflight;
- current FortiGuard object versions against the latest apply evidence.

Every run writes:

```text
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.txt
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.json
```

| Result | Exit code | Meaning |
|---|---:|---|
| `HEALTHY` | `0` | No failed or warning checks |
| `WARNING` | `1` | One or more warnings require review |
| `CRITICAL` | `2` | At least one health check failed |

The console and report files include an `Operator values` section intended to be copied directly into the operator Word checklist.

For local-only diagnostics without a FortiGate SSH preflight:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py" `
  --skip-preflight
```

`--skip-preflight` is not equivalent to a complete production health check.

### Health-report safety boundary

The health script does **not** run `cycle`, `approve`, `apply`, `backup-test`, or any FortiGate restore command. Its only active device operation is the existing pinned read-only preflight.

A normal production health result expects the Scheduled Task to be `Ready` or `Running`. A deliberately disabled Task during maintenance is therefore reported as unhealthy by design; restore scheduling after the maintenance validation and then run the full health report again.

See [Operator health report](docs/operator-health-report.md) for all `HC-01` through `HC-20` checks and [Operator checklist logging](docs/operator-checklist-logging.md) for the operator response procedure.

## Operator and technical journals

Every installed `fgops-agent` command writes two complementary daily log files:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

| File | Intended reader | Content |
|---|---|---|
| `fgops-operator-YYYY-MM-DD.log` | Operations staff | Per-run ToDo list, readable step results, final status, exit code, suggested action |
| `fgops-YYYY-MM-DD.log` | Technical support | Structured JSON events, result payloads, exceptions, tracebacks |

Operator symbols:

| Symbol | Meaning |
|---|---|
| `⬜` | Planned |
| `🔄` | In progress |
| `✅` | Success |
| `⚠️` | Warning / attention |
| `❌` | Failed |
| `⏭️` | Safely skipped |

The health report is the routine monitoring summary. The operator journal is the first per-run troubleshooting view. The technical journal is used when deeper evidence is required.

## Validated reference profile

| Area | Validated value |
|---|---|
| Runtime host | Windows VM, Python 3.13, Scheduled Task as `SYSTEM` |
| Appliance | FortiGate 300D |
| FortiOS | 6.4.16 build 2098 |
| VDOM mode | Multiple VDOM, global-context execution |
| Recommended validated package set | AV, IPS, APDB, MCDB, MMDB |
| Excluded by default | FFDB after return code `49` with unchanged expected ISDB versions |
| Validated live outcome | AV/IPS/APDB/MCDB already current; MMDB increased from `93.07607` to `93.07613`; overall `SUCCESS_WITH_WARNING` |
| Out of scope | Firmware upgrade/downgrade, signature bypass, security-level reduction, Botnet automation |

The tested third-party FFDB file transferred but failed activation with return code `49`; the expected Internet-service database versions remained unchanged. FFDB is therefore excluded from the recommended default allowlist.

Other models, FortiOS branches, package publishers, authentication methods, and network topologies require independent validation.

## Core capabilities

- Configurable source-page monitoring and link matching.
- Native/system TLS validation, bounded downloads, transient-error retry, and atomic replacement.
- SHA-256 archive identity and payload deduplication.
- Safe ZIP extraction and package-kind inventory.
- Fail-closed unknown/ambiguous package handling.
- Exact audit-only `IGNORED` mappings for reviewed legacy files.
- Immutable manifests and atomic lifecycle state.
- SSH host-key pinning and expected target identity checks.
- Encrypted `full-config` backup before every controlled apply.
- Temporary TFTP bound to the selected management interface.
- Explicit package allowlist, deterministic order, stop-on-failure, and downgrade protection.
- Before/after object-version verification rather than trusting transfer success.
- Windows DPAPI `LocalMachine` secret storage with restrictive NTFS ACLs.
- `prepare_only`, exact-manifest `approval`, and `unattended` policies.
- JSON/TXT evidence for preflight, backup, apply, and command output.
- Separate technical and operator UTF-8 daily journals.
- One-command operator health report with machine-readable JSON and operator-friendly TXT output.
- Optional Telegram notifications with tokens kept out of YAML.

## Safety model

FGOps is designed to fail closed. A controlled apply is blocked when any mandatory gate fails, including:

- changed or unverified SSH host key;
- hostname, model, FortiOS branch, or build mismatch;
- unknown or ambiguous enabled package family;
- package/archive SHA-256 mismatch;
- missing or empty encrypted backup;
- downgrade detection;
- invalid-signature or wrong-firmware response;
- missing expected FortiGuard object;
- unconfirmed package outcome;
- failed postflight validation.

A successful TFTP transfer proves delivery only. Package activation requires object-version evidence or another explicitly trusted already-current result.

Health reporting and logging are observational. They must never weaken package selection, target validation, backup, or result-classification gates.

## Requirements

- Windows 10/11 or Windows Server suitable for a dedicated management VM.
- Python `3.11` or newer.
- Access to the authoritative private repository for installation and upgrades.
- Network reachability from the FGOps VM to the FortiGate management interface.
- SSH access appropriate to the selected operation.
- UDP/69 reachability from FortiGate to the temporary FGOps TFTP endpoint.
- Independently verified FortiGate SSH host-key fingerprint.
- Authorized offline signature packages compatible with the target system.

## Repository checkout and upgrades

New production installation:

```powershell
git clone `
  https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git `
  C:\FGOps
```

Verify an existing checkout:

```powershell
Set-Location C:\FGOps
git remote -v
git status --short
git branch --show-current
```

Both fetch and push URLs must point to the private repository. If histories diverge or the checkout still points to the former public repository, follow [Private repository synchronization](docs/private-repository-sync.md). Do not merge unrelated public/private histories merely to make `git pull` succeed.

The default health report also enforces the expected private production origin. Overriding `--expected-remote` is for controlled development diagnostics, not for making a public production checkout appear healthy.

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

Copy and adapt [`config/agent.example.yml`](config/agent.example.yml). Keep production addresses, fingerprints, credentials, evidence, backups, downloaded archives, logs, health reports, and package files outside Git.

Confirm installed version:

```powershell
& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

The current documentation baseline is `0.5.8`.

## Upgrade the production checkout

Disable scheduling while source or environment files are changing:

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

Confirm the reviewed private checkout includes:

```text
scripts/health_report.py
```

Validate configuration, state, and the preparation-only path while the Task remains disabled:

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

After maintenance validation is accepted, enable scheduling:

```powershell
Enable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
```

Then run the normal-state health report:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

Review any `WARNING`. Do not ignore `CRITICAL` merely to restore unattended operation.

## Minimum configuration model

Documentation-only addresses below use TEST-NET ranges and must be replaced locally.

```yaml
source:
  page_url: "https://example.invalid/fortigate-updates/"
  link_text_regex: '(?i)Fortigate\s+V6\.4'
  timeout_seconds: 60
  retry_attempts: 3
  retry_backoff_seconds: 2

execution:
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

Package presence in a downloaded archive does not make it eligible for installation. `execution.enabled_packages` is the apply allowlist. `apply.package_order` only orders packages that already passed that filter.

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

`scan-host-key` discovers the presented key; verify it independently before trusting it.

`backup-test` exercises the pinned SSH + temporary TFTP backup path, verifies the encrypted permanent copy, writes evidence, and performs no package restore.

## Windows machine secret store

Scheduled execution stores DPAPI-encrypted ciphertext in:

```text
C:\ProgramData\FGOps\secrets\secret-store.json
```

The store uses DPAPI `LocalMachine` scope plus restrictive NTFS ACLs for `SYSTEM` and local Administrators.

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

Secret values must never be committed or printed in documentation/evidence.

## Execution policies

### `prepare_only`

Prepare and inventory only; no device-changing path.

### `approval`

Prepare and wait for explicit approval of the exact reviewed manifest:

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  approve --manifest-id FGOPS-0123456789ABCDEF
```

### `unattended`

Run the same target validation, backup, package-hash, allowlist, version, postflight, logging, and state gates without interactive approval. Enable only after an approval-mode evidence set is reviewed for the exact target profile.

## Result classification

| Evidence | Result | Interpretation |
|---|---|---|
| Expected object version increased | `SUCCESS` | Activated and verified |
| Version increased with non-blocking warning | `SUCCESS_WITH_WARNING` | Review warning; no blind retry |
| Explicit successful transfer and object already current | `SKIPPED_NO_UPDATE` | Safe no-op |
| Same archive already handled | `NO_CHANGE` | No apply |
| New ZIP bytes with previously applied enabled payload | `NO_CONTENT_CHANGE` | No device-changing path |
| All enabled packages already current | `NO_UPDATE` | Do not repeat apply |
| New manifest awaiting approval | `PREPARED` | Review before approval |
| Expected object missing/unchanged without trusted no-op evidence | `FAILED_UNCONFIRMED` | Investigate |
| Downgrade, validation, backup, identity, or blocking restore failure | `FAILED` | Stop and investigate |

## Schedule the policy cycle

```powershell
.\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6 `
  -TaskCommand cycle `
  -TaskName "FGOps Offline Update Monitor"
```

The Task runs as `SYSTEM`, prevents overlapping executions, and obeys `execution.mode`.

## Runtime data

Runtime files belong outside the repository:

```text
C:\ProgramData\FGOps\incoming\                         downloaded archives
C:\ProgramData\FGOps\quarantine\                      extracted packages/manifests
C:\ProgramData\FGOps\state\agent-state.json           lifecycle state
C:\ProgramData\FGOps\secrets\                         encrypted local secrets
C:\ProgramData\FGOps\evidence\                        preflight/backup evidence
C:\ProgramData\FGOps\evidence\backups\                encrypted full-config backups
C:\ProgramData\FGOps\reports\                         apply reports
C:\ProgramData\FGOps\reports\health\                  operator health TXT/JSON reports
C:\ProgramData\FGOps\logs\fgops-operator-*.log       operator journals
C:\ProgramData\FGOps\logs\fgops-*.log                technical journals
C:\ProgramData\FGOps\tftp\                            per-run temporary TFTP roots
```

`FGOPS_LOG_RETENTION_DAYS` controls the date-named journals. Timestamped health reports require a separate retention policy.

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

python scripts/health_report.py [--skip-preflight]
```

## Project layout

```text
config/                 package map and sanitized example configuration
docs/                   architecture, deployment, operations, and runbooks
scripts/                Scheduled Task, deployment, and operator health helpers
src/fgops/               application source
tests/                   automated test suite
.github/workflows/       continuous integration
```

## Documentation

- [Operator health report](docs/operator-health-report.md)
- [Operator checklist logging](docs/operator-checklist-logging.md)
- [Daily runtime logging](docs/daily-runtime-logging.md)
- [Production operations and recovery](docs/operations.md)
- [Architecture and trust boundaries](docs/architecture.md)
- [Standalone Windows deployment](docs/standalone-agent.md)
- [Private repository synchronization](docs/private-repository-sync.md)
- [Read-only FortiGate preflight](docs/read-only-preflight.md)
- [Backup-only validation](docs/backup-test.md)
- [Controlled apply runbook](docs/controlled-apply.md)
- [Source bundle ingestion and troubleshooting](docs/source-bundle-ingestion.md)
- [Payload-level deduplication](docs/payload-deduplication.md)
- [Public release checklist](docs/public-release-checklist.md)
- [Security policy](SECURITY.md)
- [Contribution guidelines](CONTRIBUTING.md)

## Contributing

Issues and pull requests should include clear scope, tests for behavioral changes, and documentation aligned with produced evidence. Do not submit credentials, private keys, production addresses, FortiGate backups, package files, bot tokens, unsanitized logs, or health reports.

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

## Security

Do not report vulnerabilities or operational secrets in issue threads. Follow [`SECURITY.md`](SECURITY.md) for the supported reporting process.

## License

FGOps is licensed under the [MIT License](LICENSE).

The license applies to this repository's original source code and documentation. It does not grant rights to Fortinet software, FortiGuard content, third-party update packages, trademarks, or externally supplied materials.

## Disclaimer

FGOps is an independent project and is not affiliated with, maintained by, sponsored by, or endorsed by Fortinet or any package publisher. A discovered or successfully downloaded package is not automatically trusted or compatible. Use only packages you are authorized to obtain, preserve an independent recovery path, and validate every package family against the exact target model and FortiOS branch before unattended deployment.
