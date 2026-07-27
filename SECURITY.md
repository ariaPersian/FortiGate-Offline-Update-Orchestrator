# Security policy

Do not publish credentials, private keys, FortiGate configuration backups, package files, bot tokens, production addresses, serial numbers, host-key fingerprints, or unredacted operational reports in issues, pull requests, Actions logs, or repository files.

## Security model

FGOps automates a privileged management path. Its controls reduce operational risk, but they do not establish the authenticity or compatibility of a third-party package publisher. A discovered link, successful HTTPS download, matching local SHA-256, or successful TFTP transfer does not prove that a package is appropriate for a specific FortiGate model and FortiOS branch.

## Deployment host

- Use a dedicated or tightly controlled, patched Windows VM.
- Limit interactive administration of the VM to authorized operators.
- Review the installed repository revision and configuration before allowing a Scheduled Task to run as `SYSTEM`.
- Keep the repository checkout read-only for ordinary runtime operations.
- Keep production runtime data under `C:\ProgramData\FGOps`, outside Git.
- Restrict the report, evidence, backup, state, quarantine, and secret directories according to organizational retention and access policy.

## Secrets

- Never store SSH passwords, private-key passphrases, backup encryption passwords, or notification tokens in YAML, Git, command-line arguments, reports, or persistent plaintext environment variables.
- Store scheduled-execution secrets only in the FGOps Windows DPAPI `LocalMachine` store.
- Remove inherited ACLs from the secret store and grant access only to `SYSTEM` and local Administrators.
- Treat DPAPI `LocalMachine` as machine binding, not as an authorization boundary: another sufficiently privileged process on the same machine may be able to decrypt machine-scoped data.
- Rotate a secret after suspected VM compromise, administrator misuse, accidental disclosure, or backup exposure.
- Do not copy the encrypted secret store to another machine as a credential-transfer method.

## FortiGate identity and access

- Verify the SSH host-key fingerprint through an independent trusted channel before pinning it.
- Configure the expected hostname, model, FortiOS branch, and build; a mismatch must fail closed.
- Use the least-privileged FortiGate administrator profile that still supports the required global-context backup and restore commands.
- Protect management interfaces with network controls independent of FGOps.
- Do not disable host-key verification or accept an unknown replacement key automatically.

## Package and source controls

- Treat every configured source and downloaded archive as untrusted input.
- Keep TLS verification enabled; use system or explicitly managed CA trust rather than `verify=false` behavior.
- Enforce download timeout and maximum size.
- Preserve archive and package SHA-256 identity from download through quarantine and TFTP staging.
- Reject path traversal, symlinks, duplicate package kinds, malformed archives, and unknown package types.
- Use `execution.enabled_packages` as the authoritative allowlist.
- Validate each package family against the exact target model and FortiOS branch before unattended use.
- Keep FFDB disabled by default on targets where FortiOS returns code `49` without an observed Internet-service database version increase.
- Keep Botnet and any unvalidated database family out of unattended apply.
- Never automate firmware downgrade, signature-verification bypass, wrong-firmware acceptance, or security-level reduction.

## Backup and TFTP controls

- Require a non-empty encrypted full-configuration backup before any package restore.
- Verify the permanent backup copy with SHA-256 before considering the backup gate complete.
- Bind TFTP only to the dedicated management-facing VM address.
- Restrict inbound UDP/69 to the FortiGate management source address using Windows Firewall or an equivalent network control.
- Start TFTP only for the active operation and remove the temporary run directory after a successful cycle.
- Remember that TFTP provides delivery, not confidentiality, authentication, or package authenticity.

## Execution-policy controls

- `prepare_only` must never perform a device-changing operation.
- `approval` must bind apply to the exact local manifest ID and hashes.
- Enable `unattended` only after the complete preflight, backup, restore, version comparison, postflight, evidence, and recovery paths have been reviewed.
- A changed host key, identity mismatch, failed preflight, failed mandatory backup, hash mismatch, detected downgrade, missing expected object, or unresolved package validation failure must fail closed.
- Do not automatically replay `APPLY_FAILED` or review-required archives.
- Schedule unattended live apply in a maintenance window appropriate to the environment.

## Evidence and privacy

- Treat JSON/TXT reports as operationally sensitive; they may contain hostnames, addresses, versions, package names, CLI output, and file paths.
- Keep configuration backups and production evidence out of the repository unless separately approved, encrypted, and redacted.
- Retain evidence long enough to support rollback analysis and incident review, but remove it according to policy.
- Notification messages must contain status and manifest metadata only, never secrets or configuration content.

## Reporting a vulnerability

Send security reports privately to the repository owner. Include the affected version, impact, reproduction steps, and a redacted proof of concept. Do not open a public issue for an unpatched vulnerability or include live credentials, backups, package files, or production evidence.
