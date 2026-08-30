# Daily runtime logging

FGOps v0.5.8 writes two append-only UTF-8 journals per local calendar day for every installed `fgops-agent` command, including Scheduled Task `cycle` executions.

The operator-health update adds a separate timestamped health-report layer. The three evidence views serve different purposes:

| Artifact | Audience | Primary purpose |
|---|---|---|
| `fgops-health-*.txt/.json` | Operator / support | Consolidated current health across checkout, runtime, Task, state, evidence, and read-only FortiGate checks |
| `fgops-operator-YYYY-MM-DD.log` | Operations staff | Human-readable per-run ToDo checklist, step results, final status, exit code, and suggested action |
| `fgops-YYYY-MM-DD.log` | Technical support | Structured JSON events, complete result payloads, exceptions, and tracebacks |

The health report is a snapshot generated on demand. The journals are append-only execution histories. Neither replaces immutable manifests, lifecycle state, apply reports, preflight evidence, encrypted backups, or FortiGate version evidence.

See [Operator health report](operator-health-report.md) for the health-check contract and [Operator checklist logging](operator-checklist-logging.md) for the operator procedure.

## Location and naming

Daily journals:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

On-demand health reports:

```text
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.txt
C:\ProgramData\FGOps\reports\health\fgops-health-YYYYMMDD-HHMMSS.json
```

Logging starts before the complete YAML configuration is loaded. With the normal configuration path `C:\ProgramData\FGOps\config.yml`, early configuration failures are captured under the same runtime root.

When `storage.root` points elsewhere, both runtime loggers relocate to `<storage.root>\logs` after configuration loads successfully.

Both handlers check the local date for every emitted record. A command that crosses midnight continues in the new day's files without requiring a restart.

## Operator journal

At the start of each `fgops-agent` run, the operator journal writes:

- the command name;
- a unique run identifier;
- the complete planned ToDo list;
- one `⬜` row for every planned step.

As execution proceeds, each step is recorded with a fixed status symbol:

| Symbol | State | Interpretation |
|---|---|---|
| `⬜` | ToDo | Planned and not yet completed |
| `🔄` | Running | Currently being processed |
| `✅` | Success | Completed successfully |
| `⚠️` | Warning | Completed with a warning or requires operator attention |
| `❌` | Failed | Failed or blocked by a mandatory gate |
| `⏭️` | Skipped | Safely not required for this execution path |

The end of every normally completed run contains:

- a summary of the run steps;
- the overall result;
- the process exit code;
- an operator action when review, approval, or troubleshooting is required.

Controlled apply and approval runs add one row per package result.

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

`source.retrying` records a bounded retry of source-page or bundle-download operations. Its presence alone is not a failed cycle; correlate it with the final `cycle.completed` or `command.failed` event.

## Health report relationship to the journals

The on-demand health script reads or validates information across several sources:

- Git remote, branch, and working tree;
- source and installed package version;
- production configuration and safety policy;
- secret-store metadata;
- Scheduled Task state, action, last result, and schedule;
- lifecycle state;
- latest operator-cycle result;
- latest retained encrypted backup;
- latest apply report;
- UDP/69 listener state;
- runtime free space;
- pinned read-only FortiGate preflight;
- current FortiGuard versions against the latest apply evidence.

Run it with:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

The health report does not parse the technical log to determine package activation. Apply reports and FortiGate version evidence remain authoritative.

The health script does not execute `cycle`, `approve`, `apply`, `backup-test`, or any restore operation. Its only active device operation is the existing pinned read-only preflight.

## Scheduled Task behavior

The production Scheduled Task runs `fgops-agent ... cycle` as `SYSTEM`. Foreground and scheduled executions append to the same pair of date-named journals.

A successful Task Scheduler invocation normally reports:

```text
LastTaskResult : 0
```

The operator journal should show a matching final result. The health report also checks the Task state, last result, next run, executable, production config path, and `cycle` action.

A deliberately disabled Task is considered unhealthy in normal-state health reporting. During maintenance, record the authorized disabled state and rerun the complete health report after scheduling is restored.

## Retention and log level

The default retention is 30 date-named files for **each daily log type**.

Optional machine/process environment variables:

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

`FGOPS_LOG_LEVEL` controls the technical logger. The operator journal remains an INFO-level operational checklist.

Health reports under `reports\health` are **not** deleted by `FGOPS_LOG_RETENTION_DAYS`. They are timestamped operational evidence and require a separate organizational retention policy.

Retention deletion for daily logs is best effort. A file temporarily locked by an operator, antivirus product, collector, or backup process is left in place rather than blocking an update cycle.

## Validate the installed logging and health entry points

After upgrading, reinstall the checked-out project into the virtual environment before validation. The current documentation baseline remains `0.5.8`:

```powershell
Set-Location C:\FGOps

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --force-reinstall --no-deps C:\FGOps

& C:\FGOps\venv\Scripts\python.exe -m pip show fgops
```

Run a harmless installed-agent command:

```powershell
& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Confirm both daily files exist:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"
$TechnicalLog = "C:\ProgramData\FGOps\logs\fgops-$Today.log"

Get-Item $OperatorLog,$TechnicalLog |
  Select-Object FullName,Length,LastWriteTime
```

A valid operator entry contains `فهرست مراحل (ToDo):` and `نتیجه نهایی:`. A valid technical entry contains `command.started` and `command.completed` or `command.failed`.

After normal scheduling has been restored, run the health report:

```powershell
& "C:\FGOps\venv\Scripts\python.exe" `
  "C:\FGOps\scripts\health_report.py"
```

Confirm the generated TXT and JSON paths are printed and exist below `C:\ProgramData\FGOps\reports\health`.

## Operational log commands

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

## Interpretation limits

The journals and health report describe orchestration state and evidence paths; they do not independently prove package activation.

Use the apply report and current FortiGate `diagnose autoupdate versions` evidence for final package activation. A successful TFTP transfer proves delivery only.

`HC-20` helps reconcile current FortiGuard object versions with the versions recorded in the latest apply report. A failed reconciliation must be investigated rather than hidden by a new transfer or manual retry.

## Security boundary

Daily logs and health reports are runtime data and must remain outside Git. FGOps does not intentionally write plaintext secret values to these records.

They can contain:

- device identity and management address;
- repository/source metadata;
- package versions and filenames;
- archive SHA-256 and manifest IDs;
- evidence, backup, quarantine, and report paths;
- notification status;
- failure details and tracebacks.

Restrict access to the runtime host, apply approved retention, and sanitize files before sharing outside the authorized operations team. Never attach unsanitized production logs or health reports to a public issue or commit them to the repository.
