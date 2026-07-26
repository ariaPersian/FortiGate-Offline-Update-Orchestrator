# FGOps

**FortiGate Offline Update Orchestrator** automates preparation and controlled delivery of offline FortiGuard signature bundles.

> Current milestone: `v0.4.0`. A standalone VM can monitor the source page, prepare and deduplicate a FortiOS 6.4 bundle, pin and validate the FortiGate SSH host key, create an encrypted full configuration backup through a temporary TFTP service, apply an approved manifest package-by-package, compare before/after database versions, and write audit evidence.

## Primary deployment model

```text
scheduled local agent
  -> monitor configured source page
  -> discover Fortigate V6.4 download link
  -> bounded download + SHA-256 deduplication
  -> safe extraction + package inventory
  -> pinned read-only SSH preflight
  -> exact manifest approval gate
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

## Controlled apply

The first live use must set:

```yaml
execution:
  mode: approval
```

The command requires the operator to repeat the exact prepared manifest ID:

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  apply `
  --manifest-id FGOPS-0123456789ABCDEF `
  --approve-manifest FGOPS-0123456789ABCDEF
```

Before any package restore, FGOps requires:

- pinned SSH host key and passing target identity validation;
- unchanged package hashes from manifest to TFTP staging;
- an available management-facing UDP/69 endpoint;
- a non-empty backup encryption secret from `FGOPS_BACKUP_PASSWORD`;
- receipt of a non-empty encrypted full-config backup.

Only the standard FortiOS overwrite confirmation is automatically answered. Signature, wrong-firmware, or downgrade warnings abort the run.

## Result classification

```text
expected object version increased                         SUCCESS
version increased despite FortiOS non-zero return code    SUCCESS_WITH_WARNING
No updates with return code -85                           SKIPPED_NO_UPDATE
expected object absent or unchanged                       FAILED_UNCONFIRMED
object version decreased                                  FAILED
```

## Schedule the monitor

The recurring monitor can run independently of apply:

```powershell
.\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6
```

Do not schedule live apply until one complete approval-mode evidence set has been reviewed.

## Commands

```text
fgops-agent init
fgops-agent validate-config
fgops-agent run [--dry-run]
fgops-agent scan-host-key
fgops-agent preflight
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
- secrets read from environment variables, never YAML;
- fixed package order and stop-on-failure;
- downgrade detection;
- preflight/postflight and command-output hashes;
- atomic local state updates.

See [standalone agent](docs/standalone-agent.md), [read-only preflight](docs/read-only-preflight.md), [controlled apply](docs/controlled-apply.md), [architecture](docs/architecture.md), and [security policy](SECURITY.md).

## Disclaimer

FGOps is independent and is not affiliated with or endorsed by Fortinet or third-party package publishers. Use only packages you are authorized to obtain and validate them under your organization’s security policy.
