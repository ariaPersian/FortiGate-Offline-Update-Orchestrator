# Source bundle ingestion

FGOps v0.5.8 treats every source page, download, ZIP member, filename, and package-map match as untrusted input. Preparation may write only to local runtime storage; it does not open SSH, start TFTP, create a FortiGate backup, or restore a package.

This runbook documents the source behavior added after the August 2026 production logs showed intermittent HTTP timeouts, byte-identical duplicate ZIP members, and an older `64...` package set bundled beside the current publisher-prefixed set.

## Source retry policy

Configure bounded retries in the production YAML:

```yaml
source:
  timeout_seconds: 60
  retry_attempts: 3
  retry_backoff_seconds: 2
```

`retry_attempts` is the total number of attempts, including the first one, and must be between `1` and `5`. `retry_backoff_seconds` must be between `0` and `60`. The delay before the next attempt is:

```text
retry_backoff_seconds * 2 ** (failed_attempt - 1)
```

With the default values, a transient failure waits 2 seconds before attempt 2 and 4 seconds before attempt 3. Page fetch and bundle download have independent retry budgets.

Only transient timeout and connection failures are retried. TLS validation failures, an ambiguous or missing page link, size-limit violations, malformed archives, and package-validation failures stop immediately. Retrying cannot weaken certificate validation or convert invalid content into accepted content.

Every scheduled retry writes a `source.retrying` event to the technical journal with:

- `operation`: `fetch_source_page` or `download_bundle`;
- `attempt`, `next_attempt`, and `max_attempts`;
- `delay_seconds`;
- `error_type` and `error`.

## ZIP extraction rules

Only `.pkg` members are extracted. Directory structure inside the ZIP is removed, so uniqueness is evaluated using the case-insensitive flattened filename.

| ZIP condition | Decision | Evidence |
|---|---|---|
| Absolute path, `..` traversal, or symbolic link | Reject archive | Exception in technical journal |
| No `.pkg` member | Reject archive | Exception in technical journal |
| Same flattened filename and identical SHA-256 | Keep one copy | Manifest warning records the ignored duplicate member |
| Same flattened filename and different SHA-256 | Reject archive | Conflict identifies both ZIP member paths |

Filename deduplication is separate from package-kind uniqueness. Two differently named files can still map to the same package kind.

## Package classifications

The package map classifies every extracted filename before an apply plan is created:

| Classification | Manifest | Apply eligibility | Failure behavior |
|---|---|---|---|
| Known and enabled | Full record | Eligible when `safe_for_deferred_apply` is true | More than one candidate for the kind blocks preparation |
| Known but disabled | Full record | Never planned | Multiple candidates are retained with an audit warning |
| `IGNORED` | Full record and warning | Never approvable, planned, or restored | The mapping must be exact and cannot be marked safe for deferred apply |
| `UNKNOWN` | Full record and warning | Never planned | Blocks preparation when `reject_unknown_packages: true` |

`IGNORED` is not a general allow-unknown switch. In the supplied FortiOS 6.4 package map it applies only to these exact, case-insensitive legacy names:

```text
64Antivirus.pkg
64Application-Control.pkg
64Botnet-Domain.pkg
64Industrial-DB.pkg
64Internet-Service.pkg
64IPS.pkg
64MCDB.pkg
64Mobile-Malware.pkg
```

The records remain in `manifest.json` with their size and SHA-256 for audit, but have no restore family and cannot enter approval or controlled apply. A new or renamed publisher file does not inherit this treatment; it remains `UNKNOWN` until the package map is deliberately reviewed and changed.

Keep this production default:

```yaml
execution:
  enabled_packages: [AV, IPS, APDB, MCDB, MMDB]
  reject_unknown_packages: true
```

The BOTNET rule is bounded to the filename token `Botnet-Domain.pkg`; text appearing elsewhere in a filename must not cause an accidental BOTNET classification.

## Uniqueness gates

Preparation requires no more than one candidate for each kind in `execution.enabled_packages`. Disabled kinds may occur more than once because none can be selected, but the manifest records every candidate and emits a warning.

Controlled apply repeats the enabled-kind uniqueness check against the saved manifest before package hashing, SSH, backup, TFTP, or restore. A modified or incompatible manifest therefore fails before device-changing work.

## Archive and payload deduplication

The agent applies two independent identity checks:

1. An archive SHA-256 already recorded as handled returns `NO_CHANGE`. This includes failed or review-required archives so the same bytes cannot be replayed unattended.
2. New ZIP bytes whose enabled package-kind/SHA-256 payload matches a previously applied payload return `NO_CONTENT_CHANGE` and are recorded as `CONTENT_DUPLICATE`.

Both results avoid SSH, backup, TFTP, and restore. `IGNORED`, `UNKNOWN`, and disabled families do not contribute to `payload_sha256`; only the exactly planned enabled package set does. See [Payload-level deduplication](payload-deduplication.md) for state compatibility and payload fingerprint construction.

## Validate an upgrade

Keep the Scheduled Task disabled while validating v0.5.8:

```powershell
& C:\FGOps\venv\Scripts\python.exe -m pip show fgops

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  validate-config

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  run --dry-run

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Confirm the installed version is `0.5.8`. An acceptable preparation-plane result is `PREPARED`, `NO_CHANGE`, or `NO_CONTENT_CHANGE`; a source or inventory exception is not acceptable. `NO_CHANGE` does not erase prior lifecycle state, so do not re-enable scheduling while `status` shows an unresolved `APPLY_FAILED` or `REVIEW_REQUIRED` archive.

For a newly prepared archive, inspect `<work_dir>\manifest.json` and `<work_dir>\agent-plan.json`:

- `planned_packages` contains only the intended enabled kinds;
- every `IGNORED` record is an expected exact legacy filename;
- there are no `UNKNOWN` records;
- duplicate-member and disabled-kind warnings match the ZIP contents;
- every planned kind appears exactly once.

`run --dry-run` stops in the preparation plane. It does not test pinned SSH, backup, TFTP, or package activation.

## Troubleshooting decisions

| Symptom | Meaning | Operator action |
|---|---|---|
| `source.retrying` followed by success | A transient source failure recovered | Record the recurrence; no manual rerun is needed |
| Final timeout or connection exception | All configured attempts failed | Keep scheduling disabled if failures persist; verify DNS, route, proxy, and source availability |
| `Conflicting package files share the same flattened filename` | Same output name has different bytes | Preserve the ZIP and log; do not rename or choose one manually |
| `Enabled package kind ... is ambiguous` | More than one candidate could be restored | Review the publisher bundle and package map; do not bypass the gate |
| `Unknown package types were found` | A name has no reviewed mapping | Keep `reject_unknown_packages: true`; review provenance and compatibility before changing the map |
| Expected legacy file appears as `UNKNOWN` | The filename is not one of the exact exclusions | Treat it as a publisher change and review it; do not broaden the regex casually |

Preparation failures occur before device access. Preserve the source ZIP, technical log, and any generated quarantine evidence before changing the package map or retrying.

## Package-map change control

Treat the package map as executable policy:

1. collect the exact publisher filename and SHA-256;
2. establish which FortiOS restore family and FortiGuard objects apply;
3. verify compatibility with the exact FortiGate model and FortiOS build;
4. use anchored, non-overlapping regex rules;
5. add positive, ambiguity, and near-match tests;
6. run the full test suite and a foreground dry run;
7. review the manifest before any approval-mode apply.

Never convert a broad prefix or all unknown files to `IGNORED` merely to make preparation pass.
