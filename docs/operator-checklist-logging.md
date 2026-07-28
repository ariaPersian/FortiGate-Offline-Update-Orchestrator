# Operator checklist logging

FGOps writes a second daily UTF-8 journal intended for operators who do not need to interpret structured JSON events or Python tracebacks.

The operator journal supplements the technical runtime log; it does not replace the technical log, apply reports, preflight evidence, manifests, state, or encrypted backups.

## Files

Both logs are written below the configured runtime storage root:

```text
C:\ProgramData\FGOps\logs\fgops-operator-YYYY-MM-DD.log
C:\ProgramData\FGOps\logs\fgops-YYYY-MM-DD.log
```

Use the files as follows:

| File | Audience | Purpose |
|---|---|---|
| `fgops-operator-YYYY-MM-DD.log` | Operations staff | Readable checklist, final status, and suggested action |
| `fgops-YYYY-MM-DD.log` | Technical support | Structured JSON events, result payloads, exception details, and tracebacks |

The operator log uses the same `FGOPS_LOG_RETENTION_DAYS` retention setting as the technical log. Deletion is limited to files matching `fgops-operator-YYYY-MM-DD.log`; it does not remove the technical journal.

## Status symbols

| Symbol | Meaning |
|---|---|
| `⬜` | Planned and not yet completed |
| `🔄` | Currently being processed |
| `✅` | Completed successfully |
| `⚠️` | Completed with a warning or requires operator attention |
| `❌` | Failed |
| `⏭️` | Safely skipped because the step was not required |

The journal is plain UTF-8 text. It does not rely on ANSI terminal colour codes, so the same content remains readable in Notepad, PowerShell, log collectors, and downloaded log files. Emoji appearance depends on the viewer and installed fonts, but the status meaning remains fixed.

## Example cycle

```text
2026-07-28T11:15:00+01:00 run=20260728T111500+0100-pid4216 ========================================================================
2026-07-28T11:15:00+01:00 run=20260728T111500+0100-pid4216 شروع اجرای جدید FGOps | فرمان: cycle | شناسه اجرا: 20260728T111500+0100-pid4216
2026-07-28T11:15:00+01:00 run=20260728T111500+0100-pid4216 فهرست مراحل (ToDo):
2026-07-28T11:15:00+01:00 run=20260728T111500+0100-pid4216   ⬜ [1/12] راه‌اندازی ربات و ایجاد شناسه اجرا
2026-07-28T11:15:00+01:00 run=20260728T111500+0100-pid4216   ⬜ [2/12] بارگذاری و اعتبارسنجی تنظیمات
...
2026-07-28T11:15:01+01:00 run=20260728T111500+0100-pid4216 ✅ [2/12] بارگذاری و اعتبارسنجی تنظیمات — C:\ProgramData\FGOps\config.yml
2026-07-28T11:15:12+01:00 run=20260728T111500+0100-pid4216 ✅ [4/12] بررسی منبع و شناسایی بسته به‌روزرسانی — https://example.invalid/bundle.zip
2026-07-28T11:15:12+01:00 run=20260728T111500+0100-pid4216 ⏭️ [5/12] دانلود، کنترل و آماده‌سازی بسته — بسته از قبل آماده شده و تغییر جدیدی وجود ندارد.
2026-07-28T11:15:12+01:00 run=20260728T111500+0100-pid4216 ⏭️ [7/12] بررسی مجوز اجرای به‌روزرسانی — نسخه جدیدی برای اعمال وجود ندارد.
...
2026-07-28T11:15:12+01:00 run=20260728T111500+0100-pid4216 ✅ نتیجه نهایی: NO_CHANGE | کد خروج: 0
2026-07-28T11:15:12+01:00 run=20260728T111500+0100-pid4216 اقدام پیشنهادی اپراتور: اقدامی لازم نیست؛ بسته جدیدی شناسایی نشده است.
```

For controlled apply, one additional checklist row is added for every package result, for example:

```text
✅ بسته AV: avdb.pkg — Expected object version increased.
⚠️ بسته MMDB: mmdb.pkg — FortiGate completed the transfer; the installed version was already current.
❌ بسته IPS: ipsdb.pkg — Expected object version did not increase.
```

## Follow the operator log

```powershell
$Today = Get-Date -Format "yyyy-MM-dd"
$OperatorLog = "C:\ProgramData\FGOps\logs\fgops-operator-$Today.log"
Get-Content $OperatorLog -Wait
```

Display only warning and failed lines:

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

Find every line for one run identifier:

```powershell
Select-String `
  -Path "C:\ProgramData\FGOps\logs\fgops-operator-*.log" `
  -Pattern "20260728T111500\+0100-pid4216"
```

## Operator response

When the final line is `✅`, no intervention is normally required unless the checklist contains a separate `⚠️` action.

When the final line is `⚠️`, read the suggested action. Common examples include waiting for explicit manifest approval or checking Telegram delivery while the main update operation remains complete.

When the final line is `❌`:

1. identify the checklist row containing `❌`;
2. read the suggested operator action;
3. open the technical log with the same date;
4. search for the same run time, command, manifest ID, package name, or error text;
5. do not retry a controlled apply until the failed safety gate is understood.

A transfer-success message is not proof that a FortiGuard database was activated. The apply report and before/after `diagnose autoupdate versions` evidence remain authoritative.

## Security boundary

Operator logs can include device identity, source URLs, manifest IDs, archive hashes, package filenames, backup paths, report paths, and failure messages. They do not intentionally include plaintext secret values.

Treat both daily logs as sensitive operational records. Keep them outside Git, restrict access to the runtime host, and sanitize them before sharing outside the authorized operations team.
