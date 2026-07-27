# Controlled apply runbook

FGOps v0.5.4 provides the device-changing path for selected offline FortiGuard database packages. The path is designed around exact package identity, pinned target identity, mandatory encrypted backup, temporary TFTP delivery, and observed FortiGuard object versions.

## Fortinet command basis

The controlled path uses the FortiOS CLI families documented for manual database update and configuration backup:

```text
execute restore av tftp <package> <server>
execute restore ips tftp <package> <server>
execute restore other-objects tftp <package> <server>
execute backup full-config tftp <filename> <server> <password>
diagnose autoupdate versions
```

References:

- [FortiOS 6.4 manual updates](https://docs.fortinet.com/document/fortigate/6.4.0/administration-guide/200702/manual-updates)
- [FortiOS 6.4 multi-VDOM backup and restore](https://docs.fortinet.com/document/fortigate/6.4.0/administration-guide/87472/backing-up-and-restoring-configurations-in-multi-vdom-mode)
- [FortiOS 6.4 configuration backup best practice](https://docs.fortinet.com/document/fortigate/6.4.0/best-practices/262994/performing-a-configuration-backup)

## Recommended configuration

Start with `approval` mode and the validated package set:

```yaml
execution:
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

`tftp_bind_address` is the dedicated management-facing address on the FGOps VM. `tftp_advertise_address` is placed in the FortiOS command and must be reachable from the FortiGate. FortiOS restore commands do not expose a custom TFTP port, so the endpoint uses UDP/69.

The ZIP inventory may contain additional package families. Only `execution.enabled_packages` authorizes installation. `package_order` does not authorize a package by itself.

## Secrets

For interactive diagnostics, FGOps can read the configured secret names from process environment variables. Scheduled and unattended execution should use the local encrypted secret store:

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

Do not place either secret in YAML, Git, command history, Scheduled Task arguments, or reports.

## Prerequisites

1. Install the reviewed FGOps revision in the production virtual environment.
2. Copy production configuration outside the repository.
3. Verify the FortiGate host-key fingerprint through an independent trusted path.
4. Configure expected hostname, model, FortiOS branch/build, and global-context behavior.
5. Bind TFTP to the management-facing VM address.
6. Restrict inbound UDP/69 to the FortiGate management address.
7. Store the SSH and backup encryption secrets.
8. Run `preflight` and `backup-test` successfully.
9. Review the package allowlist and maintenance window.

Confirm that UDP/69 is not already in use:

```powershell
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
```

Example restricted firewall rule:

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

## Approval-mode apply

Prepare the bundle and obtain its manifest ID:

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  run --dry-run
```

Apply the exact manifest:

```powershell
fgops-agent `
  --config C:\ProgramData\FGOps\config.yml `
  approve --manifest-id FGOPS-0123456789ABCDEF
```

The approval is local and exact. Another archive hash or manifest ID is not substituted.

## Unattended cycle

After one reviewed live run, set:

```yaml
execution:
  mode: unattended
```

Then execute or schedule:

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml cycle
```

A newly downloaded archive or an eligible previously prepared archive enters the same controlled path. `APPLY_FAILED` and review-required archives are not replayed automatically.

## Apply state machine

```text
PREPARED
  -> policy/manifest eligibility
  -> pinned read-only preflight PASS
  -> package and staged-file SHA-256 verification
  -> restricted per-run TFTP root
  -> encrypted full-config backup received
  -> permanent backup copy verified by SHA-256
  -> restore enabled packages in configured order
  -> collect versions after each package
  -> classify package result
  -> stop on blocking failure when configured
  -> postflight PASS
  -> JSON/TXT report
  -> APPLIED or APPLY_FAILED state
  -> TFTP cleanup after successful completion
```

Any failure before the first package restore blocks device changes. A failed mandatory backup blocks all restores.

## Interactive confirmation boundary

FGOps answers only the standard FortiOS prompt:

```text
Do you want to continue? (y/n)
```

TFTP progress lines made only of `#` are not CLI prompts. The agent waits for the real FortiGate prompt and command completion.

The following conditions block apply rather than being accepted:

```text
invalid signature
signature invalid
no signature for validation
wrong firmware version
pkg has wrong firmware version
downgrade
```

## Result classification

Classification uses expected FortiGuard objects before and after restore, together with the CLI output:

| Condition | Result |
|---|---|
| At least one expected version increased | `SUCCESS` |
| Version increased despite a non-zero code or command warning | `SUCCESS_WITH_WARNING` |
| FortiGate explicitly completed transfer and all expected versions were already current | `SKIPPED_NO_UPDATE` |
| Expected object missing or unchanged without a trusted successful-transfer outcome | `FAILED_UNCONFIRMED` |
| Version decreased or blocking validation/backup/identity error | `FAILED` |

`SUCCESS_WITH_WARNING` and `SKIPPED_NO_UPDATE` produce an overall warning result but do not stop the package sequence. `FAILED` and `FAILED_UNCONFIRMED` stop the remaining sequence when `stop_on_failure: true`.

## FFDB and return code 49

FFDB is target-specific and is not in the recommended default allowlist.

If FFDB is explicitly enabled and FortiOS returns code `49`, FGOps v0.5.4:

1. does not submit the package a second time;
2. polls `Internet-service Database Apps` and `Internet-service Full Database Maps` every 30 seconds;
3. waits for up to 30 minutes by default;
4. continues only if a version change is observed;
5. otherwise keeps a fail-closed result.

Diagnostic overrides:

```text
FGOPS_FFDB_MAX_WAIT_SECONDS
FGOPS_FFDB_POLL_SECONDS
```

A transfer message such as `Get other objects from tftp server OK.` proves that the file reached FortiOS. If it is followed by `Failed to restore other objects file`, return code `49`, and unchanged database versions, the package was not activated and must not be treated as current.

## Evidence

FGOps writes:

```text
C:\ProgramData\FGOps\evidence\<timestamp>-<host>.json
C:\ProgramData\FGOps\evidence\<timestamp>-<host>.txt
C:\ProgramData\FGOps\evidence\backups\<hostname>-<timestamp>-full.conf
C:\ProgramData\FGOps\reports\<timestamp>-<manifest>-apply.json
C:\ProgramData\FGOps\reports\<timestamp>-<manifest>-apply.txt
```

Reports contain target identity, preflight/postflight evidence paths, backup metadata, per-package before/after versions, return codes, classifications, and hashes of command output. Backup passwords are redacted.

## Failure recovery

1. Disable the Scheduled Task before investigation.
2. Preserve the failed apply report, preflight/postflight evidence, encrypted backup, state file, and TFTP run root.
3. Compare package command output with `diagnose autoupdate versions` on the FortiGate.
4. Do not infer activation from TFTP success alone.
5. Correct code, configuration, package allowlist, or source compatibility before retrying.
6. Do not delete the archive state to force replay.
7. If a state reset is exceptionally required, back up the state file, target exactly one archive hash/manifest, document the reason, and perform the retry in the foreground.
8. Re-enable scheduling only after a clean `SUCCESS`, `SUCCESS_WITH_WARNING`, or verified `NO_CHANGE` outcome.
