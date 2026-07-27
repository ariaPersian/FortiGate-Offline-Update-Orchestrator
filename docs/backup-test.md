# Encrypted full-config backup test

`fgops-agent backup-test` validates the exact SSH, global-context, TFTP, backup encryption, persistence, and evidence path used by controlled apply without restoring any FortiGuard package.

## What it does

1. Runs the pinned read-only preflight.
2. Starts a temporary TFTP server on the configured management-facing UDP/69 address.
3. Allows exactly one backup upload basename.
4. Executes an encrypted FortiGate `full-config` backup over pinned SSH.
5. Waits for the uploaded file to become stable and non-empty.
6. Copies it to the permanent evidence backup directory.
7. Verifies the permanent copy with SHA-256.
8. Writes JSON and text reports with the backup password redacted.
9. Stops TFTP and removes the temporary run directory.

No `execute restore` command is issued. The report records:

```text
device_changes_performed: false
package_restores_performed: 0
```

## Required configuration

```yaml
storage:
  root: C:/ProgramData/FGOps
  evidence: evidence
  reports: reports
  tftp: tftp
  secret_store: secrets/secret-store.json

apply:
  tftp_bind_address: 192.0.2.10
  tftp_advertise_address: 192.0.2.10
  tftp_port: 69
  require_backup: true
  backup_password_env: FGOPS_BACKUP_PASSWORD
```

The `device` block must contain the independently verified SSH host-key fingerprint and expected target identity.

## Prepare Windows

Run from elevated PowerShell. Restrict inbound UDP/69 to the FortiGate management source address and verify that no other process is listening:

```powershell
Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue
```

Store the required secrets for scheduled or unattended execution:

```powershell
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_SSH_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret set FGOPS_BACKUP_PASSWORD
fgops-agent --config C:\ProgramData\FGOps\config.yml secret status
```

For a one-time interactive diagnostic, process environment variables may be used instead, but they must not be placed in YAML, Git, command history, Scheduled Task arguments, or reports.

## Run

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  backup-test
```

Expected result:

```json
{
  "status": "PASS",
  "device_changes_performed": false,
  "package_restores_performed": 0
}
```

Permanent artifacts are written under:

```text
C:\ProgramData\FGOps\evidence\backups
C:\ProgramData\FGOps\reports
```

Verify the backup SHA-256 independently:

```powershell
$Backup = Get-ChildItem C:\ProgramData\FGOps\evidence\backups -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Get-FileHash $Backup.FullName -Algorithm SHA256
```

A failed preflight, missing secret, TFTP startup failure, FortiGate backup-command failure, empty upload, unstable upload, or SHA-256 copy mismatch aborts the test.

## Interpretation

A `PASS` proves that FGOps can authenticate the pinned target, create a full encrypted backup, receive it over the restricted TFTP path, preserve it, and verify the copy. It does not prove that the backup password is recoverable from an independent process, that the file has been restore-tested, or that any package is safe to apply. Those are separate organizational controls.
