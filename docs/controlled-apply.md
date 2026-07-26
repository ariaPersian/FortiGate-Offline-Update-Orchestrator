# Controlled apply runbook

FGOps v0.4 introduces the first device-changing path. It is intentionally separate from the scheduled source monitor and must remain in `approval` mode for the first reviewed execution.

## Fortinet basis

Fortinet documents:

- manual IPS update with `execute restore ips tftp <package> <server>`;
- antivirus restore through the corresponding `execute restore av tftp` family;
- other FortiGuard objects through `execute restore other-objects tftp`;
- configuration and full-configuration backups to TFTP;
- global administrator requirements for whole-device backup in multiple-VDOM mode.

References:

- [FortiOS 6.4 manual updates](https://docs.fortinet.com/document/fortigate/6.4.0/administration-guide/200702/manual-updates)
- [FortiOS 6.4 multi-VDOM backup and restore](https://docs.fortinet.com/document/fortigate/6.4.0/administration-guide/87472/backing-up-and-restoring-configurations-in-multi-vdom-mode)

## Configuration

```yaml
execution:
  mode: approval
  enabled_packages: [AV, IPS, APDB, FFDB, MCDB, MMDB]
  reject_unknown_packages: true
  prevent_downgrade: true

apply:
  tftp_bind_address: 192.168.1.179
  tftp_advertise_address: 192.168.1.179
  tftp_port: 69
  require_backup: true
  backup_password_env: FGOPS_BACKUP_PASSWORD
  settle_seconds: 5
  stop_on_failure: true
  package_order: [AV, IPS, APDB, FFDB, MCDB, MMDB]
```

`tftp_bind_address` should be the dedicated management-facing address on the FGOps VM. `tftp_advertise_address` is the address used in FortiOS CLI commands and must be reachable from the FortiGate. The port is fixed to UDP/69 because the FortiOS restore command does not expose a custom TFTP port parameter.

## Secrets

The SSH and backup encryption secrets are read from environment variables:

```powershell
$env:FGOPS_SSH_PASSWORD = '<runtime secret>'
$env:FGOPS_BACKUP_PASSWORD = '<runtime backup encryption secret>'
```

Do not store either value in YAML, Git, command history, reports, or Scheduled Task arguments. For unattended operation, use an OS-managed service credential or secret provider rather than a plaintext machine environment variable.

## Windows prerequisites

Run from elevated PowerShell because binding UDP/69 and creating a firewall rule may require administrator rights.

Confirm the port is not already used:

```powershell
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
```

Permit inbound TFTP only from the FortiGate management address:

```powershell
New-NetFirewallRule `
  -DisplayName 'FGOps temporary TFTP from FortiGate' `
  -Direction Inbound `
  -Action Allow `
  -Protocol UDP `
  -LocalPort 69 `
  -LocalAddress 192.168.1.179 `
  -RemoteAddress 172.16.1.2
```

The rule may remain disabled outside a maintenance window. FGOps itself starts and stops the TFTP application endpoint for each run.

## Required sequence

1. Run source preparation and record `manifest_id`.
2. Run pinned read-only preflight and review `PASS`.
3. Ensure the package has not already been manually applied.
4. Set both runtime secrets.
5. Confirm UDP/69 is available and reachable.
6. Repeat the exact manifest ID in both apply arguments.

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  apply `
  --manifest-id FGOPS-0123456789ABCDEF `
  --approve-manifest FGOPS-0123456789ABCDEF
```

## Apply state machine

```text
PREPARED
  -> exact approval manifest check
  -> preflight PASS
  -> package SHA-256 verification
  -> restricted temporary TFTP root
  -> encrypted full-config backup received
  -> package restore
  -> immediate version collection
  -> per-package classification
  -> postflight PASS
  -> report + APPLIED state
```

Any failure before the first restore causes an abort with no package changes. A failed mandatory backup blocks all restores.

## Automatic confirmation boundary

FGOps answers only the standard FortiOS prompt:

```text
Do you want to continue? (y/n)
```

The following text aborts instead of being accepted:

```text
invalid signature
signature invalid
no signature for validation
wrong firmware version
pkg has wrong firmware version
downgrade
```

## Package order and classification

Default order:

```text
AV -> IPS -> APDB -> FFDB -> MCDB -> MMDB
```

ISDB and Botnet remain excluded because their observed FortiOS 6.4 behavior was not suitable for unattended execution.

Classification is based on expected object versions, not only the CLI return code:

- version increase: `SUCCESS`;
- version increase plus non-zero return code or `Command fail`: `SUCCESS_WITH_WARNING`;
- unchanged version with `No updates` and `-85`: `SKIPPED_NO_UPDATE`;
- unchanged or missing expected object: `FAILED_UNCONFIRMED`;
- decreased object version: `FAILED`.

With `stop_on_failure: true`, `FAILED` and `FAILED_UNCONFIRMED` stop the remaining package sequence.

## Evidence

FGOps writes:

```text
C:\ProgramData\FGOps\evidence\<timestamp>-<host>.json
C:\ProgramData\FGOps\evidence\<timestamp>-<host>.txt
C:\ProgramData\FGOps\evidence\backups\<hostname>-<timestamp>-full.conf
C:\ProgramData\FGOps\reports\<timestamp>-<manifest>-apply.json
C:\ProgramData\FGOps\reports\<timestamp>-<manifest>-apply.txt
```

The encrypted backup is copied out of the temporary TFTP root and SHA-256 verified before the temporary root is removed. Reports include before/after versions and hashes of command output. The backup password is redacted.

## First-run restriction for the current SITEC bundle

The already prepared manifest `FGOPS-87B42FF117D6CCD6` corresponds to definitions that were previously installed manually. Reapplying it is not a valid end-to-end update test because the expected versions are already present and would correctly classify as unchanged. Use the next newly published archive for the first live package apply, or validate only preflight and infrastructure until a new archive hash appears.
