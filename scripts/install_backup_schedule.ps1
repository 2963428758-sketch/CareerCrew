[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "CareerCrew-Backup",
    [ValidatePattern("^([01][0-9]|2[0-3]):[0-5][0-9]$")]
    [string]$DailyTime = "02:00",
    [ValidateRange(1, 3650)]
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"

$resolvedRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
if (-not (Test-Path -LiteralPath $resolvedRoot -PathType Container)) {
    throw "RepositoryRoot does not exist: $resolvedRoot"
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $resolvedPython = $pythonCommand.Source
} else {
    $resolvedPython = [System.IO.Path]::GetFullPath($PythonPath)
}
if (-not (Test-Path -LiteralPath $resolvedPython -PathType Leaf)) {
    throw "Python executable does not exist: $resolvedPython"
}

$backupScript = Join-Path $resolvedRoot "scripts\backup_restore.py"
if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) {
    throw "Backup script does not exist: $backupScript"
}

$at = [datetime]::ParseExact($DailyTime, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
$escapedScript = $backupScript.Replace('"', '\"')
$action = New-ScheduledTaskAction `
    -Execute $resolvedPython `
    -Argument "-u `"$escapedScript`" create --retention-days $RetentionDays" `
    -WorkingDirectory $resolvedRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $at

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Description "CareerCrew PostgreSQL/Qdrant/upload backup" `
    -Force | Out-Null

Write-Output "Registered $TaskName at $DailyTime daily; retention ${RetentionDays} days."
