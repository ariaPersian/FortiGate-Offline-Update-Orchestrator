# FGOps architecture

FGOps separates internet-facing package discovery from private-network execution.

1. A controlled station obtains an offline signature bundle.
2. The bundle enters quarantine and is inventoried by filename, size, SHA-256, and package type.
3. An immutable manifest is generated. Approval is bound to the manifest ID and hashes.
4. GitHub Issues provide the audit conversation and support `/fg` commands.
5. A private Windows self-hosted runner can access the TFTP host and FortiGate management interface.
6. The runner prepares a plan first. Applying packages remains disabled in v0.1.0.
7. Future apply jobs compare `diagnose autoupdate versions` before and after every package.

## Deferred approval model

FGOps does not keep a workflow job open while waiting for a person. Short event-driven jobs will persist and re-evaluate state.

Supported command grammar:

- `/fg approve`
- `/fg reject <reason>`
- `/fg snooze <duration>`
- `/fg schedule <ISO-8601 timestamp>`
- `/fg apply-safe`
- `/fg status`
- `/fg cancel`

An approval must bind to device identity, FortiOS build, bundle SHA-256, manifest SHA-256, and an exact package allow-list. Any change invalidates it.

The initial deferred-safe set is AV, IPS, APDB, FFDB, MCDB, and MMDB. ISDB and Botnet remain explicit because the validated FG-300D run produced package-specific `No updates`, code `-85`, and partial-success/code `49` behavior.

## FortiOS 6.4 result interpretation

| Evidence | Classification |
|---|---|
| Expected object version increases | `SUCCESS` |
| Version increases and CLI returns a non-zero code | `SUCCESS_WITH_WARNING` |
| TFTP succeeds, debug contains `No updates`, version remains equal | `SKIPPED_NO_UPDATE` |
| TFTP succeeds but the expected object does not increase | `FAILED_UNCONFIRMED` |
| Transfer or parsing fails | `FAILED` |

A successful TFTP transfer proves delivery only; it does not prove that a FortiGuard object was applied.

## Trust boundaries

- Third-party packages are untrusted until inventoried and approved.
- Pull-request CI runs only on GitHub-hosted runners.
- Network-capable workflows use dedicated labels and never run pull-request code.
- Firmware, engine upgrades, downgrade, and signature bypass are outside deferred auto-approval.
- TFTP is temporary and restricted to the management network; it is not an authenticity control.
