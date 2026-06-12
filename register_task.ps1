# register_task.ps1
# Stock auto-trading simulation task scheduler registration

$TaskName = "Stock_Danta_Simulation"
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonPath) {
    $PythonPath = "python"  # PATH에서 찾기 실패 시 기본값
}
$ScriptPath = Join-Path $PSScriptRoot "danta_simulation.py"
$WorkDir = $PSScriptRoot

# Remove existing task
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task: $TaskName"
}

# Define action (Wrapping ScriptPath with escaped quotes for space-safe execution)
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $WorkDir

# Define trigger (Daily, repeating every 4 hours)
$Trigger = New-ScheduledTaskTrigger -Daily -At "12:00 AM"
$Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "12:00 AM").Repetition
$Trigger.Repetition.Interval = "PT4H"
$Trigger.Repetition.Duration = "P1D"

# Define settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register task
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Stock trading danta simulation engine v3 (Every 4 hours)"

Write-Host "Task Scheduler Registration Successful!"
Write-Host "Task Name: $TaskName"
Write-Host "Schedule: Every 4 hours repeating daily"
