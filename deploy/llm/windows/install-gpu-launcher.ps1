# Installs the click-to-connect launcher: copies the scripts to %LOCALAPPDATA%\grc (so they do not depend on where
# this repo lives) and puts two shortcuts on your Desktop: "Start GRC GPU" and "Stop GRC GPU". Needs no admin rights.
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\install-gpu-launcher.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\install-gpu-launcher.ps1 -Remove
param([switch]$Remove)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $env:LOCALAPPDATA "grc"
$desktop = [Environment]::GetFolderPath("Desktop")
$links = @{ "Start GRC GPU.lnk" = ""; "Stop GRC GPU.lnk" = "-Stop" }

if ($Remove) {
  foreach ($n in $links.Keys) { Remove-Item (Join-Path $desktop $n) -ErrorAction SilentlyContinue }
  foreach ($f in "start-gpu-host.ps1", "gpu-thermal-guard.ps1", "ollama_gate.py") { Remove-Item (Join-Path $dest $f) -ErrorAction SilentlyContinue }
  Write-Host "Removed the shortcuts and the copied scripts." -ForegroundColor Green
  exit 0
}

New-Item -ItemType Directory -Force -Path $dest | Out-Null
foreach ($f in "start-gpu-host.ps1", "gpu-thermal-guard.ps1", "ollama_gate.py") { Copy-Item (Join-Path $here $f) (Join-Path $dest $f) -Force }

$shell = New-Object -ComObject WScript.Shell
foreach ($n in $links.Keys) {
  $lnk = $shell.CreateShortcut((Join-Path $desktop $n))
  $lnk.TargetPath = "powershell.exe"
  # -NoExit keeps the window open so you can read what happened (and what is still to do)
  $lnk.Arguments = "-NoProfile -NoExit -ExecutionPolicy Bypass -File `"$(Join-Path $dest 'start-gpu-host.ps1')`" $($links[$n])".Trim()
  $lnk.WorkingDirectory = $dest
  $lnk.WindowStyle = 1
  $lnk.Description = if ($links[$n]) { "Disconnect this PC's GPU from the GRC website" } else { "Connect this PC's GPU to the GRC website" }
  $lnk.Save()
}
Write-Host "Installed. Desktop shortcuts: 'Start GRC GPU' and 'Stop GRC GPU'. Scripts: $dest" -ForegroundColor Green
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File $($MyInvocation.MyCommand.Path) -Remove"
