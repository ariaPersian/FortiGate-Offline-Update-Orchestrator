# FGOps architecture

FGOps v0.5.8 separates internet-facing bundle discovery from private-network FortiGate management while keeping the complete production runtime on one controlled Windows VM.

The authoritative source repository is `ariaPersian/FortiGate-Offline-Update-Orchestrator-Private`. GitHub hosts private source code, pull requests, and CI; GitHub is not in the production runtime data path and device access does not require a self-hosted runner.

## Runtime components

```text
Configured HTTPS source
        |
        v
Source monitor and retrying downloader
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
        |                                      +-> selected package transfers
        v
Before/after FortiGuard version comparison -> postflight -> JSON/TXT evidence
        |
        v
Operator journal + technical journal + lifecycle state

Read-only operator observation plane
        |
        +-> scripts/health_report.py
        +-> checkout/config/Task/state/evidence checks
        +-> pinned read-only FortiGate preflight
        +-> current-vs-last-apply version reconciliation
        +-> HEALTHY / WARNING / CRITICAL
        +-> reports/health TXT + JSON
```

Every `fgops-agent` invocation starts the daily journals before loading the full YAML configuration. This bootstrap path captures early configuration and command failures as well as normal Scheduled Task results.

The operator health script is outside the device-changing control plane. It observes existing state and can run the existing pinned read-only preflight, but it cannot approve a manifest, start a policy cycle, create a backup, restore a package, or change FortiGate configuration.

## Source and preparation plane

1. The agent fetches the configured source page using the selected TLS trust mode. Transient timeout and connection failures are retried with bounded exponential backoff; TLS validation and content-validation failures are not retried.
2. The link matcher evaluates the anchor, URL, and surrounding list-item context.
3. The selected archive is downloaded with timeout and maximum-size limits using the same bounded transient-error retry policy.
4. Archive identity is the downloaded SHA-256, not the URL, filename, or page timestamp.
5. Safe extraction rejects traversal, symlinks, malformed entries, and conflicting files that flatten to the same filename. Byte-identical duplicate members are retained once after SHA-256 verification and recorded as warnings.
6. Each package is recorded by kind, size, filename, SHA-256, restore family, expected FortiGuard objects, and deferred-apply eligibility. Exact `IGNORED` mappings remain audit-only; arbitrary `UNKNOWN` names still fail closed when configured.
7. Multiple candidates for an enabled package kind block preparation. Multiple candidates for a disabled kind remain in the manifest with a warning and cannot enter the apply plan.
8. An immutable manifest ID binds the prepared archive and package inventory. Controlled apply rechecks that every enabled kind resolves to at most one selected package.

A publisher may reuse a stable URL while replacing the ZIP. SHA-256 identity ensures the new content is still detected.

See [Source bundle ingestion](source-bundle-ingestion.md) for retry settings, package classifications, duplicate handling, and operator troubleshooting.

## Policy and state plane

The local state file records each archive lifecycle:

```text
new content
  -> PREPARED
  -> APPLIED

new archive bytes with an already-applied enabled payload
  -> CONTENT_DUPLICATE
  -> NO_CONTENT_CHANGE

PREPARED
  -> APPLY_FAILED
  -> REVIEW_REQUIRED
```

`cycle` obeys `execution.mode`:

- `prepare_only`: prepare and stop;
- `approval`: prepare and require the exact manifest ID;
- `unattended`: prepare or resume an eligible `PREPARED` archive and enter controlled apply.

Archives that failed apply or require review are not replayed automatically. State changes are written atomically. Manual state editing is an exceptional recovery action and must preserve the previous file as evidence.

The health report reads this state and marks unresolved `APPLY_FAILED` or `REVIEW_REQUIRED` entries as a failed health check. It does not alter the lifecycle state.

## Device execution plane

The device-changing path is deliberately narrow:

1. load required secrets from the local encrypted store;
2. validate the pinned SSH host key;
3. confirm expected hostname, model, FortiOS branch/build, VDOM mode, and HA state;
4. verify prepared package hashes;
5. create a per-run TFTP root and stage only selected package files;
6. start TFTP on the configured management-facing address and UDP/69;
7. export an encrypted full-configuration backup and verify its permanent SHA-256 copy;
8. restore enabled packages in deterministic order;
9. read `diagnose autoupdate versions` after each package;
10. stop on blocking failure when configured;
11. run postflight and write reports;
12. stop TFTP and clean the temporary root after a successful cycle;
13. persist lifecycle state and final journal results.

Only the standard FortiOS confirmation prompt is answered automatically. Signature errors, wrong-firmware warnings, downgrade indications, identity changes, backup failures, and hash mismatches fail closed.

## Read-only device observation plane

The health script can enter only the existing pinned read-only preflight path.

The allowlist is limited to:

```text
get system status
diagnose autoupdate versions
diagnose sys flash list
diagnose debug config-error-log read
diagnose autoupdate signature check-all
```

It reuses DPAPI secret loading only for the SSH credential needed by the read-only preflight. It cannot call `FortiGateApplySession`, cannot start the temporary TFTP service, cannot issue `execute backup`, and cannot issue `execute restore`.

This separation is important: a health check must never become an implicit remediation or update operation.

## Package selection

Package selection has two independent stages:

1. the manifest records packages found in the ZIP;
2. `execution.enabled_packages` decides which recorded packages may be restored.

`apply.package_order` only sorts packages that already passed the allowlist. Presence in a manifest does not imply installation.

Validated package order:

```text
AV -> IPS -> APDB -> MCDB -> MMDB
```

The validated end-to-end cycle completed as `SUCCESS_WITH_WARNING`: AV, IPS, APDB, and MCDB were already current, while MMDB increased from `93.07607` to `93.07613`.

FFDB is target-specific. On the validated FortiGate 300D/FortiOS 6.4.16 deployment, the tested third-party FFDB package transferred successfully but was rejected with return code `49` and no expected Internet-service database version increase. The recommended default therefore excludes FFDB.

## Result model

| Evidence | Classification |
|---|---|
| Expected object version increases | `SUCCESS` |
| Version increases despite a non-zero FortiOS code or warning | `SUCCESS_WITH_WARNING` |
| FortiGate explicitly reports successful transfer and versions are already current | `SKIPPED_NO_UPDATE` |
| Expected object is missing or unchanged without a trusted successful-transfer outcome | `FAILED_UNCONFIRMED` |
| Version decreases or a blocking validation/backup/identity error occurs | `FAILED` |

A successful TFTP transfer proves delivery only. It does not prove that FortiOS accepted, parsed, and activated the database.

The operator health report does not redefine these classifications. Its `HC-20` only compares current observed FortiGuard versions with the object versions retained in the latest apply report and surfaces a health inconsistency when current evidence is older or cannot be reconciled.

## Health-result model

Health results are independent from cycle/package classifications:

| Health state | Exit | Definition |
|---|---:|---|
| `HEALTHY` | `0` | No `FAIL` and no `WARN` health checks |
| `WARNING` | `1` | No `FAIL`, at least one `WARN` |
| `CRITICAL` | `2` | At least one `FAIL` |

`INFO` checks do not change the overall health state.

The health script is intended for normal production state. A deliberately disabled Scheduled Task is therefore a failed health check; maintenance procedures must record that intentional state separately and rerun health after scheduling is restored.

## FFDB return code 49

The FFDB guard remains fail closed:

```text
FFDB restore returns 49
  -> do not submit a second FFDB package
  -> poll expected Internet-service database versions
  -> continue only if a version change is observed
  -> otherwise retain failure/review evidence
```

The polling window can be overridden for controlled diagnostics. A timeout does not convert return code `49` into success.

## Operational audit and health plane

Daily journals:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

On-demand health evidence:

```text
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.txt
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.json
```

The operator journal records readable per-run state. The technical journal records structured command events and exceptions. The health report aggregates current operational state across checkout, config, Task Scheduler, lifecycle state, retained evidence, and read-only FortiGate observations.

Health reporting is intentionally non-remediating. A failed health check produces evidence and an exit code; it does not mutate package policy, repair state, restart a Task, or submit a package.

`FGOPS_LOG_RETENTION_DAYS` applies to the date-named operator and technical journals. Timestamped health reports require a separate retention policy.

## Trust boundaries

- The configured publisher and package files are outside the FGOps trust boundary.
- TLS authenticates the configured web endpoint according to the selected trust store; it does not establish package compatibility.
- SHA-256 establishes local content identity; it does not establish publisher authenticity.
- Windows DPAPI machine scope binds ciphertext to the machine; restrictive ACLs remain mandatory.
- SSH host-key pinning authenticates the configured management endpoint.
- TFTP is a temporary transport on the management network and is not an authenticity or confidentiality control.
- Health reports, JSON/TXT apply reports, backups, state, quarantine data, evidence, and daily logs are operationally sensitive and remain outside Git.
- The private Git repository is a development and release-control boundary, not a runtime secret or evidence store.
- The public development repository must not be treated as the production source of truth merely because the health script exists there.

## Explicit non-goals

FGOps does not automate FortiOS firmware upgrade or downgrade, engine replacement, signature-verification bypass, wrong-platform acceptance, security-level reduction, arbitrary FortiGate CLI execution, or automatic remediation of health-report failures.

## Related documentation

- [Operator health report](operator-health-report.md)
- [Production operations](operations.md)
- [Operator checklist logging](operator-checklist-logging.md)
- [Daily runtime logging](daily-runtime-logging.md)
- [Read-only preflight](read-only-preflight.md)
- [Controlled apply](controlled-apply.md)
- [Private repository synchronization](private-repository-sync.md)
