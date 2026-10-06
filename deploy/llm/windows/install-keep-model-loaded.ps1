# Registers keep-model-loaded.ps1 to start (hidden) every time you log in, and starts it now.
# Runs as YOU, not as SYSTEM: the LM Studio CLI and LM Link are per-user.
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\install-keep-model-loaded.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\install-keep-model-loaded.ps1 -Remove
param([string]$Model = "google/gemma-4-e4b", [int]$Context = 16384, [switch]$Remove)
$name = "GRC keep model loaded"
if ($Remove) {
  Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed '$name'." -ForegroundColor Green
  exit 0
}
$script = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "keep-model-loaded.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Model `"$Model`" -Context $Context"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
  -Description "Reloads the LM Studio model if LM Link drops it (see deploy/llm/windows/keep-model-loaded.ps1)" -Force | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "Installed '$name' and started it. Log: $env:LOCALAPPDATA\grc\keep-model-loaded.log" -ForegroundColor Green
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File $($MyInvocation.MyCommand.Path) -Remove"
