# Security policy

Do not report credentials, private keys, FortiGate configuration backups, package files, or production IP details in public issues.

## Mandatory controls

- Keep the repository private while a self-hosted runner can reach management networks.
- Never run pull-request code on the network-capable runner.
- Store SSH credentials and notification tokens in GitHub Secrets or the runner credential store.
- Store `FGOPS_APPROVAL_HMAC_KEY` as a private repository Actions secret with at least 32 random bytes of entropy-equivalent material.
- Never print, upload, artifact, or place the approval HMAC key in an Issue, log, configuration file, or package manifest.
- Bind approvals to repository, issue, device, expected firmware, archive hash, manifest ID, package hashes, and an exact package allow-list.
- Expire approvals and reject stale, replayed, unauthorized, malformed, or tampered commands.
- Rotate the HMAC key after suspected disclosure; rotation intentionally invalidates every outstanding approval.
- Reject unknown package types by default.
- Never automate firmware downgrade, signature-verification bypass, or security-level reduction.

## Workflow controls

- Grant `GITHUB_TOKEN` only `contents: read` and `issues: write` where issue mutation is required.
- Keep approval workflows on the default branch; do not execute approval logic from unreviewed pull-request code.
- Upload only the manifest from the private runner. Package payloads, configurations, and captured production evidence must remain outside GitHub unless separately approved and redacted.
- Treat a signed-state verification failure as a security event and fail closed without attempting a device operation.

Security reports should be sent privately to the repository owner.
