# Keeps an LM Studio model loaded, so the GRC app's LLM_PROVIDER=openai path has something to talk to.
#
# Why it exists: a model served over LM Link (a model hosted on your other PC) is dropped whenever
# that PC sleeps, restarts or loses the link, and LM Studio's just-in-time loading does NOT bring a
# remote model back - the API just answers "No models loaded" until someone runs `lms load`. This
# does that, as soon as the peer is reachable again, and otherwise stays out of the way.
#
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\keep-model-loaded.ps1
#   ... -Once                      check once, load if missing, exit (testing / a cron-style task)
#   ... -Model google/gemma-4-e4b  (default) -Context 16384  -IntervalSec 30
#
# Install it to run at logon with install-keep-model-loaded.ps1. It only ever runs `lms ps`,
# `lms server status|start` and `lms load` - it never unloads, deletes or downloads anything.
param(
  [string]$Model = "google/gemma-4-e4b",
  [int]$Context = 16384,        # keep in step with LLM_CONTEXT, which the app uses to spot a truncated prompt
  [int]$IntervalSec = 30,
  [int]$MaxBackoffSec = 300,    # while the peer is down, check less and less often
  [int]$TtlSec = 604800,        # idle-unload timer on the load; a week, so "idle" never unloads it in practice
  [switch]$Once,
  [string]$LogFile = (Join-Path $env:LOCALAPPDATA "grc\keep-model-loaded.log")
)
$ErrorActionPreference = "Continue"

$lms = (Get-Command lms -ErrorAction SilentlyContinue).Source
if (-not $lms) { $lms = Join-Path $env:USERPROFILE ".cache\lm-studio\bin\lms.exe" }
if (-not (Test-Path $lms)) { Write-Error "lms (the LM Studio CLI) was not found. Open LM Studio once so it installs it."; exit 2 }

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
function Log([string]$msg) {
  $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  Write-Host $line
  if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 512KB)) { Move-Item $LogFile "$LogFile.old" -Force }
  Add-Content -Path $LogFile -Value $line
}
function IsLoaded { return [bool]((& $lms ps 2>&1 | Out-String) -match [regex]::Escape($Model)) }
function PeerConnected {
  # "Status: connected" under a device; also true when no device is needed because the model is local
  $out = (& $lms link status 2>&1 | Out-String)
  return ($out -match "Status:\s*connected")
}

$wait = $IntervalSec
$lastState = ""
do {
  try {
    if ((& $lms server status 2>&1 | Out-String) -notmatch "(?i)running|ON") {
      Log "LM Studio server is not running; starting it"
      & $lms server start 2>&1 | Out-Null
    }

    if (IsLoaded) {
      if ($lastState -ne "loaded") { Log "$Model is loaded" }
      $lastState = "loaded"; $wait = $IntervalSec
    }
    elseif (-not (PeerConnected)) {
      if ($lastState -ne "peer-down") { Log "$Model is not loaded and the LM Link peer is unreachable; waiting for it (the PC may be off or asleep)" }
      $lastState = "peer-down"; $wait = [Math]::Min($MaxBackoffSec, [Math]::Max($wait * 2, $IntervalSec))
    }
    else {
      Log "$Model is not loaded and the peer is reachable; loading"
      $out = (& $lms load $Model -y -c $Context --ttl $TtlSec 2>&1 | Out-String)
      if (IsLoaded) { Log "loaded $Model"; $lastState = "loaded"; $wait = $IntervalSec }
      elseif (-not (PeerConnected)) {
        # the peer was there a moment ago and went away mid-load: the same outage, not a bad load
        Log "the LM Link peer dropped while loading; waiting for it to come back"
        $lastState = "peer-down"; $wait = [Math]::Min($MaxBackoffSec, [Math]::Max($wait * 2, $IntervalSec))
      }
      else {
        # the end of the output holds the reason; the start is progress-spinner noise
        $clean = (($out -replace '\x1b\[[0-9;?]*[A-Za-z]', '' -replace '[\u2800-\u28FF]', '') -replace '\s+', ' ').Trim()
        Log ("load did not take: " + $clean.Substring([Math]::Max(0, $clean.Length - 200)))
        $lastState = "load-failed"; $wait = [Math]::Min($MaxBackoffSec, [Math]::Max($wait * 2, $IntervalSec))
      }
    }
  } catch { Log "check failed: $($_.Exception.Message)"; $wait = [Math]::Min($MaxBackoffSec, [Math]::Max($wait * 2, $IntervalSec)) }
  if (-not $Once) { Start-Sleep -Seconds $wait }
} while (-not $Once)
