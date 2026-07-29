# Payload-level deduplication

FGOps v0.5.7 separates ZIP archive identity from the identity of the enabled FortiGuard package payload.

## Why archive SHA-256 is not sufficient

A publisher can regenerate a ZIP file with different container metadata, member timestamps, compression output, or comments while leaving every enabled `.pkg` file byte-for-byte unchanged. In that case the ZIP SHA-256 changes even though applying the bundle would repeat the same FortiGate database restores.

Repeated restores create unnecessary backups, SSH sessions, TFTP transfers, reports, and possible short scanning interruptions. Archive SHA-256 remains valuable for audit and exact-download deduplication, but it is no longer the only execution gate.

## Payload fingerprint

After safe extraction and package identification, FGOps calculates SHA-256 for every enabled package. It then builds a deterministic payload identity from sorted package-kind and package-hash pairs:

```text
APDB:<package-sha256>
AV:<package-sha256>
IPS:<package-sha256>
MCDB:<package-sha256>
MMDB:<package-sha256>
```

The SHA-256 of this canonical text is stored as `payload_sha256`.

Only package kinds present in `execution.enabled_packages` participate. An excluded package such as FFDB cannot force a live apply merely because its bytes or ZIP metadata changed.

## Decision flow

```text
Download ZIP
  -> calculate archive SHA-256
  -> exact archive already handled?
       yes: NO_CHANGE
       no: safely extract and hash enabled packages
  -> enabled payload matches a previously applied payload?
       yes: NO_CONTENT_CHANGE
            no SSH
            no FortiGate preflight
            no backup
            no TFTP server
            no restore
       no: PREPARED and continue according to execution.mode
```

The new archive is recorded with state `CONTENT_DUPLICATE`, including:

- its own archive SHA-256 and source path;
- the enabled `payload_sha256`;
- the original applied archive SHA-256;
- the original manifest ID when available;
- the planned enabled package kinds.

This preserves auditability while preventing device-changing work.

## Compatibility with existing state

Older state entries do not contain `payload_sha256`. When possible, FGOps reads the retained `manifest.json` from the prior work directory and reconstructs the enabled payload fingerprint from the package records. The recovered fingerprint is then persisted in state.

If the previous manifest is unavailable, FGOps cannot prove payload equality and fails safely by preparing the new archive normally. It never guesses that two payloads are equal.

## Operator log behavior

`NO_CONTENT_CHANGE` is an informational successful outcome. The operator journal records that the ZIP bytes changed but enabled package content did not, then marks preflight, backup, TFTP/apply, and postflight stages as safely skipped.

Package results with `SKIPPED_NO_UPDATE` are also informational rather than warnings. Package details are written as unnumbered child rows, so the main checklist remains a stable `1/N ... N/N` sequence.

## Security properties

- SHA-256 uses Python's `hashlib` implementation.
- Package hashes are calculated only after safe ZIP extraction.
- Unknown-package rejection remains unchanged.
- Package allowlisting remains authoritative.
- A changed enabled package hash still enters the normal preflight, mandatory backup, controlled apply, and version-verification path.
- Failed or review-required payloads are not treated as successfully applied payloads and are not silently replayed.
