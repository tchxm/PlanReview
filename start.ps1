# Starts the FastAPI backend only (API + /docs) on loopback. It does not need web/dist.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "Missing .venv. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt" }
& $py -m uvicorn engine.api:app --host 127.0.0.1 --port 8000
