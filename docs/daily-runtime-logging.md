# Daily runtime logging

FGOps v0.5.8 writes two append-only UTF-8 journals per local calendar day for every installed `fgops-agent` command, including Scheduled Task `cycle` executions.

The two files serve different audiences:

| File | Audience | Primary purpose |
|---|---|---|
| `fgops-operator-YYYY-MM-DD.log` | Operations staff | Human-readable ToDo checklist, step results, final status, exit code, and suggested action |
| `fgops-YYYY-MM-DD.log` | Technical support | Structured JSON events, complete result payloads, exceptions, and tracebacks |

The journals supplement immutable manifests, lifecycle state, JSON/TXT evidence, apply reports, and encrypted backups. They do not replace those artifacts.

## Location and naming

The default location is derived from the configured runtime storage root:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

Examples:

```text
C:\ProgramData\FGOps\logs\fgops-operator-2026-07-28.log
C:\ProgramData\FGOps\logs\fgops-2026-07-28.log
```

Logging starts before the complete YAML configuration is loaded. With the normal configuration location `C:\ProgramData\FGOps\config.yml`, early configuration failures are captured under the same runtime root.

When `storage.root` points elsewhere, both loggers relocate to `<storage.root>\logs` after configuration loads successfully. The operator journal records the relocation as a readable step message, while the technical journal records the corresponding structured event.

Both handlers check the local date for every emitted record. A command that crosses midnight continues in the new day's files without requiring a service restart.

## Operator journal

The operator journal is the first file a non-technical operator should inspect.

At the start of each run, FGOps writes:

- the command name;
- a unique run identifier;
- the complete planned ToDo list;
- one `⬜` row for every planned step.

As execution proceeds, each row is updated through additional log lines:

| Symbol | State | Interpretation |
|---|---|---|
| `⬜` | ToDo | Planned and not yet completed |
| `🔄` | Running | Currently being processed |
| `✅` | Success | Completed successfully |
| `⚠️` | Warning | Completed with a warning or requires operator attention |
| `❌` | Failed | Failed or blocked by a mandatory gate |
| `⏭️` | Skipped | Safely not required for this execution path |

The end of every completed run contains:

- a final summary of all steps;
- the overall result;
- the process exit code;
- an operator action when review, approval, or troubleshooting is required.

Controlled apply and approval runs add one row per package result. This lets the operator distinguish, for example, a successful AV update from an already-current MMDB package or a failed IPS activation.

See [Operator checklist logging](operator-checklist-logging.md) for examples and the response procedure.

## Technical journal format

Each technical line contains:

```text
<local ISO-8601 timestamp> <level> pid=<process-id> <structured JSON payload>
```

Example:

```text
2026-07-28T12:45:03+04:00 INFO pid=4216 {"command":"cycle","event":"command.started","config":"C:\\ProgramData\\FGOps\\config.yml"}
2026-07-28T12:45:11+04:00 INFO pid=4216 {"command":"cycle","event":"cycle.completed","exit_code":0,"result":{"status":"NO_CHANGE"}}
2026-07-28T12:45:11+04:00 INFO pid=4216 {"command":"cycle","event":"command.completed","exit_code":0}
```

The structured result can contain archive SHA-256 values, manifest IDs, package versions, report paths, backup paths, target identity, notification results, and error details.

Common technical events include:

```text
command.started
command.completed
command.failed
config.initialized
config.validated
host_key.scanned
monitor.completed
cycle.completed
source.retrying
preflight.completed
backup_test.completed
apply.completed
approval.completed
state.displayed
secret.updated
secret.deleted
secret.status
notification.test_completed
```

`command.failed` includes the error type, message, and traceback. Secret-store events include metadata only and do not intentionally expose plaintext values.

`source.retrying` is written at warning level before a bounded retry of `fetch_source_page` or `download_bundle`. It records the completed attempt, next attempt, maximum attempts, delay, and exception. Its presence alone is not a failed cycle; correlate it with the final `cycle.completed` or `command.failed` event. TLS validation and content-validation failures are not retried. See [Source bundle ingestion](source-bundle-ingestion.md).

## Relationship between both files

The operator and technical journals are complementary, not duplicates.

Use the operator file to answer:

- Did the run complete?
- Which step is still pending, safely skipped, warning, or failed?
- Did a new package require approval?
- Was a backup created?
- Which package needs attention?
- What should the operator do next?

Use the technical file to answer:

- Which exact structured result was returned?
- What manifest ID, SHA-256, package filename, version, or report path was involved?
- Which exception and traceback caused the failure?
- What exit code did the Scheduled Task receive?

The shared local date, command, timestamp, package name, manifest ID, and run timing make it possible to correlate the readable checklist with the detailed technical events.

## Scheduled Task behavior

The Scheduled Task runs `fgops-agent ... cycle` as `SYSTEM`. Foreground and scheduled executions append to the same pair of date-named files.

A successful Task Scheduler invocation normally reports:

```text
LastTaskResult : 0
```

The operator journal should show a matching final result with exit code `0`. The technical journal should contain a matching `command.completed` event with `exit_code: 0`.

Inspect the Task and both logs:

```powershell
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor" |
  Format-List LastRunTime,LastTaskResult,NextRunTime

$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log" -Tail 100
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log" -Tail 100
```

## Retention and log level

The default retention is 30 date-named files **for each log type**. Expired operator files and expired technical files are removed independently.

Optional process or machine environment variables:

```text
FGOPS_LOG_RETENTION_DAYS=30
FGOPS_LOG_LEVEL=INFO
```

Set machine-wide values from elevated PowerShell:

```powershell
[Environment]::SetEnvironmentVariable(
  "FGOPS_LOG_RETENTION_DAYS",
  "30",
  "Machine"
)

[Environment]::SetEnvironmentVariable(
  "FGOPS_LOG_LEVEL",
  "INFO",
  "Machine"
)
```

`FGOPS_LOG_LEVEL` controls the technical logger. Supported values include `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`. Invalid values fall back to `INFO` and do not block the update workflow.

The operator journal remains an INFO-level operational checklist so normal step transitions are not hidden by technical verbosity settings.

Retention deletion is best effort. A log temporarily locked by an operator, antivirus tool, collector, or backup process is left in place rather than blocking an update cycle.

## Validate the installed logging entry point

The operator journal is implemented by the installed `fgops-agent` console entry point. After upgrading, reinstall the project into the virtual environment before validation. The current expected version is `0.5.8`:

```powershell
Set-Location C:\FGOps

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --force-reinstall --no-deps C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

Run a harmless command:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Confirm both files exist and contain the same execution period:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"
$TechnicalLog = "C:\ProgramData\FGOps\logs\fgops-$Today.log"

Get-Item $OperatorLog,$TechnicalLog |
  Select-Object FullName,Length,LastWriteTime

Get-Content $OperatorLog -Tail 50
Get-Content $TechnicalLog -Tail 20
```

A valid operator entry contains `فهرست مراحل (ToDo):` and `نتیجه نهایی:`. A valid technical entry contains `command.started` and `command.completed` or `command.failed`.

## Operational commands

Follow the operator journal:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log" -Wait
```

Follow the technical journal:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log" -Wait
```

Display warning and failed operator rows:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "⚠️|❌"
```

Display final operator results:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "نتیجه نهایی:"
```

Search technical logs for failures:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-*.log" `
  -Pattern '"event": "command.failed"|"status": "FAILED"'
```

Search for one manifest:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\*.log" `
  -Pattern "FGOPS-0123456789ABCDEF"
```

Search for one package family:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\*.log" `
  -Pattern "MMDB|FFDB"
```

## Interpretation limits

The journals describe orchestration and evidence paths; they do not independently prove FortiGuard database activation.

Use the apply report and FortiGate `diagnose autoupdate versions` output for final package activation evidence. A TFTP success line proves file delivery only. The result remains failed or unconfirmed when expected object versions do not change and no trusted already-current outcome applies.

## Security boundary

Both log types are runtime data and must remain outside Git. FGOps does not intentionally write plaintext secret values to either journal. Backup command output continues to use the existing redacted path.

Treat both files as sensitive operational records because they can contain:

- device identity and management address;
- source URLs;
- package versions and filenames;
- archive SHA-256 and manifest IDs;
- evidence, backup, quarantine, and report paths;
- notification status;
- failure details and tracebacks.

Restrict access to the runtime host, apply an approved retention policy, and sanitize logs before sharing them outside the authorized operations team. Never attach unsanitized production logs to a public issue or commit them to the repository.
