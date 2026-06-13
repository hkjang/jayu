param(
    [string]$TaskName = "Stock_Jayu_Simulation",
    [string]$Command = "simulate --notify",
    [int[]]$Hours = @(0, 4, 8, 12, 16, 20)
)

# Register the Jayu CLI with Windows Task Scheduler.

$ErrorActionPreference = "Stop"
$WorkDir = $PSScriptRoot
$JayuPath = Join-Path $WorkDir ".venv\Scripts\jayu.exe"

if (-not (Test-Path -LiteralPath $JayuPath)) {
    throw "Jayu environment not found. Run 'uv sync --frozen' first: $JayuPath"
}

foreach ($ExistingName in @($TaskName, "Stock_Danta_Simulation")) {
    if (Get-ScheduledTask -TaskName $ExistingName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $ExistingName -Confirm:$false
    }
}

$Action = New-ScheduledTaskAction `
    -Execute $JayuPath `
    -Argument $Command `
    -WorkingDirectory $WorkDir

$Triggers = $Hours | Sort-Object -Unique | ForEach-Object {
    if ($_ -lt 0 -or $_ -gt 23) {
        throw "Invalid schedule hour: $_"
    }
    New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($_))
}

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "Jayu strategy research, signal generation, risk gate, and notification"

Write-Host "Registered: $TaskName"
Write-Host "Executable: $JayuPath"
Write-Host "Command: $Command"
Write-Host "Schedule hours: $($Hours -join ', ')"
