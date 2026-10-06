# Makes keep-model-loaded.ps1 start (hidden) every time you log in, and starts it now.
# Per-user and needs no admin rights: it uses the HKCU "Run" key, not Task Scheduler (which some
# locked-down Windows setups will not let you run programs from; see the README).
# The script is copied to %LOCALAPPDATA%\grc so this does not depend on where this repo lives.
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\install-keep-model-loaded.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\install-keep-model-loaded.ps1 -Remove
param([string]$Model = "google/gemma-4-e4b", [int]$Context = 16384, [switch]$Remove)
$name = "GRC keep model loaded"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$dest = Join-Path $env:LOCALAPPDATA "grc"
$ps1 = Join-Path $dest "keep-model-loaded.ps1"
$vbs = Join-Path $dest "keep-model-loaded.vbs"

function Stop-Running {
  # only processes whose command line is THIS script, never anything else
  Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -like "*$ps1*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if ($Remove) {
  Remove-ItemProperty -Path $runKey -Name $name -ErrorAction SilentlyContinue
  Stop-Running
  Remove-Item $vbs -ErrorAction SilentlyContinue
  Write-Host "Removed '$name' from login and stopped it." -ForegroundColor Green
  exit 0
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "keep-model-loaded.ps1") $ps1 -Force

# A .vbs launcher so no console window flashes at login (powershell -WindowStyle Hidden still shows one briefly).
$cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """"$ps1"""" -Model """"$Model"""" -Context $Context"
Set-Content -Path $vbs -Encoding ASCII -Value @(
  "' Starts keep-model-loaded.ps1 with no visible window. Installed by install-keep-model-loaded.ps1.",
  "CreateObject(""WScript.Shell"").Run ""$cmd"", 0, False")
Set-ItemProperty -Path $runKey -Name $name -Value "wscript.exe `"$vbs`""

Stop-Running                               # replace an older copy instead of stacking a second one
Start-Process wscript.exe -ArgumentList "`"$vbs`""
Write-Host "Installed '$name': starts at every login, and is running now. Log: $dest\keep-model-loaded.log" -ForegroundColor Green
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File $($MyInvocation.MyCommand.Path) -Remove"
