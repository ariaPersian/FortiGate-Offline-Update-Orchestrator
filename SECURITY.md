# Security policy

Do not report credentials, private keys, FortiGate configuration backups, package files, bot tokens, or production IP details in public issues.

## Mandatory controls

- Keep the deployment VM dedicated or tightly controlled and patched.
- Run the scheduled policy cycle under `SYSTEM` only after reviewing the installed code and configuration.
- Keep SSH passwords, backup encryption passwords, and notification tokens out of YAML, Git, command-line arguments, logs, reports, and process-wide persistent environment variables.
- Store scheduled-execution secrets only in the FGOps Windows DPAPI `LocalMachine` store with inherited ACLs removed and access limited to `SYSTEM` and local Administrators.
- Treat DPAPI `LocalMachine` as machine binding, not as an authorization boundary by itself; NTFS ACL restriction is mandatory.
- Verify the FortiGate SSH host-key fingerprint through an independent trusted channel before configuring it.
- Restrict inbound TFTP UDP/69 to the FortiGate management source address and the dedicated VM interface.
- Require a non-empty encrypted full configuration backup before every package restore.
- Reject unknown package types by default.
- Preserve package and archive SHA-256 identity from download through TFTP staging.
- Never automate firmware downgrade, signature-verification bypass, wrong-firmware acceptance, or security-level reduction.
- Keep ISDB and Botnet excluded from unattended apply until independently validated for the target FortiOS branch.

## Execution-policy controls

- `prepare_only` must never perform a device-changing operation.
- `approval` requires an exact local manifest ID and may not silently fall through to unattended apply.
- `unattended` may be enabled only after at least one approval-mode live evidence set has been reviewed.
- Notification failure must be recorded and retried without changing package identity or bypassing apply gates.
- A changed host key, target identity mismatch, failed preflight, failed backup, missing expected object, or detected downgrade must fail closed.

## Evidence controls

- Keep configuration backups and production evidence outside GitHub unless separately approved and redacted.
- Protect the local evidence and report directories with host access controls and retention policy.
- Reports may contain production hostnames, IP addresses, versions, package names, and command output; handle them as operationally sensitive.
- Telegram messages must contain status and manifest metadata only, never credentials or full configuration content.

Security reports should be sent privately to the repository owner.
