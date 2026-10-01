# Starts the token-checking gate in front of the Ollama already running on this PC.
# Reads OLLAMA_API_KEY from ..\.env without printing it. Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File deploy\llm\windows\start-gate.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $here "..\.env"

if (-not $env:OLLAMA_API_KEY) {
  if (-not (Test-Path $envFile)) { throw "No OLLAMA_API_KEY set and no $envFile. Copy ..\.env.example to ..\.env and set OLLAMA_API_KEY (openssl rand -hex 32)." }
  $line = Select-String -Path $envFile -Pattern '^\s*OLLAMA_API_KEY\s*=' | Select-Object -First 1
  if (-not $line) { throw "OLLAMA_API_KEY is not in $envFile" }
  $env:OLLAMA_API_KEY = ($line.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
}

# Ollama must be reachable here, and must NOT be exposed to the network: this gate is meant to be
# the only way in. (Ollama's "Expose Ollama to the network" setting binds it to 0.0.0.0.)
try { Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5 | Out-Null } catch { throw "Ollama is not answering on 127.0.0.1:11434. Start it first." }
$wide = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in '0.0.0.0', '::' }
if ($wide) { Write-Warning "Ollama is listening on ALL interfaces. Turn off 'Expose Ollama to the network' in its settings and restart it, or the gate can be bypassed." }

Write-Host "Gate on http://127.0.0.1:8088 -> Ollama. Next (once): tailscale funnel --bg 8088" -ForegroundColor Green
python (Join-Path $here "ollama_gate.py")
