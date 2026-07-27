# Daily runtime logging

FGOps writes one append-only UTF-8 log file per local calendar day for every `fgops-agent` command, including Scheduled Task `cycle` executions.

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

The handler checks the local date for every emitted record. A command that crosses midnight continues in the new day's file without requiring a long-running process or service restart.

## Recorded events

The daily journal includes:

- command start and exit code;
- source-monitor and policy-cycle results;
- preflight, backup-test, controlled-apply, approval, and notification results;
- configuration validation and state-display actions;
- secret-store metadata actions without plaintext values;
- unhandled exceptions with a traceback.

Each event is timestamped with the local UTC offset and includes the process ID. Structured result payloads are serialized as JSON inside the log record.

## Retention and log level

The default retention is 30 daily files. The oldest date-named files are removed when a new agent process starts or when the active date changes.

Optional process or machine environment variables:

```text
FGOPS_LOG_RETENTION_DAYS=30
FGOPS_LOG_LEVEL=INFO
```

Supported standard log levels include `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`. Invalid values fall back to safe defaults and do not block the update workflow.

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

## Security boundary

Daily logs are runtime data and must remain outside Git. FGOps does not write plaintext secret values to command result events. Backup commands continue to use the existing redacted output path. Operators should still treat logs as sensitive operational records because they can contain device identity, paths, package versions, manifest IDs, and error details.
