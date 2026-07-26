# FGOps

**FortiGate Offline Update Orchestrator** automates preparation and controlled delivery of offline FortiGuard signature bundles.

> Current milestone: `v0.5.0`. A standalone Windows VM can monitor the source page, prepare and deduplicate a FortiOS 6.4 bundle, notify through Telegram, load machine-scoped encrypted secrets for scheduled execution, validate encrypted full-config backup delivery, and apply a prepared manifest according to `prepare_only`, `approval`, or `unattended` policy.

## Primary deployment model

```text
Windows Scheduled Task (SYSTEM)
  -> policy cycle
  -> monitor configured source page
  -> discover Fortigate V6.4 download link
  -> bounded download + SHA-256 deduplication
  -> safe extraction + package inventory
  -> Telegram notification when configured
  -> prepare_only: stop
  -> approval: wait for exact local manifest approval
  -> unattended: load DPAPI machine secrets
  -> pinned read-only SSH preflight
  -> temporary restricted TFTP service
  -> encrypted full-config backup
  -> AV / IPS / APDB / FFDB / MCDB / MMDB restore
  -> per-package version comparison
  -> postflight + JSON/TXT report
```

GitHub maintains and reviews the code. A GitHub self-hosted runner is not required.

## Supported profile

- FortiGate 300D
- FortiOS 6.4.16 build 2098
- multiple VDOM mode and global-context execution
- default apply allowlist: AV, IPS, APDB, FFDB, MCDB, MMDB
- ISDB and Botnet are classified but excluded from controlled/unattended apply
- firmware upgrade, downgrade enablement, signature bypass, and security-level reduction are out of scope

## Install on a Windows VM

```powershell
py -3.13 -m venv C:\FGOps\venv
& C:\FGOps\venv\Scripts\python.exe -m pip install --upgrade pip
& C:\FGOps\venv\Scripts\python.exe -m pip install --no-user C:\FGOps

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  init --package-map-source C:\FGOps\config\fortios64-package-map.yml
```

## Safe preparation and preflight

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml validate-config
fgops-agent --config C:\ProgramData\FGOps\config.yml run --dry-run
fgops-agent scan-host-key --host 172.16.1.2 --port 22
fgops-agent --config C:\ProgramData\FGOps\config.yml preflight
fgops-agent --config C:\ProgramData\FGOps\config.yml status
```

The URL is rediscovered on each run. A reused URL does not hide a new package because archive identity is the downloaded SHA-256.

## Windows machine secret store

Scheduled execution cannot depend on process-scoped PowerShell environment variables. FGOps stores only DPAPI-encrypted ciphertext in:

```text
C:\ProgramData\FGOps\secrets\secret-store.json
```

The store uses Windows DPAPI `LocalMachine` scope and removes inherited ACLs, granting full control only to `SYSTEM` and the local Administrators group. The plaintext is injected into the scheduled process environment only for the duration of the controlled operation and is then restored/removed.

Create the required secrets interactively from an elevated shell:

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_TELEGRAM_BOT_TOKEN
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

Secret values are never printed by the CLI and must never be committed to Git.

## Telegram notification policy

Add an optional notification block to `config.yml`:

```yaml
storage:
  root: C:/ProgramData/FGOps
  secret_store: secrets/secret-store.json

notifications:
  telegram:
    enabled: true
    chat_id: "REPLACE_WITH_CHAT_ID"
    token_secret_name: FGOPS_TELEGRAM_BOT_TOKEN
    timeout_seconds: 30
    notify_on: [PREPARED, FAILED, SUCCESS, SUCCESS_WITH_WARNING]
```

Validate and send a test message:

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml validate-config
fgops-agent --config C:\ProgramData\FGOps\config.yml notify-test
```

The Bot API token remains in the encrypted local secret store, not YAML.

## Backup-only validation

Before the first live package restore, validate the exact SSH, global-context, TFTP, encryption, firewall, and persistence path independently:

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  backup-test
```

The command runs preflight, starts the temporary UDP/69 service, exports one encrypted `full-config` backup, verifies the permanent copy with SHA-256, writes JSON/TXT evidence, and removes the temporary TFTP run directory. It never issues `execute restore` and records:

```text
device_changes_performed: false
package_restores_performed: 0
```

## Execution policies

### `prepare_only`

The cycle downloads, validates, inventories, and optionally notifies. It never connects to the FortiGate for apply.

```yaml
execution:
  mode: prepare_only
```

### `approval`

The cycle prepares and notifies, then waits. Apply requires the exact manifest ID and loads SSH/backup secrets from the machine store:

```yaml
execution:
  mode: approval
```

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  approve --manifest-id FGOPS-0123456789ABCDEF
```

### `unattended`

A newly prepared manifest immediately passes through the same pinned preflight, mandatory encrypted backup, hash verification, temporary TFTP, downgrade protection, package allowlist, and postflight gates:

```yaml
execution:
  mode: unattended
```

Enable this only after at least one approval-mode live evidence set has been reviewed.

## Result classification

```text
expected object version increased                         SUCCESS
version increased despite FortiOS non-zero return code    SUCCESS_WITH_WARNING
No updates with return code -85                           SKIPPED_NO_UPDATE
expected object absent or unchanged                       FAILED_UNCONFIRMED
object version decreased                                  FAILED
```

## Schedule the policy cycle

```powershell
.\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6 `
  -TaskCommand cycle
```

The task runs as `SYSTEM`. `cycle` always obeys `execution.mode`; registration alone does not enable unattended apply.

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

## Safety controls

- bounded download size and timeout;
- native/system TLS validation;
- archive and package SHA-256 identity;
- ZIP traversal, symlink, duplicate-kind, and unknown-package rejection;
- SSH host-key pinning and expected target identity;
- temporary TFTP root with exact backup upload basename;
- encrypted backup required by default;
- Windows DPAPI LocalMachine secret protection plus restrictive NTFS ACLs;
- secrets injected only for the controlled operation;
- Telegram token never stored in YAML;
- explicit execution policy boundary;
- backup-only test before first package restore;
- fixed package order and stop-on-failure;
- downgrade detection;
- preflight/postflight and command-output hashes;
- atomic local state updates.

See [standalone agent](docs/standalone-agent.md), [read-only preflight](docs/read-only-preflight.md), [backup test](docs/backup-test.md), [controlled apply](docs/controlled-apply.md), [architecture](docs/architecture.md), and [security policy](SECURITY.md).

## Disclaimer

FGOps is independent and is not affiliated with or endorsed by Fortinet or third-party package publishers. Use only packages you are authorized to obtain and validate them under your organization’s security policy.
