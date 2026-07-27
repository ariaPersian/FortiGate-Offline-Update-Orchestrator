# Daily runtime logging

FGOps v0.5.5 writes one append-only UTF-8 log file per local calendar day for every `fgops-agent` command, including Scheduled Task `cycle` executions.

Daily logs provide an operator-facing execution journal. They supplement immutable manifests, state, JSON/TXT evidence, apply reports, and encrypted backups; they do not replace those artifacts.

## Location and naming

The default location is derived from the configured runtime storage root:

```text
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

Examples:

```text
C:\ProgramData\FGOps\logs\fgops-2026-07-27.log
C:\ProgramData\FGOps\logs\fgops-2026-07-28.log
```

The logger starts before the complete YAML configuration is loaded. With the normal configuration location `C:\ProgramData\FGOps\config.yml`, early configuration failures are therefore captured under the same runtime root.

If `storage.root` points elsewhere, logging relocates to `<storage.root>\logs` after configuration loads successfully. The relocation itself is recorded.

The handler checks the local date for every emitted record. A command that crosses midnight continues in the new day's file without requiring a service restart.

## Record format

Each line contains:

```text
<local ISO-8601 timestamp> <level> pid=<process-id> <structured JSON payload>
```

Example:

```text
2026-07-27T12:45:03+03:30 INFO pid=4216 {"command":"cycle","event":"command.started","config":"C:\\ProgramData\\FGOps\\config.yml"}
2026-07-27T12:45:11+03:30 INFO pid=4216 {"command":"cycle","event":"cycle.completed","exit_code":0,"result":{"status":"NO_CHANGE"}}
2026-07-27T12:45:11+03:30 INFO pid=4216 {"command":"cycle","event":"command.completed","exit_code":0}
```

The exact structured result can contain archive SHA-256 values, manifest IDs, package versions, report paths, backup paths, target identity, and error details.

## Recorded events

The daily journal includes:

- `command.started` and `command.completed`;
- source monitor and policy-cycle results;
- preflight, backup-test, controlled-apply, approval, and notification results;
- configuration validation and state-display actions;
- host-key scan metadata;
- secret-store metadata actions without plaintext values;
- `command.failed` with error type, message, and traceback.

Common result events include:

```text
config.initialized
config.validated
host_key.scanned
monitor.completed
cycle.completed
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

## Scheduled Task behavior

The Scheduled Task runs `fgops-agent ... cycle` as `SYSTEM`. It writes to the same daily file as foreground commands, so one date-named journal can contain multiple processes and both interactive and scheduled executions. The `pid=` field distinguishes them.

A successful Scheduled Task normally has:

```text
LastTaskResult : 0
```

The log should also contain a matching `command.completed` event with `exit_code: 0`.

Inspect the Task and today's log:

```powershell
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor" |
  Format-List LastRunTime,LastTaskResult,NextRunTime

$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log"
```

## Retention and log level

The default retention is 30 daily files. The oldest date-named files are removed when a new agent process starts or when the active date changes.

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

Supported standard log levels include `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`. Invalid values fall back to safe defaults and do not block the update workflow.

Retention deletion is best effort. An old log temporarily locked by an operator, antivirus tool, or backup process is left in place rather than blocking an update cycle.

## Validate logging

Run a harmless command:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Confirm today's file exists and has content:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
$LogPath = "C:\ProgramData\FGOps\logs\fgops-$Today.log"

Get-Item $LogPath |
  Select-Object FullName,Length,LastWriteTime

Get-Content $LogPath -Tail 20
```

`validate-config` also reports the resolved log directory:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  validate-config
```

## Operational commands

Display recent daily files:

```powershell
Get-ChildItem "C:\ProgramData\FGOps\logs" -Filter "fgops-*.log" |
  Sort-Object LastWriteTime -Descending |
  Select-Object Name,Length,LastWriteTime
```

Follow today's log:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log" -Wait
```

Search for failures:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-*.log" `
  -Pattern '"event": "command.failed"|"status": "FAILED"'
```

Search for one manifest:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-*.log" `
  -Pattern "FGOPS-0123456789ABCDEF"
```

Search for one package family:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-*.log" `
  -Pattern '"kind": "MMDB"|"kind": "FFDB"'
```

## Interpretation

Use the daily journal to answer:

- when a command started and ended;
- whether it ran interactively or through another process ID;
- what archive SHA-256 and manifest ID were processed;
- which package results were produced;
- which report and backup paths were written;
- what exit code the Scheduled Task received;
- what exception occurred before a report could be written.

Use the apply report and FortiGate `diagnose autoupdate versions` output for final package activation evidence. A daily log line showing TFTP success does not by itself prove database activation.

## Security boundary

Daily logs are runtime data and must remain outside Git. FGOps does not write plaintext secret values to command result events. Backup commands continue to use the existing redacted output path.

Operators must still treat logs as sensitive operational records because they can contain:

- device identity and management address;
- package versions and filenames;
- archive SHA-256 and manifest IDs;
- evidence, backup, quarantine, and report paths;
- failure details and tracebacks.

Restrict access to the runtime host, apply an approved retention policy, and remove or sanitize logs before sharing them outside the operational team. Never attach unsanitized production logs to a public issue or commit them to the repository.
