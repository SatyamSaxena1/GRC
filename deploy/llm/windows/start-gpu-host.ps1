# One click: connect this PC's GPU to the GRC website. No Docker.
#
#   Ollama (loopback only)  ->  token gate on :8088 (only the 2 calls the app makes)  ->  Tailscale Funnel
#
# What it does, in order, and stops with a plain message at the first thing that is missing:
#   1. starts Ollama if it is not running (bound to 127.0.0.1, never your network)
#   2. checks the model is pulled
#   3. starts the gate (rejects requests without your key; reads OLLAMA_API_KEY from deploy\llm\.env)
#   4. starts a thermal guard (unloads the model if the GPU reaches -TripAt degrees C)
#   5. turns on the Tailscale Funnel to the gate and tests the public address end to end
#
#   powershell -ExecutionPolicy Bypass -File start-gpu-host.ps1        (or double-click "Start GRC GPU")
#   ... -Stop        disconnect: funnel off, gate stopped, model unloaded (Ollama itself is left alone)
#
# Nothing here loads the model until the website actually sends it work, so connecting is cool and cheap.
param(
  [switch]$Stop,
  [string]$Model = "qwen2.5vl:7b",
  [int]$GatePort = 8088,
  [int]$TripAt = 90,
  [string]$EnvFile = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $env:LOCALAPPDATA "grc"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$ollama = "http://127.0.0.1:11434"

function Say($m, $c = "Gray") { Write-Host $m -ForegroundColor $c }
function Ok($m)   { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Todo($m) { Write-Host "  [todo] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [stop] $m" -ForegroundColor Red }
function Up($url, $hdr = @{}) { try { Invoke-WebRequest $url -Headers $hdr -TimeoutSec 4 -UseBasicParsing | Out-Null; $true } catch { $false } }
function Code($url, $hdr = @{}) { try { (Invoke-WebRequest $url -Headers $hdr -TimeoutSec 5 -UseBasicParsing).StatusCode } catch { try { [int]$_.Exception.Response.StatusCode } catch { 0 } } }

function Find-Tailscale {
  $c = Get-Command tailscale -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  foreach ($p in @("$env:ProgramFiles\Tailscale\tailscale.exe", "${env:ProgramFiles(x86)}\Tailscale\tailscale.exe")) { if (Test-Path $p) { return $p } }
  return $null
}
function Find-Python {
  foreach ($c in @("python", "$env:USERPROFILE\miniconda3\python.exe", "$env:USERPROFILE\anaconda3\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { & $cmd.Source -c "import fastapi, uvicorn, httpx" 2>$null; if ($LASTEXITCODE -eq 0) { return $cmd.Source } }
  }
  return $null
}
function Read-Key {
  if ($env:OLLAMA_API_KEY) { return $env:OLLAMA_API_KEY }
  $candidates = @($EnvFile, (Join-Path $here "..\.env"), (Join-Path $logDir "llm.env"), "D:\GRC\deploy\llm\.env") | Where-Object { $_ }
  foreach ($f in $candidates) {
    if (Test-Path $f) {
      $line = Select-String -Path $f -Pattern '^\s*OLLAMA_API_KEY\s*=' | Select-Object -First 1
      if ($line) { return ($line.Line -split '=', 2)[1].Trim().Trim('"').Trim("'") }
    }
  }
  return $null
}
function Stop-Mine([string]$pattern) {
  Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like $pattern } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# ------------------------------------------------------------------------------------------ stop
if ($Stop) {
  Say "Disconnecting the GPU from the website..." Cyan
  $ts = Find-Tailscale
  if ($ts) { & $ts funnel --bg "--https=443" off 2>&1 | Out-Null; Ok "Funnel off" }
  Stop-Mine "*ollama_gate.py*"; Ok "gate stopped"
  Stop-Mine "*gpu-thermal-guard.ps1*"; Ok "thermal guard stopped"
  try { Invoke-RestMethod "$ollama/api/generate" -Method Post -Body (@{ model = $Model; keep_alive = 0 } | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 10 | Out-Null; Ok "model unloaded from the GPU" } catch { Say "  (no model was loaded)" }
  Say "Done. Ollama is still running idle (uses no GPU). The website will fall back to its other model server, or queue uploads for review." Green
  exit 0
}

# ------------------------------------------------------------------------------------------ start
Say "Connecting this PC's GPU to the GRC website" Cyan
Say "-----------------------------------------------"

# 1. Ollama
function Ollama-Exposed { [bool](Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in '0.0.0.0', '::' }) }
function Start-OllamaLoopback {
  $exe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
  if (-not $exe) { Fail "Ollama is not installed. Get it from https://ollama.com/download, then run this again."; exit 2 }
  $env:OLLAMA_HOST = "127.0.0.1:11434"; $env:OLLAMA_KEEP_ALIVE = "24h"; $env:OLLAMA_NUM_PARALLEL = "1"; $env:OLLAMA_MAX_LOADED_MODELS = "1"
  Start-Process $exe -ArgumentList "serve" -WindowStyle Hidden | Out-Null
  foreach ($i in 1..30) { Start-Sleep 1; if (Up "$ollama/api/tags") { break } }
}
if (-not (Up "$ollama/api/tags")) { Say "  starting Ollama (loopback only)..."; Start-OllamaLoopback }
if (-not (Up "$ollama/api/tags")) { Fail "Ollama did not start. Open the Ollama app once and try again."; exit 2 }
# Ollama has no login. The Ollama tray app has an 'Expose Ollama to the network' setting that binds it to every
# interface and ignores OLLAMA_HOST, which would let anyone on your network use it and skip the gate. Replace
# such an instance with a loopback-only one (the gate is then the only way in).
Start-Sleep 3     # the tray app starts its own server a moment after ours; let it show itself
if (Ollama-Exposed) {
  Todo "Ollama was listening on ALL network interfaces; restarting it on this PC only"
  Get-Process -Name "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep 2
  Start-OllamaLoopback
  Start-Sleep 4
}
if (Ollama-Exposed) { Todo "Ollama is STILL reachable from your network. Turn off 'Expose Ollama to the network' in the Ollama app's settings, then run this again." }
else { Ok "Ollama is running and reachable only from this PC" }

# 2. model
$have = (Invoke-RestMethod "$ollama/api/tags").models.name
if ($have -notcontains $Model) { Fail "The model '$Model' is not pulled here. Run:  ollama pull $Model"; exit 2 }
Ok "model $Model is available"

# 3. gate
$key = Read-Key
if (-not $key) { Fail "No OLLAMA_API_KEY found (looked in deploy\llm\.env). It must match the key set on Render."; exit 2 }
$py = Find-Python
if (-not $py) { Fail "Python with fastapi, uvicorn and httpx was not found (the repo's environment has them)."; exit 2 }
$gateScript = Join-Path $here "ollama_gate.py"
if (-not (Test-Path $gateScript)) { $gateScript = Join-Path $logDir "ollama_gate.py" }
$gateUrl = "http://127.0.0.1:$GatePort"
if ((Code "$gateUrl/api/tags") -ne 401) {
  Stop-Mine "*ollama_gate.py*"
  $env:OLLAMA_API_KEY = $key
  Start-Process $py -ArgumentList "`"$gateScript`"" -WindowStyle Hidden -RedirectStandardError (Join-Path $logDir "gate.err.log") -RedirectStandardOutput (Join-Path $logDir "gate.out.log") | Out-Null
  foreach ($i in 1..15) { Start-Sleep 1; if ((Code "$gateUrl/api/tags") -eq 401) { break } }
}
$noTok = Code "$gateUrl/api/tags"; $withTok = Code "$gateUrl/api/tags" @{ Authorization = "Bearer $key" }
if ($noTok -ne 401 -or $withTok -ne 200) { Fail "The gate is not behaving (without key: $noTok, with key: $withTok; expected 401 and 200). See $logDir\gate.err.log"; exit 2 }
Ok "gate is up on $gateUrl (401 without your key, 200 with it)"

# 4. thermal guard
$guard = Join-Path $here "gpu-thermal-guard.ps1"
if (-not (Test-Path $guard)) { $guard = Join-Path $logDir "gpu-thermal-guard.ps1" }
Stop-Mine "*gpu-thermal-guard.ps1*"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  Start-Process powershell.exe -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$guard`" -TripAt $TripAt -Model $Model" -WindowStyle Hidden | Out-Null
  Ok "thermal guard watching the GPU (unloads the model at $TripAt C)"
} else { Todo "nvidia-smi not found, so there is no thermal guard on this run" }

# 5. Tailscale Funnel
$ts = Find-Tailscale
if (-not $ts) {
  Todo "Tailscale is not installed on this PC yet (one-time setup):"
  Say "         1. Install it:  winget install --id Tailscale.Tailscale   (or https://tailscale.com/download)"
  Say "         2. Sign in with the same account the website's tunnel used"
  Say "         3. Run this again. The local gate above is ready and waiting."
  exit 3
}
$st = (& $ts status --json 2>$null | ConvertFrom-Json)
if (-not $st -or $st.BackendState -ne "Running") { Todo "Tailscale is installed but not signed in / running. Open it from the tray, sign in, then run this again."; exit 3 }
& $ts funnel --bg $GatePort 2>&1 | Out-Null
$dns = ($st.Self.DNSName).TrimEnd(".")
$public = "https://$dns"
foreach ($i in 1..10) { Start-Sleep 2; if ((Code "$public/api/tags") -eq 401) { break } }
$pubNo = Code "$public/api/tags"; $pubYes = Code "$public/api/tags" @{ Authorization = "Bearer $key" }
if ($pubNo -eq 401 -and $pubYes -eq 200) { Ok "public address works end to end: $public" }
else { Todo "the public address did not answer as expected (no key: $pubNo, key: $pubYes). Funnel may still be enabling, or it is not enabled for this node: https://login.tailscale.com/admin/dns" }

Say ""
Say "CONNECTED. Set this on Render (once, if the address changed):  OLLAMA_BASE_URL = $public" Green
Say "The website can now use this GPU. Close this window any time; use 'Stop GRC GPU' to disconnect." Gray
