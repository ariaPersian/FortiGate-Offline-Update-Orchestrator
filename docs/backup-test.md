# Encrypted full-config backup test

`fgops-agent backup-test` validates the TFTP and SSH path used by controlled apply without restoring any FortiGuard package.

## What it does

1. Runs the pinned read-only preflight.
2. Starts a temporary TFTP server on the configured UDP/69 address.
3. Allows exactly one upload basename.
4. Executes an encrypted FortiGate `full-config` backup over pinned SSH.
5. Waits for the uploaded file to become stable and non-empty.
6. Copies it to the permanent evidence backup directory.
7. Verifies the copy with SHA-256.
8. Writes JSON and text reports.
9. Removes the temporary TFTP run directory.

No `execute restore` command is issued. The report records:

```text
device_changes_performed: false
package_restores_performed: 0
```

## Required configuration

```yaml
storage:
  tftp: tftp

apply:
  tftp_bind_address: 192.168.1.34
  tftp_advertise_address: 192.168.1.34
  tftp_port: 69
  require_backup: true
  backup_password_env: FGOPS_BACKUP_PASSWORD
```

The `device` block must contain the independently verified SSH host-key fingerprint.

## Windows preparation

The VM firewall should allow UDP/69 only from the FortiGate management address. Ensure no other process is listening on UDP/69.

Set the two runtime secrets in the same PowerShell process:

```powershell
$env:FGOPS_SSH_PASSWORD = '<runtime-secret>'
$env:FGOPS_BACKUP_PASSWORD = '<independent-backup-password>'
```

Do not place either value in YAML, source control, command arguments, or reports.

## Run

```powershell
& 'C:\FGOps\venv\Scripts\fgops-agent.exe' `
  --config 'C:\ProgramData\FGOps\config.yml' `
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

A failed preflight, missing backup password, TFTP startup failure, FortiGate command failure, empty upload, or SHA-256 copy mismatch aborts the test.
