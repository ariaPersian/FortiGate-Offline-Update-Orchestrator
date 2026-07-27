# Read-only FortiGate preflight

`fgops-agent preflight` records and validates the FortiGate state before backup or package application. It does not start TFTP, answer restore prompts, change configuration, or issue firmware-update commands.

In v0.5.5, the command also records start, result, exit code, and any exception in the daily runtime journal.

## Security model

- The FortiGate SSH host key is pinned by its OpenSSH-style `SHA256:<base64>` fingerprint.
- Unknown or changed host keys are rejected; FGOps does not automatically trust a newly presented key.
- The configured hostname, model, FortiOS branch/build, VDOM mode, and HA mode are collected and expected identity fields are validated.
- Authentication secrets are read from the configured environment-variable names; scheduled execution loads those values temporarily from the encrypted local secret store.
- Device commands are restricted to a hard-coded read-only allowlist.
- Evidence stores the command output and SHA-256 hash of each output.
- Daily logs contain operational metadata and result payloads, never plaintext secret values.

`scan-host-key` reads the key presented by the network endpoint. The displayed fingerprint must be verified through a separate trusted path before it is copied into `config.yml`.

## 1. Read the presented host key

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  scan-host-key `
  --host 192.0.2.1 `
  --port 22
```

Example:

```json
{
  "host": "192.0.2.1",
  "port": 22,
  "key_type": "ssh-ed25519",
  "bits": 256,
  "sha256": "SHA256:..."
}
```

Do not treat this scan as proof of identity. Verify the fingerprint through a console session, an already trusted SSH client, a controlled asset record, or another independent administrative path.

## 2. Configure the pinned target

```yaml
device:
  host: 192.0.2.1
  port: 22
  username: fgops-admin
  host_key_sha256: SHA256:VERIFIED_VALUE
  password_env: FGOPS_SSH_PASSWORD
  # key_file: C:/ProgramData/FGOps/keys/fgops_ed25519
  # key_passphrase_env: FGOPS_SSH_KEY_PASSPHRASE
  connect_timeout_seconds: 20
  command_timeout_seconds: 120
  expected_hostname: REPLACE_WITH_EXPECTED_HOSTNAME
  expected_model: REPLACE_WITH_EXPECTED_MODEL
  expected_firmware_branch: "6.4"
  expected_build: 2098
  global_context: true
```

Use the least-privileged administrator profile that still supports the required global-context read, backup, and restore commands. For key authentication, configure `key_file` rather than embedding private-key content in YAML.

## 3. Store authentication for scheduled execution

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  secret set FGOPS_SSH_PASSWORD

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  secret status
```

For a one-time interactive diagnostic, the configured environment variable may be set in the current PowerShell process. Do not embed a password in the repository, YAML, Scheduled Task command line, persistent plaintext machine environment, report, or log.

## 4. Run preflight

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  preflight
```

The read-only command set is:

```text
get system status
diagnose autoupdate versions
diagnose sys flash list
diagnose debug config-error-log read
diagnose autoupdate signature check-all
```

The expected hostname, model, FortiOS branch, and build are validated. A mismatch produces a failed validation result and non-zero process outcome.

## Evidence

FGOps writes paired JSON and text evidence under:

```text
C:\ProgramData\FGOps\evidence
```

Evidence includes:

- captured UTC time;
- target address and port;
- pinned host-key fingerprint;
- parsed system status;
- parsed FortiGuard database versions;
- raw output and SHA-256 for every command;
- validation and command errors;
- `device_changes_performed: false`.

Reports can contain operationally sensitive target identity and version information. Keep them outside Git and protect them with the host access and retention policy.

## Daily log correlation

The same command writes a structured event to:

```text
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

Search for recent preflight results:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-*.log" `
  -Pattern '"event": "preflight.completed"|"event": "command.failed"'
```

The daily log identifies when the command ran, its exit code, and the evidence path returned by the command. The JSON/TXT evidence remains the authoritative detailed command record.

## Required interpretation

A `PASS` means the pinned endpoint authenticated, the allowed commands completed, and configured identity expectations matched. It does not establish package compatibility, source trust, backup validity, or the safety of a future restore. Those gates are evaluated separately.
