# Protects the GPU while it serves the website. Polls the temperature twice a second and, at -TripAt degrees C,
# unloads the Ollama model and (if the GPU is still that hot 3 s later) ends Ollama's model-runner process, so
# generation actually stops. The owner's ceiling is 93 C and a poll can overshoot by 2-3 C, so the default trip
# is 90. After a trip it waits for the card to cool below -ResumeBelow before it will act again.
#
# Started by start-gpu-host.ps1; it only ever (a) unloads a model and (b) stops Ollama's own *runner* child.
# The website sees a failed call during that moment and falls back to its other model server, or queues for review.
param(
  [int]$TripAt = 90,
  [int]$ResumeBelow = 75,
  [string]$Model = "qwen2.5vl:7b",
  [string]$Ollama = "http://127.0.0.1:11434",
  [double]$PollSec = 0.5,
  [string]$LogFile = (Join-Path $env:LOCALAPPDATA "grc\gpu-thermal-guard.log")
)
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
function Log($m) {
  if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 256KB)) { Move-Item $LogFile "$LogFile.old" -Force }
  Add-Content $LogFile ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m)
}
function Temp {
  try { return [int](((& nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>$null) -split "`n")[0].Trim()) } catch { return $null }
}
Log "guard started: trip at $TripAt C, resume below $ResumeBelow C"
$peak = 0
while ($true) {
  $t = Temp
  if ($t -ne $null) {
    if ($t -gt $peak) { $peak = $t }
    if ($t -ge $TripAt) {
      Log "TRIP at $t C: unloading $Model"
      try { Invoke-RestMethod "$Ollama/api/generate" -Method Post -Body (@{ model = $Model; keep_alive = 0 } | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 5 | Out-Null } catch { Log "unload call failed: $($_.Exception.Message)" }
      Start-Sleep -Seconds 3
      $t2 = Temp
      if ($t2 -ne $null -and $t2 -ge ($TripAt - 2)) {
        # still hot: the in-flight request is still grinding. End Ollama's runner child (not the server).
        $runners = Get-CimInstance Win32_Process | Where-Object { $_.Name -like "ollama*" -and $_.CommandLine -match "runner" }
        foreach ($r in $runners) { Log "still $t2 C: ending Ollama runner pid $($r.ProcessId)"; Stop-Process -Id $r.ProcessId -Force -ErrorAction SilentlyContinue }
      }
      while (($t3 = Temp) -ne $null -and $t3 -gt $ResumeBelow) { Start-Sleep -Seconds 2 }
      Log "cooled to $t3 C; peak this session $peak C; watching again"
    }
  }
  Start-Sleep -Milliseconds ([int]($PollSec * 1000))
}
