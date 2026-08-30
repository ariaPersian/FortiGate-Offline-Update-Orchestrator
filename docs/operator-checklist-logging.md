# Operator checklist logging

FGOps v0.5.8 writes a separate daily UTF-8 journal for operators who do not need to interpret structured JSON events or Python tracebacks.

The operator journal supplements the technical runtime log, apply reports, preflight evidence, manifests, lifecycle state, and encrypted backups. It does not replace them.

## Files and responsibilities

Both logs are written below the configured runtime storage root:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

| File | Audience | Purpose |
|---|---|---|
| `fgops-operator-YYYY-MM-DD.log` | Operations staff | Readable checklist, final status, exit code, and suggested action |
| `fgops-YYYY-MM-DD.log` | Technical support | Structured JSON events, result payloads, exception details, and tracebacks |

The operator log should be the first review point. Open the technical log when the operator checklist contains `⚠️` or `❌`, when a suggested action requests technical investigation, or when exact evidence is needed.

## Status symbols

| Symbol | Meaning | Normal operator response |
|---|---|---|
| `⬜` | Planned and not yet completed | Wait for the run to finish |
| `🔄` | Currently being processed | Do not start another run |
| `✅` | Completed successfully | No action unless another row warns |
| `⚠️` | Warning or attention required | Read the detail and suggested action |
| `❌` | Failed | Stop retries and escalate for investigation |
| `⏭️` | Safely skipped because not required | No action |

The journal is plain UTF-8 text and does not depend on ANSI terminal colors. The same content remains readable in Notepad, PowerShell, log collectors, and downloaded files. Emoji appearance depends on the viewer and installed fonts, but the status meaning is fixed.

## Run identifier

Every invocation has a unique identifier similar to:

```text
20260728T111500+0400-pid4216
```

Every operator line contains `run=<identifier>`. Use it to isolate one run when the daily file contains multiple scheduled or foreground executions.

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "20260728T111500\+0400-pid4216"
```

## Example: clean NO_CHANGE cycle

```text
2026-07-28T11:15:00+04:00 run=20260728T111500+0400-pid4216 ========================================================================
2026-07-28T11:15:00+04:00 run=20260728T111500+0400-pid4216 شروع اجرای جدید FGOps | فرمان: cycle | شناسه اجرا: 20260728T111500+0400-pid4216
2026-07-28T11:15:00+04:00 run=20260728T111500+0400-pid4216 فهرست مراحل (ToDo):
2026-07-28T11:15:00+04:00 run=20260728T111500+0400-pid4216   ⬜ [1/12] راه‌اندازی ربات و ایجاد شناسه اجرا
2026-07-28T11:15:00+04:00 run=20260728T111500+0400-pid4216   ⬜ [2/12] بارگذاری و اعتبارسنجی تنظیمات
...
2026-07-28T11:15:01+04:00 run=20260728T111500+0400-pid4216 ✅ [2/12] بارگذاری و اعتبارسنجی تنظیمات — C:\ProgramData\FGOps\config.yml
2026-07-28T11:15:12+04:00 run=20260728T111500+0400-pid4216 ✅ [4/12] بررسی منبع و شناسایی بسته به‌روزرسانی — https://example.invalid/bundle.zip
2026-07-28T11:15:12+04:00 run=20260728T111500+0400-pid4216 ⏭️ [5/12] دانلود، کنترل و آماده‌سازی بسته — بسته از قبل آماده شده و تغییر جدیدی وجود ندارد.
2026-07-28T11:15:12+04:00 run=20260728T111500+0400-pid4216 ⏭️ [7/12] بررسی مجوز اجرای به‌روزرسانی — نسخه جدیدی برای اعمال وجود ندارد.
...
2026-07-28T11:15:12+04:00 run=20260728T111500+0400-pid4216 ✅ نتیجه نهایی: NO_CHANGE | کد خروج: 0
2026-07-28T11:15:12+04:00 run=20260728T111500+0400-pid4216 اقدام پیشنهادی اپراتور: اقدامی لازم نیست؛ بسته جدیدی شناسایی نشده است.
```

`NO_CHANGE` is a normal successful monitoring result. Apply-only steps are shown as `⏭️` because no new archive required device changes.

## Example: approval required

In `execution.mode=approval`, a prepared archive is not applied automatically. The checklist records the execution gate as a warning and tells the operator what to review next.

```text
✅ دانلود، کنترل و آماده‌سازی بسته — Manifest=FGOPS-0123456789ABCDEF | SHA-256=...
⚠️ بررسی مجوز اجرای به‌روزرسانی — بسته آماده است و در انتظار تایید اپراتور قرار دارد.
⏭️ تهیه نسخه پشتیبان رمزگذاری‌شده — عملیات اعمال اجرا نشد.
⚠️ نتیجه نهایی: PREPARED | کد خروج: 0
اقدام پیشنهادی اپراتور: Manifest آماده‌شده را بررسی و فقط در صورت تایید، فرمان approve را اجرا کنید.
```

This is an expected waiting condition. Do not treat it as a technical failure, and do not approve a manifest without reviewing the source, package list, target, and maintenance authorization.

## Package-level rows

Controlled apply and approval runs add one checklist row for every package result.

```text
✅ بسته AV: avdb.pkg — Expected object version increased.
⚠️ بسته MMDB: mmdb.pkg — FortiGate completed the transfer; the installed version was already current.
❌ بسته IPS: ipsdb.pkg — Expected object version did not increase.
```

Interpretation:

- `✅` means the expected object version increased.
- `⚠️` can mean the package was already current or completed with a non-blocking warning.
- `❌` means activation failed or could not be confirmed. Do not retry until the technical evidence is reviewed.

A successful TFTP transfer alone is not proof of database activation. The apply report and before/after `diagnose autoupdate versions` evidence remain authoritative.

## Daily operator procedure

1. Confirm the Scheduled Task completed and note `LastTaskResult`.
2. Open today's operator log.
3. Find the most recent `نتیجه نهایی:` line.
4. Review any `⚠️` or `❌` rows within the same run identifier.
5. Follow the recorded operator action.
6. Open the technical log only when more detail is required.
7. Do not manually rerun a failed apply without technical approval.

```powershell
Get-ScheduledTaskInfo -TaskName "FGOps Offline Update Monitor" |
  Format-List LastRunTime,LastTaskResult,NextRunTime

$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"
Get-Content $OperatorLog -Tail 150
```

## Quick decision table

| Final marker/result | Meaning | Required action |
|---|---|---|
| `✅ NO_CHANGE` | Source checked; no new archive | None |
| `✅ NO_CONTENT_CHANGE` | ZIP bytes changed, but the enabled payload was already applied | None; device-changing steps were skipped |
| `✅ NO_UPDATE` | Controlled apply confirmed every enabled package was already current | None; do not repeat the apply |
| `✅ SUCCESS` | Apply and verification completed | Retain reports and continue monitoring |
| `⚠️ SUCCESS_WITH_WARNING` | Safe completion with package or FortiOS warning | Review warning rows and report |
| `⚠️ PREPARED` | Package is waiting for explicit approval | Follow the approval procedure |
| `⚠️ ...NOTIFICATION_ERROR` | Main operation completed but Telegram delivery failed | Check notification configuration |
| `❌ FAILED` | Mandatory gate, backup, package, or verification failed | Disable scheduling and escalate |
| No final line and last row is `🔄` | Run may still be active or terminated unexpectedly | Check Task state and technical log before retrying |

## PowerShell review commands

Follow the operator log:

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"
Get-Content $OperatorLog -Wait
```

Display only warnings and failures:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "⚠️|❌"
```

Display final results:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "نتیجه نهایی:"
```

Display suggested actions:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "اقدام پیشنهادی اپراتور:"
```

## Failure response

When the final line is `❌`:

1. Disable the Scheduled Task.
2. Do not run `cycle`, `approve`, or `apply` again immediately.
3. Identify the first checklist row containing `❌`.
4. Record the run identifier, command, manifest ID, and package name when available.
5. Open the technical log with the same date.
6. Preserve the related apply report, preflight/postflight evidence, encrypted backup, state file, and quarantine directory.
7. Escalate the evidence to technical support.
8. Re-enable scheduling only after a reviewed successful foreground result.

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"

$Today = Get-Date -Format "yyyy-MM-dd"
Get-Content "C:\ProgramData\FGOps\logs\fgops-$Today.log" -Tail 200
```

## Source retry visibility

A recovered transient page-fetch or bundle-download failure can finish with a normal successful operator result. Retry details are written as `source.retrying` events in the technical journal. A retry warning does not authorize a manual second run and does not indicate that SSH, backup, TFTP, or restore has started.

If the operator run finishes with `❌`, use the run time and command to locate the matching technical `command.failed` event. See [Source bundle ingestion](source-bundle-ingestion.md) for the connectivity and inventory decision table.

## Missing operator log after upgrade

The operator journal is created by the installed `fgops-agent` console entry point. If the technical log exists but `fgops-operator-YYYY-MM-DD.log` is not created after upgrading, reinstall the local package. The current expected version is `0.5.8`:

```powershell
Disable-ScheduledTask -TaskName "FGOps Offline Update Monitor"
Set-Location C:\FGOps

& C:\FGOps\venv\Scripts\python.exe `
  -m pip install --upgrade --force-reinstall --no-deps C:\FGOps

& C:\FGOps\venv\Scripts\fgops-agent.exe `
  --config C:\ProgramData\FGOps\config.yml `
  status
```

Then confirm the installed version and both files:

```powershell
& C:\FGOps\venv\Scripts\python.exe -m pip show fgops

$Today = Get-Date -Format "yyyy-MM-dd"
Get-Item `
  "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log", `
  "C:\ProgramData\FGOps\logs\fgops-$Today.log"
```

## Retention

The operator log uses the same `FGOPS_LOG_RETENTION_DAYS` setting as the technical log. Deletion is limited to files matching `fgops-operator-YYYY-MM-DD.log`; it does not remove the technical journal.

```powershell
[Environment]::SetEnvironmentVariable(
  "FGOPS_LOG_RETENTION_DAYS",
  "30",
  "Machine"
)
```

## Security boundary

Operator logs can include device identity, source URLs, manifest IDs, archive hashes, package filenames, backup paths, report paths, notification status, and failure messages. They do not intentionally include plaintext secret values.

Treat both daily logs as sensitive operational records. Keep them outside Git, restrict access to the runtime host, and sanitize them before sharing outside the authorized operations team.
