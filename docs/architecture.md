# FGOps architecture

FGOps separates internet-facing bundle discovery from private-network FortiGate management while keeping the complete production runtime on one controlled Windows VM.

## Runtime components

```text
Configured HTTPS source
        |
        v
Source monitor and downloader
        |
        v
Incoming archive -> quarantine -> package inventory -> immutable manifest
        |                                            |
        |                                            v
        |                                  local JSON state machine
        v
Policy cycle: prepare_only / approval / unattended
        |
        v
DPAPI secret loader -> pinned SSH preflight -> temporary TFTP
        |                                      |
        |                                      +-> encrypted full-config backup
        |                                      +-> selected package downloads
        v
Before/after FortiGuard version comparison -> postflight -> JSON/TXT evidence
```

GitHub hosts source code, pull requests, and CI. GitHub is not in the runtime data path, and production device access does not require a self-hosted GitHub runner.

## Source and preparation plane

1. The agent downloads the configured source page using the selected TLS trust mode.
2. The link matcher evaluates the anchor, URL, and surrounding list-item context.
3. The selected archive is downloaded with timeout and maximum-size limits.
4. Archive identity is the downloaded SHA-256, not the URL, filename, or web-page timestamp.
5. Safe extraction rejects traversal, symlinks, duplicate package kinds, malformed entries, and unknown packages when configured to fail closed.
6. Each package is recorded by kind, size, filename, SHA-256, restore family, expected FortiGuard objects, and deferred-apply eligibility.
7. An immutable manifest ID binds the prepared archive and package inventory.

A publisher may reuse a stable URL while replacing the ZIP. SHA-256 identity ensures the new content is still detected.

## Policy and state plane

The local state file records each archive lifecycle:

```text
new content
  -> PREPARED
  -> APPLIED

PREPARED
  -> APPLY_FAILED
  -> review-required state
```

`cycle` always obeys `execution.mode`:

- `prepare_only`: prepare and stop;
- `approval`: prepare and require the exact manifest ID;
- `unattended`: prepare or resume an eligible `PREPARED` archive and enter controlled apply.

Archives that failed apply or require review are not replayed automatically. State changes are written atomically. Manual state editing is an exceptional recovery action and must preserve the previous file as evidence.

## Device execution plane

The device-changing path is deliberately narrow:

1. load the required secrets from the local encrypted store;
2. validate the pinned SSH host key;
3. confirm expected hostname, model, FortiOS branch/build, VDOM mode, and HA state;
4. verify prepared package hashes;
5. create a per-run TFTP root and stage only the selected package files;
6. start TFTP on the configured management-facing address and UDP/69;
7. export an encrypted full-configuration backup and verify its permanent SHA-256 copy;
8. restore enabled packages in deterministic order;
9. read `diagnose autoupdate versions` after each package;
10. stop on blocking failure when configured;
11. run postflight and write reports;
12. stop TFTP and clean the temporary root after a successful cycle.

Only the standard FortiOS confirmation prompt is answered automatically. Signature errors, wrong-firmware warnings, downgrade indications, identity changes, backup failures, and hash mismatches fail closed.

## Package selection

Package selection has two independent stages:

1. the manifest records packages found in the ZIP;
2. `execution.enabled_packages` decides which recorded packages may be restored.

`apply.package_order` only sorts packages that already passed the allowlist. Presence in `planned_packages` does not imply installation.

The validated unattended profile is:

```text
AV -> IPS -> APDB -> MCDB -> MMDB
```

FFDB is optional and target-specific. On the validated FortiGate 300D/FortiOS 6.4.16 deployment, the tested third-party FFDB package transferred successfully but was rejected with return code `49` and no Internet-service database version increase. The recommended default therefore excludes FFDB.

## Result model

| Evidence | Classification |
|---|---|
| Expected object version increases | `SUCCESS` |
| Version increases despite a non-zero FortiOS code or warning | `SUCCESS_WITH_WARNING` |
| FortiGate explicitly reports successful transfer and versions are already current | `SKIPPED_NO_UPDATE` |
| Expected object is missing or unchanged without a trusted successful-transfer outcome | `FAILED_UNCONFIRMED` |
| Version decreases or a blocking validation/backup/identity error occurs | `FAILED` |

A successful TFTP transfer proves delivery only. It does not prove that FortiOS accepted, parsed, and activated the database.

## FFDB return code 49

FGOps v0.5.4 contains a bounded FFDB-specific guard:

```text
FFDB restore returns 49
  -> do not submit a second FFDB package
  -> poll Internet-service Database Apps/Maps versions every 30 seconds
  -> wait up to 30 minutes by default
  -> continue only if a version change is observed
  -> otherwise retain a fail-closed result
```

The polling window can be overridden for controlled diagnostics through `FGOPS_FFDB_MAX_WAIT_SECONDS` and `FGOPS_FFDB_POLL_SECONDS`. A timeout does not convert code `49` into success.

## Trust boundaries

- The configured publisher and package files are outside the FGOps trust boundary.
- TLS authenticates the configured web endpoint according to the selected trust store; it does not establish FortiGate package compatibility.
- SHA-256 establishes local content identity; it does not establish publisher authenticity.
- Windows DPAPI machine scope binds ciphertext to the machine; restrictive ACLs remain mandatory.
- SSH host-key pinning authenticates the configured management endpoint.
- TFTP is a temporary transport on the management network and is not an authenticity or confidentiality control.
- JSON/TXT reports, backups, state, and quarantine data are operationally sensitive and remain outside Git.

## Explicit non-goals

FGOps does not automate FortiOS firmware upgrade or downgrade, engine replacement, signature-verification bypass, wrong-platform acceptance, security-level reduction, or arbitrary FortiGate CLI execution.
