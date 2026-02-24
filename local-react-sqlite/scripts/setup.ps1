$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$Venv = Join-Path $Backend '.venv'

python -m venv $Venv
& (Join-Path $Venv 'Scripts\python.exe') -m pip install --upgrade pip
& (Join-Path $Venv 'Scripts\pip.exe') install -r (Join-Path $Backend 'requirements.txt')

Push-Location $Frontend
npm install
Pop-Location

Write-Host ''
Write-Host 'Setup complete.'
Write-Host "Run backend: $Venv\Scripts\uvicorn.exe main:app --reload --host 127.0.0.1 --port 8000 --app-dir $Backend"
Write-Host "Run frontend: cd $Frontend; npm run dev"
