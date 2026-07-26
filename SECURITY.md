# Security policy

Do not report credentials, private keys, FortiGate configuration backups, package files, or production IP details in public issues.

## Mandatory controls

- Keep the repository private while a self-hosted runner can reach management networks.
- Never run pull-request code on the network-capable runner.
- Store SSH credentials and notification tokens in GitHub Secrets or the runner credential store.
- Bind approvals to cryptographic hashes and expire them.
- Reject unknown package types by default.
- Never automate firmware downgrade, signature-verification bypass, or security-level reduction.

Security reports should be sent privately to the repository owner.
