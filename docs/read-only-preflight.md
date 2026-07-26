# Read-only FortiGate preflight

FGOps v0.3 adds an SSH preflight that records the FortiGate state before any package-application milestone. It does not start TFTP, answer restore prompts, change configuration, or execute firmware updates.

## Security model

- The FortiGate SSH host key is pinned by its OpenSSH-style `SHA256:<base64>` fingerprint.
- Unknown or changed host keys are rejected. FGOps does not use Paramiko `AutoAddPolicy`.
- Authentication secrets are read from an environment variable or an operator-managed private-key file; passwords are not stored in YAML or evidence.
- Device commands are restricted by a hard-coded read-only allowlist.
- Evidence records the exact outputs and SHA-256 hash of each output.

`scan-host-key` only reads the key presented by the network endpoint. The displayed fingerprint must be verified through a separate trusted path before it is copied into `config.yml`.

## 1. Read the presented host key

```powershell
& "C:\FGOps\venv\Scripts\fgops-agent.exe" `
  scan-host-key `
  --host 172.16.1.2 `
  --port 22
```

Example:

```json
{
  "host": "172.16.1.2",
  "port": 22,
  "key_type": "ssh-ed25519",
  "bits": 256,
  "sha256": "SHA256:..."
}
```

Do not treat this network scan itself as proof of identity. Verify the fingerprint through a console session, an already trusted SSH client, a controlled asset record, or another independent administrative path.

## 2. Configure the pinned target

```yaml
device:
  host: 172.16.1.2
  port: 22
  username: fgops-readonly
  host_key_sha256: SHA256:VERIFIED_VALUE
  password_env: FGOPS_SSH_PASSWORD
  expected_hostname: SITEC-FW-02
  expected_model: FortiGate-300D
  expected_firmware_branch: "6.4"
  expected_build: 2098
  global_context: true
```

For key authentication, configure `key_file` instead of placing a password in YAML.

## 3. Supply authentication for the current process

```powershell
$env:FGOPS_SSH_PASSWORD = Read-Host "FortiGate SSH password" -AsSecureString |
  ConvertFrom-SecureString -AsPlainText
```

For unattended Windows Task Scheduler operation, use an appropriately protected service account and secret-delivery mechanism. Do not embed a password in the task command line, repository, or YAML file.

## 4. Run the preflight

```powershell
& "C:\FGOps\venv\Scripts\fgops-agent.exe" `
  --config "C:\ProgramData\FGOps\config.yml" `
  preflight
```

The command runs only:

```text
get system status
diagnose autoupdate versions
diagnose sys flash list
diagnose debug config-error-log read
diagnose autoupdate signature check-all
```

The expected hostname, model, FortiOS branch, and build are validated. A mismatch results in `FAILED_VALIDATION` and a non-zero exit code.

## Evidence

FGOps writes paired JSON and text evidence under:

```text
C:\ProgramData\FGOps\evidence
```

Evidence includes:

- captured UTC time;
- target address and username;
- pinned host-key fingerprint;
- parsed system status;
- parsed FortiGuard database versions;
- raw output and SHA-256 for every command;
- validation errors;
- `device_changes_performed: false`.
