<#
.SYNOPSIS
Produces one operator-oriented FGOps health report without applying packages.

.DESCRIPTION
Checks the Windows checkout/runtime, installed package, config/safety policy,
DPAPI secret metadata, Scheduled Task, local state, latest cycle journal,
backup/apply evidence, UDP/69, free space, and a pinned read-only FortiGate
preflight. It never runs cycle, approve, apply, or backup-test.

Reports are saved under C:\ProgramData\FGOps\reports\health.
Exit codes: 0=HEALTHY, 1=WARNING, 2=CRITICAL.
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\FGOps",
    [string]$RuntimeRoot = "C:\ProgramData\FGOps",
    [string]$ConfigPath = "C:\ProgramData\FGOps\config.yml",
    [string]$AgentExecutable = "C:\FGOps\venv\Scripts\fgops-agent.exe",
    [string]$PythonExecutable = "C:\FGOps\venv\Scripts\python.exe",
    [string]$TaskName = "FGOps Offline Update Monitor",
    [string]$ExpectedRemote = "https://github.com/ariaPersian/FortiGate-Offline-Update-Orchestrator-Private.git",
    [int]$MaxBackupAgeDays = 30,
    [double]$MinFreeSpaceGB = 2,
    [switch]$SkipPreflight
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$Checks = New-Object System.Collections.Generic.List[object]
$Values = [ordered]@{
    ReportTime = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    OverallHealth = "UNKNOWN"
    TaskState = "-"
    TaskLastResult = "-"
    TaskLastRunTime = "-"
    TaskNextRunTime = "-"
    SourceVersion = "-"
    InstalledVersion = "-"
    ExecutionMode = "-"
    EnabledPackages = "-"
    StateLastResult = "-"
    UnresolvedStateCount = 0
    LatestCycleResult = "-"
    LatestCycleAction = "-"
    LatestBackup = "-"
    LatestBackupAgeDays = "-"
    LatestApplyStatus = "-"
    LatestManifestId = "-"
    FortiGatePreflight = if ($SkipPreflight) { "SKIPPED" } else { "-" }
    FortiGateIdentity = "-"
    VersionVerification = if ($SkipPreflight) { "SKIPPED" } else { "-" }
    HealthReportText = "-"
    HealthReportJson = "-"
}

function Add-Check {
    param(
        [string]$Id,
        [string]$Name,
        [ValidateSet("PASS", "WARN", "FAIL", "INFO")][string]$Status,
        [string]$Value,
        [string]$Action = ""
    )
    $Checks.Add([pscustomobject]@{ Id=$Id; Name=$Name; Status=$Status; Value=$Value; Action=$Action }) | Out-Null
}

function Invoke-AgentJson {
    param([string[]]$Arguments)
    if (-not (Test-Path -LiteralPath $AgentExecutable -PathType Leaf)) {
        return [pscustomobject]@{ Ok=$false; Code=$null; Data=$null; Text="Missing agent: $AgentExecutable" }
    }
    $Output = @(& $AgentExecutable @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    $Code = $LASTEXITCODE
    $Text = ($Output -join [Environment]::NewLine).Trim()
    if ($Code -ne 0) { return [pscustomobject]@{ Ok=$false; Code=$Code; Data=$null; Text=$Text } }
    try {
        return [pscustomobject]@{ Ok=$true; Code=0; Data=($Text | ConvertFrom-Json -ErrorAction Stop); Text=$Text }
    } catch {
        return [pscustomobject]@{ Ok=$false; Code=0; Data=$null; Text="Invalid JSON output: $Text" }
    }
}

function Invoke-ReadOnlyPreflight {
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
        return [pscustomobject]@{ Ok=$false; Data=$null; Text="Missing Python: $PythonExecutable" }
    }
    $Code = @'
import json, sys
from fgops.agent_config import load_agent_config
from fgops.runtime_policy import load_runtime_policy
from fgops.secret_store import secret_environment
from fgops.fortigate_preflight import run_read_only_preflight
cfg = load_agent_config(sys.argv[1])
if cfg.device is None:
    raise ValueError("Device configuration is required.")
policy = load_runtime_policy(cfg.config_path, cfg.storage.root)
names = []
if cfg.device.key_file is None and cfg.device.password_env:
    names.append(cfg.device.password_env)
elif cfg.device.key_file is not None and cfg.device.key_passphrase_env:
    names.append(cfg.device.key_passphrase_env)
with secret_environment(policy.secret_store, tuple(names)):
    result = run_read_only_preflight(cfg)
print(json.dumps(result.to_dict(), ensure_ascii=False))
'@
    $Output = @(& $PythonExecutable -c $Code $ConfigPath 2>&1 | ForEach-Object { $_.ToString() })
    $ExitCode = $LASTEXITCODE
    $Text = ($Output -join [Environment]::NewLine).Trim()
    if ($ExitCode -ne 0) { return [pscustomobject]@{ Ok=$false; Data=$null; Text=$Text } }
    try {
        return [pscustomobject]@{ Ok=$true; Data=($Text | ConvertFrom-Json -ErrorAction Stop); Text=$Text }
    } catch {
        return [pscustomobject]@{ Ok=$false; Data=$null; Text="Invalid preflight JSON: $Text" }
    }
}

function Get-LatestCycleResult {
    $LogDir = Join-Path $RuntimeRoot "logs"
    if (-not (Test-Path -LiteralPath $LogDir -PathType Container)) { return $null }
    $Files = @(Get-ChildItem -LiteralPath $LogDir -Filter "fgops-operator-*.log" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 7)
    if ($Files.Count -eq 0) { return $null }
    $Lines = New-Object System.Collections.Generic.List[string]
    foreach ($File in ($Files | Sort-Object LastWriteTime)) {
        foreach ($Line in (Get-Content -LiteralPath $File.FullName -ErrorAction SilentlyContinue)) { $Lines.Add([string]$Line) | Out-Null }
    }
    $Starts = @($Lines | Where-Object { $_ -match "فرمان:\s*cycle" })
    if ($Starts.Count -eq 0) { return $null }
    $Match = [regex]::Match($Starts[-1], "run=([^\s]+)")
    if (-not $Match.Success) { return $null }
    $RunId = $Match.Groups[1].Value
    $RunLines = @($Lines | Where-Object { $_ -match ("run=" + [regex]::Escape($RunId) + "(?:\s|$)") })
    $Final = @($RunLines | Where-Object { $_ -match "نتیجه نهایی:" } | Select-Object -Last 1)
    $Action = @($RunLines | Where-Object { $_ -match "اقدام پیشنهادی اپراتور:" } | Select-Object -Last 1)
    $Status = $null
    if ($Final.Count -gt 0) {
        $StatusMatch = [regex]::Match($Final[0], "نتیجه نهایی:\s*([A-Z0-9_]+)")
        if ($StatusMatch.Success) { $Status = $StatusMatch.Groups[1].Value }
    }
    $ActionText = "-"
    if ($Action.Count -gt 0) {
        $Index = $Action[0].IndexOf("اقدام پیشنهادی اپراتور:")
        if ($Index -ge 0) { $ActionText = $Action[0].Substring($Index + "اقدام پیشنهادی اپراتور:".Length).Trim() }
    }
    return [pscustomobject]@{ RunId=$RunId; HasFinal=($Final.Count -gt 0); Status=$Status; Action=$ActionText }
}

function Compare-FortiVersion {
    param([string]$Current, [string]$Expected)
    if ($Current -eq $Expected) { return 0 }
    $A = @([regex]::Matches($Current, "\d+") | ForEach-Object { [long]$_.Value })
    $B = @([regex]::Matches($Expected, "\d+") | ForEach-Object { [long]$_.Value })
    if ($A.Count -eq 0 -or $B.Count -eq 0) { return $null }
    $Count = [Math]::Max($A.Count, $B.Count)
    for ($i=0; $i -lt $Count; $i++) {
        $Av = if ($i -lt $A.Count) { $A[$i] } else { 0 }
        $Bv = if ($i -lt $B.Count) { $B[$i] } else { 0 }
        if ($Av -gt $Bv) { return 1 }
        if ($Av -lt $Bv) { return -1 }
    }
    return 0
}

# 1. Elevation and local paths
try {
    $Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Add-Check "HC-01" "PowerShell elevation" "PASS" "Run as Administrator"
    } else {
        Add-Check "HC-01" "PowerShell elevation" "WARN" "Not elevated" "Re-run as Administrator for complete checks."
    }
} catch { Add-Check "HC-01" "PowerShell elevation" "WARN" $_.Exception.Message }

if (Test-Path -LiteralPath $ProjectRoot -PathType Container) { Add-Check "HC-02" "Project root" "PASS" $ProjectRoot }
else { Add-Check "HC-02" "Project root" "FAIL" "Missing: $ProjectRoot" }
if (Test-Path -LiteralPath $AgentExecutable -PathType Leaf) { Add-Check "HC-03" "Agent executable" "PASS" $AgentExecutable }
else { Add-Check "HC-03" "Agent executable" "FAIL" "Missing: $AgentExecutable" }

# 2. Git production checkout
if (Test-Path -LiteralPath $ProjectRoot -PathType Container) {
    try {
        $Origin = (& git -C $ProjectRoot remote get-url origin 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $Origin.TrimEnd('/') -ieq $ExpectedRemote.TrimEnd('/')) { Add-Check "HC-04" "Git origin" "PASS" $Origin }
        else { Add-Check "HC-04" "Git origin" "FAIL" $Origin "Production checkout must use the reviewed private repository." }
    } catch { Add-Check "HC-04" "Git origin" "FAIL" $_.Exception.Message }
    try {
        $Branch = (& git -C $ProjectRoot branch --show-current 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $Branch -eq "main") { Add-Check "HC-05" "Git branch" "PASS" $Branch }
        else { Add-Check "HC-05" "Git branch" "WARN" $Branch }
    } catch { Add-Check "HC-05" "Git branch" "WARN" $_.Exception.Message }
    try {
        $Dirty = @(& git -C $ProjectRoot status --porcelain 2>&1)
        if ($LASTEXITCODE -eq 0 -and $Dirty.Count -eq 0) { Add-Check "HC-06" "Git working tree" "PASS" "Clean" }
        elseif ($LASTEXITCODE -eq 0) { Add-Check "HC-06" "Git working tree" "WARN" ((@($Dirty | Select-Object -First 5) -join "; ")) "Review local changes before upgrade." }
        else { Add-Check "HC-06" "Git working tree" "WARN" ($Dirty -join " ") }
    } catch { Add-Check "HC-06" "Git working tree" "WARN" $_.Exception.Message }
}

# 3. Source vs installed version
$Pyproject = Join-Path $ProjectRoot "pyproject.toml"
if (Test-Path -LiteralPath $Pyproject -PathType Leaf) {
    $M = [regex]::Match((Get-Content -LiteralPath $Pyproject -Raw), '(?m)^version\s*=\s*"([^"]+)"')
    if ($M.Success) { $Values.SourceVersion = $M.Groups[1].Value }
}
if (Test-Path -LiteralPath $PythonExecutable -PathType Leaf) {
    try {
        $Pip = @(& $PythonExecutable -m pip show fgops 2>&1)
        $VersionLine = @($Pip | Where-Object { $_ -match '^Version:\s*' } | Select-Object -First 1)
        if ($VersionLine.Count -gt 0) { $Values.InstalledVersion = ($VersionLine[0] -replace '^Version:\s*', '').Trim() }
        if ($Values.SourceVersion -ne "-" -and $Values.InstalledVersion -eq $Values.SourceVersion) { Add-Check "HC-07" "Installed/source version" "PASS" $Values.InstalledVersion }
        else { Add-Check "HC-07" "Installed/source version" "FAIL" ("installed={0}; source={1}" -f $Values.InstalledVersion,$Values.SourceVersion) "Reinstall the checked-out source into the venv." }
    } catch { Add-Check "HC-07" "Installed/source version" "FAIL" $_.Exception.Message }
} else { Add-Check "HC-07" "Installed/source version" "FAIL" "Missing Python: $PythonExecutable" }

# 4. Config, safe package policy, secret metadata
$ConfigValidation = $null
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $ConfigValidation = Invoke-AgentJson @("--config",$ConfigPath,"validate-config")
    if ($ConfigValidation.Ok -and [bool]$ConfigValidation.Data.valid) {
        $Values.ExecutionMode = [string]$ConfigValidation.Data.execution_mode
        Add-Check "HC-08" "Configuration validation" "PASS" ("mode={0}; device={1}; apply={2}" -f $ConfigValidation.Data.execution_mode,$ConfigValidation.Data.device_configured,$ConfigValidation.Data.apply_configured)
    } else { Add-Check "HC-08" "Configuration validation" "FAIL" $ConfigValidation.Text "Fix config.yml before any apply." }
} else { Add-Check "HC-08" "Configuration validation" "FAIL" "Missing: $ConfigPath" }

$Policy = $null
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf -and Test-Path -LiteralPath $PythonExecutable -PathType Leaf) {
    try {
        $Code = 'import json,sys,yaml; d=yaml.safe_load(open(sys.argv[1],encoding="utf-8")) or {}; e=d.get("execution") or {}; dv=d.get("device") or {}; ap=d.get("apply") or {}; print(json.dumps({"mode":e.get("mode"),"enabled":e.get("enabled_packages") or [],"reject":e.get("reject_unknown_packages"),"downgrade":e.get("prevent_downgrade"),"ssh":dv.get("password_env"),"key_file":dv.get("key_file"),"key_secret":dv.get("key_passphrase_env"),"backup_required":ap.get("require_backup"),"backup_secret":ap.get("backup_password_env")}))'
        $Raw = (& $PythonExecutable -c $Code $ConfigPath 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw $Raw }
        $Policy = $Raw | ConvertFrom-Json
        $Values.ExecutionMode = [string]$Policy.mode
        $Values.EnabledPackages = (@($Policy.enabled) -join ",")
        $Recommended = @("AV","IPS","APDB","MCDB","MMDB")
        $Extra = @($Policy.enabled | Where-Object { $_ -notin $Recommended })
        if ($Policy.reject -eq $true -and $Policy.downgrade -eq $true -and $Extra.Count -eq 0) {
            Add-Check "HC-09" "Execution safety policy" "PASS" ("mode={0}; packages={1}" -f $Policy.mode,$Values.EnabledPackages)
        } else {
            Add-Check "HC-09" "Execution safety policy" "WARN" ("mode={0}; packages={1}; reject_unknown={2}; prevent_downgrade={3}" -f $Policy.mode,$Values.EnabledPackages,$Policy.reject,$Policy.downgrade) "Review allowlist and fail-closed policy."
        }
        $SecretStatus = Invoke-AgentJson @("--config",$ConfigPath,"secret","status")
        if (-not $SecretStatus.Ok) { throw $SecretStatus.Text }
        $Configured = @($SecretStatus.Data.secrets | ForEach-Object { [string]$_.name })
        $Required = New-Object System.Collections.Generic.List[string]
        if ([string]::IsNullOrWhiteSpace([string]$Policy.key_file)) {
            if ($Policy.ssh) { $Required.Add(([string]$Policy.ssh).ToUpperInvariant()) | Out-Null }
        } elseif ($Policy.key_secret) { $Required.Add(([string]$Policy.key_secret).ToUpperInvariant()) | Out-Null }
        if ($Policy.backup_required -eq $true -and $Policy.backup_secret) { $Required.Add(([string]$Policy.backup_secret).ToUpperInvariant()) | Out-Null }
        $Missing = @($Required | Where-Object { $_ -notin $Configured })
        if ($Missing.Count -eq 0) { Add-Check "HC-10" "Secret store readiness" "PASS" ("required={0}" -f ($Required -join ',')) }
        else { Add-Check "HC-10" "Secret store readiness" "FAIL" ("missing={0}" -f ($Missing -join ',')) }
    } catch { Add-Check "HC-09" "Execution safety policy" "WARN" $_.Exception.Message }
}

# 5. Scheduled Task
try {
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $TaskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    $Values.TaskState = [string]$Task.State
    $Values.TaskLastResult = [string]$TaskInfo.LastTaskResult
    $Values.TaskLastRunTime = if ($TaskInfo.LastRunTime) { $TaskInfo.LastRunTime.ToString("yyyy-MM-dd HH:mm:ss") } else { "-" }
    $Values.TaskNextRunTime = if ($TaskInfo.NextRunTime) { $TaskInfo.NextRunTime.ToString("yyyy-MM-dd HH:mm:ss") } else { "-" }
    if ($Task.State -in @("Ready","Running")) { Add-Check "HC-11" "Scheduled Task state" "PASS" ([string]$Task.State) }
    else { Add-Check "HC-11" "Scheduled Task state" "FAIL" ([string]$Task.State) "Do not leave production scheduling disabled unless investigating a failure." }
    if ([int64]$TaskInfo.LastTaskResult -eq 0) { Add-Check "HC-12" "Scheduled Task last result" "PASS" "0" }
    else { Add-Check "HC-12" "Scheduled Task last result" "WARN" ([string]$TaskInfo.LastTaskResult) "Correlate with the latest cycle result." }
    $Action = @($Task.Actions | Select-Object -First 1)
    if ($Action.Count -gt 0 -and [string]$Action[0].Execute -ieq $AgentExecutable -and [string]$Action[0].Arguments -match [regex]::Escape($ConfigPath) -and [string]$Action[0].Arguments -match '(?:^|\s)cycle(?:\s|$)') {
        Add-Check "HC-13" "Scheduled Task action" "PASS" ("{0} {1}" -f $Action[0].Execute,$Action[0].Arguments)
    } else { Add-Check "HC-13" "Scheduled Task action" "FAIL" "Unexpected task action" "Reinstall the FGOps Scheduled Task." }
} catch {
    Add-Check "HC-11" "Scheduled Task state" "FAIL" $_.Exception.Message
    Add-Check "HC-12" "Scheduled Task last result" "INFO" "Unavailable"
    Add-Check "HC-13" "Scheduled Task action" "INFO" "Unavailable"
}

# 6. Agent state and latest scheduled cycle journal
$State = Invoke-AgentJson @("--config",$ConfigPath,"status")
if ($State.Ok) {
    $Values.StateLastResult = if ($State.Data.last_result) { [string]$State.Data.last_result } else { "-" }
    $Unresolved = @()
    if ($State.Data.archives) {
        foreach ($P in $State.Data.archives.PSObject.Properties) {
            if ([string]$P.Value.status -in @("APPLY_FAILED","REVIEW_REQUIRED")) { $Unresolved += ("{0}:{1}" -f $P.Value.status,$P.Name.Substring(0,[Math]::Min(12,$P.Name.Length))) }
        }
    }
    $Values.UnresolvedStateCount = $Unresolved.Count
    if ($Unresolved.Count -eq 0) { Add-Check "HC-14" "Unresolved archive state" "PASS" "0" }
    else { Add-Check "HC-14" "Unresolved archive state" "FAIL" ($Unresolved -join "; ") "Do not run cycle/approve/apply until reviewed." }
    if ($Values.StateLastResult -eq "FAILED") { Add-Check "HC-15" "Agent last result" "FAIL" $Values.StateLastResult }
    elseif ($Values.StateLastResult -match 'WARNING|ERROR|PREPARED') { Add-Check "HC-15" "Agent last result" "WARN" $Values.StateLastResult }
    else { Add-Check "HC-15" "Agent last result" "PASS" $Values.StateLastResult }
} else {
    Add-Check "HC-14" "Unresolved archive state" "FAIL" $State.Text
    Add-Check "HC-15" "Agent last result" "FAIL" "Unavailable"
}

$Cycle = Get-LatestCycleResult
if ($null -eq $Cycle) { Add-Check "HC-16" "Latest cycle result" "WARN" "No recent cycle result found" }
elseif (-not $Cycle.HasFinal) {
    $Values.LatestCycleResult = "INCOMPLETE"
    Add-Check "HC-16" "Latest cycle result" "FAIL" ("run={0}; incomplete" -f $Cycle.RunId) "Check process/Task/TFTP state before retry."
} else {
    $Values.LatestCycleResult = [string]$Cycle.Status
    $Values.LatestCycleAction = [string]$Cycle.Action
    if ($Cycle.Status -eq "FAILED") { Add-Check "HC-16" "Latest cycle result" "FAIL" ("run={0}; result={1}" -f $Cycle.RunId,$Cycle.Status) $Cycle.Action }
    elseif ($Cycle.Status -match 'WARNING|ERROR|PREPARED') { Add-Check "HC-16" "Latest cycle result" "WARN" ("run={0}; result={1}" -f $Cycle.RunId,$Cycle.Status) $Cycle.Action }
    else { Add-Check "HC-16" "Latest cycle result" "PASS" ("run={0}; result={1}" -f $Cycle.RunId,$Cycle.Status) }
}

# 7. Backup and latest apply evidence
$BackupDir = Join-Path $RuntimeRoot "evidence\backups"
$Backup = $null
if (Test-Path -LiteralPath $BackupDir -PathType Container) { $Backup = Get-ChildItem -LiteralPath $BackupDir -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 }
if ($null -eq $Backup) { Add-Check "HC-17" "Latest encrypted backup" "WARN" "No backup found" "Run backup-test during an authorized maintenance check before the next live apply." }
else {
    $Age = [Math]::Round(((Get-Date)-$Backup.LastWriteTime).TotalDays,1)
    $Values.LatestBackup = $Backup.FullName
    $Values.LatestBackupAgeDays = [string]$Age
    if ($Backup.Length -le 0) { Add-Check "HC-17" "Latest encrypted backup" "FAIL" ("{0}; size=0" -f $Backup.FullName) }
    elseif ($Age -gt $MaxBackupAgeDays) { Add-Check "HC-17" "Latest encrypted backup" "WARN" ("{0}; ageDays={1}" -f $Backup.Name,$Age) }
    else { Add-Check "HC-17" "Latest encrypted backup" "PASS" ("{0}; size={1}; ageDays={2}" -f $Backup.Name,$Backup.Length,$Age) }
}

$ReportsDir = Join-Path $RuntimeRoot "reports"
$ApplyFile = $null
$Apply = $null
if (Test-Path -LiteralPath $ReportsDir -PathType Container) { $ApplyFile = Get-ChildItem -LiteralPath $ReportsDir -Filter "*-apply.json" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1 }
if ($null -eq $ApplyFile) { Add-Check "HC-18" "Latest apply report" "INFO" "No apply report found yet" }
else {
    try {
        $Apply = Get-Content -LiteralPath $ApplyFile.FullName -Raw | ConvertFrom-Json -ErrorAction Stop
        $Values.LatestApplyStatus = [string]$Apply.status
        $Values.LatestManifestId = [string]$Apply.manifest_id
        $Packages = @($Apply.packages | ForEach-Object { "{0}={1}" -f $_.kind,$_.status }) -join ","
        if ($Apply.status -eq "FAILED" -or @($Apply.packages | Where-Object { $_.status -in @("FAILED","FAILED_UNCONFIRMED") }).Count -gt 0) { Add-Check "HC-18" "Latest apply report" "FAIL" ("status={0}; manifest={1}; {2}" -f $Apply.status,$Apply.manifest_id,$Packages) }
        elseif ($Apply.status -eq "SUCCESS_WITH_WARNING") { Add-Check "HC-18" "Latest apply report" "WARN" ("status={0}; manifest={1}; {2}" -f $Apply.status,$Apply.manifest_id,$Packages) "Review warning rows; do not repeat an already completed apply." }
        else { Add-Check "HC-18" "Latest apply report" "PASS" ("status={0}; manifest={1}; {2}" -f $Apply.status,$Apply.manifest_id,$Packages) }
    } catch { Add-Check "HC-18" "Latest apply report" "FAIL" $_.Exception.Message }
}

# 8. UDP/69 and disk
try {
    $Udp = @(Get-NetUDPEndpoint -LocalPort 69 -ErrorAction SilentlyContinue)
    if ($Udp.Count -eq 0) { Add-Check "HC-19" "UDP/69 idle" "PASS" "No listener detected" }
    else { Add-Check "HC-19" "UDP/69 idle" "WARN" ((@($Udp | ForEach-Object { "PID=" + $_.OwningProcess }) -join ",")) "Confirm no stale/third-party TFTP listener before apply or backup-test." }
} catch { Add-Check "HC-19" "UDP/69 idle" "WARN" $_.Exception.Message }
try {
    $DriveName = [System.IO.Path]::GetPathRoot($RuntimeRoot).TrimEnd('\').TrimEnd(':')
    $Drive = Get-PSDrive -Name $DriveName -ErrorAction Stop
    $FreeGB = [Math]::Round($Drive.Free/1GB,2)
    if ($FreeGB -lt 1) { Add-Check "HC-20" "Runtime free disk space" "FAIL" ("{0} GB" -f $FreeGB) }
    elseif ($FreeGB -lt $MinFreeSpaceGB) { Add-Check "HC-20" "Runtime free disk space" "WARN" ("{0} GB" -f $FreeGB) }
    else { Add-Check "HC-20" "Runtime free disk space" "PASS" ("{0} GB" -f $FreeGB) }
} catch { Add-Check "HC-20" "Runtime free disk space" "WARN" $_.Exception.Message }

# 9. Pinned read-only FortiGate preflight and current-vs-apply version evidence
$Preflight = $null
if ($SkipPreflight) {
    Add-Check "HC-21" "FortiGate read-only preflight" "INFO" "Skipped by -SkipPreflight"
    Add-Check "HC-22" "Apply/current version verification" "INFO" "Skipped"
} elseif ($ConfigValidation -and $ConfigValidation.Ok -and [bool]$ConfigValidation.Data.device_configured) {
    $PreflightResult = Invoke-ReadOnlyPreflight
    if ($PreflightResult.Ok) {
        $Preflight = $PreflightResult.Data
        $Values.FortiGatePreflight = [string]$Preflight.status
        $S = $Preflight.system_status
        $Values.FortiGateIdentity = ("{0} | {1} | v{2} build{3}" -f $S.hostname,$S.model,$S.firmware_version,$S.build)
        if ($Preflight.status -eq "PASS") { Add-Check "HC-21" "FortiGate read-only preflight" "PASS" $Values.FortiGateIdentity }
        else { Add-Check "HC-21" "FortiGate read-only preflight" "FAIL" ("status={0}; validation={1}; command={2}" -f $Preflight.status,(@($Preflight.validation_errors)-join '; '),(@($Preflight.command_errors)-join '; ')) }
    } else {
        $Values.FortiGatePreflight = "FAILED"
        Add-Check "HC-21" "FortiGate read-only preflight" "FAIL" $PreflightResult.Text "Check pinned host key, credentials, SSH path and target identity."
    }

    if ($null -ne $Apply -and $null -ne $Preflight -and $Preflight.status -eq "PASS") {
        $FailedVersion = New-Object System.Collections.Generic.List[string]
        $UnknownVersion = New-Object System.Collections.Generic.List[string]
        $Verified = 0
        foreach ($Pkg in @($Apply.packages)) {
            foreach ($Obj in @($Pkg.objects)) {
                $Expected = [string]$Obj.after_version
                if ([string]::IsNullOrWhiteSpace($Expected)) { continue }
                $Property = $Preflight.autoupdate_versions.PSObject.Properties[$Obj.name]
                if ($null -eq $Property) { $UnknownVersion.Add(("{0}=missing" -f $Obj.name)) | Out-Null; continue }
                $Current = [string]$Property.Value.Version
                $Compare = Compare-FortiVersion $Current $Expected
                if ($null -eq $Compare) { if ($Current -eq $Expected) { $Verified++ } else { $UnknownVersion.Add(("{0}:{1}!={2}" -f $Obj.name,$Current,$Expected)) | Out-Null } }
                elseif ($Compare -ge 0) { $Verified++ }
                else { $FailedVersion.Add(("{0}:{1}<{2}" -f $Obj.name,$Current,$Expected)) | Out-Null }
            }
        }
        if ($FailedVersion.Count -gt 0) {
            $Values.VersionVerification = "FAILED"
            Add-Check "HC-22" "Apply/current version verification" "FAIL" ($FailedVersion -join "; ") "Current FortiGuard version is older than the latest apply evidence."
        } elseif ($UnknownVersion.Count -gt 0) {
            $Values.VersionVerification = "WARNING"
            Add-Check "HC-22" "Apply/current version verification" "WARN" ("verified={0}; unresolved={1}" -f $Verified,($UnknownVersion -join '; '))
        } else {
            $Values.VersionVerification = "PASS"
            Add-Check "HC-22" "Apply/current version verification" "PASS" ("Verified objects: {0}" -f $Verified)
        }
    } elseif ($null -eq $Apply) {
        $Values.VersionVerification = "NO_APPLY_REPORT"
        Add-Check "HC-22" "Apply/current version verification" "INFO" "No previous apply report to compare"
    } else {
        $Values.VersionVerification = "UNAVAILABLE"
        Add-Check "HC-22" "Apply/current version verification" "WARN" "Unavailable because preflight did not pass"
    }
} else {
    $Values.FortiGatePreflight = "UNAVAILABLE"
    $Values.VersionVerification = "UNAVAILABLE"
    Add-Check "HC-21" "FortiGate read-only preflight" "WARN" "Device not configured or config validation failed"
    Add-Check "HC-22" "Apply/current version verification" "INFO" "Unavailable"
}

# Final classification and persistent report
$FailCount = @($Checks | Where-Object { $_.Status -eq "FAIL" }).Count
$WarnCount = @($Checks | Where-Object { $_.Status -eq "WARN" }).Count
if ($FailCount -gt 0) { $Values.OverallHealth="CRITICAL"; $ExitCode=2 }
elseif ($WarnCount -gt 0) { $Values.OverallHealth="WARNING"; $ExitCode=1 }
else { $Values.OverallHealth="HEALTHY"; $ExitCode=0 }

$HealthDir = Join-Path $ReportsDir "health"
New-Item -ItemType Directory -Path $HealthDir -Force | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$TextReport = Join-Path $HealthDir ("fgops-health-{0}.txt" -f $Stamp)
$JsonReport = Join-Path $HealthDir ("fgops-health-{0}.json" -f $Stamp)
$Values.HealthReportText = $TextReport
$Values.HealthReportJson = $JsonReport

[ordered]@{
    schema_version=1
    captured_at=(Get-Date).ToString("o")
    overall_health=$Values.OverallHealth
    fail_count=$FailCount
    warning_count=$WarnCount
    operator_values=$Values
    checks=@($Checks)
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $JsonReport -Encoding UTF8

$Lines = New-Object System.Collections.Generic.List[string]
$Lines.Add("FGOps HEALTH REPORT") | Out-Null
$Lines.Add(("Generated : {0}" -f $Values.ReportTime)) | Out-Null
$Lines.Add(("Overall   : {0}" -f $Values.OverallHealth)) | Out-Null
$Lines.Add(("Failures  : {0}" -f $FailCount)) | Out-Null
$Lines.Add(("Warnings  : {0}" -f $WarnCount)) | Out-Null
$Lines.Add("") | Out-Null
$Lines.Add("OPERATOR VALUES") | Out-Null
foreach ($Entry in $Values.GetEnumerator()) { $Lines.Add(("{0,-24}: {1}" -f $Entry.Key,$Entry.Value)) | Out-Null }
$Lines.Add("") | Out-Null
$Lines.Add("CHECKS") | Out-Null
foreach ($Check in $Checks) {
    $Lines.Add(("[{0}] {1} {2} - {3}" -f $Check.Status,$Check.Id,$Check.Name,$Check.Value)) | Out-Null
    if ($Check.Action) { $Lines.Add(("       Action: {0}" -f $Check.Action)) | Out-Null }
}
$Lines | Set-Content -LiteralPath $TextReport -Encoding UTF8

Write-Host ""
Write-Host "============================================================"
Write-Host " FGOps Health Report"
Write-Host "============================================================"
Write-Host (" Overall Health : {0}" -f $Values.OverallHealth)
Write-Host (" Failures       : {0}" -f $FailCount)
Write-Host (" Warnings       : {0}" -f $WarnCount)
Write-Host ""
$Checks | Format-Table Id,Status,Name,Value -AutoSize
Write-Host ""
Write-Host "Operator values:"
$Values.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-24}: {1}" -f $_.Key,$_.Value) }
Write-Host ""
Write-Host ("Text report : {0}" -f $TextReport)
Write-Host ("JSON report : {0}" -f $JsonReport)
Write-Host ""
exit $ExitCode
