# FGOps

**FortiGate Offline Update Orchestrator** automates the recurring preparation and controlled delivery of offline FortiGuard signature bundles.

> Current milestone: `v0.2.0` standalone-agent foundation. A local VM can monitor a configured web page, discover the FortiGate 6.4 download link, download the ZIP atomically, deduplicate it by SHA-256, extract it safely, classify packages, and create a local execution plan. Device-changing SSH/TFTP execution remains blocked until the next validation gate.

## Primary deployment model

For one FortiGate, FGOps runs directly on a Windows or Linux VM that can reach both the internet and the firewall management network:

```text
scheduled local agent
  -> monitor configured source page
  -> discover Fortigate V6.4 download link
  -> download and SHA-256 check
  -> safe extraction and package inventory
  -> local state and plan
  -> SSH/TFTP apply gate (next milestone)
```

GitHub is used to maintain and review the code. A GitHub self-hosted runner is not required for this deployment model.

## Supported bundle profile

- FortiGate 300D
- FortiOS 6.4.16 build 2098
- AV, IPS, APDB, FFDB, MCDB, MMDB, ISDB, and Botnet package classification
- default unattended allow-list: AV, IPS, APDB, FFDB, MCDB, MMDB
- ISDB and Botnet excluded from default unattended execution because their observed FortiOS 6.4 behavior needs separate handling

## Install on a Windows VM

```powershell
py -3.12 -m venv C:\FGOps\venv
C:\FGOps\venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest

fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  init --package-map-source .\config\fortios64-package-map.yml

fgops-agent --config C:\ProgramData\FGOps\config.yml validate-config
fgops-agent --config C:\ProgramData\FGOps\config.yml run --dry-run
fgops-agent --config C:\ProgramData\FGOps\config.yml status
```

The generated configuration monitors the Cyberlogic offline-update page and selects the entry whose surrounding text matches:

```text
Fortigate V6.4
```

The URL is rediscovered on every run. A reused URL does not hide an update because FGOps compares the downloaded archive SHA-256 with local state.

## Schedule the monitor

From elevated PowerShell:

```powershell
.\scripts\install-scheduled-task.ps1 `
  -AgentExecutable C:\FGOps\venv\Scripts\fgops-agent.exe `
  -ConfigPath C:\ProgramData\FGOps\config.yml `
  -IntervalHours 6
```

The scheduled task prevents overlapping executions and records all runtime state outside the repository under `C:\ProgramData\FGOps` by default.

## Commands

```text
fgops-agent init
fgops-agent validate-config
fgops-agent run [--dry-run]
fgops-agent status
```

The existing `fgops` CLI remains available for manual inventory, FortiOS output parsing, result classification, restore-command rendering, and the optional GitHub Issue approval model.

## Safety controls

- bounded download size and timeout;
- atomic `.part` download and rename;
- SHA-256 archive identity and duplicate suppression;
- ZIP traversal and symbolic-link rejection;
- unknown package types rejected by default;
- local state written atomically;
- no password stored in the agent YAML;
- no firmware downgrade, signature bypass, or security-level reduction;
- no device-changing action in v0.2.

See [standalone agent](docs/standalone-agent.md), [architecture](docs/architecture.md), [approval model](docs/approval-model.md), and [security policy](SECURITY.md).

## Roadmap

1. Standalone source monitor, bounded downloader, SHA-256 state, extraction, and plan generation. **Implemented in v0.2.**
2. Read-only SSH preflight: host-key pinning, target model/build validation, and version evidence.
3. Temporary TFTP lifecycle manager and package-by-package restore.
4. Before/after version comparison, FortiOS return-code classification, and stop-on-failure.
5. Windows Task Scheduler installation hardening, notifications, retention, and audit reports.
6. Optional GitHub/Telegram approval channels for organizations that require them.

## Disclaimer

FGOps is independent and is not affiliated with or endorsed by Fortinet or third-party package publishers. Use only packages you are authorized to obtain and validate them according to your organization's security policy.
