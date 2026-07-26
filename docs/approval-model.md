# Approval model

FGOps treats approval as durable signed state, not as a long-running GitHub Actions job.

## Canonical state

Each approval is stored in the body of one private GitHub Issue. The human-readable status table is followed by a hidden Base64URL-encoded JSON envelope. The envelope contains:

- schema version and approval ID;
- repository and issue number;
- device name, expected model, and expected FortiOS build;
- source archive SHA-256 and immutable manifest ID;
- exact package filename-to-SHA-256 map;
- exact package allow-list and safe-package subset;
- authorized GitHub approvers;
- state, expiry, schedule, snooze, reminder, revision, and processed comment IDs.

The payload is authenticated with HMAC-SHA256 using the repository secret `FGOPS_APPROVAL_HMAC_KEY`. The secret is never stored in the issue or repository.

## State transitions

```text
AWAITING_APPROVAL
  |-- /fg snooze --> SNOOZED
  |-- /fg schedule --> SCHEDULED
  |-- /fg approve --> APPROVED
  |-- /fg apply-safe --> APPROVED with safe subset
  |-- /fg reject --> REJECTED
  `-- /fg cancel --> CANCELLED

SNOOZED --watchdog due--> AWAITING_APPROVAL
SCHEDULED --watchdog due--> APPROVED
non-approved state --expiry--> EXPIRED
APPROVED --/fg cancel--> CANCELLED
```

Firmware, downgrade, signature bypass, SSH, TFTP, and FortiGate restore operations are outside this milestone.

## Command durability and concurrency

GitHub Issue comments are the durable command queue. Every reconciliation run fetches the complete comment history, sorts commands by `(created_at, comment_id)`, and replays every unprocessed `/fg` command. Processed comment IDs are included in signed state.

This design provides:

- idempotency after retries;
- recovery when an intermediate workflow run is cancelled or never starts;
- deterministic reconstruction by the hourly watchdog;
- rejection and durable recording of invalid, unauthorized, stale, or expired commands.

Workflow concurrency serializes approval-state mutation. Even if GitHub replaces a pending run in a concurrency group, the next run reconciles the complete durable comment history rather than relying only on the triggering comment.

## Authorization

A command must satisfy both controls:

1. the comment association is one of `OWNER`, `MEMBER`, or `COLLABORATOR`;
2. the GitHub login is present in the signed approval record's approver list.

The exact approver list is bound when the approval issue is created. Editing visible issue text cannot modify signed authorization.

## Reminder and waiting behavior

The watchdog runs independently of user visits. It records reminder timestamps and counts in signed state to prevent duplicate notifications. Policy supports initial reminder intervals and a repeating interval.

A snoozed approval produces no reminder until its snooze deadline. A scheduled approval changes to `APPROVED` at its due time, but device execution remains a separate, currently disabled workflow.

## Secret generation

Generate at least 32 random bytes. One suitable PowerShell command is:

```powershell
$bytes = New-Object byte[] 48
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToBase64String($bytes)
```

Save the result as the private repository Actions secret `FGOPS_APPROVAL_HMAC_KEY`. Rotating the secret invalidates all outstanding approval issues; pending approvals must then be recreated.

## Fail-closed conditions

FGOps refuses state mutation when:

- the HMAC is absent or invalid;
- the issue contains duplicate or incomplete state blocks;
- repository or issue binding differs;
- an actor is not authorized;
- a command predates the current revision;
- an approval is expired or terminal;
- a schedule has no explicit UTC offset or is outside the approval lifetime;
- a snooze extends beyond expiry;
- a package allow-list or hash is changed without recreating the approval.
