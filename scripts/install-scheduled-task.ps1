[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$AgentExecutable,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$ConfigPath,

    [ValidateRange(1, 168)]
    [int]$IntervalHours = 6,

    [string]$TaskName = "FGOps Offline Update Monitor"
)

$ErrorActionPreference = "Stop"
$agent = (Resolve-Path $AgentExecutable).Path
$config = (Resolve-Path $ConfigPath).Path

$action = New-ScheduledTaskAction `
    -Execute $agent `
    -Argument ('--config "{0}" run' -f $config)

# Pass repetition settings when constructing the trigger. On some Windows
# PowerShell 5.1 / ScheduledTasks module versions, the returned CIM instance
# does not expose a mutable Repetition.Interval property.
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 15)

$principal = New-ScheduledTaskPrincipal `
    -UserId "NT AUTHORITY\SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Polls the configured offline FortiGate signature source and prepares new bundles."

if ($PSCmdlet.ShouldProcess($TaskName, "Register scheduled task")) {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Get-ScheduledTask -TaskName $TaskName |
        Select-Object TaskName, State, Description
}
