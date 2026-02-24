$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Venv = Join-Path $Backend '.venv'
$Uvicorn = Join-Path $Venv 'Scripts\uvicorn.exe'

if (-not (Test-Path $Uvicorn)) {
  Write-Error "Backend venv not found. Run .\scripts\setup.ps1 first."
}

if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
  Write-Error "Frontend dependencies not found. Run .\scripts\setup.ps1 first."
}

Write-Host 'Starting backend on http://127.0.0.1:8000 ...'
$backendProc = Start-Process -FilePath $Uvicorn `
  -ArgumentList "main:app --reload --host 127.0.0.1 --port 8000 --app-dir `"$Backend`"" `
  -PassThru

Write-Host 'Starting frontend on http://127.0.0.1:5173 ...'
$frontendProc = Start-Process -FilePath 'npm' `
  -ArgumentList 'run dev -- --host 127.0.0.1 --port 5173' `
  -WorkingDirectory $Frontend `
  -PassThru

Write-Host "Backend PID: $($backendProc.Id)"
Write-Host "Frontend PID: $($frontendProc.Id)"
Write-Host 'Press Ctrl+C to stop both.'

try {
  while (-not $backendProc.HasExited -and -not $frontendProc.HasExited) {
    Start-Sleep -Seconds 1
    $backendProc.Refresh()
    $frontendProc.Refresh()
  }
}
finally {
  if (-not $backendProc.HasExited) { Stop-Process -Id $backendProc.Id -Force }
  if (-not $frontendProc.HasExited) { Stop-Process -Id $frontendProc.Id -Force }
}
