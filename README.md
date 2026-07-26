# FGOps

**FortiGate Offline Update Orchestrator** is a policy-driven tool for preparing, approving, applying, and auditing offline FortiGuard signature updates in restricted networks.

> Current milestone: `v0.1.0` approval foundation. Bundle inventory, package classification, signed durable approval state, deterministic GitHub Issue command reconciliation, reminders, expiry, snooze, scheduling, FortiOS output parsing, tests, and safe workflow scaffolding are implemented. Device-changing automation remains intentionally disabled until read-only preflight and SSH/TFTP execution gates are complete.

## Why FGOps

Manual offline updating is repetitive, but blindly automating third-party package installation is unsafe. FGOps uses an immutable manifest and a deferred approval model:

```text
bundle -> quarantine -> SHA-256 manifest -> signed approval -> maintenance window -> apply -> verify -> audit
```

Approvals can be explicit, snoozed, scheduled, or configured with a grace period for a restricted safe package set. Firmware, downgrade, and signature bypass never enter unattended execution.

## Initial supported profile

- FortiGate 300D
- FortiOS 6.4.16 build 2098
- Multi-VDOM/global restore context
- Offline packages delivered through a private TFTP host
- AV, IPS, APDB, FFDB, MCDB, MMDB, ISDB, and Botnet package inventory

## Quick start

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest

fgops inventory `
  C:\Downloads\Cyberlogic-Fortigate-V6.4-Weekly-Signature.zip `
  --output C:\FGOps\quarantine\run-001 `
  --package-map config\fortios64-package-map.yml
```

Parse a captured FortiGate status file:

```powershell
fgops parse-versions .\evidence\before.txt
```

Validate an approval command:

```powershell
fgops approval-command "/fg snooze 24h"
```

Render, but do not execute, a FortiOS restore command:

```powershell
fgops render-restore AV cyberlogic.ir-AV.pkg 192.168.1.179
```

## Configure durable approvals

Create a private repository Actions secret named:

```text
FGOPS_APPROVAL_HMAC_KEY
```

Generate a random value of at least 32 bytes:

```powershell
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToBase64String($bytes)
```

Then run **Prepare offline update approval** manually. The private runner inventories the local ZIP and uploads only `manifest.json`; a GitHub-hosted job creates an Issue containing HMAC-authenticated state bound to the exact issue, device, expected firmware, archive hash, package hashes, and package allow-list.

The hourly watchdog and comment workflow become active after their workflow files are present on the default branch.

## Deferred approval commands

```text
/fg approve
/fg reject <reason>
/fg snooze 24h
/fg schedule 2026-08-02T02:00:00+03:30
/fg apply-safe
/fg status
/fg cancel
```

All unprocessed `/fg` comments are replayed in deterministic chronological order. Comment IDs are persisted in signed state, making retries idempotent and allowing the watchdog to recover commands even when an intermediate workflow run is dropped.

## Repository safety model

- Pull-request CI uses GitHub-hosted runners.
- The private network runner is selected only by `[self-hosted, windows, fgops, sitec]`.
- `prepare-update.yml` inventories a bundle but executes no FortiGate command.
- Only the manifest is uploaded from the private runner; package payloads remain local.
- Package files, firmware, configurations, logs, secrets, and runtime state are ignored by Git.
- Approval state is HMAC-bound to the repository, issue, device, expected firmware, manifest, package hashes, and exact package allow-list.
- GitHub Issue comments form the durable command queue and GitHub Issues remain the audit source of truth.

See [architecture](docs/architecture.md), [approval model](docs/approval-model.md), and [security policy](SECURITY.md).

## Roadmap

1. Persist approval requests in signed state and synchronize them with GitHub Issues. **Implemented in DEV-001.**
2. Add reminder escalation channels, beginning with Telegram.
3. Add SSH read-only preflight and configuration backup.
4. Add a temporary TFTP lifecycle manager.
5. Add package-by-package apply with before/after verification and concurrency locks.
6. Add HTML/JSON audit reports and rollback guidance.

## Disclaimer

FGOps is an independent project and is not affiliated with or endorsed by Fortinet. Use only packages you are authorized to obtain and validate them according to your organization's security policy.
